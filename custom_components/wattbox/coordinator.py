"""DataUpdateCoordinator for WattBox."""

import logging
from datetime import timedelta
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BaseWattBox, WattBoxAuthError, WattBoxError, WattBoxLoggedOut

_LOGGER = logging.getLogger(__name__)

# An HTTP session can lapse while the device is perfectly healthy, so one
# logged-out poll says nothing about the credentials. The client has already
# retried each of these on a session built moments earlier; only ask for new
# credentials once that has been turned away this many polls running.
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
        except WattBoxAuthError as err:
            self._logged_out_polls = 0
            raise ConfigEntryAuthFailed(
                f"Authentication failed for WattBox: {err}"
            ) from err
        except WattBoxLoggedOut as err:
            self._logged_out_polls += 1
            if self._logged_out_polls >= _LOGGED_OUT_POLLS_BEFORE_REAUTH:
                # Fresh sessions, refused this many times in a row: the
                # credentials on the entry are no longer the device's.
                raise ConfigEntryAuthFailed(
                    f"WattBox turned away {self._logged_out_polls} logins in a row: {err}"
                ) from err
            raise UpdateFailed(f"Error communicating with WattBox: {err}") from err
        except WattBoxError as err:
            # A timeout or connection error says nothing about the
            # credentials, so it breaks any run of logged-out polls.
            self._logged_out_polls = 0
            raise UpdateFailed(f"Error communicating with WattBox: {err}") from err

        self._logged_out_polls = 0
        return self.wattbox
