"""
Component to integrate with wattbox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""

import asyncio
import logging
from datetime import datetime
from functools import partial
from typing import Final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
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
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.importlib import async_import_module
from homeassistant.helpers.typing import ConfigType
from pywattbox.base import BaseWattBox

from .const import (
    BINARY_SENSOR_TYPES,
    CONF_NAME_REGEXP,
    CONF_SKIP_REGEXP,
    DEFAULT_NAME,
    DEFAULT_PASSWORD,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_USER,
    DOMAIN,
    DOMAIN_DATA,
    PLATFORMS,
    SENSOR_TYPES,
    STARTUP,
    TOPIC_UPDATE,
)

REQUIREMENTS: Final[list[str]] = ["pywattbox>=0.7.2"]

_LOGGER = logging.getLogger(__name__)

ALL_SENSOR_TYPES: Final[list[str]] = [*BINARY_SENSOR_TYPES.keys(), *SENSOR_TYPES.keys()]

WATTBOX_HOST_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USER): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_NAME_REGEXP): cv.string,
        vol.Optional(CONF_SKIP_REGEXP): cv.string,
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


async def _async_create_wattbox(hass, host, port, username, password):
    """Create a WattBox instance based on port (IP or HTTP)."""
    if port in (22, 23):
        _LOGGER.debug("Importing IP Wattbox")
        from pywattbox.ip_wattbox import async_create_ip_wattbox

        # Pre-import the transport plugin to avoid blocking call issues
        transport = "asyncssh" if port == 22 else "asynctelnet"
        await async_import_module(
            hass, f"scrapli.transport.plugins.{transport}.transport"
        )

        _LOGGER.debug("Creating IP WattBox")
        wattbox = await async_create_ip_wattbox(
            host=host, user=username, password=password, port=port
        )
    else:
        _LOGGER.debug("Importing HTTP Wattbox")
        from pywattbox.http_wattbox import async_create_http_wattbox

        # Pre-import the encoding to avoid blocking call issues
        await async_import_module(hass, "encodings.ascii")

        _LOGGER.debug("Creating HTTP WattBox")
        wattbox = await async_create_http_wattbox(
            host=host, user=username, password=password, port=port
        )

    return wattbox


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this component."""
    _LOGGER.info(STARTUP)

    hass.data[DOMAIN_DATA] = {}

    # Only process YAML config if it exists
    domain_config = config.get(DOMAIN, [])
    if domain_config:
        _LOGGER.debug(
            "Found YAML configuration for %d WattBox device(s)", len(domain_config)
        )
    else:
        _LOGGER.debug("No YAML configuration found, will rely on config entries")

    for wattbox_host in domain_config:
        _LOGGER.debug(repr(wattbox_host))
        # Create DATA dict
        host = wattbox_host.get(CONF_HOST)
        password = wattbox_host.get(CONF_PASSWORD)
        port = wattbox_host.get(CONF_PORT)
        username = wattbox_host.get(CONF_USERNAME)
        name = wattbox_host.get(CONF_NAME)

        wattbox: BaseWattBox
        try:
            wattbox = await _async_create_wattbox(hass, host, port, username, password)
        except Exception as error:
            _LOGGER.error("Error creating WattBox instance: %s", error)
            raise PlatformNotReady from error

        hass.data[DOMAIN_DATA][name] = wattbox

        # Load platforms
        for platform in PLATFORMS:
            # Get platform specific configuration
            hass.async_create_task(
                discovery.async_load_platform(
                    hass, platform, DOMAIN, wattbox_host, config
                )
            )

        # Use the scan interval to trigger updates
        scan_interval = wattbox_host.get(CONF_SCAN_INTERVAL)
        async_track_time_interval(
            hass, partial(update_data, hass=hass, name=name), scan_interval
        )

    # Extra logging to ensure the right outlets are set up.
    _LOGGER.debug(", ".join([str(v) for _, v in hass.data[DOMAIN_DATA].items()]))
    _LOGGER.debug(repr(hass.data[DOMAIN_DATA]))
    for _, wattbox in hass.data[DOMAIN_DATA].items():
        _LOGGER.debug("%s has %s outlets", wattbox, len(wattbox.outlets))
        for outlet in wattbox.outlets:
            _LOGGER.debug("Outlet: %s - %s", outlet, repr(outlet))

    return True


async def update_data(_dt: datetime, hass: HomeAssistant, name: str) -> None:
    """Update data."""

    # This is where the main logic to update platform data goes.
    try:
        wattbox = hass.data[DOMAIN_DATA][name]
        await wattbox.async_update()
        _LOGGER.debug("Updated: %s - %s", wattbox, repr(wattbox))
        # Send update to topic for entities to see
        async_dispatcher_send(hass, TOPIC_UPDATE.format(DOMAIN, name))
    except Exception as error:
        _LOGGER.error("Could not update data - %s", error)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WattBox from a config entry."""
    if DOMAIN_DATA not in hass.data:
        hass.data[DOMAIN_DATA] = {}

    # Extract configuration
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    name = entry.data[CONF_NAME]
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    wattbox: BaseWattBox
    try:
        wattbox = await _async_create_wattbox(hass, host, port, username, password)
    except Exception as error:
        _LOGGER.error("Error creating WattBox instance: %s", error)
        raise PlatformNotReady from error

    hass.data[DOMAIN_DATA][name] = wattbox

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Use the scan interval to trigger updates
    async_track_time_interval(
        hass, partial(update_data, hass=hass, name=name), scan_interval
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    name = entry.data[CONF_NAME]

    # Unload platforms
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok:
        # Remove the wattbox from data
        if name in hass.data[DOMAIN_DATA]:
            del hass.data[DOMAIN_DATA][name]

    return unload_ok

