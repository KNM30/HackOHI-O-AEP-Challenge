"""Pipeline units: upstream parsing, graph orientation, gap bridging, capped matching."""
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point

import topology as topo
from common import parse_upstream
from matching import match_damage


def test_parse_upstream_orders_nearest_first(tmp_path):
    f = tmp_path / "up.txt"
    f.write_text("111\teo_power_xfrmr_inst*5*Distribution*L5\teo_isolating_eqpt_inst*7*Fuse*L7\t"
                 "eo_circuit*9*Circuit Breaker*0000018\n222\tbadtoken\n")
    df = parse_upstream(f)
    p = df[df.premise == "111"]
    assert list(p.position) == [0, 1, 2]
    assert list(p.device_type) == ["Distribution", "Fuse", "Circuit Breaker"]
    assert p.iloc[1].feature_id == 7 and p.iloc[1].location == "L7"
    assert df[df.premise == "222"].malformed.iloc[0] == "badtoken"


def test_choose_root_agrees_with_hierarchy():
    H = nx.path_graph(["a", "b", "c", "d"])
    H.add_edge("c", "e")
    # devices at d and e both list c as their upstream location; b is upstream of c
    root, info = topo.choose_root(H, [("d", "c"), ("e", "c"), ("c", "b")], top_level=["b"])
    assert root == "a" and info["consistency"] == 1.0
    parent, children, order, tin, tout = topo.orient(H, root)
    assert topo.is_ancestor(tin, tout, "b", "e") and not topo.is_ancestor(tin, tout, "d", "e")


def test_gap_bridge_joins_close_pieces_only():
    xy = {"a": (0, 0), "b": (100, 0), "c": (105, 0), "d": (200, 0), "e": (900, 0), "f": (1000, 0)}
    H = nx.Graph()
    for u, v in (("a", "b"), ("c", "d"), ("e", "f")):
        H.add_edge(u, v, circuit="X", length_m=100, mounting="Overhead", usage="Primary", segs=[1])
    added = topo._gap_bridge(H, xy.get, max_gap_m=10)
    assert added == 1 and H.has_edge("b", "c") and H.edges["b", "c"]["bridge_kind"] == "spatial_gap"
    assert not nx.is_connected(H)  # the 700 m gap is left alone


def test_damage_matching_respects_cap():
    crs = "EPSG:32617"
    damage = gpd.GeoDataFrame({"Asset_Type": ["Fuse Bank", "Fuse Bank", "Light", None]},
                              geometry=[Point(0, 0), Point(500, 0), Point(0, 0), Point(0, 0)], crs=crs)
    fuses = gpd.GeoDataFrame({"id": [42]}, geometry=[Point(3, 4)], crs=crs)
    empty = gpd.GeoDataFrame({"id": [], "location_n": []}, geometry=[], crs=crs)
    m = match_damage(damage, dict(fuse=fuses, primary=empty, pole=empty, recloser=empty, switch=empty,
                                  transformer=empty))
    assert m.loc[0, "match_status"] == "matched" and m.loc[0, "match_key"] == 42
    assert abs(m.loc[0, "match_dist_m"] - 5.0) < 1e-6
    assert m.loc[1, "match_status"] == "unmatched_beyond_cap"
    assert m.loc[2, "match_status"] == "not_modelled_asset_type"
    assert m.loc[3, "match_status"] == "missing_asset_type"
