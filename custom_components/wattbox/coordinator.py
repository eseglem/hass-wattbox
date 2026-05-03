"""DataUpdateCoordinator for WattBox."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pywattbox.base import BaseWattBox

_LOGGER = logging.getLogger(__name__)


def _is_auth_error(err: BaseException) -> bool:
    """Best-effort detection of auth failures across pywattbox transports.

    The HTTP transport surfaces 401/403 from httpx, while the SSH/telnet
    transport raises scrapli exceptions whose class name contains ``Auth``.
    """
    try:
        from httpx import HTTPStatusError

        if isinstance(err, HTTPStatusError):
            status = getattr(err.response, "status_code", None)
            if status in (401, 403):
                return True
    except ImportError:  # pragma: no cover - httpx is always installed via pywattbox[http]
        pass

    return "auth" in type(err).__name__.lower()


class WattBoxCoordinator(DataUpdateCoordinator[BaseWattBox]):
    """Coordinator to manage fetching WattBox data from the device.

    When the device is unreachable, UpdateFailed is raised, which causes
    all entities using this coordinator to automatically become unavailable.
    When the device comes back, entities automatically become available again.
    Authentication failures raise ConfigEntryAuthFailed which triggers the
    reauth flow in the UI.
    """

    wattbox: BaseWattBox
    mac_address: str | None

    def __init__(
        self,
        hass: HomeAssistant,
        wattbox: BaseWattBox,
        name: str,
        scan_interval: timedelta,
        mac_address: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"WattBox {name}",
            update_interval=scan_interval,
        )
        self.wattbox = wattbox
        self.mac_address = mac_address

    async def _async_update_data(self) -> BaseWattBox:
        """Fetch data from the WattBox device."""
        try:
            await self.wattbox.async_update()
            return self.wattbox
        except Exception as err:
            if _is_auth_error(err):
                raise ConfigEntryAuthFailed(
                    f"Authentication failed for WattBox: {err}"
                ) from err
            raise UpdateFailed(
                f"Error communicating with WattBox: {err}"
            ) from err
