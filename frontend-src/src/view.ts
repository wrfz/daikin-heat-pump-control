import { LitElement, css, html, type PropertyValues } from "lit";
import { property, state } from "lit/decorators.js";

import { layoutFile } from "./appearance";
import { bundleLanguage, localize } from "./localize";
import { Schema } from "./schema";
import type {
  Appearance,
  DashboardData,
  HomeAssistant,
  MasterStatus,
  UnsubscribeFunc,
} from "./types";

export const DOMAIN = "daikin_heat_pump_control";

const layouts = new Map<string, Promise<string>>();

/** URL of a file next to this module, with the version of the module. */
export function assetUrl(
  file: string,
  moduleUrl: string = import.meta.url,
): string {
  const url = new URL(file, moduleUrl);
  url.search = new URL(moduleUrl).search;
  return url.href;
}

/** Load a layout once per page. */
export function loadLayout(file: string): Promise<string> {
  let layout = layouts.get(file);
  if (!layout) {
    layout = fetch(assetUrl(file)).then((response) => {
      if (!response.ok) throw new Error(`${file}: ${response.status}`);
      return response.text();
    });
    layout.catch(() => layouts.delete(file));
    layouts.set(file, layout);
  }
  return layout;
}

const REFRESH_DELAY = 500;

/** The schematic shared by the card and the panel. */
export class DaikinHeatPumpView extends LitElement {
  @property({ attribute: false }) hass?: HomeAssistant;
  @property({ attribute: false }) appearance: Appearance = {};

  @state() private data?: DashboardData;
  @state() private error?: string;
  @state() private source?: { file: string; text: string };
  @state() private master?: MasterStatus;
  @state() private claimError = false;

  private schema?: Schema;
  private schemaKey?: string;
  private unsubscribe?: Promise<UnsubscribeFunc | undefined>;
  private unsubscribeMaster?: Promise<UnsubscribeFunc | undefined>;
  private refreshTimer?: ReturnType<typeof setTimeout>;
  private loading?: string;

  override connectedCallback(): void {
    super.connectedCallback();
    if (this.hass) this.subscribe();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this.refreshTimer);
    void this.unsubscribe?.then((unsubscribe) => unsubscribe?.());
    this.unsubscribe = undefined;
    void this.unsubscribeMaster?.then((unsubscribe) => unsubscribe?.());
    this.unsubscribeMaster = undefined;
  }

  private get language(): string {
    return bundleLanguage(this.hass?.locale?.language ?? this.hass?.language);
  }

  private get file(): string {
    return layoutFile(
      this.appearance.layout,
      this.hass?.themes?.darkMode ?? false,
    );
  }

  private subscribe(): void {
    if (this.unsubscribe || !this.hass) return;
    void this.fetchData();
    this.unsubscribe = this.hass.connection
      .subscribeEvents(() => {
        clearTimeout(this.refreshTimer);
        this.refreshTimer = setTimeout(
          () => void this.fetchData(),
          REFRESH_DELAY,
        );
      }, "entity_registry_updated")
      .catch(() => undefined);
    this.unsubscribeMaster = this.hass.connection
      .subscribeMessage<MasterStatus>(
        (status) => {
          this.master = status;
        },
        { type: `${DOMAIN}/master/subscribe` },
      )
      .catch(() => undefined);
  }

  /** Another instance controls the bridges; this one only shows the values. */
  private get listening(): boolean {
    return (
      this.master !== undefined &&
      !this.master.master &&
      this.master.clients > 1
    );
  }

  private async claim(): Promise<void> {
    if (!this.hass) return;
    try {
      await this.hass.callWS({ type: `${DOMAIN}/master/claim` });
      this.claimError = false;
    } catch {
      this.claimError = true;
    }
  }

  /** Ask the integration for the entities of the values. */
  async fetchData(): Promise<void> {
    if (!this.hass) return;
    try {
      this.data = await this.hass.callWS<DashboardData>({
        type: `${DOMAIN}/entities`,
      });
      this.error = undefined;
    } catch (err) {
      const code = (err as { code?: string } | undefined)?.code;
      this.error =
        code === "not_loaded" ? "state.not_loaded" : "state.load_error";
    }
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.hass && this.isConnected) this.subscribe();
    const file = this.file;
    if (this.source?.file !== file && this.loading !== file) {
      this.loading = file;
      loadLayout(file).then(
        (text) => {
          if (this.loading === file) this.source = { file, text };
        },
        () => {
          if (this.loading === file) this.error = "state.load_error";
        },
      );
    }
  }

  protected override render() {
    if (this.error) {
      return html`<div class="message">
        ${localize(this.language, this.error)}
      </div>`;
    }
    const t = (key: string): string => localize(this.language, key);
    return html`${
        this.listening
          ? html`<div class="master">
              <span>${t("master.listening")}</span>
              ${
                this.hass?.user?.is_admin
                  ? html`<button type="button" @click=${this.claim}>
                      ${t("master.claim")}
                    </button>`
                  : ""
              }
              ${
                this.claimError
                  ? html`<span class="error">${t("master.claim_error")}</span>`
                  : ""
              }
            </div>`
          : ""
      }
      <div class="schema" @click=${this.onClick}></div>`;
  }

  protected override updated(): void {
    const container = this.renderRoot.querySelector(".schema");
    if (!container || !this.source || !this.hass || !this.data) return;
    const key = JSON.stringify([
      this.source.file,
      this.appearance,
      this.language,
    ]);
    if (!this.schema || this.schemaKey !== key) {
      this.schema = new Schema(
        this.source.text,
        this.appearance,
        this.language,
      );
      this.schemaKey = key;
      container.replaceChildren(this.schema.svg);
    }
    this.schema.update(this.hass, this.data);
  }

  private onClick(event: Event): void {
    const target = (event.target as Element | null)?.closest?.("[data-entity]");
    const entityId = target?.getAttribute("data-entity");
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      }),
    );
  }

  static override styles = css`
    :host {
      display: block;
    }
    .schema svg {
      display: block;
      width: 100%;
      height: auto;
    }
    :host([fit]) .schema svg {
      height: var(--daikin-view-height, auto);
      max-height: var(--daikin-view-height, none);
    }
    .message {
      padding: 16px;
      color: var(--secondary-text-color);
    }
    .master {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 16px;
      padding: 8px 16px;
      margin-bottom: 8px;
      border-radius: var(--ha-card-border-radius, 12px);
      background: var(--warning-color, #ffa600);
      color: var(--text-primary-color, #fff);
    }
    .master span {
      flex: 1;
    }
    .master .error {
      flex-basis: 100%;
    }
    .master button {
      font: inherit;
      padding: 6px 14px;
      border-radius: 18px;
      border: 1px solid currentColor;
      background: none;
      color: inherit;
      cursor: pointer;
    }
  `;
}
