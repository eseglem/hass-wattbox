"""The WattBox Integration Protocol, without any I/O.

The protocol spoken over telnet (port 23) and SSH (port 22) is line oriented,
LF terminated, and has no prompt:

* ``?Key`` or ``?Key=arg`` requests are answered by ``?Key=value``
* ``!Command=args`` controls are answered by ``OK``
* either can be answered by ``#Error``
* ``~Key=value`` lines arrive unsolicited, e.g. ``~OutletStatus=...`` after an
  outlet changes state

Properties of real hardware that shape this module, confirmed against
800-series units on firmware 2.10.0.0 (issues #55 and #66):

* Values contain spaces, commas and punctuation. Outlet names are user
  supplied and braced: ``?OutletName={Apple TV 06 Office Wall},{Modem}``.
* Commands are not echoed over telnet. They are echoed over SSH, so a reply
  cannot be found by its line number.
* The login prompts are not followed by a newline, so they cannot be read a
  line at a time.
* An unsolicited ``~`` line can arrive between a request and its reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

ERROR_REPLY: Final[str] = "#Error"
OK_REPLY: Final[str] = "OK"
UNSOLICITED_PREFIX: Final[str] = "~"

USERNAME_PROMPT: Final[re.Pattern[bytes]] = re.compile(rb"(?i)(?:username|login)\s*:")
PASSWORD_PROMPT: Final[re.Pattern[bytes]] = re.compile(rb"(?i)password\s*:")
LOGIN_SUCCESS: Final[re.Pattern[bytes]] = re.compile(rb"(?i)successfully logged in")
LOGIN_FAILURE: Final[re.Pattern[bytes]] = re.compile(rb"(?i)invalid login")

# Requests sent once, when the device is first set up.
REQ_MODEL: Final[str] = "?Model"
REQ_FIRMWARE: Final[str] = "?Firmware"
REQ_HOSTNAME: Final[str] = "?Hostname"
REQ_SERVICE_TAG: Final[str] = "?ServiceTag"
REQ_OUTLET_COUNT: Final[str] = "?OutletCount"
REQ_UPS_CONNECTION: Final[str] = "?UPSConnection"

# Requests sent on every poll.
REQ_AUTO_REBOOT: Final[str] = "?AutoReboot"
REQ_POWER_STATUS: Final[str] = "?PowerStatus"
REQ_OUTLET_NAME: Final[str] = "?OutletName"
REQ_OUTLET_STATUS: Final[str] = "?OutletStatus"
REQ_UPS_STATUS: Final[str] = "?UPSStatus"
REQ_OUTLET_POWER_STATUS: Final[str] = "?OutletPowerStatus={index}"

CMD_OUTLET_SET: Final[str] = "!OutletSet={index},{action},0"
CMD_EXIT: Final[str] = "!Exit"


@dataclass(frozen=True, slots=True)
class Request:
    """One request or control message, and how to recognise its reply."""

    command: str

    @property
    def is_query(self) -> bool:
        return self.command.startswith("?")

    @property
    def key(self) -> str:
        return self.command.partition("=")[0]

    @property
    def argument(self) -> str:
        return self.command.partition("=")[2]

    def accepts(self, line: str) -> bool:
        """Whether *line* is the reply to this request.

        Rejects the echo of the request itself, which matters for requests
        that carry an argument: the echo of ``?OutletPowerStatus=1`` is itself
        a well-formed ``key=value`` line, and taking it for the reply would
        return the request instead of the reading.

        For those requests the reply also has to name the same argument, so a
        late reply to an earlier request can never be taken for this one.
        """
        if line == ERROR_REPLY:
            return True
        if line == self.command:
            return False
        if not self.is_query:
            return line == OK_REPLY
        key, sep, value = line.partition("=")
        if not sep or key != self.key:
            return False
        if self.argument:
            return value.split(",", 1)[0] == self.argument.split(",", 1)[0]
        return True

    def value(self, line: str) -> str:
        """The value carried by an accepted reply."""
        if not self.is_query:
            return line
        return line.partition("=")[2]


def split_unsolicited(line: str) -> tuple[str, str] | None:
    """``(key, value)`` for an unsolicited ``~Key=value`` line, else None."""
    if not line.startswith(UNSOLICITED_PREFIX):
        return None
    key, _, value = line[1:].partition("=")
    return key, value


def parse_outlet_names(value: str) -> list[str]:
    """Outlet names, braced on the Integration Protocol.

    Splitting on commas, as pywattbox did, misaligns every outlet after one
    whose name contains a comma. Names are braced, so take what is inside
    each pair; fall back to commas for firmware that does not brace them.
    """
    if "{" in value:
        return re.findall(r"\{([^}]*)\}", value)
    return [name.strip() for name in value.split(",")] if value else []


def parse_flags(value: str) -> list[bool]:
    """A comma separated list of ``1``/``0`` flags."""
    return [flag.strip() == "1" for flag in value.split(",")] if value else []


@dataclass(frozen=True, slots=True)
class PowerStatus:
    current: float
    power: float
    voltage: float
    safe_voltage: bool


def parse_power_status(value: str) -> PowerStatus:
    """``current,power,voltage,safe_voltage``.

    The safe-voltage flag reads ``0`` while the front-panel light is green and
    the web UI says the voltage is safe, so it is inverted here.
    """
    current, power, voltage, safe, *_ = value.split(",")
    return PowerStatus(
        current=float(current),
        power=float(power),
        voltage=float(voltage),
        safe_voltage=safe.strip() == "0",
    )


@dataclass(frozen=True, slots=True)
class UpsStatus:
    battery_charge: int
    battery_load: int
    battery_health: bool
    power_lost: bool
    est_run_time: int
    audible_alarm: bool
    mute: bool


def parse_ups_status(value: str) -> UpsStatus:
    """``charge,load,health,power_lost,runtime,alarm,mute``.

    A unit with no UPS still answers, with ``0,0,Good,False,0,False,False``,
    and ``power_lost`` from that tuple is still meaningful.
    """
    charge, load, health, lost, runtime, alarm, mute, *_ = value.split(",")
    return UpsStatus(
        battery_charge=int(float(charge)),
        battery_load=int(float(load)),
        battery_health=health.strip() == "Good",
        power_lost=lost.strip() == "True",
        est_run_time=int(float(runtime)),
        audible_alarm=alarm.strip() == "True",
        mute=mute.strip() == "True",
    )


@dataclass(frozen=True, slots=True)
class OutletPower:
    index: int
    power: float
    current: float
    voltage: float


def parse_outlet_power(value: str) -> OutletPower:
    """``index,power,current,voltage`` for one outlet."""
    index, power, current, voltage, *_ = value.split(",")
    return OutletPower(
        index=int(index),
        power=float(power),
        current=float(current),
        voltage=float(voltage),
    )


class LineBuffer:
    """Turns a byte stream into lines, holding back any partial last line."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, data: bytes) -> list[str]:
        self._pending += data
        *complete, self._pending = self._pending.split(b"\n")
        lines = []
        for raw in complete:
            if line := raw.decode(errors="replace").strip():
                lines.append(line)
        return lines


# Telnet option negotiation (RFC 854). The WattBox sends none, but a client
# that does not cope with it would wedge on a firmware that starts to.
IAC: Final[int] = 255
DONT: Final[int] = 254
DO: Final[int] = 253
WONT: Final[int] = 252
WILL: Final[int] = 251
SB: Final[int] = 250
SE: Final[int] = 240


# TelnetFilter states.
_DATA, _COMMAND, _OPTION, _SUBNEGOTIATION, _SUBNEGOTIATION_IAC = range(5)


class TelnetFilter:
    """Strips telnet negotiation from a byte stream and refuses every option.

    Stateful, so a sequence split across two reads is still recognised.
    """

    def __init__(self) -> None:
        self._state = _DATA
        self._verb = 0

    def feed(self, data: bytes) -> tuple[bytes, bytes]:
        """Return ``(payload, replies)`` for a chunk read from the socket."""
        if IAC not in data and self._state == _DATA:
            return data, b""
        out = bytearray()
        replies = bytearray()
        for byte in data:
            if self._state != _DATA:
                self._negotiate(byte, out, replies)
            elif byte == IAC:
                self._state = _COMMAND
            else:
                out.append(byte)
        return bytes(out), bytes(replies)

    def _negotiate(self, byte: int, out: bytearray, replies: bytearray) -> None:
        state, self._state = self._state, _DATA
        if state == _COMMAND:
            if byte == IAC:  # An escaped 0xFF data byte.
                out.append(IAC)
            elif byte in (DO, DONT, WILL, WONT):
                self._verb = byte
                self._state = _OPTION
            elif byte == SB:
                self._state = _SUBNEGOTIATION
        elif state == _OPTION:
            if (refusal := {DO: WONT, WILL: DONT}.get(self._verb)) is not None:
                replies += bytes((IAC, refusal, byte))
        elif state == _SUBNEGOTIATION:
            self._state = _SUBNEGOTIATION_IAC if byte == IAC else _SUBNEGOTIATION
        elif state == _SUBNEGOTIATION_IAC and byte != SE:
            self._state = _SUBNEGOTIATION
