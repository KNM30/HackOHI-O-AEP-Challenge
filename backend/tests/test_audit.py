"""Audit trail: per-session, summary-only, never stores typed text."""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit
from app.config import PROCESSED_DIR
from app.main import app

pytestmark = pytest.mark.skipif(not (PROCESSED_DIR / "index.json").exists(), reason="run the pipeline first")
client = TestClient(app)
DEMO = "PRM-00770FFC"


def _h(sid):
    return {"X-Session-Id": sid}


def test_decisions_are_recorded_per_session():
    audit.clear()
    a, b = "session-aaaa-1111", "session-bbbb-2222"
    client.get(f"/api/premises/{DEMO}/risk", params={"severity": "severe"}, headers=_h(a))
    client.post("/api/briefing", json={"premise_id": DEMO, "severity": "minor"}, headers=_h(b))
    ea = client.get("/api/audit", headers=_h(a)).json()
    assert [e["endpoint"] for e in ea] == ["risk"]
    assert ea[0]["premise_id"] == DEMO and ea[0]["inputs"] == {"severity": "severe"}
    assert ea[0]["outputs"]["band"] in ("low", "moderate", "high") and "risk model" in ea[0]["model"]
    assert [e["endpoint"] for e in client.get("/api/audit", headers=_h(b)).json()] == ["briefing"]


def test_question_text_is_never_stored():
    audit.clear()
    sid = "session-cccc-3333"
    secret = "my neighbour at 12 Elm Street uses oxygen"
    client.post("/api/assistant", json={"briefing": {"premise_id": DEMO}, "question": secret}, headers=_h(sid))
    entries = client.get("/api/audit", headers=_h(sid)).json()
    assert entries and entries[0]["inputs"]["question_chars"] == len(secret)
    assert "Elm" not in json.dumps(entries) and "oxygen" not in json.dumps(entries)


def test_no_or_malformed_session_records_nothing():
    audit.clear()
    client.get(f"/api/premises/{DEMO}/risk")
    client.get(f"/api/premises/{DEMO}/risk", headers=_h("bad id!"))
    assert client.get("/api/audit").json() == []
    assert client.get("/api/audit", headers=_h("bad id!")).json() == []
    assert audit.for_session("bad id!") == []
