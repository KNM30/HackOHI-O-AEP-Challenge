"""API tests against the processed CIR18 subset (skipped if it has not been built)."""
import json

import pytest
from fastapi.testclient import TestClient

from app import data_store
from app.config import PROCESSED_DIR
from app.main import app

pytestmark = pytest.mark.skipif(not (PROCESSED_DIR / "index.json").exists(),
                                reason="run pipeline/build_subset.py first")
client = TestClient(app)
DEMO = "PRM-00770FFC"


def test_health_and_circuits():
    assert client.get("/api/health").json()["status"] == "ok"
    assert any(c["circuit_id"] == "0000018" for c in client.get("/api/circuits").json())


def test_demo_premise_context():
    r = client.get(f"/api/premises/{DEMO}")
    assert r.status_code == 200
    body = r.json()
    chain = body["upstream_chain"]
    assert chain[-1]["kind"] == "breaker"
    assert [c["position"] for c in chain] == list(range(len(chain)))
    assert body["supply_path"]["length_km"] > 0
    # prediction cards must not carry fabricated values yet
    for card in body["predictions"].values():
        assert set(card) == {"status", "message"} and card["status"] == "not_calculated"


def test_unknown_premise_404():
    assert client.get("/api/premises/PRM-NOPE").status_code == 404


def test_responses_do_not_leak_internal_fields():
    net = data_store.circuit("0000018")
    text = client.get(f"/api/premises/{DEMO}").text + client.get("/api/circuits/0000018/map").text
    forbidden_keys = ["premise_nu", "critical_c", "Life Support", "location_n", "feature_id", "transformer_node", "scada", "tin"]
    for k in forbidden_keys:
        assert f'"{k}' not in text, k
    # raw structure location numbers never appear in responses
    some_locations = [n for n in list(net.nodes)[:200] if not n.startswith("pt:")]
    assert not any(loc in text for loc in some_locations)


def test_historical_damage_is_rounded_and_labelled():
    body = client.get(f"/api/premises/{DEMO}").json()["historical_damage"]
    assert "not current" in body["note"]
    for r in body["records"]:
        for v in r["approx_location"].values():
            assert round(v, 3) == v


def test_risk_endpoint_is_pre_storm_and_monotone():
    scores = [client.get(f"/api/premises/{DEMO}/risk", params={"severity": s}).json()["score"]
              for s in ("minor", "moderate", "severe")]
    assert scores == sorted(scores)
    body = client.get(f"/api/premises/{DEMO}/risk").json()
    assert body["kind"] == "pre_storm_risk" and body["severity"] == "moderate"
    assert "probab" not in " ".join(f["value"] for f in body["factors"]).lower()
    assert "%" not in str(body["score"])
    assert client.get(f"/api/premises/{DEMO}/risk", params={"severity": "hurricane"}).status_code == 422


def test_historical_records_stay_historical():
    before = client.get(f"/api/premises/{DEMO}").json()["historical_damage"]
    cat = client.get(f"/api/premises/{DEMO}/scenarios").json()["scenarios"]
    hist_ids = {r["id"] for r in before["records"]}
    for sc in cat:
        # no scenario exposes historical record ids; only the explicit replay draws on them
        assert not hist_ids & {l["id"] for l in sc["locations"]}
        if sc["available"]:
            r = client.post(f"/api/premises/{DEMO}/scenario", json={"scenario_id": sc["id"]}).json()
            assert r["state"] == "simulated" and "not a real outage" in r["disclaimer"].lower()
    after = client.get(f"/api/premises/{DEMO}").json()["historical_damage"]
    assert before == after  # running scenarios does not alter the historical layer
    replay = next(sc for sc in cat if sc["id"] == "historical_replay")
    assert "replay" in replay["label"].lower() and "not a record" in replay["description"]


def test_scenario_is_stateless_and_resettable():
    a = client.post(f"/api/premises/{DEMO}/scenario", json={"scenario_id": "local_branch"}).json()
    client.post(f"/api/premises/{DEMO}/scenario", json={"scenario_id": "shared_upstream"})
    b = client.post(f"/api/premises/{DEMO}/scenario", json={"scenario_id": "local_branch"}).json()
    assert a == b
    # the pre-storm risk is unaffected by any scenario having been run
    assert client.get(f"/api/premises/{DEMO}/risk").json()["kind"] == "pre_storm_risk"


def test_scenario_validation():
    url = f"/api/premises/{DEMO}/scenario"
    assert client.post(url, json={"scenario_id": "nope"}).status_code == 404
    assert client.post(url, json={"scenario_id": "local_branch", "location_ids": ["LOC-BOGUS"]}).status_code == 422
    cat = client.get(f"/api/premises/{DEMO}/scenarios").json()["scenarios"]
    local = next(sc for sc in cat if sc["id"] == "local_branch")
    two = [l["id"] for l in local["locations"][:2]]
    assert client.post(url, json={"scenario_id": "local_branch", "location_ids": two}).status_code == 422
    multi = next(sc for sc in cat if sc["id"] == "multiple")
    one = multi["locations"][0]["id"]
    r = client.post(url, json={"scenario_id": "multiple", "location_ids": [one]})
    assert r.status_code == 200 and [l["id"] for l in r.json()["active_locations"]] == [one]


def test_new_endpoints_do_not_leak_internal_fields():
    net = data_store.circuit("0000018")
    text = client.get(f"/api/premises/{DEMO}/risk").text + client.get(f"/api/premises/{DEMO}/scenarios").text
    for sc in ("shared_upstream", "neighbouring_branch", "historical_replay"):
        text += client.post(f"/api/premises/{DEMO}/scenario", json={"scenario_id": sc}).text
    for k in ["premise_nu", "critical_c", "Life Support", "location_n", "feature_id", "transformer_node", "coverage",
              "zone_premise_count", "DEV-", "\"node\"", "\"tin\""]:
        assert k not in text, k
    nodes = [n for n in net.nodes if not n.startswith("pt:")]
    assert not any(n in text for n in nodes)


def _sim_body(pid, sid, crew=None, generator=DEMO):
    sc = next(x for x in client.get(f"/api/premises/{generator}/scenarios").json()["scenarios"] if x["id"] == sid)
    return {"premise_id": pid, "scenario_id": sid, "scenario_label": sc["label"],
            "location_ids": sc["default_location_ids"], "crew": crew or {}}


SIM = "/api/circuits/0000018/simulation"


def test_simulation_fixed_across_premises():
    body = _sim_body(DEMO, "historical_replay")
    a = client.post(SIM, json=body).json()
    b = client.post(SIM, json={**body, "premise_id": "PRM-00340340"}).json()
    assert a["restoration"]["jobs"] == b["restoration"]["jobs"]
    assert a["restoration"]["overall"] == b["restoration"]["overall"]
    assert a["impact"]["initially_interrupted"] == b["impact"]["initially_interrupted"]
    r = a["restoration"]
    assert r["state"] == "simulated" and "not official" in r["disclaimer"].lower()
    assert "elapsed" in r["time_reference"]
    # replayed duplicate records collapse into fewer jobs than locations
    assert r["overall"]["jobs"] < len(body["location_ids"])


def test_simulation_crew_inputs_change_time_not_effort():
    wb = {"restring_assumption": False}
    base = client.post(SIM, json=_sim_body(DEMO, "historical_replay", {"crews": 2, **wb})).json()["restoration"]
    more = client.post(SIM, json=_sim_body(DEMO, "historical_replay", {"crews": 6, **wb})).json()["restoration"]
    delay = client.post(SIM, json=_sim_body(DEMO, "historical_replay",
                                             {"crews": 2, "access_delay_h": 12, **wb})).json()["restoration"]
    # the replay has partly modeled jobs: no "all repairs finished" upper bound is reported
    assert base["overall"]["complete"] is False and base["overall"]["upper_h"] is None
    assert more["overall"]["modeled_work_upper_h"] < base["overall"]["modeled_work_upper_h"]
    assert delay["overall"]["modeled_work_upper_h"] >= base["overall"]["modeled_work_upper_h"]
    for x in (more, delay):
        assert x["overall"]["person_hours_high"] == base["overall"]["person_hours_high"]


def test_simulation_validation():
    body = _sim_body(DEMO, "local_branch")
    assert client.post(SIM, json={**body, "crew": {"crew_size": 9}}).status_code == 422
    assert client.post(SIM, json={**body, "crew": {"crews": 0}}).status_code == 422
    assert client.post(SIM, json={**body, "location_ids": ["LOC-BOGUS"]}).status_code == 422
    assert client.post(SIM, json={**body, "location_ids": []}).status_code == 422
    assert client.post(SIM, json={**body, "premise_id": "PRM-NOPE"}).status_code == 404


def test_simulation_does_not_leak_internal_fields():
    net = data_store.circuit("0000018")
    text = "".join(client.post(SIM, json=_sim_body(DEMO, sid)).text
                   for sid in ("shared_upstream", "multiple", "historical_replay"))
    for k in ["premise_nu", "critical_c", "Life Support", "location_n", "feature_id", "transformer_node", "coverage",
              "zone_premise_count", "DEV-", "\"node\"", "\"tin\"", "DMG-"]:
        assert k not in text, k
    nodes = [n for n in net.nodes if not n.startswith("pt:")]
    assert not any(n in text for n in nodes)


def test_every_premise_resolves():
    ids = [p["id"] for p in client.get("/api/circuits/0000018/premises").json()]
    assert len(ids) == len(set(ids)) == 893
    for pid in ids[:: max(1, len(ids) // 40)]:
        assert client.get(f"/api/premises/{pid}").status_code == 200
    json.dumps(ids)
