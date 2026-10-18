"""HTTP client for the ``wattbox_info.xml`` API of the 150/250/300/700 series.

The 800 series has no such API: it answers every request with
``401 Unauthorized``, credentials or not, and is driven over telnet instead.

The web server on these units is very small, and three behaviours of it
shape this module. They were worked around in the integration's
``session.py`` while pywattbox was in use (v1.2.1, discussion #68):

* When its session lapses it answers ``200 OK`` with a page that redirects to
  ``login.htm`` in place of the data, so a status code alone cannot tell a
  logged-out reply from a good one.
* A lapsed session sticks: replaying its cookie draws ``400 Bad Request`` on
  everything that follows. So no cookie is carried between requests, no
  connection is kept alive between polls, and a refused request is retried
  once on a brand new client.
* Some models answer bad credentials with a ``200`` page that is neither the
  data nor the login redirect (#67). Anything that is not recognisably the
  status document is therefore rejected instead of being read as a device
  with no outlets.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Final, TypeVar

import httpx

from .exceptions import (
    WattBoxAuthError,
    WattBoxConnectionError,
    WattBoxLoggedOut,
    WattBoxProtocolError,
)
from .models import BaseWattBox, Commands, MasterSwitch

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

DEFAULT_TIMEOUT: Final[float] = 10.0

_INFO_PATH: Final[str] = "/wattbox_info.xml"
_CONTROL_PATH: Final[str] = "/control.cgi"
_LOGIN_MARKER: Final[bytes] = b"login.htm"

# Any of these identifies the status document. Checked so that a page which
# happens to be well-formed XML -- `<html><body>...</body></html>` is -- is
# not mistaken for a device with nothing on it.
_IDENTIFYING_TAGS: Final[tuple[str, ...]] = ("hardware_version", "outlet_status")

# No keep-alive: a connection held open to this device is one that can rot.
_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_keepalive_connections=0, max_connections=4
)


class _NotStatusData(Exception):
    """A 200 reply that is not the status document."""


def _parse_info(response: httpx.Response) -> ET.Element:
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as err:
        raise _NotStatusData from err
    if not any(root.find(tag) is not None for tag in _IDENTIFYING_TAGS):
        raise _NotStatusData
    return root


def _flag(root: ET.Element, tag: str) -> bool | None:
    """A ``1``/``0`` field, or None when the model does not report it."""
    text = root.findtext(tag)
    return None if text is None else text.strip() == "1"


def _number(text: str) -> float:
    """Integers stay integers, so readings display as the device reports them."""
    try:
        return int(text)
    except ValueError:
        return float(text)


class HttpWattBox(BaseWattBox):
    """A WattBox driven over its XML API."""

    transport = "http"

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 80,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(host, user, password, port)
        self.base_url: str = f"http://{host}:{port}"
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _new_client(self) -> httpx.AsyncClient:
        # `verify=False`: the API is plain HTTP, and building a verifying SSL
        # context reads the CA bundle from disk inside the event loop.
        return httpx.AsyncClient(
            verify=False,
            timeout=self._timeout,
            limits=_LIMITS,
            auth=httpx.BasicAuth(self.user, self.password),
        )

    async def _reset_client(self) -> None:
        """Throw the current session away; the next request starts a new one."""
        if (client := self._client) is not None:
            self._client = None
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - closing must never raise
                _LOGGER.debug("Error closing WattBox HTTP client", exc_info=True)

    async def _request(
        self,
        path: str,
        params: dict[str, int] | None = None,
        parse: Callable[[httpx.Response], _T] | None = None,
    ) -> _T | None:
        """GET *path*, retrying once on a new session if the device refuses it.

        Only refusals are retried: an error status, the login page, or a page
        that is not data all mean the device answered without acting. A
        timeout or broken connection is not retried, since the request may
        well have been carried out -- and an outlet reset is not something to
        send twice by accident.

        Raises:
            WattBoxAuthError: ``401`` or ``403``.
            WattBoxLoggedOut: the login page, or anything else that is not
                data, twice running.
            WattBoxConnectionError: the device could not be reached, or kept
                answering with an error status.
        """
        url = f"{self.base_url}{path}"
        for attempt in range(2):
            if self._client is None:
                self._client = self._new_client()
            client = self._client
            try:
                response = await client.get(url, params=params)
            except httpx.TimeoutException as err:
                raise WattBoxConnectionError(f"timed out requesting {url}") from err
            except httpx.HTTPError as err:
                raise WattBoxConnectionError(f"error requesting {url}: {err}") from err
            finally:
                # Never replay a session cookie the device may have forgotten.
                client.cookies.clear()

            _LOGGER.debug("%s: %s -> %s", self.host, path, response.status_code)
            error: Exception
            if response.status_code in (401, 403):
                raise WattBoxAuthError(
                    f"{url} answered {response.status_code}. If this is an "
                    "800-series WattBox, it has no HTTP API: use telnet"
                )
            if response.status_code >= 400:
                error = WattBoxConnectionError(f"{url} answered {response.status_code}")
            elif _LOGIN_MARKER in response.content:
                error = WattBoxLoggedOut(f"{url} answered with the login page")
            else:
                try:
                    return parse(response) if parse is not None else None
                except _NotStatusData:
                    error = WattBoxLoggedOut(
                        f"{url} answered, but not with the WattBox status data; "
                        "this usually means the credentials were not accepted"
                    )

            if attempt == 0:
                _LOGGER.debug(
                    "%s: retrying on a new session after: %s", self.host, error
                )
                await self._reset_client()
                continue
            raise error
        raise AssertionError("unreachable")

    async def _fetch_info(self) -> ET.Element:
        root = await self._request(_INFO_PATH, parse=_parse_info)
        assert root is not None
        return root

    async def async_get_initial(self) -> None:
        root = await self._fetch_info()
        self.hardware_version = root.findtext("hardware_version")
        self.has_ups = root.findtext("hasUPS") == "1"
        self.hostname = root.findtext("host_name") or ""
        self.serial_number = root.findtext("serial_number") or ""

        # Count the outlets from their states rather than the model number:
        # some models have outlets that are always on and not reported.
        if (statuses := root.findtext("outlet_status")) is not None:
            count = len(statuses.split(","))
        elif self.hardware_version:
            try:
                count = int(self.hardware_version.rsplit("-", 1)[-1])
            except ValueError:
                count = 0
        else:
            count = 0
        self._set_outlet_layout(count)
        self.master_outlet = MasterSwitch(self)
        self._apply(root)

    async def async_update(self) -> None:
        self._apply(await self._fetch_info())

    def _apply(self, root: ET.Element) -> None:
        try:
            self._apply_fields(root)
        except (ValueError, TypeError) as err:
            raise WattBoxProtocolError(f"unreadable status data: {err}") from err

    def _apply_fields(self, root: ET.Element) -> None:
        self._apply_status(root)
        self._apply_power(root)
        if self.has_ups:
            self._apply_ups(root)
        self._apply_outlets(root)
        if isinstance(self.master_outlet, MasterSwitch):
            self.master_outlet.refresh()

    def _apply_status(self, root: ET.Element) -> None:
        for tag in (
            "audible_alarm",
            "auto_reboot",
            "cloud_status",
            "mute",
            "power_lost",
            "safe_voltage_status",
        ):
            if (value := _flag(root, tag)) is not None:
                setattr(self, tag, value)

    def _apply_power(self, root: ET.Element) -> None:
        if (text := root.findtext("power_value")) is not None:
            self.power_value = _number(text)
        # Current and voltage are reported in tenths.
        if (text := root.findtext("current_value")) is not None:
            self.current_value = _number(text) / 10
        if (text := root.findtext("voltage_value")) is not None:
            self.voltage_value = _number(text) / 10

    def _apply_ups(self, root: ET.Element) -> None:
        for tag in ("battery_charge", "battery_load", "est_run_time"):
            if (text := root.findtext(tag)) is not None:
                setattr(self, tag, int(_number(text)))
        for tag in ("battery_health", "battery_test"):
            if (value := _flag(root, tag)) is not None:
                setattr(self, tag, value)

    def _apply_outlets(self, root: ET.Element) -> None:
        if (text := root.findtext("outlet_method")) is not None:
            for index, method in enumerate(text.split(","), start=1):
                if outlet := self.outlets.get(index):
                    outlet.method = method.strip() == "1"
        if (text := root.findtext("outlet_name")) is not None:
            self._apply_outlet_names(text.split(","))
        if (text := root.findtext("outlet_status")) is not None:
            self._apply_outlet_statuses([s.strip() == "1" for s in text.split(",")])

    async def async_send_command(self, outlet: int, command: Commands) -> None:
        if outlet not in self.outlets:
            raise ValueError(f"{self} has no outlet {outlet}")
        await self._request(
            _CONTROL_PATH, params={"outlet": outlet, "command": command.value}
        )
        self.outlets[outlet].status = command is not Commands.OFF
        if isinstance(self.master_outlet, MasterSwitch):
            self.master_outlet.refresh()

    async def async_close(self) -> None:
        await self._reset_client()
