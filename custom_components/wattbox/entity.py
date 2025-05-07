"""Base Entity component for wattbox."""
from collections.abc import Callable
from typing import Any, Literal

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
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
