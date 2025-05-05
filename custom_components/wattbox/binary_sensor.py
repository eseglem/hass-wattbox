"""Binary sensor platform for wattbox."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import CONF_NAME, CONF_RESOURCES
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.exceptions import PlatformNotReady

from .const import BINARY_SENSOR_TYPES
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup binary_sensor platform."""
    try:
        name = discovery_info[CONF_NAME]
        entities = []

        for resource in discovery_info[CONF_RESOURCES]:
            sensor_type = resource.lower()

            if sensor_type not in BINARY_SENSOR_TYPES:
                continue

            try:
                entities.append(WattBoxBinarySensor(hass, name, sensor_type))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxBinarySensor: %s", err)
                raise PlatformNotReady from err

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up binary_sensor platform: %s", err)
        raise PlatformNotReady from err


class WattBoxBinarySensor(WattBoxEntity, BinarySensorEntity):
    """WattBox binary_sensor class."""

    _flipped: bool = False

    def __init__(self, hass: HomeAssistant, name: str, sensor_type: str) -> None:
        super().__init__(hass, name, sensor_type)
        self.sensor_type: str = sensor_type
        self._flipped = BINARY_SENSOR_TYPES[self.sensor_type]["flipped"]
        self._attr_name = name + " " + BINARY_SENSOR_TYPES[self.sensor_type]["name"]
        self._attr_device_class = BINARY_SENSOR_TYPES[self.sensor_type]["device_class"]
        self._attr_unique_id = (
            f"{self._wattbox.serial_number}-bsensor-{self.sensor_type}"
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        # Check the data and update the value.
        value: bool | None = getattr(self._wattbox, self.sensor_type, None)
        if value is not None and self._flipped:
            value = not value
        self._attr_is_on = value
