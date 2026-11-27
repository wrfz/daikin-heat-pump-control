"""Helpers shared by the tests."""

from pathlib import Path
import sys
import tempfile
from typing import Any

# The repository is the integration package itself. Expose it as
# `custom_components.daikin_heat_pump_control` from a temporary directory so
# that Home Assistant's loader finds it independent of the checkout location.
_REPO = Path(__file__).resolve().parent.parent
_ROOT = Path(tempfile.mkdtemp(prefix="dhpc-"))
(_ROOT / "custom_components").mkdir()
(_ROOT / "custom_components" / "__init__.py").write_text("")
(_ROOT / "custom_components" / "daikin_heat_pump_control").symlink_to(_REPO)
sys.path.insert(0, str(_ROOT))

import asyncio  # noqa: E402

from pytest_homeassistant.common import MockConfigEntry  # noqa: E402

from homeassistant.config_entries import ConfigEntryDisabler  # noqa: E402
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback  # noqa: E402
from homeassistant.helpers.event import async_track_state_change_event  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402

from sim.esp import SimulatedEsp  # noqa: E402

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
        else ({"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "auto"} if uart else {}),
    )
    entry.add_to_hass(hass)
    return entry


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
