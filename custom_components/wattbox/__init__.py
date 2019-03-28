"""
Component to integrate with WattBox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""
import os
import logging
from datetime import timedelta

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import discovery
from homeassistant.util import Throttle
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RESOURCES,
    CONF_SWITCHES,
    CONF_USERNAME,
)
from .const import (
    BINARY_SENSOR_TYPES,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_USER,
    DOMAIN_DATA,
    DOMAIN,
    ISSUE_URL,
    PLATFORMS,
    REQUIRED_FILES,
    SENSOR_TYPES,
    STARTUP,
    VERSION,
)

REQUIREMENTS = ["pywattbox>=0.0.4"]

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=5)

ALL_SENSOR_TYPES = {**BINARY_SENSOR_TYPES, **SENSOR_TYPES}

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.string,
                vol.Optional(CONF_USERNAME, default=DEFAULT_USER): cv.string,
                vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Optional(CONF_RESOURCES, default=ALL_SENSOR_TYPES): vol.All(
                    cv.ensure_list, [vol.In(ALL_SENSOR_TYPES)]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up this component."""
    from pywattbox import WattBox

    # Print startup message
    startup = STARTUP.format(name=DOMAIN, version=VERSION, issueurl=ISSUE_URL)
    _LOGGER.info(startup)

    # Check that all required files are present
    file_check = await check_files(hass)
    if not file_check:
        return False

    # Create DATA dict
    host = config[DOMAIN].get(CONF_HOST)
    password = config[DOMAIN].get(CONF_PASSWORD)
    port = config[DOMAIN].get(CONF_PORT)
    username = config[DOMAIN].get(CONF_USERNAME)

    hass.data[DOMAIN_DATA] = WattBox(host, port, username, password)

    # Load platforms
    for platform in PLATFORMS:
        # Get platform specific configuration
        platform_config = config[DOMAIN]

        hass.async_create_task(
            discovery.async_load_platform(
                hass, platform, DOMAIN, platform_config, config
            )
        )
    return True


@Throttle(MIN_TIME_BETWEEN_UPDATES)
async def update_data(hass):
    """Update data."""
    # This is where the main logic to update platform data goes.
    try:
        hass.data[DOMAIN_DATA].update()
    except Exception as error:  # pylint: disable=broad-except
        _LOGGER.error("Could not update data - %s", error)


async def check_files(hass):
    """Return bool that indicates if all files are present."""
    # Verify that the user downloaded all files.
    base = "{}/custom_components/{}/".format(hass.config.path(), DOMAIN)
    missing = []
    for file in REQUIRED_FILES:
        fullpath = "{}{}".format(base, file)
        if not os.path.exists(fullpath):
            missing.append(file)

    if missing:
        _LOGGER.critical("The following files are missing: %s", str(missing))
        returnvalue = False
    else:
        returnvalue = True

    return returnvalue
