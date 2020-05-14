"""Sensor platform for wattbox."""
import logging

from homeassistant.const import CONF_NAME, CONF_RESOURCES

from .const import DOMAIN_DATA, SENSOR_TYPES
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass, config, async_add_entities, discovery_info=None
):  # pylint: disable=unused-argument
    """Setup sensor platform."""
    name = discovery_info[CONF_NAME]
    entities = []

    for resource in discovery_info[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in SENSOR_TYPES:
            continue

        entities.append(WattBoxSensor(hass, name, sensor_type))

    async_add_entities(entities, True)


class WattBoxSensor(WattBoxEntity):
    """WattBox Sensor class."""

    def __init__(self, hass, name, sensor_type):
        super().__init__(hass, name, sensor_type)
        self.type = sensor_type
        self._name = name + " " + SENSOR_TYPES[self.type][0]
        self._state = None
        self._unit = SENSOR_TYPES[self.type][1]

    async def async_update(self):
        """Update the sensor."""
        # Get new data (if any)
        wattbox = self.hass.data[DOMAIN_DATA][self.wattbox_name]

        # Check the data and update the value.
        self._state = getattr(wattbox, self.type)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Return the icon of the sensor."""
        return SENSOR_TYPES[self.type][2]

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit
