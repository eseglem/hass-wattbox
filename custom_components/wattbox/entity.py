"""Base Entity component for wattbox."""

import logging
from collections.abc import Callable
from typing import Any, Literal

from getmac import get_mac_address
from homeassistant.const import ATTR_CONNECTIONS
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from pywattbox.base import BaseWattBox

from .const import DOMAIN, DOMAIN_DATA, TOPIC_UPDATE

_LOGGER = logging.getLogger(__name__)


def _get_mac_address(ip: str) -> str | None:
    """Get MAC address from IP using ARP table.

    Args:
        ip: IP address to lookup

    Returns:
        MAC address string or None if not found
    """
    try:
        mac = get_mac_address(ip=ip)
        if mac:
            _LOGGER.debug("Found MAC address %s for IP %s", mac, ip)
            return mac
        else:
            _LOGGER.debug("No MAC address found in ARP table for IP %s", ip)
            return None
    except Exception as err:
        _LOGGER.debug("Error getting MAC address for IP %s: %s", ip, err)
        return None


class WattBoxEntity(Entity):
    """WattBox Entity class."""

    _wattbox: BaseWattBox
    _async_unsub_dispatcher_connect: Callable
    _attr_should_poll: Literal[False] = False

    def __init__(self, hass: HomeAssistant, name: str, *_args: Any) -> None:
        self.hass = hass
        self._wattbox = self.hass.data[DOMAIN_DATA][name]
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

        # Add MAC address connection if host is available
        if hasattr(self._wattbox, "host") and self._wattbox.host:
            mac_address = _get_mac_address(self._wattbox.host)
            if mac_address:
                device_info[ATTR_CONNECTIONS] = {
                    (dr.CONNECTION_NETWORK_MAC, mac_address)
                }

        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        @callback
        def update() -> None:
            """Update the state."""
            self.async_schedule_update_ha_state(True)

        self._async_unsub_dispatcher_connect = async_dispatcher_connect(
            self.hass, self.topic, update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect dispatcher listener when removed."""
        if hasattr(self, "_async_unsub_dispatcher_connect"):
            self._async_unsub_dispatcher_connect()
