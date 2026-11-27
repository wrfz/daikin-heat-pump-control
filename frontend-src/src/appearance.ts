import type { Appearance, Rgb } from "./types";

export const LAYOUTS = ["auto", "light", "dark", "petrol"] as const;
export type Layout = (typeof LAYOUTS)[number];

/** File of the layout to show; `auto` follows the dark mode of the frontend. */
export function layoutFile(
  layout: Layout | undefined,
  darkMode: boolean,
): string {
  const resolved =
    layout === undefined || layout === "auto"
      ? darkMode
        ? "dark"
        : "light"
      : layout;
  return `daikin_glass_${resolved}.svg`;
}

const clampPercent = (value: number): number =>
  Math.min(100, Math.max(0, Number(value)));

/** Parse `#rgb`, `#rrggbb`, `#rrggbbaa` or `rgb()/rgba()` into r, g, b, alpha. */
export function parseColor(
  value: string | undefined | null,
): [number, number, number, number] | undefined {
  if (!value) return undefined;
  const hex = value.trim().match(/^#([0-9a-f]{3,8})$/i);
  if (hex?.[1]) {
    let digits = hex[1];
    if (digits.length === 3 || digits.length === 4) {
      digits = [...digits].map((d) => d + d).join("");
    }
    const n = parseInt(digits.slice(0, 6), 16);
    const alpha =
      digits.length === 8 ? parseInt(digits.slice(6, 8), 16) / 255 : 1;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, alpha];
  }
  const fn = value.match(/rgba?\(([^)]+)\)/);
  if (fn?.[1]) {
    const [r = 0, g = 0, b = 0, a = 1] = fn[1].split(",").map(parseFloat);
    return [r, g, b, a];
  }
  return undefined;
}

/**
 * Colour from the appearance with its opacity (0–100). Only an opacity applies
 * to the colour of the layout (`base`).
 */
export function composeColor(
  color: Rgb | undefined,
  opacity: number | undefined,
  base: string | undefined,
): string | undefined {
  if (color === undefined && opacity === undefined) return undefined;
  const fallback = parseColor(base);
  const rgb = color ?? fallback?.slice(0, 3);
  if (!rgb) return undefined;
  const alpha =
    opacity !== undefined
      ? clampPercent(opacity) / 100
      : color
        ? 1
        : (fallback?.[3] ?? 1);
  const [r, g, b] = rgb;
  return alpha >= 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
}

const isRgb = (value: unknown): value is Rgb =>
  Array.isArray(value) &&
  value.length === 3 &&
  value.every((v) => Number.isInteger(v) && v >= 0 && v <= 255);

const isPercent = (value: unknown): boolean =>
  typeof value === "number" && value >= 0 && value <= 100;

const SECTIONS: Record<string, Record<string, (value: unknown) => boolean>> = {
  background: {
    show: (v) => typeof v === "boolean",
    color: isRgb,
    opacity: isPercent,
  },
  box: {
    fill: isRgb,
    fill_opacity: isPercent,
    border: isRgb,
    border_opacity: isPercent,
  },
  text: { value_color: isRgb, label_color: isRgb },
};

/** Check an appearance; throws with the first wrong field. */
export function validateAppearance(
  config: Record<string, unknown>,
): Appearance {
  for (const [key, value] of Object.entries(config)) {
    if (key === "type" || key === "grid_options" || key === "view_layout") {
      continue;
    }
    if (key === "layout") {
      if (!LAYOUTS.includes(value as Layout)) {
        throw new Error(`Invalid layout: ${String(value)}`);
      }
      continue;
    }
    if (key === "animations") {
      if (typeof value !== "boolean") {
        throw new Error(`Invalid option: ${key}`);
      }
      continue;
    }
    const fields = SECTIONS[key];
    if (!fields) throw new Error(`Unknown option: ${key}`);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error(`Invalid option: ${key}`);
    }
    for (const [field, fieldValue] of Object.entries(value)) {
      const check = fields[field];
      if (!check) throw new Error(`Unknown option: ${key}.${field}`);
      if (!check(fieldValue))
        throw new Error(`Invalid option: ${key}.${field}`);
    }
  }
  return config as Appearance;
}

/**
 * Keep only what differs from the layout: no empty values, no empty sections,
 * no default layout, no running animations and no shown background.
 */
export function cleanAppearance<T extends Appearance>(config: T): T {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (value === undefined || value === null || value === "") continue;
    if (key === "layout" && value === "auto") continue;
    if (key === "animations" && value === true) continue;
    if (key in SECTIONS && typeof value === "object") {
      const section = Object.fromEntries(
        Object.entries(value as Record<string, unknown>).filter(
          ([field, fieldValue]) =>
            fieldValue !== undefined &&
            fieldValue !== null &&
            fieldValue !== "" &&
            !(key === "background" && field === "show" && fieldValue === true),
        ),
      );
      if (Object.keys(section).length > 0) result[key] = section;
      continue;
    }
    result[key] = value;
  }
  return result as T;
}
