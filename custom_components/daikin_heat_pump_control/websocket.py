"""WebSocket API for the panel and the card."""

from typing import Any, Final

import probatio

from homeassistant.components import websocket_api
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .bridge.client import BridgeError
from .const import DOMAIN
from .dashboard import dashboard_entities, info_rows
from .panel import APPEARANCE_SCHEMA
from .runtime import DaikinConfigEntry

ERR_NOT_LOADED: Final = "not_loaded"


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the WebSocket commands."""
    websocket_api.async_register_command(hass, ws_entities)
    websocket_api.async_register_command(hass, ws_panel_config)
    websocket_api.async_register_command(hass, ws_set_panel_config)
    websocket_api.async_register_command(hass, ws_subscribe_master)
    websocket_api.async_register_command(hass, ws_claim_master)


def _loaded_entry(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg_id: int
) -> DaikinConfigEntry | None:
    """Return the loaded config entry, or send an error."""
    entries: list[DaikinConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(
            msg_id, ERR_NOT_LOADED, "Daikin Heat Pump Control is not loaded"
        )
        return None
    return entries[0]


@websocket_api.websocket_command({probatio.Required("type"): f"{DOMAIN}/entities"})
@callback
def ws_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the entity of every dashboard value and the info box rows."""
    if (entry := _loaded_entry(hass, connection, msg["id"])) is None:
        return
    connection.send_result(
        msg["id"],
        {
            "entities": dashboard_entities(hass, entry),
            "info": info_rows(entry.options),
        },
    )


@websocket_api.websocket_command({probatio.Required("type"): f"{DOMAIN}/panel_config"})
@callback
def ws_panel_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the appearance of the panel."""
    if (entry := _loaded_entry(hass, connection, msg["id"])) is None:
        return
    connection.send_result(msg["id"], {"config": entry.runtime_data.panel.config})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/panel_config/set",
        probatio.Required("config"): APPEARANCE_SCHEMA,
    }
)
@websocket_api.async_response
async def ws_set_panel_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Store the appearance of the panel."""
    if (entry := _loaded_entry(hass, connection, msg["id"])) is None:
        return
    await entry.runtime_data.panel.async_save(msg["config"])
    connection.send_result(msg["id"], {"config": entry.runtime_data.panel.config})


def master_status(entry: DaikinConfigEntry) -> dict[str, Any]:
    """Return whether this instance is the master of all connected bridges."""
    nodes = [node for node in entry.runtime_data.nodes.values() if node.bridge_ready]
    return {
        "master": all(node.master for node in nodes),
        "clients": max((node.clients for node in nodes), default=0),
    }


@websocket_api.websocket_command(
    {probatio.Required("type"): f"{DOMAIN}/master/subscribe"}
)
@callback
def ws_subscribe_master(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send the master status now and whenever it changes."""
    if (entry := _loaded_entry(hass, connection, msg["id"])) is None:
        return
    last: dict[str, Any] = master_status(entry)

    @callback
    def _changed() -> None:
        nonlocal last
        status = master_status(entry)
        if status != last:
            last = status
            connection.send_event(msg["id"], status)

    unsubs: list[CALLBACK_TYPE] = [
        node.async_add_listener(_changed) for node in entry.runtime_data.nodes.values()
    ]

    @callback
    def _unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    connection.send_event(msg["id"], last)


@websocket_api.require_admin
@websocket_api.websocket_command({probatio.Required("type"): f"{DOMAIN}/master/claim"})
@websocket_api.async_response
async def ws_claim_master(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Make this instance the master of all connected bridges."""
    if (entry := _loaded_entry(hass, connection, msg["id"])) is None:
        return
    try:
        for node in entry.runtime_data.nodes.values():
            if node.bridge_ready:
                await node.async_claim()
    except (BridgeError, HomeAssistantError) as err:
        connection.send_error(msg["id"], "claim_failed", str(err))
        return
    connection.send_result(msg["id"], master_status(entry))
