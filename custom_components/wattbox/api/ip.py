"""Integration Protocol client, over telnet or SSH.

Replaces pywattbox's scrapli-based driver. scrapli is a screen-scraping
framework built around prompts, and this protocol has none: every exchange is
one line out and one line back. Forcing it through prompt matching is what
broke the 800 series -- the in-channel telnet login timed out, values with
spaces were truncated, and replies were looked up by line number on a
transport that does not echo (#55, #66). scrapli 2 then removed the API
pywattbox was built on altogether (#75).

Telnet needs nothing beyond asyncio streams: the WattBox negotiates no telnet
options and frames everything with ``\\n``. SSH uses asyncssh, imported only
when an SSH device is set up.

One session is kept open per device and reused across polls. A background
task reads it continuously, so unsolicited ``~`` lines are applied as they
arrive and a dropped connection is noticed before the next request is sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from .exceptions import (
    WattBoxAuthError,
    WattBoxCommandError,
    WattBoxConnectionError,
    WattBoxProtocolError,
)
from .models import BaseWattBox, Commands
from .protocol import (
    CMD_EXIT,
    CMD_OUTLET_SET,
    ERROR_REPLY,
    LOGIN_FAILURE,
    LOGIN_SUCCESS,
    PASSWORD_PROMPT,
    REQ_AUTO_REBOOT,
    REQ_FIRMWARE,
    REQ_HOSTNAME,
    REQ_MODEL,
    REQ_OUTLET_COUNT,
    REQ_OUTLET_NAME,
    REQ_OUTLET_POWER_STATUS,
    REQ_OUTLET_STATUS,
    REQ_POWER_STATUS,
    REQ_SERVICE_TAG,
    REQ_UPS_CONNECTION,
    REQ_UPS_STATUS,
    USERNAME_PROMPT,
    LineBuffer,
    Request,
    TelnetFilter,
    parse_flags,
    parse_outlet_names,
    parse_outlet_power,
    parse_power_status,
    parse_ups_status,
    split_unsolicited,
)

if TYPE_CHECKING:
    import asyncssh

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT: Final[float] = 5.0
DEFAULT_CONNECT_TIMEOUT: Final[float] = 10.0

# How long to wait, over SSH, for the device to announce the login. Over SSH
# the transport has already authenticated, and not every firmware says so.
_SSH_BANNER_TIMEOUT: Final[float] = 2.0

# Models whose Integration Protocol has no per-outlet power readings.
_UNMETERED_MODELS: Final[tuple[str, ...]] = ("150", "250")


class _Stream(ABC):
    """A byte stream to the device, whatever carries it."""

    @abstractmethod
    async def read(self) -> bytes:
        """The next chunk; ``b""`` once the device has closed the stream."""

    @abstractmethod
    async def send(self, data: bytes) -> None:
        """Write *data* and wait for it to be accepted."""

    @abstractmethod
    async def close(self) -> None:
        """Close the stream. Must not raise."""


class _TelnetStream(_Stream):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._filter = TelnetFilter()

    async def read(self) -> bytes:
        while True:
            data = await self._reader.read(4096)
            if not data:
                return b""
            payload, replies = self._filter.feed(data)
            if replies:
                self._writer.write(replies)
            if payload:
                return payload

    async def send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(2):
                await self._writer.wait_closed()


class _SshStream(_Stream):
    def __init__(
        self,
        conn: asyncssh.SSHClientConnection,
        stdin: asyncssh.SSHWriter[bytes],
        stdout: asyncssh.SSHReader[bytes],
    ) -> None:
        self._conn = conn
        self._stdin = stdin
        self._stdout = stdout

    async def read(self) -> bytes:
        return await self._stdout.read(4096)

    async def send(self, data: bytes) -> None:
        self._stdin.write(data)
        await self._stdin.drain()

    async def close(self) -> None:
        self._conn.close()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(2):
                await self._conn.wait_closed()


class _ClosedBeforeSend(Exception):
    """The session had already closed; nothing reached the device."""


class _ClosedAfterSend(Exception):
    """The session closed after the request went out, before a reply."""


async def _expect(
    stream: _Stream, buffer: bytes, patterns: list[re.Pattern[bytes]], timeout: float
) -> tuple[int, bytes]:
    """Read until one of *patterns* appears; return its index and what follows.

    The login prompts are not newline terminated, so they are searched for in
    the raw stream rather than read line by line. The earliest match wins.
    """
    async with asyncio.timeout(timeout):
        while True:
            found = [
                (match.start(), index, match.end())
                for index, pattern in enumerate(patterns)
                if (match := pattern.search(buffer))
            ]
            if found:
                _, index, end = min(found)
                return index, buffer[end:]
            chunk = await stream.read()
            if not chunk:
                raise WattBoxConnectionError(
                    "the WattBox closed the connection before logging in; it may "
                    "already have as many sessions open as it allows"
                )
            buffer += chunk


async def _login(
    stream: _Stream, user: str, password: str, timeout: float, *, required: bool
) -> bytes:
    """Answer the in-channel login, returning anything read past it.

    Telnet always presents ``Username:``/``Password:`` prompts. SSH has
    already authenticated, so there the device may announce success, ask
    again in-channel, or say nothing at all -- which ``required`` tolerates.
    """
    try:
        index, rest = await _expect(
            stream, b"", [USERNAME_PROMPT, LOGIN_SUCCESS], timeout
        )
    except TimeoutError:
        if required:
            raise WattBoxConnectionError(
                "the WattBox did not present a login prompt"
            ) from None
        return b""
    if index == 1:
        return rest

    await stream.send(user.encode() + b"\n")
    index, rest = await _expect(
        stream, rest, [PASSWORD_PROMPT, LOGIN_FAILURE, USERNAME_PROMPT], timeout
    )
    if index != 0:
        raise WattBoxAuthError("the WattBox rejected the username")

    await stream.send(password.encode() + b"\n")
    index, rest = await _expect(
        stream, rest, [LOGIN_SUCCESS, LOGIN_FAILURE, USERNAME_PROMPT], timeout
    )
    if index != 0:
        raise WattBoxAuthError("the WattBox rejected the username or password")
    return rest


class _Session:
    """One logged-in connection, read continuously in the background."""

    def __init__(
        self, stream: _Stream, on_push: Callable[[str, str], None], label: str
    ) -> None:
        self._stream = stream
        self._on_push = on_push
        self._label = label
        self._lines = LineBuffer()
        self._replies: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.closed = False

    def start(self, leftover: bytes) -> None:
        # Whatever followed the login banner is the start of the line stream.
        # In practice that is the rest of the "Successfully Logged In!" line,
        # which no request accepts, so it is dropped as stray.
        for line in self._lines.feed(leftover):
            self._dispatch(line)
        self._task = asyncio.create_task(
            self._read_loop(), name=f"wattbox reader {self._label}"
        )

    async def _read_loop(self) -> None:
        try:
            while data := await self._stream.read():
                for line in self._lines.feed(data):
                    self._dispatch(line)
        except (OSError, EOFError) as err:
            _LOGGER.debug("%s: connection lost: %s", self._label, err)
        except Exception:  # noqa: BLE001 - asyncssh raises its own error types
            _LOGGER.debug("%s: connection lost", self._label, exc_info=True)
        finally:
            self.closed = True
            self._replies.put_nowait(None)

    def _dispatch(self, line: str) -> None:
        _LOGGER.debug("%s < %s", self._label, line)
        if (push := split_unsolicited(line)) is not None:
            self._on_push(*push)
        else:
            self._replies.put_nowait(line)

    async def request(self, request: Request, timeout: float) -> str:
        """Send one request and wait for the line that answers it."""
        # Nothing should be waiting: replies are consumed by the request they
        # answer, and a request that gives up closes the session. Anything
        # here is stray (the tail of the login line, say) and is dropped.
        while not self._replies.empty():
            if (stray := self._replies.get_nowait()) is None:
                raise _ClosedBeforeSend
            _LOGGER.debug("%s: dropping stray line %r", self._label, stray)
        if self.closed:
            raise _ClosedBeforeSend

        _LOGGER.debug("%s > %s", self._label, request.command)
        async with asyncio.timeout(timeout):
            try:
                await self._stream.send(request.command.encode() + b"\n")
            except (OSError, EOFError) as err:
                # Some of it may have gone out, so treat it as sent: a query
                # is still retried, a control message is not.
                raise _ClosedAfterSend from err

            while True:
                line = await self._replies.get()
                if line is None:
                    raise _ClosedAfterSend
                if request.accepts(line):
                    return line
                _LOGGER.debug(
                    "%s: ignoring %r while waiting for %s",
                    self._label,
                    line,
                    request.command,
                )

    async def close(self, *, say_goodbye: bool) -> None:
        if say_goodbye and not self.closed:
            # Tells the device to free the session now, rather than when its
            # own idle timeout gets round to it. The 800 series caps sessions.
            with contextlib.suppress(Exception):
                async with asyncio.timeout(1):
                    await self._stream.send(CMD_EXIT.encode() + b"\n")
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        await self._stream.close()
        self.closed = True


class IpWattBox(BaseWattBox):
    """A WattBox driven over the Integration Protocol."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 23,
        transport: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        super().__init__(host, user, password, port)
        if transport is None:
            if port == 22:
                transport = "ssh"
            elif port == 23:
                transport = "telnet"
            else:
                raise ValueError(f"Cannot infer the transport for port {port}")
        if transport not in ("telnet", "ssh"):
            raise ValueError(f"Unknown transport {transport!r}")
        self.transport = transport
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._session: _Session | None = None
        self._lock = asyncio.Lock()

    # Connection management

    async def _open_stream(self) -> _Stream:
        try:
            async with asyncio.timeout(self._connect_timeout):
                if self.transport == "telnet":
                    reader, writer = await asyncio.open_connection(self.host, self.port)
                    return _TelnetStream(reader, writer)
                return await self._open_ssh()
        except TimeoutError as err:
            raise WattBoxConnectionError(
                f"timed out connecting to {self.host}:{self.port}"
            ) from err
        except OSError as err:
            raise WattBoxConnectionError(
                f"cannot connect to {self.host}:{self.port}: {err}"
            ) from err

    async def _open_ssh(self) -> _Stream:
        # Imported here so telnet and HTTP users never load it. The
        # integration pre-imports it off the event loop before getting here.
        import asyncssh

        try:
            conn = await asyncssh.connect(
                self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                # Nothing is read from ~/.ssh: no config, keys, agent or
                # known hosts. That would be blocking I/O in the event loop,
                # and a LAN device's host key cannot be verified anyway.
                config=None,
                client_keys=None,
                agent_path=None,
                known_hosts=None,
                x509_trusted_certs=None,
                preferred_auth="password,keyboard-interactive",
            )
        except asyncssh.PermissionDenied as err:
            raise WattBoxAuthError(
                "the WattBox rejected the SSH login. On the 800 series SSH is "
                "reserved for OvrC; use telnet instead"
            ) from err
        except asyncssh.Error as err:
            raise WattBoxConnectionError(f"SSH error: {err}") from err
        try:
            # A terminal is requested because that is what the device's shell
            # is used to: scrapli asked for one too.
            stdin, stdout, _ = await conn.open_session(term_type="vt100", encoding=None)
        except asyncssh.Error as err:
            conn.close()
            raise WattBoxConnectionError(f"SSH error: {err}") from err
        return _SshStream(conn, stdin, stdout)

    async def _connect(self) -> _Session:
        label = f"{self.host}:{self.port}"
        _LOGGER.debug("%s: connecting over %s", label, self.transport)
        stream = await self._open_stream()
        try:
            leftover = await _login(
                stream,
                self.user,
                self.password,
                self._timeout
                if self.transport == "telnet"
                else min(self._timeout, _SSH_BANNER_TIMEOUT),
                required=self.transport == "telnet",
            )
        except TimeoutError as err:
            await stream.close()
            raise WattBoxConnectionError("timed out logging in") from err
        except BaseException:
            await stream.close()
            raise
        _LOGGER.debug("%s: logged in", label)
        session = _Session(stream, self._handle_push, label)
        session.start(leftover)
        return session

    async def _drop_session(self, *, say_goodbye: bool = False) -> None:
        if (session := self._session) is not None:
            self._session = None
            await session.close(say_goodbye=say_goodbye)

    async def _exchange(self, command: str) -> str:
        """Send *command* and return the value of its reply.

        A request that finds the session already gone is sent again on a new
        one: nothing reached the device. A query whose reused session dies
        before it is answered is retried once too, since asking twice is
        harmless. A control message is never sent twice -- it may well have
        been carried out before the connection broke.

        Raises:
            WattBoxCommandError: the device answered ``#Error``.
            WattBoxConnectionError: no usable reply.
            WattBoxAuthError: a reconnect was refused.
        """
        request = Request(command)
        async with self._lock:
            for attempt in range(2):
                fresh = self._session is None or self._session.closed
                if fresh:
                    await self._drop_session()
                    self._session = await self._connect()
                session = self._session
                assert session is not None
                try:
                    line = await session.request(request, self._timeout)
                except _ClosedBeforeSend:
                    await self._drop_session()
                    if attempt == 0:
                        continue
                    raise WattBoxConnectionError(
                        f"the WattBox closed the connection before {command}"
                    ) from None
                except _ClosedAfterSend:
                    await self._drop_session()
                    if attempt == 0 and not fresh and request.is_query:
                        continue
                    raise WattBoxConnectionError(
                        f"the WattBox closed the connection while answering {command}"
                    ) from None
                except TimeoutError:
                    # A reply may still be on its way. Rather than risk taking
                    # it for the answer to the next request, start clean.
                    await self._drop_session()
                    raise WattBoxConnectionError(f"no reply to {command}") from None
                if line == ERROR_REPLY:
                    raise WattBoxCommandError(
                        f"the WattBox answered {command} with #Error"
                    )
                return request.value(line)
        raise AssertionError("unreachable")

    async def _optional(self, command: str) -> str | None:
        """Like :meth:`_exchange`, but ``None`` where the firmware lacks it."""
        try:
            return await self._exchange(command)
        except WattBoxCommandError:
            _LOGGER.debug("%s: %s is not supported", self.host, command)
            return None

    async def async_close(self) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._lock:
                    await self._drop_session(say_goodbye=True)
        except TimeoutError:
            # Something is holding the lock; close regardless.
            await self._drop_session()

    # Unsolicited messages

    def _handle_push(self, key: str, value: str) -> None:
        try:
            if key == "OutletStatus":
                self._apply_outlet_statuses(parse_flags(value))
            elif key == "OutletName":
                self._apply_outlet_names(parse_outlet_names(value))
            elif key == "PowerStatus":
                self._apply_power_status(value)
            else:
                _LOGGER.debug("%s: ignoring unsolicited %s=%s", self.host, key, value)
                return
        except (ValueError, IndexError):
            _LOGGER.debug("%s: unreadable unsolicited %s=%s", self.host, key, value)
            return
        self._notify()

    # Requests

    def _apply_power_status(self, value: str) -> None:
        status = parse_power_status(value)
        self.current_value = status.current
        self.power_value = status.power
        self.voltage_value = status.voltage
        self.safe_voltage_status = status.safe_voltage

    async def async_get_initial(self) -> None:
        model = await self._exchange(REQ_MODEL)
        self.hardware_version = model
        self.firmware_version = await self._exchange(REQ_FIRMWARE)
        self.has_ups = await self._optional(REQ_UPS_CONNECTION) == "1"
        self.hostname = await self._optional(REQ_HOSTNAME) or ""
        self.serial_number = await self._exchange(REQ_SERVICE_TAG)
        count = await self._exchange(REQ_OUTLET_COUNT)
        try:
            self._set_outlet_layout(int(count))
        except ValueError as err:
            raise WattBoxProtocolError(f"unreadable outlet count {count!r}") from err
        self.supports_outlet_metering = not any(m in model for m in _UNMETERED_MODELS)

    async def async_update(self) -> None:
        try:
            await self._update()
        except (ValueError, IndexError) as err:
            raise WattBoxProtocolError(f"unreadable reply: {err}") from err

    async def _update(self) -> None:
        if (auto_reboot := await self._optional(REQ_AUTO_REBOOT)) is not None:
            self.auto_reboot = auto_reboot == "1"
        self._apply_power_status(await self._exchange(REQ_POWER_STATUS))
        self._apply_outlet_names(
            parse_outlet_names(await self._exchange(REQ_OUTLET_NAME))
        )
        self._apply_outlet_statuses(
            parse_flags(await self._exchange(REQ_OUTLET_STATUS))
        )

        # Asked even with no UPS attached: the device answers with a zeroed
        # tuple, and `power_lost` from it is still meaningful.
        if (ups_value := await self._optional(REQ_UPS_STATUS)) is not None:
            ups = parse_ups_status(ups_value)
            self.battery_charge = ups.battery_charge
            self.battery_load = ups.battery_load
            self.battery_health = ups.battery_health
            self.power_lost = ups.power_lost
            self.est_run_time = ups.est_run_time
            self.audible_alarm = ups.audible_alarm
            self.mute = ups.mute

        if self.outlet_metering and self.supports_outlet_metering:
            await self._update_outlet_power()

    async def _update_outlet_power(self) -> None:
        for index in self.outlets:
            value = await self._optional(REQ_OUTLET_POWER_STATUS.format(index=index))
            if value is None:
                # One `#Error` means the model has no per-outlet metering;
                # asking every outlet every poll would only repeat it.
                _LOGGER.warning(
                    "%s does not report per-outlet power; turning metering off",
                    self,
                )
                self.supports_outlet_metering = False
                for outlet in self.outlets.values():
                    outlet.power_value = outlet.current_value = None
                    outlet.voltage_value = None
                return
            reading = parse_outlet_power(value)
            if target := self.outlets.get(reading.index):
                target.power_value = reading.power
                target.current_value = reading.current
                target.voltage_value = reading.voltage

    async def async_send_command(self, outlet: int, command: Commands) -> None:
        if outlet not in self.outlets:
            raise ValueError(f"{self} has no outlet {outlet}")
        await self._exchange(CMD_OUTLET_SET.format(index=outlet, action=command.name))
        # Reflect the change straight away. The device usually pushes the new
        # outlet states as well, and the next poll confirms either way.
        self.outlets[outlet].status = command is not Commands.OFF
