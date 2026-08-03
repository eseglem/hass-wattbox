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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_OUTLET_METERING,
    CONF_SKIP_REGEXP,
    DEFAULT_OUTLET_METERING,
    DOMAIN_DATA,
    OUTLET_SENSOR_TYPES,
    SENSOR_TYPES,
    UPS_ONLY_SENSORS,
)
from .entity import WattBoxEntity
from .switch import validate_regex

_LOGGER = logging.getLogger(__name__)


def _is_supported(hass: HomeAssistant, name: str, sensor_type: str) -> bool:
    """Whether this sensor can ever carry a real value on this device.

    A WattBox with no UPS still answers `?UPSStatus`, but with a zeroed
    placeholder tuple, so the battery sensors would sit at 0 forever while
    still being polled and recorded.

    Unsupported sensors are *not created*, rather than created disabled.
    `entity_registry_enabled_default` is only consulted when an entity is
    first registered, so it does nothing for anyone who already has these
    entities -- which is everyone upgrading. Skipping creation takes effect on
    every reload, and the entities come back by themselves if a UPS is later
    attached.
    """
    if sensor_type not in UPS_ONLY_SENSORS:
        return True
    wattbox = hass.data.get(DOMAIN_DATA, {}).get(name)
    return wattbox is None or bool(getattr(wattbox, "has_ups", False))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WattBox sensors from a config entry."""
    try:
        conf_name: str = entry.data[CONF_NAME]
        clean_name = slugify(conf_name)
        entities: list[WattBoxSensor | WattBoxEnergySensor | WattBoxOutletSensor] = []

        # Get available resources from entry data or use all sensor types
        resources = entry.data.get(CONF_RESOURCES, list(SENSOR_TYPES.keys()))

        resource: str
        for resource in resources:
            if (sensor_type := resource.lower()) not in SENSOR_TYPES:
                continue

            if not _is_supported(hass, conf_name, sensor_type):
                _LOGGER.debug(
                    "Skipping unsupported sensor %s for %s", sensor_type, conf_name
                )
                continue

            try:
                entities.append(WattBoxSensor(hass, conf_name, sensor_type))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxSensor: %s", err)
                raise PlatformNotReady from err

        # Add a Total Energy sensor that integrates the power reading over time.
        entities.append(WattBoxEnergySensor(hass, conf_name, clean_name))

        entities.extend(_outlet_sensors(hass, entry, conf_name))

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up sensor platform: %s", err)
        raise PlatformNotReady from err


def _outlet_unique_id_prefix(serial_number: str) -> str:
    """Prefix shared by every outlet sensor on one device.

    Creation and pruning both derive from this, so they cannot drift into
    disagreeing about which entities belong to the feature.
    """
    return f"{serial_number}-outlet-"


def _outlet_unique_id(serial_number: str, index: int, sensor_type: str) -> str:
    """Unique ID for one outlet's sensor.

    Keyed by outlet index, not name: outlets get renamed on the device and the
    entity has to survive that.
    """
    return f"{_outlet_unique_id_prefix(serial_number)}{index}-sensor-{sensor_type}"


def _outlet_sensors(
    hass: HomeAssistant, entry: ConfigEntry, conf_name: str
) -> list["WattBoxOutletSensor"]:
    """Per-outlet power, current and voltage, when metering is enabled.

    Not created when the option is off, rather than created and disabled: the
    option *is* the opt-in, and `entity_registry_enabled_default` is only
    consulted at first registration, so a disabled-by-default entity would
    never come back for anyone who already has it.

    Gated on `outlet_power_status`, which only `IpWattBox` defines. Enabling
    metering on an HTTP unit polls nothing extra and would produce sensors
    stuck at `unknown` forever -- the XML API reports power for the unit as a
    whole and never per outlet.
    """
    wattbox = hass.data[DOMAIN_DATA][conf_name]
    enabled = entry.options.get(CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING)
    supported = bool(getattr(wattbox, "outlet_power_status", False))

    if enabled and not supported:
        _LOGGER.debug(
            "Per-outlet metering requested for %s, but this device does not "
            "report it; no outlet sensors created",
            conf_name,
        )

    sensors: list[WattBoxOutletSensor] = []
    if enabled and supported:
        # Skipped outlets are skipped whole. A sensor cannot cut anyone's
        # network, but "skip outlets matching" should mean one thing, not two.
        skip_regexp = validate_regex(entry.options, CONF_SKIP_REGEXP)
        for index, outlet in wattbox.outlets.items():
            if skip_regexp and outlet.name and skip_regexp.search(outlet.name):
                continue
            sensors.extend(
                WattBoxOutletSensor(hass, conf_name, index, sensor_type)
                for sensor_type in OUTLET_SENSOR_TYPES
            )

    _prune_outlet_sensors(
        hass,
        entry,
        wattbox.serial_number,
        {sensor.unique_id for sensor in sensors},
    )
    return sensors


def _prune_outlet_sensors(
    hass: HomeAssistant, entry: ConfigEntry, serial_number: str, keep: set[str | None]
) -> None:
    """Delete registry entries for outlet sensors no longer being created.

    Simply not creating an entity does not remove it. Home Assistant restores
    the registry entry for the config entry, finds nothing providing it, and
    shows it as `unavailable` indefinitely -- so turning metering off would
    leave a wall of dead sensors rather than clearing them.

    Also covers an outlet newly matching the skip pattern, and an outlet that
    no longer exists because the device reports fewer of them.

    Scoped by serial-number prefix and to the sensor domain, so it cannot
    reach the whole-unit sensors, the energy sensor, or another device's
    entities sharing this config entry.
    """
    registry = er.async_get(hass)
    prefix = _outlet_unique_id_prefix(serial_number)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.domain == "sensor"
            and entity.unique_id.startswith(prefix)
            and entity.unique_id not in keep
        ):
            _LOGGER.debug("Removing outlet sensor %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


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


class WattBoxOutletSensor(WattBoxEntity, SensorEntity):
    """Power, current or voltage for a single outlet."""

    def __init__(
        self, hass: HomeAssistant, name: str, index: int, sensor_type: str
    ) -> None:
        super().__init__(hass, name)
        self.index: int = index
        self.sensor_type: str = sensor_type
        sensor_def = SENSOR_TYPES[sensor_type]
        outlet_name = self._wattbox.outlets[index].name or f"Outlet {index}"
        self._attr_name = f"{name} {outlet_name} {sensor_def['name']}"
        self._attr_native_unit_of_measurement = sensor_def["unit"]
        self._attr_icon = sensor_def["icon"]
        self._attr_device_class = sensor_def["device_class"]
        self._attr_state_class = sensor_def["state_class"]
        self._attr_unique_id = _outlet_unique_id(
            self._wattbox.serial_number, index, sensor_type
        )
        self._attr_extra_state_attributes["index"] = index

    @callback
    def _update_attrs(self) -> None:
        outlet = self._wattbox.outlets.get(self.index)
        self._attr_native_value = (
            getattr(outlet, self.sensor_type, None) if outlet is not None else None
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
