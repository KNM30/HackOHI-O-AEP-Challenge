"""Build the processed demo subset consumed by the backend.

Usage:  python pipeline/build_subset.py [--circuits 0000018 ...]

Writes data/processed/circuits/<circuit_id>/{model.json,lines.geojson} and
data/processed/region_circuits.json. Source premise numbers and per-device premise
lists are dropped before writing.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

import pandas as pd

import circuit as cm
import critical
from common import DISPLAY_CRS, PROCESSED, public_id
from matching import MAX_MATCH_M, SECONDARY_TO_TRANSFORMER_M
from topology import GAP_BRIDGE_M, MAX_BRIDGE_EDGES, SNAP_M

# 0000018: demo circuit. 0000109: serves a fire station and an ambulance station (critical-facility demo).
DEMO_CIRCUITS = ["0000018", "0000109"]
EVENT_WINDOW = ("2025-02-12", "2025-02-18")  # largest storm event in the ARCOS extract


def _round_coords(coords):
    return [[round(x, 6), round(y, 6)] for x, y in coords]


def circuit_doc(model: dict, cid: str, facility_links) -> dict:
    """The model.json document (allowlisted fields) for a built circuit model."""
    premises = [{k: v for k, v in p.items() if k != "_premise"} for p in model["premises"]]
    devices = {d["public_id"]: {k: v for k, v in d.items() if k != "zone_premises"}
               for d in model["devices"].values()}
    transformers = {t["public_id"]: t for t in model["transformers"].values()}
    doc = dict(
        generated=str(date.today()),
        circuit_id=cid,
        label=f"Circuit {int(cid)}",
        stats=model["stats"],
        parameters=dict(snap_m=SNAP_M, gap_bridge_m=GAP_BRIDGE_M, max_bridge_edges=MAX_BRIDGE_EDGES,
                        damage_match_cap_m=MAX_MATCH_M,
                        secondary_to_transformer_cap_m=SECONDARY_TO_TRANSFORMER_M),
        root=model["stats"]["root"],
        nodes=model["nodes"],
        devices=devices,
        transformers=transformers,
        premises=premises,
        damage=model["damage"],
        critical_facilities=critical.for_circuit(facility_links, cid, model["transformers"]),
        critical_match_cap_m=critical.CRITICAL_MATCH_M,
    )
    return doc


def write_circuit(ctx: cm.Context, cid: str, facility_links) -> dict:
    model = cm.build_circuit_model(ctx, cid)
    out = PROCESSED / "circuits" / cid
    out.mkdir(parents=True, exist_ok=True)
    doc = circuit_doc(model, cid, facility_links)
    (out / "model.json").write_text(json.dumps(doc, default=str), encoding="utf-8")

    # display lines: allowlisted properties only
    seg_info = {}
    for u, v, e in model["H"].edges(data=True):
        for s in e["segs"]:
            seg_info[s] = e
    segs = ctx.primary[ctx.primary.id.isin(seg_info.keys())].to_crs(DISPLAY_CRS)
    feats = []
    for r in segs.itertuples():
        e = seg_info[int(r.id)]
        feats.append(dict(type="Feature",
                          geometry=dict(type="LineString", coordinates=_round_coords(r.geometry.coords)),
                          properties=dict(id=public_id("SEG", int(r.id)), usage=r.usage, mounting=r.mounting,
                                          bridge=bool(e["bridge"]))))
    (out / "lines.geojson").write_text(json.dumps(dict(type="FeatureCollection", features=feats)), encoding="utf-8")
    s = model["stats"]
    print(f"  {cid}: {s['premises']} premises, {len(doc['devices'])} devices, {len(doc['transformers'])} transformers, "
          f"{len(feats)} line features, {s['damage_records']} damage records "
          f"({s['damage_on_network']} on network), chain consistency {s['chain_consistency']}, "
          f"{len(doc['critical_facilities'])} critical facilities linked")
    return s


def region_table(ctx: cm.Context) -> list[dict]:
    """Per-circuit exposure and historical-damage counts for relative risk context."""
    name_to_id = dict(zip(ctx.primary.aep_circui, ctx.primary.circuit_id))
    dm = ctx.damage_match.copy()
    dm["circuit"] = dm.asset_circuit.where(dm.asset_circuit.notna(), dm.arcos_circuit.map(name_to_id))
    dm["date"] = ctx.damage.Report_Tim.values
    dm["in_event"] = dm.date.between(*EVENT_WINDOW)
    km = (ctx.primary.assign(km=ctx.primary.length / 1000)
          .pivot_table(index="circuit_id", columns="mounting", values="km", aggfunc="sum").fillna(0))
    prem = ctx.customer.groupby("circuit_id").size()
    rows = []
    for cid in sorted(set(km.index) | set(prem.index)):
        d = dm[dm.circuit == cid]
        oh = float(km.loc[cid].get("Overhead", 0)) if cid in km.index else 0.0
        ug = float(km.loc[cid].get("Underground", 0)) if cid in km.index else 0.0
        rows.append(dict(circuit_id=cid, premises=int(prem.get(cid, 0)), overhead_km=round(oh, 2),
                         underground_km=round(ug, 2), damage_records=len(d),
                         event_damage_records=int(d.in_event.sum()),
                         event_damage_per_overhead_km=round(int(d.in_event.sum()) / oh, 3) if oh > 0.5 else None))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--circuits", nargs="*", default=DEMO_CIRCUITS)
    args = ap.parse_args()
    print("loading source layers ...")
    ctx = cm.load_context()
    print("building circuits ...")
    links = critical.link_facilities(critical.load_facilities(), ctx.transformer)
    built = [write_circuit(ctx, cid, links) for cid in args.circuits]
    region = region_table(ctx)
    (PROCESSED / "region_circuits.json").write_text(json.dumps(dict(
        generated=str(date.today()), event_window=EVENT_WINDOW, circuits=region), indent=1), encoding="utf-8")
    (PROCESSED / "index.json").write_text(json.dumps(dict(
        generated=str(date.today()),
        circuits=[dict(circuit_id=s["circuit_id"], label=f"Circuit {int(s['circuit_id'])}", premises=s["premises"])
                  for s in built]), indent=1), encoding="utf-8")
    print(f"wrote {PROCESSED}")


if __name__ == "__main__":
    main()
