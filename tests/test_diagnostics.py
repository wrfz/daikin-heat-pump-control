"""Tests for diagnostics and entity snapshots."""

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import async_fire_time_changed, snapshot_platform
from pytest_homeassistant.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.daikin_heat_pump_control.bridge.protocol import CanFrame
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from helpers import daikin_entry
from sim.esp import SimulatedEsp


@pytest.mark.freeze_time("2026-11-26 12:00:00+00:00")
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
    freezer: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Diagnostics contain node state and raw frames, with secrets redacted."""
    entry = daikin_entry(hass, can=can_esp, uart=uart_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    channel = entry.runtime_data.channels["can"]
    channel.async_send([CanFrame(can_id=0x680, data=bytes.fromhex("3100FAC0FC0000"))])
    entry.runtime_data.channels["uart"].async_send(bytes.fromhex("0340615B"))
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=0.2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert diagnostics == snapshot(exclude=props("port", "connect_count"))
    text = str(diagnostics)
    assert can_esp.noise_psk not in text
    assert "192.168.0.50" not in text


@pytest.mark.freeze_time("2026-11-26 12:00:00+00:00")
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("platform", [Platform.BINARY_SENSOR, Platform.SENSOR])
async def test_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """All diagnostic entities of the bridge nodes."""
    entry = daikin_entry(hass, can=can_esp, uart=uart_esp)
    with patch("custom_components.daikin_heat_pump_control.PLATFORMS", [platform]):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await snapshot_platform(hass, entity_registry, snapshot, entry.entry_id)
