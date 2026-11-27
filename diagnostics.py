"""Diagnostics of the Daikin Heat Pump Control integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .bridge.node import BridgeNode
from .const import CONF_NOISE_PSK
from .runtime import DaikinConfigEntry

TO_REDACT = {CONF_NOISE_PSK, CONF_HOST, "ip", "ssid"}


def _node_diagnostics(node: BridgeNode) -> dict[str, Any]:
    identity = node.identity
    return {
        "name": node.name,
        "state": node.state,
        "assigned_buses": sorted(node.assigned_buses),
        "connected_via": node.connected_target.source
        if node.connected_target
        else None,
        "connect_count": node.connect_count,
        "last_error": node.last_error,
        "identity": None
        if identity is None
        else {
            "firmware": identity.firmware,
            "buses": sorted(identity.buses),
            "project_name": identity.project_name,
            "project_version": identity.project_version,
            "esphome_version": identity.esphome_version,
        },
        "info": async_redact_data(node.info.raw, TO_REDACT) if node.info else None,
        "channels": {
            bus: {
                "available": channel.available,
                "exchanges": channel.exchanges,
                "errors": channel.errors,
                "overflows": channel.overflows,
                "history": list(channel.history),
            }
            for bus, channel in node.channels.items()
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DaikinConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "nodes": {
            mac: _node_diagnostics(node)
            for mac, node in entry.runtime_data.nodes.items()
        },
        "can": entry.runtime_data.can.diagnostics()
        if entry.runtime_data.can is not None
        else None,
    }
