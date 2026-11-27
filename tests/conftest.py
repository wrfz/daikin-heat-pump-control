"""Fixtures for the Daikin Heat Pump Control tests."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant

import helpers  # noqa: F401  # sets up the import path first
from helpers import MAC_BOTH, MAC_CAN, MAC_UART, ha_clock
from sim.esp import FIRMWARE_BRIDGE, SimulatedEsp, make_noise_psk
from sim.heat_pump import HeatPump
from sim.indoor import load_indoor
from sim.rocon import load_rocon


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable the integration in all tests."""


@pytest.fixture(autouse=True)
def zeroconf_mock(mock_async_zeroconf: Any) -> None:
    """Use the mocked zeroconf instance."""


@pytest.fixture(autouse=True)
def mdns() -> Generator[dict[str, str]]:
    """Answer `<name>.local` lookups from a dict; mDNS cannot run in tests."""
    names: dict[str, str] = {}

    async def _resolve(hass: HomeAssistant, name: str) -> str | None:
        return names.get(name)

    with patch(
        "custom_components.daikin_heat_pump_control.bridge.resolve.async_resolve_node_name",
        side_effect=_resolve,
    ):
        yield names


@pytest.fixture
def no_can_polling() -> Generator[None]:
    """Keep the CAN coordinator from polling, for tests of the raw channel."""
    with patch(
        "custom_components.daikin_heat_pump_control.entity_defaults",
        return_value={},
    ):
        yield


@pytest.fixture
def no_uart_polling() -> Generator[None]:
    """Keep the UART coordinator away from the bus, for tests of the raw channel."""
    with patch(
        "custom_components.daikin_heat_pump_control.uart_coordinator."
        "UartCoordinator.async_start",
        return_value=lambda: None,
    ):
        yield


@pytest.fixture
def heat_pump() -> HeatPump:
    """Return the simulated heat pump."""
    hp = HeatPump()
    load_rocon(hp)
    load_indoor(hp)
    return hp


type EspFactory = Callable[..., Awaitable[SimulatedEsp]]


@pytest.fixture
async def esp_factory(
    heat_pump: HeatPump, socket_enabled: None
) -> AsyncGenerator[EspFactory]:
    """Create and start simulated ESP nodes on localhost."""
    nodes: list[SimulatedEsp] = []

    async def _create(**kwargs: Any) -> SimulatedEsp:
        kwargs.setdefault("noise_psk", make_noise_psk())
        kwargs.setdefault("firmware", FIRMWARE_BRIDGE)
        kwargs.setdefault("clock", ha_clock)
        kwargs.setdefault("heat_pump", heat_pump)
        esp = SimulatedEsp(**kwargs)
        await esp.start()
        nodes.append(esp)
        return esp

    yield _create
    for esp in nodes:
        await esp.stop()


@pytest.fixture
async def can_esp(esp_factory: EspFactory) -> SimulatedEsp:
    """Return a node with the CAN bridge."""
    return await esp_factory(name="daikin-can", mac=MAC_CAN, can=True)


@pytest.fixture
async def uart_esp(esp_factory: EspFactory) -> SimulatedEsp:
    """Return a node with the UART bridge."""
    return await esp_factory(
        name="daikin-uart", mac=MAC_UART, uart=True, noise_psk=make_noise_psk(7)
    )


@pytest.fixture
async def both_esp(esp_factory: EspFactory) -> SimulatedEsp:
    """Return a node with both bridges."""
    return await esp_factory(
        name="daikin-both",
        mac=MAC_BOTH,
        can=True,
        uart=True,
        noise_psk=make_noise_psk(9),
    )
