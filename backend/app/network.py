"""Oriented circuit network built from the processed model.

Conventions: a damage at node X means the structure at X or the span from
parent(X) to X. A device at node N with coverage [c1, ...] protects the spans
N->c1, ... and everything below them.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

# Devices that open automatically to clear a fault. Manual switches only isolate
# (they matter for step restoration); step transformers do neither.
PROTECTIVE_KINDS = {"fuse", "recloser", "sectionalizer"}
ISOLATING_KINDS = {"switch"}

# Historical records whose report dates are within this many days of the previous
# record are grouped into one storm event (dates are day-granular).
EVENT_GAP_DAYS = 2


def assign_events(damage: list[dict]) -> dict[str, str]:
    """Map damage public id -> event label ('2025-02-13..2025-02-17')."""
    dated = sorted({d["report_date"] for d in damage if d.get("report_date")})
    groups: list[list[str]] = []
    for ds in dated:
        if groups and (date.fromisoformat(ds) - date.fromisoformat(groups[-1][-1])).days <= EVENT_GAP_DAYS:
            groups[-1].append(ds)
        else:
            groups.append([ds])
    label = {ds: (g[0] if len(g) == 1 else f"{g[0]}..{g[-1]}") for g in groups for ds in g}
    return {d["public_id"]: label[d["report_date"]] for d in damage if d.get("report_date")}


@dataclass(frozen=True)
class Relation:
    affects_premise: bool  # the protective device that would clear this damage serves the premise
    on_supply_path: bool  # the damage sits on the premise's path to the substation
    same_transformer: bool
    protecting_device: str | None  # public id, None = substation breaker


class CircuitNetwork:
    def __init__(self, model: dict):
        self.model = model
        self.circuit_id: str = model["circuit_id"]
        self.label: str = model["label"]
        self.nodes: dict[str, dict] = model["nodes"]
        self.devices: dict[str, dict] = model["devices"]
        self.transformers: dict[str, dict] = model["transformers"]
        self.premises: dict[str, dict] = {p["public_id"]: p for p in model["premises"]}
        self.damage: list[dict] = model["damage"]
        self.stats: dict = model["stats"]
        # Critical facilities are linked to a service transformer (spatial approximation in the
        # pipeline). A facility depends on exactly what that transformer's premises depend on, so
        # one premise on the transformer stands in for it when tracing impact.
        self.critical: list[dict] = []
        by_xf: dict[str, dict] = {}
        for p in model["premises"]:
            by_xf.setdefault(p["transformer_id"], p)
        for f in model.get("critical_facilities", []):
            rep = by_xf.get(f["transformer_id"])
            if rep is not None:
                self.critical.append({**f, "rep_premise": rep["public_id"]})
        self._iso_cache: dict[tuple[str, str], dict | None] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        for n, nd in self.nodes.items():
            if nd["parent"] is not None:
                self.children[nd["parent"]].append(n)
        self.devices_at: dict[str, list[dict]] = defaultdict(list)
        for d in self.devices.values():
            if d.get("node") and d.get("coverage") is not None:
                self.devices_at[d["node"]].append(d)
        for lst in self.devices_at.values():
            lst.sort(key=lambda d: d.get("zone_premise_count", 0))
        # protective device (public id, None = breaker) for every span parent(n)->n
        self.protector: dict[str, str | None] = {}
        self.zone_km: dict[str | None, dict[str, float]] = defaultdict(
            lambda: {"Overhead": 0.0, "Underground": 0.0, "Unknown": 0.0})
        for n, nd in self.nodes.items():
            if nd["parent"] is None:
                continue
            dev = self.protecting_device(n)
            pid = dev["public_id"] if dev else None
            self.protector[n] = pid
            e = nd["edge"]
            m = e["mounting"] if e["mounting"] in ("Overhead", "Underground") else "Unknown"
            self.zone_km[pid][m] += e["length_m"] / 1000
        self.event_of = assign_events(self.damage)
        self._xf_tins = sorted(self.nodes[p["transformer_node"]]["tin"] for p in self.premises.values()
                               if p.get("transformer_node") in self.nodes)
        self.transformer_by_node = {t["node"]: t for t in self.transformers.values() if t.get("node")}

    # -- tree primitives
    def is_ancestor(self, a: str | None, b: str | None) -> bool:
        if a not in self.nodes or b not in self.nodes:
            return False
        na, nb = self.nodes[a], self.nodes[b]
        return na["tin"] <= nb["tin"] and nb["tout"] <= na["tout"]

    def path_to_root(self, node: str | None) -> list[str]:
        out = []
        while node is not None and node in self.nodes:
            out.append(node)
            node = self.nodes[node]["parent"]
        return out

    def protecting_device(self, node: str) -> dict | None:
        """Nearest upstream device whose coverage includes the damaged span.

        Returns None when no device is found before the root, meaning the
        substation breaker would clear the fault. Protective devices that appear in
        no premise's upstream chain are skipped: the upstream file is the
        authoritative dependency source, and using them would give a fault an empty
        interruption zone.
        """
        return self.protection_detail(node)[0]

    def protection_detail(self, node: str) -> tuple[dict | None, list[dict]]:
        """(device that opens, unevidenced protective devices passed over on the way).

        Sectionalizers do not interrupt fault current: they count the operations of
        an upstream recloser and open while it is open. One is therefore used as the
        sustained-outage boundary only if an evidenced recloser sits above it;
        otherwise the walk continues upward.
        """
        skipped: list[dict] = []
        child, cur = node, self.nodes.get(node, {}).get("parent")
        while cur is not None:
            for dev in self.devices_at.get(cur, ()):
                if dev["kind"] not in PROTECTIVE_KINDS or child not in dev["coverage"]:
                    continue
                if dev.get("zone_premise_count", 0) <= 0:
                    skipped.append(dev)
                    continue
                if dev["kind"] == "sectionalizer" and not self._recloser_above(cur):
                    skipped.append(dev)
                    continue
                return dev, skipped
            child, cur = cur, self.nodes[cur]["parent"]
        return None, skipped

    def _recloser_above(self, node: str) -> bool:
        child, cur = node, self.nodes[node]["parent"]
        while cur is not None:
            if any(d["kind"] == "recloser" and child in d["coverage"] and d.get("zone_premise_count", 0) > 0
                   for d in self.devices_at.get(cur, ())):
                return True
            child, cur = cur, self.nodes[cur]["parent"]
        return False

    def isolating_switch(self, node: str, xf_node: str) -> dict | None:
        """A normally-closed switch that separates damage at `node` from `xf_node`'s supply path.

        Walks up from the damaged span to the branch point (the first ancestor that
        also feeds `xf_node`). A switch on that stretch, covering the damaged side,
        could be opened so the tripped device can be re-closed. A switch is used only
        when the branch it sits on is known: evidenced coverage, or a structure with a
        single outgoing span.
        """
        key = (node, xf_node)
        if key not in self._iso_cache:
            self._iso_cache[key] = self._isolating_switch(node, xf_node)
        return self._iso_cache[key]

    def _isolating_switch(self, node: str, xf_node: str) -> dict | None:
        child, cur = node, self.nodes.get(node, {}).get("parent")
        while cur is not None:
            for dev in self.devices_at.get(cur, ()):
                known_branch = (dev.get("coverage_method") == "zone_transformers"
                                or len(self.children.get(cur, ())) == 1)
                if (dev["kind"] in ISOLATING_KINDS and child in dev["coverage"] and known_branch
                        and (dev.get("normal_state") or "Closed") == "Closed"):
                    return dev
            if self.is_ancestor(cur, xf_node):
                return None
            child, cur = cur, self.nodes[cur]["parent"]
        return None

    def interrupting_km(self, premise: dict) -> dict[str, float]:
        """Line length (by mounting) whose damage would trip a device this premise depends on.

        Sums the spans directly protected by each device in the premise's chain plus
        the breaker-protected spans. Includes the premise's own supply path.
        """
        out = {"Overhead": 0.0, "Underground": 0.0, "Unknown": 0.0}
        for pid in [*premise["chain"], None]:
            for k, v in self.zone_km.get(pid, {}).items():
                out[k] += v
        return out

    def downstream_count(self, node: str) -> int:
        """Premises whose service transformer is at or below `node`."""
        nd = self.nodes[node]
        return bisect_right(self._xf_tins, nd["tout"]) - bisect_left(self._xf_tins, nd["tin"])

    def premises_downstream(self, node: str) -> list[dict]:
        return [p for p in self.premises.values()
                if p.get("transformer_node") and self.is_ancestor(node, p["transformer_node"])]

    # -- premise relations
    def relation(self, premise: dict, dmg: dict) -> Relation | None:
        """How a damage record relates to a premise, or None if it cannot be placed."""
        xf_node = premise.get("transformer_node")
        layer = dmg.get("matched_layer")
        if dmg.get("match_status") != "matched":
            return None
        if layer in ("transformer", "secondary"):
            same = dmg.get("matched_ref") == premise.get("transformer_id")
            return Relation(same, same, same, None)
        node = dmg.get("node")
        if node is None or xf_node is None:
            return None
        ref = dmg.get("matched_ref")
        if layer in ("fuse", "recloser") and ref in self.devices:
            dev_id = ref  # the damaged protective device itself opens
        else:
            dev_id = self.protector.get(node)  # precomputed protecting_device(); root -> breaker (None)
        affects = dev_id is None or dev_id in premise["chain"]
        on_path = self.is_ancestor(node, xf_node)
        return Relation(affects or on_path, on_path, False, dev_id)
