"""Constants for wattbox."""
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    DEVICE_CLASS_CONNECTIVITY,
    DEVICE_CLASS_PLUG,
    DEVICE_CLASS_PROBLEM,
    DEVICE_CLASS_SAFETY,
)
from homeassistant.const import POWER_WATT, TIME_MINUTES, PERCENTAGE, VOLT

# Base component constants
DOMAIN = "wattbox"
DOMAIN_DATA = f"{DOMAIN}_data"
VERSION = "0.5.4"
PLATFORMS = ["binary_sensor", "sensor", "switch"]
REQUIRED_FILES = ["binary_sensor.py", "const.py", "sensor.py", "switch.py"]
ISSUE_URL = "https://github.com/eseglem/hass-wattbox/issues"

STARTUP = f"""
-------------------------------------------------------------------
{DOMAIN}
Version: {VERSION}
This is a custom component
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

# Icons
ICON = "mdi:power"
PLUG_ICON = "mdi:power-socket-us"

# Defaults
DEFAULT_NAME = "WattBox"
DEFAULT_PASSWORD = DOMAIN
DEFAULT_PORT = 80
DEFAULT_USER = DOMAIN
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

TOPIC_UPDATE = "{}_data_update_{}"

BINARY_SENSOR_TYPES = {
    "audible_alarm": {"name": "Audible Alarm", "device_class": None, "flipped": False},
    "auto_reboot": {"name": "Auto Reboot", "device_class": None, "flipped": False},
    "battery_health": {
        "name": "Battery Health",
        "device_class": DEVICE_CLASS_PROBLEM,
        "flipped": True,
    },
    "battery_test": {"name": "Battery Test", "device_class": None, "flipped": False},
    "cloud_status": {
        "name": "Cloud Status",
        "device_class": DEVICE_CLASS_CONNECTIVITY,
        "flipped": False,
    },
    "has_ups": {"name": "Has UPS", "device_class": None, "flipped": False},
    "mute": {"name": "Mute", "device_class": None, "flipped": False},
    "power_lost": {"name": "Power", "device_class": DEVICE_CLASS_PLUG, "flipped": True},
    "safe_voltage_status": {
        "name": "Safe Voltage Status",
        "device_class": DEVICE_CLASS_SAFETY,
        "flipped": True,
    },
}

SENSOR_TYPES = {
    "battery_charge": ["Battery Charge", PERCENTAGE, "mdi:gauge"],
    "battery_load": ["Battery Load", PERCENTAGE, "mdi:gauge"],
    "current_value": ["Current", "A", "mdi:current-ac"],
    "est_run_time": ["Estimated Run Time", TIME_MINUTES, "mdi:update"],
    "power_value": ["Power", POWER_WATT, "mdi:lightbulb-outline"],
    "voltage_value": ["Voltage", VOLT, "mdi:flash-circle"],
}
