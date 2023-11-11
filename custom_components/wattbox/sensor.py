"""Sensor platform for wattbox."""

import logging
from typing import List, Union

from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME, CONF_RESOURCES, STATE_UNKNOWN, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN_DATA, SENSOR_TYPES
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup sensor platform."""
    name: str = discovery_info[CONF_NAME]
    entities: List[Union[WattBoxSensor, IntegrationSensor]] = []

    for resource in discovery_info[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in SENSOR_TYPES:
            continue

        entities.append(WattBoxSensor(hass, name, sensor_type))

    # TODO: Add a setting for this, default to true?
    # Add an IntegrationSensor, so end users don't have to manually configure it.
    entities.append(
        IntegrationSensor(
            integration_method="trapezoidal",
            name=f"{name}_energy_spent",
            round_digits=2,
            source_entity=f"sensor.{name}_power",
            unique_id=None,
            unit_prefix="k",
            unit_time=UnitOfTime.HOURS,
        )
    )

    async_add_entities(entities)


class WattBoxSensor(WattBoxEntity, SensorEntity):
    """WattBox Sensor class."""

    def __init__(self, hass: HomeAssistant, name: str, sensor_type: str) -> None:
        super().__init__(hass, name, sensor_type)
        self.sensor_type: str = sensor_type
        self._attr_name = name + " " + SENSOR_TYPES[self.sensor_type]["name"]
        self._attr_native_unit_of_measurement = SENSOR_TYPES[self.sensor_type]["unit"]
        self._attr_suggested_unit_of_measurement = SENSOR_TYPES[self.sensor_type][
            "unit"
        ]
        self._attr_icon = SENSOR_TYPES[self.sensor_type]["icon"]

    async def async_update(self) -> None:
        """Update the sensor."""
        # Get new data (if any)
        wattbox = self.hass.data[DOMAIN_DATA][self.wattbox_name]

        # Check the data and update the value.
        self._attr_native_value = getattr(wattbox, self.sensor_type, STATE_UNKNOWN)
