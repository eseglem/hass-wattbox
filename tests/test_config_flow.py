"""Config, reauth and options flows."""

import asyncio
import socket
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wattbox.const import (
    CONF_CONNECTION_TYPE,
    CONF_OUTLET_METERING,
    CONF_SKIP_REGEXP,
    DOMAIN,
)

from .conftest import HTTP_SERIAL, TELNET_SERIAL
from .simulator import HttpSimulator, SimState, TelnetSimulator


def _ports(**ports: int):  # type: ignore[no-untyped-def]
    """Point the connection types at the simulators' ports."""
    return patch.dict("custom_components.wattbox.config_flow.CONNECTION_TYPES", ports)


async def _submit(hass: HomeAssistant, **user_input: object) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "127.0.0.1",
            CONF_USERNAME: "wattbox",
            CONF_PASSWORD: "wattbox",
            CONF_NAME: "Rack",
            **user_input,
        },
    )


async def test_telnet(hass: HomeAssistant, telnet_sim: TelnetSimulator) -> None:
    with _ports(telnet=telnet_sim.port):
        result = await _submit(
            hass,
            **{
                CONF_CONNECTION_TYPE: "telnet",
                CONF_SKIP_REGEXP: "Modem|Router",
                CONF_OUTLET_METERING: True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == TELNET_SERIAL
    assert entry.data[CONF_CONNECTION_TYPE] == "telnet"
    assert entry.data["port"] == telnet_sim.port
    assert entry.data["outlet_metering_supported"] is True
    assert entry.options == {
        CONF_OUTLET_METERING: True,
        CONF_SKIP_REGEXP: "Modem|Router",
    }

    await hass.config_entries.async_unload(entry.entry_id)


async def test_http(hass: HomeAssistant, http_sim: HttpSimulator) -> None:
    with _ports(http=http_sim.port):
        result = await _submit(
            hass, **{CONF_CONNECTION_TYPE: "http", CONF_OUTLET_METERING: True}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == HTTP_SERIAL
    # Not supported over HTTP, so not stored as on.
    assert result["result"].options[CONF_OUTLET_METERING] is False
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_telnet_bad_password(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    with _ports(telnet=telnet_sim.port):
        result = await _submit(
            hass, **{CONF_CONNECTION_TYPE: "telnet", CONF_PASSWORD: "nope"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert "rejected" in result["description_placeholders"]["error_detail"]
    await asyncio.sleep(0.05)  # let the simulator see the hang-up
    assert not telnet_sim.sessions


async def test_http_bad_password_without_error_status(
    hass: HomeAssistant, socket_enabled: None
) -> None:
    """A 200 that is not data is a failed login, not an empty device (#67)."""
    sim = HttpSimulator(
        SimState.with_outlets(12, model="WB-700-IPV-12"), bad_auth="blank"
    )
    await sim.start()
    try:
        with _ports(http=sim.port):
            result = await _submit(
                hass, **{CONF_CONNECTION_TYPE: "http", CONF_PASSWORD: "nope"}
            )
    finally:
        await sim.stop()
    assert result["errors"] == {"base": "invalid_auth"}


async def test_800_series_over_http(hass: HomeAssistant, socket_enabled: None) -> None:
    """The 800 series refuses HTTP outright; say what to pick instead (#56)."""
    sim = HttpSimulator(SimState.with_outlets(12, password="\0never"))
    await sim.start()
    try:
        with _ports(http=sim.port):
            result = await _submit(hass, **{CONF_CONNECTION_TYPE: "http"})
    finally:
        await sim.stop()
    assert result["errors"] == {"base": "invalid_auth"}
    assert "telnet" in result["description_placeholders"]["error_detail"]


async def test_cannot_connect(hass: HomeAssistant, socket_enabled: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with _ports(telnet=port):
        result = await _submit(hass, **{CONF_CONNECTION_TYPE: "telnet"})
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["description_placeholders"]["error_detail"]


async def test_invalid_skip_regexp(hass: HomeAssistant) -> None:
    result = await _submit(
        hass, **{CONF_CONNECTION_TYPE: "telnet", CONF_SKIP_REGEXP: "("}
    )
    assert result["errors"] == {CONF_SKIP_REGEXP: "invalid_regex"}


async def test_already_configured(
    hass: HomeAssistant, telnet_sim: TelnetSimulator
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=TELNET_SERIAL).add_to_hass(hass)
    with _ports(telnet=telnet_sim.port):
        result = await _submit(hass, **{CONF_CONNECTION_TYPE: "telnet"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, telnet_sim: TelnetSimulator) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TELNET_SERIAL,
        data={
            CONF_HOST: "127.0.0.1",
            "port": telnet_sim.port,
            CONF_USERNAME: "wattbox",
            CONF_PASSWORD: "old",
            CONF_NAME: "Rack",
            CONF_CONNECTION_TYPE: "telnet",
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "wattbox", CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "wattbox", CONF_PASSWORD: "wattbox"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "wattbox"
    await hass.config_entries.async_unload(entry.entry_id)
