"""Binary sensor platform for wattbox."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_NAME, CONF_RESOURCES
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import BINARY_SENSOR_TYPES, DOMAIN_DATA
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(  # pylint: disable=unused-argument
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup binary_sensor platform."""
    name = discovery_info[CONF_NAME]
    entities = []

    for resource in discovery_info[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in BINARY_SENSOR_TYPES:
            continue

        entities.append(WattBoxBinarySensor(hass, name, sensor_type))

    async_add_entities(entities, True)


class WattBoxBinarySensor(WattBoxEntity, BinarySensorEntity):
    """WattBox binary_sensor class."""

    def __init__(self, hass: HomeAssistant, name: str, sensor_type: str) -> None:
        super().__init__(hass, name, sensor_type)
        self.type: str = sensor_type
        self.flipped: bool = BINARY_SENSOR_TYPES[self.type]["flipped"]
        self._attr_name = name + " " + BINARY_SENSOR_TYPES[sensor_type]["name"]
        self._attr_device_class = BINARY_SENSOR_TYPES[self.type]["device_class"]
        self._wattbox =  self.hass.data[DOMAIN_DATA][self.wattbox_name]['wattbox']
        self._attr_unique_id = 'wb-{}-bsensor-{}'.format(self._wattbox.serial_number, name)

    async def async_update(self) -> None:
        """Update the sensor."""
        # Check the data and update the value.
        value: bool | None = getattr(self._wattbox, self.type)
        if value is not None and self.flipped:
            value = not value
        self._attr_is_on = value
