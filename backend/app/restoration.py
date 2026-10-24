"""Repair jobs, labor conversion, deterministic crew scheduling and restoration ranges.

All times are hours elapsed from the start of the simulated response (t = 0), not
clock times. Ranges come from an optimistic and a conservative bound; they are
scenario bounds, not statistical confidence intervals. See docs/restoration_model.md.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from . import labor_config as cfg
from . import schemas as s
from .network import CircuitNetwork
from .scenarios import Loc, Scenario, Trip, premise_status, trip_for

BOUNDS = ("optimistic", "conservative")
B = {"optimistic": 0, "conservative": 1}


@dataclass
class CrewParams:
    crews: int
    crew_size: int
    hours_per_day: float
    access_delay_h: float
    access_scope: str  # "reported" | "all"
    prioritize_critical: bool = True
    restring_assumption: bool = True


@dataclass
class Task:
    name: str
    source: str  # human-readable workbook reference (developer view)
    unit_hours: tuple[float, float] | None  # per unit, install+removal as applicable; None = missing
    qty: tuple[float, float]
    drawing: str | None = None  # structure_drawings.pdf page / D.S. assembly reference


@dataclass
class Job:
    id: str
    key: tuple
    label: str
    asset: str
    locs: list[Loc]
    trip: Trip
    templates: list[str] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    adders: list[tuple[str, float, str]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)  # team assumptions filling a workbook gap
    notes: list[str] = field(default_factory=list)
    crew_min: int = 2
    crew_useful_max: int = 2
    material_wait: bool = False
    access_issue: bool = False
    status_of: dict[str, str] = field(default_factory=dict)
    blocked: set[str] = field(default_factory=set)
    critical: list[dict] = field(default_factory=list)  # critical facilities waiting on this repair
    direct: tuple[float, float] = (0.0, 0.0)
    person_hours: tuple[float, float] = (0.0, 0.0)
    work_hours: tuple[float, float] | None = None  # elapsed working hours for the assigned crew size
    ready: tuple[float, float] = (0.0, 0.0)
    waits: dict[str, tuple[float, float]] = field(default_factory=dict)
    infeasible: str | None = None
    schedule: dict[str, tuple[int, float, float]] = field(default_factory=dict)  # bound -> (crew, start, end)

    @property
    def schedulable(self) -> bool:
        return not self.unsupported and self.infeasible is None


# ------------------------------------------------------------------ labor lookups
class Labor:
    def __init__(self, ref: dict):
        self.ref = ref
        self.ilm = ref["ilm"]["value"]
        self.ilm_cell = ref["ilm"]["cell"]
        self.cat = ref["categories"]
        self.only = {r["original_intent"]: r for r in ref["labor_only"]}

    def _row_hours(self, row: dict, actions) -> float | None:
        total = 0.0
        for a in actions:
            v = row.get("Avg Install Hours" if a == "install" else "Avg Removal Hours")
            if not isinstance(v, (int, float)):
                return None  # missing value is never treated as zero
            total += v
        return total

    def category(self, name: str, actions) -> tuple[float | None, str]:
        t = self.cat.get(name)
        if not t or not t["rows"]:
            return None, f"{name}: not in workbook"
        row = t["rows"][0]
        cells = "/".join(row.get(f"{c} cell", "?") for c in
                         (["Avg Install Hours"] if "install" in actions else []) +
                         (["Avg Removal Hours"] if "remove" in actions else []))
        return self._row_hours(row, actions), f"{t['sheet']}!{cells} ({name})"

    def connectors(self, actions) -> tuple[float | None, str]:
        avg = self.ref["connectors"]["average"]
        h = (avg["install"] if "install" in actions else 0) + (avg["removal"] if "remove" in actions else 0)
        return h, f"{avg['cells']} (connector average, {avg['count']} CUs)"

    def pole(self, height_ft: float | None, actions) -> tuple[tuple[float, float] | None, str]:
        rows = {r["Size Group"]: r for r in self.cat["Pole"]["rows"]}
        sheet = self.cat["Pole"]["sheet"]
        if height_ft is None:
            lo, hi = self._row_hours(rows["Small"], actions), self._row_hours(rows["Large"], actions)
            return (None if lo is None or hi is None else (lo, hi)), \
                f"{sheet}!C12:D14 (pole height unknown: Small..Large class)"
        cls = next(c for limit, c in cfg.POLE_CLASS if height_ft <= limit)
        h = self._row_hours(rows[cls], actions)
        return (None if h is None else (h, h)), f"{sheet}!C{rows[cls]['row']}:D{rows[cls]['row']} ({cls}, {height_ft:g} ft)"

    def transformer(self, kva: float | None, actions) -> tuple[tuple[float, float] | None, str]:
        rows = sorted(self.cat["Transformer"]["rows"], key=lambda r: r["Size (kVA)"])
        sheet = self.cat["Transformer"]["sheet"]
        hours = [self._row_hours(r, actions) for r in rows]
        if any(h is None for h in hours):
            return None, f"{sheet}: missing transformer hours"
        if kva is None:
            return (min(hours), max(hours)), f"{sheet}!C19:D30 (kVA unknown: smallest..largest)"
        i = next((k for k, r in enumerate(rows) if r["Size (kVA)"] >= kva), len(rows) - 1)
        return (hours[i], hours[i]), f"{sheet}!C{rows[i]['row']}:D{rows[i]['row']} ({rows[i]['Size (kVA)']} kVA class for {kva:g} kVA)"

    def adder(self, intent: str) -> tuple[float | None, str]:
        r = self.only.get(intent)
        return (r["install_hours"] if r else None), (r["cell"] if r else f"{intent}: not in workbook")


# ------------------------------------------------------------------ job construction
def job_id(net: CircuitNetwork, key: tuple) -> str:
    return "JOB-" + hashlib.sha256(f"job|{net.circuit_id}|{key}".encode()).hexdigest()[:6].upper()


def _key(loc: Loc) -> tuple:
    if loc.kind == "transformer":
        return ("xfr", loc.transformer_id)
    if loc.kind == "device":
        return ("dev", loc.device_id)
    return ("span", loc.node)


def _template_for(net: CircuitNetwork, loc: Loc) -> tuple[str | None, str | None]:
    """(template, unsupported key) for one damage location."""
    a = loc.asset_type
    if loc.kind == "transformer":
        return ("secondary", None) if a == "secondary" else ("transformer", None)
    if loc.kind == "device":
        return ("fuse_cutout", None) if a == "fuse" else ("recloser", None) if a == "recloser" else (None, "unknown_asset")
    if a == "pole":
        return "pole", None
    if a == "switch":
        return "switch", None
    if a in ("primary", "primary_line"):
        mount = (net.nodes[loc.node]["edge"] or {}).get("mounting")
        if mount == "Overhead":
            return "overhead_conductor", None
        return None, "underground_primary" if mount == "Underground" else "unknown_mounting"
    return None, "unknown_asset"


def _phases(net: CircuitNetwork, job_key: tuple, loc: Loc) -> int | None:
    if job_key[0] == "xfr":
        return 1
    node = loc.node
    if job_key[0] == "dev":
        cov = net.devices[loc.device_id].get("coverage") or []
        node = cov[0] if cov else node
    return (net.nodes.get(node, {}).get("edge") or {}).get("phases")


def _qty(mode: str, q: tuple[float, float], phases: int | None) -> tuple[float, float]:
    if mode == "fixed":
        return q
    if mode == "per_phase":
        lo, hi = (phases, phases) if phases else (1, 3)
        return q[0] * lo, q[1] * hi
    if mode == "three_phase_only":
        if phases == 3:
            return q
        return (0, 0) if phases == 1 else (0, q[1])
    raise ValueError(mode)


def _restring_tasks(net: CircuitNetwork, loc: Loc):
    """Extra (task, unit hours, source) entries for conductor replacement, or None if the span length is unknown."""
    r = cfg.RESTRING
    length_m = ((net.nodes.get(loc.node) or {}).get("edge") or {}).get("length_m") if loc.node else None
    if not length_m:
        return None
    ft = min(length_m * 3.281, r["max_span_ft"])
    lo, hi = r["hours_per_100ft_per_phase"]
    pull = (ft / 100 * lo, ft / 100 * hi)
    return [(r["dead_end_task"], ("category", "Dead-End"), ("install", "remove"), "per_phase", (0, 2), None, None),
            (r["pull_task"], ("assumed", None), ("install",), "per_phase", (1, 1), pull,
             f"team assumption: {ft:.0f} ft span x {lo:g}-{hi:g} h per phase per 100 ft (labor_config.RESTRING)")]


def build_jobs(net: CircuitNetwork, locs: list[Loc], labor: Labor, restring: bool = True) -> list[Job]:
    groups: dict[tuple, list[Loc]] = {}
    for l in locs:
        groups.setdefault(_key(l), []).append(l)
    jobs = []
    for key, gl in groups.items():
        rep = gl[0]
        job = Job(id=job_id(net, key), key=key, label="", asset=rep.asset_type, locs=gl, trip=trip_for(net, rep))
        job.access_issue = any(l.access_issue for l in gl)
        templates, unsupported = [], []
        for l in gl:  # duplicate records of the same damage type at one location count once
            t, u = _template_for(net, l)
            if t and t not in templates:
                templates.append(t)
            if u and u not in unsupported:
                unsupported.append(u)
        if "pole" in templates and "overhead_conductor" in templates:
            job.notes.append("Pole replacement already includes re-attaching conductor; splices are counted once "
                             "under the line repair.")
        job.templates = templates
        job.unsupported = [cfg.UNSUPPORTED[u] for u in unsupported]
        phases = _phases(net, key, rep)
        if phases is None and key[0] != "xfr":
            job.notes.append("Phase count unknown: quantities range from single-phase (optimistic) to three-phase "
                             "(conservative).")
        lo = hi = 0.0
        for t in templates:
            tpl = cfg.TEMPLATES[t]
            job.crew_min = max(job.crew_min, tpl["crew_min"])
            job.crew_useful_max = max(job.crew_useful_max, tpl["crew_useful_max"])
            job.material_wait |= tpl["material_wait"]
            extra = _restring_tasks(net, rep) if restring and tpl.get("restring") else None
            if tpl["partial"] and extra is None:
                job.partial.append(tpl["partial"])
            if extra:
                job.assumed.append(cfg.RESTRING["note"])
            for name, (kind, ref), actions, mode, q, *given in [(*task, None, None) for task in tpl["tasks"]] + (extra or []):
                if t == "pole" and name == "Re-attach conductor" and "overhead_conductor" in templates:
                    continue  # splices already counted by the line repair at this location
                if kind == "assumed":
                    uh, src = given
                elif kind == "category":
                    h, src = labor.category(ref, actions)
                    uh = None if h is None else (h, h)
                elif kind == "connectors":
                    h, src = labor.connectors(actions)
                    uh = (h, h)
                elif kind == "pole":
                    uh, src = labor.pole((net.nodes.get(rep.node, {}).get("pole") or {}).get("height_ft"), actions)
                else:
                    uh, src = labor.transformer((net.transformers.get(rep.transformer_id) or {}).get("kva"), actions)
                qty = _qty(mode, q, phases)
                if qty == (0, 0):
                    continue
                job.tasks.append(Task(name=name, source=src, unit_hours=uh, qty=qty,
                                      drawing=cfg.TASK_DRAWINGS.get(name)))
                if uh is None:
                    job.unsupported.append(f"Missing workbook hours for '{name}' ({src}); not treated as zero.")
                    continue
                lo += uh[0] * qty[0]
                hi += uh[1] * qty[1]
        if job.access_issue and templates:
            intent = cfg.BACKYARD_ADDER if any(l.special_equipment == "Backyard Bucket" for l in gl) else cfg.ACCESS_ADDER
            h, cell = labor.adder(intent)
            if h is None:
                job.notes.append(f"Access adder '{intent}' has no hours in the workbook; not applied.")
            else:
                job.adders.append((intent, h, cell))
                lo, hi = lo + h, hi + h
        if not templates and not job.unsupported:
            job.unsupported.append(cfg.UNSUPPORTED["unknown_asset"])
        job.direct = (lo, hi)
        job.person_hours = (lo * labor.ilm, hi * labor.ilm)  # ILM applied exactly once per job
        names = [cfg.TEMPLATES[t]["label"] for t in templates] or ["Unsupported repair"]
        job.label = " + ".join(names)
        jobs.append(job)
    jobs.sort(key=lambda j: j.id)
    return jobs


def attach_dependencies(net: CircuitNetwork, jobs: list[Job]) -> None:
    for j in jobs:
        for q in j.trip.zone:
            st, _ = premise_status(net, j.trip, q)
            j.status_of[q["public_id"]] = st
            if st in ("repair_dependent", "unresolved"):
                j.blocked.add(q["public_id"])
        j.critical = [f for f in net.critical if f["rep_premise"] in j.blocked]


def apply_crew_params(jobs: list[Job], params: CrewParams) -> None:
    assess, weather, material = cfg.ASSESSMENT_H, cfg.WEATHER_HOLD_H, cfg.MATERIAL_WAIT_H
    for j in jobs:
        j.infeasible = None
        if j.unsupported:
            j.work_hours = None
        elif params.crew_size < j.crew_min:
            j.infeasible = f"needs at least {j.crew_min} people per crew"
            j.work_hours = None
        elif cfg.LABOR_HOURS_BASIS == "person_hours":
            eff = min(params.crew_size, j.crew_useful_max)
            j.work_hours = (j.person_hours[0] / eff, j.person_hours[1] / eff)
        else:  # crew_hours: workbook hours are already per crew
            j.work_hours = j.person_hours
        access = params.access_delay_h if (params.access_scope == "all" or j.access_issue) else 0.0
        j.waits = {"assessment": assess, "weather": weather,
                   "material": material if j.material_wait else (0.0, 0.0), "access": (access, access)}
        j.ready = tuple(sum(w[b] for w in j.waits.values()) for b in (0, 1))


# ------------------------------------------------------------------ scheduler
def next_work_time(t: float, hpd: float) -> float:
    if hpd >= 24:
        return t
    day = math.floor(t / 24 + 1e-9)
    return t if t < day * 24 + hpd - 1e-9 else (day + 1) * 24


def finish_time(start: float, work: float, hpd: float) -> float:
    """Advance through daily working windows [24d, 24d + hpd)."""
    if hpd >= 24:
        return start + work
    t = next_work_time(start, hpd)
    while True:
        day = math.floor(t / 24 + 1e-9)
        avail = day * 24 + hpd - t
        if work <= avail + 1e-9:
            return t + work
        work -= avail
        t = (day + 1) * 24


def schedule(jobs: list[Job], params: CrewParams) -> None:
    """Greedy list scheduling, one crew per job.

    Priority: repairs that restore a critical facility (hospital, fire or ambulance station)
    first when params.prioritize_critical, then the most customers unblocked per crew-hour.

    Repairs have no prerequisites on each other (de-energised sections can be worked in
    parallel); upstream position only matters for re-energisation, which is applied
    per customer afterwards. Deterministic: ties break on job id. Not claimed optimal.
    """
    for bound, b in B.items():
        pending = [j for j in jobs if j.schedulable]
        crews = [0.0] * params.crews
        for j in jobs:
            j.schedule.pop(bound, None)
        while pending:
            c = min(range(len(crews)), key=lambda i: (crews[i], i))
            t = crews[c]
            ready = [j for j in pending if j.ready[b] <= t + 1e-9]
            if not ready:
                t = min(j.ready[b] for j in pending)
                ready = [j for j in pending if j.ready[b] <= t + 1e-9]
            job = max(ready, key=lambda j: (params.prioritize_critical and bool(j.critical),
                                            len(j.blocked) / max(j.work_hours[b], 1e-6), -int(j.id[4:], 16)))
            start = next_work_time(t, params.hours_per_day)
            end = finish_time(start, job.work_hours[b], params.hours_per_day)
            job.schedule[bound] = (c + 1, start, end)
            crews[c] = end
            pending.remove(job)


# ------------------------------------------------------------------ customer ranges
def _isolation_time(net: CircuitNetwork, p: dict, jobs: list[Job], b: int) -> float:
    switches = {net.isolating_switch(j.trip.loc.node, p["transformer_node"])["public_id"]
                for j in jobs if j.status_of.get(p["public_id"]) == "isolation_candidate"}
    return cfg.ASSESSMENT_H[b] + len(switches) * cfg.SWITCHING_H_PER_SWITCH[b] + cfg.REENERGIZE_H[b]


def _repair_release(jobs_for_p: list[Job], bound: str) -> tuple[float | None, list[Job], list[Job]]:
    """Latest re-energisation over the given repairs; (None, missing) if any cannot be scheduled."""
    b = B[bound]
    missing = [j for j in jobs_for_p if bound not in j.schedule]
    if missing:
        return None, [], missing
    if not jobs_for_p:
        return None, [], []
    t = max(j.schedule[bound][2] for j in jobs_for_p) + cfg.REENERGIZE_H[b]
    controlling = [j for j in jobs_for_p if j.schedule[bound][2] + cfg.REENERGIZE_H[b] >= t - 1e-9]
    return t, controlling, []


def customer_range(net: CircuitNetwork, p: dict, jobs: list[Job], overall_status: str):
    pid = p["public_id"]
    blocking = [j for j in jobs if j.status_of.get(pid) in ("repair_dependent", "unresolved")]
    iso_jobs = [j for j in jobs if j.status_of.get(pid) == "isolation_candidate"]
    if overall_status == "not_interrupted":
        return None, None, [], [], "not_interrupted"
    if overall_status == "isolation_candidate":
        lower = _isolation_time(net, p, jobs, 0)
        upper, ctrl, missing = _repair_release(iso_jobs, "conservative")
        return lower, upper, ctrl or iso_jobs, missing, "isolation"
    lo, ctrl_lo, miss_lo = _repair_release(blocking, "optimistic")
    hi, ctrl_hi, miss_hi = _repair_release(blocking, "conservative")
    if iso_jobs and lo is not None and hi is not None:  # other faults also need switching before re-closing
        lo = max(lo, _isolation_time(net, p, jobs, 0))
        hi = max(hi, _isolation_time(net, p, jobs, 1))
    missing = list({j.id: j for j in miss_lo + miss_hi}.values())
    if missing or lo is None:
        return None, None, blocking, missing, "repair"
    return lo, hi, ctrl_hi, [], "repair"


def _worst_status(jobs: list[Job], pid: str) -> str:
    rank = {"not_interrupted": 0, "isolation_candidate": 1, "unresolved": 2, "repair_dependent": 3}
    return max((j.status_of.get(pid, "not_interrupted") for j in jobs), key=rank.get, default="not_interrupted")


def critical_outcome(net: CircuitNetwork, f: dict, jobs: list[Job]) -> s.CriticalRestoration:
    """Restoration of one critical facility, traced through its representative premise."""
    p = net.premises[f["rep_premise"]]
    status = _worst_status(jobs, p["public_id"])
    if status == "not_interrupted":
        return s.CriticalRestoration(kind=f["kind"], status=status, display="Not interrupted", lower_h=None,
                                     upper_h=None, at_least=False)
    lower, upper, _, _, basis = customer_range(net, p, jobs, status)
    wanted = ("isolation_candidate",) if basis == "isolation" else ("repair_dependent", "unresolved")
    at_least = any(j.partial for j in jobs if j.status_of.get(p["public_id"]) in wanted)
    if lower is None:
        display = "Cannot be estimated"
    elif basis == "isolation":
        display = f"about {_fmt_h(lower)} if crews isolate the damage; otherwise after the repair"
    elif at_least:
        display = f"at least {_fmt_h(lower)}"
    else:
        display = f"{_fmt_h(lower)} - {_fmt_h(upper)}"
    bounded = upper is not None and not at_least and basis != "isolation"
    return s.CriticalRestoration(kind=f["kind"], status=status, display=display,
                                 lower_h=None if lower is None else round(lower, 2),
                                 upper_h=round(upper, 2) if bounded else None, at_least=at_least)


KIND_TEXT = {"hospital": "hospital", "fire_station": "fire station", "ambulance_station": "ambulance station"}


def critical_priority(net: CircuitNetwork, jobs: list[Job], params: CrewParams) -> s.CriticalPriority | None:
    """Compare facility restoration with priority on vs off. Leaves jobs scheduled with params."""
    if not net.critical:
        return None
    if not any(j.critical for j in jobs):
        schedule(jobs, params)
        return s.CriticalPriority(effect="no_facility_waiting", hours_earlier=None,
                                  text="No critical facility waits on these repairs, so the priority rule has "
                                       "nothing to change.")
    res = {}
    for prio in (True, False):
        schedule(jobs, CrewParams(**{**params.__dict__, "prioritize_critical": prio}))
        res[prio] = [critical_outcome(net, f, jobs).lower_h for f in net.critical]
    schedule(jobs, params)
    gains = [(off - on, f) for on, off, f in zip(res[True], res[False], net.critical)
             if on is not None and off is not None]
    gain, f = max(gains, key=lambda g: g[0], default=(0.0, None))
    if gain < 0.05:
        return s.CriticalPriority(effect="already_first", hours_earlier=None,
                                  text="Repairs serving the critical facilities already come first when ranked by "
                                       "customers restored per crew-hour, so the priority rule does not change the "
                                       "order here.")
    kind = KIND_TEXT[f["kind"]]
    text = (f"Putting critical-facility repairs first restores the {kind} about {_fmt_h(gain)} sooner than ranking "
            "by customers alone, at the cost of other customers waiting longer." if params.prioritize_critical else
            f"Critical-facility priority is off. With it on, the {kind} would be restored about {_fmt_h(gain)} "
            "sooner.")
    return s.CriticalPriority(effect="changed_order", hours_earlier=round(gain, 2), text=text)


TARGETS = [(48.0, "2 days"), (72.0, "3 days"), (168.0, "1 week")]


def crew_targets(jobs: list[Job], params: CrewParams) -> s.CrewTargets | None:
    """Fewest crews (1-20, other inputs fixed) whose schedule finishes all modeled work by each target."""
    sched = [j for j in jobs if j.schedulable]
    if not sched:
        return None
    finish: dict[int, tuple[float, float]] = {}
    for n in range(1, 21):
        schedule(jobs, CrewParams(**{**params.__dict__, "crews": n}))
        finish[n] = tuple(max(j.schedule[bd][2] for j in sched) + cfg.REENERGIZE_H[B[bd]] for bd in BOUNDS)
        if finish[n][1] <= TARGETS[0][0]:
            break

    def needed(target: float, b: int) -> int | None:
        return next((n for n in sorted(finish) if finish[n][b] <= target), None)

    complete = len(sched) == len(jobs) and not any(j.partial for j in jobs)
    note = ("Crews needed for all modeled repairs to finish within each time, with the other crew inputs unchanged. "
            "Optimistic and conservative use the scenario bounds.")
    if not complete:
        note += (" Some repair work is not modeled or not schedulable, so these are minimums: more crews may be "
                 "needed in reality.")
    return s.CrewTargets(scope_complete=complete, note=note, targets=[
        s.CrewTarget(target_h=t, label=lbl, crews_needed_optimistic=needed(t, 0),
                     crews_needed_conservative=needed(t, 1)) for t, lbl in TARGETS])


# ------------------------------------------------------------------ response
def _fmt_h(h: float) -> str:
    if h < 1:
        return f"{round(h * 60)} min"
    if h < 48:
        return f"{h:.0f} h" if h >= 10 else f"{h:.1f} h"
    return f"{h / 24:.1f} days"


def _job_out(j: Job, labor: Labor) -> s.RepairJob:
    sched = {b: s.JobSlot(crew=v[0], start_h=round(v[1], 2), end_h=round(v[2], 2)) for b, v in j.schedule.items()}
    return s.RepairJob(
        id=j.id, label=j.label, evidence="historical record replayed" if any(l.group == "historical_replay" for l in j.locs)
        else "simulated", records=len(j.locs),
        tasks=[s.RepairTask(name=t.name, quantity_low=t.qty[0], quantity_high=t.qty[1]) for t in j.tasks],
        direct_hours_low=round(j.direct[0], 2), direct_hours_high=round(j.direct[1], 2),
        person_hours_low=round(j.person_hours[0], 2), person_hours_high=round(j.person_hours[1], 2),
        work_hours_low=round(j.work_hours[0], 2) if j.work_hours else None,
        work_hours_high=round(j.work_hours[1], 2) if j.work_hours else None,
        waits={k: [round(v[0], 2), round(v[1], 2)] for k, v in j.waits.items()},
        crew_min=j.crew_min, crew_useful_max=j.crew_useful_max,
        customers_waiting=len(j.blocked), supported=not j.unsupported, schedulable=j.schedulable,
        problems=j.unsupported + ([f"Cannot be scheduled: {j.infeasible}."] if j.infeasible else []),
        partial=j.partial, assumed=j.assumed, notes=j.notes,
        protection_uncertain=j.trip.skipped_devices > 0,
        optimistic=sched.get("optimistic"), conservative=sched.get("conservative"),
        developer=s.JobDeveloper(
            tasks=[s.DevTask(name=t.name, source=t.source,
                             unit_hours_low=None if t.unit_hours is None else round(t.unit_hours[0], 4),
                             unit_hours_high=None if t.unit_hours is None else round(t.unit_hours[1], 4),
                             quantity_low=t.qty[0], quantity_high=t.qty[1], drawing=t.drawing) for t in j.tasks],
            structures=[f"{cfg.TEMPLATES[t]['label']}: {cfg.STRUCTURE_DRAWINGS[t] or 'not shown in the sample drawings'}"
                        for t in j.templates],
            adders=[s.DevAdder(name=n, hours=h, source=c) for n, h, c in j.adders],
            ilm=labor.ilm, ilm_source=labor.ilm_cell))


def _workbook_only_lower(net: CircuitNetwork, p: dict, scen: Scenario, params: CrewParams, labor: Labor,
                         status: str) -> float | None:
    """Earliest repair-based time for the premise without the re-stringing assumption (a lower bound)."""
    jobs = build_jobs(net, scen.locations, labor, restring=False)
    attach_dependencies(net, jobs)
    apply_crew_params(jobs, params)
    schedule(jobs, params)
    if status == "isolation_candidate":  # compare like with like: the repair alternative
        lo, _, _ = _repair_release([j for j in jobs if j.status_of.get(p["public_id"]) == "isolation_candidate"],
                                   "optimistic")
        return lo
    lower, *_ = customer_range(net, p, jobs, status)
    return lower


def simulate(net: CircuitNetwork, p: dict, scen: Scenario, params: CrewParams, labor_ref: dict,
             impact: s.ScenarioResult) -> s.RestorationResult:
    labor = Labor(labor_ref)
    jobs = build_jobs(net, scen.locations, labor, restring=params.restring_assumption)
    attach_dependencies(net, jobs)
    apply_crew_params(jobs, params)
    pid = p["public_id"]
    status = impact.selected_premise.status
    uses_assumption = any(j.assumed for j in jobs if j.status_of.get(pid))
    workbook_only = _workbook_only_lower(net, p, scen, params, labor, status) if uses_assumption else None
    targets = crew_targets(jobs, params)
    priority = critical_priority(net, jobs, params)  # also leaves jobs scheduled with params
    if priority is None:
        schedule(jobs, params)

    lower, upper, controlling, missing, basis = customer_range(net, p, jobs, status)
    why, warnings = [], []
    unit_note = ("Workbook hours are treated as person-hours (demo assumption): a crew of N finishes a job up to N "
                 "times faster, capped at the job's useful crew size. If the hours were per crew, adding people "
                 "would not shorten jobs and total effort would be N times higher."
                 if cfg.LABOR_HOURS_BASIS == "person_hours" else
                 "Workbook hours are treated as crew-hours (demo assumption): job durations do not shrink with crew "
                 "size.")
    warnings.append(unit_note)
    if any(j.unsupported for j in jobs):
        warnings.append(f"{sum(1 for j in jobs if j.unsupported)} repair job(s) could not be estimated from the "
                        "workbook, so the schedule is incomplete.")
    if any(j.infeasible for j in jobs):
        warnings.append(f"{sum(1 for j in jobs if j.infeasible)} job(s) need a larger crew than the one selected.")
    if any(j.partial for j in jobs):
        warnings.append("Some repairs are only partly covered by the workbook (for example conductor re-stringing), "
                        "so their effort may be understated.")
    if any(j.assumed for j in jobs):
        warnings.append(f"{sum(1 for j in jobs if j.assumed)} line repair(s) include our team's assumed time for "
                        "replacing wire, which the AEP workbook does not cover. Switch the assumption off to see "
                        "workbook data only.")

    relevant = [j for j in jobs if j.status_of.get(pid)]
    partial_relevant = any(j.partial for j in relevant)
    conditional = None
    if status == "not_interrupted":
        kind = "not_interrupted"
        headline = "Not interrupted in this simulation"
        display = "No restoration needed"
    elif basis == "isolation":
        # Two alternative outcomes, not one interval.
        kind = "conditional"
        iso_jobs = [j for j in jobs if j.status_of.get(pid) == "isolation_candidate"]
        rep_lo, _, _ = _repair_release(iso_jobs, "optimistic")
        rep_hi, _, _ = _repair_release(iso_jobs, "conservative")
        iso = (_isolation_time(net, p, jobs, 0), _isolation_time(net, p, jobs, 1))
        conditional = s.ConditionalOutcomes(
            if_isolated_low_h=round(iso[0], 2), if_isolated_high_h=round(iso[1], 2),
            if_repair_low_h=None if rep_lo is None else round(rep_lo, 2),
            if_repair_high_h=None if rep_hi is None else round(rep_hi, 2),
            repair_scope_complete=not any(j.partial for j in iso_jobs))
        headline = "Two possible outcomes: earlier if crews isolate the damage, otherwise after the repair"
        if rep_hi is None:
            rep_txt = "repair cannot be estimated"
        elif not conditional.repair_scope_complete:
            rep_txt = f"at least {_fmt_h(rep_lo)}"
        else:
            rep_txt = f"{_fmt_h(rep_lo)} - {_fmt_h(rep_hi)}"
        display = f"If isolated: {_fmt_h(iso[0])} - {_fmt_h(iso[1])} | If not: {rep_txt}"
        why.append("These are two alternative outcomes, not a single range. Whether crews isolate the damaged section "
                   "first is a field decision the model does not know.")
        why.append(f"If isolated: after damage assessment, a crew opens a mapped switch and the device that opened is "
                   f"safely re-closed (about {_fmt_h(iso[0])} to {_fmt_h(iso[1])}).")
        if rep_hi is None:
            why.append("If not isolated: power returns when the repair is finished, which cannot be estimated from "
                       "the workbook.")
        elif not conditional.repair_scope_complete:
            why.append("If not isolated: power returns when the repair is finished. Part of that repair has no labor "
                       f"entry in the workbook, so only a lower bound (at least {_fmt_h(rep_lo)}) can be given.")
        else:
            why.append("If not isolated: power returns when the repair is finished.")
    elif lower is None and upper is None:
        infeasible = [m for m in missing if m.infeasible and not m.unsupported]
        if missing and len(infeasible) == len(missing):
            kind = "crew_infeasible"
            headline = "The selected crews cannot do a required repair under these assumptions"
            display = "Not possible with the selected crew size"
            for m in infeasible[:3]:
                why.append(f"{m.label}: needs at least {m.crew_min} people per crew; the scenario has "
                           f"{params.crew_size}. The repair data is available; raise people per crew to estimate it.")
        else:
            kind = "insufficient_data"
            headline = "Insufficient information for a restoration range"
            display = "Cannot estimate"
            why.append("At least one repair your supply depends on cannot be estimated from the workbook: "
                       + "; ".join(sorted({m.unsupported[0] for m in missing if m.unsupported})))
    else:
        if partial_relevant:
            kind = "lower_bound_only"
            display = f"At least {_fmt_h(lower)}"
            why.append("Part of the required work (for example re-stringing conductor) has no labor entry in the "
                       f"workbook, so the modeled times are lower bounds. The modeled work alone finishes between "
                       f"{_fmt_h(lower)} and {_fmt_h(upper)}; the full repair would take longer by an unknown amount.")
        else:
            kind = "bounded"
            display = f"{_fmt_h(lower)} - {_fmt_h(upper)}"
        headline = ("Waits for repair" if status == "repair_dependent"
                    else "Repair-based estimate (earlier restoration unresolved)")
        if status == "unresolved":
            why.append("No mapped switch separates you from the damage, so this estimate assumes you wait for the "
                       "repair. Field sectionalizing could restore you earlier, but the model does not assume it.")
    if uses_assumption and status != "not_interrupted":
        why.append(cfg.RESTRING["note"] + (f" From workbook data alone, the repair would take at least "
                                           f"{_fmt_h(workbook_only)}." if workbook_only is not None else ""))
    for j in controlling[:3]:
        if j.schedule.get("conservative"):
            crew, st, en = j.schedule["conservative"]
            why.append(f"{j.label}: crew {crew} works on it from about {_fmt_h(st)} to {_fmt_h(en)} in the "
                       f"conservative schedule; {len(j.blocked)} customers wait on it.")
    if any(j.trip.skipped_devices for j in controlling) or any(j.trip.skipped_devices for j in jobs
                                                                if j.status_of.get(p["public_id"])):
        warnings.append("A mapped protective device that is not in the customer dependency file lies between the "
                        "damage and the device assumed to open. The real outage area could be smaller.")

    # confidence
    reasons = [s.ConfidenceReason(effect=-25, text="Restoration durations are not validated: historical records "
                                                   "have dates only, so they are not used as duration targets."),
               s.ConfidenceReason(effect=-10, text="Per-person vs per-crew labor hours is a demo assumption.")]
    mine = [j for j in jobs if j.status_of.get(p["public_id"])]
    if any(j.partial for j in mine):
        reasons.append(s.ConfidenceReason(effect=-10, text="A repair you depend on is only partly covered by the "
                                                           "workbook."))
    if any(j.assumed for j in mine):
        reasons.append(s.ConfidenceReason(effect=-10, text="Part of the repair time is our team's assumption for "
                                                           "replacing wire, not AEP data."))
    if any(j.trip.skipped_devices for j in mine):
        reasons.append(s.ConfidenceReason(effect=-15, text="Which device opens for your fault is uncertain."))
    if basis == "isolation":
        reasons.append(s.ConfidenceReason(effect=-10, text="The early end assumes crews choose to isolate and "
                                                           "switch manually."))
    pts = 100 + sum(r.effect for r in reasons)
    conf = s.Confidence(level="moderate" if pts >= 55 else "low", points=pts, reasons=reasons,
                        ceiling_note="Scenario bounds from explicit assumptions, not a statistical confidence "
                                     "interval.")

    critical_out = [critical_outcome(net, f, jobs) for f in net.critical]

    sched = [j for j in jobs if j.schedulable]
    estimable = [j for j in jobs if not j.unsupported]  # effort is known even if no crew can take the job
    ends = {b: [j.schedule[b][2] for j in sched if b in j.schedule] for b in BOUNDS}
    jobs_partial = sum(1 for j in jobs if j.partial)
    all_scheduled = len(sched) == len(jobs)
    complete = all_scheduled and jobs_partial == 0
    modeled_hi = round(max(ends["conservative"]) + cfg.REENERGIZE_H[1], 2) if ends["conservative"] else None
    notes = []
    if jobs_partial:
        notes.append(f"{jobs_partial} of {len(jobs)} repair jobs are only partly covered by the labor workbook "
                     "(for example conductor re-stringing), so this is a lower bound.")
    if not all_scheduled:
        notes.append(f"{len(jobs) - len(sched)} job(s) could not be estimated or scheduled and are excluded.")
    overall = s.OverallRestoration(
        complete=complete,
        lower_h=round(max(ends["optimistic"]) + cfg.REENERGIZE_H[0], 2) if ends["optimistic"] else None,
        upper_h=modeled_hi if complete else None,
        modeled_work_upper_h=modeled_hi,
        note=" ".join(notes) or None,
        jobs=len(jobs), jobs_unsupported=sum(1 for j in jobs if j.unsupported),
        jobs_infeasible=sum(1 for j in jobs if j.infeasible), jobs_partial=jobs_partial,
        direct_hours_low=round(sum(j.direct[0] for j in estimable), 1),
        direct_hours_high=round(sum(j.direct[1] for j in estimable), 1),
        person_hours_low=round(sum(j.person_hours[0] for j in estimable), 1),
        person_hours_high=round(sum(j.person_hours[1] for j in estimable), 1),
        customers_interrupted=impact.initially_interrupted)
    return s.RestorationResult(
        state="simulated",
        time_reference="Hours elapsed from the start of the simulated storm response (t = 0), not a clock time.",
        disclaimer="Simulated model estimate, not official AEP restoration information.",
        params=s.CrewParamsOut(**params.__dict__),
        selected=s.CustomerRestoration(status=status, headline=headline, display=display,
                                       lower_h=None if lower is None else round(lower, 2),
                                       upper_h=None if upper is None else round(upper, 2),
                                       basis=basis, controlling_jobs=[j.id for j in controlling], why=why,
                                       confidence=conf, range_kind=kind, conditional=conditional,
                                       scope_complete=not partial_relevant,
                                       network_uncertain=status == "unresolved" or any(
                                           j.trip.skipped_devices for j in relevant),
                                       uses_assumption=uses_assumption and status != "not_interrupted",
                                       workbook_only_lower_h=None if workbook_only is None else round(workbook_only, 2)),
        overall=overall,
        critical_facilities=critical_out,
        critical_priority=priority,
        crew_targets=targets,
        jobs=[_job_out(j, labor) for j in jobs],
        warnings=warnings,
        assumptions=[
            f"Direct labor = workbook install/removal hours x quantity + reported-access adders; total person-hours "
            f"= direct labor x {labor.ilm:g} (indirect labor multiplier, applied once; it already covers travel, "
            f"safety briefings and setup).",
            "Waiting time (assessment, weather, material, access) delays when a job can start but is not labor and "
            "is never multiplied.",
            "One crew works one job at a time; extra people shorten a job only up to its useful crew size.",
            f"Crews work {params.hours_per_day:g} hours per day starting at t = 0; unfinished jobs continue the next "
            "working day.",
            "Repairs can proceed in parallel; upstream position only affects when customers can be re-energized.",
            ("Priority: repairs that restore a critical facility (hospital, fire or ambulance station, linked to "
             "the nearest service transformer within 150 m) go first; then " if params.prioritize_critical else
             "Priority (critical-facility priority switched off): ")
            + "the job that lets the most waiting customers back per hour of crew work. This is a heuristic, not an "
              "optimal plan. No individual customer is prioritized from medical flags.",
            "Optimistic and conservative ends use the low and high quantities and waits; they are scenario bounds.",
        ],
        developer=s.DeveloperView(
            labor_basis=cfg.LABOR_HOURS_BASIS, ilm=labor.ilm, ilm_source=labor.ilm_cell,
            ilm_applies_to=cfg.ILM_APPLIES_TO,
            waits_hours={"assessment": list(cfg.ASSESSMENT_H), "weather": list(cfg.WEATHER_HOLD_H),
                         "material": list(cfg.MATERIAL_WAIT_H), "switching_per_switch": list(cfg.SWITCHING_H_PER_SWITCH),
                         "reenergize": list(cfg.REENERGIZE_H)},
            adders_not_applied=cfg.NOT_APPLIED_ADDERS,
            source_workbook=labor_ref.get("source", "")),
    )
