"""Shared paths, loaders and identifiers for the data pipeline.

Source data is read from the challenge repository (never modified). Processed
outputs go to data/processed/.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = Path(os.environ.get("AEP_RAW_DIR", ROOT / "challenge_repo" / "data"))
EXTRACTED = RAW_DIR / "extracted"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

# Study area is around 80W / 37N (Roanoke, VA): UTM zone 17N gives metre units.
PROJECTED_CRS = "EPSG:32617"
DISPLAY_CRS = "EPSG:4326"

LAYERS: dict[str, tuple[str, str]] = {
    "customer": ("Data1", "Customer_Clip.shp"),
    "damage": ("Data1", "arcos_prod_damage_09_28_Clip.shp"),
    "pole": ("Data1", "Pole_Clip.shp"),
    "primary": ("Data1", "Primary_ExportFeatures.shp"),
    "fuse": ("Data1", "Fuse_Bank_Clip.shp"),
    "ambulance": ("Data1", "Ambulance_Servi_Pairwis_Clip.shp"),
    "fire": ("Data1", "Fire_Stations_E_Pairwis_Clip.shp"),
    "hospital": ("Data1", "Hospitals_Medic_Pairwis_Clip.shp"),
    "secondary": ("Data2", "Secondary_ExportFeatures.shp"),
    "transformer": ("Data2", "Transformer_Clip.shp"),
    "switch": ("Data2", "Switch_Clip.shp"),
    "recloser": ("Data2", "Recloser_Bank_Clip.shp"),
}
UPSTREAM_TXT = EXTRACTED / "matched_upstream" / "matched_upstream.txt"
LABOR_XLSX = RAW_DIR / "Install_Labor_HackOHIO.xlsx"
STRUCTURE_PDF = RAW_DIR.parent / "docs" / "structure_drawings.pdf"

# Pseudonymisation salt for public identifiers. Premise numbers in the source are
# already anonymised by the organisers; hashing adds a second layer so the
# customer-facing app never echoes source keys.
ID_SALT = os.environ.get("AEP_ID_SALT", "hackohio26-outage-concierge")


def layer_path(name: str) -> Path:
    folder, fname = LAYERS[name]
    return EXTRACTED / folder / fname


def read_layer(name: str, columns: list[str] | None = None, geometry: bool = True):
    path = layer_path(name)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing - run `python pipeline/extract.py` first")
    df = pyogrio.read_dataframe(path, columns=columns, read_geometry=geometry)
    if geometry:
        df = gpd.GeoDataFrame(df, geometry=shapely.force_2d(df.geometry.values), crs=df.crs)
    return df


def public_id(prefix: str, key) -> str:
    digest = hashlib.sha256(f"{ID_SALT}|{prefix}|{key}".encode()).hexdigest()
    return f"{prefix}-{digest[:8].upper()}"


def circuit_name(circuit_id: str) -> str:
    """'0000018' -> 'CIR18' (ARCOS uses the aep_circui naming)."""
    return f"CIR{int(circuit_id)}"


def parse_upstream(path: Path = UPSTREAM_TXT) -> pd.DataFrame:
    """Long table: one row per (premise, upstream element), position 0 = nearest.

    Line format: premise<TAB>source*feature_id*device_type*location_number<TAB>...
    """
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            premise = parts[0].strip()
            for pos, token in enumerate(parts[1:]):
                bits = token.split("*")
                if len(bits) != 4:
                    rows.append((premise, pos, None, None, None, None, token))
                    continue
                src, fid, dtype, loc = bits
                rows.append((premise, pos, src, int(fid), dtype, loc, None))
    return pd.DataFrame(
        rows, columns=["premise", "position", "source", "feature_id", "device_type", "location", "malformed"]
    )
