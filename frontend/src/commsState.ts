import type { LastNotified, MessagePreview, SimEvent } from "./types";

// Simulated communications for this browser session (React state only; nothing is
// written to localStorage/sessionStorage and nothing is sent anywhere).
// - `events`: explicit simulated lifecycle events (outage confirmed, power restored).
// - `log`: messages that "would have been sent". A message is added once per dedupe key,
//   so re-renders and repeated identical calculations never duplicate it.
export interface LoggedMessage extends MessagePreview {
  seq: number;
  scenario_key: string | null;
}

export interface CommsState {
  events: SimEvent[];
  log: LoggedMessage[];
  seq: number;
}

export type CommsAction =
  | { type: "event"; event: SimEvent }
  | { type: "deliver"; messages: MessagePreview[]; scenarioKey: string | null }
  | { type: "clearScenario" } // scenario reset/changed: drop simulated lifecycle history
  | { type: "clearAll" }; // premise changed

export const initialComms: CommsState = { events: [], log: [], seq: 0 };

export function commsReducer(state: CommsState, action: CommsAction): CommsState {
  switch (action.type) {
    case "event": {
      const e = action.event;
      if (state.events.some((x) => x.type === e.type && x.scenario_key === e.scenario_key)) return state;
      return { ...state, events: [...state.events, e] };
    }
    case "deliver": {
      const known = new Set(state.log.map((m) => m.dedupe_key));
      const fresh = action.messages.filter((m) => m.status === "would_send" && !known.has(m.dedupe_key));
      if (!fresh.length) return state;
      let seq = state.seq;
      const added = fresh.map((m) => ({ ...m, seq: ++seq, scenario_key: m.type === "pre_storm" ? null : action.scenarioKey }));
      return { ...state, seq, log: [...state.log, ...added] };
    }
    case "clearScenario":
      return { ...state, events: [], log: state.log.filter((m) => m.type === "pre_storm") };
    case "clearAll":
      return initialComms;
  }
}

/** The estimate in the last outage/update message sent for this scenario (baseline for "meaningful change"). */
export function lastNotified(log: LoggedMessage[], scenarioKey: string | null): LastNotified | null {
  if (!scenarioKey) return null;
  for (let i = log.length - 1; i >= 0; i--) {
    const m = log[i];
    if ((m.type === "outage_confirmed" || m.type === "estimate_updated") && m.scenario_key === scenarioKey && m.estimate) {
      return { ...m.estimate, scenario_key: scenarioKey };
    }
  }
  return null;
}

/** An assistant answer is shown only if it was computed for the snapshot currently on screen. */
export function isCurrentAnswer(currentSnapshot: string | null, answerSnapshot: string): boolean {
  return currentSnapshot !== null && currentSnapshot === answerSnapshot;
}
