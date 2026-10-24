"""Repair jobs, labor conversion, scheduling and customer ranges.

Uses the feeder from test_risk_scenarios (R-A-B-{C, D-E}, recloser at A, tap fuse at
B, single-branch switch at D) and the real workbook extract when it has been built.
"""
import copy
import json

import pytest

from app import labor_config as cfg
from app import restoration as rs
from app import schemas as s
from app.config import PROCESSED_DIR
from app.network import CircuitNetwork
from app.scenarios import Loc, Scenario, evaluate
from test_risk_scenarios import build, dev, node, premise

REF_PATH = PROCESSED_DIR / "labor_reference.json"
pytestmark = pytest.mark.skipif(not REF_PATH.exists(), reason="run pipeline/build_labor.py first")


@pytest.fixture
def ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


def span(n, asset="primary_line", access=False, special=None, rid=None):
    return Loc(public_id=rid or f"LOC-{n}", kind="span", label=n, lonlat=[0, 0], node=n, asset_type=asset,
               access_issue=access, special_equipment=special)


WB = {"restring_assumption": False}  # workbook data only: line repairs stay lower bounds


def params(**kw):
    base = dict(crews=1, crew_size=4, hours_per_day=24, access_delay_h=0.0, access_scope="reported")
    base.update(kw)
    return rs.CrewParams(**base)


def run(net, locs, ref, pid="P-C", **kw):
    scen = Scenario(id="t", label="t", description="", mode="multi", locations=locs)
    impact = evaluate(net, net.premises[pid], scen, locs)
    return rs.simulate(net, net.premises[pid], scen, params(**kw), ref, impact)


def jobs_for(net, locs, ref, **kw):
    jobs = rs.build_jobs(net, locs, rs.Labor(ref), restring=kw.get("restring_assumption", True))
    rs.attach_dependencies(net, jobs)
    rs.apply_crew_params(jobs, params(**kw))
    rs.schedule(jobs, params(**kw))
    return jobs


# ------------------------------------------------------------------ labor units
def test_workbook_values_and_separate_removal_hours(ref):
    assert ref["ilm"]["value"] == 4.5 and ref["ilm"]["cell"] == "Indirect Labor Multiplier!B1"
    medium = next(r for r in ref["categories"]["Pole"]["rows"] if r["Size Group"] == "Medium")
    assert medium["Avg Install Hours"] != medium["Avg Removal Hours"]
    lab = rs.Labor(ref)
    both, _ = lab.category("Fuse Cutout", ("install", "remove"))
    inst, _ = lab.category("Fuse Cutout", ("install",))
    assert both == pytest.approx(0.256 + 0.128) and inst == pytest.approx(0.256)


def test_ilm_applied_exactly_once(ref):
    net = build()
    [job] = jobs_for(net, [span("C")], ref)
    assert job.person_hours[0] == pytest.approx(job.direct[0] * 4.5)
    assert job.person_hours[1] == pytest.approx(job.direct[1] * 4.5)
    # crew inputs change elapsed time, never the effort
    [job8] = jobs_for(net, [span("C")], ref, crew_size=8, crews=5, access_delay_h=10, access_scope="all")
    assert job8.person_hours == job.person_hours and job8.direct == job.direct


def test_access_adder_is_labor_but_delay_is_waiting(ref):
    net = build()
    [plain] = jobs_for(net, [span("C")], ref)
    [adder] = jobs_for(net, [span("C", access=True)], ref)
    assert adder.direct[0] - plain.direct[0] == pytest.approx(0.5)            # Restricted Access Work
    assert adder.person_hours[0] - plain.person_hours[0] == pytest.approx(2.25)  # x 4.5 once
    [delayed] = jobs_for(net, [span("C", access=True)], ref, access_delay_h=6)
    assert delayed.person_hours == adder.person_hours                          # waiting is not labor
    for b in ("optimistic", "conservative"):
        assert delayed.schedule[b][2] - adder.schedule[b][2] == pytest.approx(6.0)  # not multiplied


def test_access_delay_scope(ref):
    net = build()
    [j] = jobs_for(net, [span("C")], ref, access_delay_h=6, access_scope="reported")
    assert j.waits["access"] == (0.0, 0.0)
    [j] = jobs_for(net, [span("C")], ref, access_delay_h=6, access_scope="all")
    assert j.waits["access"] == (6.0, 6.0)


def test_no_excavation_or_valueless_adders(ref):
    net = build()
    jobs = jobs_for(net, [span("C", asset="pole", access=True), span("D", access=True, special="Backyard Bucket")], ref)
    names = {a[0] for j in jobs for a in j.adders}
    assert not names & {"Hand Dig", "Rock Hole", "Junction Pole Work", "Access Constraint Adder"}
    assert names == {"Difficult Location", "Backyard Adder"}


def test_line_damage_is_not_a_pole(ref):
    net = build()
    [job] = jobs_for(net, [span("C")], ref, **WB)
    assert job.templates == ["overhead_conductor"] and all("Pole" not in t.name for t in job.tasks)
    assert job.partial  # conductor re-stringing is not in the workbook: flagged


def test_duplicate_records_make_one_job(ref):
    net = build()
    single = jobs_for(net, [span("C", rid="R1")], ref)
    dup = jobs_for(net, [span("C", rid="R1"), span("C", rid="R2"), span("C", rid="R3")], ref)
    assert len(dup) == 1 and dup[0].direct == single[0].direct and len(dup[0].locs) == 3


def test_pole_and_line_at_one_location_share_splices(ref):
    net = build()
    [both] = jobs_for(net, [span("C", asset="pole"), span("C")], ref)
    assert "Re-attach conductor" not in [t.name for t in both.tasks]


def test_missing_labor_value_is_not_zero(ref):
    broken = copy.deepcopy(ref)
    for r in broken["categories"]["Insulator"]["rows"]:
        r["Avg Removal Hours"] = None
    net = build()
    res = run(net, [span("C")], broken)
    job = res.jobs[0]
    assert not job.supported and any("not treated as zero" in p for p in job.problems)
    assert res.selected.lower_h is None and res.selected.upper_h is None
    assert "Insufficient information" in res.selected.headline


def test_unsupported_underground_gives_explicit_fallback(ref):
    net = build()
    net.nodes["C"]["edge"]["mounting"] = "Underground"
    res = run(net, [span("C")], ref)
    assert res.jobs[0].supported is False and res.selected.lower_h is None
    assert not res.overall.complete


# ------------------------------------------------------------------ scheduling
def test_workday_windows():
    assert rs.next_work_time(17, 16) == 24
    assert rs.next_work_time(10, 16) == 10
    assert rs.finish_time(15, 3, 16) == pytest.approx(26)   # 1 h today, 2 h next day
    assert rs.finish_time(0, 40, 16) == pytest.approx(24 * 2 + 8)
    assert rs.finish_time(5, 3, 24) == 8


def test_one_crew_is_sequential_two_crews_parallel(ref):
    net = build()
    locs = [span("C"), span("E")]
    one = jobs_for(net, locs, ref, crews=1)
    two = jobs_for(net, locs, ref, crews=2)
    s1 = sorted(j.schedule["optimistic"][1:] for j in one)
    s2 = sorted(j.schedule["optimistic"][1:] for j in two)
    assert s1[1][0] == pytest.approx(s1[0][1])            # second starts when first ends
    assert s2[0][0] == pytest.approx(s2[1][0])            # both start together


def test_crew_size_capped_and_minimum_enforced(ref):
    net = build()
    [j4] = jobs_for(net, [span("C")], ref, crew_size=4)
    [j8] = jobs_for(net, [span("C")], ref, crew_size=8)
    assert j4.work_hours == j8.work_hours                 # line repair useful max is 4 people
    [pole2] = jobs_for(net, [span("C", asset="pole")], ref, crew_size=2)
    assert pole2.infeasible and not pole2.schedule        # pole setting needs >= 3


def test_effort_counts_jobs_a_small_crew_cannot_take(ref):
    net = build()
    locs = [span("C", asset="pole"), span("E")]
    four = run(net, locs, ref, crew_size=4)
    two = run(net, locs, ref, crew_size=2)
    assert two.overall.jobs_infeasible == 1 and not two.overall.complete
    assert two.overall.person_hours_high == four.overall.person_hours_high


def test_priority_prefers_more_customers_per_hour(ref):
    net = build()
    jobs = jobs_for(net, [span("C"), span("B")], ref, crews=1)  # B blocks 3 customers, C blocks 1
    first = min(jobs, key=lambda j: j.schedule["optimistic"][1])
    assert first.trip.loc.node == "B"


# ------------------------------------------------------------------ customer ranges
def test_customer_range_vs_overall_completion(ref):
    net = build()
    res = run(net, [span("C"), span("E")], ref, pid="P-C", crews=1)
    assert res.selected.status == "repair_dependent"
    assert res.selected.upper_h <= res.overall.modeled_work_upper_h
    assert res.selected.lower_h <= res.selected.upper_h


def test_multiple_faults_prevent_premature_restoration(ref):
    net = build()
    alone = run(net, [span("C")], ref, pid="P-C", crews=1)
    both = run(net, [span("C"), span("B")], ref, pid="P-C", crews=1)  # second fault also on P-C's path
    assert both.selected.upper_h > alone.selected.upper_h
    assert len(both.selected.controlling_jobs) >= 1


def test_isolation_range_is_not_a_short_promise(ref):
    net = build()
    res = run(net, [span("E")], ref, pid="P-C")
    sel = res.selected
    assert sel.basis == "isolation"
    assert sel.lower_h == pytest.approx(cfg.ASSESSMENT_H[0] + cfg.SWITCHING_H_PER_SWITCH[0] + cfg.REENERGIZE_H[0])
    assert sel.upper_h > sel.lower_h  # conservative end = repair-based


def test_isolation_blocked_by_second_fault_on_path(ref):
    net = build()
    res = run(net, [span("E"), span("C")], ref, pid="P-C")
    assert res.selected.basis == "repair" and res.selected.status == "repair_dependent"


def test_unaffected_premise_has_no_range(ref):
    net = build()
    res = run(net, [span("C")], ref, pid="P-D")
    assert res.selected.status == "not_interrupted" and res.selected.lower_h is None


def test_fixed_scenario_same_jobs_for_every_premise(ref):
    net = build()
    locs = [span("C"), span("E")]
    a = run(net, locs, ref, pid="P-C", crews=2)
    b = run(net, locs, ref, pid="P-D", crews=2)
    assert [j.model_dump() for j in a.jobs] == [j.model_dump() for j in b.jobs]
    assert a.overall == b.overall


# ------------------------------------------------------------------ protection review
def test_sectionalizer_needs_an_evidenced_recloser_above():
    base = build()
    model = copy.deepcopy(base.model)
    model["devices"]["SEC"] = dev("SEC", "sectionalizer", "D", ["E"], 1)
    model["premises"][2]["chain"] = ["SEC", "REC"]
    with_rec = CircuitNetwork(copy.deepcopy(model))
    assert with_rec.protecting_device("E")["public_id"] == "SEC"
    model["devices"]["REC"]["zone_premise_count"] = 0  # no evidenced recloser above
    no_rec = CircuitNetwork(model)
    dev_, skipped = no_rec.protection_detail("E")
    assert dev_ is None and {d["public_id"] for d in skipped} >= {"SEC"}


def test_skipped_device_marks_protection_uncertain(ref):
    net = build()  # unevidenced recloser U sits at D covering E
    res = run(net, [span("E")], ref, pid="P-E")
    assert res.jobs[0].protection_uncertain
    assert any("not in the customer dependency file" in w for w in res.warnings)
