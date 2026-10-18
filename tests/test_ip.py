"""The Integration Protocol client against the simulator."""

import asyncio
import socket

import pytest

from custom_components.wattbox.api import (
    Commands,
    WattBoxAuthError,
    WattBoxCommandError,
    WattBoxConnectionError,
    async_create_wattbox,
)
from custom_components.wattbox.api.ip import IpWattBox

from .simulator import SimState, SshSimulator, TelnetSimulator


async def _settle() -> None:
    """Let the background reader process what the simulator sent."""
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)


async def _connect(sim: TelnetSimulator, **kwargs: object) -> IpWattBox:
    wattbox = await async_create_wattbox(
        "127.0.0.1", sim.port, "wattbox", "wattbox", transport="telnet", **kwargs
    )
    assert isinstance(wattbox, IpWattBox)
    return wattbox


async def test_initial_and_update(telnet_sim: TelnetSimulator) -> None:
    wattbox = await _connect(telnet_sim)
    try:
        assert wattbox.hardware_version == "WB-800-IPVM-12"
        assert wattbox.firmware_version == "2.10.0.0"
        assert wattbox.serial_number == "ST-SIM0000001"
        assert wattbox.hostname == "WattBox-Sim"
        assert wattbox.number_outlets == 12
        assert wattbox.supports_outlet_metering is True
        assert wattbox.cloud_status is None
        assert wattbox.master_outlet is None
        # Spaces and punctuation survive (#55).
        assert wattbox.outlets[2].name == "Apple TV 06 Office Wall"
        assert wattbox.outlets[5].name == "Router (Main)"
        assert all(o.status for o in wattbox.outlets.values())
        assert wattbox.voltage_value == 120.1
        assert wattbox.safe_voltage_status is True
        # Metering is opt-in, so no per-outlet request was made.
        assert not any(c.startswith("?OutletPowerStatus") for c in telnet_sim.commands)
        assert wattbox.outlets[1].power_value is None
    finally:
        await wattbox.async_close()


async def test_outlet_metering(telnet_sim: TelnetSimulator) -> None:
    telnet_sim.state.outlets[1].on = False
    wattbox = await _connect(telnet_sim, outlet_metering=True)
    try:
        assert wattbox.outlets[1].power_value == 10.5
        assert wattbox.outlets[2].power_value == 0.0
        assert wattbox.outlets[12].voltage_value == 120.1
    finally:
        await wattbox.async_close()


async def test_metering_switches_itself_off_on_error(
    telnet_sim: TelnetSimulator,
) -> None:
    telnet_sim.unsupported.add("?OutletPowerStatus")
    wattbox = await _connect(telnet_sim, outlet_metering=True)
    try:
        assert wattbox.supports_outlet_metering is False
        sent = len(telnet_sim.commands)
        await wattbox.async_update()
        assert not any(
            c.startswith("?OutletPowerStatus") for c in telnet_sim.commands[sent:]
        )
    finally:
        await wattbox.async_close()


async def test_optional_requests_tolerate_error(telnet_sim: TelnetSimulator) -> None:
    telnet_sim.unsupported |= {"?Hostname", "?AutoReboot", "?UPSStatus"}
    wattbox = await _connect(telnet_sim)
    try:
        assert wattbox.hostname == ""
        assert wattbox.number_outlets == 12
    finally:
        await wattbox.async_close()


async def test_required_request_error_raises(telnet_sim: TelnetSimulator) -> None:
    telnet_sim.unsupported.add("?PowerStatus")
    with pytest.raises(WattBoxCommandError):
        await _connect(telnet_sim)
    await _settle()
    assert not telnet_sim.sessions


async def test_echoed_commands(socket_enabled: None) -> None:
    """SSH echoes each command; the reply must still be found."""
    sim = TelnetSimulator(SimState.with_outlets(4), echo=True)
    await sim.start()
    try:
        wattbox = await _connect(sim, outlet_metering=True)
        assert wattbox.outlets[1].name == "Kaleidescape Server"
        assert wattbox.outlets[3].power_value == 10.5
        await wattbox.async_send_command(2, Commands.OFF)
        assert sim.state.outlets[1].on is False
        await wattbox.async_close()
    finally:
        await sim.stop()


async def test_bad_password(telnet_sim: TelnetSimulator) -> None:
    with pytest.raises(WattBoxAuthError):
        await async_create_wattbox(
            "127.0.0.1", telnet_sim.port, "wattbox", "nope", transport="telnet"
        )
    await _settle()
    assert not telnet_sim.sessions


async def test_nothing_listening(socket_enabled: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with pytest.raises(WattBoxConnectionError):
        await async_create_wattbox(
            "127.0.0.1", port, "wattbox", "wattbox", transport="telnet"
        )


async def test_session_cap(socket_enabled: None) -> None:
    sim = TelnetSimulator(SimState.with_outlets(2), max_sessions=0)
    await sim.start()
    try:
        with pytest.raises(WattBoxConnectionError, match="sessions"):
            await _connect(sim)
    finally:
        await sim.stop()


async def test_command_and_push(telnet_sim: TelnetSimulator) -> None:
    wattbox = await _connect(telnet_sim)
    pushes: list[None] = []
    remove = wattbox.add_listener(lambda: pushes.append(None))
    try:
        await wattbox.async_send_command(3, Commands.OFF)
        await _settle()
        assert telnet_sim.state.outlets[2].on is False
        assert wattbox.outlets[3].status is False
        assert pushes  # the device's ~OutletStatus

        # A change made elsewhere arrives without polling.
        telnet_sim.state.outlets[0].on = False
        await telnet_sim.push(f"~OutletStatus={telnet_sim.outlet_status()}")
        await _settle()
        assert wattbox.outlets[1].status is False

        # The push in the middle of an exchange does not confuse it (#66).
        await wattbox.async_update()
        assert wattbox.outlets[3].status is False
    finally:
        remove()
        await wattbox.async_close()


async def test_command_error(telnet_sim: TelnetSimulator) -> None:
    wattbox = await _connect(telnet_sim)
    try:
        telnet_sim.unsupported.add("!OutletSet")
        with pytest.raises(WattBoxCommandError):
            await wattbox.async_send_command(1, Commands.RESET)
        with pytest.raises(ValueError):
            await wattbox.async_send_command(99, Commands.ON)
    finally:
        await wattbox.async_close()


async def test_reconnects_after_device_drops_session(
    telnet_sim: TelnetSimulator,
) -> None:
    wattbox = await _connect(telnet_sim)
    try:
        await telnet_sim.drop_sessions()
        await _settle()
        await wattbox.async_update()
        assert telnet_sim.total_logins == 2
        assert len(telnet_sim.sessions) == 1
    finally:
        await wattbox.async_close()


async def test_timeout_drops_session(telnet_sim: TelnetSimulator) -> None:
    wattbox = IpWattBox(
        "127.0.0.1", "wattbox", "wattbox", telnet_sim.port, "telnet", timeout=0.3
    )
    try:
        await wattbox.async_get_initial()
        telnet_sim.silent.add("?PowerStatus")
        with pytest.raises(WattBoxConnectionError, match="no reply"):
            await wattbox.async_update()
        telnet_sim.silent.clear()
        # A new session, so a late reply could never be misread.
        await wattbox.async_update()
        assert telnet_sim.total_logins == 2
    finally:
        await wattbox.async_close()


async def test_close_releases_session(telnet_sim: TelnetSimulator) -> None:
    wattbox = await _connect(telnet_sim)
    assert len(telnet_sim.sessions) == 1
    await wattbox.async_close()
    await _settle()
    assert telnet_sim.commands[-1] == "!Exit"
    assert not telnet_sim.sessions
    # Safe to repeat.
    await wattbox.async_close()


@pytest.mark.parametrize("banner", [True, False])
async def test_ssh(socket_enabled: None, banner: bool) -> None:
    sim = SshSimulator(SimState.with_outlets(4), banner=banner)
    await sim.start()
    try:
        wattbox = IpWattBox(
            "127.0.0.1", "wattbox", "wattbox", sim.port, "ssh", timeout=1.0
        )
        await wattbox.async_get_initial()
        await wattbox.async_update()
        assert wattbox.transport == "ssh"
        assert wattbox.outlets[2].name == "Apple TV 06 Office Wall"
        await wattbox.async_send_command(1, Commands.OFF)
        assert sim.state.outlets[0].on is False
        await wattbox.async_close()
        await _settle()
        assert sim.core.commands[-1] == "!Exit"
    finally:
        await sim.stop()


async def test_ssh_bad_password(socket_enabled: None) -> None:
    sim = SshSimulator(SimState.with_outlets(2))
    await sim.start()
    try:
        with pytest.raises(WattBoxAuthError, match="OvrC"):
            await async_create_wattbox(
                "127.0.0.1", sim.port, "wattbox", "nope", transport="ssh"
            )
    finally:
        await sim.stop()
