"""Creating a WattBox client from Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.importlib import async_import_module

from .api import BaseWattBox, async_create_wattbox, transport_for_port


async def async_connect(
    hass: HomeAssistant,
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    transport: str | None = None,
    outlet_metering: bool = False,
) -> BaseWattBox:
    """Connect to a WattBox over *transport*, or the one *port* implies.

    Entries created before the connection type was stored, and YAML
    configuration, only have the port to go on.

    Anything the chosen client imports lazily is imported here first, off the
    event loop, so Home Assistant does not flag a blocking import.
    """
    transport = transport or transport_for_port(port)
    if transport == "ssh":
        await async_import_module(hass, "asyncssh")
    elif transport == "http":
        await async_import_module(hass, "encodings.ascii")

    return await async_create_wattbox(
        host,
        port,
        username,
        password,
        transport=transport,
        outlet_metering=outlet_metering,
    )
