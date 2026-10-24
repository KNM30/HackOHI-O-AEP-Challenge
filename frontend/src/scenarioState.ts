import type { ScenarioOption, SimulationResult } from "./types";

// Simulated-outage state, kept separate from pre-storm risk.
// - `draft` is what the user is choosing from the current premise's scenario presets.
// - `active` is a fixed definition (a set of damage locations). Once simulated it stays
//   pinned while other premises are viewed, so every premise sees the same repairs.
// - `requestId` guards against stale responses: every request, reset or definition
//   change bumps it, and a late response carrying an older id is dropped.
export interface ActiveScenario {
  scenarioId: string;
  label: string;
  locationIds: string[];
}

export interface ScenarioState {
  draft: { scenarioId: string | null; locationIds: string[] };
  active: ActiveScenario | null;
  requestId: number;
  status: "idle" | "loading" | "ready" | "error";
  result: SimulationResult | null;
  error: string | null;
}

export type ScenarioAction =
  | { type: "choose"; scenario: ScenarioOption }
  | { type: "setLocation"; id: string } // single-location presets
  | { type: "toggleLocation"; id: string } // multi-location presets
  | { type: "activate"; label: string }
  | { type: "premiseChanged" }
  | { type: "requestStarted"; requestId: number }
  | { type: "loaded"; requestId: number; result: SimulationResult }
  | { type: "failed"; requestId: number; error: string }
  | { type: "reset" };

export const initialScenarioState: ScenarioState = {
  draft: { scenarioId: null, locationIds: [] },
  active: null,
  requestId: 0,
  status: "idle",
  result: null,
  error: null,
};

export function scenarioReducer(state: ScenarioState, action: ScenarioAction): ScenarioState {
  switch (action.type) {
    case "choose":
      return {
        ...state,
        draft: { scenarioId: action.scenario.id, locationIds: [...action.scenario.default_location_ids] },
      };
    case "setLocation":
      return { ...state, draft: { ...state.draft, locationIds: [action.id] } };
    case "toggleLocation": {
      const ids = state.draft.locationIds;
      return {
        ...state,
        draft: {
          ...state.draft,
          locationIds: ids.includes(action.id) ? ids.filter((x) => x !== action.id) : [...ids, action.id],
        },
      };
    }
    case "activate":
      if (!state.draft.scenarioId || !state.draft.locationIds.length) return state;
      return {
        ...state,
        active: { scenarioId: state.draft.scenarioId, label: action.label, locationIds: [...state.draft.locationIds] },
        requestId: state.requestId + 1,
        result: null,
        error: null,
      };
    case "premiseChanged":
      // presets belong to the old premise; the active fixed scenario stays
      return { ...state, draft: { scenarioId: null, locationIds: [] } };
    case "requestStarted":
      return { ...state, requestId: action.requestId, status: "loading", error: null };
    case "loaded":
      if (action.requestId !== state.requestId) return state; // stale
      return { ...state, status: "ready", result: action.result };
    case "failed":
      if (action.requestId !== state.requestId) return state; // stale
      return { ...state, status: "error", error: action.error };
    case "reset":
      return { ...initialScenarioState, requestId: state.requestId + 1 };
  }
}

/** Latest-only request helper for simple fetches (risk, premise context). */
export function createLatest() {
  let current = 0;
  let controller: AbortController | null = null;
  return {
    start() {
      controller?.abort();
      controller = new AbortController();
      const id = ++current;
      return { signal: controller.signal, isCurrent: () => id === current };
    },
    cancel() {
      controller?.abort();
      current++;
    },
  };
}
