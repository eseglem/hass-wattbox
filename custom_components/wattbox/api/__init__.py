"""Async client for SnapAV WattBox power distribution units.

Kept free of Home Assistant imports, so it can be tested on its own and
lifted out into a standalone library if the integration is ever proposed for
Home Assistant core, which requires one.

Two interfaces, chosen by the connection type:

* ``telnet`` (port 23) and ``ssh`` (port 22): the Integration Protocol, see
  :mod:`.ip`. This is the only interface on the 800 series.
* ``http`` (port 80): the XML API of the 150/250/300/700 series, see
  :mod:`.http`.
"""

from __future__ import annotations

from .exceptions import (
    WattBoxAuthError,
    WattBoxCommandError,
    WattBoxConnectionError,
    WattBoxError,
    WattBoxLoggedOut,
    WattBoxProtocolError,
)
from .models import BaseWattBox, Commands, MasterSwitch, Outlet

__all__ = [
    "BaseWattBox",
    "Commands",
    "MasterSwitch",
    "Outlet",
    "WattBoxAuthError",
    "WattBoxCommandError",
    "WattBoxConnectionError",
    "WattBoxError",
    "WattBoxLoggedOut",
    "WattBoxProtocolError",
    "async_create_wattbox",
    "transport_for_port",
]


def transport_for_port(port: int) -> str:
    """The interface a port number implies: 22 SSH, 23 telnet, else HTTP."""
    if port == 22:
        return "ssh"
    if port == 23:
        return "telnet"
    return "http"


async def async_create_wattbox(
    host: str,
    port: int,
    user: str,
    password: str,
    *,
    transport: str | None = None,
    outlet_metering: bool = False,
) -> BaseWattBox:
    """Connect, read the device's identity, and take a first reading.

    Whatever was opened is closed again if any of that fails, so a failed
    attempt never holds one of the device's few sessions.
    """
    transport = transport or transport_for_port(port)
    wattbox: BaseWattBox
    if transport == "http":
        from .http import HttpWattBox

        wattbox = HttpWattBox(host, user, password, port)
    else:
        from .ip import IpWattBox

        wattbox = IpWattBox(host, user, password, port, transport)

    try:
        await wattbox.async_get_initial()
        wattbox.outlet_metering = outlet_metering and wattbox.supports_outlet_metering
        await wattbox.async_update()
    except BaseException:
        await wattbox.async_close()
        raise
    return wattbox
