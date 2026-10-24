"""Generate docs/data_inspection_report.md and data/processed/inspection_summary.json.

Usage:  python pipeline/inspect_data.py [--circuits 0000018 0000072 ...]
"""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import date

import openpyxl
import pandas as pd
import pyogrio
from pyproj import CRS

import circuit as cm
from common import DOCS, LABOR_XLSX, LAYERS, PROCESSED, RAW_DIR, UPSTREAM_TXT, layer_path
from matching import MAX_MATCH_M, SECONDARY_TO_TRANSFORMER_M
from privacy import classify
from topology import GAP_BRIDGE_M, MAX_BRIDGE_EDGES, SNAP_M

DEFAULT_CIRCUITS = ["0000018", "0000072", "0000036", "0000010", "0000002"]


def crs_label(wkt) -> str:
    crs = CRS.from_user_input(wkt)
    if crs.is_compound:
        horiz = crs.sub_crs_list[0]
        return f"{crs.name} (horizontal EPSG:{horiz.to_epsg()})"
    return f"{crs.name} (EPSG:{crs.to_epsg()})"


def md_table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |")
    return "\n".join(out)


def profile_layer(name: str) -> dict:
    path = layer_path(name)
    info = pyogrio.read_info(path)
    df = pyogrio.read_dataframe(path, read_geometry=False)
    companions = sorted(p.suffix for p in path.parent.glob(path.stem + ".*"))
    cols = []
    for c in df.columns:
        cls = classify(name, c)
        s = df[c]
        example = ""
        if cls != "sensitive":
            nn = s.dropna()
            example = str(nn.iloc[0])[:40] if len(nn) else ""
        cols.append(dict(column=c, dtype=str(s.dtype), non_null_pct=round(100 * s.notna().mean(), 1),
                         unique=int(s.nunique()), classification=cls,
                         example=example if cls != "sensitive" else "(withheld)"))
    return dict(layer=name, file=f"{LAYERS[name][0]}/{path.name}", records=int(info["features"]),
                geometry=info["geometry_type"], crs=crs_label(info["crs"]), companions=" ".join(companions),
                columns=cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--circuits", nargs="*", default=DEFAULT_CIRCUITS)
    args = ap.parse_args()

    print("profiling layers ...")
    layers = {n: profile_layer(n) for n in LAYERS}
    print("loading context ...")
    ctx = cm.load_context()
    up = ctx.upstream
    cust = ctx.customer

    joins = []

    def jrow(name, num, den, note=""):
        joins.append(dict(join=name, matched=num, total=den, rate=f"{100 * num / den:.2f}%" if den else "n/a",
                          note=note))

    up_prem = set(up.premise)
    cprem = set(cust.premise_nu)
    jrow("Customer.premise_nu -> matched_upstream premise", len(cprem & up_prem), len(cprem), "direct key")
    jrow("matched_upstream premise -> Customer.premise_nu", len(up_prem & cprem), len(up_prem), "direct key")
    jrow("Customer.aep_xfmr_l -> Transformer.location_n", int(cust.aep_xfmr_l.isin(set(ctx.transformer.location_n)).sum()),
         len(cust), "location number")
    xf_up = up[(up.source == "eo_power_xfrmr_inst") & (up.position == 0)]
    jrow("upstream nearest transformer id -> Transformer.id", int(xf_up.feature_id.isin(set(ctx.transformer.id)).sum()),
         len(xf_up), "feature id")
    first_xf = dict(zip(xf_up.premise, xf_up.location))
    agree = sum(first_xf.get(p) == x for p, x in zip(cust.premise_nu, cust.aep_xfmr_l) if p in first_xf)
    jrow("Customer.aep_xfmr_l == upstream nearest transformer location", agree, len(first_xf.keys() & cprem),
         "consistency of two sources")
    iso = up[up.source == "eo_isolating_eqpt_inst"].drop_duplicates("feature_id")
    dev_ids = set(ctx.fuse.id) | set(ctx.recloser.id) | set(ctx.switch.id)
    jrow("upstream isolating-device ids -> Fuse/Recloser/Switch.id", int(iso.feature_id.isin(dev_ids).sum()), len(iso),
         "unmatched ids may sit outside the clip or in layers not supplied")
    brk = up[up.source == "eo_circuit"].drop_duplicates("premise")
    cust_cid = dict(zip(cust.premise_nu, cust.circuit_id))
    agree = sum(cust_cid.get(p) == l for p, l in zip(brk.premise, brk.location) if p in cust_cid)
    jrow("Customer.circuit_id == upstream breaker circuit", agree, len(set(brk.premise) & cprem), "")
    name_to_id = dict(zip(ctx.primary.aep_circui, ctx.primary.circuit_id))
    lab = ctx.damage.Circuit
    jrow("ARCOS Circuit label -> Primary.aep_circui", int(lab.isin(name_to_id.keys()).sum()), len(lab),
         "labels like TINKER / SERVICE CENTER have no GIS circuit")
    dm = ctx.damage_match
    jrow("ARCOS record -> same-type asset (spatial, capped)", int((dm.match_status == "matched").sum()), len(dm),
         f"cap {MAX_MATCH_M} m; secondary->transformer cap {SECONDARY_TO_TRANSFORMER_M} m")
    jrow("ARCOS record matched only via other-circuit asset (label fallback)", int(dm.label_fallback.sum()), len(dm),
         "label disagrees with GIS circuit of nearest asset")

    dist = (dm[dm.match_status == "matched"].groupby("layer").match_dist_m
            .describe(percentiles=[.5, .9]).round(2).reset_index())
    dist_rows = dist.rename(columns={"50%": "p50_m", "90%": "p90_m", "max": "max_m"}).to_dict("records")

    chain_len = up.groupby("premise").size()
    elem_counts = up.groupby(["source", "device_type"]).size().reset_index(name="count").to_dict("records")

    dmg = ctx.damage
    dmg_summary = {c: dmg[c].value_counts(dropna=False).head(12).to_dict() for c in
                   ["Asset_Type", "Inform_Wor", "Media", "Access_Iss", "Special_Eq", "Repaired", "Event"]}
    by_day = dmg.Report_Tim.dt.date.value_counts().head(10)
    span = (dmg.Repaired_D - dmg.Report_Tim).dt.days
    sentinel = int((dmg.Repaired_D.dt.date == date(2025, 10, 24)).sum())

    print("building circuit models ...")
    circuits = []
    for cid in args.circuits:
        s = cm.build_circuit_model(ctx, cid)["stats"]
        circuits.append(s)

    wb = openpyxl.load_workbook(LABOR_XLSX, data_only=False)
    sheets = [dict(sheet=ws.title, dimensions=ws.dimensions, rows=ws.max_row) for ws in wb.worksheets]

    region = (cust.groupby("circuit_id").size().rename("premises").to_frame()
              .join(ctx.primary.assign(km=ctx.primary.length / 1000)
                    .pivot_table(index="circuit_id", columns="mounting", values="km", aggfunc="sum").round(2))
              .join(dm[dm.match_status == "matched"].groupby("asset_circuit").size().rename("matched_damage")))

    summary = dict(generated=str(date.today()), layers={k: {kk: vv for kk, vv in v.items() if kk != "columns"}
                                                        for k, v in layers.items()},
                   joins=joins, match_distance=dist_rows, circuits=circuits,
                   upstream=dict(rows=len(chain_len), elements=len(up),
                                 malformed=int(up.malformed.notna().sum()),
                                 chain_length=chain_len.describe().round(2).to_dict()))
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "inspection_summary.json").write_text(json.dumps(summary, indent=1, default=str))

    L = []
    L.append("# Data inspection report\n")
    L.append(f"Generated by `pipeline/inspect_data.py` on {date.today()}. Source: `{RAW_DIR.relative_to(RAW_DIR.parents[1])}` "
             "(read-only; archives extracted by `pipeline/extract.py`). Re-run the script to regenerate.\n")
    L.append("Projected CRS for distances: **EPSG:32617 (WGS 84 / UTM 17N)** - the study area is around 80 W, 37 N. "
             "Display CRS: **EPSG:4326**. Point layers carry Z values; Z is dropped on load.\n")
    L.append("## 1. Layers\n")
    L.append(md_table([{k: v for k, v in l.items() if k != "columns"} for l in layers.values()],
                      ["layer", "file", "records", "geometry", "crs", "companions"]))
    L.append(f"\n\n`matched_upstream.txt`: {len(chain_len):,} premise rows, {len(up):,} upstream elements, "
             f"{int(up.malformed.notna().sum())} malformed tokens. Format: `premise<TAB>source*feature_id*type*location<TAB>...`, "
             "ordered nearest element first, circuit breaker last.\n")
    L.append(md_table(elem_counts, ["source", "device_type", "count"]))
    L.append(f"\n\nChain length (elements per premise): {chain_len.describe().round(1).to_dict()}\n")
    L.append(f"\n`Install_Labor_HackOHIO.xlsx` sheets:\n\n" + md_table(sheets, ["sheet", "dimensions", "rows"]))
    L.append("\n\n`structure_drawings.pdf`: 9 image-only pages (no extractable text). Reviewed visually: transformer "
             "pole (cutout + fuse link, arrester, bracket, transformer, grounding, connectors, secondary), single-phase "
             "pin-top tangent, three-phase crossarm, primary dead-end with guy + anchor, tap / junction structures.\n")

    L.append("\n## 2. Columns, missing values and customer-facing classification\n")
    L.append("Classification: **customer-safe** (may reach the browser, possibly bucketed), **internal** (server-side "
             "only), **sensitive** (never written to processed outputs; examples withheld).\n")
    for l in layers.values():
        L.append(f"\n### {l['layer']} ({l['records']:,} records)\n")
        L.append(md_table(l["columns"], ["column", "dtype", "non_null_pct", "unique", "classification", "example"]))
    L.append("\n\n## 3. Candidate identifiers and joins\n")
    L.append(md_table(joins, ["join", "matched", "total", "rate", "note"]))
    L.append("\n\nDamage match distance by matched layer (metres, projected):\n\n")
    L.append(md_table(dist_rows, ["layer", "count", "mean", "p50_m", "p90_m", "max_m"]))
    L.append(f"\n\nARCOS points are already snapped onto assets (median 0 m), so a {MAX_MATCH_M} m cap rejects only "
             f"records without any same-type asset nearby. Secondary-wire damage is attributed to the nearest service "
             f"transformer within {SECONDARY_TO_TRANSFORMER_M} m and labelled as an approximation.\n")
    L.append("\n## 4. ARCOS damage assessments\n")
    for c, v in dmg_summary.items():
        L.append(f"- **{c}**: {v}")
    L.append(f"- **Report dates** (top days): {{{', '.join(f'{k}: {v}' for k, v in by_day.items())}}}")
    L.append(f"- Report_Tim and Repaired_D are **date-only**; `Repaired_D - Report_Tim` days: "
             f"{span.describe().round(1).to_dict()}. {sentinel} records carry Repaired_D = 2025-10-24, which looks like "
             "an extract-date placeholder (most have Repaired = 'No'). Durations are therefore day-granular and are "
             "not used as restoration-hour targets.")
    L.append("- `Outage_Num` and `Incident_W` are all zero; `Status`, `District`, `Crew_Area` and task fields are empty. "
             "There is no customer-outage count or customer-minutes field, so records describe damage, not outages.")
    L.append("- `Media` meaning is not documented; values 0-6. Treated as an *unverified* possible quantity field and "
             "not used in calculations.")
    L.append("- `NEAR_FID` / `NEAR_DIST` are from an upstream snapping step (distance in degrees). The target layer "
             "is not stated, so matching is recomputed here.\n")

    L.append("\n## 5. Network topology by circuit\n")
    L.append(f"Graph nodes are structure location numbers. Segment ends are snapped to pole/device points within "
             f"{SNAP_M} m; pieces within {GAP_BRIDGE_M} m are joined with flagged gap edges; remaining pieces may be "
             f"joined through <= {MAX_BRIDGE_EDGES} neighbouring-circuit edges. The root is the leaf whose orientation "
             "best agrees with the `upstream_l` device hierarchy. *Chain consistency* checks that every upstream device "
             "listed for a premise is an ancestor of that premise's transformer in the oriented tree.\n")
    ccols = ["circuit_name", "premises", "premises_with_oriented_transformer", "graph_main_nodes", "graph_gap_bridges",
             "graph_bridge_edges", "graph_dropped_components", "root_consistency", "chain_ancestor_checks",
             "chain_consistency", "damage_records", "damage_on_network", "overhead_km", "underground_km"]
    L.append(md_table(circuits, ccols))
    L.append("\n\n**Demo subset: CIR18 (`0000018`).** All premises sit on one oriented network, the root agrees with "
             "every `upstream_l` pair, every upstream-chain ancestry check passes, and it has a large share of the "
             "Feb 2025 storm damage. Other circuits can be built with `build_subset.py --circuits ...`; circuits with "
             "lower consistency should be shown with lower confidence. Circuits whose root consistency is `None` "
             "had no device/transformer locations on the built graph and cannot be oriented with this method yet; "
             "premises there must fall back to the upstream file's device chain without network geometry.\n")
    L.append("\n### Region-level circuit table (premises, primary km by mounting, matched damage)\n")
    reg = region.reset_index().rename(columns={"index": "circuit_id"}).fillna(0).to_dict("records")
    L.append(md_table(reg, ["circuit_id", "premises", "Overhead", "Underground", "matched_damage"]))

    L.append("\n\n## 6. Unmatched / missing records\n")
    L.append(f"- Customers not in upstream file: {len(cprem - up_prem)}; upstream premises not in customer layer: "
             f"{len(up_prem - cprem)}.")
    L.append(f"- Upstream isolating-device ids not found in the supplied device layers: "
             f"{int((~iso.feature_id.isin(dev_ids)).sum())} distinct ids. Their location numbers are still usable "
             "for chain ordering.")
    L.append(f"- ARCOS records unmatched (beyond cap): {int((dm.match_status == 'unmatched_beyond_cap').sum())}; "
             f"not modelled (lights, capacitors): {int((dm.match_status == 'not_modelled_asset_type').sum())}; "
             f"missing asset type: {int((dm.match_status == 'missing_asset_type').sum())}.")
    L.append("- Customer `address`, `address_nu`, `macss_mete`, `special_op` are entirely empty.\n")

    L.append("\n## 7. Fields that may be shown to customers\n")
    L.append("Only fields classified **customer-safe** above reach the browser, through explicit response "
             "models (`backend/app/schemas.py`). In particular:\n")
    L.append("- Premises are shown by a salted-hash ID (`PRM-XXXXXXXX`), service type (Overhead / Underground), "
             "single vs multi-unit, and circuit label. Source premise numbers never leave the server.")
    L.append("- The map overview shows service transformers (equipment), not homes. The selected premise's own point "
             "is shown only for that premise.")
    L.append("- `critical_c` (life-support flag) is **never** used or exposed. Medical / accessibility needs come only "
             "from what the user declares in the app.")
    L.append("- Road names, city, street codes, house-number annotations, SCADA ids, global ids and raw location "
             "numbers are internal.")
    L.append("- Historical damage is labelled as historical, shown with date, asset and damage category, and its point "
             "is rounded to ~100 m for display.")
    L.append("- Hospital / fire / ambulance layers are public data but are not shown on the customer map; precise "
             "sensitive-facility locations are not exposed.\n")
    DOCS.mkdir(exist_ok=True)
    (DOCS / "data_inspection_report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {DOCS / 'data_inspection_report.md'} and {PROCESSED / 'inspection_summary.json'}")


if __name__ == "__main__":
    main()
