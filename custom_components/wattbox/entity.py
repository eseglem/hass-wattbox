"""Base Entity component for wattbox."""

import logging
from collections.abc import Callable, Iterable
from typing import Any, Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pywattbox.base import BaseWattBox

from .const import DOMAIN, DOMAIN_DATA, TOPIC_UPDATE

_LOGGER = logging.getLogger(__name__)


@callback
def async_prune_unsupported(
    hass: HomeAssistant, entry: ConfigEntry, unique_ids: Iterable[str]
) -> None:
    """Delete registry entries for entities this device cannot populate.

    Declining to create an entity does not remove it. Home Assistant restores
    the registry entry for the config entry, finds nothing providing it, and
    shows it as `unavailable` indefinitely. Without this, everyone upgrading
    from a release that created these unconditionally keeps a wall of dead
    battery, UPS and cloud-status entities that they cannot clear except by
    deleting each one by hand.

    Matched on exact unique IDs -- the ones the platform just decided to skip
    -- so it cannot reach an entity that is still being created.
    """
    stale = set(unique_ids)
    if not stale:
        return

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in stale:
            _LOGGER.debug("Removing unsupported entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)


class WattBoxEntity(Entity):
    """WattBox Entity base class.

    Entities pull their state from the shared :class:`BaseWattBox` instance
    that the coordinator (or legacy YAML poller) keeps fresh. On every
    coordinator tick the entity's :meth:`_update_attrs` is invoked and the
    state is written, mirroring the ``CoordinatorEntity`` pattern.
    """

    _wattbox: BaseWattBox
    _coordinator: DataUpdateCoordinator | None
    _async_unsub_dispatcher_connect: Callable
    _attr_should_poll: Literal[False] = False

    def __init__(self, hass: HomeAssistant, name: str, *_args: Any) -> None:
        self.hass = hass
        self._wattbox = self.hass.data[DOMAIN_DATA][name]

        # Use coordinator if available (config entry path), otherwise
        # fall back to dispatcher pattern (legacy YAML path).
        self._coordinator = self.hass.data.get(DOMAIN, {}).get(name)

        self.topic: str = TOPIC_UPDATE.format(DOMAIN, name)
        self._attr_extra_state_attributes: dict[str, Any] = {}

        # Build device info with MAC address connection if available
        device_info = DeviceInfo(
            identifiers={(DOMAIN, self._wattbox.serial_number)},
            name=name,
            manufacturer="WattBox",
            model=getattr(self._wattbox, "hardware_version", None) or "WattBox",
            sw_version=getattr(self._wattbox, "firmware_version", None),
            serial_number=self._wattbox.serial_number,
            # Always the web UI. The entry's port may be 23 (telnet), which
            # would produce an unusable http://host:23 link.
            configuration_url=f"http://{self._wattbox.host}"
            if hasattr(self._wattbox, "host")
            else None,
        )

        # Add MAC address as a device connection (looked up once during setup)
        mac_address = getattr(self._coordinator, "mac_address", None)
        if mac_address:
            device_info["connections"] = {(dr.CONNECTION_NETWORK_MAC, mac_address)}

        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        When using a coordinator, availability is determined by whether the
        last data update succeeded. The dispatcher (YAML) path has no
        availability signal, so it is always reported as available.
        """
        if self._coordinator is not None:
            return self._coordinator.last_update_success
        return True

    @callback
    def _update_attrs(self) -> None:
        """Populate ``_attr_*`` from ``self._wattbox``.

        Subclasses override this to map device state onto entity attributes.
        Called on every coordinator update and once during setup.
        """

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh attributes from the device snapshot and write state."""
        self._update_attrs()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates and seed initial state."""
        if self._coordinator is not None:
            # Config entry path: listen to coordinator updates
            self.async_on_remove(
                self._coordinator.async_add_listener(self._handle_coordinator_update)
            )
        else:
            # Legacy YAML path: listen to dispatcher updates
            self._async_unsub_dispatcher_connect = async_dispatcher_connect(
                self.hass, self.topic, self._handle_coordinator_update
            )

        # Seed initial state from whatever the device snapshot already holds.
        self._update_attrs()

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect dispatcher listener when removed."""
        # Coordinator listeners are cleaned up via async_on_remove.
        # Only manually disconnect the dispatcher listener (YAML path).
        if self._coordinator is None and hasattr(
            self, "_async_unsub_dispatcher_connect"
        ):
            self._async_unsub_dispatcher_connect()
