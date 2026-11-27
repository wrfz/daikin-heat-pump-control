"""Helpers shared by the tests."""

from pathlib import Path
import sys
from typing import Any

# Make `custom_components.daikin_heat_pump_control` importable from the checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from pytest_homeassistant.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from sim.esp import SimulatedEsp

DOMAIN = "daikin_heat_pump_control"
MAC_CAN = "aa:bb:cc:00:00:01"
MAC_UART = "aa:bb:cc:00:00:02"
MAC_BOTH = "aa:bb:cc:00:00:03"
ENTRY_ID = "01JDAIKINTESTENTRY00000000"


def ha_clock() -> float:
    """Return Home Assistant's (possibly frozen) time in seconds."""
    return dt_util.utcnow().timestamp()


def esphome_entry(
    hass: HomeAssistant, esp: SimulatedEsp, *, noise_psk: str | None = None
) -> MockConfigEntry:
    """Add a (disabled) ESPHome config entry for a node."""
    entry = MockConfigEntry(
        domain="esphome",
        unique_id=esp.mac,
        data={
            "host": esp.host,
            "port": esp.port,
            "password": "",
            "noise_psk": noise_psk if noise_psk is not None else esp.noise_psk,
            "device_name": esp.name,
        },
        disabled_by=ConfigEntryDisabler.USER,
    )
    entry.add_to_hass(hass)
    return entry


def node_data(esp: SimulatedEsp) -> dict[str, Any]:
    """Return the stored data of a node."""
    return {
        "host": esp.host,
        "port": esp.port,
        "noise_psk": esp.noise_psk,
        "name": esp.name,
    }


def daikin_entry(
    hass: HomeAssistant,
    *,
    can: SimulatedEsp | None = None,
    uart: SimulatedEsp | None = None,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Add a config entry of the integration."""
    nodes = {esp.mac: node_data(esp) for esp in (can, uart) if esp is not None}
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id=DOMAIN,
        title="Daikin Heat Pump",
        data={
            "nodes": nodes,
            "can_node": can.mac if can else None,
            "uart_node": uart.mac if uart else None,
        },
        options=options
        if options is not None
        else ({"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "i"} if uart else {}),
    )
    entry.add_to_hass(hass)
    return entry


async def options_step(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> Any:
    """Open the options and choose a part of the menu."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["step_id"] == step
    return result


async def wait_for_state(
    hass: HomeAssistant, entity_id: str, state: str, timeout: float = 5
) -> None:
    """Wait until an entity reaches a state (driven by socket events, not time)."""
    current = hass.states.get(entity_id)
    if current is not None and current.state == state:
        return
    future: asyncio.Future[None] = hass.loop.create_future()

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is not None and new.state == state and not future.done():
            future.set_result(None)

    unsub = async_track_state_change_event(hass, entity_id, _changed)
    try:
        async with asyncio.timeout(timeout):
            await future
    finally:
        unsub()


# ------------------------------------------------------------------ CAN bus

FULL_POLL = 30  # s of bus time to read every polled value once


async def _block_till_done_except(
    hass: HomeAssistant, waiting: set[asyncio.Future[Any]]
) -> None:
    """Wait for Home Assistant's tasks except those of a pending service call."""
    if not waiting:
        await hass.async_block_till_done()
        return
    await asyncio.sleep(0)
    current = asyncio.current_task()
    while tasks := [
        task
        for task in hass._tasks
        if task is not current and task not in waiting and not task.done()
    ]:
        await asyncio.wait(tasks)


async def run_bus(
    hass: HomeAssistant,
    freezer: Any,
    seconds: float,
    step: float = 0.2,
    *,
    waiting: set[asyncio.Future[Any]] | None = None,
) -> None:
    """Let the exchange cycle run for a while in steps of 200 ms by default.

    `waiting` are tasks of a service call that waits for the bus; they are
    not waited for between the steps.
    """
    from datetime import timedelta  # noqa: PLC0415

    from pytest_homeassistant.common import async_fire_time_changed  # noqa: PLC0415

    for _ in range(round(seconds / step)):
        freezer.tick(timedelta(seconds=step))
        async_fire_time_changed(hass)
        await _block_till_done_except(hass, waiting or set())


async def setup_can(
    hass: HomeAssistant, esp: SimulatedEsp, **kwargs: Any
) -> MockConfigEntry:
    """Set up the integration with a CAN node."""
    entry = daikin_entry(hass, can=esp, **kwargs)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    """Return the state of an entity, which must exist."""
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


def requested(esp: SimulatedEsp, register: tuple[int, ...], kind: int = 1) -> int:
    """Return how often the integration sent a frame of a kind for a register."""
    assert esp.can is not None
    return sum(
        1
        for _, frame in esp.can.sent
        if frame.data[0] & 0x0F == kind
        and frame.data[2 : 2 + len(register)] == bytes(register)
    )


async def call_with_bus(
    hass: HomeAssistant,
    freezer: Any,
    awaitable: Any,
    seconds: float = 2.0,
) -> Any:
    """Await a service call while the bus runs; return its result."""
    before = set(hass._tasks)
    task = asyncio.ensure_future(awaitable)
    await asyncio.sleep(0)
    waiting: set[asyncio.Future[Any]] = {task}
    for item in set(hass._tasks) - before:
        if "async_exchange" not in item.get_coro().__qualname__:  # type: ignore[union-attr]
            waiting.add(item)
    await run_bus(hass, freezer, seconds, waiting=waiting)
    return await task
