"""Extract the labor workbook into data/processed/labor_reference.json.

Every value keeps its sheet and cell so the developer view can cite it. Tables are
located by their label text rather than fixed cell addresses. Missing values stay
null (never zero).

Usage:  python pipeline/build_labor.py
"""
from __future__ import annotations

import json
import re
from datetime import date

import openpyxl

from common import LABOR_XLSX, PROCESSED

LTMR = "Labor time material related"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def category_tables(ws) -> dict:
    """Tables headed '<Name> CU Average Hours' (or 'Fuse Cutout Average Hours')."""
    out = {}
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row))
    i = 0
    while i < len(rows):
        title = rows[i][0].value
        if isinstance(title, str) and "Average Hours" in title:
            name = re.sub(r"\s*(CU )?Average Hours.*$", "", title.strip()).strip()
            header = [c.value for c in rows[i + 1]]
            cols = {h: j for j, h in enumerate(header) if isinstance(h, str)}
            data, k = [], i + 2
            while k < len(rows) and any(c.value is not None for c in rows[k][:4]):
                r = rows[k]
                entry = {"row": r[0].row}
                for h, j in cols.items():
                    entry[h] = r[j].value
                    entry[f"{h} cell"] = r[j].coordinate
                data.append(entry)
                k += 1
            out[name] = {"sheet": ws.title, "title_cell": rows[i][0].coordinate, "columns": list(cols), "rows": data}
            i = k
        else:
            i += 1
    return out


def connectors(ws) -> dict:
    items, ins, rem = {}, [], []
    for r in ws.iter_rows(min_row=2, max_col=3):
        code, a, b = r[0].value, _num(r[1].value), _num(r[2].value)
        if isinstance(code, str) and code.startswith("CNC"):
            items[code] = {"install": a, "removal": b, "row": r[0].row}
            if a is not None:
                ins.append(a)
            if b is not None:
                rem.append(b)
    return {
        "sheet": ws.title,
        "items": items,
        "average": {"install": round(sum(ins) / len(ins), 4), "removal": round(sum(rem) / len(rem), 4),
                    "count": len(items), "cells": f"{ws.title}!B2:C{1 + len(items)}",
                    "note": "Recomputed mean of the CU rows (matches the sheet's AVERAGE formula range). "
                            "The sheet notes it includes all connector sizes and valid zero-hour records."},
    }


def labor_only(ws) -> list[dict]:
    out = []
    for r in ws.iter_rows(min_row=2, max_col=5):
        intent = r[0].value
        if not isinstance(intent, str):
            continue
        out.append({"original_intent": intent.strip(), "work_type": r[1].value, "description": r[2].value,
                    "install_hours": _num(r[3].value), "unit": r[4].value or "per occurrence (unit not stated)",
                    "cell": f"{ws.title}!D{r[0].row}"})
    return out


def main() -> None:
    wb = openpyxl.load_workbook(LABOR_XLSX, data_only=False)
    ilm_ws = wb["Indirect Labor Multiplier"]
    doc = {
        "generated": str(date.today()),
        "source": LABOR_XLSX.name,
        "ilm": {"value": _num(ilm_ws["B1"].value), "cell": "Indirect Labor Multiplier!B1",
                "note": ilm_ws["A3"].value},
        "categories": category_tables(wb[LTMR]),
        "connectors": connectors(wb["CNC"]),
        "labor_only": labor_only(wb["Labor only work"]),
        "cu_groups": {r[0].value: r[1].value for r in wb["CU Group descriptions"].iter_rows(min_row=2, max_col=2)
                      if r[0].value},
    }
    assert doc["ilm"]["value"] == 4.5, doc["ilm"]
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "labor_reference.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    print(f"categories: {', '.join(doc['categories'])}")
    print(f"labor-only rows: {len(doc['labor_only'])}; connectors: {doc['connectors']['average']}")
    print(f"wrote {PROCESSED / 'labor_reference.json'}")


if __name__ == "__main__":
    main()
