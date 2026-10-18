"""Diagnostics for WattBox.

Downloadable from the device page, and what the bug report template asks
for. It shows what the integration made of the device -- model, firmware,
outlet layout and the last readings -- which is most of what it takes to
tell a parsing problem from a connection one.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import BaseWattBox
from .const import DOMAIN, DOMAIN_DATA

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, "serial_number", "mac_address"}

_DEVICE_FIELDS = (
    "transport",
    "hardware_version",
    "firmware_version",
    "serial_number",
    "number_outlets",
    "has_ups",
    "supports_outlet_metering",
    "outlet_metering",
    "auto_reboot",
    "cloud_status",
    "safe_voltage_status",
    "power_lost",
    "power_value",
    "current_value",
    "voltage_value",
    "battery_charge",
    "battery_load",
    "battery_health",
    "battery_test",
    "est_run_time",
    "audible_alarm",
    "mute",
)


def _device(wattbox: BaseWattBox) -> dict[str, Any]:
    return {
        **{field: getattr(wattbox, field, None) for field in _DEVICE_FIELDS},
        "outlets": [
            {
                "index": outlet.index,
                "name": outlet.name,
                "status": outlet.status,
                "method": outlet.method,
                "power_value": outlet.power_value,
                "current_value": outlet.current_value,
                "voltage_value": outlet.voltage_value,
            }
            for outlet in wattbox.outlets.values()
        ],
        "master_outlet": None
        if wattbox.master_outlet is None
        else {"status": wattbox.master_outlet.status},
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    name = entry.data.get(CONF_NAME)
    wattbox: BaseWattBox | None = hass.data.get(DOMAIN_DATA, {}).get(name)
    coordinator = hass.data.get(DOMAIN, {}).get(name)

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": None
        if coordinator is None
        else {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval": str(coordinator.update_interval),
            "mac_address": "**REDACTED**" if coordinator.mac_address else None,
        },
        "device": None
        if wattbox is None
        else async_redact_data(_device(wattbox), TO_REDACT),
    }
