"""WebSocket API for the panel and the card."""

from typing import Any, Final

import probatio

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

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
