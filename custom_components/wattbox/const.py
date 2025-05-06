"""Constants for wattbox."""

from datetime import timedelta
from typing import Dict, Final, List, TypedDict

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    UnitOfElectricPotential,
    PERCENTAGE,
    UnitOfPower,
    UnitOfTime,
)

# Base component constants
DOMAIN: Final[str] = "wattbox"
DOMAIN_DATA: Final[str] = f"{DOMAIN}_data"
VERSION: Final[str] = "0.8.2"
PLATFORMS: Final[List[str]] = ["binary_sensor", "sensor", "switch"]
REQUIRED_FILES: Final[List[str]] = [
    "binary_sensor.py",
    "const.py",
    "sensor.py",
    "switch.py",
]
ISSUE_URL: Final[str] = "https://github.com/eseglem/hass-wattbox/issues"

STARTUP: Final[
    str
] = f"""
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

# Defaults
DEFAULT_NAME: Final[str] = "WattBox"
DEFAULT_PASSWORD: Final[str] = DOMAIN
DEFAULT_PORT: Final[int] = 80
DEFAULT_USER: Final[str] = DOMAIN
DEFAULT_SCAN_INTERVAL: Final[timedelta] = timedelta(seconds=30)

TOPIC_UPDATE: Final[str] = "{}_data_update_{}"


class _BinarySensorDict(TypedDict):
    """TypedDict for use in BINARY_SENSOR_TYPES"""

    name: str
    device_class: BinarySensorDeviceClass | None
    flipped: bool


BINARY_SENSOR_TYPES: Final[Dict[str, _BinarySensorDict]] = {
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


SENSOR_TYPES: Final[Dict[str, _SensorTypeDict]] = {
    "battery_charge": {
        "name": "Battery Charge",
        "unit": PERCENTAGE,
        "icon": "mdi:battery",
    },
    "battery_load": {"name": "Battery Load", "unit": PERCENTAGE, "icon": "mdi:gauge"},
    "current_value": {"name": "Current", "unit": "A", "icon": "mdi:current-ac"},
    "est_run_time": {
        "name": "Estimated Run Time",
        "unit": UnitOfTime.MINUTES,
        "icon": "mdi:timer",
    },
    "power_value": {
        "name": "Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:lightbulb-outline",
    },
    "voltage_value": {
        "name": "Voltage",
        "unit": UnitOfElectricPotential.VOLT,
        "icon": "mdi:lightning-bolt-circle",
    },
}
