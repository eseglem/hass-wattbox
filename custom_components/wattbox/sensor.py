"""Sensor platform for wattbox."""

import logging

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    CONF_RESOURCES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN_DATA, SENSOR_TYPES
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WattBox sensors from a config entry."""
    try:
        conf_name: str = entry.data[CONF_NAME]
        clean_name = slugify(conf_name)
        entities: list[WattBoxSensor | WattBoxEnergySensor] = []

        # Get available resources from entry data or use all sensor types
        resources = entry.data.get(CONF_RESOURCES, list(SENSOR_TYPES.keys()))

        resource: str
        for resource in resources:
            if (sensor_type := resource.lower()) not in SENSOR_TYPES:
                continue

            try:
                entities.append(WattBoxSensor(hass, conf_name, sensor_type))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxSensor: %s", err)
                raise PlatformNotReady from err

        # Add a Total Energy sensor that integrates the power reading over time.
        entities.append(WattBoxEnergySensor(hass, conf_name, clean_name))

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up sensor platform: %s", err)
        raise PlatformNotReady from err


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup sensor platform (legacy YAML support)."""
    try:
        conf_name: str = discovery_info[CONF_NAME]
        clean_name = slugify(conf_name)
        entities: list[WattBoxSensor | WattBoxEnergySensor] = []

        resource: str
        for resource in discovery_info[CONF_RESOURCES]:
            if (sensor_type := resource.lower()) not in SENSOR_TYPES:
                continue

            try:
                entities.append(WattBoxSensor(hass, conf_name, sensor_type))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxSensor: %s", err)
                raise PlatformNotReady from err

        # Add a Total Energy sensor that integrates the power reading over time.
        entities.append(WattBoxEnergySensor(hass, conf_name, clean_name))

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up sensor platform: %s", err)
        raise PlatformNotReady from err


class WattBoxSensor(WattBoxEntity, SensorEntity):
    """WattBox Sensor class."""

    def __init__(self, hass: HomeAssistant, name: str, sensor_type: str) -> None:
        super().__init__(hass, name, sensor_type)
        self.sensor_type: str = sensor_type
        sensor_def = SENSOR_TYPES[self.sensor_type]
        self._attr_name = f"{name} {sensor_def['name']}"
        self._attr_native_unit_of_measurement = sensor_def["unit"]
        self._attr_icon = sensor_def["icon"]
        self._attr_device_class = sensor_def["device_class"]
        self._attr_state_class = sensor_def["state_class"]
        self._attr_unique_id = f"{self._wattbox.serial_number}-sensor-{sensor_type}"

    async def async_update(self) -> None:
        """Update the sensor (legacy poll fallback)."""
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        self._attr_native_value = getattr(
            self._wattbox, self.sensor_type, STATE_UNKNOWN
        )


class WattBoxEnergySensor(WattBoxEntity, RestoreSensor):
    """Total Energy sensor derived by integrating the WattBox power reading.

    Uses the trapezoidal rule between successive coordinator updates and
    persists its accumulated value across restarts via RestoreSensor.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, name: str, clean_name: str) -> None:
        super().__init__(hass, name)
        self._attr_name = f"{name} Total Energy"
        # Preserve the unique_id used by the previous IntegrationSensor-based
        # implementation so existing installs keep their entity and history.
        self._attr_unique_id = f"{clean_name}_total_energy"
        self._attr_native_value: float = 0.0
        self._last_power: float | None = None
        self._last_update: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore previous accumulated value, then register update callbacks."""
        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is not None and isinstance(
            last_sensor_data.native_value, (int, float)
        ):
            self._attr_native_value = float(last_sensor_data.native_value)
        else:
            # Fall back to the plain restored state in case the sensor data
            # extra is not available (e.g. very old history).
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state not in (
                None,
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                try:
                    self._attr_native_value = float(last_state.state)
                except (TypeError, ValueError):
                    pass

        # Subscribe to coordinator updates after restoring so the first tick
        # integrates against the restored value, not the default 0.0.
        await super().async_added_to_hass()

    @callback
    def _update_attrs(self) -> None:
        """Integrate the current power reading into the running total."""
        power = getattr(self._wattbox, "power_value", None)
        now = dt_util.utcnow().timestamp()

        if not isinstance(power, (int, float)):
            # Treat non-numeric readings as a gap; reset the integration
            # window so we don't extrapolate across unknown periods.
            self._last_power = None
            self._last_update = now
            return

        power = float(power)
        if self._last_power is not None and self._last_update is not None:
            elapsed_hours = (now - self._last_update) / 3600.0
            if elapsed_hours > 0:
                # Trapezoidal rule: average of endpoints * dt, watts -> kWh.
                avg_watts = (self._last_power + power) / 2.0
                self._attr_native_value += (avg_watts * elapsed_hours) / 1000.0

        self._last_power = power
        self._last_update = now
