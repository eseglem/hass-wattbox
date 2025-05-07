"""Switch platform for wattbox."""

import logging
import re
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from pywattbox.base import BaseWattBox, Outlet

from .const import CONF_NAME_REGEXP, CONF_SKIP_REGEXP, DOMAIN_DATA, PLUG_ICON
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


def validate_regex(config: ConfigType, key: str) -> re.Pattern[str] | None:
    regexp_str: str = config.get(key, "")
    if regexp_str:
        try:
            return re.compile(regexp_str)
        except re.error:
            _LOGGER.error("Invalid %s: %s", key, regexp_str)
    return None


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup switch platform."""
    name: str = discovery_info[CONF_NAME]

    entities: list[WattBoxEntity] = []
    wattbox: BaseWattBox = hass.data[DOMAIN_DATA][name]

    name_regexp = validate_regex(config, CONF_NAME_REGEXP)
    skip_regexp = validate_regex(config, CONF_SKIP_REGEXP)

    skipped_an_outlet = False
    for i, outlet in wattbox.outlets.items():
        outlet_name = outlet.name or ""

        # Skip outlets if they match regex
        if skip_regexp and skip_regexp.search(outlet_name):
            _LOGGER.debug("Skipping switch #%s - %s", i, outlet_name)
            skipped_an_outlet = True
            continue

        if name_regexp:
            if matched := name_regexp.search(outlet_name):
                outlet_name = matched.group()
                try:
                    outlet_name = matched.group(1)
                except re.error:
                    pass

        _LOGGER.debug("Adding switch #%s - %s", i, outlet_name)
        entities.append(WattBoxBinarySwitch(hass, name, i, outlet_name))

    # Skip the master switch iff any of the outlets are skipped
    if not skipped_an_outlet:
        entities.append(WattBoxMasterSwitch(hass, name))
    else:
        _LOGGER.debug(
            "Skipping master switch because an outlet was skipped for %s", name
        )

    async_add_entities(entities)


class WattBoxBinarySwitch(WattBoxEntity, SwitchEntity):
    """WattBox switch class."""

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_icon = PLUG_ICON
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
            self._attr_name = f"{name} {outlet_name}"
        else:
            self._attr_name = f"{name} Outlet {index}"
        self._attr_unique_id = f"{self._wattbox.serial_number}-switch-{index}"

    async def async_update(self) -> None:
        """Update the sensor."""
        # Check the data and update the value.
        self._attr_is_on = self._outlet.status

        # Set/update attributes
        self._attr_extra_state_attributes["name"] = self._outlet.name
        self._attr_extra_state_attributes["method"] = self._outlet.method
        self._attr_extra_state_attributes["index"] = self._outlet.index

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on the switch."""
        _LOGGER.debug("Turning On: %s - %s", self._wattbox, self._outlet)
        _LOGGER.debug(
            "Current Outlet Before: %s - %s", self._outlet.status, repr(self._outlet)
        )
        # Update state first so it is not stale.
        self._attr_is_on = True
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self._outlet.async_turn_on()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the switch."""
        _LOGGER.debug("Turning Off: %s - %s", self._wattbox, self._outlet)
        _LOGGER.debug(
            "Current Outlet Before: %s - %s", self._outlet.status, repr(self._outlet)
        )
        # Update state first so it is not stale.
        self._attr_is_on = False
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self._outlet.async_turn_off()


class WattBoxMasterSwitch(WattBoxBinarySwitch):
    """WattBox master switch class."""

    _outlet: Outlet | None  # type: ignore[assignment]

    def __init__(self, hass: HomeAssistant, name: str) -> None:
        super().__init__(hass, name, 0)
        self._outlet = self._wattbox.master_outlet
        self._attr_name = f"{name} Master Switch"
        self._attr_unique_id = f"{self._wattbox.serial_number}-switch-master"

    async def async_update(self) -> None:
        """Update the sensor."""
        if self._outlet is not None:
            # Check the data and update the value.
            self._attr_is_on = self._outlet.status

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        if self._outlet is not None:
            await super().async_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        if self._outlet is not None:
            await super().async_turn_on(**kwargs)
