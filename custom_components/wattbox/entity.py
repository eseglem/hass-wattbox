"""Base Entity component for wattbox."""

import logging
from collections.abc import Callable
from typing import Any, Literal

from homeassistant.const import ATTR_CONNECTIONS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pywattbox.base import BaseWattBox

from .const import DOMAIN, DOMAIN_DATA, TOPIC_UPDATE

_LOGGER = logging.getLogger(__name__)


class WattBoxEntity(Entity):
    """WattBox Entity class."""

    _wattbox: BaseWattBox
    _coordinator: DataUpdateCoordinator | None
    _async_unsub_dispatcher_connect: Callable
    _attr_should_poll: Literal[False] = False

    def __init__(self, hass: HomeAssistant, name: str, *_args: Any) -> None:
        self.hass = hass
        self._wattbox = self.hass.data[DOMAIN_DATA][name]

        # Use coordinator if available (config entry path), otherwise
        # fall back to dispatcher pattern (legacy YAML path).
        self._coordinator = self.hass.data.get(DOMAIN, {}).get(name)

        self.topic: str = TOPIC_UPDATE.format(DOMAIN, name)
        self._attr_extra_state_attributes: dict[str, Any] = {}

        # Build device info with MAC address connection if available
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._wattbox.serial_number)},
            name=name,
            manufacturer="WattBox",
            model=getattr(self._wattbox, "hardware_version", None) or "WattBox",
            sw_version=getattr(self._wattbox, "firmware_version", None),
            serial_number=self._wattbox.serial_number,
            configuration_url=f"http://{self._wattbox.host}:{self._wattbox.port}"
            if hasattr(self._wattbox, "host") and hasattr(self._wattbox, "port")
            else None,
        )

        # Add MAC address as a device connection (looked up once during setup)
        mac_address = getattr(self._coordinator, "mac_address", None)
        if mac_address:
            device_info[ATTR_CONNECTIONS] = {
                (dr.CONNECTION_NETWORK_MAC, mac_address)
            }

        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        When using a coordinator (config entry path), availability is
        determined by whether the last data update succeeded. This causes
        all entities to become unavailable when the WattBox device is
        unreachable, and available again when it comes back.
        """
        if self._coordinator is not None:
            return self._coordinator.last_update_success
        return True

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        @callback
        def update() -> None:
            """Update the state."""
            self.async_schedule_update_ha_state(True)

        if self._coordinator is not None:
            # Config entry path: listen to coordinator updates
            self.async_on_remove(
                self._coordinator.async_add_listener(update)
            )
        else:
            # Legacy YAML path: listen to dispatcher updates
            self._async_unsub_dispatcher_connect = async_dispatcher_connect(
                self.hass, self.topic, update
            )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect dispatcher listener when removed."""
        # Coordinator listeners are cleaned up via async_on_remove.
        # Only manually disconnect the dispatcher listener (YAML path).
        if self._coordinator is None and hasattr(
            self, "_async_unsub_dispatcher_connect"
        ):
            self._async_unsub_dispatcher_connect()
