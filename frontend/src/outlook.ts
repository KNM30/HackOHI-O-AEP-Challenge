import type { CrewParams, PreviousEstimate, RestorationResult } from "./types";

// Presentation helpers shared by the summary bar, Overview and Explore. They only reword
// what the backend already calculated; no numbers are derived here.

export const fmtHours = (h: number | null) =>
  h === null ? "?" : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h < 10 ? h.toFixed(1) : h.toFixed(0)} h` : `${(h / 24).toFixed(1)} d`;

export type RangeKind = RestorationResult["selected"]["range_kind"];

export const KIND_LABEL: Record<RangeKind, string> = {
  not_interrupted: "Not interrupted",
  bounded: "Full range (all required work modeled)",
  lower_bound_only: "Lower bound",
  conditional: "Two possible outcomes",
  crew_infeasible: "Not possible with the selected crews",
  insufficient_data: "Cannot be estimated",
};

/** Why an estimate is a lower bound: the labor workbook has no unit for replacing wire along a span. */
export const LOWER_BOUND_NOTE = "Lower bound: the labor data has no time for replacing wire, so the full repair would take longer.";

export interface Outlook {
  state: "none" | "loading" | "error" | "ready";
  text: string;
  /** The qualification that must stay next to the number (conditional, incomplete, unavailable...). */
  qualifier: string | null;
  confidence: "high" | "moderate" | "low" | null;
  stale: boolean;
}

const QUALIFIER: Partial<Record<RangeKind, string>> = {
  lower_bound_only: "lower bound - no labor data for replacing wire",
  conditional: "depends on whether crews can reroute power around the damage",
  crew_infeasible: "a required job needs a larger crew",
  insufficient_data: "insufficient information - the repair is not in the labor data",
};

/** Restoration outlook for the selected premise, as shown in compact summaries. */
export function restorationOutlook(
  active: boolean,
  r: RestorationResult | null,
  loading: boolean,
  error: string | null,
): Outlook {
  if (!active) return { state: "none", text: "Depends on the damage scenario", qualifier: null, confidence: null, stale: false };
  if (!r) {
    if (error) return { state: "error", text: "Unavailable", qualifier: "the simulation failed", confidence: null, stale: false };
    return { state: "loading", text: "Calculating...", qualifier: null, confidence: null, stale: false };
  }
  const s = r.selected;
  const parts = [QUALIFIER[s.range_kind], s.network_uncertain ? "network dependency uncertain" : undefined].filter(Boolean);
  return {
    state: "ready",
    text: s.range_kind === "not_interrupted" ? "Not interrupted in this scenario" : s.display,
    qualifier: parts.length ? parts.join("; ") : null,
    confidence: s.range_kind === "not_interrupted" ? null : s.confidence.level,
    stale: loading,
  };
}

function previousRange(p: PreviousEstimate): string {
  switch (p.range_kind) {
    case "bounded":
      return `${fmtHours(p.lower_h)} - ${fmtHours(p.upper_h)}`;
    case "lower_bound_only":
      return `at least ${fmtHours(p.lower_h)}`;
    default:
      return p.range_kind ? KIND_LABEL[p.range_kind as RangeKind]?.toLowerCase() ?? p.range_kind : "no estimate";
  }
}

const crewText = (c: CrewParams) => `${c.crews} crew${c.crews === 1 ? "" : "s"} of ${c.crew_size}`;

/**
 * "Before this change" line for the crew controls: only when the previous estimate is for the same
 * fixed scenario and differs only in the crew/access inputs, so the comparison is like for like.
 */
export function crewComparison(prev: PreviousEstimate | null, cur: PreviousEstimate | null): string | null {
  if (!prev?.crew || !cur?.crew || !prev.scenario_key || prev.scenario_key !== cur.scenario_key) return null;
  if (prev.severity !== cur.severity || JSON.stringify(prev.crew) === JSON.stringify(cur.crew)) return null;
  const changed =
    prev.crew.crews !== cur.crew.crews || prev.crew.crew_size !== cur.crew.crew_size ? crewText(prev.crew) : "previous settings";
  return `Before this change (${changed}): ${previousRange(prev)}`;
}
