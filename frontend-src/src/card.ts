import { LitElement, css, html } from "lit";
import { property, state } from "lit/decorators.js";

import { validateAppearance } from "./appearance";
import type { CardConfig, HomeAssistant } from "./types";

export const CARD_TYPE = "daikin-heat-pump-card";
export const EDITOR_TYPE = "daikin-heat-pump-card-editor";

/** Card `custom:daikin-heat-pump-card` for own dashboards. */
export class DaikinHeatPumpCard extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;
  @state() private config?: CardConfig;

  setConfig(config: CardConfig): void {
    validateAppearance(config as unknown as Record<string, unknown>);
    this.config = config;
  }

  static getConfigElement(): HTMLElement {
    return document.createElement(EDITOR_TYPE);
  }

  static getStubConfig(): Record<string, unknown> {
    return {};
  }

  getCardSize(): number {
    return 12;
  }

  getGridOptions(): Record<string, unknown> {
    return { columns: "full", min_columns: 6, rows: "auto" };
  }

  protected override render() {
    return html`<ha-card>
      <daikin-heat-pump-view
        .hass=${this.hass}
        .appearance=${this.config ?? {}}
      ></daikin-heat-pump-view>
    </ha-card>`;
  }

  static override styles = css`
    ha-card {
      overflow: hidden;
    }
  `;
}
