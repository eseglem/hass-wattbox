"""
Component to integrate with wattbox.

For more details about this component, please refer to
https://github.com/eseglem/hass-wattbox/
"""

import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from getmac import get_mac_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RESOURCES,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    PlatformNotReady,
)
from homeassistant.helpers import discovery
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .api import BaseWattBox, WattBoxAuthError, WattBoxError
from .connection import async_connect
from .const import (
    BINARY_SENSOR_TYPES,
    CONF_CONNECTION_TYPE,
    CONF_NAME_REGEXP,
    CONF_OUTLET_METERING,
    CONF_SKIP_REGEXP,
    DEFAULT_NAME,
    DEFAULT_OUTLET_METERING,
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
from .coordinator import WattBoxCoordinator

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
            wattbox = await async_connect(hass, host, port, username, password)
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
        # Stopped with Home Assistant, which closes the device first.
        async_track_time_interval(
            hass,
            partial(update_data, hass=hass, name=name),
            scan_interval,
            cancel_on_shutdown=True,
        )

    # YAML devices are never unloaded, so this is the only point at which
    # their sessions can be handed back.
    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP,
        partial(_async_close_devices, hass, [w.get(CONF_NAME) for w in domain_config]),
    )

    # Extra logging to ensure the right outlets are set up.
    _LOGGER.debug(", ".join([str(v) for _, v in hass.data[DOMAIN_DATA].items()]))
    _LOGGER.debug(repr(hass.data[DOMAIN_DATA]))
    for _, wattbox in hass.data[DOMAIN_DATA].items():
        _LOGGER.debug("%s has %s outlets", wattbox, len(wattbox.outlets))
        for outlet in wattbox.outlets:
            _LOGGER.debug("Outlet: %s - %s", outlet, repr(outlet))

    return True


async def _async_close_devices(
    hass: HomeAssistant, names: list[str], _event: Event
) -> None:
    """Close the sessions of the named devices."""
    for name in names:
        if (wattbox := hass.data.get(DOMAIN_DATA, {}).get(name)) is not None:
            await wattbox.async_close()


async def update_data(_dt: datetime, hass: HomeAssistant, name: str) -> None:
    """Update data."""

    wattbox = hass.data[DOMAIN_DATA].get(name)
    if wattbox is None:
        _LOGGER.error("No WattBox instance found for %s", name)
        return

    try:
        await wattbox.async_update()
        _LOGGER.debug("Updated: %s - %s", wattbox, repr(wattbox))
        # Send update to topic for entities to see
        async_dispatcher_send(hass, TOPIC_UPDATE.format(DOMAIN, name))
    except Exception as error:
        _LOGGER.error(
            "Could not update data for %s (%s) - %s", repr(wattbox), wattbox, error
        )


def _resolve_scan_interval(entry: ConfigEntry) -> timedelta:
    """Poll interval, preferring the options flow value.

    The options flow stores plain seconds. Entry data may hold either seconds
    or a timedelta, depending on whether it came from YAML import.
    """
    if (seconds := entry.options.get(CONF_SCAN_INTERVAL)) is not None:
        return timedelta(seconds=float(seconds))

    configured = entry.data.get(CONF_SCAN_INTERVAL)
    if isinstance(configured, timedelta):
        return configured
    if configured is not None:
        return timedelta(seconds=float(configured))
    return DEFAULT_SCAN_INTERVAL


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WattBox from a config entry."""
    if DOMAIN_DATA not in hass.data:
        hass.data[DOMAIN_DATA] = {}

    # Adopt the entry title so renaming the entry in the UI actually renames
    # the device and its entities. Without this the integration keeps using
    # the name captured when the entry was created, and a rename silently does
    # nothing -- the only way to change the name is to delete and re-add.
    # Done before the update listener is registered, so it cannot loop: after
    # the first pass title and name agree.
    if entry.title and entry.title != entry.data.get(CONF_NAME):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NAME: entry.title}
        )

    # Extract configuration
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    name = entry.data[CONF_NAME]

    # Options take precedence over the values captured at config time, so the
    # options flow can retune a live entry without re-adding it.
    options = entry.options
    scan_interval = _resolve_scan_interval(entry)

    # Per-outlet metering costs one extra round trip per outlet on every poll,
    # so it is opt-in. The client only honours it on models that report
    # per-outlet power at all, and drops it if the device turns out not to.
    wattbox: BaseWattBox
    try:
        wattbox = await async_connect(
            hass,
            host,
            port,
            username,
            password,
            transport=entry.data.get(CONF_CONNECTION_TYPE),
            outlet_metering=options.get(CONF_OUTLET_METERING, DEFAULT_OUTLET_METERING),
        )
    except WattBoxAuthError as error:
        raise ConfigEntryAuthFailed(
            f"WattBox rejected the credentials: {error}"
        ) from error
    except WattBoxError as error:
        raise ConfigEntryNotReady(f"Cannot reach WattBox {host}: {error}") from error

    hass.data[DOMAIN_DATA][name] = wattbox

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Home Assistant does not unload entries when it stops, so without this a
    # restart abandons the session instead of closing it. The 800 series caps
    # how many it accepts, and holds abandoned ones until they time out.
    async def _async_close_on_stop(_event: Event) -> None:
        await wattbox.async_close()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_close_on_stop)
    )

    # Everything past the point the session exists has to hand it back if it
    # fails. Home Assistant does not call `async_unload_entry` for a setup that
    # raised, so nothing else would close it, and it retries on a backoff --
    # leaking one session per attempt until the device refuses new connections.
    try:
        # Look up MAC address once via executor (blocking ARP lookup)
        mac_address = await hass.async_add_executor_job(
            partial(get_mac_address, ip=host)
        )

        # Create coordinator for polling and availability tracking
        coordinator = WattBoxCoordinator(
            hass, wattbox, name, scan_interval, mac_address=mac_address
        )
        await coordinator.async_config_entry_first_refresh()

        # Telnet and SSH devices push `~OutletStatus` when outlets change
        # (seen after a switch command, #66). Apply it without waiting for
        # the next poll. HTTP devices never push, so this is a no-op there.
        entry.async_on_unload(wattbox.add_listener(coordinator.async_update_listeners))

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][name] = coordinator

        # Forward entry setup to platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN_DATA, {}).pop(name, None)
        hass.data.get(DOMAIN, {}).pop(name, None)
        await wattbox.async_close()
        raise

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so new options take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    name = entry.data[CONF_NAME]

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        wattbox = hass.data.get(DOMAIN_DATA, {}).pop(name, None)
        hass.data.get(DOMAIN, {}).pop(name, None)
        if wattbox is not None:
            await wattbox.async_close()

    return unload_ok
