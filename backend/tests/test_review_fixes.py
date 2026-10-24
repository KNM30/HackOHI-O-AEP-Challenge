"""Regressions for the requirements review: overall completeness, conditional lower bounds,
critical-facility priority and the crews-needed comparison."""
import json

import pytest
from fastapi.testclient import TestClient

from app import alerts, guidance
from app import schemas as s
from app.main import app
from test_restoration import REF_PATH, WB, jobs_for, run, span
from test_risk_scenarios import build, premise

pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="run pipeline/build_labor.py first")


@pytest.fixture
def ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ issue 2: overall completeness
def test_partly_modeled_jobs_make_overall_a_lower_bound(ref):
    res = run(build(), [span("C")], ref, pid="P-C", **WB)  # overhead line: re-stringing has no workbook entry
    o = res.overall
    assert o.jobs_partial == 1 and o.complete is False
    assert o.upper_h is None and o.lower_h is not None and o.modeled_work_upper_h is not None
    assert "lower bound" in o.note


def test_fully_modeled_jobs_give_a_full_overall_range(ref):
    res = run(build(), [span("C", asset="pole")], ref, pid="P-C")  # pole template is fully modeled
    o = res.overall
    assert o.jobs_partial == 0 and o.complete is True
    assert o.upper_h is not None and o.upper_h == o.modeled_work_upper_h


# ------------------------------------------------------------------ issue 3: conditional lower bounds
def test_incomplete_conditional_repair_has_no_upper_bound_anywhere(ref):
    res = run(build(), [span("E")], ref, pid="P-C", **WB)  # P-C can be isolated from overhead-line damage at E
    sel = res.selected
    assert sel.range_kind == "conditional" and sel.conditional.repair_scope_complete is False
    hi = f"{sel.conditional.if_repair_high_h:.1f}"
    assert "at least" in sel.display.split("|")[1] and hi not in sel.display.split("|")[1]
    # alerts: "at least", no upper repair time, and no planning horizon from the modeled upper time
    text = alerts.estimate_text(sel)
    assert "at least" in text and hi not in text
    assert alerts._horizon(sel) is None
    # guidance treats the outage length as open-ended
    ids = {g.id for g in guidance.select(None, sel, s.Preferences())}
    assert {"plan_long", "extreme_temps"} <= ids


def test_complete_conditional_repair_keeps_its_range(ref):
    res = run(build(), [span("E", asset="pole")], ref, pid="P-C")
    c = res.selected.conditional
    assert res.selected.range_kind == "conditional" and c.repair_scope_complete is True
    assert alerts._horizon(res.selected) == c.if_repair_high_h


# ------------------------------------------------------------------ issue 1: critical facilities
def _net_with_facility():
    net = build(extra_premises=[premise("P-C2", "C", ["F1", "REC"]), premise("P-C3", "C", ["F1", "REC"])])
    net.critical = [dict(public_id="CRF-TEST", kind="fire_station", transformer_id="XFR-P-E", rep_premise="P-E")]
    return net


def test_critical_facility_repair_goes_first_when_prioritised(ref):
    net = _net_with_facility()
    locs = [span("C"), span("E")]  # C restores 3 customers, E restores 1 customer + the fire station

    def first(**kw):
        jobs = jobs_for(net, locs, ref, crews=1, **kw)
        return min(jobs, key=lambda j: j.schedule["optimistic"][1]).trip.loc.node

    assert first(prioritize_critical=False) == "C"
    assert first(prioritize_critical=True) == "E"


def test_critical_facility_outcome_is_reported_without_location(ref):
    net = _net_with_facility()
    on = run(net, [span("C"), span("E")], ref, pid="P-C", crews=1, prioritize_critical=True, **WB)
    off = run(net, [span("C"), span("E")], ref, pid="P-C", crews=1, prioritize_critical=False, **WB)
    [f_on], [f_off] = on.critical_facilities, off.critical_facilities
    assert f_on.kind == "fire_station" and f_on.status == "repair_dependent"
    assert f_on.at_least and f_on.upper_h is None and f_on.display.startswith("at least")
    assert f_on.lower_h < f_off.lower_h  # priority restores the facility earlier
    dumped = json.dumps(f_on.model_dump())
    assert "CRF-" not in dumped and "lonlat" not in dumped and "XFR-" not in dumped


# ------------------------------------------------------------------ crews-needed comparison
def test_crew_targets_are_monotone_and_flag_incomplete_scope(ref):
    res = run(build(), [span("C"), span("E"), span("B")], ref, pid="P-C", crews=1, hours_per_day=8, **WB)
    t = res.crew_targets
    assert [x.label for x in t.targets] == ["2 days", "3 days", "1 week"]
    needs = [x.crews_needed_conservative for x in t.targets]
    assert all(n is not None for n in needs) and needs == sorted(needs, reverse=True)
    assert t.scope_complete is False and "minimums" in t.note


# ------------------------------------------------------------------ real data (Circuit 109)
client = TestClient(app)


def _sim(pid, sid, crew=None, circuit="0000109"):
    sc = next(x for x in client.get(f"/api/premises/{pid}/scenarios").json()["scenarios"] if x["id"] == sid)
    return client.post(f"/api/circuits/{circuit}/simulation", json=dict(
        premise_id=pid, scenario_id=sid, scenario_label=sc["label"], location_ids=sc["default_location_ids"],
        crew=crew or {}))


def test_circuit_109_reports_facility_types_only():
    ps = client.get("/api/circuits/0000109/premises")
    if ps.status_code != 200:
        pytest.skip("circuit 0000109 not built")
    pid = ps.json()[0]["id"]
    r = _sim(pid, "historical_replay")
    if r.status_code != 200:
        pytest.skip("no replay scenario for this premise")
    body = r.json()
    kinds = {f["kind"] for f in body["impact"]["critical_facilities"]}
    assert kinds == {"fire_station", "ambulance_station"}
    text = r.text
    for banned in ("CRF-", "Fire Station", "Rescue Squad", "ADDRESS", "match_dist"):
        assert banned not in text, banned


def test_circuit_109_priority_changes_order_on_real_data():
    """The operator-view scenario is the real-data case where facility priority changes the repair order."""
    ps = client.get("/api/circuits/0000109/premises")
    if ps.status_code != 200:
        pytest.skip("circuit 0000109 not built")
    pid = "PRM-11335E1D"  # premise sharing the fire station's transformer: the facility status is visible
    on = _sim(pid, "critical_facility", crew={"crews": 1}).json()["restoration"]
    off = _sim(pid, "critical_facility", crew={"crews": 1, "prioritize_critical": False}).json()["restoration"]
    assert on["critical_priority"]["effect"] == "changed_order"
    assert off["critical_priority"]["effect"] == "changed_order"
    assert on["critical_priority"]["hours_earlier"] > 0
    fire = lambda r: next(f for f in r["critical_facilities"] if f["kind"] == "fire_station")
    assert fire(on)["lower_h"] < fire(off)["lower_h"]
    assert "CRF-" not in json.dumps(on) and "Fire Station" not in json.dumps(on)


def test_circuit_109_replay_reports_priority_already_first():
    ps = client.get("/api/circuits/0000109/premises")
    if ps.status_code != 200:
        pytest.skip("circuit 0000109 not built")
    r = _sim("PRM-0D322A0F", "historical_replay", crew={"crews": 1}).json()["restoration"]
    assert r["critical_priority"]["effect"] == "already_first"


def test_no_priority_report_without_facilities():
    r = _sim("PRM-00770FFC", "shared_upstream", circuit="0000018").json()["restoration"]
    assert r["critical_priority"] is None


# ------------------------------------------------------------------ structure-drawing traceability
def test_every_template_task_traces_to_a_structure_drawing():
    from app import labor_config as cfg
    assert set(cfg.STRUCTURE_DRAWINGS) == set(cfg.TEMPLATES)
    not_drawn = {"recloser", "switch"}  # not shown in the sample drawings
    for name, tpl in cfg.TEMPLATES.items():
        assert (cfg.STRUCTURE_DRAWINGS[name] is None) == (name in not_drawn), name
        if name in not_drawn:
            continue
        for task_name, *_ in tpl["tasks"]:
            assert task_name in cfg.TASK_DRAWINGS, task_name


def test_drawing_reference_reaches_developer_view():
    r = _sim("PRM-00770FFC", "shared_upstream", circuit="0000018").json()["restoration"]
    dev = r["jobs"][0]["developer"]
    assert dev["structures"] and all(t["drawing"] for t in dev["tasks"])


def test_operator_view_never_locates_the_facility():
    ps = client.get("/api/circuits/0000109/premises")
    if ps.status_code != 200:
        pytest.skip("circuit 0000109 not built")
    pid = "PRM-0D322A0F"
    sc = next(x for x in client.get(f"/api/premises/{pid}/scenarios").json()["scenarios"]
              if x["id"] == "critical_facility")
    assert all(l["location"] is None for l in sc["locations"])
    for sid in ("critical_facility", "renamed"):  # a different scenario id must not reveal coordinates
        r = client.post("/api/circuits/0000109/simulation", json=dict(
            premise_id=pid, scenario_id=sid, scenario_label="x", location_ids=sc["default_location_ids"])).json()
        assert all(l["location"] is None for l in r["impact"]["active_locations"])
        assert r["impact"]["transformer_impacts"] == []


# ------------------------------------------------------------------ conductor re-stringing assumption
def test_restring_assumption_bounds_line_repairs_and_is_labelled(ref):
    from app import labor_config as cfg
    on = run(build(), [span("C")], ref, pid="P-C")
    off = run(build(), [span("C")], ref, pid="P-C", **WB)
    assert off.selected.range_kind == "lower_bound_only" and not off.selected.uses_assumption
    assert on.selected.range_kind == "bounded" and on.selected.scope_complete
    assert on.selected.uses_assumption and on.selected.workbook_only_lower_h == off.selected.lower_h
    assert on.selected.lower_h >= off.selected.lower_h  # the assumption only adds work
    [job] = on.jobs
    names = [t.name for t in job.developer.tasks]
    assert cfg.RESTRING["pull_task"] in names and job.assumed and not job.partial
    pull = next(t for t in job.developer.tasks if t.name == cfg.RESTRING["pull_task"])
    assert pull.source.startswith("team assumption")  # never presented as workbook data
    assert any("team's assumption" in r.text for r in on.selected.confidence.reasons)
    assert "assumed time for replacing damaged wire" in alerts.estimate_text(on.selected)


def test_restring_assumption_keeps_ilm_once_and_scales_with_span_length(ref):
    from app import labor_config as cfg
    net = build()
    [job] = jobs_for(net, [span("C")], ref)
    assert job.person_hours[0] == pytest.approx(job.direct[0] * 4.5)
    length_m = net.nodes["C"]["edge"]["length_m"]
    pull = next(t for t in job.tasks if t.name == cfg.RESTRING["pull_task"])
    ft = min(length_m * 3.281, cfg.RESTRING["max_span_ft"])
    assert pull.unit_hours == pytest.approx(tuple(ft / 100 * h for h in cfg.RESTRING["hours_per_100ft_per_phase"]))


def test_restring_toggle_on_real_data():
    on = _sim("PRM-00770FFC", "shared_upstream", circuit="0000018").json()["restoration"]
    off = _sim("PRM-00770FFC", "shared_upstream", crew={"restring_assumption": False}, circuit="0000018").json()["restoration"]
    assert on["selected"]["range_kind"] == "bounded" and on["overall"]["complete"] is True
    assert off["selected"]["range_kind"] == "lower_bound_only" and off["overall"]["complete"] is False
    assert on["selected"]["workbook_only_lower_h"] == off["selected"]["lower_h"]
    assert on["params"]["restring_assumption"] is True and off["params"]["restring_assumption"] is False
