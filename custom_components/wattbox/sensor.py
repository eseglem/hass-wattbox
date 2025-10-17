"""Sensor platform for wattbox."""

import logging
from datetime import timedelta

from homeassistant.components.integration.sensor import IntegrationSensor
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_RESOURCES, STATE_UNKNOWN, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN, DOMAIN_DATA, SENSOR_TYPES
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
        clean_name = conf_name.replace(" ", "_").lower()
        entities: list[WattBoxSensor | WattBoxIntegrationSensor] = []

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

        # TODO: Add a setting for this, default to true?
        # Add an IntegrationSensor, so end users don't have to manually configure it.
        entities.append(
            WattBoxIntegrationSensor(
                hass=hass,
                name=conf_name,
                integration_method="trapezoidal",
                sensor_name=f"{conf_name} Total Energy",
                round_digits=2,
                source_entity=f"sensor.{clean_name}_power",
                unique_id=f"{clean_name}_total_energy",
                unit_prefix="k",
                unit_time=UnitOfTime.HOURS,
                max_sub_interval=timedelta(minutes=5),
            )
        )

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
        clean_name = conf_name.replace(" ", "_").lower()
        entities: list[WattBoxSensor | WattBoxIntegrationSensor] = []

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
            WattBoxIntegrationSensor(
                hass=hass,
                name=conf_name,
                integration_method="trapezoidal",
                sensor_name=f"{conf_name} Total Energy",
                round_digits=2,
                source_entity=f"sensor.{clean_name}_power",
                unique_id=f"{clean_name}_total_energy",
                unit_prefix="k",
                unit_time=UnitOfTime.HOURS,
                max_sub_interval=timedelta(minutes=5),
            )
        )

        async_add_entities(entities)
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


class WattBoxIntegrationSensor(IntegrationSensor):
    """WattBox Integration Sensor that includes device info."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        integration_method: str,
        sensor_name: str,
        source_entity: str,
        unique_id: str,
        unit_prefix: str,
        unit_time: str,
        round_digits: int = 2,
        max_sub_interval: timedelta = None,
    ) -> None:
        # Use a default max_sub_interval if none provided
        if max_sub_interval is None:
            max_sub_interval = timedelta(minutes=5)

        # Initialize IntegrationSensor with all required parameters
        super().__init__(
            hass=hass,
            integration_method=integration_method,
            name=sensor_name,
            round_digits=round_digits,
            source_entity=source_entity,
            unique_id=unique_id,
            unit_prefix=unit_prefix,
            unit_time=unit_time,
            max_sub_interval=max_sub_interval,
        )

        # Get the WattBox instance to create device info
        self._wattbox = hass.data[DOMAIN_DATA][name]

        # Set device info manually
        from getmac import get_mac_address
        from homeassistant.const import ATTR_CONNECTIONS
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers.entity import DeviceInfo

        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._wattbox.serial_number)},
            name=name,
            manufacturer="WattBox",
            model=getattr(self._wattbox, "hardware_version", None) or "WattBox",
            sw_version=getattr(self._wattbox, "firmware_version", None),
            serial_number=self._wattbox.serial_number,
            configuration_url=f"http://{self._wattbox.host}:{self._wattbox.port}"
            if hasattr(self._wattbox, "host") and hasattr(self._wattbox, "port")
            else None,
        )

        # Add MAC address connection if host is available
        if hasattr(self._wattbox, "host") and self._wattbox.host:
            try:
                mac_address = get_mac_address(ip=self._wattbox.host)
                if mac_address:
                    device_info[ATTR_CONNECTIONS] = {
                        (dr.CONNECTION_NETWORK_MAC, mac_address)
                    }
            except Exception:
                pass  # MAC address lookup is optional

        self._attr_device_info = device_info
