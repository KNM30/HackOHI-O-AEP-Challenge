"""Simulated damage scenarios and their customer impact.

Scenario damage is separate from historical records. Historical records enter a
scenario only through the explicit "historical_replay" scenario.

Model (simplified, see docs/assumptions.md):
- Initial interruption: each damaged span is cleared by its nearest upstream
  protective device (fuse/recloser/sectionalizer, else the substation breaker);
  every premise whose upstream chain contains that device is interrupted. A damaged
  transformer interrupts its own premises; a damaged protective device interrupts
  its zone.
- After isolation: an interrupted premise with damage on its own supply path waits
  for repair. Otherwise it is an *isolation candidate* only if a mapped, normally
  closed switch on a known branch lies between the damage and the premise's branch
  point, so the damaged section could be opened and the tripped device re-closed.
  Without such a switch the case is *unresolved*. No alternate feeds, remote
  switching or automatic re-energisation are assumed.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from . import schemas as s
from .context import KIND_LABELS, bucket, device_label
from .network import CircuitNetwork

STATUS_RANK = {"not_interrupted": 0, "isolation_candidate": 1, "unresolved": 2, "repair_dependent": 3}
NEARBY_M = 400  # damage this close but electrically unrelated gets an explicit "proximity is not dependency" note
MAX_CANDIDATES = 4
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def replay_event(net) -> str | None:
    """The circuit's own largest storm event (most placed records); ties go to the latest."""
    counts: dict[str, int] = {}
    for d in net.damage:
        ev = net.event_of.get(d["public_id"])
        if ev and d.get("match_status") == "matched":
            counts[ev] = counts.get(ev, 0) + 1
    return max(counts, key=lambda e: (counts[e], e)) if counts else None


def event_label(ev: str) -> tuple[str, str]:
    """('Feb 2025', '13-17 Feb 2025') from '2025-02-13..2025-02-17'."""
    a, _, b = ev.partition("..")
    ya, ma, da = a.split("-")
    month = f"{MONTHS[int(ma) - 1]} {ya}"
    if not b:
        return month, f"{int(da)} {month}"
    yb, mb, db = b.split("-")
    if (ya, ma) == (yb, mb):
        return month, f"{int(da)}-{int(db)} {month}"
    return month, f"{int(da)} {MONTHS[int(ma) - 1]} - {int(db)} {MONTHS[int(mb) - 1]} {yb}"


@dataclass
class Loc:
    public_id: str
    kind: str  # span | transformer | device
    label: str
    lonlat: list[float] | None
    node: str | None = None
    transformer_id: str | None = None
    device_id: str | None = None
    group: str = ""
    # repair-relevant attributes (historical replay records carry real values)
    asset_type: str = "primary_line"
    access_issue: bool = False
    special_equipment: str | None = None


@dataclass
class Scenario:
    id: str
    label: str
    description: str
    mode: str  # single | multi
    locations: list[Loc]
    defaults: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None


def loc_id(net: CircuitNetwork, key: str) -> str:
    return "LOC-" + hashlib.sha256(f"loc|{net.circuit_id}|{key}".encode()).hexdigest()[:8].upper()


def span_loc(net: CircuitNetwork, node: str, label: str, group: str) -> Loc:
    return Loc(public_id=loc_id(net, node), kind="span", label=label, lonlat=net.nodes[node]["lonlat"],
               node=node, group=group)


def _span_desc(net: CircuitNetwork, node: str, where: str, xf: str | None = None) -> str:
    e = net.nodes[node]["edge"] or {}
    mount = (e.get("mounting") or "unknown").lower()
    mount = "line" if mount == "unknown" else f"{mount} line"
    txt = f"Damaged {mount} {where} - {bucket(net.downstream_count(node))} premises beyond it"
    if xf is not None and net.is_ancestor(node, xf):
        km = (net.nodes[xf]["dist_m"] - net.nodes[node]["dist_m"]) / 1000
        txt += (", within 0.1 km upstream of you along the line" if km < 0.1
                else f", about {km:.1f} km upstream of you along the line")
    elif xf is not None and net.nodes[node]["lonlat"] and net.nodes[xf]["lonlat"]:
        txt += f", about {_dist_m(net.nodes[node]['lonlat'], net.nodes[xf]['lonlat']) / 1000:.1f} km from you"
    return txt


def _pick(cands: list[str], key, distinct) -> list[str]:
    """Deterministic, varied pick: sort by key, keep one candidate per distinct value."""
    out, seen = [], set()
    for n in sorted(cands, key=key):
        c = distinct(n)
        if c in seen:
            continue
        seen.add(c)
        out.append(n)
        if len(out) == MAX_CANDIDATES:
            break
    return out


def catalog(net: CircuitNetwork, p: dict) -> list[Scenario]:
    xf = p.get("transformer_node")
    if xf is None:
        reason = "This premise is not placed on the mapped network, so scenarios cannot be traced."
        return [Scenario(id=i, label=l, description="", mode="single", locations=[], unavailable_reason=reason)
                for i, l in (("shared_upstream", "Damage on a shared upstream line"),
                             ("local_branch", "Damage on your local branch"),
                             ("neighbouring_branch", "Damage on a neighbouring branch"),
                             ("multiple", "Multiple damage locations"))]
    chain = p["chain"]
    nearest = chain[0] if chain else None
    own = net.downstream_count(xf)
    path = [n for n in net.path_to_root(xf) if net.nodes[n]["parent"] is not None]
    on_path = set(path)
    depth = lambda n: net.nodes[n]["depth"]

    shared = [n for n in path if net.downstream_count(n) > own and (nearest is None or net.protector[n] != nearest)]
    if nearest:
        local = [n for n in path if net.protector[n] == nearest]
    else:
        local = [n for n in path if net.downstream_count(n) <= max(own, 25)]
    shares = set(chain) | {None}
    neigh = [n for n in net.protector if n not in on_path and net.protector[n] in shares
             and not net.is_ancestor(n, xf)]
    neigh_iso = [n for n in neigh if net.isolating_switch(n, xf)]
    elsewhere = [n for n, pid in net.protector.items()
                 if pid is not None and pid not in shares and net.devices[pid]["kind"] == "fuse"]

    dc = net.downstream_count
    shared_p = _pick(shared, lambda n: (-dc(n), depth(n)), dc)
    # local spans differ mainly by position, so keep one per distance band along the line
    local_p = _pick(local, lambda n: (-depth(n),), lambda n: round(net.nodes[n]["dist_m"] / 100))
    iso = set(neigh_iso)
    chain_pos = lambda n: chain.index(net.protector[n]) if net.protector[n] in chain else len(chain)
    # neighbours: isolatable first, then those sharing your nearest device, then larger branches
    neigh_p = _pick(neigh, lambda n: (n not in iso, chain_pos(n), -dc(n), depth(n)), lambda n: (chain_pos(n), dc(n)))
    else_p = _pick(elsewhere, lambda n: (-dc(n), depth(n)), dc)

    out = []

    def single(sid, label, desc, nodes, where, empty):
        locs = [span_loc(net, n, _span_desc(net, n, where, xf), sid) for n in nodes]
        out.append(Scenario(id=sid, label=label, description=desc, mode="single", locations=locs,
                            defaults=[locs[0].public_id] if locs else [],
                            unavailable_reason=None if locs else empty))

    single("shared_upstream", "Damage on a shared upstream line",
           "One damaged span on your supply path that also feeds many other customers.",
           shared_p, "on your shared supply path", "No shared upstream span was found on your supply path.")
    single("local_branch", "Damage on your local branch",
           "One damaged span on your supply path close to you, inside your nearest protective zone.",
           local_p, "on your local branch", "No local-branch span was found on your supply path.")
    single("neighbouring_branch", "Damage on a neighbouring branch",
           "One damaged span on a different branch that shares a protective device with you. Shows how isolation "
           "could restore unaffected branches.",
           neigh_p, "on a neighbouring branch", "No neighbouring branch shares a protective device with you.")
    multi = []
    if local_p:
        multi.append(span_loc(net, local_p[0], _span_desc(net, local_p[0], "on your local branch", xf), "multiple"))
    if neigh_p:
        multi.append(span_loc(net, neigh_p[0], _span_desc(net, neigh_p[0], "on a neighbouring branch", xf),
                              "multiple"))
    if else_p:
        multi.append(span_loc(net, else_p[0], _span_desc(net, else_p[0], "elsewhere on the circuit", xf),
                              "multiple"))
    out.append(Scenario(id="multiple", label="Multiple damage locations",
                        description="Several damaged spans at once. Untick a location to see how the impact changes.",
                        mode="multi", locations=multi, defaults=[l.public_id for l in multi],
                        unavailable_reason=None if len(multi) >= 2 else "Not enough distinct locations near you."))
    out.append(replay_scenario(net))
    if net.critical:
        out.append(critical_scenario(net))
    return out


CRITICAL_COMPETITOR_RATIO = 4  # competing repair must block at least this many times more customers
CRITICAL_COMPETITOR_SCAN = 40  # largest-branch spans examined for a competitor


def _blocked(net: CircuitNetwork, node: str) -> set[str]:
    """Premises that wait on a repair of this span (same rule as restoration.attach_dependencies)."""
    t = trip_for(net, span_loc(net, node, "", ""))
    return {q["public_id"] for q in t.zone if premise_status(net, t, q)[0] in ("repair_dependent", "unresolved")}


def critical_scenario(net: CircuitNetwork) -> Scenario:
    """Circuit-wide operator view: a small repair that restores a critical facility versus a larger one elsewhere.

    Ranking by customers per crew-hour alone would do the larger repair first, so this is
    the case where critical-facility priority changes the order. Fixed for the circuit
    (same locations for every premise); labels never name or locate the facility.
    """
    cached = getattr(net, "_critical_scenario", None)
    if cached is not None:
        return cached
    overhead = lambda n: (net.nodes[n]["edge"] or {}).get("mounting") == "Overhead"
    reps = {f["rep_premise"] for f in net.critical}
    fac_nodes = [net.premises[r]["transformer_node"] for r in reps if net.premises[r].get("transformer_node")]
    best = None
    for xf in fac_nodes:
        spans = [n for n in net.path_to_root(xf) if net.nodes[n]["parent"] is not None and overhead(n)]
        for n in sorted(spans, key=lambda n: (net.downstream_count(n), net.nodes[n]["depth"]))[:3]:
            b = _blocked(net, n)
            if best is None or len(b) < len(best[1]):
                best = (n, b)
    comp = None
    if best is not None:
        fac_node, fac_blocked = best
        others = [n for n in net.protector if overhead(n) and not any(net.is_ancestor(n, x) for x in fac_nodes)]
        for n in sorted(others, key=lambda n: (-net.downstream_count(n), net.nodes[n]["depth"]))[
                :CRITICAL_COMPETITOR_SCAN]:
            b = _blocked(net, n)
            if not (b & reps) and len(b) >= CRITICAL_COMPETITOR_RATIO * len(fac_blocked):
                comp = n
                break
    locs = []
    if comp is not None:
        locs = [span_loc(net, fac_node, f"Damaged overhead line feeding a critical facility - "
                                        f"{bucket(len(fac_blocked))} customers wait on it", "critical_facility"),
                span_loc(net, comp, f"Damaged overhead line on a larger branch - {bucket(len(_blocked(net, comp)))} "
                                    "customers wait on it", "critical_facility")]
    for l in locs:  # a span this close to a facility would locate it on the map
        l.lonlat = None
    net._critical_scenario = Scenario(
        id="critical_facility", label="Critical facility vs. larger branch (operator view)",
        description=("Two repairs compete for one crew: a small one that restores a hospital, fire or ambulance "
                     "station, and a larger one elsewhere. Set crews to 1 and switch critical-facility priority off "
                     "to see the order change. The facility is identified by type only."),
        mode="multi", locations=locs, defaults=[l.public_id for l in locs],
        unavailable_reason=None if locs else "No overhead repair on this circuit separates a critical facility "
                                             "from a larger branch.")
    return net._critical_scenario


def replay_scenario(net: CircuitNetwork) -> Scenario:
    """Explicitly replay one historical event's damage records as simulated damage."""
    locs: list[Loc] = []
    event = replay_event(net)
    for d in net.damage:
        if event is None or net.event_of.get(d["public_id"]) != event or d.get("match_status") != "matched":
            continue
        layer = d.get("matched_layer")
        lab = f"Replayed {d['report_date']} record: {(d.get('damage_type') or 'damage').lower()}"
        extra = dict(group="historical_replay", asset_type=layer or "unknown",
                     access_issue=d.get("access_issue") == "Yes", special_equipment=d.get("special_equipment"))
        if layer in ("transformer", "secondary") and d.get("matched_ref") in net.transformers:
            locs.append(Loc(public_id=loc_id(net, d["public_id"]), kind="transformer", label=lab,
                            lonlat=d["lonlat"], transformer_id=d["matched_ref"], **extra))
        elif layer in ("fuse", "recloser") and d.get("matched_ref") in net.devices and d.get("node"):
            locs.append(Loc(public_id=loc_id(net, d["public_id"]), kind="device", label=lab, lonlat=d["lonlat"],
                            node=d["node"], device_id=d["matched_ref"], **extra))
        elif d.get("node") and net.nodes[d["node"]]["parent"] is not None:
            locs.append(Loc(public_id=loc_id(net, d["public_id"]), kind="span", label=lab, lonlat=d["lonlat"],
                            node=d["node"], **extra))
    month, dates = event_label(event) if event else ("", "")
    return Scenario(id="historical_replay", label=f"Replay the {month} storm damage (simulation)".replace("  ", " "),
                    description=(f"Uses this circuit's largest set of historical damage records ({dates}) as if they "
                                 "all happened now. "
                                 "This is a what-if replay, not a record of what customers actually experienced."),
                    mode="multi", locations=locs, defaults=[l.public_id for l in locs],
                    unavailable_reason=None if locs else "No placed records for that event on this circuit.")


# ---------------------------------------------------------------- evaluation
def location_index(net: CircuitNetwork) -> dict[str, Loc]:
    """Every damage location that can appear in a scenario on this circuit, by public id.

    Labels here are premise-independent, so a fixed scenario reads the same for every
    premise it is evaluated against.
    """
    idx = getattr(net, "_loc_index", None)
    if idx is None:
        idx = {}
        for n, nd in net.nodes.items():
            if nd["parent"] is not None:
                loc = span_loc(net, n, _span_desc(net, n, "on this circuit"), "span")
                idx[loc.public_id] = loc
        for loc in replay_scenario(net).locations:
            idx[loc.public_id] = loc
        net._loc_index = idx
    return idx


@dataclass
class Trip:
    loc: Loc
    device: dict | None  # protective device that opens; None = breaker (or transformer-local)
    zone: list[dict]
    local_only: bool = False  # transformer damage
    skipped_devices: int = 0  # unevidenced mapped devices passed over -> protection uncertain


def trip_for(net: CircuitNetwork, loc: Loc) -> Trip:
    if loc.kind == "transformer":
        zone = [p for p in net.premises.values() if p["transformer_id"] == loc.transformer_id]
        return Trip(loc, None, zone, local_only=True)
    if loc.kind == "device":
        dev, skipped = net.devices[loc.device_id], []
    else:
        dev, skipped = net.protection_detail(loc.node)
    zone = list(net.premises.values()) if dev is None else \
        [p for p in net.premises.values() if dev["public_id"] in p["chain"]]
    return Trip(loc, dev, zone, skipped_devices=len(skipped))


def premise_status(net: CircuitNetwork, trip: Trip, p: dict) -> tuple[str, str]:
    """(status, relation) of premise p for one trip it is inside."""
    xf = p.get("transformer_node")
    if trip.local_only:
        return "repair_dependent", "own_transformer"
    if trip.loc.kind == "device":
        return "repair_dependent", "damaged_device_you_depend_on"
    if xf is None:
        return "unresolved", "not_on_network"
    if net.is_ancestor(trip.loc.node, xf):
        return "repair_dependent", "on_supply_path"
    if net.isolating_switch(trip.loc.node, xf):
        return "isolation_candidate", "shared_device_isolatable"
    return "unresolved", "shared_device_no_mapped_switch"


def _dist_m(a, b) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111_320 * math.cos(lat), (a[1] - b[1]) * 110_540)


def device_phrase(net: CircuitNetwork, p: dict, dev: dict | None) -> str:
    if dev is None:
        return "the substation circuit breaker (the whole circuit)"
    if dev["public_id"] in p["chain"]:
        pos = p["chain"].index(dev["public_id"]) + 1
        nth = {1: "nearest", 2: "2nd", 3: "3rd"}.get(pos, f"{pos}th")
        return (f"the {nth} protective device upstream of you ({device_label(dev).lower()}, serving "
                f"{bucket(dev.get('zone_premise_count'))} customers)")
    return f"a {device_label(dev).lower()} that does not serve you"


def evaluate(net: CircuitNetwork, p: dict, scen: Scenario, selected: list[Loc]) -> s.ScenarioResult:
    status: dict[str, str] = {}
    trips = [trip_for(net, l) for l in selected]
    for t in trips:
        for q in t.zone:
            st, _ = premise_status(net, t, q)
            if STATUS_RANK[st] > STATUS_RANK.get(status.get(q["public_id"]), 0):
                status[q["public_id"]] = st
    counts = {k: 0 for k in STATUS_RANK}
    for q in net.premises.values():
        counts[status.get(q["public_id"], "not_interrupted")] += 1

    # selected premise
    my = status.get(p["public_id"], "not_interrupted")
    reasons, devices = [], []
    for t in trips:
        inside = any(q["public_id"] == p["public_id"] for q in t.zone)
        if inside:
            st, rel = premise_status(net, t, p)
            dev_txt = "your service transformer" if t.local_only else device_phrase(net, p, t.device)
            text = {
                "own_transformer": "Your own service transformer is damaged; power returns only after it is repaired.",
                "damaged_device_you_depend_on": f"The damaged equipment is {dev_txt}; your supply waits for its repair.",
                "on_supply_path": f"The damage is on your supply path, so {dev_txt} would open and your power waits "
                                  "for the repair.",
                "shared_device_isolatable": f"The damage is on another branch but would open {dev_txt}, which you "
                                            "share. A mapped switch separates that branch from yours, so crews could "
                                            "potentially isolate it and restore you before the repair.",
                "shared_device_no_mapped_switch": f"The damage is on another branch but would open {dev_txt}, which "
                                                  "you share. No mapped switch separates that branch from yours, so "
                                                  "whether you could be restored before the repair is unresolved.",
                "not_on_network": "Your premise could not be placed on the mapped network.",
            }[rel]
            reasons.append(s.ImpactReason(location_id=t.loc.public_id, relation=rel, text=text))
            if not t.local_only:
                devices.append(dev_txt)
        else:
            dev_txt = device_phrase(net, p, t.device) if not t.local_only else "another service transformer"
            text = f"This damage would be cleared by {dev_txt}, so it does not interrupt you in this model."
            if p.get("lonlat") and t.loc.lonlat and _dist_m(p["lonlat"], t.loc.lonlat) < NEARBY_M:
                text += " It is close to you on the map, but you are not electrically dependent on it."
            reasons.append(s.ImpactReason(location_id=t.loc.public_id, relation="not_dependent", text=text))

    # identical explanations (e.g. many replayed records) are shown once with a count
    grouped: dict[str, list[s.ImpactReason]] = {}
    for r in reasons:
        grouped.setdefault(r.text, []).append(r)
    reasons = [s.ImpactReason(location_id=g[0].location_id, relation=g[0].relation,
                              text=g[0].text if len(g) == 1 else f"{g[0].text} ({len(g)} damage locations)")
               for g in grouped.values()]
    # damage you depend on first; stable otherwise
    reasons.sort(key=lambda r: r.relation == "not_dependent")
    headline = {
        "not_interrupted": "Not interrupted in this simulation",
        "repair_dependent": "Interrupted - waits for repair in this simulation",
        "isolation_candidate": "Interrupted - possible earlier restoration after isolation",
        "unresolved": "Interrupted - earlier restoration unresolved",
    }[my]

    # transformer aggregation for the map (no individual homes)
    by_xf: dict[str, dict[str, int]] = {}
    for q in net.premises.values():
        st = status.get(q["public_id"])
        if st and q["transformer_id"]:
            by_xf.setdefault(q["transformer_id"], {k: 0 for k in STATUS_RANK})[st] += 1
    xf_impacts = [s.TransformerImpact(id=k, status=max((st for st, n in v.items() if n), key=STATUS_RANK.get),
                                      repair_dependent=v["repair_dependent"],
                                      isolation_candidate=v["isolation_candidate"], unresolved=v["unresolved"])
                  for k, v in by_xf.items()]

    # the operator-view locations sit next to a critical facility: no coordinates and no map impacts,
    # whichever scenario id the request uses
    hidden = {l.public_id for l in critical_scenario(net).locations} if net.critical else set()
    if hidden & {l.public_id for l in selected}:
        xf_impacts = []

    interrupted = sum(counts[k] for k in ("repair_dependent", "isolation_candidate", "unresolved"))
    step = (f"{interrupted} of {len(net.premises)} premises on {net.label} would lose power initially. "
            f"{counts['repair_dependent']} have damage on their own supply path (or their own equipment) and would "
            f"wait for repairs. {counts['isolation_candidate']} are on branches that a mapped switch could separate "
            f"from the damage, so they could potentially be restored earlier by isolating the damaged section and "
            f"re-closing the device that opened. {counts['unresolved']} share the device that opened but no mapped "
            f"switch separates them from the damage, so earlier restoration for them is unresolved.")
    return s.ScenarioResult(
        scenario_id=scen.id, scenario_label=scen.label, state="simulated",
        disclaimer=("Simulated damage, not a real outage. Restoration possibilities are a simplified model, not "
                    "field switching instructions or confirmed utility actions. No alternate feeds, remote switching "
                    "or automatic re-energization are assumed."),
        active_locations=[s.ScenarioLocation(id=l.public_id, label=l.label,
                                             location=None if l.public_id in hidden else _ll(l.lonlat))
                          for l in selected],
        circuit_premises=len(net.premises), initially_interrupted=interrupted,
        repair_dependent=counts["repair_dependent"], isolation_candidates=counts["isolation_candidate"],
        unresolved=counts["unresolved"], not_interrupted=counts["not_interrupted"],
        selected_premise=s.PremiseImpact(status=my, headline=headline, reasons=reasons,
                                         devices_involved=sorted(set(devices))),
        step_restoration=step, transformer_impacts=xf_impacts,
        critical_facilities=[s.CriticalImpact(kind=f["kind"], status=status.get(f["rep_premise"], "not_interrupted"))
                             for f in net.critical],
        assumptions=["Each damaged span is cleared by the nearest protective device upstream of it.",
                     "Isolation is counted only where a mapped, normally closed switch on a known branch separates "
                     "the damage from a premise's supply path.",
                     "No alternate feeds (ties to other circuits), remote switching or automatic re-energization.",
                     "A damaged transformer or protective device must be repaired before its customers are restored."])


def _ll(lonlat):
    return s.LatLon(lat=lonlat[1], lon=lonlat[0]) if lonlat else None


def scenario_catalog_response(net: CircuitNetwork, p: dict) -> s.ScenarioCatalog:
    return s.ScenarioCatalog(premise_id=p["public_id"], scenarios=[
        s.ScenarioOption(id=sc.id, label=sc.label, description=sc.description, mode=sc.mode,
                         available=sc.unavailable_reason is None, unavailable_reason=sc.unavailable_reason,
                         locations=[s.ScenarioLocation(id=l.public_id, label=l.label, location=_ll(l.lonlat))
                                    for l in sc.locations],
                         default_location_ids=sc.defaults)
        for sc in catalog(net, p)])


def resolve_fixed(net: CircuitNetwork, scenario_id: str, label: str, location_ids: list[str]) -> Scenario:
    """A fixed scenario definition: the same locations whichever premise is evaluated."""
    if not location_ids:
        raise ValueError("select at least one damage location")
    idx = location_index(net)
    unknown = [i for i in location_ids if i not in idx]
    if unknown:
        raise LookupError(f"location(s) not on this circuit: {', '.join(unknown[:5])}")
    locs = [idx[i] for i in dict.fromkeys(location_ids)]  # de-duplicate, keep order
    return Scenario(id=scenario_id, label=label, description="", mode="multi", locations=locs,
                    defaults=[l.public_id for l in locs])


def run(net: CircuitNetwork, p: dict, scenario_id: str, location_ids: list[str] | None) -> s.ScenarioResult:
    scen = next((sc for sc in catalog(net, p) if sc.id == scenario_id), None)
    if scen is None:
        raise KeyError(f"unknown scenario {scenario_id}")
    if scen.unavailable_reason:
        raise ValueError(scen.unavailable_reason)
    by_id = {l.public_id: l for l in scen.locations}
    ids = scen.defaults if location_ids is None else location_ids
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise LookupError(f"location(s) not part of this scenario: {', '.join(unknown)}")
    if scen.mode == "single" and len(ids) != 1:
        raise ValueError("this scenario takes exactly one damage location")
    if not ids:
        raise ValueError("select at least one damage location")
    return evaluate(net, p, scen, [by_id[i] for i in ids])


__all__ = ["catalog", "run", "scenario_catalog_response", "KIND_LABELS"]
