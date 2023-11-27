"""
Component to integrate with wattbox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""
import logging
from datetime import datetime
from functools import partial
from typing import Final, List

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from pywattbox.base import BaseWattBox

from .const import (
    DOMAIN,
    DOMAIN_DATA,
    PLATFORMS,
    STARTUP,
    TOPIC_UPDATE,
)

REQUIREMENTS: Final[List[str]] = ["pywattbox>=0.7.2"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up this component."""
    _LOGGER.info(STARTUP)

    hass.data[DOMAIN_DATA] = {}

    for wattbox_host in config[DOMAIN]:
        _LOGGER.debug(repr(wattbox_host))
        # Create DATA dict
        host = wattbox_host.get(CONF_HOST)
        password = wattbox_host.get(CONF_PASSWORD)
        port = wattbox_host.get(CONF_PORT)
        username = wattbox_host.get(CONF_USERNAME)
        name = wattbox_host.get(CONF_NAME)

        wattbox: BaseWattBox
        if port in (22, 23):
            _LOGGER.debug("Importing IP Wattbox")
            from pywattbox.ip_wattbox import async_create_ip_wattbox

            _LOGGER.debug("Creating IP WattBox")
            wattbox = await async_create_ip_wattbox(
                host=host, user=username, password=password, port=port
            )
        else:
            _LOGGER.debug("Importing HTTP Wattbox")
            from pywattbox.http_wattbox import async_create_http_wattbox

            _LOGGER.debug("Creating HTTP WattBox")
            wattbox = await async_create_http_wattbox(
                host=host, user=username, password=password, port=port
            )
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
