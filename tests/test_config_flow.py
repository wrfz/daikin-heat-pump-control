"""Tests for the config flow."""

from ipaddress import ip_address
from typing import Any

import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from helpers import (
    DOMAIN,
    MAC_BOTH,
    MAC_CAN,
    MAC_UART,
    daikin_entry,
    esphome_entry,
    options_step,
)
from sim.esp import (
    FIRMWARE_LEGACY_CAN,
    FIRMWARE_LEGACY_UART,
    FIRMWARE_OTHER,
    SimulatedEsp,
    make_noise_psk,
)


def _zeroconf(esp: SimulatedEsp, **properties: Any) -> ZeroconfServiceInfo:
    props = {
        "mac": esp.mac.replace(":", ""),
        "project_name": esp.project_name,
        "friendly_name": "",
        "api_encryption": "Noise_NNpsk0_25519_ChaChaPoly_SHA256",
    }
    props.update(properties)
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname=f"{esp.name}.local.",
        name=f"{esp.name}._esphomelib._tcp.local.",
        port=esp.port,
        type="_esphomelib._tcp.local.",
        properties=props,
    )


async def _start_search(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )


def _options(result: dict[str, Any], key: str) -> list[str]:
    for field, selector in result["data_schema"].schema.items():
        if str(field) == key:
            return [o["value"] for o in selector.config["options"]]
    return []


def _default(result: dict[str, Any], key: str) -> Any:
    for field in result["data_schema"].schema:
        if str(field) == key:
            return field.default() if callable(field.default) else field.default
    raise KeyError(key)


async def test_search_two_nodes(
    hass: HomeAssistant,
    can_esp: SimulatedEsp,
    uart_esp: SimulatedEsp,
    esp_factory: Any,
) -> None:
    """ESPHome entries are probed, bridges and previous firmware are offered."""
    legacy = await esp_factory(
        name="hpsu-can", mac="aa:bb:cc:00:00:10", firmware=FIRMWARE_LEGACY_CAN, can=True
    )
    other = await esp_factory(
        name="lamp", mac="aa:bb:cc:00:00:11", firmware=FIRMWARE_OTHER
    )
    for esp in (can_esp, uart_esp, legacy, other):
        esphome_entry(hass, esp)
    # An ESPHome entry with a wrong key is skipped.
    broken = await esp_factory(name="broken", mac="aa:bb:cc:00:00:12", can=True)
    esphome_entry(hass, broken, noise_psk=make_noise_psk(99))

    result = await _start_search(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "assign"
    assert _options(result, "can_node") == ["none", MAC_CAN, legacy.mac]
    assert _options(result, "uart_node") == ["none", MAC_UART]
    assert _default(result, "uart_node") == MAC_UART

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": MAC_CAN, "uart_node": MAC_UART}
    )
    assert result["step_id"] == "uart"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_unit": "ERGA08EAV3", "uart_protocol": "auto"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Daikin Heat Pump"
    assert result["data"] == {
        "nodes": {
            MAC_CAN: {
                "host": "127.0.0.1",
                "port": can_esp.port,
                "noise_psk": can_esp.noise_psk,
                "name": "daikin-can",
            },
            MAC_UART: {
                "host": "127.0.0.1",
                "port": uart_esp.port,
                "noise_psk": uart_esp.noise_psk,
                "name": "daikin-uart",
            },
        },
        "can_node": MAC_CAN,
        "uart_node": MAC_UART,
    }
    assert result["options"] == {"outdoor_unit": "ERGA08EAV3", "uart_protocol": "auto"}
    entry = result["result"]
    assert entry.unique_id == DOMAIN
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_node_with_both_buses_preselected(
    hass: HomeAssistant, both_esp: SimulatedEsp, can_esp: SimulatedEsp
) -> None:
    """A node with both buses is preselected for both when it is the only dual one."""
    esphome_entry(hass, both_esp)
    esphome_entry(hass, can_esp)
    result = await _start_search(hass)
    assert _default(result, "can_node") == MAC_BOTH
    assert _default(result, "uart_node") == MAC_BOTH


async def test_legacy_uart_offered(hass: HomeAssistant, esp_factory: Any) -> None:
    """A UART node with the previous firmware is offered with a mark."""
    legacy = await esp_factory(
        name="hpsu-uart", mac=MAC_UART, firmware=FIRMWARE_LEGACY_UART, uart=True
    )
    esphome_entry(hass, legacy)
    result = await _start_search(hass)
    labels = [
        o["label"]
        for field, selector in result["data_schema"].schema.items()
        if str(field) == "uart_node"
        for o in selector.config["options"]
    ]
    assert labels[1].endswith(" *")
    assert "can_node" not in [str(field) for field in result["data_schema"].schema]


async def test_manual_errors_and_success(
    hass: HomeAssistant, can_esp: SimulatedEsp, esp_factory: Any
) -> None:
    """Without ESPHome entries the manual form is shown and validated."""
    result = await _start_search(hass)
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "no_nodes_found"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "127.0.0.1", "port": can_esp.port, "noise_psk": make_noise_psk(5)},
    )
    assert result["errors"] == {"base": "invalid_auth"}

    other = await esp_factory(
        name="lamp", mac="aa:bb:cc:00:00:11", firmware=FIRMWARE_OTHER
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "127.0.0.1", "port": other.port, "noise_psk": other.noise_psk},
    )
    assert result["errors"] == {"base": "not_daikin_node"}

    port = can_esp.port
    await can_esp.stop()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "127.0.0.1", "port": port, "noise_psk": can_esp.noise_psk},
    )
    assert result["errors"] == {"base": "cannot_connect"}

    await can_esp.start(port)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "127.0.0.1", "port": port, "noise_psk": can_esp.noise_psk},
    )
    assert result["step_id"] == "assign"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": "none"}
    )
    assert result["errors"] == {"base": "no_bus"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": MAC_CAN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["uart_node"] is None
    assert result["options"] == {}


async def test_add_manual_from_assign(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """A second node can be added manually after the search."""
    esphome_entry(hass, can_esp)
    result = await _start_search(hass)
    assert "uart_node" not in [str(field) for field in result["data_schema"].schema]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": MAC_CAN, "add_manual": True}
    )
    assert result["step_id"] == "manual"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "127.0.0.1", "port": uart_esp.port, "noise_psk": uart_esp.noise_psk},
    )
    assert result["step_id"] == "assign"
    assert _default(result, "can_node") == MAC_CAN
    assert _default(result, "uart_node") == MAC_UART


async def test_single_instance(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """Only one entry is allowed."""
    daikin_entry(hass, can=can_esp)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.parametrize(
    "properties",
    [{"project_name": "esphome.web"}, {"mac": ""}],
)
async def test_zeroconf_not_a_bridge(
    hass: HomeAssistant, can_esp: SimulatedEsp, properties: dict[str, str]
) -> None:
    """Other firmware is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=_zeroconf(can_esp, **properties),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_daikin_bridge"


async def test_zeroconf_with_esphome_key(
    hass: HomeAssistant, uart_esp: SimulatedEsp
) -> None:
    """The key of the ESPHome entry is used; the UART step follows."""
    esphome_entry(hass, uart_esp)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(uart_esp)
    )
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"]["buses"] == "UART"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "uart"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "i"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["uart_node"] == MAC_UART
    assert result["result"].unique_id == DOMAIN


async def test_zeroconf_asks_for_key(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """Without ESPHome entry the key is asked for and checked."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(can_esp)
    )
    assert result["step_id"] == "discovery_key"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"noise_psk": make_noise_psk(3)}
    )
    assert result["step_id"] == "discovery_key"
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"noise_psk": can_esp.noise_psk}
    )
    assert result["step_id"] == "discovery_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["can_node"] == MAC_CAN


async def test_zeroconf_unreachable(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """A discovered node that cannot be reached aborts."""
    esphome_entry(hass, can_esp)
    info = _zeroconf(can_esp)
    await can_esp.stop()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_updates_known_host(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """A known node gets its new address."""
    entry = daikin_entry(hass, can=can_esp)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "nodes": {MAC_CAN: {**entry.data["nodes"][MAC_CAN], "port": 1}},
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(can_esp)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["nodes"][MAC_CAN]["port"] == can_esp.port


async def test_zeroconf_assign_new_node(
    hass: HomeAssistant, can_esp: SimulatedEsp, both_esp: SimulatedEsp
) -> None:
    """A new bridge replaces the CAN node and adds the UART bus."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    esphome_entry(hass, both_esp)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(both_esp)
    )
    assert result["step_id"] == "discovery_assign"
    assert result["description_placeholders"]["can"] == "daikin-can"
    assert result["description_placeholders"]["uart"] == "-"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": "use_new", "uart_node": "use_new"}
    )
    assert result["step_id"] == "uart"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "auto"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "node_assigned"
    await hass.async_block_till_done()
    assert set(entry.data["nodes"]) == {MAC_BOTH}
    assert entry.data["can_node"] == MAC_BOTH
    assert entry.data["uart_node"] == MAC_BOTH
    assert entry.options["outdoor_unit"] == "RRLQ008CAV3"
    registry = dr.async_get(hass)
    assert (
        registry.async_get_device_by_identifier(
            (DOMAIN, f"bridge_{MAC_CAN}"), entry.entry_id
        )
        is None
    )
    assert can_esp.connection_count == 0


async def test_zeroconf_assign_nothing(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """Keeping all buses changes nothing."""
    daikin_entry(hass, can=can_esp)
    esphome_entry(hass, uart_esp)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(uart_esp)
    )
    assert result["step_id"] == "discovery_assign"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"uart_node": "keep"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_changes"


async def test_zeroconf_ignored_node(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """A node the user ignored is not offered again."""
    MockConfigEntry(domain=DOMAIN, unique_id=MAC_CAN, source="ignore").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(can_esp)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """Reconfigure starts from the current assignment and keeps offline nodes."""
    entry = daikin_entry(hass, can=can_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    esphome_entry(hass, uart_esp)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    assert result["step_id"] == "assign"
    assert _default(result, "can_node") == MAC_CAN
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": MAC_CAN, "uart_node": MAC_UART}
    )
    assert result["step_id"] == "uart"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"outdoor_unit": "RRLQ008CAV3", "uart_protocol": "s"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["uart_node"] == MAC_UART
    assert entry.options["uart_protocol"] == "s"
    assert uart_esp.connection_count == 1


async def test_reconfigure_offline_node_kept(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """A node that is offline during reconfigure stays selectable."""
    entry = daikin_entry(hass, can=can_esp, uart=uart_esp)
    await can_esp.stop()
    esphome_entry(hass, uart_esp)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "search"}
    )
    assert _options(result, "can_node") == ["none", MAC_CAN]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"can_node": "none", "uart_node": MAC_UART}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["nodes"].keys() == {MAC_UART}


async def test_reauth(hass: HomeAssistant, can_esp: SimulatedEsp) -> None:
    """A new key is asked for and checked."""
    entry = daikin_entry(hass, can=can_esp)
    can_esp.noise_psk = make_noise_psk(50)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"noise_psk": make_noise_psk(51)}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"noise_psk": make_noise_psk(50)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["nodes"][MAC_CAN]["noise_psk"] == make_noise_psk(50)
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth_unreachable_during_confirm(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """A node that goes offline while the key is entered shows an error."""
    entry = daikin_entry(hass, can=can_esp)
    can_esp.noise_psk = make_noise_psk(50)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    await can_esp.stop()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"noise_psk": make_noise_psk(50)}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_key_from_esphome_entry(
    hass: HomeAssistant, can_esp: SimulatedEsp, uart_esp: SimulatedEsp
) -> None:
    """The current key of the ESPHome entry fixes the reauth without asking."""
    entry = daikin_entry(hass, can=can_esp, uart=uart_esp)
    can_esp.noise_psk = make_noise_psk(60)
    esphome_entry(hass, can_esp)
    await uart_esp.stop()
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["nodes"][MAC_CAN]["noise_psk"] == make_noise_psk(60)


async def test_options(hass: HomeAssistant, uart_esp: SimulatedEsp) -> None:
    """Outdoor unit and protocol can be changed."""
    entry = daikin_entry(hass, uart=uart_esp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await options_step(hass, entry, "bus")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outdoor_unit": "ERGA04EAV3", "uart_protocol": "s"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {
        "outdoor_unit": "ERGA04EAV3",
        "uart_protocol": "s",
        "preferred_master": False,
    }
    assert entry.state is ConfigEntryState.LOADED


async def test_options_polling_intervals(
    hass: HomeAssistant, can_esp: SimulatedEsp
) -> None:
    """With CAN the polling intervals can be set; a cleared group interval is removed."""
    entry = daikin_entry(
        hass, can=can_esp, options={"scan_interval": 30, "interval_counter": 600}
    )
    result = await options_step(hass, entry, "bus")
    fields = {str(key) for key in result["data_schema"].schema}
    assert fields == {
        "scan_interval",
        "interval_measurement",
        "interval_state",
        "interval_setting",
        "interval_counter",
        "tv_offset",
        "tvbh_offset",
        "tr_offset",
        "max_spread_tvbh_tv",
        "max_spread_tvbh_tr",
        "preferred_master",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 60, "interval_setting": 300, "tv_offset": -0.5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "scan_interval": 60,
        "interval_setting": 300,
        "tv_offset": -0.5,
        "tvbh_offset": 0.0,
        "tr_offset": 0.0,
        "max_spread_tvbh_tv": 0.3,
        "max_spread_tvbh_tr": 0.3,
        "preferred_master": False,
    }


async def test_options_both_buses(hass: HomeAssistant, both_esp: SimulatedEsp) -> None:
    """With both buses the form holds the intervals and the UART settings."""
    entry = daikin_entry(hass, can=both_esp, uart=both_esp)
    result = await options_step(hass, entry, "bus")
    fields = {str(key) for key in result["data_schema"].schema}
    assert {"scan_interval", "outdoor_unit", "uart_protocol"} <= fields
