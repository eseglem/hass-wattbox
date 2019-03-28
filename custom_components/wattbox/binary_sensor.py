"""Binary sensor platform for wattbox."""
import logging

from homeassistant.components.binary_sensor import BinarySensorDevice
from homeassistant.const import CONF_NAME, CONF_RESOURCES

from . import update_data
from .const import BINARY_SENSOR_TYPES, DOMAIN_DATA

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):  # pylint: disable=unused-argument
    """Setup binary_sensor platform."""
    name = discovery_info[CONF_NAME]
    entities = []

    for resource in discovery_info[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in BINARY_SENSOR_TYPES:
            continue

        entities.append(WattBoxBinarySensor(hass, name, sensor_type))

    async_add_entities(entities, True)


class WattBoxBinarySensor(BinarySensorDevice):
    """WattBox binary_sensor class."""

    def __init__(self, hass, name, sensor_type):
        self.hass = hass
        self.attr = {}
        self.type = sensor_type
        self._status = False
        self._name = name.lower() + "_" + BINARY_SENSOR_TYPES[sensor_type][0]

    async def async_update(self):
        """Update the sensor."""
        # Send update "signal" to the component
        await update_data(self.hass)

        # Get new data (if any)
        updated = self.hass.data[DOMAIN_DATA]

        # Check the data and update the value.
        self._state = getattr(updated, self.type)

    @property
    def name(self):
        """Return the name of the binary_sensor."""
        return self._name

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BINARY_SENSOR_TYPES[self.type][1]

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self._status

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self.attr
