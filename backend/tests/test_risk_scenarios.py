"""Risk monotonicity / fallbacks and scenario impact on a hand-built feeder.

        R (root, breaker)
        |
        A ---- recloser REC at A protects A->B and below
        |
        B ---- fuse F1 at B protects only the tap B->C
       / \\
      C   D ---- switch S at D (single outgoing span) on D->E
          |      unevidenced recloser U at D (in no premise chain)
          E
   transformers: XC at C (P-C), XD at D (P-D), XE at E (P-E)
"""
import copy

import pytest

from app import data_store, risk, risk_config
from app.network import CircuitNetwork
from app.scenarios import Loc, Scenario, evaluate

EDGE = dict(length_m=1000.0, mounting="Overhead", usage="Primary", bridge=False, segs=[])


def node(parent, tin, tout, lonlat=(0, 0)):
    return dict(parent=parent, depth=0, dist_m=0, tin=tin, tout=tout, lonlat=list(lonlat),
                edge=None if parent is None else dict(EDGE), pole=None)


def dev(pid, kind, at, coverage, zone, method="zone_transformers", state=None):
    return dict(public_id=pid, kind=kind, device_type=kind.title(), node=at, coverage=coverage,
                zone_premise_count=zone, coverage_method=method, normal_state=state)


def premise(pid, xf_node, chain, service="Overhead", flags=()):
    return dict(public_id=pid, transformer_id=f"XFR-{pid}", transformer_node=xf_node, chain=chain,
                service_type=service, meters="single", lonlat=[0.0, 0.0], data_flags=list(flags))


def build(with_switch=True, extra_premises=(), damage=()):
    nodes = {"R": node(None, 0, 11), "A": node("R", 1, 10), "B": node("A", 2, 9),
             "C": node("B", 3, 4), "D": node("B", 5, 8), "E": node("D", 6, 7)}
    devices = {"REC": dev("REC", "recloser", "A", ["B"], 3), "F1": dev("F1", "fuse", "B", ["C"], 1),
               "U": dev("U", "recloser", "D", ["E"], 0, method="all_children_assumed")}
    if with_switch:
        devices["S"] = dev("S", "switch", "D", ["E"], 0, method="all_children_assumed", state="Closed")
    prem = [premise("P-C", "C", ["F1", "REC"]), premise("P-D", "D", ["REC"], service="Underground"),
            premise("P-E", "E", ["REC"]), *extra_premises]
    model = dict(circuit_id="T", label="Test", nodes=nodes, devices=devices, transformers={}, premises=prem,
                 damage=list(damage), root="R",
                 stats=dict(root_consistency=1.0, chain_consistency=1.0))
    return CircuitNetwork(copy.deepcopy(model))


def span(node_id):
    return Loc(public_id=f"LOC-{node_id}", kind="span", label=node_id, lonlat=[0, 0], node=node_id)


def run(net, *locs, pid="P-C"):
    scen = Scenario(id="t", label="t", description="", mode="multi", locations=list(locs))
    return evaluate(net, net.premises[pid], scen, list(locs))


# ------------------------------------------------------------------ risk (heuristic fallback: model=None)
SEVERITIES = list(risk_config.SEVERITY)  # ordered from minor to severe


def test_severity_factors_increase():
    factors = [risk_config.SEVERITY[k]["factor"] for k in SEVERITIES]
    assert factors == sorted(factors) and len(set(factors)) == len(SEVERITIES)


def test_higher_severity_never_lowers_risk():
    net = build()
    order = {"low": 0, "moderate": 1, "high": 2}
    for p in net.premises.values():
        res = [risk.assess(net, p, sev, 0, model=None) for sev in SEVERITIES]
        scores = [r.score for r in res]
        assert scores == sorted(scores)
        assert [order[r.band] for r in res] == sorted(order[r.band] for r in res)


def test_identical_features_give_identical_results():
    twin = premise("P-E2", "E", ["REC"])
    net = build(extra_premises=[twin])
    a = risk.assess(net, net.premises["P-E"], "moderate", 0, model=None)
    b = risk.assess(net, net.premises["P-E2"], "moderate", 0, model=None)
    assert (a.score, a.band, a.confidence.points) == (b.score, b.band, b.confidence.points)


def test_score_is_never_a_probability_and_confidence_is_separate():
    net = build()
    r = risk.assess(net, net.premises["P-C"], "severe", 0, model=None)
    assert r.kind == "pre_storm_risk" and r.method == "heuristic" and "Not a probability" in r.score_note
    assert 0 <= r.score <= 100 and r.confidence.level in ("moderate", "low")
    # a premise-level data flag lowers confidence but not the score
    flagged = build(extra_premises=[premise("P-F", "C", ["F1", "REC"], flags=["customer_layer_transformer_differs"])])
    rf = risk.assess(flagged, flagged.premises["P-F"], "severe", 0, model=None)
    rc = risk.assess(flagged, flagged.premises["P-C"], "severe", 0, model=None)
    assert rf.score == rc.score and rf.confidence.points < rc.confidence.points


def test_missing_network_placement_returns_fallback():
    net = build(extra_premises=[premise("P-X", None, [], flags=["transformer_not_on_oriented_network"])])
    r = risk.assess(net, net.premises["P-X"], "severe", 0)
    assert r.status == "insufficient_data" and r.band is None and r.score is None and r.fallback_message


def test_approximate_history_lowers_confidence():
    rec = dict(public_id="DMG-1", report_date="2025-02-14", match_status="matched", matched_layer="primary",
               node="B", matched_ref=None, match_method="nearest_primary", match_dist_m=0.0)
    exact = build(damage=[rec])
    approx = build(damage=[dict(rec, label_fallback=True)])
    pe, pa = exact.premises["P-C"], approx.premises["P-C"]
    for model in (None, data_store.risk_model()):
        assert risk.assess(exact, pe, "moderate", 0, model=model).confidence.points >             risk.assess(approx, pa, "moderate", 0, model=model).confidence.points


# ------------------------------------------------------------------ risk (fitted model)
needs_model = pytest.mark.skipif(data_store.risk_model() is None, reason="run pipeline/build_risk_model.py first")


@needs_model
def test_fitted_chance_rises_with_storm_size_and_interval_contains_it():
    net, model = build(), data_store.risk_model()
    order = {"low": 0, "moderate": 1, "high": 2}
    for p in net.premises.values():
        res = [risk.assess(net, p, sev, 0, model=model) for sev in SEVERITIES]
        if res[0].status != "calculated":
            continue
        probs = [r.probability for r in res]
        assert probs == sorted(probs) and len(set(probs)) == len(probs)
        assert [order[r.band] for r in res] == sorted(order[r.band] for r in res)
        for r in res:
            assert r.method == "fitted_model" and r.score is None
            assert 0 < r.probability_low <= r.probability <= r.probability_high < 1


@needs_model
def test_fitted_band_follows_documented_thresholds():
    for prob, band in [(0.01, "low"), (0.049, "low"), (0.05, "moderate"), (0.149, "moderate"), (0.15, "high")]:
        assert risk._prob_band(prob) == band


@needs_model
def test_fitted_data_flag_lowers_confidence_not_chance():
    model = data_store.risk_model()
    flagged = build(extra_premises=[premise("P-F", "C", ["F1", "REC"], flags=["customer_layer_transformer_differs"])])
    rf = risk.assess(flagged, flagged.premises["P-F"], "severe", 0, model=model)
    rc = risk.assess(flagged, flagged.premises["P-C"], "severe", 0, model=model)
    assert rf.probability == rc.probability and rf.confidence.points < rc.confidence.points


@needs_model
def test_fitted_confidence_tracks_interval_spread():
    """Confidence is no longer constant: a narrow interval inside one band scores higher than a wide one."""
    net, model = build(), data_store.risk_model()
    p = net.premises["P-C"]
    small, big = (risk.assess(net, p, sev, 0, model=model) for sev in ("minor", "major"))
    assert small.confidence.points > big.confidence.points
    assert {small.confidence.level, big.confidence.level} != {small.confidence.level}


@needs_model
def test_model_card_reports_held_out_storm_validation():
    card = risk.model_card(data_store.risk_model())
    assert card.training_storms >= 10 and card.training_premises > 50_000
    assert 0.5 < card.within_storm_auc < card.pooled_auc <= 1
    assert any("storm size" in n for n in card.notes)


# ------------------------------------------------------------------ protection / impact
def test_switch_and_unevidenced_device_do_not_clear_faults():
    net = build()
    assert net.protecting_device("E")["public_id"] == "REC"


def test_shared_upstream_damage_interrupts_everyone_downstream():
    r = run(build(), span("B"))
    assert (r.initially_interrupted, r.repair_dependent, r.isolation_candidates) == (3, 3, 0)
    assert r.selected_premise.status == "repair_dependent"


def test_local_branch_damage_stays_on_the_branch():
    r = run(build(), span("C"))
    assert (r.initially_interrupted, r.repair_dependent, r.not_interrupted) == (1, 1, 2)
    other = run(build(), span("C"), pid="P-D")
    assert other.selected_premise.status == "not_interrupted"


def test_side_branch_isolation_needs_a_mapped_switch():
    with_sw = run(build(with_switch=True), span("E"))
    assert with_sw.repair_dependent == 1 and with_sw.isolation_candidates == 2
    assert with_sw.selected_premise.status == "isolation_candidate"
    without = run(build(with_switch=False), span("E"))
    assert without.isolation_candidates == 0 and without.unresolved == 2
    assert without.selected_premise.status == "unresolved"


def test_open_or_ambiguous_switch_is_not_used():
    net = build()
    net.devices["S"]["normal_state"] = "Open"
    assert run(net, span("E")).isolation_candidates == 0


def test_multiple_damage_takes_worst_status():
    r = run(build(), span("C"), span("E"))
    statuses = {pid: s for pid, s in [("P-C", run(build(), span("C"), span("E")).selected_premise.status),
                                      ("P-D", run(build(), span("C"), span("E"), pid="P-D").selected_premise.status)]}
    assert statuses == {"P-C": "repair_dependent", "P-D": "isolation_candidate"}
    assert r.repair_dependent == 2 and r.isolation_candidates == 1


def test_unplaced_premise_in_tripped_zone_is_unresolved():
    net = build(extra_premises=[premise("P-X", None, ["REC"])])
    r = run(net, span("E"), pid="P-X")
    assert r.selected_premise.status == "unresolved"


def test_transformer_damage_is_local():
    net = build()
    loc = Loc(public_id="LOC-X", kind="transformer", label="x", lonlat=[0, 0], transformer_id="XFR-P-D")
    r = run(net, loc, pid="P-D")
    assert r.initially_interrupted == 1 and r.selected_premise.status == "repair_dependent"
