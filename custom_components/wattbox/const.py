"""Constants for wattbox."""

from datetime import timedelta
from typing import Final, TypedDict

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTime,
)

# Base component constants
DOMAIN: Final[str] = "wattbox"
DOMAIN_DATA: Final[str] = f"{DOMAIN}_data"
VERSION: Final[str] = "1.1.0"
PLATFORMS: Final[list[str]] = ["binary_sensor", "button", "sensor", "switch"]
ISSUE_URL: Final[str] = "https://github.com/eseglem/hass-wattbox/issues"

STARTUP: Final[str] = f"""
-------------------------------------------------------------------
{DOMAIN}
Version: {VERSION}
This is a custom component
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

# Icons
ICON: Final[str] = "mdi:power"
PLUG_ICON: Final[str] = "mdi:power-socket-us"
RESTART_ICON: Final[str] = "mdi:restart"

# Defaults
DEFAULT_NAME: Final[str] = "WattBox"
DEFAULT_PASSWORD: Final[str] = DOMAIN
DEFAULT_PORT: Final[int] = 80
DEFAULT_USER: Final[str] = DOMAIN
DEFAULT_SCAN_INTERVAL: Final[timedelta] = timedelta(seconds=30)

TOPIC_UPDATE: Final[str] = "{}_data_update_{}"

# config options
CONF_NAME_REGEXP: Final[str] = "name_regexp"
CONF_SKIP_REGEXP: Final[str] = "skip_regexp"

#: Per-outlet metering. On by default, matching long-standing behaviour, and
#: selectable both when adding a device and afterwards. Turning it off saves
#: one request per outlet on every poll, which is worth having on a large
#: fleet, but it is the installer's call rather than a silent default.
CONF_OUTLET_METERING: Final[str] = "outlet_metering"
DEFAULT_OUTLET_METERING: Final[bool] = True

#: The sensors created per outlet when metering is on, in display order.
#: Keys into `SENSOR_TYPES`, so the units, icons and device classes match the
#: whole-unit equivalents. Only the IP (telnet/SSH) driver fills these -- the
#: HTTP XML API has no per-outlet values -- which is why creation is gated on
#: the presence of `outlet_power_status`, an attribute only `IpWattBox` defines.
OUTLET_SENSOR_TYPES: Final[tuple[str, ...]] = (
    "power_value",
    "current_value",
    "voltage_value",
)

# Connection type. Chosen explicitly rather than inferred from the port,
# because guessing sends 800-series users to the HTTP driver, which answers
# with a 401 and no indication of why.
CONF_CONNECTION_TYPE: Final[str] = "connection_type"
CONNECTION_HTTP: Final[str] = "http"
CONNECTION_TELNET: Final[str] = "telnet"
CONNECTION_SSH: Final[str] = "ssh"
CONNECTION_TYPES: Final[dict[str, int]] = {
    CONNECTION_TELNET: 23,
    CONNECTION_HTTP: 80,
    CONNECTION_SSH: 22,
}
DEFAULT_CONNECTION_TYPE: Final[str] = CONNECTION_TELNET

#: Entities that only carry meaning when a UPS is attached. On a WattBox with
#: no UPS the device still answers `?UPSStatus`, but with a zeroed placeholder
#: tuple, so these would sit at 0/off forever while still being polled and
#: recorded. They are not created when `has_ups` is false, and appear on their
#: own once a UPS is attached and the entry reloads.
UPS_ONLY_SENSORS: Final[frozenset[str]] = frozenset(
    {"battery_charge", "battery_load", "est_run_time"}
)
UPS_ONLY_BINARY_SENSORS: Final[frozenset[str]] = frozenset(
    {"audible_alarm", "battery_health", "battery_test", "mute"}
)

#: Attributes the IP (telnet/SSH) driver never populates -- there is no
#: equivalent in the Integration Protocol, so they are not created on those
#: units rather than sitting at `unknown` indefinitely.
HTTP_ONLY_BINARY_SENSORS: Final[frozenset[str]] = frozenset({"cloud_status"})


class _BinarySensorDict(TypedDict):
    """TypedDict for use in BINARY_SENSOR_TYPES"""

    name: str
    device_class: BinarySensorDeviceClass | None
    flipped: bool


BINARY_SENSOR_TYPES: Final[dict[str, _BinarySensorDict]] = {
    "audible_alarm": {
        "name": "Audible Alarm",
        "device_class": BinarySensorDeviceClass.SOUND,
        "flipped": False,
    },
    "auto_reboot": {"name": "Auto Reboot", "device_class": None, "flipped": False},
    "battery_health": {
        "name": "Battery Health",
        "device_class": BinarySensorDeviceClass.PROBLEM,
        "flipped": True,
    },
    "battery_test": {"name": "Battery Test", "device_class": None, "flipped": False},
    "cloud_status": {
        "name": "Cloud Status",
        "device_class": BinarySensorDeviceClass.CONNECTIVITY,
        "flipped": False,
    },
    "has_ups": {"name": "Has UPS", "device_class": None, "flipped": False},
    "mute": {"name": "Mute", "device_class": None, "flipped": False},
    "power_lost": {
        "name": "Power",
        "device_class": BinarySensorDeviceClass.PLUG,
        "flipped": True,
    },
    "safe_voltage_status": {
        "name": "Safe Voltage Status",
        "device_class": BinarySensorDeviceClass.SAFETY,
        "flipped": True,
    },
}


class _SensorTypeDict(TypedDict):
    name: str
    unit: str
    icon: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None


SENSOR_TYPES: Final[dict[str, _SensorTypeDict]] = {
    "battery_charge": {
        "name": "Battery Charge",
        "unit": PERCENTAGE,
        "icon": "mdi:battery",
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_load": {
        "name": "Battery Load",
        "unit": PERCENTAGE,
        "icon": "mdi:gauge",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "current_value": {
        "name": "Current",
        "unit": UnitOfElectricCurrent.AMPERE,
        "icon": "mdi:current-ac",
        "device_class": SensorDeviceClass.CURRENT,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "est_run_time": {
        "name": "Estimated Run Time",
        "unit": UnitOfTime.MINUTES,
        "icon": "mdi:timer",
        "device_class": SensorDeviceClass.DURATION,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "power_value": {
        "name": "Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:lightbulb-outline",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "voltage_value": {
        "name": "Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "icon": "mdi:lightning-bolt-circle",
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}
