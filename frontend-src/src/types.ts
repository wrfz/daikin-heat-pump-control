// The parts of the Home Assistant frontend objects the dashboard uses.

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export type UnsubscribeFunc = () => void;

export interface Connection {
  subscribeEvents(
    callback: (event: unknown) => void,
    eventType: string,
  ): Promise<UnsubscribeFunc>;
  subscribeMessage<T>(
    callback: (message: T) => void,
    subscribeMessage: Record<string, unknown>,
  ): Promise<UnsubscribeFunc>;
}

export interface HomeAssistant {
  states: Record<string, HassEntity | undefined>;
  locale: { language: string };
  language?: string;
  themes?: { darkMode?: boolean };
  user?: { is_admin: boolean };
  connection: Connection;
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  formatEntityState?(stateObj: HassEntity, state?: string): string;
}

/** Answer of the WebSocket command `daikin_heat_pump_control/entities`. */
export interface DashboardData {
  entities: Record<string, string>;
  info: string[];
}

/** Whether this instance controls the bridges (WebSocket `master/subscribe`). */
export interface MasterStatus {
  master: boolean;
  clients: number;
}

export type Rgb = [number, number, number];

/** Appearance of the dashboard; the card configuration and the panel share it. */
export interface Appearance {
  layout?: "auto" | "light" | "dark" | "petrol";
  /** False stops the animations of the layout. */
  animations?: boolean;
  background?: { show?: boolean; color?: Rgb; opacity?: number };
  box?: {
    fill?: Rgb;
    fill_opacity?: number;
    border?: Rgb;
    border_opacity?: number;
  };
  text?: { value_color?: Rgb; label_color?: Rgb };
}

export interface CardConfig extends Appearance {
  type: string;
}
