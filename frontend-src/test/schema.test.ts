import { describe, expect, it } from "vitest";

import { localize } from "../src/localize";
import { Schema } from "../src/schema";
import { GROUPS, VALUES } from "../src/values";
import type { HassEntity } from "../src/types";
import {
  LAYOUT_NAMES,
  dashboard,
  entity,
  layoutSource,
  mockHass,
} from "./helpers";

const parse = (name: string): Document =>
  new DOMParser().parseFromString(layoutSource(name), "image/svg+xml");

const byId = (schema: Schema, id: string): SVGElement =>
  schema.svg.querySelector(`[id="${id}"]`) as SVGElement;

const hidden = (element: Element | null): boolean =>
  (element as SVGElement | null)?.style.display === "none";

describe.each(LAYOUT_NAMES)("layout %s", (name) => {
  const doc = parse(name);

  it("marks every shown value and has every group", () => {
    const values = [...doc.querySelectorAll("[data-value]")].map((e) =>
      e.getAttribute("data-value"),
    );
    expect(new Set(values)).toEqual(new Set(Object.keys(VALUES)));
    expect(values.length).toBe(new Set(values).size);
    for (const group of GROUPS) {
      expect(doc.querySelector(`[id="${group.id}"]`), group.id).not.toBeNull();
    }
  });

  it("has a text for every label", () => {
    for (const label of doc.querySelectorAll("[data-label]")) {
      const key = `label.${label.getAttribute("data-label")}`;
      expect(localize("en", key), key).not.toBe(key);
    }
  });
});

describe("info and prefix texts", () => {
  it("exist for the info box and the prefixed values", () => {
    const info = GROUPS.find((g) => g.info)!;
    const rows = [
      ...parse("light").querySelectorAll(`[id="${info.id}"] [data-value]`),
    ];
    for (const row of rows) {
      const key = `info.${row.getAttribute("data-value")}`;
      expect(localize("de", key), key).not.toBe(key);
    }
    for (const [id, spec] of Object.entries(VALUES)) {
      if (spec.prefix)
        expect(localize("en", `prefix.${id}`)).not.toBe(`prefix.${id}`);
    }
  });
});

const STATES: HassEntity[] = [
  entity("sensor.tv", "31.25", { unit_of_measurement: "°C" }),
  entity("sensor.tr", "27", { unit_of_measurement: "°C" }),
  entity("sensor.tr_uart", "27.4", { unit_of_measurement: "°C" }),
  entity("sensor.error", "no_error"),
  entity("select.mode", "heating"),
  entity("sensor.power", "4.2", { unit_of_measurement: "kW" }),
  entity("sensor.sub", "unknown", { unit_of_measurement: "K" }),
  entity("sensor.liquid", "30", { unit_of_measurement: "°C" }),
  entity("binary_sensor.compressor", "on"),
  entity("binary_sensor.pump", "off"),
  entity("sensor.valve", "heating"),
  entity("sensor.fan", "600", { unit_of_measurement: "RPM" }),
  entity("sensor.mixer", "25", { unit_of_measurement: "%" }),
];

const ENTITIES = {
  tv: "sensor.tv",
  tr: "sensor.tr",
  tr_uart: "sensor.tr_uart",
  error_code: "sensor.error",
  operating_mode: "select.mode",
  thermal_power: "sensor.power",
  subcooling: "sensor.sub",
  liquid_temperature: "sensor.liquid",
  compressor_running: "binary_sensor.compressor",
  pump_running: "binary_sensor.pump",
  four_way_valve: "sensor.valve",
  fan_speed: "sensor.fan",
  dhw_mixer_position: "sensor.mixer",
};

function render(
  states: HassEntity[] = STATES,
  info = ["thermal_power", "error_code", "operating_mode"],
  appearance = {},
) {
  const schema = new Schema(layoutSource("light"), appearance, "de");
  const hass = mockHass(states, {}, { language: "de" });
  schema.update(hass, dashboard(ENTITIES, info));
  return schema;
}

describe("schema", () => {
  it("shows values with label, decimals and unit", () => {
    const schema = render();
    const text = byId(schema, "flow_can_value_text");
    expect(text.textContent).toBe("31,3 °C");
    expect(text.getAttribute("data-entity")).toBe("sensor.tv");
    expect(text.getAttribute("data-state")).toBe("normal");
    // Aligned at the decimal separator of the box.
    expect(text.children).toHaveLength(2);
    expect(text.children[1]!.textContent).toBe(",3 °C");
    const labels = [...byId(schema, "Vorlauf").querySelectorAll("text")].map(
      (t) => t.textContent,
    );
    expect(labels).toContain("Vorlauf");
  });

  it("shows the UART reading below the CAN reading", () => {
    const schema = render();
    expect(byId(schema, "return_flow_can_value_text").textContent).toBe(
      "27,0 °C",
    );
    const uart = byId(schema, "return_flow_uart_value_text");
    expect(uart.textContent).toBe("27,4 °C");
    expect(uart.getAttribute("data-entity")).toBe("sensor.tr_uart");
    expect(hidden(byId(schema, "return_flow_uart_value"))).toBe(false);
  });

  it("hides rows and boxes without a value", () => {
    const schema = render();
    expect(hidden(byId(schema, "flow_uart_value"))).toBe(true);
    expect(hidden(byId(schema, "TA2"))).toBe(true);
    for (const leader of schema.svg.querySelectorAll('path[data-box="EEV"]')) {
      expect(hidden(leader)).toBe(true);
    }
    expect(hidden(byId(schema, "Vorlauf"))).toBe(false);
  });

  it("shrinks a box to its rows and moves its leaders", () => {
    const schema = render();
    const frame = byId(schema, "Vorlauf_rect");
    expect(Number(frame.getAttribute("height"))).toBeCloseTo(160.42);
    const leader = schema.svg.querySelector('path[data-box="Vorlauf"]')!;
    const before = parse("light").querySelector('path[data-box="Vorlauf"]')!;
    const y = (path: Element) =>
      Number(path.getAttribute("d")!.split(/[ L]/)[1]);
    expect(y(leader)).toBeLessThan(y(before));
    expect(leader.getAttribute("d")!.endsWith("L897 619")).toBe(true);
  });

  it("shows unknown state dependent values as dashes with their prefix", () => {
    const schema = render();
    const text = byId(schema, "subcooling_value_text");
    expect(text.textContent).toBe("UK---");
    expect(text.getAttribute("data-state")).toBe("normal");
  });

  it("orders the info box and marks errors", () => {
    let schema = render();
    const rowY = (id: string) => Number(byId(schema, id).getAttribute("y"));
    expect(rowY("therm_leistung_value")).toBeLessThan(rowY("fehlercode_value"));
    expect(rowY("fehlercode_value")).toBeLessThan(rowY("betriebsmodus_value"));
    expect(byId(schema, "fehlercode_value_text").textContent).toBe(
      "Fehlercode: «no_error»",
    );
    expect(
      byId(schema, "fehlercode_value_text").getAttribute("data-state"),
    ).toBe("normal");
    expect(hidden(byId(schema, "betriebsart_value"))).toBe(true);

    const failing = STATES.map((s) =>
      s.entity_id === "sensor.error" ? entity("sensor.error", "e9001") : s,
    );
    schema = render(failing);
    expect(
      byId(schema, "fehlercode_value_text").getAttribute("data-state"),
    ).toBe("error");
    schema = render(STATES, []);
    expect(hidden(byId(schema, "Info"))).toBe(true);
  });

  it("drives animations and colours", () => {
    const schema = render();
    expect(byId(schema, "compressor-symbol").getAttribute("data-state")).toBe(
      "on",
    );
    expect(byId(schema, "pump-symbol").getAttribute("data-state")).toBe("off");
    expect(byId(schema, "fan").getAttribute("data-state")).toBe("on");
    expect(byId(schema, "fw-heat").getAttribute("data-state")).toBe("on");
    expect(byId(schema, "fw-cool").getAttribute("data-state")).toBe("off");
    expect(byId(schema, "eev-symbol").getAttribute("data-state")).toBe(
      "unknown",
    );
    expect(schema.svg.style.getPropertyValue("--k-vorlauf")).toBe("0.450");
    expect(schema.svg.style.getPropertyValue("--k-fan")).toBe("0.600");
    expect(schema.svg.style.getPropertyValue("--k-hotgas")).toBe("");
    expect(byId(schema, "dhw-flap").getAttribute("transform")).toMatch(
      /^rotate\(24 /,
    );
    expect(byId(schema, "dhw-open-arrows").style.opacity).toBe("0.25");
    expect(byId(schema, "compressor-symbol").getAttribute("data-entity")).toBe(
      "binary_sensor.compressor",
    );
    expect(byId(schema, "eev-symbol").hasAttribute("data-entity")).toBe(false);
  });

  it("applies the appearance", () => {
    const schema = render(STATES, [], {
      box: { fill: [1, 2, 3], border_opacity: 50 },
      text: { value_color: [9, 9, 9] },
      background: { color: [4, 5, 6], opacity: 30 },
    });
    expect(byId(schema, "Vorlauf_rect").getAttribute("fill")).toBe(
      "rgb(1,2,3)",
    );
    expect(byId(schema, "Vorlauf_rect").getAttribute("stroke")).toBe(
      "rgba(201,210,227,0.5)",
    );
    expect(byId(schema, "flow_can_value_text").getAttribute("fill")).toBe(
      "rgb(9,9,9)",
    );
    expect(schema.svg.style.getPropertyValue("--bg-color")).toBe("rgb(4,5,6)");
    expect(schema.svg.style.getPropertyValue("--bg-opacity")).toBe("0.3");
    const off = render(STATES, [], { background: { show: false } });
    expect(off.svg.getAttribute("data-bg")).toBe("off");
    expect(schema.svg.getAttribute("data-animations")).toBe("on");
    const still = render(STATES, [], { animations: false });
    expect(still.svg.getAttribute("data-animations")).toBe("off");
  });

  it("marks unavailable values", () => {
    const states = STATES.map((s) =>
      s.entity_id === "sensor.tv" ? entity("sensor.tv", "unavailable") : s,
    );
    const text = byId(render(states), "flow_can_value_text");
    expect(text.textContent).toBe("n. v.");
    expect(text.getAttribute("data-state")).toBe("unavailable");
    expect(text.hasAttribute("fill")).toBe(false);
  });

  it("rejects other documents", () => {
    expect(() => new Schema("<html></html>", {}, "en")).toThrow();
  });
});
