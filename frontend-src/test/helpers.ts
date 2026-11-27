import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { DashboardData, HassEntity, HomeAssistant } from "../src/types";

export const LAYOUT_NAMES = ["light", "dark", "petrol"] as const;

export function layoutSource(name: string): string {
  // Vitest runs in the frontend project.
  return readFileSync(
    join(process.cwd(), "layouts", `daikin_glass_${name}.svg`),
    "utf-8",
  );
}

export function entity(
  entityId: string,
  state: string,
  attributes: Record<string, unknown> = {},
): HassEntity {
  return { entity_id: entityId, state, attributes };
}

export interface MockHass extends HomeAssistant {
  calls: Record<string, unknown>[];
  events: ((event: unknown) => void)[];
  /** Callbacks of `subscribeMessage`, by message type. */
  subscriptions: Record<string, ((message: unknown) => void)[]>;
}

/** A Home Assistant object with states and canned WebSocket answers. */
export function mockHass(
  states: HassEntity[],
  answers: Record<string, unknown> = {},
  options: { language?: string; dark?: boolean; admin?: boolean } = {},
): MockHass {
  const calls: Record<string, unknown>[] = [];
  const events: ((event: unknown) => void)[] = [];
  const subscriptions: Record<string, ((message: unknown) => void)[]> = {};
  return {
    calls,
    events,
    subscriptions,
    states: Object.fromEntries(states.map((s) => [s.entity_id, s])),
    locale: { language: options.language ?? "en" },
    themes: { darkMode: options.dark ?? false },
    user: { is_admin: options.admin ?? true },
    connection: {
      subscribeEvents: (callback) => {
        events.push(callback);
        return Promise.resolve(() => undefined);
      },
      subscribeMessage: <T>(
        callback: (message: T) => void,
        message: Record<string, unknown>,
      ) => {
        const type = message.type as string;
        (subscriptions[type] ??= []).push(
          callback as (message: unknown) => void,
        );
        return Promise.resolve(() => undefined);
      },
    },
    callWS: <T>(message: Record<string, unknown>): Promise<T> => {
      calls.push(message);
      const answer = answers[message.type as string];
      if (answer instanceof Error || (answer as { code?: string })?.code) {
        return Promise.reject(answer);
      }
      if (typeof answer === "function") {
        return Promise.resolve(answer(message) as T);
      }
      return Promise.resolve(answer as T);
    },
    formatEntityState: (stateObj) => `«${stateObj.state}»`,
  };
}

/** Entities as the integration returns them: value ID → entity. */
export function dashboard(
  entities: Record<string, string>,
  info: string[] = [],
): DashboardData {
  return { entities, info };
}

/** Wait until the pending promises and Lit updates are done. */
export async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++)
    await new Promise((resolve) => setTimeout(resolve, 0));
}
