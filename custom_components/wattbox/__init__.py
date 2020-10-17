"""
Component to integrate with WattBox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""
from datetime import timedelta
from functools import partial
import logging
import os

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    PERCENTAGE,

)
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
import voluptuous as vol

from .const import (
    BINARY_SENSOR_TYPES,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USER,
    DOMAIN,
    DOMAIN_DATA,
    PLATFORMS,
    REQUIRED_FILES,
    SENSOR_TYPES,
    STARTUP,
    TOPIC_UPDATE,
)

REQUIREMENTS = ["pywattbox>=0.3.0"]

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=1)

ALL_SENSOR_TYPES = list({**BINARY_SENSOR_TYPES, **SENSOR_TYPES}.keys())

WATTBOX_HOST_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USER): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_RESOURCES, default=ALL_SENSOR_TYPES): vol.All(
            cv.ensure_list, [vol.In(ALL_SENSOR_TYPES)]
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.All(cv.ensure_list, [WATTBOX_HOST_SCHEMA]),}, extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Set up this component."""
    from pywattbox import WattBox

    # Print startup message
    _LOGGER.info(STARTUP)

    # Check that all required files are present
    file_check = await check_files(hass)
    if not file_check:
        return False

    hass.data[DOMAIN_DATA] = dict()

    for wattbox_host in config[DOMAIN]:
        # Create DATA dict
        host = wattbox_host.get(CONF_HOST)
        password = wattbox_host.get(CONF_PASSWORD)
        port = wattbox_host.get(CONF_PORT)
        username = wattbox_host.get(CONF_USERNAME)
        name = wattbox_host.get(CONF_NAME)

        hass.data[DOMAIN_DATA][name] = await hass.async_add_executor_job(
            WattBox, host, port, username, password
        )

        # Load platforms
        for platform in PLATFORMS:
            # Get platform specific configuration
            hass.async_create_task(
                discovery.async_load_platform(
                    hass, platform, DOMAIN, wattbox_host, config
                )
            )

        scan_interval = wattbox_host.get(CONF_SCAN_INTERVAL)
        async_track_time_interval(
            hass, partial(scan_update_data, hass=hass, name=name), scan_interval
        )

    # Extra logging to ensure the right outlets are set up.
    _LOGGER.debug(", ".join([str(v) for k, v in hass.data[DOMAIN_DATA].items()]))
    _LOGGER.debug(repr(hass.data[DOMAIN_DATA]))
    for _, wattbox in hass.data[DOMAIN_DATA].items():
        _LOGGER.debug("%s has %s outlets", wattbox, len(wattbox.outlets))
        for o in wattbox.outlets:
            _LOGGER.debug("Outlet: %s - %s", o, repr(o))

    return True


# Setup scheduled updates
async def scan_update_data(_, hass, name):
    _LOGGER.debug(
        "Scan Update Data: %s - %s",
        hass.data[DOMAIN_DATA][name],
        repr(hass.data[DOMAIN_DATA][name]),
    )
    await update_data(hass, name)


async def update_data(hass, name):
    """Update data."""
    # This is where the main logic to update platform data goes.
    try:
        await hass.async_add_executor_job(hass.data[DOMAIN_DATA][name].update)
        _LOGGER.debug(
            "Updated: %s - %s",
            hass.data[DOMAIN_DATA][name],
            repr(hass.data[DOMAIN_DATA][name]),
        )
        # Send update to topic for entities to see
        async_dispatcher_send(hass, TOPIC_UPDATE.format(DOMAIN, name))
    except Exception as error:  # pylint: disable=broad-except
        _LOGGER.error("Could not update data - %s", error)


async def check_files(hass):
    """Return bool that indicates if all files are present."""
    # Verify that the user downloaded all files.
    base = f"{hass.config.path()}/custom_components/{DOMAIN}"
    missing = []
    for file in REQUIRED_FILES:
        fullpath = f"{base}/{file}"
        if not os.path.exists(fullpath):
            missing.append(file)

    if missing:
        _LOGGER.critical("The following files are missing: %s", str(missing))
        returnvalue = False
    else:
        returnvalue = True

    return returnvalue
