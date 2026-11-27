import { LitElement, css, html } from "lit";
import { property, state } from "lit/decorators.js";

import { LAYOUTS, cleanAppearance } from "./appearance";
import { bundleLanguage, localize } from "./localize";
import type { Appearance, HomeAssistant } from "./types";

interface SchemaItem {
  name: string;
  type?: string;
  title?: string;
  selector?: Record<string, unknown>;
  schema?: SchemaItem[];
}

const percent = {
  number: {
    min: 0,
    max: 100,
    step: 1,
    mode: "slider",
    unit_of_measurement: "%",
  },
};
const color = { color_rgb: {} };

/** Fields of the appearance for ha-form. */
export function editorSchema(language: string): SchemaItem[] {
  const t = (key: string): string => localize(language, `editor.${key}`);
  return [
    {
      name: "layout",
      selector: {
        select: {
          mode: "dropdown",
          options: LAYOUTS.map((layout) => ({
            value: layout,
            label: t(`layout_${layout}`),
          })),
        },
      },
    },
    { name: "animations", selector: { boolean: {} } },
    {
      name: "background",
      type: "expandable",
      title: t("background"),
      schema: [
        { name: "show", selector: { boolean: {} } },
        { name: "color", selector: color },
        { name: "opacity", selector: percent },
      ],
    },
    {
      name: "box",
      type: "expandable",
      title: t("box"),
      schema: [
        { name: "fill", selector: color },
        { name: "fill_opacity", selector: percent },
        { name: "border", selector: color },
        { name: "border_opacity", selector: percent },
      ],
    },
    {
      name: "text",
      type: "expandable",
      title: t("text"),
      schema: [
        { name: "value_color", selector: color },
        { name: "label_color", selector: color },
      ],
    },
  ];
}

/** Values shown in the form: the defaults filled in. */
export function formData(appearance: Appearance): Record<string, unknown> {
  return {
    ...appearance,
    layout: appearance.layout ?? "auto",
    animations: appearance.animations !== false,
    background: { show: true, ...appearance.background },
  };
}

/**
 * Make sure ha-form is defined. The panel has no card editor around it, so
 * the form is loaded through the editor of a built-in card.
 */
export async function ensureHaForm(): Promise<void> {
  if (customElements.get("ha-form")) return;
  const helpers = await (
    window as unknown as {
      loadCardHelpers?: () => Promise<{
        createCardElement(config: object): unknown;
      }>;
    }
  ).loadCardHelpers?.();
  const card = helpers?.createCardElement({
    type: "entities",
    entities: [],
  }) as
    { constructor: { getConfigElement?: () => Promise<unknown> } } | undefined;
  await card?.constructor.getConfigElement?.();
}

/** Editor of the appearance (card editor and panel dialog). */
export class DaikinHeatPumpCardEditor extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;
  @property({ attribute: false }) config: Record<string, unknown> = {};
  @state() private formReady = false;

  setConfig(config: Record<string, unknown>): void {
    this.config = config;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void ensureHaForm().then(() => (this.formReady = true));
  }

  private get language(): string {
    return bundleLanguage(this.hass?.locale?.language ?? this.hass?.language);
  }

  protected override render() {
    const language = this.language;
    return html`
      ${
        this.formReady
          ? html`<ha-form
              .hass=${this.hass}
              .data=${formData(this.config as Appearance)}
              .schema=${editorSchema(language)}
              .computeLabel=${(item: SchemaItem) => localize(language, `editor.${item.name}`)}
              @value-changed=${this.valueChanged}
            ></ha-form>`
          : ""
      }
      <div class="actions">
        <button type="button" @click=${this.reset}>
          ${localize(language, "editor.reset")}
        </button>
      </div>
      <p class="hint">${localize(language, "editor.hint")}</p>
    `;
  }

  private valueChanged(
    event: CustomEvent<{ value: Record<string, unknown> }>,
  ): void {
    event.stopPropagation();
    this.changed({ ...this.config, ...event.detail.value });
  }

  private reset(): void {
    const type = this.config.type;
    this.changed(type === undefined ? {} : { type });
  }

  private changed(config: Record<string, unknown>): void {
    this.config = cleanAppearance(config);
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this.config },
        bubbles: true,
        composed: true,
      }),
    );
  }

  static override styles = css`
    .actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 12px;
    }
    button {
      font: inherit;
      color: var(--primary-color);
      background: none;
      border: 1px solid var(--divider-color);
      border-radius: 18px;
      padding: 6px 14px;
      cursor: pointer;
    }
    .hint {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
  `;
}
