import { describe, expect, it } from "vitest";

import {
  cleanAppearance,
  composeColor,
  layoutFile,
  parseColor,
  validateAppearance,
} from "../src/appearance";
import { formatValue, separatorIndex } from "../src/format";
import { TRANSLATIONS, bundleLanguage, localize } from "../src/localize";
import { apply, invert, multiply, parseTransform } from "../src/matrix";
import { entity, mockHass } from "./helpers";

const keys = (texts: object): string[] =>
  Object.entries(texts).flatMap(([section, entries]) =>
    Object.keys(entries as object).map((key) => `${section}.${key}`),
  );

describe("translations", () => {
  it("have the same keys in every language", () => {
    const english = keys(TRANSLATIONS.en!).sort();
    for (const language of ["de", "fr", "it"]) {
      expect(keys(TRANSLATIONS[language]!).sort()).toEqual(english);
    }
  });

  it("follow the language of the user with English as fallback", () => {
    expect(bundleLanguage("de-CH")).toBe("de");
    expect(bundleLanguage("FR")).toBe("fr");
    expect(bundleLanguage("nl")).toBe("en");
    expect(bundleLanguage(undefined)).toBe("en");
    expect(localize("de", "label.flow")).toBe("Vorlauf");
    expect(localize("nl", "label.flow")).toBe("Flow");
    expect(localize("de", "label.missing")).toBe("label.missing");
  });
});

describe("appearance", () => {
  it("picks the layout file", () => {
    expect(layoutFile(undefined, false)).toBe("daikin_glass_light.svg");
    expect(layoutFile("auto", true)).toBe("daikin_glass_dark.svg");
    expect(layoutFile("petrol", true)).toBe("daikin_glass_petrol.svg");
  });

  it("parses colours", () => {
    expect(parseColor("#fff")).toEqual([255, 255, 255, 1]);
    expect(parseColor("#10203080")).toEqual([16, 32, 48, 128 / 255]);
    expect(parseColor("rgba(1, 2, 3, 0.5)")).toEqual([1, 2, 3, 0.5]);
    expect(parseColor("red")).toBeUndefined();
    expect(parseColor(undefined)).toBeUndefined();
  });

  it("composes colours with opacity", () => {
    expect(composeColor(undefined, undefined, "#fff")).toBeUndefined();
    expect(composeColor([1, 2, 3], undefined, "#fff")).toBe("rgb(1,2,3)");
    expect(composeColor([1, 2, 3], 50, undefined)).toBe("rgba(1,2,3,0.5)");
    expect(composeColor(undefined, 20, "#ffffff")).toBe(
      "rgba(255,255,255,0.2)",
    );
    expect(composeColor(undefined, 150, "#000")).toBe("rgb(0,0,0)");
    expect(composeColor(undefined, 50, undefined)).toBeUndefined();
  });

  it("validates the configuration", () => {
    const config = {
      type: "custom:daikin-heat-pump-card",
      layout: "dark",
      background: { show: false, opacity: 40 },
      box: { fill: [1, 2, 3] },
    };
    expect(validateAppearance(config)).toBe(config);
    expect(() => validateAppearance({ layout: "neon" })).toThrow("layout");
    expect(() => validateAppearance({ entities: {} })).toThrow(
      "Unknown option: entities",
    );
    expect(() => validateAppearance({ box: "x" })).toThrow(
      "Invalid option: box",
    );
    expect(() => validateAppearance({ box: { size: 1 } })).toThrow("box.size");
    expect(() =>
      validateAppearance({ text: { value_color: [0, 0, 300] } }),
    ).toThrow("text.value_color");
    expect(() => validateAppearance({ background: { opacity: -1 } })).toThrow();
  });

  it("keeps only the changes to the layout", () => {
    expect(
      cleanAppearance({
        layout: "auto",
        background: { show: true, color: undefined },
        box: { fill: [1, 2, 3], border: undefined },
        text: {},
      }),
    ).toEqual({ box: { fill: [1, 2, 3] } });
    expect(
      cleanAppearance({ layout: "dark", background: { show: false } }),
    ).toEqual({
      layout: "dark",
      background: { show: false },
    });
  });
});

describe("format", () => {
  const hass = mockHass([], {}, { language: "de" });

  it("shows numbers with fixed decimals and the unit", () => {
    const tv = entity("sensor.tv", "31.456", { unit_of_measurement: "°C" });
    expect(formatValue(hass, tv, { digits: 1 })).toEqual({
      text: "31,5 °C",
      state: "normal",
    });
    expect(
      formatValue(hass, entity("number.x", "7", {}), { digits: 0 }).text,
    ).toBe("7");
  });

  it("shows other states as Home Assistant translates them", () => {
    expect(
      formatValue(hass, entity("sensor.mode", "heating"), { digits: 1 }).text,
    ).toBe("«heating»");
    expect(
      formatValue(
        { ...hass, formatEntityState: undefined },
        entity("select.m", "summer"),
        {
          digits: 1,
        },
      ).text,
    ).toBe("summer");
  });

  it("marks unknown values", () => {
    const unknown = entity("sensor.sc", "unknown");
    expect(
      formatValue(hass, unknown, { digits: 1, dashUnknown: true }),
    ).toEqual({
      text: "---",
      state: "normal",
    });
    expect(
      formatValue(hass, entity("sensor.tv", "unavailable"), { digits: 1 }),
    ).toEqual({
      text: "n. v.",
      state: "unavailable",
    });
  });

  it("finds the decimal separator", () => {
    expect(separatorIndex("31,5 °C")).toBe(2);
    expect(separatorIndex("1.000")).toBe(1);
    expect(separatorIndex("12 °C")).toBe(-1);
  });
});

describe("matrix", () => {
  it("parses transforms", () => {
    expect(parseTransform("translate(10 20) scale(2)")).toEqual([
      2, 0, 0, 2, 10, 20,
    ]);
    expect(parseTransform("matrix(1,0,0,1,5,6)")).toEqual([1, 0, 0, 1, 5, 6]);
    expect(parseTransform("scale(2, 3)")).toEqual([2, 0, 0, 3, 0, 0]);
    expect(parseTransform(null)).toEqual([1, 0, 0, 1, 0, 0]);
    const [x, y] = apply(parseTransform("rotate(90 10 10)"), 20, 10);
    expect(x).toBeCloseTo(10);
    expect(y).toBeCloseTo(20);
  });

  it("inverts", () => {
    const m = parseTransform("translate(3 4) scale(0.5)");
    const [x, y] = apply(multiply(invert(m), m), 7, 9);
    expect(x).toBeCloseTo(7);
    expect(y).toBeCloseTo(9);
  });
});
