"""DataUpdateCoordinator for WattBox."""

import logging
from datetime import timedelta
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pywattbox.base import BaseWattBox

from .session import (
    WattBoxLoggedOut,
    async_reset_session,
    is_auth_error,
    is_session_error,
)

_LOGGER = logging.getLogger(__name__)

# An HTTP session can lapse while the device is perfectly healthy, so one
# logged-out poll says nothing about the credentials. Only ask for new ones
# once a session built moments earlier has been turned away this many polls
# running.
_LOGGED_OUT_POLLS_BEFORE_REAUTH: Final[int] = 3


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
        self._logged_out_polls = 0

    async def _async_update_data(self) -> BaseWattBox:
        """Fetch data from the WattBox device."""
        try:
            await self.wattbox.async_update()
        except Exception as err:
            if is_auth_error(err):
                raise ConfigEntryAuthFailed(
                    f"Authentication failed for WattBox: {err}"
                ) from err

            if not is_session_error(err):
                raise UpdateFailed(f"Error communicating with WattBox: {err}") from err

            # The device answered, it just would not serve us. Over HTTP that
            # is usually a session the driver has outlived: it replays the dead
            # one on every request from then on, which is why recovering used
            # to take a manual reload. Build a clean session and try once more.
            _LOGGER.debug("Retrying update on a new session after: %s", err)
            if not await async_reset_session(self.wattbox):
                raise UpdateFailed(f"Error communicating with WattBox: {err}") from err

            try:
                await self.wattbox.async_update()
            except Exception as retry_err:
                raise self._retry_failure(retry_err) from retry_err

        self._logged_out_polls = 0
        return self.wattbox

    def _retry_failure(self, err: Exception) -> Exception:
        """Pick the failure to report when a clean session was refused too."""
        if is_auth_error(err):
            return ConfigEntryAuthFailed(f"Authentication failed for WattBox: {err}")

        if isinstance(err, WattBoxLoggedOut):
            self._logged_out_polls += 1
            if self._logged_out_polls >= _LOGGED_OUT_POLLS_BEFORE_REAUTH:
                # Sessions built seconds ago, refused this many times in a row:
                # the credentials on the entry are no longer the device's.
                return ConfigEntryAuthFailed(
                    f"WattBox turned away {self._logged_out_polls} logins in a row: {err}"
                )

        return UpdateFailed(f"Error communicating with WattBox: {err}")
