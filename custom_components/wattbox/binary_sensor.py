"""Binary sensor platform for wattbox."""

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_RESOURCES
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    BINARY_SENSOR_TYPES,
    DOMAIN_DATA,
    HTTP_ONLY_BINARY_SENSORS,
    UPS_ONLY_BINARY_SENSORS,
)
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


def _is_supported(hass: HomeAssistant, name: str, sensor_type: str) -> bool:
    """Whether this sensor can ever carry a real value on this device.

    A WattBox with no UPS reports a zeroed placeholder UPS tuple, and the IP
    driver has no source at all for `cloud_status`, so those entities sit
    pinned at off/unknown while still being polled and recorded.

    Unsupported sensors are *not created*, rather than created disabled.
    `entity_registry_enabled_default` is only consulted when an entity is
    first registered, so it does nothing for anyone who already has these
    entities. Skipping creation takes effect on every reload.
    """
    wattbox = hass.data.get(DOMAIN_DATA, {}).get(name)
    if wattbox is None:
        return True
    if sensor_type in UPS_ONLY_BINARY_SENSORS and not getattr(
        wattbox, "has_ups", False
    ):
        return False
    if (
        sensor_type in HTTP_ONLY_BINARY_SENSORS
        and getattr(wattbox, sensor_type, None) is None
    ):
        return False
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WattBox binary sensors from a config entry."""
    try:
        name = entry.data[CONF_NAME]
        entities = []

        # Get available resources from entry data or use all binary sensor types
        resources = entry.data.get(CONF_RESOURCES, list(BINARY_SENSOR_TYPES.keys()))

        for resource in resources:
            sensor_type = resource.lower()

            if sensor_type not in BINARY_SENSOR_TYPES:
                continue

            if not _is_supported(hass, name, sensor_type):
                _LOGGER.debug(
                    "Skipping unsupported binary sensor %s for %s", sensor_type, name
                )
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


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup binary_sensor platform (legacy YAML support)."""
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
        """Update the sensor (legacy poll fallback)."""
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        value: bool | None = getattr(self._wattbox, self.sensor_type, None)
        if value is not None and self._flipped:
            value = not value
        self._attr_is_on = value
