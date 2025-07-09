"""Base Entity component for wattbox."""

from collections.abc import Callable
from typing import Any, Literal

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from pywattbox.base import BaseWattBox

from .const import DOMAIN, DOMAIN_DATA, TOPIC_UPDATE


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._wattbox.serial_number)},
            name=name,
            manufacturer="WattBox",
            model=getattr(self._wattbox, "model", None) or "WattBox",
            sw_version=getattr(self._wattbox, "firmware_version", None),
            serial_number=self._wattbox.serial_number,
            configuration_url=f"http://{self._wattbox.host}:{self._wattbox.port}"
            if hasattr(self._wattbox, "host") and hasattr(self._wattbox, "port")
            else None,
        )

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
