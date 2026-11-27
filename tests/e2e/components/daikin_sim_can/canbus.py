"""CAN bus platform that exchanges frames with the simulator over UDP."""

import esphome.codegen as cg
from esphome.components.canbus import CanbusComponent
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PORT

from esphome.components import canbus

DEPENDENCIES = ["host"]

daikin_sim_can_ns = cg.esphome_ns.namespace("daikin_sim_can")
SimCan = daikin_sim_can_ns.class_("SimCan", CanbusComponent)

CONFIG_SCHEMA = canbus.CANBUS_SCHEMA.extend(
    {
        cv.GenerateID(): cv.declare_id(SimCan),
        cv.Required(CONF_PORT): cv.port,
    }
)


async def to_code(config):
    """Generate the platform."""
    var = cg.new_Pvariable(config[CONF_ID])
    cg.add(var.set_port(config[CONF_PORT]))
    await canbus.register_canbus(var, config, reports_status=False)
