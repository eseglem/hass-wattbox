"""Sensor platform for wattbox."""

import logging
from typing import List, Union
from asyncio import TimeoutError, wait_for

from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME, CONF_RESOURCES, STATE_UNKNOWN, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.exceptions import PlatformNotReady

from .const import SENSOR_TYPES
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup sensor platform."""
    try:
        conf_name: str = discovery_info[CONF_NAME]
        clean_name = conf_name.replace(" ", "_").lower()
        entities: List[Union[WattBoxSensor, IntegrationSensor]] = []

        resource: str
        for resource in discovery_info[CONF_RESOURCES]:
            if (sensor_type := resource.lower()) not in SENSOR_TYPES:
                continue

            try:
                entities.append(WattBoxSensor(hass, conf_name, sensor_type))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxSensor: %s", err)
                raise PlatformNotReady from err

        # TODO: Add a setting for this, default to true?
        # Add an IntegrationSensor, so end users don't have to manually configure it.
        entities.append(
            IntegrationSensor(
                integration_method="trapezoidal",
                name=f"{conf_name} Total Energy",
                round_digits=2,
                max_sub_interval=timedelta(minutes=5),
                source_entity=f"sensor.{clean_name}_power",
                unique_id=f"{clean_name}_total_energy",
                unit_prefix="k",
                unit_time=UnitOfTime.HOURS,
            )
        )

        await async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up sensor platform: %s", err)
        raise PlatformNotReady from err


class WattBoxSensor(WattBoxEntity, SensorEntity):
    """WattBox Sensor class."""

    def __init__(self, hass: HomeAssistant, name: str, sensor_type: str) -> None:
        super().__init__(hass, name, sensor_type)
        self.sensor_type: str = sensor_type
        self._attr_name = f"{name} {SENSOR_TYPES[self.sensor_type]['name']}"
        self._attr_native_unit_of_measurement = SENSOR_TYPES[self.sensor_type]["unit"]
        self._attr_icon = SENSOR_TYPES[self.sensor_type]["icon"]
        self._attr_unique_id = f"{self._wattbox.serial_number}-sensor-{sensor_type}"

    async def async_update(self) -> None:
        """Update the sensor."""
        # Check the data and update the value.
        self._attr_native_value = getattr(
            self._wattbox, self.sensor_type, STATE_UNKNOWN
        )
