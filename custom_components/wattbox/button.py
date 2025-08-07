"""Button platform for wattbox."""

import logging
import re
from typing import Any, List

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from pywattbox.base import BaseWattBox, Outlet
from .switch import validate_regex

from .const import CONF_NAME_REGEXP, CONF_SKIP_REGEXP, DOMAIN_DATA, RESTART_ICON
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup button platform."""
    name: str = discovery_info[CONF_NAME]

    entities: List[WattBoxEntity] = []
    wattbox: BaseWattBox = hass.data[DOMAIN_DATA][name]

    name_regexp = validate_regex(config, CONF_NAME_REGEXP)
    skip_regexp = validate_regex(config, CONF_SKIP_REGEXP)

    for i, outlet in wattbox.outlets.items():
        outlet_name = outlet.name or ""

        # Skip outlets if they match regex
        if skip_regexp and skip_regexp.search(outlet_name):
            _LOGGER.debug("Skipping outlet #%s - %s", i, outlet_name)
            continue

        if name_regexp:
            if matched := name_regexp.search(outlet_name):
                outlet_name = matched.group()
                try:
                    outlet_name = matched.group(1)
                except re.error:
                    pass

        _LOGGER.debug("Adding outlet reset #%s - %s", i, outlet_name)
        entities.append(WattBoxResetButton(hass, name, i, outlet_name))

    async_add_entities(entities)


class WattBoxResetButton(WattBoxEntity, ButtonEntity):
    """WattBox reset button class."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_should_poll = False
    _outlet: Outlet

    def __init__(
        self, hass: HomeAssistant, name: str, index: int, outlet_name: str = ""
    ) -> None:
        super().__init__(hass, name, index)
        # Master Outlet (index == 0) is not in the oulets dict
        if index:
            self._outlet = self._wattbox.outlets[index]
        # Determine outlet name
        if outlet_name := outlet_name.strip():
            self._attr_name = f"{name} {outlet_name} Reset"
        else:
            self._attr_name = f"{name} Outlet {index} Reset"
        self._attr_unique_id = f"{self._wattbox.serial_number}-button-reset-{index}"

    async def async_update(self) -> None:
        """Update the sensor."""
        # Set/update attributes
        self._attr_extra_state_attributes["name"] = self._outlet.name
        self._attr_extra_state_attributes["method"] = self._outlet.method
        self._attr_extra_state_attributes["index"] = self._outlet.index

    async def async_press(self) -> None:
        """Issue a reset to the outlet."""
        _LOGGER.debug("Resetting On: %s - %s", self._wattbox, self._outlet)
        # Trigger the action on the wattbox.
        await self._outlet.async_reset()

    @property
    def icon(self) -> str | None:
        """Return the icon of this button."""
        return RESTART_ICON

    @property
    def device_class(self) -> str:
        return ButtonDeviceClass.RESTART

    @property
    def entity_category(self):
        return EntityCategory.CONFIG
