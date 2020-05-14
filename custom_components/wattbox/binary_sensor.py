"""Binary sensor platform for wattbox."""
import logging

from homeassistant.components.binary_sensor import BinarySensorDevice
from homeassistant.const import CONF_NAME, CONF_RESOURCES

from .const import BINARY_SENSOR_TYPES, DOMAIN_DATA
from .entity import WattBoxEntity

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


class WattBoxBinarySensor(WattBoxEntity, BinarySensorDevice):
    """WattBox binary_sensor class."""

    def __init__(self, hass, name, sensor_type):
        super().__init__(hass, name, sensor_type)
        self.type = sensor_type
        self._status = False
        self._name = name + " " + BINARY_SENSOR_TYPES[sensor_type]["name"]

    async def async_update(self):
        """Update the sensor."""
        # Get domain data
        wattbox = self.hass.data[DOMAIN_DATA][self.wattbox_name]

        # Check the data and update the value.
        self._status = getattr(wattbox, self.type)

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BINARY_SENSOR_TYPES[self.type]["device_class"]

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return (
            not self._status
            if BINARY_SENSOR_TYPES[self.type]["flipped"]
            else self._status
        )
