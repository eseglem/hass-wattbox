"""Button platform for wattbox."""

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from pywattbox.base import BaseWattBox, Outlet

from .const import CONF_NAME_REGEXP, CONF_SKIP_REGEXP, DOMAIN_DATA, RESTART_ICON
from .entity import WattBoxEntity
from .session import async_run_command
from .switch import resolve_outlet_name, validate_regex

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Setup button platform."""
    try:
        name: str = entry.data[CONF_NAME]

        entities: list[WattBoxEntity] = []
        wattbox: BaseWattBox = hass.data[DOMAIN_DATA][name]

        # Sourced from the options, exactly as in switch.py. A reset button
        # power-cycles its outlet, so a skipped outlet must not get one either
        # -- otherwise suppressing the switch only removes the obvious way to
        # cut power to protected equipment, not the one-click way.
        name_regexp = validate_regex(entry.options, CONF_NAME_REGEXP)
        skip_regexp = validate_regex(entry.options, CONF_SKIP_REGEXP)

        for i, outlet in wattbox.outlets.items():
            outlet_name = outlet.name or ""

            # Skip outlets if they match regex
            if skip_regexp and skip_regexp.search(outlet_name):
                _LOGGER.debug("Skipping outlet #%s - %s", i, outlet_name)
                continue

            outlet_name = resolve_outlet_name(name_regexp, outlet_name)

            _LOGGER.debug("Adding outlet reset #%s - %s", i, outlet_name)
            entities.append(WattBoxResetButton(hass, name, i, outlet_name))

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up button platform: %s", err)
        raise PlatformNotReady from err


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup button platform. (legacy YAML support)."""
    name: str = discovery_info[CONF_NAME]

    entities: list[WattBoxEntity] = []
    wattbox: BaseWattBox = hass.data[DOMAIN_DATA][name]

    name_regexp = validate_regex(config, CONF_NAME_REGEXP)
    skip_regexp = validate_regex(config, CONF_SKIP_REGEXP)

    for i, outlet in wattbox.outlets.items():
        outlet_name = outlet.name or ""

        # Skip outlets if they match regex
        if skip_regexp and skip_regexp.search(outlet_name):
            _LOGGER.debug("Skipping outlet #%s - %s", i, outlet_name)
            continue

        outlet_name = resolve_outlet_name(name_regexp, outlet_name)

        _LOGGER.debug("Adding outlet reset #%s - %s", i, outlet_name)
        entities.append(WattBoxResetButton(hass, name, i, outlet_name))

    async_add_entities(entities)


class WattBoxResetButton(WattBoxEntity, ButtonEntity):
    """WattBox reset button class."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = RESTART_ICON
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
        """Update the sensor (legacy poll fallback)."""
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        self._attr_extra_state_attributes["name"] = self._outlet.name
        self._attr_extra_state_attributes["method"] = self._outlet.method
        self._attr_extra_state_attributes["index"] = self._outlet.index

    async def async_press(self) -> None:
        """Issue a reset to the outlet."""
        _LOGGER.debug("Resetting On: %s - %s", self._wattbox, self._outlet)
        # Trigger the action on the wattbox.
        await async_run_command(self._wattbox, self._outlet.async_reset)
        if self._coordinator is not None:
            await self._coordinator.async_request_refresh()
