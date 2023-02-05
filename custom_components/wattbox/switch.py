"""Switch platform for wattbox."""

import logging
from typing import Final, List

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN_DATA, PLUG_ICON
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

    num_switches: int = hass.data[DOMAIN_DATA][name].number_outlets

    entities.append(WattBoxMasterSwitch(hass, name))
    for i in range(1, num_switches + 1):
        entities.append(WattBoxBinarySwitch(hass, name, i))

    async_add_entities(entities, True)


class WattBoxBinarySwitch(WattBoxEntity, SwitchEntity):
    """WattBox switch class."""

    _attr_device_class: Final[str] = SwitchDeviceClass.OUTLET

    def __init__(self, hass: HomeAssistant, name: str, index: int):
        super().__init__(hass, name, index)
        self.index: int = index
        self._attr_name = name + " Outlet " + str(index)

    async def async_update(self):
        """Update the sensor."""
        # Get new data (if any)
        outlet = self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index]

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
            self.hass.data[DOMAIN_DATA][self.wattbox_name],
            self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index],
        )
        _LOGGER.debug(
            "Current Outlet Before: %s - %s",
            self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index].status,
            repr(self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index]),
        )
        # Update state first so it is not stale.
        self._attr_is_on = True
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[
            self.index
        ].async_turn_on()

    async def async_turn_off(self, **kwargs) -> None:  # pylint: disable=unused-argument
        """Turn off the switch."""
        _LOGGER.debug(
            "Turning Off: %s - %s",
            self.hass.data[DOMAIN_DATA][self.wattbox_name],
            self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index],
        )
        _LOGGER.debug(
            "Current Outlet Before: %s - %s",
            self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index].status,
            repr(self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index]),
        )
        # Update state first so it is not stale.
        self._attr_is_on = False
        self.async_write_ha_state()
        # Trigger the action on the wattbox.
        await self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[
            self.index
        ].async_turn_off()

    @property
    def icon(self) -> str | None:
        """Return the icon of this switch."""
        return PLUG_ICON


class WattBoxMasterSwitch(WattBoxBinarySwitch):
    """WattBox master switch class."""

    def __init__(self, hass: HomeAssistant, name: str) -> None:
        super().__init__(hass, name, 0)
        self._attr_name = name + " Master Switch"
