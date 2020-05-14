from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TOPIC_UPDATE


class WattBoxEntity(Entity):
    def __init__(self, hass, name, *args):
        self.hass = hass
        self.attr = dict()
        self.wattbox_name = name
        self._name = ""
        self.topic = TOPIC_UPDATE.format(DOMAIN, self.wattbox_name)

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
        if self._async_unsub_dispatcher_connect:
            self._async_unsub_dispatcher_connect()

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attr

    @property
    def should_poll(self) -> bool:
        """Return true."""
        return False
