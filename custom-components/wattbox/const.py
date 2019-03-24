"""Constants for wattbox."""
# Base component constants
DOMAIN = 'wattbox'
DOMAIN_DATA = '{}_data'.format(DOMAIN)
VERSION = '0.0.1'
PLATFORMS = ['sensor', 'switch']
REQUIRED_FILES = ['binary_sensor.py', 'const.py', 'sensor.py', 'switch.py']
ISSUE_URL = 'https://github.com/eseglem/hass-wattbox/issues'

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
ICON = 'mdi:power'
PLUG_ICON = 'mdi:power-socket-us'

# Configuration
CONF_NAME = 'name'

# Defaults
DEFAULT_NAME = DOMAIN
DEFAULT_PASSWORD = DOMAIN
DEFAULT_PORT = 80
DEFAULT_USER = DOMAIN
