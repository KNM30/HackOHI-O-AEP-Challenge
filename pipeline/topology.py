"""Primary-network graph construction and orientation.

Approach (documented in docs/assumptions.md):
1. Nodes are structure location numbers (poles/devices). Primary segments carry
   `location_n`/`location_1`, but direction is not consistent and some ends are
   null, so each segment end is also snapped to the nearest structure point
   within SNAP_M metres. Unsnapped ends become coordinate nodes.
2. A circuit's own segments can be split into pieces separated by small digitising
   gaps. Pieces whose nearest nodes are within GAP_BRIDGE_M are joined by a flagged
   "spatial_gap" edge; remaining pieces may be joined by a short path through
   neighbouring-circuit segments (<= MAX_BRIDGE_EDGES). Anything else is dropped
   and its premises are reported as off-network.
3. The root (feeder head) is the leaf node whose BFS orientation agrees best with
   the supplied `upstream_l` device hierarchy. The agreement rate is reported.
"""
from __future__ import annotations

from collections import defaultdict, deque

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

SNAP_M = 3.0
GAP_BRIDGE_M = 10.0
MAX_BRIDGE_EDGES = 25


def structure_index(point_layers: list[pd.DataFrame]):
    """KD-tree over projected structure points keyed by location number."""
    pts = pd.concat([d[["location_n", "geometry"]] for d in point_layers])
    pts = pts.dropna(subset=["location_n"]).drop_duplicates("location_n")
    xy = np.c_[pts.geometry.x.values, pts.geometry.y.values]
    return cKDTree(xy), pts.location_n.values, dict(zip(pts.location_n.values, map(tuple, xy)))


def build_global_graph(primary_proj, tree, locs, snap_m: float = SNAP_M) -> nx.Graph:
    G = nx.Graph()
    starts = np.array([g.coords[0][:2] for g in primary_proj.geometry])
    ends = np.array([g.coords[-1][:2] for g in primary_proj.geometry])
    ds, is_ = tree.query(starts)
    de, ie = tree.query(ends)

    def node(d, i, pt):
        return locs[i] if d <= snap_m else f"pt:{round(pt[0])}:{round(pt[1])}"

    for k, r in enumerate(primary_proj.itertuples(index=False)):
        a = node(ds[k], is_[k], starts[k])
        b = node(de[k], ie[k], ends[k])
        phase = getattr(r, "phase_orde", None)
        attrs = dict(seg=int(r.id), circuit=r.circuit_id, length_m=float(r.geometry.length),
                     mounting=r.mounting, usage=r.usage,
                     phases=len(phase) if isinstance(phase, str) and phase else None)
        if a != b:
            _add(G, a, b, attrs)
        la, lb = r.location_n, r.location_1
        if isinstance(la, str) and isinstance(lb, str) and la != lb and {la, lb} != {a, b}:
            _add(G, la, lb, attrs)
    return G


def _add(G, a, b, attrs):
    if G.has_edge(a, b):
        G.edges[a, b]["segs"].append(attrs["seg"])
        return
    G.add_edge(a, b, segs=[attrs["seg"]], **{k: v for k, v in attrs.items() if k != "seg"})


def _gap_bridge(H: nx.Graph, node_xy, max_gap_m: float) -> int:
    """Join components whose nearest node pair is within max_gap_m (digitising gaps)."""
    added = 0
    while True:
        comps = sorted(nx.connected_components(H), key=len, reverse=True)
        if len(comps) <= 1:
            return added
        main = [n for n in comps[0] if node_xy(n) is not None]
        tree = cKDTree([node_xy(n) for n in main])
        best = None
        for c in comps[1:]:
            pts = [(n, node_xy(n)) for n in c if node_xy(n) is not None]
            if not pts:
                continue
            d, i = tree.query([p for _, p in pts])
            k = int(np.argmin(d))
            if d[k] <= max_gap_m and (best is None or d[k] < best[0]):
                best = (float(d[k]), pts[k][0], main[int(i[k])])
        if best is None:
            return added
        gap, a, b = best
        H.add_edge(a, b, segs=[], circuit=None, length_m=gap, mounting="Unknown", usage="gap",
                   bridge=True, bridge_kind="spatial_gap")
        added += 1


def circuit_graph(GG: nx.Graph, circuit_id: str, node_xy=None, max_gap_m: float = GAP_BRIDGE_M,
                  max_bridge: int = MAX_BRIDGE_EDGES):
    """Circuit subgraph plus flagged bridges (spatial gaps, then short neighbour paths)."""
    H = nx.Graph()
    H.add_edges_from((u, v, d) for u, v, d in GG.edges(data=True) if d["circuit"] == circuit_id)
    for _, _, d in H.edges(data=True):
        d["bridge"] = False
    gap_edges = _gap_bridge(H, node_xy, max_gap_m) if node_xy else 0
    bridged_edges = 0
    unbridged = []
    while True:
        comps = sorted(nx.connected_components(H), key=len, reverse=True)
        if len(comps) <= 1:
            break
        main = comps[0]
        # multi-source BFS from the main component over the global graph
        pred, dist = {n: None for n in main}, {n: 0 for n in main}
        q = deque(main)
        others = {n: i for i, c in enumerate(comps[1:]) for n in c}
        hit = None
        while q:
            u = q.popleft()
            if dist[u] >= max_bridge:
                continue
            for v in GG.neighbors(u):
                if v in dist:
                    continue
                dist[v], pred[v] = dist[u] + 1, u
                if v in others:
                    hit = v
                    break
                q.append(v)
            if hit:
                break
        if hit is None:
            unbridged = [len(c) for c in comps[1:]]
            break
        path = [hit]
        while pred[path[-1]] is not None:
            path.append(pred[path[-1]])
        for a, b in zip(path, path[1:]):
            if not H.has_edge(a, b):
                d = dict(GG.edges[a, b])
                d["bridge"], d["bridge_kind"] = True, "neighbour_circuit_path"
                H.add_edge(a, b, **d)
                bridged_edges += 1
    comps = sorted(nx.connected_components(H), key=len, reverse=True)
    main = H.subgraph(comps[0]).copy()
    info = dict(nodes=H.number_of_nodes(), main_nodes=main.number_of_nodes(), gap_bridges=gap_edges,
                bridge_edges=bridged_edges, dropped_components=[len(c) for c in comps[1:]],
                unbridged_components=unbridged)
    return main, info


def _euler(parent_children, root):
    tin, tout, t = {}, {}, 0
    stack = [(root, False)]
    while stack:
        n, done = stack.pop()
        if done:
            tout[n] = t
            t += 1
            continue
        tin[n] = t
        t += 1
        stack.append((n, True))
        for c in parent_children.get(n, ()):
            stack.append((c, False))
    return tin, tout


def orient(H: nx.Graph, root):
    parent = {root: None}
    order = [root]
    q = deque([root])
    while q:
        u = q.popleft()
        for v in sorted(H.neighbors(u), key=str):
            if v not in parent:
                parent[v] = u
                order.append(v)
                q.append(v)
    children = defaultdict(list)
    for v, u in parent.items():
        if u is not None:
            children[u].append(v)
    tin, tout = _euler(children, root)
    return parent, children, order, tin, tout


def is_ancestor(tin, tout, a, b) -> bool:
    """True if a is an ancestor of (or equal to) b."""
    return a in tin and b in tin and tin[a] <= tin[b] and tout[b] <= tout[a]


def choose_root(H: nx.Graph, hierarchy: list[tuple[str, str]], top_level: list[str]):
    """Pick the leaf whose orientation agrees most with (location, upstream_location) pairs."""
    pairs = [(l, u) for l, u in hierarchy if l in H and u in H and l != u]
    leaves = [n for n in H.nodes if H.degree(n) == 1] or list(H.nodes)
    best = None
    for cand in leaves:
        parent, children, order, tin, tout = orient(H, cand)
        ok = sum(is_ancestor(tin, tout, u, l) for l, u in pairs)
        depth = {n: 0 for n in [cand]}
        for n in order[1:]:
            depth[n] = depth[parent[n]] + 1
        top_depth = sum(depth.get(t, 0) for t in top_level)
        score = (ok, -top_depth)
        if best is None or score > best[0]:
            best = (score, cand)
    (ok, _), root = best
    return root, dict(hierarchy_pairs=len(pairs), consistent_pairs=ok,
                      consistency=round(ok / len(pairs), 4) if pairs else None,
                      candidate_roots=len(leaves))
