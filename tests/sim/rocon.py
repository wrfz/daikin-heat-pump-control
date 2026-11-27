"""Register contents of a simulated RoCon controller in a typical heating state.

Each entry is (answering node, register address, two data bytes). For long
registers (0xFA hh ll) the data bytes are bytes 5-6 of the answer, for short
registers bytes 3-4.
"""

from .heat_pump import HeatPump

C = 0x180  # controller
R = 0x300  # room unit / mixer module side
B = 0x500  # outdoor unit side


def _long(high: int, low: int) -> tuple[int, int, int]:
    return (0xFA, high, low)


REGISTERS: list[tuple[int, tuple[int, ...], bytes]] = [
    (C, _long(0x01, 0x44), b"\x00\x00"),  # 1x hot water: off
    (C, _long(0x06, 0x91), b"\x00\x32"),  # heat pump hysteresis 5.0 K
    (C, _long(0x06, 0x92), b"\x00\x3c"),  # backup heater waiting time 60 min
    (C, _long(0x06, 0x9A), b"\x00\x03"),  # outdoor unit 8
    (C, _long(0x06, 0x99), b"\x00\x02"),  # indoor unit 308
    (C, _long(0x01, 0x0C), b"\x04\x00"),  # building insulation normal
    (C, _long(0x05, 0x87), b"\x02\x8a"),  # anti-legionella 65 °C
    (C, _long(0x01, 0x01), b"\x07\x00"),  # anti-legionella day Sunday
    (C, _long(0x06, 0x5E), b"\x00\x05"),  # circulation interval on 5 min
    (C, _long(0x06, 0x5F), b"\x00\x0a"),  # circulation interval off 10 min
    (C, _long(0x01, 0x82), b"\x00\x01"),  # circulation with hot water program
    (C, _long(0x06, 0x73), b"\x01\xc2"),  # switching threshold 45 °C
    (C, _long(0x01, 0x80), b"\x00\x3c"),  # max. hot water loading 60 min
    (C, _long(0x4E, 0x3F), b"\x00\x1e"),  # hot water blocking 30 min
    (C, _long(0x06, 0x6D), b"\x00\x32"),  # TDiff 5 K
    (C, _long(0x01, 0xD6), b"\x01\x2c"),  # T-WE 30.0 °C
    (C, _long(0xC0, 0xFF), b"\xff\xce"),  # outside -5.0 °C
    (C, _long(0xC1, 0x05), b"\xff\xd3"),  # TA2 -4.5 °C
    (C, _long(0xC1, 0x03), b"\x00\xfa"),  # Tliq 25.0 °C
    (R, _long(0x0A, 0x0C), b"\xff\xce"),  # T-outside -5.0 °C
    (R, _long(0x00, 0x11), b"\x00\xd7"),  # room 21.5 °C
    (C, _long(0x00, 0x0E), b"\x01\xf4"),  # hot water 50.0 °C
    (C, _long(0xC1, 0x06), b"\x01\xea"),  # hot water 2 49.0 °C
    (C, (0x1C,), b"\x07\x08"),  # water pressure 1.8 bar
    (C, _long(0xC0, 0xF7), b"\x00\x46"),  # circulation pump 70 %
    (C, _long(0x06, 0x7F), b"\x00\x32"),  # pump min 50 %
    (C, _long(0x06, 0x7E), b"\x00\x64"),  # pump max 100 %
    (C, _long(0xC0, 0xFB), b"\x00\x00"),  # bypass valve 0 %
    (C, _long(0x06, 0x9B), b"\x00\x00"),  # hot water mixer 0 %
    (C, (0x02,), b"\x01\x2c"),  # flow setpoint 30.0 °C
    (C, _long(0x09, 0x20), b"\x00\x0c"),  # backup heater energy heating 12 kWh
    (C, _long(0x06, 0xA7), b"\x1f\x40"),  # heating energy 8000 kWh
    (C, _long(0x09, 0x1C), b"\x00\x05"),  # backup heater energy hot water 5 kWh
    (C, _long(0x09, 0x2C), b"\x07\xd0"),  # hot water energy 2000 kWh
    (C, _long(0x09, 0x30), b"\x27\x10"),  # total energy 10000 kWh
    (C, _long(0x06, 0xA6), b"\x00\x00"),  # cooling energy 0 kWh
    (C, _long(0xC2, 0xFA), b"\x0b\xb8"),  # electrical energy 3000 kWh
    (C, _long(0x06, 0xA5), b"\x13\x88"),  # compressor runtime 5000 h
    (C, _long(0x06, 0xA4), b"\x17\x70"),  # pump runtime 6000 h
    (C, _long(0x06, 0x83), b"\x00\x32"),  # spread heating 5 K
    (C, _long(0x06, 0x84), b"\x00\x50"),  # spread hot water 8 K
    (C, _long(0x0A, 0x00), b"\xff\x60"),  # antifreeze off
    (C, _long(0xC0, 0xFC), b"\x01\x2c"),  # TV 30.0 °C
    (C, _long(0xC0, 0xFE), b"\x01\x2c"),  # TVBH 30.0 °C
    (C, _long(0xC1, 0x00), b"\x00\xfa"),  # TR 25.0 °C
    (C, _long(0x01, 0xDA), b"\x04\xb0"),  # flow 1200 L/h
    (C, _long(0x06, 0x9C), b"\x00\xc8"),  # flow calculated 20.0 L/min
    (C, _long(0x06, 0x89), b"\x00\x96"),  # flow setpoint 15 L/min
    (C, _long(0x06, 0x88), b"\x00\x78"),  # flow min 12 L/min
    (C, _long(0x06, 0x8A), b"\x00\x0a"),  # flow hysteresis 1.0 L/min
    (C, (0x05,), b"\x00\xd7"),  # room setpoint 1 21.5 °C
    (C, (0x06,), b"\x00\xd2"),  # room setpoint 2 21.0 °C
    (C, (0x07,), b"\x00\xc8"),  # room setpoint 3 20.0 °C
    (C, _long(0x01, 0x29), b"\x01\x90"),  # flow temperature day 40.0 °C
    (C, _long(0x01, 0x2A), b"\x01\x2c"),  # flow temperature night 30.0 °C
    (C, _long(0x01, 0x16), b"\x00\xc8"),  # heating limit day 20 °C
    (C, _long(0x01, 0x17), b"\x00\x5a"),  # heating limit night off
    (C, _long(0x01, 0x0E), b"\x00\x37"),  # heating curve 0.55
    (C, _long(0x01, 0x2B), b"\x00\xfa"),  # min. flow 25.0 °C
    (C, (0x28,), b"\x01\xc2"),  # max. flow 45.0 °C
    (C, (0x13,), b"\x01\xf4"),  # hot water setpoint 1 50 °C
    (C, _long(0x0A, 0x06), b"\x01\xc2"),  # hot water setpoint 2 45 °C
    (C, _long(0x01, 0x3E), b"\x02\x08"),  # hot water setpoint 3 52 °C
    (C, _long(0xC0, 0xF6), b"\x00\x01"),  # operating state heating
    (C, _long(0x01, 0x12), b"\x03\x00"),  # operating mode heating
    (C, _long(0x06, 0x96), b"\x00\x00"),  # quiet mode off
    (C, _long(0x13, 0x88), b"\x00\x00"),  # no error
    (B, (0x61,), b"\x01\x00"),  # compressor on
    (C, _long(0x0A, 0x8C), b"\x00\x01"),  # boiler pump on
    (C, _long(0x09, 0x61), b"\x00\x05"),  # external outside sensor configured
    (C, _long(0x01, 0x76), b"\x00\x00"),  # energy saving off
    (C, _long(0x01, 0x41), b"\x00\x00"),  # heating circuit weather-compensated
    (C, _long(0x06, 0x94), b"\x00\x00"),  # SG mode off
    (C, _long(0x06, 0x93), b"\x00\x00"),  # Smart Grid off
    (C, _long(0x06, 0xD2), b"\x00\x01"),  # backup heater function optional
    (C, _long(0x06, 0x6C), b"\x00\x01"),  # heating support on
    (C, _long(0x06, 0x68), b"\x01\x2c"),  # hot water power 3 kW
    (C, _long(0x06, 0x69), b"\x01\x2c"),  # backup heater stage 1 3 kW
    (C, _long(0x06, 0x6A), b"\x02\x58"),  # backup heater stage 2 6 kW
    (C, _long(0x06, 0x6B), b"\x03\x84"),  # bivalent power 9 kW
    (C, _long(0x0A, 0x20), b"\x0d\x00"),  # electric heater 6 kW
    (C, _long(0xC0, 0xF8), b"\x00\x03"),  # Smart Grid state normal
    (C, _long(0x06, 0x6E), b"\x02\x08"),  # max. heating 52 °C
    (B, _long(0x06, 0xD3), b"\x00\x00"),  # bivalence function off
    (B, _long(0x06, 0xD4), b"\xff\xec"),  # bivalence -2.0 °C
    (C, _long(0x06, 0xA0), b"\x00\x00"),  # flow adjustment heating 0 K
    (C, _long(0x06, 0xA1), b"\x00\x00"),  # flow adjustment cooling 0 K
    (C, _long(0x06, 0x78), b"\x00\x00"),  # room thermostat off
    (R, _long(0x01, 0x15), b"\x00\x00"),  # heating curve adaptation off
    (C, _long(0x01, 0x22), b"\x1b\x00"),  # day 27
    (C, _long(0x01, 0x23), b"\x0b\x00"),  # month 11
    (C, _long(0x01, 0x24), b"\x1a\x00"),  # year 2026
    (C, _long(0x01, 0x25), b"\x0c\x00"),  # hour 12
    (C, _long(0x01, 0x26), b"\x1e\x00"),  # minute 30
    (C, _long(0x01, 0x27), b"\x2d\x00"),  # second 45
    (C, _long(0x07, 0x25), b"\x07\x08"),  # target pressure 1.8 bar
    (C, _long(0x07, 0x26), b"\x01\xf4"),  # max. pressure drop 0.5 bar
    (C, _long(0x07, 0x27), b"\x0b\xb8"),  # max. pressure 3.0 bar
    (C, _long(0x07, 0x28), b"\x03\xe8"),  # min. pressure 1.0 bar
    (C, _long(0x13, 0x5B), b"\x00\xfa"),  # cooling start 25.0 °C
    (C, _long(0x13, 0x5C), b"\x01\x5e"),  # cooling max. 35.0 °C
    (C, _long(0x13, 0x5D), b"\x00\xb4"),  # cooling flow at start 18.0 °C
    (C, _long(0x13, 0x5E), b"\x00\xa0"),  # cooling flow at max. 16.0 °C
    (C, _long(0x13, 0x63), b"\x00\x96"),  # min. cooling flow 15.0 °C
    (C, _long(0x03, 0xDD), b"\x00\xb4"),  # cooling flow 18.0 °C
    (C, _long(0xC1, 0xC3), b"\x00\x5a"),  # heating/cooling switchover off
    (C, _long(0x13, 0x59), b"\xff\xfb"),  # cooling setpoint correction -0.5 K
]


def load_rocon(heat_pump: HeatPump) -> None:
    """Fill the CAN registers of a heat pump with the typical values."""
    for responder, register, value in REGISTERS:
        heat_pump.set_can(responder, register, value)
