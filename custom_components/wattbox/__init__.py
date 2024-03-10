"""
Component to integrate with wattbox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""
import logging
import os
from datetime import datetime
from functools import partial
from typing import Final, List

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

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
    CONF_NAME_REGEXP,
    CONF_SKIP_REGEXP
)

REQUIREMENTS: Final[List[str]] = ["pywattbox>=0.4.0"]

_LOGGER = logging.getLogger(__name__)

ALL_SENSOR_TYPES: Final[List[str]] = [*BINARY_SENSOR_TYPES.keys(), *SENSOR_TYPES.keys()]

CONF_USE_OUTLET_NAMES = 'use_outlet_names'

WATTBOX_HOST_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USER): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_NAME_REGEXP): cv.string,
        vol.Optional(CONF_SKIP_REGEXP): cv.string,
        vol.Optional(CONF_USE_OUTLET_NAMES, default=False): cv.boolean,
        vol.Optional(CONF_RESOURCES, default=ALL_SENSOR_TYPES): vol.All(
            cv.ensure_list, [vol.In(ALL_SENSOR_TYPES)]
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(cv.ensure_list, [WATTBOX_HOST_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this component."""
    from pywattbox import WattBox  # pylint: disable=import-outside-toplevel

    # Print startup message
    _LOGGER.info(STARTUP)

    # Check that all required files are present
    file_check = await check_files(hass)
    if not file_check:
        return False

    hass.data[DOMAIN_DATA] = dict()

    for wattbox_host in config[DOMAIN]:
        _LOGGER.debug(repr(wattbox_host))
        # Create DATA dict
        host = wattbox_host.get(CONF_HOST)
        password = wattbox_host.get(CONF_PASSWORD)
        port = wattbox_host.get(CONF_PORT)
        username = wattbox_host.get(CONF_USERNAME)
        name = wattbox_host.get(CONF_NAME)
        name_regexp = wattbox_host.get(CONF_NAME_REGEXP)
        skip_regexp = wattbox_host.get(CONF_SKIP_REGEXP)
        use_outlet_names = wattbox_host.get(CONF_USE_OUTLET_NAMES)

        wattbox = await hass.async_add_executor_job(
            WattBox, host, port, username, password
        )
        hass.data[DOMAIN_DATA][name] = { "wattbox": wattbox, "name_regexp": name_regexp, "skip_regexp": skip_regexp, "use_outlet_names": use_outlet_names }

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
            hass, partial(update_data, hass=hass, name=name), scan_interval
        )

    # Extra logging to ensure the right outlets are set up.
    _LOGGER.debug(", ".join([str(v) for _, v in hass.data[DOMAIN_DATA].items()]))
    _LOGGER.debug(repr(hass.data[DOMAIN_DATA]))
    for _, config in hass.data[DOMAIN_DATA].items():
        wattbox = config['wattbox']
        _LOGGER.debug("%s has %s outlets%s", wattbox, len(wattbox.outlets), " [use_outlet_names]" if config['use_outlet_names'] else "")
        for outlet in wattbox.outlets:
            _LOGGER.debug("Outlet: %s - %s [%s]", outlet, repr(outlet), outlet.name)

    return True


async def update_data(_: datetime, hass: HomeAssistant, name: str) -> None:
    """Update data."""

    # This is where the main logic to update platform data goes.
    try:
        wattbox = hass.data[DOMAIN_DATA][name]['wattbox']
        await hass.async_add_executor_job(wattbox.update)
        _LOGGER.debug(
            "Updated: %s - %s",
            wattbox,
            repr(wattbox),
        )
        # Send update to topic for entities to see
        async_dispatcher_send(hass, TOPIC_UPDATE.format(DOMAIN, name))
    except Exception as error:  # pylint: disable=broad-except
        _LOGGER.error("Could not update data - %s", error)


async def check_files(hass: HomeAssistant) -> bool:
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
        return False
    return True
