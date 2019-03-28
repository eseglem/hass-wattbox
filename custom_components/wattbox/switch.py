"""Switch platform for blueprint."""
from homeassistant.components.switch import SwitchDevice
from homeassistant.const import CONF_NAME

from . import update_data
from .const import DOMAIN_DATA, PLUG_ICON


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):  # pylint: disable=unused-argument
    """Setup switch platform."""
    name = discovery_info[CONF_NAME]
    entities = []

    # The Hardware Version has the number of outlets at the end.
    num_switches = hass.data[DOMAIN_DATA].number_outlets

    for i in range(num_switches):
        entities.append(WattBoxBinarySwitch(hass, name, i))

    async_add_entities(entities, True)


class WattBoxBinarySwitch(SwitchDevice):
    """WattBox switch class."""

    def __init__(self, hass, name, index):
        self.hass = hass
        self.attr = {}
        self.index = index
        self._status = False
        self._name = name.lower() + "_outlet_" + str(index + 1)

    async def async_update(self):
        """Update the sensor."""
        # Send update "signal" to the component
        await update_data(self.hass)

        # Get new data (if any)
        updated = self.hass.data[DOMAIN_DATA]
        # self.index starts at 1, but list starts at 0
        outlet = updated.outlets[self.index]

        # Check the data and update the value.
        self._status = outlet.status

        # Set/update attributes
        self.attr["name"] = outlet.name
        self.attr["method"] = outlet.method
        self.attr["index"] = outlet.index

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn on the switch."""
        self.hass.data[DOMAIN_DATA].outlets[self.index].turn_on()
        self._status = True

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn off the switch."""
        self.hass.data[DOMAIN_DATA].outlets[self.index].turn_off()
        self._status = False

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def icon(self):
        """Return the icon of this switch."""
        return PLUG_ICON

    @property
    def is_on(self):
        """Return true if the switch is on."""
        return self._status

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attr
