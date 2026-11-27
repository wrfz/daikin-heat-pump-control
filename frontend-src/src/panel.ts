import { LitElement, css, html, type PropertyValues } from "lit";
import { property, query, state } from "lit/decorators.js";

import { bundleLanguage, localize } from "./localize";
import type { Appearance, HomeAssistant } from "./types";
import { DOMAIN } from "./view";

// Material Design Icons "cog".
const MDI_COG =
  "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z";

/** Sidebar panel: the schematic over the whole page, appearance for all users. */
export class DaikinHeatPumpPanel extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;
  @property({ type: Boolean }) narrow = false;

  @state() private appearance: Appearance = {};
  @state() private draft?: Appearance;
  @state() private saveError = false;

  @query("dialog") private dialog?: HTMLDialogElement;

  private loaded = false;

  private get language(): string {
    return bundleLanguage(this.hass?.locale?.language ?? this.hass?.language);
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.hass && !this.loaded) {
      this.loaded = true;
      void this.loadAppearance();
    }
  }

  private async loadAppearance(): Promise<void> {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS<{ config: Appearance }>({
        type: `${DOMAIN}/panel_config`,
      });
      this.appearance = result.config;
    } catch {
      // Without a loaded entry the view shows the message.
    }
  }

  protected override render() {
    const t = (key: string): string => localize(this.language, key);
    return html`
      <div class="toolbar">
        <ha-menu-button
          .hass=${this.hass}
          .narrow=${this.narrow}
        ></ha-menu-button>
        <div class="title">${t("panel.title")}</div>
        ${
          this.hass?.user?.is_admin
            ? html`<ha-icon-button
                .path=${MDI_COG}
                .label=${t("panel.settings")}
                @click=${this.openSettings}
              ></ha-icon-button>`
            : ""
        }
      </div>
      <div class="content">
        <daikin-heat-pump-view
          fit
          .hass=${this.hass}
          .appearance=${this.draft ?? this.appearance}
        ></daikin-heat-pump-view>
      </div>
      <dialog @close=${this.closed}>
        <h2>${t("panel.settings")}</h2>
        <p class="note">${t("panel.all_users")}</p>
        ${
          this.draft !== undefined
            ? html`<daikin-heat-pump-card-editor
                .hass=${this.hass}
                .config=${this.draft}
                @config-changed=${this.draftChanged}
              ></daikin-heat-pump-card-editor>`
            : ""
        }
        ${this.saveError ? html`<p class="error">${t("panel.save_error")}</p>` : ""}
        <div class="buttons">
          <button type="button" @click=${this.cancel}>
            ${t("panel.cancel")}
          </button>
          <button type="button" class="primary" @click=${this.save}>
            ${t("panel.save")}
          </button>
        </div>
      </dialog>
    `;
  }

  private async openSettings(): Promise<void> {
    this.draft = { ...this.appearance };
    this.saveError = false;
    await this.updateComplete;
    this.dialog?.showModal();
  }

  private draftChanged(event: CustomEvent<{ config: Appearance }>): void {
    this.draft = event.detail.config;
  }

  private cancel(): void {
    this.dialog?.close();
  }

  private closed(): void {
    this.draft = undefined;
  }

  private async save(): Promise<void> {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS<{ config: Appearance }>({
        type: `${DOMAIN}/panel_config/set`,
        config: this.draft ?? {},
      });
      this.appearance = result.config;
      this.dialog?.close();
    } catch {
      this.saveError = true;
    }
  }

  static override styles = css`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      --daikin-view-height: calc(100vh - var(--header-height, 56px) - 32px);
    }
    .toolbar {
      display: flex;
      align-items: center;
      height: var(--header-height, 56px);
      padding: 0 12px;
      box-sizing: border-box;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, var(--text-primary-color));
      border-bottom: var(--app-header-border-bottom, none);
    }
    .title {
      flex: 1;
      margin-left: 12px;
      font-size: 20px;
    }
    .content {
      padding: 16px;
    }
    dialog {
      width: min(560px, calc(100vw - 32px));
      max-height: calc(100vh - 64px);
      border: none;
      border-radius: var(--ha-dialog-border-radius, 24px);
      background: var(--card-background-color, var(--primary-background-color));
      color: var(--primary-text-color);
      padding: 24px;
    }
    dialog::backdrop {
      background: rgba(0, 0, 0, 0.4);
    }
    h2 {
      margin: 0 0 8px;
      font-size: 22px;
      font-weight: 400;
    }
    .note {
      margin: 0 0 16px;
      color: var(--secondary-text-color);
    }
    .error {
      color: var(--error-color);
    }
    .buttons {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 16px;
    }
    button {
      font: inherit;
      padding: 8px 16px;
      border-radius: 18px;
      border: 1px solid var(--divider-color);
      background: none;
      color: var(--primary-color);
      cursor: pointer;
    }
    button.primary {
      background: var(--primary-color);
      color: var(--text-primary-color);
      border-color: var(--primary-color);
    }
  `;
}
