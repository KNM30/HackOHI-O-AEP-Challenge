import { describe, expect, it } from "vitest";
import { createLatest, initialScenarioState, scenarioReducer, type ScenarioState } from "./scenarioState";
import type { ScenarioOption, SimulationResult } from "./types";

const option = (id: string, mode: "single" | "multi", ids: string[]): ScenarioOption => ({
  id,
  label: id,
  description: "",
  mode,
  available: true,
  unavailable_reason: null,
  locations: ids.map((x) => ({ id: x, label: x, location: null })),
  default_location_ids: mode === "single" ? ids.slice(0, 1) : ids,
});

const result = (label: string) => ({ impact: { scenario_label: label } }) as unknown as SimulationResult;

const apply = (s: ScenarioState, ...actions: Parameters<typeof scenarioReducer>[1][]) =>
  actions.reduce(scenarioReducer, s);

const activated = (ids = ["A", "B"]) =>
  apply(initialScenarioState, { type: "choose", scenario: option("m", "multi", ids) }, { type: "activate", label: "m" });

describe("scenario state", () => {
  it("activates the draft as a fixed definition and resets fully", () => {
    let s = activated();
    expect(s.active).toEqual({ scenarioId: "m", label: "m", locationIds: ["A", "B"] });
    s = apply(s, { type: "requestStarted", requestId: 5 }, { type: "loaded", requestId: 5, result: result("x") });
    expect(s.status).toBe("ready");
    s = apply(s, { type: "reset" });
    expect(s.active).toBeNull();
    expect(s.result).toBeNull();
    expect(s.status).toBe("idle");
  });

  it("keeps the active scenario fixed when the premise changes", () => {
    let s = activated(["A", "B"]);
    s = apply(s, { type: "premiseChanged" });
    expect(s.active?.locationIds).toEqual(["A", "B"]);
    expect(s.draft.scenarioId).toBeNull();
  });

  it("editing the draft does not change the active definition until re-activated", () => {
    let s = activated(["A", "B"]);
    s = apply(s, { type: "toggleLocation", id: "A" });
    expect(s.active?.locationIds).toEqual(["A", "B"]);
    s = apply(s, { type: "activate", label: "m" });
    expect(s.active?.locationIds).toEqual(["B"]);
  });

  it("drops a response that arrives after reset", () => {
    let s = apply(activated(), { type: "requestStarted", requestId: 7 });
    s = apply(s, { type: "reset" }, { type: "loaded", requestId: 7, result: result("late") });
    expect(s.result).toBeNull();
    expect(s.status).toBe("idle");
  });

  it("keeps only the latest of overlapping requests (e.g. crew changes)", () => {
    let s = apply(activated(), { type: "requestStarted", requestId: 1 }, { type: "requestStarted", requestId: 2 });
    s = apply(s, { type: "loaded", requestId: 2, result: result("second") });
    s = apply(s, { type: "loaded", requestId: 1, result: result("first") });
    expect(s.result?.impact.scenario_label).toBe("second");
    s = apply(s, { type: "failed", requestId: 1, error: "old error" });
    expect(s.status).toBe("ready");
  });

  it("will not activate an empty selection", () => {
    let s = apply(initialScenarioState, { type: "choose", scenario: option("m", "multi", ["A"]) });
    s = apply(s, { type: "toggleLocation", id: "A" }, { type: "activate", label: "m" });
    expect(s.active).toBeNull();
  });
});

describe("createLatest", () => {
  it("marks earlier requests stale and aborts them", () => {
    const latest = createLatest();
    const a = latest.start();
    const b = latest.start();
    expect(a.isCurrent()).toBe(false);
    expect(a.signal.aborted).toBe(true);
    expect(b.isCurrent()).toBe(true);
    latest.cancel();
    expect(b.isCurrent()).toBe(false);
  });
});
