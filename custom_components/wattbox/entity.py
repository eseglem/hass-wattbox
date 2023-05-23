"""Base Entity component for wattbox."""
from typing import Any, Callable, Dict, Literal

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TOPIC_UPDATE


class WattBoxEntity(Entity):
    """WattBox Entity class."""

    _async_unsub_dispatcher_connect: Callable
    _attr_should_poll: Literal[False] = False

    def __init__(  # pylint: disable=unused-argument
        self, hass: HomeAssistant, name: str, *args
    ) -> None:
        self.hass = hass
        self._attr_extra_state_attributes: Dict[str, Any] = {}
        self.wattbox_name: str = name
        self.topic: str = TOPIC_UPDATE.format(DOMAIN, self.wattbox_name)

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
