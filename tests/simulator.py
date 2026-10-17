"""WattBox device simulator for tests and local development.

Speaks both interfaces a WattBox exposes, modelled on wire captures from real
hardware (see issues #55 and #66):

* The Integration Protocol over telnet, as the 800 series answers it on
  firmware 2.10.0.0: no telnet option negotiation, LF framing, prompts that
  are not followed by a newline, commands that are not echoed, values that
  contain spaces, and unsolicited ``~`` messages pushed after an outlet
  changes state.
* The ``wattbox_info.xml`` / ``control.cgi`` HTTP API of the 150/250/300/700
  series, behind basic auth.

Run standalone to point a development Home Assistant at it::

    python -m tests.simulator --telnet-port 2323 --http-port 8080

The telnet simulator listens on a non-standard port by default; the
integration's config flow derives the port from the connection type, so for
manual testing either run this on 23 (as root) or override ``CONF_PORT`` in a
test.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Final

_LOGGER = logging.getLogger(__name__)

LOGIN_BANNER: Final[bytes] = b"Please Login to Continue\n"
USERNAME_PROMPT: Final[bytes] = b"Username: "
PASSWORD_PROMPT: Final[bytes] = b"Password: "
LOGIN_OK: Final[bytes] = b"Successfully Logged In!\n"
LOGIN_FAILED: Final[bytes] = b"Invalid Login\n"


@dataclass
class SimOutlet:
    """One outlet's state."""

    name: str
    on: bool = True
    # Whether the outlet follows the master switch (HTTP `outlet_method`).
    method: bool = True
    power: float = 10.5
    current: float = 0.09
    voltage: float = 120.1


@dataclass
class SimState:
    """Device state shared by both interfaces."""

    model: str = "WB-800-IPVM-12"
    firmware: str = "2.10.0.0"
    hostname: str = "WattBox-Sim"
    service_tag: str = "ST-SIM0000001"
    username: str = "wattbox"
    password: str = "wattbox"
    has_ups: bool = False
    auto_reboot: bool = False
    cloud: bool = True
    outlets: list[SimOutlet] = field(default_factory=list)

    @classmethod
    def with_outlets(cls, count: int = 12, **kwargs: object) -> SimState:
        """A device with *count* outlets, some with spaces/punctuation in names."""
        names = [
            "Kaleidescape Server",
            "Apple TV 06 Office Wall",
            "Hue Sync Power 1 to 3",
            "Modem",
            "Router (Main)",
        ]
        outlets = [
            SimOutlet(name=names[i] if i < len(names) else f"Outlet {i + 1}")
            for i in range(count)
        ]
        return cls(outlets=outlets, **kwargs)  # type: ignore[arg-type]

    @property
    def total_power(self) -> float:
        return round(sum(o.power for o in self.outlets if o.on), 2)

    @property
    def total_current(self) -> float:
        return round(sum(o.current for o in self.outlets if o.on), 2)


class TelnetSimulator:
    """Integration Protocol server, behaving like an 800 series on fw 2.10.0.0."""

    def __init__(
        self,
        state: SimState,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        max_sessions: int = 4,
        echo: bool = False,
        push_unsolicited: bool = True,
    ) -> None:
        self.state = state
        self.host = host
        self.port = port
        self.max_sessions = max_sessions
        # Real telnet does not echo; SSH does. Left switchable so a client can
        # be tested against both shapes over one transport.
        self.echo = echo
        self.push_unsolicited = push_unsolicited
        self.sessions: set[asyncio.StreamWriter] = set()
        self.total_logins = 0
        self.commands: list[str] = []
        # Requests that answer `#Error`, to model firmware lacking a command.
        self.unsupported: set[str] = set()
        # Requests that never answer, to model a wedged device.
        self.silent: set[str] = set()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        _LOGGER.info("Telnet simulator on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        for writer in list(self.sessions):
            writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def push(self, line: str) -> None:
        """Send an unsolicited line to every session, as the device does."""
        for writer in list(self.sessions):
            writer.write(line.encode() + b"\n")
            with contextlib.suppress(ConnectionError):
                await writer.drain()

    def outlet_status(self) -> str:
        return self._outlet_status()

    async def drop_sessions(self) -> None:
        """Close every session, as a device reboot or idle timeout would."""
        for writer in list(self.sessions):
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        self.sessions.clear()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        if len(self.sessions) >= self.max_sessions:
            # The 800 series refuses sessions beyond its cap by hanging up.
            writer.close()
            return
        self.sessions.add(writer)
        try:
            if not await self._login(reader, writer):
                return
            while line := await reader.readline():
                command = line.decode(errors="replace").strip()
                if not command:
                    continue
                self.commands.append(command)
                if self.echo:
                    writer.write(command.encode() + b"\n")
                if command == "!Exit":
                    break
                if command in self.silent:
                    continue
                for reply in self._respond(command):
                    writer.write(reply.encode() + b"\n")
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.sessions.discard(writer)
            writer.close()

    async def _login(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> bool:
        writer.write(LOGIN_BANNER)
        while True:
            writer.write(USERNAME_PROMPT)
            await writer.drain()
            user = await reader.readline()
            if not user:
                return False
            writer.write(PASSWORD_PROMPT)
            await writer.drain()
            password = await reader.readline()
            if not password:
                return False
            if (
                user.strip().decode() == self.state.username
                and password.strip().decode() == self.state.password
            ):
                writer.write(LOGIN_OK)
                await writer.drain()
                self.total_logins += 1
                return True
            writer.write(LOGIN_FAILED)

    def _outlet_status(self) -> str:
        return ",".join("1" if o.on else "0" for o in self.state.outlets)

    def _respond(self, command: str) -> list[str]:
        s = self.state
        key, _, arg = command.partition("=")
        if command in self.unsupported or key in self.unsupported:
            return ["#Error"]
        if command.startswith("?"):
            value = self._query(key, arg)
            return ["#Error"] if value is None else [f"{key}={value}"]
        if key == "!OutletSet":
            try:
                index_str, action, *_ = arg.split(",")
                outlet = s.outlets[int(index_str) - 1]
            except (ValueError, IndexError):
                return ["#Error"]
            if action == "ON":
                outlet.on = True
            elif action == "OFF":
                outlet.on = False
            elif action == "TOGGLE":
                outlet.on = not outlet.on
            elif action == "RESET":
                outlet.on = True
            else:
                return ["#Error"]
            replies = ["OK"]
            if self.push_unsolicited:
                replies.append(f"~OutletStatus={self._outlet_status()}")
            return replies
        if key == "!AutoReboot":
            s.auto_reboot = arg == "1"
            return ["OK"]
        return ["#Error"]

    def _query(self, key: str, arg: str) -> str | None:
        s = self.state
        match key:
            case "?Model":
                return s.model
            case "?Firmware":
                return s.firmware
            case "?Hostname":
                return s.hostname
            case "?ServiceTag":
                return s.service_tag
            case "?OutletCount":
                return str(len(s.outlets))
            case "?UPSConnection":
                return "1" if s.has_ups else "0"
            case "?AutoReboot":
                return "1" if s.auto_reboot else "0"
            case "?PowerStatus":
                return f"{s.total_current},{s.total_power},120.1,0"
            case "?OutletStatus":
                return self._outlet_status()
            case "?OutletName":
                return ",".join(f"{{{o.name}}}" for o in s.outlets)
            case "?UPSStatus":
                if s.has_ups:
                    return "100,22,Good,False,95,False,False"
                # A unit with no UPS answers with a zeroed tuple, not #Error.
                return "0,0,Good,False,0,False,False"
            case "?OutletPowerStatus":
                try:
                    index = int(arg)
                    o = s.outlets[index - 1]
                except (ValueError, IndexError):
                    return None
                if not o.on:
                    return f"{index},0.00,0.00,{o.voltage}"
                return f"{index},{o.power},{o.current},{o.voltage}"
        return None


class SshSimulator:
    """The Integration Protocol over SSH, built on :class:`TelnetSimulator`.

    SSH authenticates before the channel opens, so there are no in-channel
    prompts. Whether real firmware then announces the login is not known, so
    ``banner`` covers both. Commands are echoed, as a terminal session does.
    """

    def __init__(
        self,
        state: SimState,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        banner: bool = True,
    ) -> None:
        self.core = TelnetSimulator(state, push_unsolicited=True)
        self.state = state
        self.host = host
        self.port = port
        self.banner = banner
        self.sessions = 0
        self._server: object | None = None

    async def start(self) -> None:
        import asyncssh

        state = self.state
        sim = self

        class _Server(asyncssh.SSHServer):
            def begin_auth(self, username: str) -> bool:
                return True

            def password_auth_supported(self) -> bool:
                return True

            def validate_password(self, username: str, password: str) -> bool:
                return username == state.username and password == state.password

        async def _handle(process: asyncssh.SSHServerProcess) -> None:
            sim.sessions += 1
            try:
                if sim.banner:
                    process.stdout.write("Successfully Logged In!\n")
                async for raw in process.stdin:
                    command = raw.strip()
                    if not command:
                        continue
                    sim.core.commands.append(command)
                    process.stdout.write(command + "\n")  # terminal echo
                    if command == "!Exit":
                        break
                    for reply in sim.core._respond(command):
                        process.stdout.write(reply + "\n")
            except (asyncssh.BreakReceived, asyncssh.TerminalSizeChanged):
                pass
            finally:
                sim.sessions -= 1
                process.exit(0)

        self._server = await asyncssh.create_server(
            _Server,
            self.host,
            self.port,
            server_host_keys=[asyncssh.generate_private_key("ssh-ed25519")],
            process_factory=_handle,
            line_editor=False,
        )
        self.port = self._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()  # type: ignore[attr-defined]
            await self._server.wait_closed()  # type: ignore[attr-defined]


def _xml(state: SimState) -> bytes:
    """`wattbox_info.xml` as the 150/250/300/700 series serve it."""
    outlets = state.outlets
    fields = {
        "host_name": state.hostname,
        "hardware_version": state.model,
        "serial_number": state.service_tag,
        "site_ip": "127.0.0.1",
        "connect_status": "1",
        "cloud_status": "1" if state.cloud else "0",
        "auto_reboot": "1" if state.auto_reboot else "0",
        "outlet_name": ",".join(o.name for o in outlets),
        "outlet_status": ",".join("1" if o.on else "0" for o in outlets),
        "outlet_method": ",".join("1" if o.method else "0" for o in outlets),
        "safe_voltage_status": "1",
        # The XML API reports voltage and current in tenths.
        "voltage_value": "1201",
        "current_value": str(round(state.total_current * 10)),
        "power_value": str(round(state.total_power)),
        "hasUPS": "1" if state.has_ups else "0",
        "audible_alarm": "0",
        "battery_test": "0",
        "battery_charge": "100" if state.has_ups else "0",
        "battery_health": "1" if state.has_ups else "0",
        "battery_load": "22" if state.has_ups else "0",
        "power_lost": "0",
        "est_run_time": "95" if state.has_ups else "0",
        "mute": "0",
    }
    body = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<request>{body}</request>'.encode()


LOGIN_PAGE: Final[bytes] = (
    b"<html><head><script>window.location.href='/login.htm';</script>"
    b"</head><body></body></html>"
)


class HttpSimulator:
    """Minimal HTTP/1.1 server for the XML API, using only asyncio.

    ``bad_auth`` picks how wrong credentials are answered, since models
    differ: ``"401"`` is a plain challenge, ``"login"`` is a 200 carrying a
    redirect to the login page, and ``"blank"`` is a 200 with an HTML page
    and no recognisable marker at all -- the shape behind #67, where bad
    credentials produced a device with no outlets and no error.
    """

    def __init__(
        self,
        state: SimState,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        bad_auth: str = "401",
    ) -> None:
        self.state = state
        self.host = host
        self.port = port
        self.bad_auth = bad_auth
        self.requests: list[str] = []
        # When set, every request is answered with the login page, as a
        # device whose session has lapsed does.
        self.logged_out = False
        # Answer this many requests with the login page, then recover.
        self.logged_out_requests = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        _LOGGER.info("HTTP simulator on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _authorized(self, headers: dict[str, str]) -> bool:
        expected = base64.b64encode(
            f"{self.state.username}:{self.state.password}".encode()
        ).decode()
        return headers.get("authorization", "") == f"Basic {expected}"

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = (await reader.readline()).decode().strip()
            headers: dict[str, str] = {}
            while (line := await reader.readline()) not in (b"\r\n", b"\n", b""):
                name, _, value = line.decode().partition(":")
                headers[name.strip().lower()] = value.strip()
            if not request_line:
                return
            _method, target, _version = request_line.split(" ", 2)
            self.requests.append(target)
            status, body, ctype = self._route(target, headers)
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n".encode()
                + (
                    b'WWW-Authenticate: Basic realm="WattBox"\r\n'
                    if status.startswith("401")
                    else b""
                )
                + b"\r\n"
                + body
            )
            await writer.drain()
        except (ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    def _route(self, target: str, headers: dict[str, str]) -> tuple[str, bytes, str]:
        path, _, query = target.partition("?")
        if self.logged_out_requests > 0:
            self.logged_out_requests -= 1
            return "200 OK", LOGIN_PAGE, "text/html"
        if self.logged_out:
            return "200 OK", LOGIN_PAGE, "text/html"
        if not self._authorized(headers):
            if self.bad_auth == "login":
                return "200 OK", LOGIN_PAGE, "text/html"
            if self.bad_auth == "blank":
                return "200 OK", b"<html><body>Unauthorized</body></html>", "text/html"
            return "401 Unauthorized", b"", "text/html"
        if path == "/wattbox_info.xml":
            return "200 OK", _xml(self.state), "text/xml"
        if path == "/control.cgi":
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            try:
                index = int(params["outlet"])
                command = int(params["command"])
            except (KeyError, ValueError):
                return "400 Bad Request", b"", "text/html"
            targets = (
                [o for o in self.state.outlets if o.method]
                if index == 0
                else [self.state.outlets[index - 1]]
            )
            for outlet in targets:
                if command == 0:
                    outlet.on = False
                elif command in (1, 3):
                    outlet.on = True
            if command == 4:
                self.state.auto_reboot = True
            elif command == 5:
                self.state.auto_reboot = False
            return "200 OK", _xml(self.state), "text/xml"
        return "404 Not Found", b"", "text/html"


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--telnet-port", type=int, default=2323)
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--outlets", type=int, default=12)
    parser.add_argument("--bad-auth", choices=("401", "login", "blank"), default="401")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    telnet = TelnetSimulator(
        SimState.with_outlets(args.outlets), args.host, args.telnet_port
    )
    http = HttpSimulator(
        SimState.with_outlets(args.outlets, model="WB-300-IP-3"),
        args.host,
        args.http_port,
        bad_auth=args.bad_auth,
    )
    await telnet.start()
    await http.start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())
