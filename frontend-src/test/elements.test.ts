import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import "../src/main";
import { DaikinHeatPumpCard } from "../src/card";
import { editorSchema, formData } from "../src/editor";
import { assetUrl } from "../src/view";
import type { DaikinHeatPumpCardEditor } from "../src/editor";
import type { DaikinHeatPumpPanel } from "../src/panel";
import type { DaikinHeatPumpView } from "../src/view";
import { dashboard, entity, layoutSource, mockHass, settle } from "./helpers";

const ENTITIES = dashboard({ tv: "sensor.tv" });
const STATES = [entity("sensor.tv", "30", { unit_of_measurement: "°C" })];

const fetched: string[] = [];

beforeAll(() => {
  vi.stubGlobal("fetch", (url: string) => {
    fetched.push(url);
    const name = /daikin_glass_(\w+)\.svg/.exec(url)?.[1] ?? "";
    return Promise.resolve(
      name === "petrol"
        ? new Response("missing", { status: 404 })
        : new Response(layoutSource(name)),
    );
  });
});

afterEach(() => {
  document.body.replaceChildren();
});

async function view(
  hass = mockHass(STATES, { "daikin_heat_pump_control/entities": ENTITIES }),
  appearance = {},
): Promise<DaikinHeatPumpView> {
  const element = document.createElement("daikin-heat-pump-view");
  element.hass = hass;
  element.appearance = appearance;
  document.body.appendChild(element);
  await settle();
  await element.updateComplete;
  return element;
}

describe("view", () => {
  it("loads the layout next to the module with its version", () => {
    expect(
      assetUrl(
        "daikin_glass_light.svg",
        "http://ha/daikin/frontend/x.js?v=0.1.0",
      ),
    ).toBe("http://ha/daikin/frontend/daikin_glass_light.svg?v=0.1.0");
  });

  it("shows the schematic with the values of the integration", async () => {
    const element = await view();
    const text = element.shadowRoot!.querySelector(
      '[id="flow_can_value_text"]',
    );
    expect(text?.textContent).toBe("30.0 °C");
    expect(fetched.some((url) => url.includes("daikin_glass_light.svg"))).toBe(
      true,
    );
  });

  it("follows the dark mode", async () => {
    await view(
      mockHass(
        STATES,
        { "daikin_heat_pump_control/entities": ENTITIES },
        { dark: true },
      ),
    );
    expect(fetched.some((url) => url.includes("daikin_glass_dark.svg"))).toBe(
      true,
    );
  });

  it("opens the details of a value", async () => {
    const element = await view();
    const opened: string[] = [];
    element.addEventListener("hass-more-info", (event) =>
      opened.push((event as CustomEvent<{ entityId: string }>).detail.entityId),
    );
    const text = element.shadowRoot!.querySelector(
      '[id="flow_can_value_text"]',
    )!;
    text.dispatchEvent(
      new MouseEvent("click", { bubbles: true, composed: true }),
    );
    element
      .shadowRoot!.querySelector(".schema")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(opened).toEqual(["sensor.tv"]);
  });

  it("asks again when the entity registry changes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const hass = mockHass(STATES, {
        "daikin_heat_pump_control/entities": ENTITIES,
      });
      const element = document.createElement("daikin-heat-pump-view");
      element.hass = hass;
      document.body.appendChild(element);
      await vi.runAllTimersAsync();
      expect(hass.calls).toHaveLength(1);
      hass.events[0]!({});
      hass.events[0]!({});
      await vi.runAllTimersAsync();
      expect(hass.calls).toHaveLength(2);
      element.remove();
    } finally {
      vi.useRealTimers();
    }
  });

  it("explains a missing integration", async () => {
    const element = await view(
      mockHass(STATES, {
        "daikin_heat_pump_control/entities": { code: "not_loaded" },
      }),
    );
    expect(element.shadowRoot!.textContent).toContain(
      "not set up or not loaded",
    );
  });

  it("reports a layout that cannot be loaded", async () => {
    const element = await view(undefined, { layout: "petrol" });
    expect(element.shadowRoot!.textContent).toContain("could not be loaded");
  });
});

describe("card", () => {
  it("checks its configuration", () => {
    const card = document.createElement("daikin-heat-pump-card");
    card.setConfig({ type: "custom:daikin-heat-pump-card", layout: "dark" });
    expect(() =>
      card.setConfig({
        type: "custom:daikin-heat-pump-card",
        layout: "neon",
      } as never),
    ).toThrow();
    expect(card.getCardSize()).toBe(12);
    expect(card.getGridOptions()).toMatchObject({ columns: "full" });
    expect(DaikinHeatPumpCard.getStubConfig()).toEqual({});
    expect(DaikinHeatPumpCard.getConfigElement().tagName.toLowerCase()).toBe(
      "daikin-heat-pump-card-editor",
    );
  });

  it("is offered in the card picker", () => {
    const cards = (window as unknown as { customCards: { type: string }[] })
      .customCards;
    expect(
      cards.filter((c) => c.type === "daikin-heat-pump-card"),
    ).toHaveLength(1);
  });

  it("shows the view", async () => {
    const card = document.createElement("daikin-heat-pump-card");
    card.setConfig({ type: "custom:daikin-heat-pump-card" });
    card.hass = mockHass(STATES, {
      "daikin_heat_pump_control/entities": ENTITIES,
    });
    document.body.appendChild(card);
    await card.updateComplete;
    const element = card.shadowRoot!.querySelector("daikin-heat-pump-view")!;
    expect(element.hass).toBe(card.hass);
  });
});

describe("editor", () => {
  it("describes the appearance", () => {
    const schema = editorSchema("de");
    expect(schema.map((item) => item.name)).toEqual([
      "layout",
      "animations",
      "background",
      "box",
      "text",
    ]);
    expect(formData({})).toEqual({
      layout: "auto",
      animations: true,
      background: { show: true },
    });
    expect(formData({ animations: false }).animations).toBe(false);
  });

  it("stores only changes and can reset", async () => {
    customElements.define("ha-form", class extends HTMLElement {});
    const editor = document.createElement(
      "daikin-heat-pump-card-editor",
    ) as DaikinHeatPumpCardEditor;
    editor.hass = mockHass([]);
    editor.setConfig({ type: "custom:daikin-heat-pump-card", layout: "dark" });
    const changes: unknown[] = [];
    editor.addEventListener("config-changed", (event) =>
      changes.push((event as CustomEvent<{ config: unknown }>).detail.config),
    );
    document.body.appendChild(editor);
    await settle();
    await editor.updateComplete;
    const form = editor.shadowRoot!.querySelector("ha-form")!;
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            layout: "auto",
            background: { show: true },
            box: { fill: [1, 2, 3] },
          },
        },
      }),
    );
    editor.shadowRoot!.querySelector("button")!.click();
    expect(changes).toEqual([
      { type: "custom:daikin-heat-pump-card", box: { fill: [1, 2, 3] } },
      { type: "custom:daikin-heat-pump-card" },
    ]);
  });
});

describe("panel", () => {
  async function panel(admin: boolean, setResult?: unknown) {
    const hass = mockHass(
      STATES,
      {
        "daikin_heat_pump_control/entities": ENTITIES,
        "daikin_heat_pump_control/panel_config": { config: { layout: "dark" } },
        "daikin_heat_pump_control/panel_config/set":
          setResult ??
          ((message: { config: unknown }) => ({ config: message.config })),
      },
      { admin },
    );
    const element = document.createElement(
      "daikin-heat-pump-panel",
    ) as DaikinHeatPumpPanel;
    element.hass = hass;
    document.body.appendChild(element);
    await settle();
    await element.updateComplete;
    return { element, hass };
  }

  it("shows the stored appearance and hides the settings from users", async () => {
    const { element } = await panel(false);
    const view = element.shadowRoot!.querySelector("daikin-heat-pump-view")!;
    expect(view.appearance).toEqual({ layout: "dark" });
    expect(element.shadowRoot!.querySelector("ha-icon-button")).toBeNull();
    expect(element.shadowRoot!.querySelector(".title")!.textContent).toBe(
      "Heat pump",
    );
  });

  it("lets admins change the appearance for everybody", async () => {
    const { element, hass } = await panel(true);
    const dialog = element.shadowRoot!.querySelector("dialog")!;
    dialog.showModal = () => dialog.setAttribute("open", "");
    dialog.close = () => {
      dialog.removeAttribute("open");
      dialog.dispatchEvent(new Event("close"));
    };
    element
      .shadowRoot!.querySelector("ha-icon-button")!
      .dispatchEvent(new Event("click"));
    await settle();
    await element.updateComplete;
    expect(dialog.hasAttribute("open")).toBe(true);
    const editor = element.shadowRoot!.querySelector(
      "daikin-heat-pump-card-editor",
    )!;
    editor.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: { layout: "light" } },
      }),
    );
    await element.updateComplete;
    const [, save] =
      element.shadowRoot!.querySelectorAll<HTMLButtonElement>(
        ".buttons button",
      );
    save!.click();
    await settle();
    await element.updateComplete;
    expect(hass.calls.at(-1)).toEqual({
      type: "daikin_heat_pump_control/panel_config/set",
      config: { layout: "light" },
    });
    expect(dialog.hasAttribute("open")).toBe(false);
    const view = element.shadowRoot!.querySelector("daikin-heat-pump-view")!;
    expect(view.appearance).toEqual({ layout: "light" });
  });

  it("keeps the dialog open when saving fails", async () => {
    const { element } = await panel(true, { code: "unauthorized" });
    const dialog = element.shadowRoot!.querySelector("dialog")!;
    dialog.showModal = () => dialog.setAttribute("open", "");
    element
      .shadowRoot!.querySelector("ha-icon-button")!
      .dispatchEvent(new Event("click"));
    await settle();
    const [cancel, save] =
      element.shadowRoot!.querySelectorAll<HTMLButtonElement>(
        ".buttons button",
      );
    save!.click();
    await settle();
    await element.updateComplete;
    expect(element.shadowRoot!.querySelector(".error")).not.toBeNull();
    dialog.close = () => dialog.dispatchEvent(new Event("close"));
    cancel!.click();
    await element.updateComplete;
    expect(
      element.shadowRoot!.querySelector("daikin-heat-pump-card-editor"),
    ).toBeNull();
  });
});
