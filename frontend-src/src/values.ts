// Boxes of the schematic and how their values are shown. The SVG layouts mark
// the value rectangles with `data-value` and the label rectangles with
// `data-label`; this table adds what the layout does not describe.

export interface GroupSpec {
  /** Element ID of the group in the layout. */
  id: string;
  /** Font size of the values. */
  fontSize?: number;
  /** Vertical offset of the text from the middle of its rectangle. */
  offset?: number;
  /** Values start at the left edge of their rectangle. */
  alignLeft?: boolean;
  /** The group is a framed box (otherwise only text on the drawing). */
  framed?: boolean;
  /** Rows follow the info box order of the integration. */
  info?: boolean;
}

export interface ValueSpec {
  /** Fixed number of decimals of numeric values. */
  digits: number;
  /** Show "---" instead of "not available" (values of some operating states). */
  dashUnknown?: boolean;
  /** A short prefix in label style before the value. */
  prefix?: boolean;
}

const BOX = { framed: true } as const;

export const GROUPS: readonly GroupSpec[] = [
  { id: "TA", ...BOX },
  { id: "TA2", ...BOX },
  { id: "EEV", ...BOX },
  { id: "Kondensat", ...BOX },
  { id: "Umwaelzpumpe", ...BOX },
  { id: "Durchfluss", ...BOX },
  { id: "Ruecklauf", ...BOX },
  { id: "Verdampfer", ...BOX },
  { id: "hot_gas", ...BOX },
  { id: "Kondensation", ...BOX },
  { id: "hot_gas_condenser", ...BOX },
  { id: "Spreizung", ...BOX },
  { id: "Vorlauf", ...BOX },
  { id: "Vorlauf-Soll", ...BOX },
  { id: "Druck", ...BOX },
  { id: "Vorlauf-BH", ...BOX },
  { id: "Luefter", ...BOX },
  { id: "Verdichter", ...BOX },
  { id: "Speicher", ...BOX },
  { id: "Speicher-Soll", ...BOX },
  { id: "buh", ...BOX },
  { id: "DHW-Valve", fontSize: 40 },
  { id: "BPV-Valve", fontSize: 40 },
  { id: "Info", ...BOX, fontSize: 40, alignLeft: true, info: true },
];

export const DEFAULT_FONT_SIZE = 56;
export const LABEL_FONT_SIZE = 35;
export const DEFAULT_OFFSET = 6;

const ONE = { digits: 1 } as const;
const WHOLE = { digits: 0 } as const;
const STATE_DEPENDENT = { digits: 1, dashUnknown: true } as const;

/** Values shown as text, by value ID. */
export const VALUES: Readonly<Record<string, ValueSpec>> = {
  temperature_outside: ONE,
  ta2: ONE,
  expansion_valve: WHOLE,
  liquid_temperature: ONE,
  subcooling: { ...STATE_DEPENDENT, prefix: true },
  circulation_pump: WHOLE,
  flow_rate: WHOLE,
  tr: ONE,
  evaporator_temperature: ONE,
  hot_gas_temperature: ONE,
  discharge_superheat: { ...STATE_DEPENDENT, prefix: true },
  saturation_temperature: STATE_DEPENDENT,
  hot_gas_condenser: ONE,
  refrigerant_pressure: STATE_DEPENDENT,
  temperature_spread: ONE,
  tv: ONE,
  target_supply_temperature: ONE,
  water_pressure: ONE,
  tvbh: ONE,
  tv_uart: ONE,
  tr_uart: ONE,
  tvbh_uart: ONE,
  fan_speed: WHOLE,
  compressor_speed: WHOLE,
  hot_water_temperature: ONE,
  hot_water_setpoint: ONE,
  backup_heater_power: WHOLE,
  dhw_mixer_position: WHOLE,
  bypass_valve: WHOLE,
  error_code: ONE,
  operating_mode: ONE,
  mode_of_operating: ONE,
  thermal_power: ONE,
  electric_power: ONE,
  cop: ONE,
  room_temperature: ONE,
  room_setpoint: ONE,
};

/** State of the error code without an error. */
export const NO_ERROR = "no_error";
