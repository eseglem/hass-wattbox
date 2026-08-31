"""Connection lifecycle for the WattBox drivers.

pywattbox 0.9.0's HTTP driver builds one ``httpx.AsyncClient`` in
``HttpWattBox.__init__``, reuses it for the life of the object, and offers no
way to close it -- the class has no ``async_close``, unlike the telnet/SSH
driver. That client keeps a cookie jar and a keep-alive pool pointed at the
WattBox's very small web server, and three things go wrong as a result:

* When the device's session lapses it answers ``200 OK`` with a page that
  redirects to ``login.htm``, in place of the ``wattbox_info.xml`` payload.
  pywattbox hands that page to its XML parser, matches none of the tags it
  looks for, and returns without touching a single value -- so the poll counts
  as a success and every entity keeps reporting whatever it last saw.
* The lapsed session then sticks. The client replays the same cookie, the
  device answers ``400 Bad Request`` to everything that follows, and only
  reloading the entry -- which happens to build a new client -- clears it.
* Reloads and failed config-flow probes drop the client without closing it,
  leaking sockets to a device that accepts only a handful at a time.

The driver in 0.8.0 opened a fresh connection per request and had none of
these problems, so this module gives the integration ownership of the client
and puts that behaviour back: no cookie is carried between requests, no
connection is kept alive between polls, a logged-out reply raises instead of
passing for data, and the session can be closed or rebuilt on demand.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, Final, Protocol, cast

import httpx
from pywattbox.base import BaseWattBox

_LOGGER = logging.getLogger(__name__)

# The web UI bounces unauthenticated requests to this page rather than
# answering with an error status, so the marker is the only thing separating a
# logged-out reply from real data.
_LOGIN_REDIRECT_MARKER: Final[bytes] = b"login.htm"

# A poll that has not come back by now is not going to; the coordinator polls
# again in 30 seconds by default.
_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(10.0)

# No keep-alive. A connection held open to this device is a connection that can
# rot, and a rotten one takes every later request down with it.
_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_keepalive_connections=0, max_connections=4
)


class WattBoxLoggedOut(Exception):
    """The device served its login page where data was expected."""


class _HttpDriver(Protocol):
    """The part of pywattbox's HTTP driver this module reaches into."""

    async_client: httpx.AsyncClient


def _as_http_driver(wattbox: BaseWattBox | None) -> _HttpDriver | None:
    """Return the driver typed for client access, or None if it is not HTTP.

    Duck-typed on purpose: importing ``HttpWattBox`` to check would pull in
    BeautifulSoup for telnet and SSH users who never touch the HTTP driver.
    """
    if isinstance(getattr(wattbox, "async_client", None), httpx.AsyncClient):
        return cast(_HttpDriver, wattbox)
    return None


def is_http_wattbox(wattbox: BaseWattBox | None) -> bool:
    """Whether this device is driven over HTTP."""
    return _as_http_driver(wattbox) is not None


def is_auth_error(err: BaseException) -> bool:
    """Best-effort detection of auth failures across pywattbox transports.

    The HTTP driver surfaces 401/403 from httpx, while the SSH/telnet driver
    raises scrapli exceptions whose class name contains ``Auth``. A login page
    is deliberately not counted here: on HTTP it usually means the session
    lapsed, not that the credentials are wrong, and the two need different
    handling.
    """
    if isinstance(err, httpx.HTTPStatusError):
        return getattr(err.response, "status_code", None) in (401, 403)

    return "auth" in type(err).__name__.lower()


def is_session_error(err: BaseException) -> bool:
    """Whether a failure looks like a dead session rather than a dead device.

    A refused or nonsensical answer means the device is reachable and talking,
    just not to us, which a clean session may well fix. Timeouts, connection
    errors, and broken responses mean it is not answering properly at all, and
    retrying those only doubles how long entities take to go unavailable.
    """
    return isinstance(err, (WattBoxLoggedOut, httpx.HTTPStatusError))


async def _async_inspect_response(
    client: httpx.AsyncClient, response: httpx.Response
) -> None:
    """Drop the session cookie, and reject a reply that is the login page."""
    # httpx has already filed any `Set-Cookie` by the time response hooks run,
    # so emptying the jar here is what keeps the next request from replaying a
    # session the device has since forgotten.
    client.cookies.clear()

    # Anything else is reported by the driver's own `raise_for_status()`.
    if response.status_code != 200:
        return

    await response.aread()
    if _LOGIN_REDIRECT_MARKER in response.content:
        raise WattBoxLoggedOut(f"{response.request.url} answered with the login page")


def _new_client() -> httpx.AsyncClient:
    """Build a client that cannot carry a session between requests."""
    # `verify=False`: the driver speaks plain HTTP, and building the default
    # SSL context reads the CA bundle from disk -- blocking work that has no
    # business happening in the event loop.
    client = httpx.AsyncClient(verify=False, timeout=_TIMEOUT, limits=_LIMITS)
    client.event_hooks = {"response": [partial(_async_inspect_response, client)]}
    return client


async def _async_aclose(client: Any) -> None:
    """Close a client, if that is what it is."""
    if not isinstance(client, httpx.AsyncClient):
        return
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001 - closing must never raise
        _LOGGER.debug("Error closing WattBox HTTP client", exc_info=True)


async def _async_install_client(driver: _HttpDriver) -> None:
    """Give the driver a fresh managed client, closing the one it had."""
    previous = driver.async_client
    driver.async_client = _new_client()
    await _async_aclose(previous)


async def async_create_http_wattbox(
    host: str, user: str, password: str, port: int
) -> BaseWattBox:
    """Create an HTTP WattBox whose session this integration owns.

    Mirrors ``pywattbox.http_wattbox.async_create_http_wattbox``, except the
    managed client is installed before the first request instead of after, so a
    device that answers the initial fetch with its login page fails setup
    rather than coming up with no outlets and no error.
    """
    from pywattbox.http_wattbox import HttpWattBox

    wattbox = HttpWattBox(host=host, user=user, password=password, port=port)
    # The constructor already built a client of its own. Swap it out before it
    # is ever used, and close it so it is not left holding a socket.
    await _async_install_client(cast(_HttpDriver, wattbox))

    try:
        await wattbox.async_get_initial()
        await wattbox.async_update()
    except BaseException:
        await async_close_wattbox(wattbox)
        raise

    return wattbox


async def async_reset_session(wattbox: BaseWattBox) -> bool:
    """Throw away the current HTTP session and start a clean one.

    Returns whether there was one to reset -- telnet and SSH devices have no
    equivalent, and pywattbox reconnects those itself.
    """
    driver = _as_http_driver(wattbox)
    if driver is None:
        return False

    _LOGGER.debug("Rebuilding HTTP session for %s", wattbox)
    await _async_install_client(driver)
    return True


async def async_run_command(
    wattbox: BaseWattBox, command: Callable[[], Awaitable[None]]
) -> None:
    """Send a command, rebuilding a dead HTTP session and retrying once.

    Only failures where the device demonstrably did not act are retried. A
    login page or an error status means the command was refused; a connection
    that broke mid-request may well have delivered it first, and an outlet
    reset is not something to send twice by accident.
    """
    try:
        await command()
    except (WattBoxLoggedOut, httpx.HTTPStatusError) as err:
        if is_auth_error(err) or not await async_reset_session(wattbox):
            raise
        _LOGGER.debug("Retrying command on a new session after: %s", err)
        await command()


async def async_close_wattbox(wattbox: BaseWattBox | None) -> None:
    """Release whatever the driver is holding open.

    The 800 series caps concurrent connections, so a session that is dropped
    without being closed eventually locks us out of the device entirely. The
    telnet/SSH driver closes through ``async_close``; the HTTP driver has no
    such method, so its client -- ours since creation -- is closed here.
    """
    if wattbox is None:
        return

    async_close = getattr(wattbox, "async_close", None)
    if async_close is not None:
        try:
            await async_close()
        except Exception:  # noqa: BLE001 - closing must never raise
            _LOGGER.debug("Error closing WattBox connection", exc_info=True)

    await _async_aclose(getattr(wattbox, "async_client", None))
