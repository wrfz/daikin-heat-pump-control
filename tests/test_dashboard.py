"""Tests for the dashboard: value table, WebSocket API, panel and options."""

import json
from pathlib import Path
import re
from typing import Any

import pytest
from pytest_homeassistant.typing import WebSocketGenerator

from custom_components.daikin_heat_pump_control.coordinator import entity_defaults
from custom_components.daikin_heat_pump_control.dashboard import (
    BUS_VALUES,
    EXTERNAL_VALUES,
    INFO_VALUES,
    VALUE_IDS,
    info_rows,
)
from custom_components.daikin_heat_pump_control.panel import panel_title
from custom_components.daikin_heat_pump_control.uart.table import UART_VALUES
from custom_components.daikin_heat_pump_control.uart_coordinator import COMPUTED
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, DATA_PANELS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from helpers import ENTRY_ID, daikin_entry, options_step, wait_for_state
from sim.esp import SimulatedEsp

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS = sorted((ROOT / "frontend-src" / "layouts").glob("daikin_glass_*.svg"))
PANEL = "daikin-heat-pump"


def _svg_value_ids(text: str) -> set[str]:
    """Return the value IDs an SVG layout refers to."""
    found = set(re.findall(r'data-(?:value|more-info)="([^"]+)"', text))
    for name in ("data-run-map", "data-temp-vars"):
        match = re.search(rf"{name}='([^']*)'", text)
        assert match, name
        for rule in json.loads(match.group(1)).values():
            ids = rule["id"]
            found.update(ids if isinstance(ids, list) else [ids])
    return found


def test_bus_keys_exist() -> None:
    """Every bus key of the value table is a key of the bus tables."""
    can_keys = set(entity_defaults())
    uart_keys = {value.key for value in UART_VALUES} | {c.key for c in COMPUTED}
    for value in BUS_VALUES:
        assert value.can is not None or value.uart is not None
        assert value.can is None or value.can in can_keys, value
        # The schematic shows its values without enabling entities first.
        assert value.can is None or entity_defaults()[value.can], value
        assert value.uart is None or value.uart in uart_keys, value
    assert set(INFO_VALUES) <= VALUE_IDS
    assert len(VALUE_IDS) == len(BUS_VALUES) + len(EXTERNAL_VALUES)


@pytest.mark.parametrize("layout", LAYOUTS, ids=lambda path: path.name)
def test_layout_value_ids(layout: Path) -> None:
    """Each layout uses every value ID and no other."""
    assert _svg_value_ids(layout.read_text(encoding="utf-8")) == VALUE_IDS


def test_layouts_present() -> None:
    """The three layouts exist."""
    assert [path.name for path in LAYOUTS] == [
        "daikin_glass_dark.svg",
        "daikin_glass_light.svg",
        "daikin_glass_petrol.svg",
    ]


def test_info_rows() -> None:
    """The info box keeps the given order and drops unknown or repeated rows."""
    assert info_rows({}) == list(INFO_VALUES)
    assert info_rows({"info_rows": ["cop", "error_code", "cop", "bogus"]}) == [
        "cop",
        "error_code",
    ]
    assert info_rows({"info_rows": []}) == []


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("de", "Wärmepumpe"),
        ("de-CH", "Wärmepumpe"),
        ("it", "Pompa di calore"),
        ("nl", "Heat pump"),
    ],
)
def test_panel_title(language: str, title: str) -> None:
    """The sidebar title follows the system language, English otherwise."""
    assert panel_title(language) == title


def _entity_id(hass: HomeAssistant, bus: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", "daikin_heat_pump_control", f"{ENTRY_ID}_{bus}_{key}"
    )
    assert entity_id is not None, (bus, key)
    return entity_id


async def _ws(
    hass_ws_client: WebSocketGenerator, hass: HomeAssistant, message: dict[str, Any]
) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    response: dict[str, Any] = await client.receive_json()
    return response


async def _entities(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> dict[str, Any]:
    response = await _ws(
        hass_ws_client, hass, {"type": "daikin_heat_pump_control/entities"}
    )
    assert response["success"], response
    result: dict[str, Any] = response["result"]
    return result


async def _setup(hass: HomeAssistant, **kwargs: Any) -> Any:
    entry = daikin_entry(hass, **kwargs)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_can_first(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
) -> None:
    """A value on both buses comes from CAN; UART fills in what CAN lacks."""
    await _setup(hass, can=can_esp, uart=uart_esp)
    result = await _entities(hass, hass_ws_client)
    entities = result["entities"]
    assert entities["tv"] == _entity_id(hass, "can", "tv")
    # The UART readings of TV, TVBH and TR are shown as second line.
    assert entities["tv_uart"] == _entity_id(hass, "uart", "tv")
    assert entities["tvbh_uart"] == _entity_id(hass, "uart", "tv_bh")
    assert entities["tr_uart"] == _entity_id(hass, "uart", "tr")
    assert entities["thermal_power"] == _entity_id(hass, "can", "thermal_power")
    assert entities["fan_speed"] == _entity_id(hass, "uart", "fan_speed")
    assert "cop" not in entities
    assert result["info"] == list(INFO_VALUES)


async def test_entities_disabled_can_uses_uart(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
) -> None:
    """A disabled CAN entity counts as missing; a hidden one still counts."""
    await _setup(hass, can=can_esp, uart=uart_esp)
    registry = er.async_get(hass)
    registry.async_update_entity(
        _entity_id(hass, "can", "tv"), disabled_by=er.RegistryEntryDisabler.USER
    )
    registry.async_update_entity(
        _entity_id(hass, "can", "tr"), hidden_by=er.RegistryEntryHider.USER
    )
    entities = (await _entities(hass, hass_ws_client))["entities"]
    assert entities["tv"] == _entity_id(hass, "uart", "tv")
    # Not shown twice: without the CAN reading there is no second line.
    assert "tv_uart" not in entities
    assert entities["tr"] == _entity_id(hass, "can", "tr")
    assert entities["tr_uart"] == _entity_id(hass, "uart", "tr")


async def test_entities_both_disabled(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
) -> None:
    """Without an enabled entity on either bus the value is missing."""
    await _setup(hass, can=can_esp, uart=uart_esp)
    registry = er.async_get(hass)
    for bus in ("can", "uart"):
        registry.async_update_entity(
            _entity_id(hass, bus, "tv"), disabled_by=er.RegistryEntryDisabler.USER
        )
    entities = (await _entities(hass, hass_ws_client))["entities"]
    assert "tv" not in entities
    assert "tv_uart" not in entities


async def test_entities_unavailable_can_stays(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
) -> None:
    """An unavailable CAN entity stays the source of its value."""
    await _setup(hass, can=can_esp, uart=uart_esp)
    tv = _entity_id(hass, "can", "tv")
    await can_esp.drop_connections()
    await wait_for_state(hass, tv, STATE_UNAVAILABLE)
    entities = (await _entities(hass, hass_ws_client))["entities"]
    assert entities["tv"] == tv


async def test_entities_uart_only(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, uart_esp: SimulatedEsp
) -> None:
    """Without CAN the values come from UART."""
    await _setup(hass, uart=uart_esp)
    entities = (await _entities(hass, hass_ws_client))["entities"]
    assert entities["tv"] == _entity_id(hass, "uart", "tv")
    assert "tv_uart" not in entities
    assert "error_code" not in entities


async def test_entities_external_and_info(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, can_esp: SimulatedEsp
) -> None:
    """External values and the info box come from the options."""
    await _setup(
        hass,
        can=can_esp,
        options={
            "external_cop": "sensor.heat_pump_cop",
            "external_room_setpoint": "",
            "info_rows": ["cop", "error_code"],
        },
    )
    result = await _entities(hass, hass_ws_client)
    assert result["entities"]["cop"] == "sensor.heat_pump_cop"
    assert "room_setpoint" not in result["entities"]
    assert result["info"] == ["cop", "error_code"]


async def test_not_loaded(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, can_esp: SimulatedEsp
) -> None:
    """Without a loaded entry the commands answer with an error."""
    entry = await _setup(hass, can=can_esp)
    assert await hass.config_entries.async_unload(entry.entry_id)
    for command in ("entities", "panel_config"):
        response = await _ws(
            hass_ws_client, hass, {"type": f"daikin_heat_pump_control/{command}"}
        )
        assert not response["success"]
        assert response["error"]["code"] == "not_loaded"
    response = await _ws(
        hass_ws_client,
        hass,
        {"type": "daikin_heat_pump_control/panel_config/set", "config": {}},
    )
    assert response["error"]["code"] == "not_loaded"


async def test_panel_config(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_storage: dict[str, Any],
    can_esp: SimulatedEsp,
) -> None:
    """The appearance of the panel is stored and survives a reload."""
    entry = await _setup(hass, can=can_esp)
    response = await _ws(
        hass_ws_client, hass, {"type": "daikin_heat_pump_control/panel_config"}
    )
    assert response["result"] == {"config": {}}
    config = {
        "layout": "petrol",
        "background": {"show": False},
        "box": {"fill": [10, 20, 30], "fill_opacity": 80},
        "text": {"label_color": [1, 2, 3]},
    }
    response = await _ws(
        hass_ws_client,
        hass,
        {"type": "daikin_heat_pump_control/panel_config/set", "config": config},
    )
    assert response["success"], response
    assert response["result"]["config"]["layout"] == "petrol"
    assert hass_storage[f"daikin_heat_pump_control.{ENTRY_ID}.panel"]["data"] == {
        "config": {**config, "box": {"fill": [10, 20, 30], "fill_opacity": 80.0}}
    }
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    response = await _ws(
        hass_ws_client, hass, {"type": "daikin_heat_pump_control/panel_config"}
    )
    assert response["result"]["config"]["layout"] == "petrol"
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"daikin_heat_pump_control.{ENTRY_ID}.panel" not in hass_storage


@pytest.mark.parametrize(
    "config",
    [
        {"layout": "neon"},
        {"box": {"fill": [1, 2]}},
        {"background": {"opacity": 101}},
        {"text": {"value_color": [0, 0, 256]}},
        {"other": 1},
    ],
)
async def test_panel_config_invalid(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    can_esp: SimulatedEsp,
    config: dict[str, Any],
) -> None:
    """An invalid appearance is rejected."""
    await _setup(hass, can=can_esp)
    response = await _ws(
        hass_ws_client,
        hass,
        {"type": "daikin_heat_pump_control/panel_config/set", "config": config},
    )
    assert not response["success"]
    assert response["error"]["code"] == "invalid_format"


async def test_panel_config_admin_only(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    can_esp: SimulatedEsp,
) -> None:
    """Only admins change the appearance; everybody reads it."""
    await _setup(hass, can=can_esp)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id(
        {"type": "daikin_heat_pump_control/panel_config/set", "config": {}}
    )
    response = await client.receive_json()
    assert response["error"]["code"] == "unauthorized"
    await client.send_json_auto_id({"type": "daikin_heat_pump_control/panel_config"})
    assert (await client.receive_json())["success"]
    await client.send_json_auto_id({"type": "daikin_heat_pump_control/entities"})
    assert (await client.receive_json())["success"]


async def test_frontend_and_panel(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """The module is loaded on every page and the panel follows the entry."""
    hass.config.language = "de"
    entry = await _setup(hass, can=can_esp)
    assert any(
        url.startswith("/daikin_heat_pump_control/frontend/daikin-heat-pump.js?v=")
        for url in hass.data[DATA_EXTRA_MODULE_URL].urls
    )
    panel = hass.data[DATA_PANELS][PANEL]
    assert panel.sidebar_title == "Wärmepumpe"
    assert panel.sidebar_icon == "mdi:heat-pump"
    assert panel.require_admin is False
    assert panel.config["_panel_custom"]["name"] == "daikin-heat-pump-panel"
    assert panel.config["entry_id"] == ENTRY_ID
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert PANEL not in hass.data[DATA_PANELS]


async def test_static_files(
    hass: HomeAssistant, hass_client: Any, can_esp: SimulatedEsp
) -> None:
    """The module and the layouts are served."""
    await _setup(hass, can=can_esp)
    client = await hass_client()
    for name in ("daikin-heat-pump.js", "daikin_glass_light.svg"):
        response = await client.get(f"/daikin_heat_pump_control/frontend/{name}")
        assert response.status == 200, name


async def test_options_dashboard(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """The dashboard part stores its options and keeps the others."""
    entry = await _setup(
        hass,
        can=can_esp,
        options={"scan_interval": 60, "external_cop": "sensor.old_cop"},
    )
    result = await options_step(hass, entry, "dashboard")
    fields = {str(key) for key in result["data_schema"].schema}
    assert fields == {
        "show_panel",
        "info_rows",
        *(f"external_{value.id}" for value in EXTERNAL_VALUES),
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "show_panel": False,
            "external_electric_power": "sensor.heat_pump_power",
            "info_rows": ["thermal_power", "error_code"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        "scan_interval": 60,
        "show_panel": False,
        "external_electric_power": "sensor.heat_pump_power",
        "info_rows": ["thermal_power", "error_code"],
    }
    assert entry.state is ConfigEntryState.LOADED
    assert PANEL not in hass.data[DATA_PANELS]
    result = await options_step(hass, entry, "dashboard")
    defaults = {
        str(key): key.default()
        for key in result["data_schema"].schema
        if callable(key.default)
    }
    assert defaults["info_rows"] == ["thermal_power", "error_code"]
    assert defaults["show_panel"] is False
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in result["data_schema"].schema
    }
    assert suggested["external_electric_power"] == "sensor.heat_pump_power"


async def test_options_bus_keeps_dashboard(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Saving the bus part keeps the dashboard options."""
    entry = await _setup(
        hass, can=can_esp, options={"external_cop": "sensor.cop", "show_panel": False}
    )
    result = await options_step(hass, entry, "bus")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["external_cop"] == "sensor.cop"
    assert entry.options["show_panel"] is False
    assert entry.options["scan_interval"] == 20
