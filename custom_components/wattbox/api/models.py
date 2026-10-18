"""Device state shared by the HTTP and Integration Protocol clients.

Attribute names follow pywattbox, which this package replaces, so the entity
layer -- and every entity's unique ID, which is built from
``serial_number`` -- carries over unchanged.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import IntEnum

_LOGGER = logging.getLogger(__name__)


class Commands(IntEnum):
    """Outlet actions.

    The HTTP API takes the values, the Integration Protocol takes the names.
    """

    OFF = 0
    ON = 1
    RESET = 3


class BaseWattBox(ABC):
    """One WattBox, its last known state, and the way to talk to it."""

    #: ``"http"``, ``"telnet"`` or ``"ssh"``.
    transport: str

    def __init__(self, host: str, user: str, password: str, port: int) -> None:
        self.host: str = host
        self.port: int = port
        self.user: str = user
        self.password: str = password

        # Identity, read once.
        self.hardware_version: str | None = None
        self.firmware_version: str | None = None
        self.has_ups: bool = False
        self.hostname: str = ""
        self.number_outlets: int = 0
        self.serial_number: str = ""

        # Whether the device reports power per outlet, and whether to ask.
        # The second can only be on when the first is.
        self.supports_outlet_metering: bool = False
        self.outlet_metering: bool = False

        # Status. None where this interface has no source for the value.
        self.audible_alarm: bool = False
        self.auto_reboot: bool = False
        self.cloud_status: bool | None = None
        self.mute: bool = False
        self.power_lost: bool = False

        # Whole-unit power.
        self.current_value: float = 0.0  # A
        self.power_value: float = 0.0  # W
        self.safe_voltage_status: bool = True
        self.voltage_value: float = 0.0  # V

        # UPS.
        self.battery_charge: int = 0  # %
        self.battery_health: bool = False
        self.battery_load: int = 0  # %
        self.battery_test: bool | None = None
        self.est_run_time: int = 0  # minutes

        # Outlets, keyed by the device's own 1-based index.
        self.outlets: dict[int, Outlet] = {}
        self.master_outlet: Outlet | None = None

        self._listeners: list[Callable[[], None]] = []

    @abstractmethod
    async def async_get_initial(self) -> None:
        """Read the device's identity and outlet layout."""

    @abstractmethod
    async def async_update(self) -> None:
        """Refresh every status value."""

    @abstractmethod
    async def async_send_command(self, outlet: int, command: Commands) -> None:
        """Act on one outlet."""

    @abstractmethod
    async def async_close(self) -> None:
        """Release whatever is held open on the device. Safe to repeat."""

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call *listener* when the device pushes a change; returns an unsubscribe.

        Only the Integration Protocol pushes anything. Listeners run in the
        event loop and must not block.
        """
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - one bad listener must not stop the rest
                _LOGGER.exception("Error in WattBox listener")

    def _set_outlet_layout(self, count: int) -> None:
        """Create the outlets once their number is known."""
        self.number_outlets = count
        self.outlets = {i: Outlet(i, self) for i in range(1, count + 1)}

    def _apply_outlet_names(self, names: list[str]) -> None:
        for index, name in enumerate(names, start=1):
            if outlet := self.outlets.get(index):
                outlet.name = name

    def _apply_outlet_statuses(self, statuses: list[bool]) -> None:
        if len(statuses) != len(self.outlets):
            _LOGGER.debug(
                "%s reported %d outlet statuses for %d outlets",
                self,
                len(statuses),
                len(self.outlets),
            )
        for index, status in enumerate(statuses, start=1):
            if outlet := self.outlets.get(index):
                outlet.status = status

    def __str__(self) -> str:
        return f"{self.hostname or self.host} ({self.host}): {self.hardware_version}"


class Outlet:
    """One outlet and its last known state."""

    def __init__(self, index: int, wattbox: BaseWattBox) -> None:
        self.index: int = index
        self.wattbox: BaseWattBox = wattbox
        self.name: str | None = ""
        self.status: bool | None = None
        # Whether the outlet follows the master switch. HTTP only.
        self.method: bool | None = None
        # Per-outlet power, when metering is on.
        self.current_value: float | None = None  # A
        self.power_value: float | None = None  # W
        self.voltage_value: float | None = None  # V

    async def async_turn_on(self) -> None:
        await self.wattbox.async_send_command(self.index, Commands.ON)

    async def async_turn_off(self) -> None:
        await self.wattbox.async_send_command(self.index, Commands.OFF)

    async def async_reset(self) -> None:
        await self.wattbox.async_send_command(self.index, Commands.RESET)

    def __str__(self) -> str:
        return f"{self.name} ({self.index}): {self.status}"


class MasterSwitch(Outlet):
    """The front-panel master switch, as the HTTP API models it.

    There is no master command; pressing it switches every outlet set to
    follow it. It reads as on only when all of those outlets are on.
    """

    def __init__(self, wattbox: BaseWattBox) -> None:
        super().__init__(0, wattbox)
        self.name = "Master Switch"

    def _followers(self) -> list[Outlet]:
        return [o for o in self.wattbox.outlets.values() if o.method]

    def refresh(self) -> None:
        followers = self._followers()
        self.status = bool(followers) and all(o.status for o in followers)

    async def _switch_all(self, on: bool) -> None:
        command = Commands.ON if on else Commands.OFF
        for outlet in self._followers():
            if outlet.status is not on:
                await self.wattbox.async_send_command(outlet.index, command)

    async def async_turn_on(self) -> None:
        await self._switch_all(True)

    async def async_turn_off(self) -> None:
        await self._switch_all(False)

    async def async_reset(self) -> None:
        raise NotImplementedError("The master switch cannot be reset")
