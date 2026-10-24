import type { ActiveScenario } from "./scenarioState";
import type {
  AssistantResponse,
  BriefingRequest,
  BriefingResponse,
  PreviousEstimate,
  CircuitMap,
  CrewParams,
  SimulationResult,
  CircuitSummary,
  PremiseContext,
  PremiseListItem,
  RiskResult,
  ScenarioOption,
  ScenarioResult,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(`${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

const enc = encodeURIComponent;

export const api = {
  circuits: () => request<CircuitSummary[]>("/api/circuits"),
  premises: (circuitId: string) => request<PremiseListItem[]>(`/api/circuits/${circuitId}/premises`),
  map: (circuitId: string) => request<CircuitMap>(`/api/circuits/${circuitId}/map`),
  premise: (id: string, signal?: AbortSignal) => request<PremiseContext>(`/api/premises/${enc(id)}`, { signal }),
  risk: (id: string, severity: string, signal?: AbortSignal) =>
    request<RiskResult>(`/api/premises/${enc(id)}/risk?severity=${enc(severity)}`, { signal }),
  scenarios: (id: string, signal?: AbortSignal) =>
    request<{ premise_id: string; scenarios: ScenarioOption[] }>(`/api/premises/${enc(id)}/scenarios`, { signal }),
  runScenario: (id: string, scenarioId: string, locationIds: string[]) =>
    request<ScenarioResult>(`/api/premises/${enc(id)}/scenario`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario_id: scenarioId, location_ids: locationIds }),
    }),
  briefing: (body: BriefingRequest, signal?: AbortSignal) =>
    request<BriefingResponse>("/api/briefing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    }),
  assistant: (briefing: BriefingRequest, question: string, previous: PreviousEstimate | null, signal?: AbortSignal) =>
    request<AssistantResponse>("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ briefing, question, previous }),
      signal,
    }),
  // Fixed scenario definition evaluated for one premise, with crew assumptions.
  simulate: (circuitId: string, premiseId: string, active: ActiveScenario, crew: CrewParams, signal?: AbortSignal) =>
    request<SimulationResult>(`/api/circuits/${enc(circuitId)}/simulation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        premise_id: premiseId,
        scenario_id: active.scenarioId,
        scenario_label: active.label,
        location_ids: active.locationIds,
        crew,
      }),
      signal,
    }),
};

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";
