"""Setup, entities, availability and teardown of a config entry."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.wattbox.const import (
    CONF_CONNECTION_TYPE,
    CONF_OUTLET_METERING,
    CONF_SKIP_REGEXP,
    DOMAIN,
)
from custom_components.wattbox.diagnostics import async_get_config_entry_diagnostics

from .conftest import HTTP_SERIAL, TELNET_SERIAL
from .simulator import HttpSimulator, TelnetSimulator


def _entry(
    port: int, connection_type: str | None, **options: object
) -> MockConfigEntry:
    data = {
        CONF_HOST: "127.0.0.1",
        CONF_PORT: port,
        CONF_USERNAME: "wattbox",
        CONF_PASSWORD: "wattbox",
        CONF_NAME: "Rack",
    }
    if connection_type is not None:
        data[CONF_CONNECTION_TYPE] = connection_type
    return MockConfigEntry(domain=DOMAIN, title="Rack", data=data, options=options)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    # Interval refreshes run as background tasks.
    await hass.async_block_till_done(wait_background_tasks=True)


async def _settle(hass: HomeAssistant) -> None:
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()


async def test_telnet_entities(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    entry = _entry(
        telnet_sim.port,
        "telnet",
        **{CONF_OUTLET_METERING: True, CONF_SKIP_REGEXP: "Modem"},
    )
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    # The unique ID scheme existing installs depend on.
    assert f"{TELNET_SERIAL}-switch-1" in unique_ids
    assert f"{TELNET_SERIAL}-switch-4" not in unique_ids  # skipped: Modem
    assert f"{TELNET_SERIAL}-button-reset-12" in unique_ids
    assert f"{TELNET_SERIAL}-sensor-power_value" in unique_ids
    assert f"{TELNET_SERIAL}-bsensor-power_lost" in unique_ids
    assert f"{TELNET_SERIAL}-outlet-1-sensor-power_value" in unique_ids
    assert "rack_total_energy" in unique_ids
    # Nothing on a telnet unit can populate these.
    assert f"{TELNET_SERIAL}-switch-master" not in unique_ids
    assert f"{TELNET_SERIAL}-bsensor-cloud_status" not in unique_ids
    assert f"{TELNET_SERIAL}-sensor-battery_charge" not in unique_ids

    assert hass.states.get("switch.rack_kaleidescape_server").state == STATE_ON
    assert hass.states.get("sensor.rack_voltage").state == "120.1"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await _settle(hass)
    assert not telnet_sim.sessions
    assert telnet_sim.commands[-1] == "!Exit"


async def test_old_entry_without_connection_type(
    hass: HomeAssistant, http_sim: HttpSimulator
) -> None:
    """Entries from before the type was stored infer it from the port."""
    entry = _entry(http_sim.port, None)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("switch.rack_master_switch") is not None
    assert hass.states.get("binary_sensor.rack_cloud_status") is not None
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", DOMAIN, f"{HTTP_SERIAL}-switch-1")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_and_push(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    entry = _entry(telnet_sim.port, "telnet")
    await _setup(hass, entry)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.rack_modem"}, blocking=True
    )
    await _settle(hass)
    assert telnet_sim.state.outlets[3].on is False
    assert hass.states.get("switch.rack_modem").state == STATE_OFF

    # Changed on the device itself: pushed, not polled.
    telnet_sim.state.outlets[0].on = False
    await telnet_sim.push(f"~OutletStatus={telnet_sim.outlet_status()}")
    await _settle(hass)
    assert hass.states.get("switch.rack_kaleidescape_server").state == STATE_OFF

    await hass.config_entries.async_unload(entry.entry_id)


async def test_failed_command_reverts(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    entry = _entry(telnet_sim.port, "telnet")
    await _setup(hass, entry)
    telnet_sim.unsupported.add("!OutletSet")

    with pytest.raises(HomeAssistantError, match="turn off"):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.rack_modem"}, blocking=True
        )
    assert hass.states.get("switch.rack_modem").state == STATE_ON

    with pytest.raises(HomeAssistantError, match="reset"):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.rack_modem_reset"}, blocking=True
        )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_and_back(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    entry = _entry(telnet_sim.port, "telnet")
    await _setup(hass, entry)
    port = telnet_sim.port

    await telnet_sim.stop()
    await _poll(hass)
    assert hass.states.get("sensor.rack_voltage").state == STATE_UNAVAILABLE

    revived = TelnetSimulator(telnet_sim.state, port=port)
    await revived.start()
    try:
        await _poll(hass)
        assert hass.states.get("sensor.rack_voltage").state == "120.1"
    finally:
        await hass.config_entries.async_unload(entry.entry_id)
        await revived.stop()


async def test_setup_with_wrong_password_starts_reauth(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    telnet_sim.state.password = "changed"
    entry = _entry(telnet_sim.port, "telnet")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_http_session_lapse_then_reauth(
    hass: HomeAssistant, http_sim: HttpSimulator
) -> None:
    entry = _entry(http_sim.port, "http")
    await _setup(hass, entry)

    # One lapsed session recovers on its own.
    http_sim.logged_out_requests = 1
    await _poll(hass)
    assert hass.states.get("sensor.rack_voltage").state == "120.1"

    # Turned away poll after poll: the credentials must have changed.
    http_sim.logged_out = True
    for _ in range(3):
        await _poll(hass)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics(hass: HomeAssistant, telnet_sim: TelnetSimulator) -> None:
    entry = _entry(telnet_sim.port, "telnet")
    await _setup(hass, entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"]["data"][CONF_PASSWORD] == "**REDACTED**"
    assert diagnostics["entry"]["data"][CONF_HOST] == "**REDACTED**"
    assert diagnostics["device"]["serial_number"] == "**REDACTED**"
    assert diagnostics["device"]["hardware_version"] == "WB-800-IPVM-12"
    assert diagnostics["device"]["outlets"][1]["name"] == "Apple TV 06 Office Wall"
    assert diagnostics["coordinator"]["last_update_success"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_yaml(hass: HomeAssistant, http_sim: HttpSimulator) -> None:
    """The legacy YAML path still sets up, and lets go of the device on stop."""
    assert await async_setup_component(
        hass,
        DOMAIN,
        {
            DOMAIN: [
                {
                    CONF_HOST: "127.0.0.1",
                    CONF_PORT: http_sim.port,
                    CONF_USERNAME: "wattbox",
                    CONF_PASSWORD: "wattbox",
                    CONF_NAME: "Yaml",
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.yaml_kaleidescape_server").state == STATE_ON
    assert hass.states.get("sensor.yaml_voltage").state == "120.1"

    wattbox = hass.data["wattbox_data"]["Yaml"]
    assert wattbox._client is not None
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert wattbox._client is None
