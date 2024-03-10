"""Switch platform for wattbox."""

import logging
import re
from typing import Final, List

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN_DATA, PLUG_ICON, CONF_NAME_REGEXP, CONF_SKIP_REGEXP
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(  # pylint: disable=unused-argument
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup switch platform."""
    name: str = discovery_info[CONF_NAME]
    entities: List[WattBoxEntity] = []
    config = hass.data[DOMAIN_DATA][name]
    wattbox = config['wattbox']
    name_regexp_str = config[CONF_NAME_REGEXP]
    skip_regexp_str = config[CONF_SKIP_REGEXP]
    num_switches: int = wattbox.number_outlets
    name_regexp = None
    try:
        if name_regexp_str:
            name_regexp = re.compile(name_regexp_str)
    except re.error as err:
        _LOGGER.error("Invalid name_regexp: %s", name_regexp_str)

    skip_regexp = None
    try:
        if skip_regexp_str:
            skip_regexp = re.compile(skip_regexp_str)
    except re.error as err:
        _LOGGER.error("Invalid skip_regexp: %s", skip_regexp_str)

    skipped_an_outlet = False
    for i in range(1, num_switches + 1):
        outlet_name = None
        outlet_full_name = wattbox.outlets[i].name

        if skip_regexp and skip_regexp.search(outlet_full_name):
            _LOGGER.debug("Skipping switch #%s - %s", i, outlet_full_name)
            skipped_an_outlet = True
            continue
        if name_regexp:
            outlet_name = outlet_full_name
            matched = name_regexp.search(outlet_full_name)
            if matched:
                outlet_name = matched.group()
                try:
                    if matched.group(1) != None and matched.group(1) != '':
                        outlet_name  = matched.group(1)
                except:
                    pass
        _LOGGER.debug("Adding switch #%s - %s", i, outlet_name)
        entities.append(WattBoxBinarySwitch(hass, name, i, outlet_name))

    # skip the master switch iff any of the outlets are skipped
    if not skipped_an_outlet:
        entities.append(WattBoxMasterSwitch(hass, name))
    else:
        _LOGGER.debug("Skipping master switch because an outlet was skipped for %s", name)

    async_add_entities(entities, True)


class WattBoxBinarySwitch(WattBoxEntity, SwitchEntity):
    """WattBox switch class."""

    _attr_device_class: Final[str] = SwitchDeviceClass.OUTLET

    def __init__(self, hass: HomeAssistant, name: str, index: int, outlet_name: str = None):
        super().__init__(hass, name, index)
        self.index: int = index
        if outlet_name and outlet_name.strip() != '':
            self._attr_name = name + " " + outlet_name.strip()
        else:
            self._attr_name = name + " Outlet " + str(index)
        self._wattbox =  self.hass.data[DOMAIN_DATA][self.wattbox_name]['wattbox']
        self._attr_unique_id = '{}-switch-{}'.format(self._wattbox.serial_number, index)

    async def async_update(self):
        """Update the sensor."""
        # Get new data (if any)
        outlet = self._wattbox.outlets[self.index]
        outlet = self._wattbox.outlets[self.index]

        # Check the data and update the value.
        self._attr_is_on = outlet.status

        # Set/update attributes
        self._attr_extra_state_attributes["name"] = outlet.name
        self._attr_extra_state_attributes["method"] = outlet.method
        self._attr_extra_state_attributes["index"] = outlet.index

    async def async_turn_on(self, **kwargs) -> None:  # pylint: disable=unused-argument
        """Turn on the switch."""
        _LOGGER.debug(
            "Turning On: %s - %s",
            self._wattbox,
            self._wattbox.outlets[self.index],
        )
        _LOGGER.debug(
            "Current Outlet Before: %s - %s",
            self._wattbox.outlets[self.index].status,
            repr(self._wattbox.outlets[self.index]),
        )
        # Update state first so it is not stale.
        self._attr_is_on = True
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self.hass.async_add_executor_job(
            self._wattbox.outlets[self.index].turn_on
        )

    async def async_turn_off(self, **kwargs) -> None:  # pylint: disable=unused-argument
        """Turn off the switch."""
        _LOGGER.debug(
            "Turning Off: %s - %s",
            self._wattbox,
            self._wattbox.outlets[self.index],
        )
        _LOGGER.debug(
            "Current Outlet Before: %s - %s",
            self._wattbox.outlets[self.index].status,
            repr(self._wattbox.outlets[self.index]),
        )
        # Update state first so it is not stale.
        self._attr_is_on = False
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self.hass.async_add_executor_job(
            self._wattbox.outlets[self.index].turn_off
        )

    @property
    def icon(self) -> str | None:
        """Return the icon of this switch."""
        return PLUG_ICON

class WattBoxMasterSwitch(WattBoxBinarySwitch):
    """WattBox master switch class."""

    def __init__(self, hass: HomeAssistant, name: str) -> None:
        super().__init__(hass, name, 0)
        self._attr_name = name + " Master Switch"
        self._wattbox =  self.hass.data[DOMAIN_DATA][self.wattbox_name]['wattbox']
        self._attr_unique_id = 'wb-{}-switch-{}'.format(self._wattbox.serial_number, name)
