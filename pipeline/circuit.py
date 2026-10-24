"""Load source layers once and build a per-circuit network model."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd
from pyproj import Transformer

import topology as topo
from common import DISPLAY_CRS, PROJECTED_CRS, circuit_name, parse_upstream, public_id, read_layer
from matching import match_damage

TO_WGS = Transformer.from_crs(PROJECTED_CRS, DISPLAY_CRS, always_xy=True)


@dataclass
class Context:
    customer: gpd.GeoDataFrame
    transformer: gpd.GeoDataFrame
    fuse: gpd.GeoDataFrame
    recloser: gpd.GeoDataFrame
    switch: gpd.GeoDataFrame
    pole: gpd.GeoDataFrame
    primary: gpd.GeoDataFrame
    damage: gpd.GeoDataFrame
    damage_match: pd.DataFrame
    upstream: pd.DataFrame
    graph: object
    loc_xy: dict
    timings: dict = field(default_factory=dict)

    def node_xy(self, node: str):
        if node in self.loc_xy:
            return self.loc_xy[node]
        if node.startswith("pt:"):
            _, x, y = node.split(":")
            return float(x), float(y)
        return None


def _proj(df):
    return df.to_crs(PROJECTED_CRS)


def load_context(verbose: bool = True) -> Context:
    t = {}

    def step(name, fn):
        s = time.time()
        v = fn()
        t[name] = round(time.time() - s, 1)
        if verbose:
            print(f"  loaded {name} in {t[name]}s")
        return v

    customer = step("customer", lambda: _proj(read_layer(
        "customer", ["id", "premise_nu", "aep_xfmr_l", "circuit_id", "kind_of_se", "customer_c"])))
    transformer = step("transformer", lambda: _proj(read_layer(
        "transformer", ["id", "location_n", "upstream_l", "circuit_id", "device_typ", "mounting",
                        "structure_", "a_phase_sp", "b_phase_sp", "c_phase_sp", "aep_custom"])))
    fuse = step("fuse", lambda: _proj(read_layer(
        "fuse", ["id", "location_n", "upstream_l", "circuit_id", "device_typ", "mounting", "aep_custom"])))
    recloser = step("recloser", lambda: _proj(read_layer(
        "recloser", ["id", "location_n", "upstream_l", "circuit_id", "device_typ", "aep_custom"])))
    switch = step("switch", lambda: _proj(read_layer(
        "switch", ["id", "location_n", "circuit_id", "device_typ", "mounting", "normal_sta"])))
    pole = step("pole", lambda: _proj(read_layer(
        "pole", ["location_n", "height", "class", "material", "date_insta", "usage"]).rename(
            columns={"class": "pole_class"})))
    primary = step("primary", lambda: _proj(read_layer(
        "primary", ["id", "circuit_id", "aep_circui", "location_n", "location_1", "usage", "mounting",
                    "phase_orde"])))
    damage = step("damage", lambda: _proj(read_layer("damage")))
    damage["record_index"] = range(len(damage))
    upstream = step("upstream", parse_upstream)
    s = time.time()
    tree, locs, loc_xy = topo.structure_index([pole, transformer, fuse, recloser, switch])
    G = topo.build_global_graph(primary, tree, locs)
    t["graph"] = round(time.time() - s, 1)
    if verbose:
        print(f"  built global graph ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges) in {t['graph']}s")
    dm = step("damage_match", lambda: _match_all_damage(damage, primary, pole, fuse, recloser, switch, transformer))
    return Context(customer, transformer, fuse, recloser, switch, pole, primary, damage, dm, upstream, G, loc_xy, t)


def _match_all_damage(damage, primary, pole, fuse, recloser, switch, transformer) -> pd.DataFrame:
    """Two-pass match of every ARCOS record.

    Pass 1 matches against assets on the circuit named by the ARCOS label (poles
    carry no circuit, so all poles are candidates). Shared structures put points
    at ~0 m from several circuits' lines, so the label breaks those ties.
    Pass 2 retries unmatched records against all circuits and is flagged
    `label_fallback`; the asset's own circuit is then used.
    """
    name_to_id = dict(zip(primary.aep_circui, primary.circuit_id))
    full = dict(primary=primary, pole=pole, fuse=fuse, recloser=recloser, switch=switch,
                transformer=transformer)
    parts = []
    for label, grp in damage.groupby("Circuit", dropna=False):
        cid = name_to_id.get(label)
        if cid is None:
            continue
        layers = {k: (v if k == "pole" else v[v.circuit_id == cid]) for k, v in full.items()}
        parts.append(match_damage(grp, layers))
    m = pd.concat(parts) if parts else pd.DataFrame()
    m = m.reindex(damage.index)
    m["label_fallback"] = False
    retry = m.match_status.isna() | (m.match_status == "unmatched_beyond_cap")
    if retry.any():
        m2 = match_damage(damage[retry], full)
        m2["label_fallback"] = m2.match_status == "matched"
        m.loc[retry, m2.columns] = m2
    circuit_of = {
        "primary": dict(zip(primary.id.astype(str), primary.circuit_id)),
        "fuse": dict(zip(fuse.id.astype(str), fuse.circuit_id)),
        "recloser": dict(zip(recloser.id.astype(str), recloser.circuit_id)),
        "switch": dict(zip(switch.id.astype(str), switch.circuit_id)),
        "transformer": dict(zip(transformer.id.astype(str), transformer.circuit_id)),
    }
    circuit_of["secondary"] = circuit_of["transformer"]
    m["asset_circuit"] = [circuit_of.get(lay, {}).get(str(k)) if k is not None else None
                          for lay, k in zip(m.layer, m.match_key)]
    m["arcos_circuit"] = damage.Circuit.values
    return m


def node_lonlat(ctx: Context, node: str):
    xy = ctx.node_xy(node)
    if xy is None:
        return None
    lon, lat = TO_WGS.transform(*xy)
    return [round(lon, 6), round(lat, 6)]


def _kva(*specs) -> float | None:
    total, found = 0.0, False
    for s in specs:
        if isinstance(s, str):
            m = re.search(r"([\d.]+)\s*kVA", s)
            if m:
                total += float(m.group(1))
                found = True
    return total if found else None


def _height_ft(s) -> float | None:
    if isinstance(s, str):
        m = re.search(r"(\d+)", s)
        if m:
            return float(m.group(1))
    return None


def _lonlat(geom):
    lon, lat = TO_WGS.transform(geom.x, geom.y)
    return [round(lon, 6), round(lat, 6)]


def build_circuit_model(ctx: Context, cid: str) -> dict:
    H, binfo = topo.circuit_graph(ctx.graph, cid, node_xy=ctx.node_xy)

    fuses = ctx.fuse[ctx.fuse.circuit_id == cid]
    recs = ctx.recloser[ctx.recloser.circuit_id == cid]
    sws = ctx.switch[ctx.switch.circuit_id == cid]
    xfs = ctx.transformer[ctx.transformer.circuit_id == cid]
    hierarchy = [(l, u) for d in (fuses, recs, xfs) for l, u in zip(d.location_n, d.upstream_l)
                 if isinstance(l, str) and isinstance(u, str) and u != "CIRCUIT"]
    top_level = [l for d in (fuses, recs) for l, u in zip(d.location_n, d.upstream_l) if u == "CIRCUIT"]
    root, rinfo = topo.choose_root(H, hierarchy, top_level)
    parent, children, order, tin, tout = topo.orient(H, root)
    depth = {root: 0}
    dist_m = {root: 0.0}
    for n in order[1:]:
        p = parent[n]
        depth[n] = depth[p] + 1
        dist_m[n] = dist_m[p] + H.edges[p, n]["length_m"]

    # ---- premises and their upstream chains (authoritative relationship file)
    cust = ctx.customer[ctx.customer.circuit_id == cid].copy()
    up = ctx.upstream[ctx.upstream.premise.isin(set(cust.premise_nu))]
    chains = {p: g.sort_values("position") for p, g in up.groupby("premise")}

    # device registry keyed by source feature id
    devices: dict[int, dict] = {}

    def reg_device(fid, kind, dtype, loc, extra=None):
        d = devices.get(fid)
        if d is None:
            d = devices[fid] = dict(public_id=public_id("DEV", fid), feature_id=int(fid), kind=kind,
                                    device_type=dtype, node=loc if loc in tin else None,
                                    location=loc, zone_premises=[], in_layer=False)
        if extra:
            d.update(extra)
        return d

    for d, kind in ((fuses, "fuse"), (recs, "recloser"), (sws, "switch")):
        for r in d.itertuples():
            reg_device(r.id, kind, r.device_typ, r.location_n,
                       dict(in_layer=True, lonlat=_lonlat(r.geometry),
                            mounting=getattr(r, "mounting", None),
                            normal_state=getattr(r, "normal_sta", None)))

    xf_by_id = {int(r.id): r for r in xfs.itertuples()}
    xf_by_loc = {r.location_n: r for r in xfs.itertuples()}
    transformers: dict[int, dict] = {}
    premises = []
    chain_checks = chain_ok = 0
    for r in cust.itertuples():
        ch = chains.get(r.premise_nu)
        flags = []
        chain_ids, xf_fid, xf_loc = [], None, None
        if ch is None:
            flags.append("not_in_upstream_file")
            xr = xf_by_loc.get(r.aep_xfmr_l)
            if xr is not None:
                xf_fid, xf_loc = int(xr.id), xr.location_n
                flags.append("transformer_from_customer_layer")
        else:
            for t in ch.itertuples():
                if t.source == "eo_power_xfrmr_inst" and t.device_type == "Distribution" and xf_fid is None:
                    xf_fid, xf_loc = t.feature_id, t.location
                elif t.source == "eo_isolating_eqpt_inst":
                    kind = "recloser" if "Recloser" in t.device_type else (
                        "fuse" if t.device_type == "Fuse" else t.device_type.lower())
                    d = reg_device(t.feature_id, kind, t.device_type, t.location)
                    d["zone_premises"].append(r.premise_nu)
                    chain_ids.append(t.feature_id)
                elif t.source == "eo_power_xfrmr_inst":  # step transformer mid-chain
                    d = reg_device(t.feature_id, "step_transformer", t.device_type, t.location)
                    d["zone_premises"].append(r.premise_nu)
                    chain_ids.append(t.feature_id)
            if r.aep_xfmr_l != xf_loc:
                flags.append("customer_layer_transformer_differs")
        xf_node = xf_loc if xf_loc in tin else None
        if xf_node is None:
            flags.append("transformer_not_on_oriented_network")
        else:
            for fid in chain_ids:
                n = devices[fid]["node"]
                if n is not None:
                    chain_checks += 1
                    chain_ok += topo.is_ancestor(tin, tout, n, xf_node)
        if xf_fid is not None:
            xr = xf_by_id.get(xf_fid)
            tr = transformers.setdefault(xf_fid, dict(
                public_id=public_id("XFR", xf_fid), feature_id=xf_fid, node=xf_node, location=xf_loc,
                lonlat=_lonlat(xr.geometry) if xr is not None else node_lonlat(ctx, xf_loc) if xf_loc else None,
                mounting=getattr(xr, "mounting", None), structure=getattr(xr, "structure_", None),
                kva=_kva(xr.a_phase_sp, xr.b_phase_sp, xr.c_phase_sp) if xr is not None else None,
                premise_count=0))
            tr["premise_count"] += 1
        premises.append(dict(
            public_id=public_id("PRM", r.premise_nu),
            _premise=r.premise_nu,
            service_type=r.kind_of_se if r.kind_of_se in ("Overhead", "Underground") else "Unknown",
            meters="single" if r.customer_c == 1 else "multi-unit",
            lonlat=_lonlat(r.geometry),
            transformer_id=transformers[xf_fid]["public_id"] if xf_fid in transformers else None,
            transformer_node=xf_node,
            chain=[devices[f]["public_id"] for f in chain_ids],
            data_flags=flags,
        ))

    # ---- device coverage: which child branches of the device's node it protects
    xf_nodes_by_premise = {p["_premise"]: p["transformer_node"] for p in premises}
    for d in devices.values():
        zone = {xf_nodes_by_premise.get(p) for p in d["zone_premises"]} - {None}
        d["zone_premise_count"] = len(d["zone_premises"])
        n = d["node"]
        if n is None:
            d["coverage"], d["coverage_method"] = None, "device_not_on_oriented_network"
            continue
        kids = children.get(n, [])
        covered = [c for c in kids if any(topo.is_ancestor(tin, tout, c, z) for z in zone)]
        if zone and covered:
            d["coverage"], d["coverage_method"] = covered, "zone_transformers"
        elif zone and n in zone:
            d["coverage"], d["coverage_method"] = [], "zone_at_device_node_only"
        else:
            d["coverage"], d["coverage_method"] = kids, "all_children_assumed"

    # ---- historical ARCOS damage on this circuit
    # A record belongs to this circuit if its matched asset does (poles have no
    # circuit field, so a pole counts if it is a node of this oriented network).
    # Unmatched records are kept when their ARCOS label names this circuit.
    dm = ctx.damage_match
    labelled_here = dm.arcos_circuit == circuit_name(cid)
    on_tree_pole = (dm.layer == "pole") & dm.match_key.isin(set(tin.keys()))
    keep = (labelled_here & ((dm.match_status != "matched") | (dm.layer == "pole") |
                             (dm.asset_circuit == cid))) | \
           (~labelled_here & dm.label_fallback & ((dm.asset_circuit == cid) | on_tree_pole))
    m = dm[keep]
    dmg = ctx.damage.loc[m.index]
    tree_poles = ctx.pole[ctx.pole.location_n.isin(tin.keys())]
    seg_child = {}
    for u, v, e in H.edges(data=True):
        child = v if parent.get(v) == u else u if parent.get(u) == v else None
        for s in e["segs"]:
            seg_child[s] = child
    damage = []
    for (i, r), (_, mr) in zip(dmg.iterrows(), m.iterrows()):
        node, ref = None, None
        if mr.match_status == "matched":
            key = mr.match_key
            if mr.layer == "primary":
                node = seg_child.get(int(key))
            elif mr.layer == "pole":
                node = key
            elif mr.layer in ("fuse", "recloser", "switch"):
                node = devices[int(key)]["node"] if int(key) in devices else None
                ref = devices[int(key)]["public_id"] if int(key) in devices else None
            elif mr.layer in ("transformer", "secondary"):
                tr = transformers.get(int(key))
                ref = tr["public_id"] if tr else public_id("XFR", int(key))
                node = xf_by_id[int(key)].location_n if int(key) in xf_by_id else None
            if node is not None and node not in tin:
                node = None
        lonlat = _lonlat(r.geometry)
        damage.append(dict(
            public_id=public_id("DMG", int(r.record_index)),
            report_date=r.Report_Tim.date().isoformat() if pd.notna(r.Report_Tim) else None,
            asset_type=r.Asset_Type if isinstance(r.Asset_Type, str) else None,
            damage_type=r.Inform_Wor if isinstance(r.Inform_Wor, str) else None,
            media=None if pd.isna(r.Media) else float(r.Media),
            access_issue=r.Access_Iss if isinstance(r.Access_Iss, str) else None,
            special_equipment=r.Special_Eq if isinstance(r.Special_Eq, str) else None,
            repaired=r.Repaired if isinstance(r.Repaired, str) else None,
            repaired_date=r.Repaired_D.date().isoformat() if pd.notna(r.Repaired_D) else None,
            lonlat=lonlat,
            match_status=mr.match_status, match_method=mr.match_method,
            match_dist_m=None if pd.isna(mr.match_dist_m) else round(float(mr.match_dist_m), 1),
            matched_layer=mr.layer, matched_ref=ref, node=node,
            arcos_circuit_label_agrees=(r.Circuit == circuit_name(cid)),
            label_fallback=bool(mr.label_fallback),
        ))

    # ---- poles on the oriented network (for structure sizing later)
    pole_attrs = {}
    for r in tree_poles.itertuples():
        pole_attrs[r.location_n] = dict(height_ft=_height_ft(r.height), pole_class=r.pole_class,
                                        material=r.material,
                                        install_year=int(r.date_insta.year) if pd.notna(r.date_insta) else None)

    nodes = {}
    for n in order:
        p = parent[n]
        e = H.edges[p, n] if p is not None else None
        nodes[n] = dict(parent=p, depth=depth[n], dist_m=round(dist_m[n], 1), tin=tin[n], tout=tout[n],
                        lonlat=node_lonlat(ctx, n),
                        edge=None if e is None else dict(length_m=round(e["length_m"], 1),
                                                         mounting=e["mounting"], usage=e["usage"],
                                                         phases=e.get("phases"),
                                                         bridge=e["bridge"], segs=e["segs"]),
                        pole=pole_attrs.get(n))

    stats = dict(
        circuit_id=cid, circuit_name=circuit_name(cid), premises=len(premises),
        premises_in_upstream_file=sum("not_in_upstream_file" not in p["data_flags"] for p in premises),
        premises_with_oriented_transformer=sum(p["transformer_node"] is not None for p in premises),
        transformers=len(transformers), devices=len(devices),
        chain_ancestor_checks=chain_checks, chain_ancestor_consistent=chain_ok,
        chain_consistency=round(chain_ok / chain_checks, 4) if chain_checks else None,
        damage_records=len(damage),
        damage_matched=sum(d["match_status"] == "matched" for d in damage),
        damage_on_network=sum(d["node"] is not None for d in damage),
        damage_label_disagrees=sum(not d["arcos_circuit_label_agrees"] for d in damage),
        damage_status_counts=pd.Series([d["match_status"] for d in damage]).value_counts().to_dict(),
        **{f"graph_{k}": v for k, v in binfo.items()}, root=root, **{f"root_{k}": v for k, v in rinfo.items()},
        overhead_km=round(sum(e["length_m"] for _, _, e in H.edges(data=True)
                              if e["mounting"] == "Overhead" and not e["bridge"]) / 1000, 2),
        underground_km=round(sum(e["length_m"] for _, _, e in H.edges(data=True)
                                 if e["mounting"] == "Underground" and not e["bridge"]) / 1000, 2),
    )
    return dict(stats=stats, H=H, nodes=nodes, devices=devices, transformers=transformers,
                premises=premises, damage=damage)
