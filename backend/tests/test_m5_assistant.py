"""Milestone 5: provider request shape, answer statuses and validation regressions.

The provider here is a stand-in (FakeClient); these tests do not prove the real API works.
"""
import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app import assistant
from app import schemas as s
from test_milestone4 import EMPTY, FakeClient, _with_fake, ask, sim

DEMO = "PRM-00770FFC"


def snap(kind="bounded", confirmed=False, **rest):
    r = {"kind": kind, "display": "6 h - 14 h", "earliest_h": 6.0, "latest_modeled_h": 14.0, "conditional": None}
    r.update(rest)
    return {"restoration": r,
            "alerts": {"simulated_outage_confirmed": confirmed,
                       "rules": ["Latest modeled time moves by at least 2 h or 25% since the last message."]},
            "guidance": [{"action": "Report downed lines to Appalachian Power at 800-956-4237. Keep generators "
                                    "at least 20 feet from doors."}]}


def problems(snapshot, **sections):
    return assistant.grounding_problems(s.AnswerSections(**{**EMPTY, **sections}), snapshot)


LOWER = dict(kind="lower_bound_only", display="At least 2.3 days", earliest_h=55.2,
             latest_modeled_h=88.0)
COND = dict(kind="conditional", display="If isolated: 1.8 h - 3.5 h | If not: 3.7 h - 7.3 h",
            conditional={"if_isolated_low_h": 1.75, "if_isolated_high_h": 3.5, "if_repair_low_h": 3.7,
                         "if_repair_high_h": 7.3, "repair_scope_complete": True})


# ------------------------------------------------------------------ previously rejected, now accepted
@pytest.mark.parametrize("text", [
    "Power could return in roughly 6 to 14 hours after the simulated response starts.",
    "That is about 14 hours, or a little over half a day.",           # small spelled numbers
    "An update is sent if the estimate moves by at least 2 h or 25%.",  # percentage quoted from the snapshot
    "Declaring a medical need does not guarantee faster restoration.",  # negated guarantee
    "There is no priority restoration in this prototype.",               # negated priority
    "Report downed lines on 800-956-4237 and keep generators at least 20 feet away.",  # approved guidance numbers
])
def test_valid_wording_is_accepted(text):
    assert problems(snap(), estimates=[text]) == []


def test_unit_conversion_and_rounding_are_accepted():
    sn = snap(**LOWER)
    assert problems(sn, estimates=["At least 55 hours (about 2.3 days); the full repair may take longer."]) == []


def test_conditional_wording_is_accepted():
    text = "If crews isolate the damaged section, about 1.8 to 3.5 hours; otherwise after the repair, 3.7 to 7.3 hours."
    assert problems(snap(**COND), estimates=[text]) == []


def test_simulated_confirmation_is_accepted_when_confirmed():
    assert problems(snap(confirmed=True), facts=["Your simulated outage has been confirmed."]) == []


# ------------------------------------------------------------------ previously missed, now rejected
def test_lower_bound_presented_as_complete_forecast():
    p = problems(snap(**LOWER), estimates=["Power should be back in 2.3 to 3.7 days."])
    assert any("at-least" in x for x in p)


def test_conditional_merged_into_one_range():
    p = problems(snap(**COND), estimates=["Restoration is expected in 1.8 to 7.3 hours."])
    assert any("conditional" in x for x in p)


def test_spelled_out_invented_duration():
    p = problems(snap(), estimates=["It could take about forty hours."])
    assert any("duration" in x for x in p)


def test_invented_percentage_and_probability():
    p = problems(snap(), estimates=["There is a 70% chance of an outage."])
    assert "contains a percentage that is not in the calculations" in p and "states a probability" in p


@pytest.mark.parametrize("text,expected", [
    ("Your power will be restored by tomorrow.", "states a restoration time as certain"),
    ("Your outage has been confirmed.", "claims a confirmed outage"),
    ("Because of your medical need you get priority restoration.", "implies priority treatment"),
    ("AEP says crews are on the way.", "presents an official utility statement"),
    ("We promise power by tonight.", "makes a promise or guarantee"),
    ("Repair job JOB-ABC123 is first.", "contains an internal identifier"),
    ("Your premise has a life support flag.", "mentions a sensitive source attribute"),
])
def test_unsafe_claims_are_rejected(text, expected):
    assert expected in problems(snap(), facts=[text])


# ------------------------------------------------------------------ request shape and statuses
def test_request_uses_stable_api_economical_model_and_no_silent_fallback(monkeypatch):
    fake = _with_fake(monkeypatch, lambda kw: EMPTY)
    a = ask("Why is my risk high?")
    kw = fake.calls[0]
    assert kw["model"] == assistant.AI_MODEL == "claude-haiku-5-5"
    assert "fallbacks" not in kw and "betas" not in kw          # no server-side model substitution
    assert kw["output_config"]["effort"] == "low" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["max_tokens"] == assistant.AI_MAX_TOKENS <= 4000
    assert a["status"] == "ai" and a["diagnostics"]["model_served"] == "claude-haiku-5-5"


def test_status_not_configured(monkeypatch):
    monkeypatch.setattr(assistant, "AI_PROVIDER", "none")
    a = ask("Why is my risk high?")
    assert a["status"] == "not_configured" and "not set up" in a["status_text"]


def test_status_provider_failed_on_error_and_refusal(monkeypatch):
    _with_fake(monkeypatch, lambda kw: anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")))
    a = ask("Why is my risk high?")
    assert a["status"] == "provider_failed" and "did not respond" in a["status_text"]
    refusal = SimpleNamespace(stop_reason="refusal", model="claude-haiku-5-5", content=[],
                              stop_details=SimpleNamespace(category="cyber"), usage=None)
    _with_fake(monkeypatch, lambda kw: refusal)
    a = ask("Why is my risk high?")
    assert a["status"] == "provider_failed" and "declined" in a["fallback_reason"]
    assert a["answer"]["estimates"]  # the standard answer still explains the risk


def test_missing_credentials_is_not_configured_not_a_500(monkeypatch):
    # what anthropic 2.3.0 actually raises when no credentials resolve (observed with the real SDK)
    _with_fake(monkeypatch, lambda kw: TypeError('"Could not resolve authentication method. Expected one of '
                                                  'api_key, auth_token, or credentials to be set."'))
    a = ask("Why is my risk high?")
    assert a["status"] == "not_configured" and "no Anthropic credentials" in a["fallback_reason"]


def test_unexpected_provider_exception_is_labelled_not_a_500(monkeypatch):
    _with_fake(monkeypatch, lambda kw: RuntimeError("boom"))
    a = ask("Why is my risk high?")
    assert a["status"] == "provider_failed" and a["answer"]["estimates"]


def test_status_validation_failed_keeps_details_for_developers(monkeypatch):
    _with_fake(monkeypatch, lambda kw: {**EMPTY, "estimates": ["Power will be restored by 9 pm."]})
    a = ask("What is delaying restoration?", simulation=sim(DEMO, "shared_upstream"))
    assert a["status"] == "validation_failed" and "could not be fully matched" in a["status_text"]
    assert "certain" in a["diagnostics"]["validation_problems"]


def test_status_not_shared(monkeypatch):
    fake = _with_fake(monkeypatch, lambda kw: EMPTY)
    a = ask("Who lives at my neighbour's address?")
    assert a["status"] == "not_shared" and not fake.calls


def test_diagnostics_never_contain_secrets(monkeypatch):
    placeholder = "placeholder-credential-for-leak-test"  # not key-shaped, so secret scanners stay quiet
    monkeypatch.setenv("ANTHROPIC_API_KEY", placeholder)
    _with_fake(monkeypatch, lambda kw: EMPTY)
    text = json.dumps(ask("Why is my risk high?"))
    assert placeholder not in text and "ANTHROPIC_API_KEY" not in text


def test_snapshot_flags_simulated_confirmation(monkeypatch):
    calls = []

    def capture(kw):
        calls.append(kw)
        return EMPTY
    _with_fake(monkeypatch, capture)
    body = {"briefing": {"premise_id": DEMO, "simulation": sim(DEMO, "shared_upstream")}, "question": "risk?"}
    from test_milestone4 import client
    key = client.post("/api/briefing", json=body["briefing"]).json()["scenario_key"]
    body["briefing"]["events"] = [{"type": "outage_confirmed", "scenario_key": key}]
    client.post("/api/assistant", json=body)
    content = calls[-1]["messages"][0]["content"]
    assert '"simulated_outage_confirmed": true' in content
