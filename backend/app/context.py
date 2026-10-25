"""Assemble the customer-facing network context for a premise (confirmed data only)."""
from __future__ import annotations

from collections import Counter

from . import schemas as s
from .config import DISPLAY_ROUND_DECIMALS
from .network import CircuitNetwork

KIND_LABELS = {
    "fuse": "Branch-line fuse",
    "recloser": "Automatic recloser",
    "sectionalizer": "Sectionalizer",
    "step_transformer": "Step transformer",
    "switch": "Manual switch",
    "breaker": "Substation circuit breaker",
}


def latlon(lonlat) -> s.LatLon | None:
    return s.LatLon(lat=lonlat[1], lon=lonlat[0]) if lonlat else None


def approx_latlon(lonlat) -> s.LatLon | None:
    """Rounded point (~100 m) for anything that could identify a home."""
    r = DISPLAY_ROUND_DECIMALS
    return s.LatLon(lat=round(lonlat[1], r), lon=round(lonlat[0], r)) if lonlat else None


def bucket(n: int | None) -> str:
    if n is None:
        return "unknown"
    if n < 10:
        return "fewer than 10"
    if n < 100:
        return f"about {round(n, -1)}"
    return f"about {round(n, -2) if n >= 1000 else round(n, -1)}"


def device_label(dev: dict) -> str:
    base = KIND_LABELS.get(dev["kind"], dev["device_type"] or dev["kind"])
    if dev["kind"] == "recloser" and dev.get("device_type"):
        return f"{base} ({dev['device_type'].split('(')[-1].rstrip(')').lower()})"
    return base


def supply_path(net: CircuitNetwork, xf_node: str | None) -> s.SupplyPath | None:
    if xf_node is None or xf_node not in net.nodes:
        return None
    path = net.path_to_root(xf_node)
    km = Counter()
    gaps = 0
    coords = []
    for n in path:
        node = net.nodes[n]
        if node["lonlat"]:
            coords.append([node["lonlat"][1], node["lonlat"][0]])
        e = node["edge"]
        if e:
            km[e["mounting"] if e["mounting"] in ("Overhead", "Underground") else "Unknown"] += e["length_m"] / 1000
            gaps += e["usage"] == "gap"
    return s.SupplyPath(length_km=round(sum(km.values()), 2), overhead_km=round(km["Overhead"], 2),
                        underground_km=round(km["Underground"], 2), unknown_km=round(km["Unknown"], 2),
                        structures=len(path), approximated_gaps=gaps, coordinates=coords)


def historical_damage(net: CircuitNetwork, premise: dict) -> s.HistoricalDamageSummary:
    records, counts = [], Counter()
    placed = 0
    for d in net.damage:
        rel = net.relation(premise, d)
        if rel is None:
            continue
        placed += 1
        if rel.same_transformer:
            kind = "own_transformer"
        elif rel.on_supply_path:
            kind = "on_supply_path"
        elif rel.affects_premise:
            kind = "same_protection_zone"
        else:
            continue
        counts[kind] += 1
        records.append(s.HistoricalDamage(
            id=d["public_id"], report_date=d["report_date"], asset_type=d["asset_type"],
            damage_type=d["damage_type"], access_issue=d["access_issue"], repaired=d["repaired"], relation=kind,
            approx_location=approx_latlon(d["lonlat"])))
    records.sort(key=lambda x: (x.report_date or ""), reverse=True)
    by_date = Counter((x.report_date or "unknown")[:7] for x in records)
    return s.HistoricalDamageSummary(
        note=("Historical ARCOS damage assessments (2022-2026 extract). These are past records, not current "
              "conditions, and they describe damage rather than confirmed customer outages."),
        circuit_records=len(net.damage), circuit_records_placed=placed,
        own_transformer=counts["own_transformer"], on_supply_path=counts["on_supply_path"],
        same_protection_zone=counts["same_protection_zone"], by_date=dict(sorted(by_date.items())),
        records=records)


FLAG_TEXT = {
    "not_in_upstream_file": "This premise is not in the upstream relationship file; its device chain is unknown.",
    "transformer_from_customer_layer": "Service transformer taken from the customer layer instead of the upstream file.",
    "customer_layer_transformer_differs": "Customer layer and upstream file name different service transformers.",
    "transformer_not_on_oriented_network": "The service transformer could not be placed on the network map.",
}


def premise_context(net: CircuitNetwork, p: dict) -> s.PremiseContext:
    tr = net.transformers.get(p["transformer_id"]) if p["transformer_id"] else None
    chain = []
    for i, dev_id in enumerate(p["chain"]):
        dev = net.devices[dev_id]
        chain.append(s.ChainElement(id=dev_id, kind=dev["kind"], label=device_label(dev), position=i,
                                    customers_behind=bucket(dev.get("zone_premise_count")),
                                    location=latlon(dev.get("lonlat") or (net.nodes.get(dev["node"]) or {}).get("lonlat"))))
    root = net.nodes.get(net.model["root"], {})
    chain.append(s.ChainElement(id=f"BRK-{net.circuit_id}", kind="breaker", label=KIND_LABELS["breaker"],
                                position=len(chain), customers_behind=bucket(len(net.premises)),
                                location=latlon(root.get("lonlat"))))
    notes = [FLAG_TEXT.get(f, f) for f in p["data_flags"]]
    path = supply_path(net, p["transformer_node"])
    if path and path.approximated_gaps:
        notes.append(f"{path.approximated_gaps} short mapping gap(s) on the supply path were bridged by proximity.")
    notes.append("The feeder head location is inferred from the device hierarchy; the substation itself is not "
                 "in the supplied layers.")
    pending = "Not calculated yet - this part of the assistant is still being built."
    return s.PremiseContext(
        premise=s.PremiseInfo(id=p["public_id"], circuit_id=net.circuit_id, circuit_label=net.label, service_type=p["service_type"],
                              meters=p["meters"], location=approx_latlon(p["lonlat"])),
        transformer=s.TransformerInfo(id=tr["public_id"], mounting=tr.get("mounting"), structure=tr.get("structure"),
                                      premises_served=tr["premise_count"]) if tr else None,
        upstream_chain=chain,
        supply_path=path,
        historical_damage=historical_damage(net, p),
        data_quality=s.DataQuality(flags=p["data_flags"],
                                   circuit_root_consistency=net.stats.get("root_consistency"),
                                   circuit_chain_consistency=net.stats.get("chain_consistency"), notes=notes),
        predictions=s.Predictions(
            restoration=s.PendingCard(status="not_calculated",
                                      message="Restoration time is estimated only for a simulated damage scenario. "
                                              "Run one in the What-if damage card."),
            guidance=s.PendingCard(status="not_calculated", message=pending),
            alerts=s.PendingCard(status="not_calculated", message=pending)),
    )


def circuit_map(net: CircuitNetwork, lines: dict) -> s.CircuitMap:
    xfs = [s.MapPoint(id=t["public_id"], kind="transformer", label="Service transformer",
                      location=latlon(t["lonlat"]), premises_served=t["premise_count"])
           for t in net.transformers.values() if t.get("lonlat")]
    devs = [s.MapPoint(id=d["public_id"], kind=d["kind"], label=device_label(d), location=latlon(d["lonlat"]))
            for d in net.devices.values() if d.get("lonlat") and d["kind"] in ("fuse", "recloser", "switch")]
    lats = [c[1] for f in lines["features"] for c in f["geometry"]["coordinates"]]
    lons = [c[0] for f in lines["features"] for c in f["geometry"]["coordinates"]]
    return s.CircuitMap(circuit_id=net.circuit_id, label=net.label,
                        bounds=[[min(lats), min(lons)], [max(lats), max(lons)]],
                        lines=lines, transformers=xfs, devices=devs)
