"""Explainable pre-storm outage risk for a premise.

Primary method: a logistic model fitted on every circuit and validated by leaving out whole
storms (pipeline/build_risk_model.py -> risk_model.json). It gives a recalibrated chance with a
90% interval. If that file is missing, the original heuristic band is used instead; it is also
the baseline the fitted model is compared with. See docs/risk_model.md.
"""
from __future__ import annotations

import math
from bisect import bisect_left

from . import data_store
from . import risk_config as cfg
from . import schemas as s
from .network import CircuitNetwork

_LOADED = object()  # assess(model=...) default: use data/processed/risk_model.json when present


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


def model_inputs(net: CircuitNetwork, p: dict) -> dict | None:
    """Network features of the fitted model, or None when the premise cannot be placed."""
    if p.get("transformer_node") not in net.nodes or "not_in_upstream_file" in p["data_flags"]:
        return None
    return dict(overhead_km=net.interrupting_km(p)["Overhead"], protect_depth=len(p["chain"]),
                overhead_service=cfg.OVERHEAD_SERVICE_VALUE.get(p["service_type"], 0.5),
                service_type=p["service_type"])


def event_hits(net: CircuitNetwork, p: dict, date_to_event: dict[str, str]) -> set[str]:
    """Territory-wide storm events in which at least one damage record would have interrupted p.

    Same rule as the history factor (relation().affects_premise), but events are grouped across
    the whole territory so they line up with the events the model was trained on.
    """
    out = set()
    for d in net.damage:
        ev = date_to_event.get(d.get("report_date"))
        if ev is None or ev in out:
            continue
        rel = net.relation(p, d)
        if rel is not None and rel.affects_premise:
            out.add(ev)
    return out


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


def _data_deductions(net: CircuitNetwork, p: dict, km: dict, approx_history: int, gaps: int,
                     ded) -> None:
    """Evidence problems that lower confidence for either method."""
    ded("inferred_feeder_head", "The substation connection point is inferred from the device hierarchy.")
    if gaps:
        ded("gap_on_path", f"{gaps} short mapping gap(s) on your supply path were joined by proximity.", min(gaps, 2))
    if any((net.devices[c].get("coverage_method") == "all_children_assumed") for c in p["chain"]):
        ded("assumed_coverage_in_chain", "Which branches one of your protective devices covers is assumed, "
                                         "not evidenced.")
    total = sum(km.values())
    if total and km["Unknown"] / total > cfg.UNKNOWN_MOUNTING_SHARE:
        ded("unknown_mounting_share", "Part of the line that could interrupt you has unknown overhead/underground "
                                      "status.")
    if approx_history:
        ded("approximate_history", f"{approx_history} historical record(s) behind your history signal were "
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


def confidence(net: CircuitNetwork, p: dict, feat: dict, gaps: int) -> s.Confidence:
    d = cfg.CONFIDENCE_DEDUCTIONS
    reasons: list[s.ConfidenceReason] = []

    def ded(key: str, text: str, times: int = 1):
        reasons.append(s.ConfidenceReason(effect=-d[key] * times, text=text))

    ded("no_validation", "No confirmed-outage records are available to validate the score; it is a heuristic.")
    _data_deductions(net, p, feat["km"], feat["approx_history"], gaps, ded)
    value = max(0, cfg.CONFIDENCE_START + sum(r.effect for r in reasons))
    level = next(lvl for lower, lvl in cfg.CONFIDENCE_LEVELS if value >= lower)
    return s.Confidence(level=level, points=value, reasons=reasons,
                        ceiling_note="High confidence is not offered: passing consistency checks does not prove the "
                                     "inferred network is physically correct, and there is no outage-labelled data "
                                     "to validate against.")


def assess(net: CircuitNetwork, p: dict, severity: str, gaps_on_path: int, model=_LOADED) -> s.RiskResult:
    severity = severity if severity in cfg.SEVERITY else cfg.DEFAULT_SEVERITY
    if model is _LOADED:
        model = data_store.risk_model()
    sev = cfg.SEVERITY[severity]
    common = dict(severity=severity, severity_label=sev["label"],
                  severity_options=[s.SeverityOption(id=k, label=cfg.SEVERITY[k]["label"],
                                                     description=_severity_description(k, model))
                                    for k in cfg.SEVERITY],
                  method="fitted_model" if model else "heuristic")
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
    if model:
        return _assess_fitted(net, p, severity, gaps_on_path, model, common)
    return _assess_heuristic(net, p, severity, gaps_on_path, common)


def _assess_heuristic(net: CircuitNetwork, p: dict, severity: str, gaps_on_path: int, common: dict) -> s.RiskResult:
    sev = cfg.SEVERITY[severity]
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


# ------------------------------------------------------------------ fitted model
def storm_size(severity: str, model: dict) -> int:
    """Territory-wide damage records the severity scenario stands for (a real past storm when it has one)."""
    sev = cfg.SEVERITY[severity]
    ev = sev.get("analog_event")
    return int(model["event_sizes"][ev]) if ev and ev in model["event_sizes"] else int(sev["storm_size"])


def _severity_description(severity: str, model: dict | None) -> str:
    sev = cfg.SEVERITY[severity]
    if not model:
        return sev["description"]
    return f"{sev['description']} Sized like {sev['analog']}: about {storm_size(severity, model):,} damage reports."


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _calibrated(model: dict, raw_logit: float) -> float:
    pl = model["platt"]
    return _sigmoid(pl["a"] + pl["b"] * raw_logit)


def _prob_band(prob: float) -> str:
    return next(b for lower, b in cfg.PROB_BANDS if prob >= lower)


def pct(x: float) -> str:
    if x < 0.01:
        return "under 1%"
    if x > 0.99:
        return "over 99%"
    return f"{x * 100:.0f}%"


def _percentile(model: dict, km: float) -> int:
    """Share of premises in the service area with less interrupting overhead line (0-99)."""
    return min(99, max(0, bisect_left(model["exposure_km_percentiles"], km) - 1))


def _confidence_fitted(net, p, km, approx_history, gaps, bands_spanned: int, lo: float, hi: float) -> s.Confidence:
    d = cfg.CONFIDENCE_DEDUCTIONS
    reasons: list[s.ConfidenceReason] = []

    def ded(key: str, text: str, times: int = 1):
        reasons.append(s.ConfidenceReason(effect=-d[key] * times, text=text))

    spread = cfg.INTERVAL_BAND_DEDUCTION[bands_spanned]
    reasons.append(s.ConfidenceReason(
        effect=-spread,
        text=(f"The 90% range for your chance ({pct(lo)} to {pct(hi)}) stays within one risk band." if spread == 0 else
              f"The 90% range for your chance ({pct(lo)} to {pct(hi)}) spans {bands_spanned} risk bands, mostly "
              "because storms of the same size have affected different areas.")))
    _data_deductions(net, p, km, approx_history, gaps, ded)
    value = max(0, cfg.CONFIDENCE_START + sum(r.effect for r in reasons))
    level = next(lvl for lower, lvl in cfg.CONFIDENCE_LEVELS_FITTED if value >= lower)
    return s.Confidence(level=level, points=value, reasons=reasons,
                        ceiling_note=("Confidence reflects the width of the 90% range and known data problems. The "
                                      "model's labels are a damage-based proxy for outages, not confirmed outages."))


def model_card(model: dict) -> s.RiskModelCard:
    v, tr = model["validation"], model["training"]
    return s.RiskModelCard(
        label_definition=model["label_definition"], training_premises=tr["premises"],
        training_circuits=tr["circuits"], training_storms=tr["storms"],
        pooled_auc=round(v["pooled_auc"], 3), within_storm_auc=round(v["mean_auc_within_storm"], 3),
        heuristic_within_storm_auc=round(v["mean_auc_heuristic_within_storm"], 3),
        calibration=[s.CalibrationRow(**r) for r in v["calibration_recalibrated"]],
        notes=[
            "Every number here comes from leaving one whole storm out, fitting on the rest, and scoring the storm "
            "the model had not seen.",
            f"Ranking across all storms (AUC {v['pooled_auc']:.2f}) is high mainly because storm size is known in "
            f"advance. Ranking premises within one storm is modest (AUC {v['mean_auc_within_storm']:.2f}; the "
            f"earlier hand-weighted score reached {v['mean_auc_heuristic_within_storm']:.2f}).",
            "So storm size sets the level, and your place on the network moves it up or down.",
            v["recalibration_note"],
        ])


def _assess_fitted(net: CircuitNetwork, p: dict, severity: str, gaps_on_path: int, model: dict,
                   common: dict) -> s.RiskResult:
    sev = cfg.SEVERITY[severity]
    inp = model_inputs(net, p)
    events = model["events"]
    hit = event_hits(net, p, model["date_to_event"]) & set(events)
    size = storm_size(severity, model)
    raw = {"log_storm_size": math.log(size), "log_exposure_km": math.log1p(inp["overhead_km"]),
           "hist_rate": len(hit) / len(events), "protect_depth": float(inp["protect_depth"]),
           "overhead_service": inp["overhead_service"]}
    feats = model["features"]
    z = [(raw[f] - mu) / sd for f, mu, sd in zip(feats, model["mu"], model["sd"])]
    lg = model["intercept"] + sum(c * zj for c, zj in zip(model["coef"], z))
    zi = [1.0, *z]
    cov = model["cov"]
    var = sum(zi[a] * cov[a][b] * zi[b] for a in range(len(zi)) for b in range(len(zi)))
    se = math.sqrt(max(var, 0.0) + model["event_sigma"] ** 2)
    prob = _calibrated(model, lg)
    lo, hi = _calibrated(model, lg - cfg.INTERVAL_Z * se), _calibrated(model, lg + cfg.INTERVAL_Z * se)
    band = _prob_band(prob)
    order = [b for _, b in reversed(cfg.PROB_BANDS)]
    spanned = order.index(_prob_band(hi)) - order.index(_prob_band(lo)) + 1

    def effect(f: str) -> float:
        """Percentage-point change against an average premise (this feature at the service-area mean)."""
        j = feats.index(f)
        return round(100 * (prob - _calibrated(model, lg - model["coef"][j] * z[j])), 1)

    def direction(pp: float) -> str:
        return "raises" if pp >= 0.5 else "lowers" if pp <= -0.5 else "neutral"

    km = net.interrupting_km(p)
    avg_depth = model["mu"][feats.index("protect_depth")]
    _, approx = _historical_events(net, p)
    factors = []
    for f, name, value, expl in [
        ("log_exposure_km", "Overhead line that could interrupt you",
         f"{km['Overhead']:.1f} km, more than {_percentile(model, inp['overhead_km'])}% of premises in the service area",
         "Overhead primary line whose damage would trip a protective device you depend on, including your own supply "
         "path. More line means more places a tree or wind can cut you off."),
        ("hist_rate", "Past storms that reached your supply",
         f"{len(hit)} of the {len(events)} storms studied" + (f" ({', '.join(sorted(hit))})" if hit else ""),
         "Storms in the damage records with at least one record that would have interrupted you. The records describe "
         "damage, not confirmed outages."),
        ("protect_depth", "Protective devices between you and the substation",
         f"{inp['protect_depth']} (service-area average {avg_depth:.1f})",
         "Each fuse or recloser on your path marks another section of line whose damage can cut you off. Premises far "
         "out on branch lines have more of them."),
        ("overhead_service", "Service drop", p["service_type"].lower(),
         "An overhead drop from the transformer to your home is exposed to falling limbs; an underground one is not."),
    ]:
        pp = effect(f)
        factors.append(s.RiskFactor(name=name, value=value, points=pp, max_points=None, direction=direction(pp),
                                    explanation=f"{expl} Effect on your chance: {pp:+.1f} percentage points against "
                                                "an average premise."))
    factors.append(s.RiskFactor(
        name="Storm size (scenario input)", value=f"about {size:,} damage reports area-wide, like {sev['analog']}",
        points=None, max_points=None, direction=None,
        explanation="You chose this; it is not a weather forecast. Storm size is the strongest factor in the model."))
    could_change = ["A different storm size (try the severity control)."]
    for lower, _ in cfg.PROB_BANDS:
        if lower > 0 and lower / cfg.PROB_BORDERLINE_RATIO <= prob <= lower * cfg.PROB_BORDERLINE_RATIO:
            could_change.insert(0, f"Borderline: your chance is close to the {pct(lower)} band edge, so small "
                                   "changes in assumptions could change the band.")
    could_change += ["Where the storm actually hits: storms of the same size have affected very different areas.",
                     "Tree condition and vegetation management near the lines (not in the data).",
                     "Pole and equipment condition (not in the data)."]
    return s.RiskResult(
        status="calculated", band=band, score=None, probability=round(prob, 4), probability_low=round(lo, 4),
        probability_high=round(hi, 4), score_note="", model_card=model_card(model),
        confidence=_confidence_fitted(net, p, km, approx, gaps_on_path, spanned, lo, hi),
        factors=factors,
        assumptions=[f"Chance that storm damage cuts your supply in a storm of this size, from a logistic model fitted "
                     f"on {model['training']['premises']:,} premises and {model['training']['storms']} past storms.",
                     "A fault is cleared by the nearest protective device upstream of it (simplified protection).",
                     "Bands: low under 5%, moderate 5% to 15%, high 15% or more.",
                     "The 90% range combines model uncertainty with storm-to-storm variation the model cannot explain."],
        missing_inputs=["No live weather, storm track or forecast: storm size stands in for the storm.",
                        "Vegetation and equipment condition are not in the data.",
                        "The training labels are damage records reaching your supply, not confirmed outages.",
                        "Pole install years are not used: a teammate's version of this model tested them and found "
                        "no gain."],
        could_change=could_change, fallback_message=None, **common)
