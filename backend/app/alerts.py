"""Alert eligibility (separate from opt-in and channel) and deterministic message previews."""
from __future__ import annotations

import hashlib
import json

from . import alert_config as cfg
from . import schemas as s


def _fmt(h: float | None) -> str:
    if h is None:
        return "?"
    if h < 1:
        return f"{round(h * 60)} minutes"
    return f"{h:.0f} hours" if h < 48 else f"{h / 24:.1f} days"


def estimate_signature(r: s.CustomerRestoration) -> s.EstimateSignature:
    c = r.conditional
    rnd = lambda v: None if v is None else round(v * 2) / 2  # half-hour resolution
    return s.EstimateSignature(range_kind=r.range_kind, lower_h=rnd(r.lower_h), upper_h=rnd(r.upper_h),
                               confidence=r.confidence.level,
                               if_isolated_high_h=rnd(c.if_isolated_high_h) if c else None,
                               if_repair_high_h=rnd(c.if_repair_high_h if c.repair_scope_complete
                                                    else c.if_repair_low_h) if c else None)


def estimate_text(r: s.CustomerRestoration) -> str:
    k = r.range_kind
    if k == "bounded":
        t = (f"Simulated estimate: power back roughly {_fmt(r.lower_h)} to {_fmt(r.upper_h)} after the response "
             f"starts. This is a model estimate, not a promise.")
    elif k == "lower_bound_only":
        t = (f"Simulated estimate: at least {_fmt(r.lower_h)} after the response starts. Part of the repair is not "
             f"covered by our labor data, so it may take longer.")
    elif k == "conditional" and r.conditional:
        c = r.conditional
        if c.if_repair_high_h is None:
            rep = "after the repair, which we cannot estimate"
        elif not c.repair_scope_complete:
            rep = (f"after the repair, at least {_fmt(c.if_repair_low_h)} (part of the repair is not covered by our "
                   f"labor data, so it may take longer)")
        else:
            rep = f"after the repair, roughly {_fmt(c.if_repair_low_h)} to {_fmt(c.if_repair_high_h)}"
        t = (f"Two possibilities: roughly {_fmt(c.if_isolated_low_h)} to {_fmt(c.if_isolated_high_h)} if crews can "
             f"isolate the damaged section; otherwise {rep}. Neither is a promise.")
    elif k == "crew_infeasible":
        t = ("We can't estimate a time: under the simulated assumptions the crews are too small for a required "
             "repair.")
    elif k == "insufficient_data":
        t = "We can't estimate a restoration time with the information available."
    else:
        t = "Your home is not interrupted in this simulation."
    if r.uses_assumption and k not in ("not_interrupted", "crew_infeasible", "insufficient_data"):
        t += " It includes our own assumed time for replacing damaged wire, which AEP's labor data does not cover."
    if r.network_uncertain and k != "not_interrupted":
        t += " Which equipment controls your outage is uncertain in our model, so this could change."
    return t


def _horizon(r: s.CustomerRestoration) -> float | None:
    if r.range_kind == "bounded":
        return r.upper_h
    if r.range_kind == "conditional" and r.conditional and r.conditional.repair_scope_complete:
        return r.conditional.if_repair_high_h
    return None  # unknown or lower bound only


def _change(prev: s.LastNotified, cur: s.EstimateSignature) -> str | None:
    """Plain-language reason if the estimate changed meaningfully, else None."""
    if prev.range_kind != cur.range_kind:
        if cur.range_kind in ("insufficient_data", "crew_infeasible"):
            return "We can no longer estimate a restoration time."
        return "The type of estimate changed (for example it now depends on whether crews can isolate the damage)."
    if prev.confidence == "moderate" and cur.confidence == "low":
        return "Confidence in the estimate dropped."
    for p, c in ((prev.upper_h, cur.upper_h), (prev.if_repair_high_h, cur.if_repair_high_h),
                 (prev.if_isolated_high_h, cur.if_isolated_high_h)):
        if p is None or c is None:
            continue
        if abs(c - p) >= max(cfg.ESTIMATE_CHANGE_MIN_H, cfg.ESTIMATE_CHANGE_MIN_FRACTION * p):
            return ("The estimate got longer" if c > p else "The estimate got shorter") + \
                f" (latest modeled time moved from about {_fmt(p)} to about {_fmt(c)})."
    return None


def _key(*parts) -> str:
    return "MSG-" + hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()[:12].upper()


def _compose(title: str, what: str, estimate: str | None, todo: str, next_update: str) -> str:
    lines = [cfg.LABEL_PREFIX, title, f"What happened: {what}"]
    if estimate:
        lines.append(f"Estimate: {estimate}")
    lines += [f"What to do: {todo}", f"Next update: {next_update}", cfg.LABEL_SUFFIX]
    return "\n".join(lines)


def evaluate(premise_alias: str, risk: s.RiskResult, impact: s.ScenarioResult | None,
             restoration: s.RestorationResult | None, scenario_key: str | None, prefs: s.Preferences,
             alerts_in: s.AlertPrefs, events: list[s.SimEvent], last: s.LastNotified | None,
             guidance: list[s.Recommendation]) -> s.AlertsResult:
    opted, channel = alerts_in.opt_in, alerts_in.channel
    channel_ok = channel != "none"

    def status_for(triggered: bool, reason: str) -> tuple[str, str]:
        if not triggered:
            return "not_triggered", reason
        if not opted:
            return "triggered_not_opted_in", "Warranted, but you have not opted in to alerts (demo preference)."
        if not channel_ok:
            return "triggered_no_channel", "Warranted, but no notification channel is selected."
        return "would_send", f"Would be sent by {cfg.CHANNELS[channel].lower()} (simulated; nothing is delivered)."

    sel = restoration.selected if restoration else None
    interrupted = impact is not None and impact.selected_premise.status != "not_interrupted"
    ev = {e.type for e in events if scenario_key and e.scenario_key == scenario_key}
    outage_confirmed = "outage_confirmed" in ev and interrupted
    restored = "restoration_confirmed" in ev and outage_confirmed
    top_actions = [g.action for g in guidance if g.category == "routine"][:2]
    todo_default = " ".join(top_actions) or "Review the preparation checklist in the app."
    medical_note = None
    if prefs.medical_power_dependent and interrupted and sel is not None:
        h = _horizon(sel)
        if h is None or h > cfg.MEDICAL_ESCALATION_H:
            medical_note = ("You told us you rely on powered medical equipment: follow your medical outage plan now, "
                            "and call 911 if anyone's health is at risk. This does not guarantee faster restoration.")

    msgs: list[s.MessagePreview] = []

    # 1. pre-storm (risk only; never implies an outage)
    band = risk.band if risk.status == "calculated" else None
    pre_trig = band is not None and cfg.BAND_RANK[band] >= cfg.BAND_RANK[cfg.PRE_STORM_MIN_BAND]
    st, why = status_for(pre_trig, f"Your pre-storm risk is {band or 'not available'}; a pre-storm alert needs "
                                   f"{cfg.PRE_STORM_MIN_BAND} risk.")
    msgs.append(s.MessagePreview(
        type="pre_storm", title="Storm preparation alert (simulated)", status=st, status_reason=why,
        dedupe_key=_key("pre_storm", premise_alias, risk.severity, band),
        text=_compose("Storm preparation alert",
                      f"A {risk.severity_label.lower()} could affect power at your home ({premise_alias}). "
                      f"Our prototype rates your outage risk as {band or 'unknown'} (a heuristic band, not a "
                      f"probability). No outage has happened.",
                      None, todo_default,
                      "only if the scenario changes or an outage is (simulated as) confirmed.")))

    # 2. outage confirmed (explicit simulated event only)
    if sel is None:
        o_reason = "No damage scenario is active."
    elif not interrupted:
        o_reason = "Your home is not interrupted in the active scenario, so an outage cannot be confirmed."
    else:
        o_reason = "Use 'Simulate: outage confirmed' to trigger this. Risk or history never confirm an outage."
    st, why = status_for(outage_confirmed, o_reason)
    sig = estimate_signature(sel) if sel and interrupted else None
    if sel and interrupted:
        o_text = _compose("Outage confirmed (simulated)",
                          f"Your home ({premise_alias}) is without power in the simulated scenario "
                          f"\"{impact.scenario_label}\".",
                          estimate_text(sel), " ".join(filter(None, [medical_note, todo_default])),
                          "if the estimate changes meaningfully, if we can no longer estimate it, or when power is "
                          "(simulated as) restored.")
    else:
        o_text = _compose("Outage confirmed (simulated)", "Not applicable: no simulated outage at your home.",
                          None, "Nothing right now.", "-")
    msgs.append(s.MessagePreview(type="outage_confirmed", title="Outage confirmed (simulated)", status=st,
                                 status_reason=why, text=o_text, estimate=sig,
                                 dedupe_key=_key("outage_confirmed", premise_alias, scenario_key)))

    # 3. estimate updated (needs a confirmed outage and a meaningful change vs the last message sent)
    change = None
    if outage_confirmed and not restored and sig and last and last.scenario_key == scenario_key:
        change = _change(last, sig)
    if not outage_confirmed:
        u_reason = "Updates start only after a (simulated) outage confirmation."
    elif restored:
        u_reason = "Power has been (simulated as) restored."
    elif last is None:
        u_reason = "No earlier estimate has been sent to compare against."
    else:
        u_reason = "The estimate has not changed meaningfully since the last message."
    st, why = status_for(change is not None, u_reason)
    msgs.append(s.MessagePreview(
        type="estimate_updated", title="Restoration estimate updated (simulated)", status=st, status_reason=why,
        estimate=sig, dedupe_key=_key("estimate_updated", premise_alias, scenario_key, sig),
        text=_compose("Restoration estimate updated (simulated)",
                      change or "No meaningful change.", estimate_text(sel) if sel and interrupted else None,
                      " ".join(filter(None, [medical_note, todo_default])),
                      "if the estimate changes again or when power is (simulated as) restored.")))

    # 4. restoration complete (explicit simulated event only)
    st, why = status_for(restored, "Use 'Simulate: power restored' after a confirmed outage. A predicted finish "
                                   "time passing does not count as restoration.")
    msgs.append(s.MessagePreview(
        type="restoration_complete", title="Power restored (simulated)", status=st, status_reason=why,
        dedupe_key=_key("restoration_complete", premise_alias, scenario_key),
        text=_compose("Power restored (simulated)", f"Power is back at your home ({premise_alias}) in the "
                                                    "simulated scenario.", None,
                      "Check food that was above 40°F for 2 hours or more, plug appliances back in gradually, and "
                      "report any damage you see. If the outage lasted more than a day, check refrigerated "
                      "medication with your pharmacist.",
                      "none - this simulated event is closed. Report a new outage if power goes out again.")))

    rules = [
        s.AlertRule(id="elevated_risk", description=f"Pre-storm risk band is {cfg.PRE_STORM_MIN_BAND}.",
                    active=pre_trig),
        s.AlertRule(id="outage_confirmed", description="An outage at your home is explicitly (simulated as) "
                                                       "confirmed.", active=outage_confirmed),
        s.AlertRule(id="estimate_change", description=f"Latest modeled time moves by at least "
                                                      f"{cfg.ESTIMATE_CHANGE_MIN_H:g} h or "
                                                      f"{cfg.ESTIMATE_CHANGE_MIN_FRACTION:.0%} since the last message.",
                    active=change is not None and "moved" in (change or "")),
        s.AlertRule(id="confidence_or_estimate_lost", description="Confidence drops, or the estimate can no longer "
                                                                  "be made.",
                    active=change is not None and "moved" not in (change or "")),
        s.AlertRule(id="restoration_confirmed", description="Restoration is explicitly (simulated as) confirmed.",
                    active=restored),
    ]
    return s.AlertsResult(
        disclaimer="Prototype alert rules for a simulated scenario - not AEP policy. Nothing is actually sent and no "
                   "contact details are collected.",
        opted_in=opted, channel=channel, channel_label=cfg.CHANNELS[channel], channel_ok=channel_ok,
        warranted_now=[m.type for m in msgs if m.status != "not_triggered"],
        escalation=medical_note, timing=cfg.TIMING, rules=rules, messages=msgs)
