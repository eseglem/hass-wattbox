"""Switch platform for wattbox."""

import logging
from typing import Any, List

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DOMAIN_DATA, PLUG_ICON
from .entity import WattBoxEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType,
) -> None:
    """Setup switch platform."""
    name: str = discovery_info[CONF_NAME]

    entities: List[WattBoxEntity] = []

    if hass.data[DOMAIN_DATA][name].master_outlet is not None:
        entities.append(WattBoxMasterSwitch(hass, name))

    for outlet in hass.data[DOMAIN_DATA][name].outlets.values():
        _LOGGER.debug("Setting up: %s", outlet)
        entities.append(WattBoxBinarySwitch(hass, name, outlet.index))

    async_add_entities(entities)


class WattBoxBinarySwitch(WattBoxEntity, SwitchEntity):
    """WattBox switch class."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, hass: HomeAssistant, name: str, index: int) -> None:
        super().__init__(hass, name, index)
        self.index: int = index
        self._attr_name = f"{name} Outlet {index}"

    async def async_update(self) -> None:
        """Update the sensor."""
        # Get new data (if any)
        outlet = self.hass.data[DOMAIN_DATA][self.wattbox_name].outlets[self.index]

        # Check the data and update the value.
        self._attr_is_on = outlet.status

        # Set/update attributes
        self._attr_extra_state_attributes["name"] = outlet.name
        self._attr_extra_state_attributes["method"] = outlet.method
        self._attr_extra_state_attributes["index"] = outlet.index

    async def async_turn_on(self, **_kwargs: Any) -> None:
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

    async def async_turn_off(self, **_kwargs: Any) -> None:
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

    async def async_update(self) -> None:
        """Update the sensor."""
        # Get new data (if any)
        outlet = self.hass.data[DOMAIN_DATA][self.wattbox_name].master_outlet
        if outlet is not None:
            # Check the data and update the value.
            self._attr_is_on = outlet.status

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on the switch."""
        master_outlet = self.hass.data[DOMAIN_DATA][self.wattbox_name].master_outlet

        if master_outlet is not None:
            # Update state first so it is not stale.
            self._attr_is_on = True
            self.async_write_ha_state()
            # Trigger the action on the wattbox.
            await master_outlet.async_turn_on()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the switch."""
        master_outlet = self.hass.data[DOMAIN_DATA][self.wattbox_name].master_outlet

        if master_outlet is not None:
            # Update state first so it is not stale.
            self._attr_is_on = False
            self.async_write_ha_state()
            # Trigger the action on the wattbox.
            await master_outlet.async_turn_off()
