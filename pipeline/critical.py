"""Link public critical-facility points (hospital, fire, ambulance) to service transformers.

The source layers carry no electrical relationship, so each facility is attached to
the nearest service transformer within CRITICAL_MATCH_M (projected metres). This is a
spatial approximation and is labelled as such; facilities beyond the cap stay
unlinked. Only the facility type and the linked transformer are written - never the
facility's name, address or coordinates.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from common import PROJECTED_CRS, public_id, read_layer

CRITICAL_MATCH_M = 150.0
KINDS = {"hospital": "hospital", "fire": "fire_station", "ambulance": "ambulance_station"}


def load_facilities() -> gpd.GeoDataFrame:
    frames = []
    for layer, kind in KINDS.items():
        f = read_layer(layer, ["PERMANENT_"]).to_crs(PROJECTED_CRS)
        frames.append(f.assign(kind=kind, source_key=f["PERMANENT_"].astype(str))[["kind", "source_key", "geometry"]])
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=PROJECTED_CRS)


def link_facilities(facilities: gpd.GeoDataFrame, transformers: gpd.GeoDataFrame,
                    max_m: float = CRITICAL_MATCH_M) -> pd.DataFrame:
    """Nearest transformer (any circuit) per facility; rows beyond the cap are dropped."""
    j = gpd.sjoin_nearest(facilities, transformers[["id", "circuit_id", "geometry"]], how="inner",
                          max_distance=max_m, distance_col="dist_m")
    j = j[~j.index.duplicated(keep="first")]
    return pd.DataFrame({"kind": j.kind, "source_key": j.source_key, "transformer_fid": j["id"].astype(int),
                         "circuit_id": j.circuit_id, "dist_m": j.dist_m.round(1)})


def for_circuit(links: pd.DataFrame, cid: str, transformers_by_fid: dict[int, dict]) -> list[dict]:
    out = []
    for r in links[links.circuit_id == cid].itertuples():
        tr = transformers_by_fid.get(int(r.transformer_fid))
        if tr is None or tr.get("node") is None:
            continue  # transformer has no premises on the oriented network: cannot trace dependency
        out.append(dict(public_id=public_id("CRF", r.source_key), kind=r.kind, transformer_id=tr["public_id"],
                        match_dist_m=float(r.dist_m),
                        match_method=f"nearest service transformer within {CRITICAL_MATCH_M:g} m (approximation)"))
    return sorted(out, key=lambda d: d["public_id"])
