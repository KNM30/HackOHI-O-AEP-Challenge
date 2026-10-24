"""Upstream-dependency logic on a small hand-built feeder.

        R (root / breaker)
        |
        A ---- recloser REC at A protects A->B (and below)
        |
        B ---- fuse F1 at B protects only B->C (a tap); main line continues B->D
       / \\
      C   D
      |   |
     XC   XD   (service transformers at C and D)
"""
import pytest

from app.network import CircuitNetwork

EDGE = dict(length_m=100.0, mounting="Overhead", usage="Primary", bridge=False, segs=[])


def node(parent, tin, tout):
    return dict(parent=parent, depth=0, dist_m=0, tin=tin, tout=tout, lonlat=[0, 0],
                edge=None if parent is None else EDGE, pole=None)


@pytest.fixture
def net():
    nodes = {
        "R": node(None, 0, 9), "A": node("R", 1, 8), "B": node("A", 2, 7),
        "C": node("B", 3, 4), "D": node("B", 5, 6),
    }
    devices = {
        "DEV-REC": dict(public_id="DEV-REC", kind="recloser", device_type="Recloser (Hydraulic)", node="A",
                        coverage=["B"], zone_premise_count=2),
        "DEV-F1": dict(public_id="DEV-F1", kind="fuse", device_type="Fuse", node="B", coverage=["C"],
                       zone_premise_count=1),
    }
    premises = [
        dict(public_id="P-C", transformer_id="XFR-C", transformer_node="C", chain=["DEV-F1", "DEV-REC"],
             data_flags=[]),
        dict(public_id="P-D", transformer_id="XFR-D", transformer_node="D", chain=["DEV-REC"], data_flags=[]),
        dict(public_id="P-X", transformer_id="XFR-X", transformer_node=None, chain=[],
             data_flags=["transformer_not_on_oriented_network"]),
    ]
    return CircuitNetwork(dict(circuit_id="T", label="Test", nodes=nodes, devices=devices,
                               transformers={}, premises=premises, damage=[], stats={}, root="R"))


def dmg(node=None, layer="primary", status="matched", ref=None):
    return dict(match_status=status, matched_layer=layer, node=node, matched_ref=ref)


def test_ancestry_and_path(net):
    assert net.is_ancestor("A", "C")
    assert net.is_ancestor("C", "C")
    assert not net.is_ancestor("C", "D")
    assert net.path_to_root("C") == ["C", "B", "A", "R"]
    assert not net.is_ancestor("A", "missing")


def test_protecting_device_respects_branch_coverage(net):
    # tap span B->C is behind the fuse; main span B->D is not, so the recloser clears it
    assert net.protecting_device("C")["public_id"] == "DEV-F1"
    assert net.protecting_device("D")["public_id"] == "DEV-REC"
    assert net.protecting_device("B")["public_id"] == "DEV-REC"
    # span R->A has no device above it: the substation breaker clears it
    assert net.protecting_device("A") is None


def test_tap_damage_affects_only_tap(net):
    rel_c = net.relation(net.premises["P-C"], dmg("C"))
    rel_d = net.relation(net.premises["P-D"], dmg("C"))
    assert rel_c.affects_premise and rel_c.on_supply_path and rel_c.protecting_device == "DEV-F1"
    assert not rel_d.affects_premise and not rel_d.on_supply_path


def test_main_line_damage_beyond_tap(net):
    # damage on B->D trips the recloser: P-C loses power but is not downstream of the damage,
    # so it is a step-restoration candidate; P-D must wait for the repair.
    rel_c = net.relation(net.premises["P-C"], dmg("D"))
    rel_d = net.relation(net.premises["P-D"], dmg("D"))
    assert rel_c.affects_premise and not rel_c.on_supply_path
    assert rel_d.affects_premise and rel_d.on_supply_path


def test_breaker_level_damage_affects_everyone(net):
    for pid in ("P-C", "P-D"):
        rel = net.relation(net.premises[pid], dmg("A"))
        assert rel.affects_premise and rel.protecting_device is None


def test_damaged_fuse_opens_itself(net):
    rel = net.relation(net.premises["P-C"], dmg("B", layer="fuse", ref="DEV-F1"))
    assert rel.protecting_device == "DEV-F1" and rel.affects_premise


def test_transformer_damage_is_local(net):
    assert net.relation(net.premises["P-C"], dmg(layer="transformer", ref="XFR-C")).same_transformer
    assert not net.relation(net.premises["P-D"], dmg(layer="transformer", ref="XFR-C")).affects_premise


def test_missing_data_yields_no_relation(net):
    assert net.relation(net.premises["P-C"], dmg("C", status="unmatched_beyond_cap")) is None
    assert net.relation(net.premises["P-C"], dmg(None)) is None
    assert net.relation(net.premises["P-X"], dmg("C")) is None
