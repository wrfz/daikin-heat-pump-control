"""Sensors of the Daikin Heat Pump Control integration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .bridge.node import BridgeNode
from .can.table import CAN_VALUES, CanValue, Platform
from .const import Bus
from .coordinator import COMPUTED_DISABLED_BY_DEFAULT, ERROR_CODE, WRITES_TODAY
from .entity import BridgeEntity, CanEntity, enum_or_none
from .runtime import DaikinConfigEntry

PARALLEL_UPDATES = 0

CAN_STATES = ["error_active", "error_passive", "bus_off", "stopped", "unknown"]


@dataclass(frozen=True, kw_only=True)
class BridgeSensorEntityDescription(SensorEntityDescription):
    """Description of a diagnostic sensor of a bridge node."""

    value_fn: Callable[[BridgeNode], StateType | datetime]
    bus: Bus | None = None


def _can(node: BridgeNode, attr: str) -> int | str | None:
    if node.info is None or node.info.can is None:
        return None
    value: int | str | None = getattr(node.info.can, attr)
    return value


def _can_state(node: BridgeNode) -> str | None:
    state = _can(node, "state")
    if state is None:
        return None
    return state if state in CAN_STATES else "unknown"


def _uart_overflows(node: BridgeNode) -> int | None:
    if node.info is None or node.info.uart is None:
        return None
    return node.info.uart.overflows


BRIDGE_SENSORS: tuple[BridgeSensorEntityDescription, ...] = (
    BridgeSensorEntityDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.info.wifi_rssi if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.info.wifi_ip if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="ssid",
        translation_key="ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.info.wifi_ssid if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="last_restart",
        translation_key="last_restart",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.boot_time,
    ),
    BridgeSensorEntityDescription(
        key="heap_free",
        translation_key="heap_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.info.heap_free if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="heap_max_block",
        translation_key="heap_max_block",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.info.heap_max_block if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="reset_reason",
        translation_key="reset_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda node: node.info.reset_reason if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="bridge_version",
        translation_key="bridge_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.info.bridge_version if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="esphome_version",
        translation_key="esphome_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda node: node.info.esphome_version if node.info else None,
    ),
    BridgeSensorEntityDescription(
        key="can_overflows",
        translation_key="can_overflows",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.CAN,
        value_fn=lambda node: _can(node, "overflows"),
    ),
    BridgeSensorEntityDescription(
        key="can_bus_state",
        translation_key="can_bus_state",
        device_class=SensorDeviceClass.ENUM,
        options=CAN_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.CAN,
        value_fn=_can_state,
    ),
    BridgeSensorEntityDescription(
        key="can_tx_errors",
        translation_key="can_tx_errors",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.CAN,
        value_fn=lambda node: _can(node, "tx_errors"),
    ),
    BridgeSensorEntityDescription(
        key="can_rx_errors",
        translation_key="can_rx_errors",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.CAN,
        value_fn=lambda node: _can(node, "rx_errors"),
    ),
    BridgeSensorEntityDescription(
        key="can_arbitration_lost",
        translation_key="can_arbitration_lost",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        bus=Bus.CAN,
        value_fn=lambda node: _can(node, "arbitration_lost"),
    ),
    BridgeSensorEntityDescription(
        key="can_bus_off",
        translation_key="can_bus_off",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.CAN,
        value_fn=lambda node: _can(node, "bus_off"),
    ),
    BridgeSensorEntityDescription(
        key="uart_overflows",
        translation_key="uart_overflows",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        bus=Bus.UART,
        value_fn=_uart_overflows,
    ),
)


def _can_description(value: CanValue) -> SensorEntityDescription:
    enum = value.platform is Platform.ENUM
    return SensorEntityDescription(
        key=value.key,
        translation_key=value.key,
        device_class=SensorDeviceClass.ENUM
        if enum
        else enum_or_none(SensorDeviceClass, value.device_class),
        options=value.option_keys if enum else None,
        native_unit_of_measurement=value.unit,
        state_class=enum_or_none(SensorStateClass, value.state_class),
        suggested_display_precision=value.precision,
        entity_category=enum_or_none(EntityCategory, value.category),
        entity_registry_enabled_default=value.enabled_default,
    )


def _delta(key: str) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        native_unit_of_measurement=UnitOfTemperature.KELVIN,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=key not in COMPUTED_DISABLED_BY_DEFAULT,
    )


def _power(key: str) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=key not in COMPUTED_DISABLED_BY_DEFAULT,
    )


COMPUTED_SENSORS: tuple[SensorEntityDescription, ...] = (
    _power("thermal_power"),
    _power("thermal_power_raw"),
    _delta("temperature_spread"),
    _delta("temperature_spread_raw"),
    _delta("tv_tvbh_delta"),
    _delta("tvbh_tr_delta"),
    _delta("vorlauf_soll_tv_delta"),
    SensorEntityDescription(
        key="tv_max",
        translation_key="tv_max",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="system_time",
        translation_key="system_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

WRITES_TODAY_SENSOR = SensorEntityDescription(
    key=WRITES_TODAY,
    translation_key=WRITES_TODAY,
    state_class=SensorStateClass.TOTAL,
    entity_category=EntityCategory.DIAGNOSTIC,
)

CAN_SENSORS: tuple[SensorEntityDescription, ...] = (
    *(
        _can_description(value)
        for value in CAN_VALUES
        if value.platform in (Platform.SENSOR, Platform.ENUM)
    ),
    *COMPUTED_SENSORS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    entities: list[SensorEntity] = [
        BridgeSensor(node, description)
        for node in entry.runtime_data.nodes.values()
        for description in BRIDGE_SENSORS
        if description.bus is None or description.bus in node.assigned_buses
    ]
    if (coordinator := entry.runtime_data.can) is not None:
        entities.extend(
            CanErrorCodeSensor(coordinator, description)
            if description.key == ERROR_CODE
            else CanSensor(coordinator, description)
            for description in CAN_SENSORS
        )
        entities.append(WritesTodaySensor(coordinator, WRITES_TODAY_SENSOR))
    async_add_entities(entities)


class CanSensor(CanEntity, SensorEntity):
    """Sensor of a value of the RoCon controller."""

    @property
    @override
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.can_state


class CanErrorCodeSensor(CanSensor):
    """Error code with the numeric code and the finding of the checks."""

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the numeric code and the finding of the checks."""
        finding = self.coordinator.finding
        return {
            "code": self.coordinator.raw(ERROR_CODE),
            "finding": None if finding is None else str(finding),
        }


class WritesTodaySensor(CanEntity, SensorEntity):
    """Number of writes to the heat pump on the current day."""

    @property
    @override
    def native_value(self) -> int:
        """Return the number of writes."""
        return self.coordinator.storage.writes_today()

    @property
    @override
    def extra_state_attributes(self) -> dict[str, int]:
        """Return the writes per value."""
        return self.coordinator.storage.writes_by_key()

    @property
    @override
    def last_reset(self) -> datetime:
        """Return the start of the current day."""
        return dt_util.start_of_local_day()


class BridgeSensor(BridgeEntity, SensorEntity):
    """Diagnostic sensor of a bridge node."""

    entity_description: BridgeSensorEntityDescription

    @property
    @override
    def native_value(self) -> StateType | datetime:
        """Return the value."""
        return self.entity_description.value_fn(self.node)
