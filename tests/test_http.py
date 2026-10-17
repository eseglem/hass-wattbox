"""The HTTP client against the simulator."""

import pytest

from custom_components.wattbox.api import (
    Commands,
    WattBoxAuthError,
    WattBoxLoggedOut,
    async_create_wattbox,
)

from .simulator import HttpSimulator, SimState


async def test_initial_and_update(http_sim: HttpSimulator) -> None:
    wattbox = await async_create_wattbox(
        "127.0.0.1", http_sim.port, "wattbox", "wattbox"
    )
    try:
        assert wattbox.transport == "http"
        assert wattbox.hardware_version == "WB-300-IP-3"
        assert wattbox.serial_number == "ST-SIM300"
        assert wattbox.number_outlets == 3
        assert wattbox.supports_outlet_metering is False
        assert wattbox.cloud_status is True
        # Tenths on the wire.
        assert wattbox.voltage_value == 120.1
        assert wattbox.power_value == 32
        assert wattbox.outlets[1].name == "Kaleidescape Server"
        assert wattbox.outlets[1].method is True
        assert wattbox.master_outlet is not None
        assert wattbox.master_outlet.status is True
    finally:
        await wattbox.async_close()


@pytest.mark.parametrize(
    ("bad_auth", "error"),
    [
        ("401", WattBoxAuthError),
        ("login", WattBoxLoggedOut),
        ("blank", WattBoxLoggedOut),
    ],
)
async def test_bad_credentials(
    socket_enabled: None, bad_auth: str, error: type[Exception]
) -> None:
    """None of these may come up as a device with no outlets (#67)."""
    sim = HttpSimulator(
        SimState.with_outlets(12, model="WB-700-IPV-12"), bad_auth=bad_auth
    )
    await sim.start()
    try:
        with pytest.raises(error):
            await async_create_wattbox("127.0.0.1", sim.port, "wattbox", "nope")
    finally:
        await sim.stop()


async def test_recovers_from_a_lapsed_session(http_sim: HttpSimulator) -> None:
    wattbox = await async_create_wattbox(
        "127.0.0.1", http_sim.port, "wattbox", "wattbox"
    )
    try:
        http_sim.logged_out_requests = 1
        http_sim.state.outlets[0].on = False
        await wattbox.async_update()
        assert wattbox.outlets[1].status is False

        http_sim.logged_out = True
        with pytest.raises(WattBoxLoggedOut):
            await wattbox.async_update()
    finally:
        await wattbox.async_close()


async def test_commands_and_master(http_sim: HttpSimulator) -> None:
    http_sim.state.outlets[2].method = False
    wattbox = await async_create_wattbox(
        "127.0.0.1", http_sim.port, "wattbox", "wattbox"
    )
    try:
        await wattbox.async_send_command(1, Commands.OFF)
        assert http_sim.state.outlets[0].on is False
        assert wattbox.master_outlet is not None
        assert wattbox.master_outlet.status is False

        await wattbox.master_outlet.async_turn_on()
        assert http_sim.state.outlets[0].on is True

        await wattbox.master_outlet.async_turn_off()
        await wattbox.async_update()
        # Only the outlets that follow the master switch.
        assert [o.on for o in http_sim.state.outlets] == [False, False, True]
        assert wattbox.master_outlet.status is False
    finally:
        await wattbox.async_close()
