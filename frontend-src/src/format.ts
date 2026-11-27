import { localize } from "./localize";
import type { HassEntity, HomeAssistant } from "./types";
import type { ValueSpec } from "./values";

export type TextState = "normal" | "unavailable" | "error";

export interface FormattedValue {
  text: string;
  state: TextState;
}

const NUMERIC_DOMAINS = new Set(["sensor", "number", "input_number"]);

const isUnavailable = (state: string): boolean =>
  state === "unknown" || state === "unavailable";

/** Return the number of a numeric state, otherwise undefined. */
export function numericState(
  entity: HassEntity | undefined,
): number | undefined {
  if (!entity || isUnavailable(entity.state) || entity.state.trim() === "") {
    return undefined;
  }
  const value = Number(entity.state);
  return Number.isFinite(value) ? value : undefined;
}

/**
 * Text of a value. Numbers get the fixed decimals of the schematic and the unit
 * of the entity; other states are shown as Home Assistant translates them.
 */
export function formatValue(
  hass: HomeAssistant,
  entity: HassEntity,
  spec: ValueSpec,
): FormattedValue {
  const language = hass.locale?.language ?? hass.language;
  if (isUnavailable(entity.state)) {
    return spec.dashUnknown
      ? { text: "---", state: "normal" }
      : { text: localize(language, "state.unavailable"), state: "unavailable" };
  }
  const domain = entity.entity_id.split(".")[0] ?? "";
  const number = numericState(entity);
  if (number !== undefined && NUMERIC_DOMAINS.has(domain)) {
    const text = new Intl.NumberFormat(language, {
      minimumFractionDigits: spec.digits,
      maximumFractionDigits: spec.digits,
    }).format(number);
    const unit = entity.attributes.unit_of_measurement;
    return {
      text: typeof unit === "string" && unit ? `${text} ${unit}` : text,
      state: "normal",
    };
  }
  return {
    text: hass.formatEntityState?.(entity) ?? entity.state,
    state: "normal",
  };
}

/**
 * Index of the decimal separator in a formatted number, or -1. Used to align
 * the rows of a box at the separator.
 */
export function separatorIndex(text: string): number {
  return text.search(/[,.]\d/);
}
