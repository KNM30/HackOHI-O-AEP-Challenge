import { describe, expect, it } from "vitest";
import { commsReducer, initialComms, isCurrentAnswer, lastNotified } from "./commsState";
import type { MessagePreview } from "./types";

const m = (type: MessagePreview["type"], key: string, status: MessagePreview["status"] = "would_send", upper = 10): MessagePreview => ({
  type,
  title: type,
  status,
  status_reason: "",
  dedupe_key: key,
  simulated: true,
  text: "[SIMULATED] x",
  estimate: { range_kind: "bounded", lower_h: 1, upper_h: upper, confidence: "low" },
});

describe("simulated message log", () => {
  it("adds a message once per dedupe key across re-renders", () => {
    let s = commsReducer(initialComms, { type: "deliver", messages: [m("pre_storm", "A")], scenarioKey: null });
    s = commsReducer(s, { type: "deliver", messages: [m("pre_storm", "A")], scenarioKey: null });
    s = commsReducer(s, { type: "deliver", messages: [m("pre_storm", "A")], scenarioKey: null });
    expect(s.log).toHaveLength(1);
  });

  it("logs only messages that would be sent", () => {
    const s = commsReducer(initialComms, {
      type: "deliver",
      messages: [m("pre_storm", "A", "triggered_not_opted_in"), m("outage_confirmed", "B", "not_triggered")],
      scenarioKey: "S1",
    });
    expect(s.log).toHaveLength(0);
  });

  it("de-duplicates lifecycle events", () => {
    let s = commsReducer(initialComms, { type: "event", event: { type: "outage_confirmed", scenario_key: "S1" } });
    s = commsReducer(s, { type: "event", event: { type: "outage_confirmed", scenario_key: "S1" } });
    expect(s.events).toHaveLength(1);
  });

  it("scenario reset clears simulated history but keeps pre-storm alerts", () => {
    let s = commsReducer(initialComms, { type: "event", event: { type: "outage_confirmed", scenario_key: "S1" } });
    s = commsReducer(s, { type: "deliver", messages: [m("pre_storm", "A"), m("outage_confirmed", "B")], scenarioKey: "S1" });
    s = commsReducer(s, { type: "clearScenario" });
    expect(s.events).toHaveLength(0);
    expect(s.log.map((x) => x.type)).toEqual(["pre_storm"]);
    expect(commsReducer(s, { type: "clearAll" })).toEqual(initialComms);
  });

  it("last notified estimate comes from the latest outage/update message for the scenario", () => {
    let s = commsReducer(initialComms, { type: "deliver", messages: [m("outage_confirmed", "B", "would_send", 10)], scenarioKey: "S1" });
    s = commsReducer(s, { type: "deliver", messages: [m("estimate_updated", "C", "would_send", 20)], scenarioKey: "S1" });
    expect(lastNotified(s.log, "S1")?.upper_h).toBe(20);
    expect(lastNotified(s.log, "S2")).toBeNull();
  });
});

describe("assistant freshness", () => {
  it("drops answers computed for an older snapshot", () => {
    expect(isCurrentAnswer("SNP-2", "SNP-1")).toBe(false);
    expect(isCurrentAnswer("SNP-2", "SNP-2")).toBe(true);
    expect(isCurrentAnswer(null, "SNP-2")).toBe(false);
  });
});
