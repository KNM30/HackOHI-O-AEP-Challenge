"""Loads processed circuit models once per process."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import PROCESSED_DIR
from .network import CircuitNetwork


class DataNotBuilt(RuntimeError):
    pass


@lru_cache(maxsize=1)
def index() -> dict:
    path = PROCESSED_DIR / "index.json"
    if not path.exists():
        raise DataNotBuilt(f"{path} not found - run pipeline/build_subset.py")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def circuit(circuit_id: str) -> CircuitNetwork:
    path = PROCESSED_DIR / "circuits" / circuit_id / "model.json"
    if not path.exists():
        raise KeyError(circuit_id)
    return CircuitNetwork(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=8)
def lines_geojson(circuit_id: str) -> dict:
    path = PROCESSED_DIR / "circuits" / circuit_id / "lines.geojson"
    if not path.exists():
        raise KeyError(circuit_id)
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def region() -> dict:
    path = PROCESSED_DIR / "region_circuits.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"circuits": []}


@lru_cache(maxsize=1)
def labor_reference() -> dict:
    path = PROCESSED_DIR / "labor_reference.json"
    if not path.exists():
        raise DataNotBuilt(f"{path} not found - run pipeline/build_labor.py")
    return json.loads(path.read_text(encoding="utf-8"))


def find_premise(premise_id: str) -> tuple[CircuitNetwork, dict] | None:
    for c in index()["circuits"]:
        net = circuit(c["circuit_id"])
        p = net.premises.get(premise_id)
        if p is not None:
            return net, p
    return None
