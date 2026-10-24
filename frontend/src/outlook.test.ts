import { describe, expect, it } from "vitest";
import { suggestions } from "./components/AssistantPanel";
import { crewComparison, restorationOutlook } from "./outlook";
import type { CrewParams, PreviousEstimate, RestorationResult } from "./types";

const result = (range_kind: RestorationResult["selected"]["range_kind"], display: string, network_uncertain = false) =>
  ({
    selected: { range_kind, display, network_uncertain, confidence: { level: "low" } },
  }) as unknown as RestorationResult;

const crew = (crews: number): CrewParams => ({
  crews,
  crew_size: 4,
  hours_per_day: 16,
  access_delay_h: 0,
  access_scope: "reported",
  prioritize_critical: true,
  restring_assumption: true,
});

const est = (crews: number | null, over: Partial<PreviousEstimate> = {}): PreviousEstimate => ({
  snapshot_version: "SNP-1",
  severity: "moderate",
  crew: crews === null ? null : crew(crews),
  scenario_key: "SCN-1",
  range_kind: "bounded",
  lower_h: 4,
  upper_h: 12,
  risk_band: "high",
  ...over,
});

describe("restoration outlook summary", () => {
  it("explains that restoration depends on a scenario when none is active", () => {
    const o = restorationOutlook(false, null, false, null);
    expect(o.state).toBe("none");
    expect(o.text).toMatch(/depends on the damage scenario/i);
  });

  it("reports loading and failure without inventing a number", () => {
    expect(restorationOutlook(true, null, true, null).state).toBe("loading");
    const failed = restorationOutlook(true, null, false, "500: boom");
    expect(failed.state).toBe("error");
    expect(failed.text).toBe("Unavailable");
  });

  it("keeps the essential qualification next to the estimate", () => {
    const lb = restorationOutlook(true, result("lower_bound_only", "At least 9.0 h"), false, null);
    expect(lb.text).toMatch(/^At least/);
    expect(lb.qualifier).toMatch(/lower bound/);
    expect(restorationOutlook(true, result("conditional", "If isolated: 1 h | If not: 9 h"), false, null).qualifier).toMatch(
      /reroute power/,
    );
    expect(restorationOutlook(true, result("insufficient_data", "Cannot estimate"), false, null).qualifier).toMatch(
      /insufficient information/,
    );
    const b = restorationOutlook(true, result("bounded", "4.0 h - 12 h", true), false, null);
    expect(b.text).toBe("4.0 h - 12 h");
    expect(b.qualifier).toMatch(/network dependency uncertain/);
    expect(b.confidence).toBe("low");
  });

  it("marks a result shown during recalculation as stale", () => {
    expect(restorationOutlook(true, result("bounded", "x"), true, null).stale).toBe(true);
  });
});

describe("crew comparison", () => {
  it("compares only crew/access changes within the same scenario and severity", () => {
    expect(crewComparison(est(2), est(3))).toBe("Before this change (2 crews of 4): 4.0 h - 12 h");
    expect(crewComparison(est(2, { range_kind: "lower_bound_only" }), est(3))).toMatch(/at least 4\.0 h/);
    expect(crewComparison(est(2), est(2))).toBeNull();
    expect(crewComparison(est(2, { scenario_key: "SCN-0" }), est(3))).toBeNull();
    expect(crewComparison(est(2, { severity: "severe" }), est(3))).toBeNull();
    expect(crewComparison(est(null), est(3))).toBeNull();
    expect(crewComparison(null, est(3))).toBeNull();
  });
});

describe("assistant suggestions", () => {
  it("uses the brief's customer questions and offers at most three", () => {
    expect(suggestions(false, false)).toEqual(["Will I lose power?", "What should I do to prepare?", "Do I qualify for outage alerts?"]);
    expect(suggestions(true, false)).toEqual([
      "How long could restoration take?",
      "How would another crew change this?",
      "Do I qualify for outage alerts?",
    ]);
    expect(suggestions(true, true)[2]).toBe("Why did my estimate change?");
  });
});
