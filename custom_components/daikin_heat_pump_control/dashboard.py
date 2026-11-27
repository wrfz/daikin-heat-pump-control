"""Values shown by the dashboard (panel and card) and their entities."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_EXTERNAL_PREFIX, CONF_INFO_ROWS, DOMAIN, Bus
from .entity import bus_unique_id


@dataclass(frozen=True, slots=True, kw_only=True)
class BusValue:
    """A dashboard value read from the buses; CAN is preferred over UART."""

    id: str
    can: str | None = None
    uart: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalValue:
    """A dashboard value taken from an entity chosen in the options."""

    id: str
    domains: tuple[str, ...] = (Platform.SENSOR,)
    device_class: str | None = None


BUS_VALUES: Final[tuple[BusValue, ...]] = (
    # CAN reads the outside sensor of the controller, UART the air sensor of
    # the outdoor unit: two sensors at different places.
    BusValue(id="temperature_outside", can="temperature_outside", uart="outdoor_temp"),
    BusValue(id="ta2", can="ta2"),
    BusValue(id="tv", can="tv", uart="tv"),
    BusValue(id="tr", can="tr", uart="tr"),
    BusValue(id="tvbh", can="tvbh", uart="tv_bh"),
    BusValue(
        id="target_supply_temperature",
        can="target_supply_temperature",
        uart="supply_setpoint",
    ),
    BusValue(
        id="temperature_spread", can="temperature_spread", uart="temperature_spread"
    ),
    BusValue(id="thermal_power", can="thermal_power", uart="thermal_power"),
    BusValue(id="flow_rate", can="flow_rate", uart="flow_rate"),
    BusValue(id="circulation_pump", can="circulation_pump", uart="circulation_pump"),
    BusValue(id="pump_running", can="status_kesselpumpe", uart="water_pump"),
    BusValue(id="compressor_running", can="status_kompressor"),
    BusValue(id="water_pressure", can="water_pressure"),
    BusValue(id="hot_water_temperature", can="tdhw1", uart="dhw_temp"),
    BusValue(
        id="hot_water_setpoint",
        can="target_hot_water_temperature_1",
        uart="dhw_setpoint",
    ),
    BusValue(id="dhw_mixer_position", can="dhw_mixer_position"),
    BusValue(id="bypass_valve", can="bypass_valve"),
    BusValue(id="error_code", can="error_code"),
    BusValue(id="operating_mode", can="operating_mode"),
    BusValue(id="mode_of_operating", can="mode_of_operating", uart="mode_of_operating"),
    BusValue(id="liquid_temperature", can="tliq", uart="t_liq"),
    BusValue(id="expansion_valve", uart="exv"),
    BusValue(id="four_way_valve", uart="4_way_valve"),
    BusValue(id="pressure_equalization", uart="press_eq"),
    BusValue(id="evaporator_temperature", uart="exch_temp"),
    BusValue(id="hot_gas_temperature", uart="temp_after_compr"),
    BusValue(id="discharge_superheat", uart="discharge_superheat"),
    BusValue(id="subcooling", uart="subcooling"),
    BusValue(id="saturation_temperature", uart="saturation_temp"),
    BusValue(id="refrigerant_pressure", uart="refrigerant_pressure"),
    BusValue(id="fan_speed", uart="fan_speed"),
    BusValue(id="compressor_speed", uart="inv_freq"),
)

EXTERNAL_VALUES: Final[tuple[ExternalValue, ...]] = (
    ExternalValue(id="cop"),
    ExternalValue(id="electric_power", device_class="power"),
    ExternalValue(id="room_temperature", device_class="temperature"),
    ExternalValue(
        id="room_setpoint",
        domains=("input_number", Platform.NUMBER, Platform.SENSOR),
    ),
    ExternalValue(id="hot_gas_condenser", device_class="temperature"),
    ExternalValue(id="backup_heater_power", device_class="power"),
)

# Values the info box can show, in their default order.
INFO_VALUES: Final[tuple[str, ...]] = (
    "error_code",
    "operating_mode",
    "mode_of_operating",
    "thermal_power",
    "electric_power",
    "cop",
    "room_temperature",
    "room_setpoint",
)

VALUE_IDS: Final[frozenset[str]] = frozenset(
    [value.id for value in BUS_VALUES] + [value.id for value in EXTERNAL_VALUES]
)


def external_option(value: ExternalValue) -> str:
    """Return the option key holding the entity of an external value."""
    return f"{CONF_EXTERNAL_PREFIX}{value.id}"


def info_rows(options: Mapping[str, Any]) -> list[str]:
    """Return the rows of the info box in their order."""
    rows = options.get(CONF_INFO_ROWS)
    if not isinstance(rows, list):
        return list(INFO_VALUES)
    return [row for row in dict.fromkeys(rows) if row in INFO_VALUES]


def _bus_entities(hass: HomeAssistant, entry: ConfigEntry, bus: Bus) -> dict[str, str]:
    """Return the enabled entities of a bus by key."""
    prefix = bus_unique_id(entry, bus, "")
    return {
        entity.unique_id.removeprefix(prefix): entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.unique_id.startswith(prefix)
        and entity.disabled_by is None
        and entity.platform == DOMAIN
    }


def dashboard_entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Return the entity of every dashboard value that has one."""
    can = _bus_entities(hass, entry, Bus.CAN)
    uart = _bus_entities(hass, entry, Bus.UART)
    entities: dict[str, str] = {}
    for value in BUS_VALUES:
        if value.can is not None and value.can in can:
            entities[value.id] = can[value.can]
        elif value.uart is not None and value.uart in uart:
            entities[value.id] = uart[value.uart]
    for external in EXTERNAL_VALUES:
        entity_id = entry.options.get(external_option(external))
        if isinstance(entity_id, str) and entity_id:
            entities[external.id] = entity_id
    return entities
