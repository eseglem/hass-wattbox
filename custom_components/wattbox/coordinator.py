"""DataUpdateCoordinator for WattBox."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pywattbox.base import BaseWattBox

from datetime import timedelta

_LOGGER = logging.getLogger(__name__)


class WattBoxCoordinator(DataUpdateCoordinator[BaseWattBox]):
    """Coordinator to manage fetching WattBox data from the device.

    When the device is unreachable, UpdateFailed is raised, which causes
    all entities using this coordinator to automatically become unavailable.
    When the device comes back, entities automatically become available again.
    """

    wattbox: BaseWattBox

    def __init__(
        self,
        hass: HomeAssistant,
        wattbox: BaseWattBox,
        name: str,
        scan_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"WattBox {name}",
            update_interval=scan_interval,
        )
        self.wattbox = wattbox

    async def _async_update_data(self) -> BaseWattBox:
        """Fetch data from the WattBox device.

        Raises UpdateFailed on any communication error, which signals
        to all listening entities that the device is unavailable.
        """
        try:
            await self.wattbox.async_update()
            return self.wattbox
        except Exception as err:
            raise UpdateFailed(
                f"Error communicating with WattBox: {err}"
            ) from err
