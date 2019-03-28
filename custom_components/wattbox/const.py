"""Constants for wattbox."""
from homeassistant.const import POWER_WATT

# Base component constants
DOMAIN = "wattbox"
DOMAIN_DATA = "{}_data".format(DOMAIN)
VERSION = "0.1.1"
PLATFORMS = ["binary_sensor", "sensor", "switch"]
REQUIRED_FILES = ["binary_sensor.py", "const.py", "sensor.py", "switch.py"]
ISSUE_URL = "https://github.com/eseglem/hass-wattbox/issues"

STARTUP = """
-------------------------------------------------------------------
{name}
Version: {version}
This is a custom component
If you have any issues with this you need to open an issue here:
{issueurl}
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

# TODO: Device Classes? None OK?
BINARY_SENSOR_TYPES = {
    "audible_alarm": ["Audible Alarm", None],
    "auto_reboot": ["Auto Reboot", None],
    "battery_health": ["Battery Health", None],
    "battery_test": ["Battery Test", None],
    "cloud_status": ["Cloud Status", None],
    "has_ups": ["Has UPS", None],
    "mute": ["Mute", None],
    "power_lost": ["Power Lost", None],
    "safe_voltage_status": ["Safe Voltage Status", None],
}

SENSOR_TYPES = {
    "battery_charge": ["Battery Charge", "%", "mdi:gauge"],
    "battery_load": ["Battery Load", "%", "mdi:gauge"],
    "current_value": ["Current", "A", "mdi:current-ac"],
    "est_run_time": ["Estimated Run Time", "min", "mdi:update"],
    "power_value": ["Power", POWER_WATT, "mdi:lightbulb-outline"],
    "voltage_value": ["Voltage", "V", "mdi:flash-circle"],
}
