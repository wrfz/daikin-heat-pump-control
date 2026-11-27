"""Bridge between Home Assistant and the CAN / UART bus of a Daikin heat pump.

The component has no protocol knowledge. It buffers received data, sends
data handed over by the integration (CAN frames only after the bus was quiet
for a while) and reports diagnostic values. The API actions that call it are
declared in the YAML packages.
"""

import esphome.codegen as cg
from esphome.components import canbus, uart
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@wrfz"]
DEPENDENCIES = ["api"]
AUTO_LOAD = ["json"]

BRIDGE_VERSION = "1.0.0"

CONF_CAN = "can"
CONF_UART = "uart"
CONF_CANBUS_ID = "canbus_id"
CONF_UART_ID = "uart_id"
CONF_BUFFER_SIZE = "buffer_size"
CONF_SEND_QUEUE_SIZE = "send_queue_size"
CONF_QUIET_TIME = "quiet_time"

daikin_bridge_ns = cg.esphome_ns.namespace("daikin_bridge")
DaikinBridge = daikin_bridge_ns.class_("DaikinBridge", cg.Component)

CAN_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_CANBUS_ID): cv.use_id(canbus.CanbusComponent),
        cv.Optional(CONF_BUFFER_SIZE, default=256): cv.int_range(min=16, max=2048),
        cv.Optional(CONF_SEND_QUEUE_SIZE, default=16): cv.int_range(min=1, max=64),
        cv.Optional(CONF_QUIET_TIME, default="250ms"): cv.positive_time_period_milliseconds,
    }
)

UART_SCHEMA = cv.Schema(
    {
        cv.GenerateID(CONF_UART_ID): cv.use_id(uart.UARTComponent),
        cv.Optional(CONF_BUFFER_SIZE, default=1024): cv.int_range(min=64, max=8192),
    }
)

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(DaikinBridge),
            cv.Optional(CONF_CAN): CAN_SCHEMA,
            cv.Optional(CONF_UART): UART_SCHEMA,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.has_at_least_one_key(CONF_CAN, CONF_UART),
)


async def to_code(config):
    """Generate the component."""
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add_define("DAIKIN_BRIDGE_VERSION", BRIDGE_VERSION)
    if can_config := config.get(CONF_CAN):
        cg.add_define("USE_DAIKIN_BRIDGE_CAN")
        bus = await cg.get_variable(can_config[CONF_CANBUS_ID])
        cg.add(var.set_canbus(bus))
        cg.add(var.set_can_buffer_size(can_config[CONF_BUFFER_SIZE]))
        cg.add(var.set_can_send_queue_size(can_config[CONF_SEND_QUEUE_SIZE]))
        cg.add(var.set_quiet_time(can_config[CONF_QUIET_TIME].total_milliseconds))
    if uart_config := config.get(CONF_UART):
        cg.add_define("USE_DAIKIN_BRIDGE_UART")
        bus = await cg.get_variable(uart_config[CONF_UART_ID])
        cg.add(var.set_uart(bus))
        cg.add(var.set_uart_buffer_size(uart_config[CONF_BUFFER_SIZE]))
