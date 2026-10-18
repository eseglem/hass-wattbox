"""Shared fixtures."""

from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import pytest

from .simulator import HttpSimulator, SimState, TelnetSimulator

TELNET_SERIAL = "ST-SIM0000001"
HTTP_SERIAL = "ST-SIM300"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components in every test."""


@pytest.fixture(autouse=True)
def mock_mac_lookup() -> Iterator[None]:
    """The ARP lookup would shell out and touch the network."""
    with patch("custom_components.wattbox.get_mac_address", return_value=None):
        yield


@pytest.fixture
async def telnet_sim(socket_enabled: None) -> AsyncIterator[TelnetSimulator]:
    """An 800-series WattBox on a free loopback port."""
    sim = TelnetSimulator(SimState.with_outlets(12, service_tag=TELNET_SERIAL))
    await sim.start()
    yield sim
    await sim.stop()


@pytest.fixture
async def http_sim(socket_enabled: None) -> AsyncIterator[HttpSimulator]:
    """A 300-series WattBox on a free loopback port."""
    sim = HttpSimulator(
        SimState.with_outlets(3, model="WB-300-IP-3", service_tag=HTTP_SERIAL)
    )
    await sim.start()
    yield sim
    await sim.stop()
