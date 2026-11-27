"""Constants for the Daikin Heat Pump Control integration."""

from enum import StrEnum
from typing import Final

DOMAIN: Final = "daikin_heat_pump_control"

DEFAULT_PORT: Final = 6053
CLIENT_INFO: Final = "Daikin Heat Pump Control"

CONF_NODES: Final = "nodes"
CONF_NOISE_PSK: Final = "noise_psk"
CONF_NODE_NAME: Final = "name"
CONF_CAN_NODE: Final = "can_node"
CONF_UART_NODE: Final = "uart_node"
CONF_OUTDOOR_UNIT: Final = "outdoor_unit"
CONF_UART_PROTOCOL: Final = "uart_protocol"

ESPHOME_DOMAIN: Final = "esphome"
ESPHOME_CONF_NOISE_PSK: Final = "noise_psk"
ESPHOME_CONF_DEVICE_NAME: Final = "device_name"

PROJECT_NAME_PREFIX: Final = "wrfz.daikin_"
PROJECT_NAME_PATTERN: Final = "wrfz.daikin_*"


class Bus(StrEnum):
    """Bus served by a bridge node."""

    CAN = "can"
    UART = "uart"


BUS_CONF: Final[dict[Bus, str]] = {Bus.CAN: CONF_CAN_NODE, Bus.UART: CONF_UART_NODE}


class UartProtocol(StrEnum):
    """UART protocol of the indoor unit."""

    AUTO = "auto"
    I = "i"  # noqa: E741
    S = "s"


OUTDOOR_UNITS: Final = (
    "RRLQ004CAV3",
    "RRLQ006CAV3",
    "RRLQ008CAV3",
    "RRLQ011CAW1",
    "ERLQ016CAW1",
    "ERGA04EAV3",
    "ERGA06EAV3",
    "ERGA08DAV3",
    "ERGA08EAV3",
    "ERGA08EAV3H",
    "RRGA08DAV3",
    "RRLQ008BAV3",
    "RDLQ014AA6V3",
)

# Actions offered by the bridge firmware.
ACTION_BRIDGE_INFO: Final = "daikin_bridge_info"
ACTION_CAN_EXCHANGE: Final = "daikin_can_exchange"
ACTION_UART_EXCHANGE: Final = "daikin_uart_exchange"
BUS_EXCHANGE_ACTION: Final[dict[Bus, str]] = {
    Bus.CAN: ACTION_CAN_EXCHANGE,
    Bus.UART: ACTION_UART_EXCHANGE,
}

# Manifest actions of the previous ESPHome components, used to recognise a node
# that still runs the previous firmware.
LEGACY_MANIFEST_ACTIONS: Final[dict[str, Bus]] = {
    "rotex_can_manifest": Bus.CAN,
    "rotex_uart_manifest": Bus.UART,
}

EXCHANGE_INTERVAL: Final = 0.2
INFO_INTERVAL: Final = 60.0
CONNECT_TIMEOUT: Final = 10.0
ACTION_TIMEOUT: Final = 3.0
RECONNECT_MIN_DELAY: Final = 1.0
RECONNECT_MAX_DELAY: Final = 60.0

ISSUE_NO_BRIDGE_FIRMWARE: Final = "no_bridge_firmware"

# Polling of the CAN values (seconds).
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_GROUP_INTERVAL_PREFIX: Final = "interval_"
DEFAULT_SCAN_INTERVAL: Final = 30.0
MIN_SCAN_INTERVAL: Final = 1.0
MAX_SCAN_INTERVAL: Final = 3600.0
TV_MAX_POLL_INTERVAL: Final = 2.0
