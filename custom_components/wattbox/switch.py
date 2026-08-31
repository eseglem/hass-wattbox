"""Switch platform for wattbox."""

import logging
import re
from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from pywattbox.base import BaseWattBox, Outlet

from .const import CONF_NAME_REGEXP, CONF_SKIP_REGEXP, DOMAIN_DATA, PLUG_ICON
from .entity import WattBoxEntity
from .session import async_run_command

_LOGGER = logging.getLogger(__name__)


def validate_regex(config: Mapping[str, Any], key: str) -> re.Pattern[str] | None:
    """Compile the pattern at *key*, or None if absent or invalid.

    Takes a Mapping rather than a dict: the YAML path passes a ConfigType,
    while the config-entry path passes `entry.options`, which is a
    MappingProxyType.
    """
    regexp_str: str = config.get(key, "")
    if regexp_str:
        try:
            return re.compile(regexp_str)
        except re.error:
            _LOGGER.error("Invalid %s: %s", key, regexp_str)
    return None


def resolve_outlet_name(name_regexp: re.Pattern[str] | None, outlet_name: str) -> str:
    """Shorten *outlet_name* with *name_regexp*, as the docs describe it.

    The first capture group wins when the pattern has one that participated in
    the match, otherwise the whole match is used. Patterns without a capture
    group are explicitly supported, so asking for group 1 has to tolerate its
    absence: `Match.group(1)` raises `IndexError`, not `re.error`, and the
    previous `except re.error` let it escape and take the platform down.

    A pattern that does not match leaves the name untouched. It selects which
    part of a name to keep, never which outlets exist -- that is `skip_regexp`.
    """
    if name_regexp is None:
        return outlet_name

    matched = name_regexp.search(outlet_name)
    if matched is None:
        return outlet_name

    # `re.groups` counts the groups in the pattern; `group(1)` still returns
    # None when the group is optional and did not participate.
    if matched.re.groups and (group := matched.group(1)) is not None:
        return group

    return matched.group()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WattBox switches from a config entry."""
    try:
        name: str = entry.data[CONF_NAME]

        entities: list[WattBoxEntity] = []
        wattbox: BaseWattBox = hass.data[DOMAIN_DATA][name]

        # Sourced from the options flow. Without this, every outlet becomes a
        # switch with no way to exclude any -- including outlets powering the
        # network equipment this integration depends on.
        name_regexp = validate_regex(entry.options, CONF_NAME_REGEXP)
        skip_regexp = validate_regex(entry.options, CONF_SKIP_REGEXP)

        skipped_an_outlet = False
        for i, outlet in wattbox.outlets.items():
            outlet_name = outlet.name or ""

            # Check to skip outlets
            if skip_regexp and skip_regexp.search(outlet_name):
                _LOGGER.debug("Skipping Outlet: %s - %s", i, outlet_name)
                skipped_an_outlet = True
                continue

            # Shortens the name, and never decides whether the outlet exists.
            # This path used to drop every outlet the pattern did not match,
            # which contradicted both the option's description and the YAML
            # behaviour, and silently removed switches for outlets the user
            # only meant to rename.
            outlet_name = resolve_outlet_name(name_regexp, outlet_name)

            try:
                entities.append(WattBoxBinarySwitch(hass, name, i, outlet_name))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxBinarySwitch: %s", err)
                raise PlatformNotReady from err

        # Add the master switch if no outlets were skipped and the device
        # actually exposes one. The IP (telnet/SSH) driver never populates
        # `master_outlet`, so on those units the entity would sit at `unknown`
        # and silently do nothing when pressed.
        if skipped_an_outlet:
            _LOGGER.debug(
                "Skipping master switch because an outlet was skipped for %s", name
            )
        elif wattbox.master_outlet is None:
            _LOGGER.debug("Skipping master switch: %s exposes no master outlet", name)
        else:
            entities.append(WattBoxMasterSwitch(hass, name))

        if skipped_an_outlet:
            _LOGGER.warning(
                "Some outlets were skipped. "
                "Check your settings for %s if this was unintentional.",
                CONF_SKIP_REGEXP,
            )

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up switch platform: %s", err)
        raise PlatformNotReady from err


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup switch platform (legacy YAML support)."""
    try:
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

            outlet_name = resolve_outlet_name(name_regexp, outlet_name)

            _LOGGER.debug("Adding switch #%s - %s", i, outlet_name)
            try:
                entities.append(WattBoxBinarySwitch(hass, name, i, outlet_name))
            except Exception as err:
                _LOGGER.error("Failed to append WattBoxBinarySwitch: %s", err)
                raise PlatformNotReady from err

        # Skip the master switch iff any of the outlets are skipped
        if not skipped_an_outlet:
            entities.append(WattBoxMasterSwitch(hass, name))
        else:
            _LOGGER.debug(
                "Skipping master switch because an outlet was skipped for %s", name
            )

        async_add_entities(entities)
    except Exception as err:
        _LOGGER.error("Error setting up switch platform: %s", err)
        raise PlatformNotReady from err


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
        """Update the sensor (legacy poll fallback)."""
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        self._attr_is_on = self._outlet.status
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
        await async_run_command(self._wattbox, self._outlet.async_turn_on)
        if self._coordinator is not None:
            await self._coordinator.async_request_refresh()

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
        await async_run_command(self._wattbox, self._outlet.async_turn_off)
        if self._coordinator is not None:
            await self._coordinator.async_request_refresh()


class WattBoxMasterSwitch(WattBoxBinarySwitch):
    """WattBox master switch class."""

    _outlet: Outlet | None  # type: ignore[assignment]

    def __init__(self, hass: HomeAssistant, name: str) -> None:
        super().__init__(hass, name, 0)
        self._outlet = self._wattbox.master_outlet
        self._attr_name = f"{name} Master Switch"
        self._attr_unique_id = f"{self._wattbox.serial_number}-switch-master"

    async def async_update(self) -> None:
        """Update the sensor (legacy poll fallback)."""
        self._update_attrs()

    @callback
    def _update_attrs(self) -> None:
        if self._outlet is not None:
            self._attr_is_on = self._outlet.status

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        if self._outlet is not None:
            await super().async_turn_on(**kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        if self._outlet is not None:
            await super().async_turn_off(**kwargs)
