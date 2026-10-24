"""Deterministic, explainable pre-storm outage-risk band for a premise.

The score is a heuristic ranking aid, not a probability. See docs/risk_model.md.
"""
from __future__ import annotations

from . import risk_config as cfg
from . import schemas as s
from .network import CircuitNetwork


def band_for(score: float) -> str:
    for lower, band in cfg.BANDS:
        if score >= lower:
            return band
    return cfg.BANDS[-1][1]


def _historical_events(net: CircuitNetwork, p: dict):
    events, approx = {}, 0
    for d in net.damage:
        rel = net.relation(p, d)
        if rel is None or not rel.affects_premise:
            continue
        ev = net.event_of.get(d["public_id"])
        if ev is None:
            continue
        events[ev] = events.get(ev, 0) + 1
        if d.get("label_fallback") or (d.get("match_method") or "").startswith("secondary") or \
                (d.get("match_dist_m") or 0) > 5:
            approx += 1
    return events, approx


def susceptibility(net: CircuitNetwork, p: dict) -> dict:
    """Severity-independent features and points (deterministic)."""
    km = net.interrupting_km(p)
    events, approx = _historical_events(net, p)
    oh = km["Overhead"]
    exposure_pts = cfg.EXPOSURE_MAX_POINTS * min(oh / cfg.EXPOSURE_SATURATION_KM, 1.0)
    n_ev = len(events)
    history_pts = cfg.HISTORY_MAX_POINTS * min(n_ev / cfg.HISTORY_SATURATION_EVENTS, 1.0)
    service_pts = cfg.SERVICE_POINTS.get(p["service_type"], cfg.SERVICE_POINTS["Unknown"])
    return dict(km=km, events=events, approx_history=approx, exposure_pts=exposure_pts,
                history_pts=history_pts, service_pts=service_pts)


def score_from(feat: dict, severity: str) -> float:
    base = feat["exposure_pts"] + feat["history_pts"] + feat["service_pts"]
    return min(base * cfg.SEVERITY[severity]["factor"], cfg.SCORE_CAP)


def confidence(net: CircuitNetwork, p: dict, feat: dict, gaps: int) -> s.Confidence:
    d = cfg.CONFIDENCE_DEDUCTIONS
    reasons: list[s.ConfidenceReason] = []

    def ded(key: str, text: str, times: int = 1):
        reasons.append(s.ConfidenceReason(effect=-d[key] * times, text=text))

    ded("no_validation", "No confirmed-outage records are available to validate the score; it is a heuristic.")
    ded("inferred_feeder_head", "The substation connection point is inferred from the device hierarchy.")
    if gaps:
        ded("gap_on_path", f"{gaps} short mapping gap(s) on your supply path were joined by proximity.", min(gaps, 2))
    if any((net.devices[c].get("coverage_method") == "all_children_assumed") for c in p["chain"]):
        ded("assumed_coverage_in_chain", "Which branches one of your protective devices covers is assumed, "
                                         "not evidenced.")
    total = sum(feat["km"].values())
    if total and feat["km"]["Unknown"] / total > cfg.UNKNOWN_MOUNTING_SHARE:
        ded("unknown_mounting_share", "Part of the line that could interrupt you has unknown overhead/underground "
                                      "status.")
    if feat["approx_history"]:
        ded("approximate_history", f"{feat['approx_history']} historical record(s) behind your history signal were "
                                   "matched approximately.")
    rc, cc = net.stats.get("root_consistency"), net.stats.get("chain_consistency")
    if rc is None or rc < cfg.CONSISTENCY_THRESHOLD:
        ded("circuit_root_consistency", "The circuit's inferred orientation only partly agrees with the device "
                                        "hierarchy.")
    if cc is None or cc < cfg.CONSISTENCY_THRESHOLD:
        ded("circuit_chain_consistency", "Upstream device chains only partly agree with the mapped network.")
    for f in p["data_flags"]:
        ded("premise_flag", f"Data issue for this premise: {f.replace('_', ' ')}.")
    if p["service_type"] == "Unknown":
        ded("unknown_service_type", "Service drop type (overhead/underground) is unknown.")
    value = max(0, cfg.CONFIDENCE_START + sum(r.effect for r in reasons))
    level = next(lvl for lower, lvl in cfg.CONFIDENCE_LEVELS if value >= lower)
    return s.Confidence(level=level, points=value, reasons=reasons,
                        ceiling_note="High confidence is not offered: passing consistency checks does not prove the "
                                     "inferred network is physically correct, and there is no outage-labelled data "
                                     "to validate against.")


def assess(net: CircuitNetwork, p: dict, severity: str, gaps_on_path: int) -> s.RiskResult:
    severity = severity if severity in cfg.SEVERITY else cfg.DEFAULT_SEVERITY
    sev = cfg.SEVERITY[severity]
    common = dict(severity=severity, severity_label=sev["label"],
                  severity_options=[s.SeverityOption(id=k, label=v["label"], description=v["description"])
                                    for k, v in cfg.SEVERITY.items()])
    missing = []
    if p.get("transformer_node") is None:
        missing.append("Your service transformer could not be placed on the mapped network.")
    if "not_in_upstream_file" in p["data_flags"]:
        missing.append("Your premise has no upstream device relationship in the supplied data.")
    if missing:
        return s.RiskResult(status="insufficient_data", band=None, score=None, confidence=None, factors=[],
                            assumptions=[], missing_inputs=missing,
                            could_change=["Corrected network mapping for this premise."],
                            fallback_message=("We can't estimate a risk band for this premise from the available data. "
                                              "Prepare as you would for any storm in your area."), **common)

    feat = susceptibility(net, p)
    score = score_from(feat, severity)
    band = band_for(score)
    km = feat["km"]
    ev = feat["events"]
    factors = [
        s.RiskFactor(
            name="Overhead line that could interrupt you",
            value=f"{km['Overhead']:.1f} km",
            points=round(feat["exposure_pts"], 1), max_points=cfg.EXPOSURE_MAX_POINTS,
            explanation=("Overhead primary line whose damage would trip a protective device you depend on "
                         f"(includes your own supply path). Scored linearly up to {cfg.EXPOSURE_SATURATION_KM:g} km. "
                         f"A further {km['Underground']:.1f} km is underground and not scored as storm exposure.")),
        s.RiskFactor(
            name="Past storm events that reached your supply",
            value=f"{len(ev)} event(s)" + (f" ({', '.join(sorted(ev))})" if ev else ""),
            points=round(feat["history_pts"], 1), max_points=cfg.HISTORY_MAX_POINTS,
            explanation=("Distinct dated events in the historical damage extract with at least one damage record that "
                         "would have interrupted this premise. Records from the same event count once. This is a "
                         "proxy: the records describe damage, not confirmed customer outages.")),
        s.RiskFactor(
            name="Service drop",
            value=p["service_type"].lower(),
            points=feat["service_pts"], max_points=max(cfg.SERVICE_POINTS.values()),
            explanation="Overhead service drops are exposed to falling limbs; underground drops are not scored."),
        s.RiskFactor(
            name="Storm severity (scenario input)",
            value=sev["label"],
            points=None, max_points=None,
            explanation=(f"Multiplies the points above by {sev['factor']:g}. You chose this; it is not a weather "
                         "forecast.")),
    ]
    could_change = ["A different storm severity (try the scenario control)."]
    lowers = [lower for lower, _ in cfg.BANDS if lower > 0]
    edge = min(lowers, key=lambda b: abs(score - b))
    if abs(score - edge) <= cfg.BORDERLINE_MARGIN:
        could_change.insert(0, f"Borderline: the score is within {cfg.BORDERLINE_MARGIN} points of a band edge "
                               f"({edge}), so small changes in assumptions could change the band.")
    could_change += ["Actual storm track, wind and ice (no live weather is used).",
                     "Tree condition and vegetation management near the lines (not in the data).",
                     "Pole and equipment condition (not in the data)."]
    return s.RiskResult(
        status="calculated", band=band, score=round(score), confidence=confidence(net, p, feat, gaps_on_path),
        factors=factors,
        assumptions=["Score = (exposure + history + service points) x severity factor, capped at 100.",
                     "A fault is cleared by the nearest protective device upstream of it (simplified protection).",
                     "All overhead line in your interrupting zone is treated as equally exposed."],
        missing_inputs=["Vegetation and equipment condition are not in the data.",
                        "Pole install years exist but are not scored: nothing in this extract shows they predict damage.",
                        "No live weather or forecast data.",
                        "No confirmed historical outage records for calibration."],
        could_change=could_change, fallback_message=None, **common)
