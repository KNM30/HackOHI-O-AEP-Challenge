"""Match ARCOS damage points to network assets.

ARCOS records carry an asset type and a coordinate but no equipment key, so the
match is spatial. Each asset type is matched only against the layer of the same
type, within a capped distance (projected metres). Records outside the cap are
left unmatched rather than forced onto the nearest asset.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

# Cap for matching a damage point to an asset of the same type. The inspection
# report shows the distance distribution that motivated this value.
MAX_MATCH_M = 15.0
# Secondary-wire damage is attributed to the nearest service transformer. This is
# a coarser approximation, so it gets its own cap and an explicit method label.
SECONDARY_TO_TRANSFORMER_M = 60.0

ASSET_TYPE_LAYER = {
    "primary": "primary",
    "Pole": "pole",
    "Fuse Bank": "fuse",
    "Recloser Bank": "recloser",
    "Switch": "switch",
    "Transformer": "transformer",
    "Step Transformer": "transformer",
    "secondary": "secondary",
}
NOT_MODELLED = {"Light", "Capacitor Bank"}


def nearest(points: gpd.GeoDataFrame, targets: gpd.GeoDataFrame, key: str, max_m: float):
    """Nearest target key and distance for each point (NaN beyond max_m)."""
    if targets.empty or points.empty:
        return pd.DataFrame({"key": pd.Series(index=points.index, dtype=object),
                             "dist_m": pd.Series(index=points.index, dtype=float)})
    j = gpd.sjoin_nearest(points[["geometry"]], targets[[key, "geometry"]], how="left",
                          max_distance=max_m, distance_col="dist_m")
    j = j[~j.index.duplicated(keep="first")]
    return j.rename(columns={key: "key"})[["key", "dist_m"]]


def match_damage(damage: gpd.GeoDataFrame, layers: dict[str, gpd.GeoDataFrame]) -> pd.DataFrame:
    """Return one row per damage record with match result columns.

    `damage` and every layer must already be in the projected CRS. Layers that have
    a circuit field should be pre-filtered to the damage record's circuit when the
    caller wants circuit-restricted matching.
    """
    out = pd.DataFrame(index=damage.index)
    out["layer"] = damage.Asset_Type.map(ASSET_TYPE_LAYER)
    out["match_key"] = None
    out["match_dist_m"] = float("nan")
    out["match_method"] = None
    out["match_status"] = "unmatched_beyond_cap"
    out.loc[damage.Asset_Type.isin(NOT_MODELLED), "match_status"] = "not_modelled_asset_type"
    out.loc[damage.Asset_Type.isna(), "match_status"] = "missing_asset_type"

    for asset_type, layer in ASSET_TYPE_LAYER.items():
        idx = damage.index[damage.Asset_Type == asset_type]
        if len(idx) == 0:
            continue
        pts = damage.loc[idx]
        if layer == "secondary":
            res = nearest(pts, layers["transformer"], "id", SECONDARY_TO_TRANSFORMER_M)
            method = "secondary->nearest_transformer"
        else:
            key = "location_n" if layer == "pole" else "id"
            res = nearest(pts, layers[layer], key, MAX_MATCH_M)
            method = f"nearest_{layer}"
        ok = res.key.notna()
        out.loc[res.index[ok], "match_key"] = res.key[ok].values
        out.loc[res.index[ok], "match_dist_m"] = res.dist_m[ok].values
        out.loc[res.index[ok], "match_method"] = method
        out.loc[res.index[ok], "match_status"] = "matched"
    return out
