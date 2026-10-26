import json

import pytest
from fastapi.testclient import TestClient

from app import analytics as an
from app import demo, main
from app.generator import generate_match

MATCH = generate_match(7)
MOMENTS = an.detect_moments(MATCH)
MID = demo.DEMO_MATCH_ID


def result(headline="recorded", graphic=None, clean=True):
    return {"headline": headline, "explanation": "e", "tactical_takeaway": "t", "stat_chips": [], "findings": [],
            "graphic": graphic, "trace": [],
            "verification": {"verdict": "verified", "claims_checked": 1, "issues": [],
                             "numeric_check": {"checked": 1, "unverified": [] if clean else ["99"]}}}


# --------------------------------------------------------------------------- pure logic
def test_fingerprint_is_stable_and_sensitive_to_the_match():
    again = generate_match(7)
    assert demo.fingerprint(MATCH, MOMENTS) == demo.fingerprint(again, an.detect_moments(again))
    other = generate_match(8)
    assert demo.fingerprint(MATCH, MOMENTS) != demo.fingerprint(other, an.detect_moments(other))


def test_save_load_roundtrip_and_stale_recordings_are_ignored(tmp_path):
    path = tmp_path / "x.json"
    key = demo.entry_key(MID, "m1", None, "coach", "en")
    demo.save({key: result()}, demo.fingerprint(MATCH, MOMENTS), path)
    entries, info = demo.install(MATCH, MOMENTS, path)
    assert info == {"found": True, "usable": True, "count": 1} and key in entries

    demo.save({key: result()}, "not-the-current-fingerprint", path)
    entries, info = demo.install(MATCH, MOMENTS, path)
    assert entries == {} and info["usable"] is False and "changed" in info["reason"]

    assert demo.install(MATCH, MOMENTS, tmp_path / "missing.json")[1] == {"found": False, "usable": False, "count": 0}


def test_is_clean_requires_verification_traced_numbers_and_a_requested_graphic():
    graphic = {"title": "t", "line": "l", "chips": []}
    assert demo.is_clean(result(), "coach")
    assert not demo.is_clean(result(clean=False), "coach")
    assert not demo.is_clean(result(), "broadcaster")  # a broadcaster recording needs its graphic
    assert demo.is_clean(result(graphic=graphic), "broadcaster")
    flagged = result()
    flagged["verification"]["issues"] = ["wrong"]
    assert not demo.is_clean(flagged, "coach")


def test_pick_fallback_prefers_same_audience_then_casual_fan_in_english():
    recorded = {demo.entry_key(MID, "m1", None, "coach", "en"): 1, demo.entry_key(MID, "m1", None, "casual_fan", "en"): 2}
    assert demo.pick_fallback(recorded, (MID, "m1", None, "coach", "pt")) == (MID, "m1", None, "coach", "en")
    assert demo.pick_fallback(recorded, (MID, "m1", None, "broadcaster", "pt")) == (MID, "m1", None, "casual_fan", "en")
    assert demo.pick_fallback(recorded, (MID, "m2", None, "coach", "en")) is None


@pytest.mark.parametrize("message,expected", [
    ("Azure CLI not found on path", True),
    ("Failed to invoke the Azure CLI", True),
    ("Model is required. Set via 'model' parameter or 'FOUNDRY_MODEL' environment variable.", True),
    ("Please run 'az login' to setup account.", True),
    ("Expecting value: line 1 column 1", False),
    ("rate limit exceeded", False),
])
def test_auth_errors_are_told_apart_from_other_failures(message, expected):
    assert demo.is_auth_error(RuntimeError(message)) is expected


# --------------------------------------------------------------------------- endpoints
@pytest.fixture
def client(monkeypatch):
    """A client over an isolated app state; no lifespan runs, so nothing calls `az`."""
    recorded = {
        demo.entry_key(MID, "m1", None, "coach", "en"): {**result("coach en"), "recorded": True},
    }
    monkeypatch.setattr(main, "RECORDED", recorded)
    monkeypatch.setattr(main, "CACHE", dict(recorded))
    monkeypatch.setattr(main, "STATE", {"live": None})
    monkeypatch.setattr(main, "DEMO_ONLY", False)
    return TestClient(main.app)


def ask(client, **kw):
    body = {"match_id": MID, "moment_id": "m1", "audience": "coach", "language": "en", **kw}
    return client.post("/api/explain", json=body)


def test_recorded_result_is_served_and_labelled(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_ONLY", True)
    r = ask(client).json()
    assert r["headline"] == "coach en" and r["recorded"] is True and r["cached"] is True and "fallback" not in r


def test_unrecorded_language_falls_back_to_english_with_a_notice(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_ONLY", True)
    r = ask(client, language="pt").json()
    assert r["headline"] == "coach en" and r["fallback"]["shown"] == {"audience": "coach", "language": "en"}
    assert r["fallback"]["requested"]["language"] == "pt" and "demo-only" in r["fallback"]["reason"]


def test_nothing_recorded_gives_a_clear_503_not_a_fake_answer(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_ONLY", True)
    r = ask(client, moment_id="m2", audience="broadcaster")
    assert r.status_code == 503 and "Live agents are unavailable" in r.json()["detail"]


def test_status_reports_mode_and_recordings(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_ONLY", True)
    monkeypatch.setitem(main.STATE, "live", False)
    s = client.get("/api/status").json()
    assert s["live"] is False and s["demo_only"] is True and s["recorded"] == 1 and s["demo_match"] == MID


def test_azure_sign_in_failure_falls_back_to_the_recording(client, monkeypatch):
    async def no_azure(*_a, **_k):
        raise RuntimeError("Azure CLI not found on path")
    monkeypatch.setattr(main, "run_explain", no_azure)
    r = ask(client, language="pt").json()
    assert r["recorded"] is True and r["fallback"]["reason"] == "Azure sign-in not available"
    assert main.STATE["live"] is False


def test_one_cold_start_failure_is_retried_and_then_succeeds(client, monkeypatch):
    calls = []

    async def flaky(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Failed to invoke the Azure CLI")
        return result("live")
    monkeypatch.setattr(main, "run_explain", flaky)
    r = ask(client, language="pt").json()
    assert r["headline"] == "live" and r["cached"] is False and len(calls) == 2 and main.STATE["live"] is True


def test_other_failures_are_not_masked_by_the_recording(client, monkeypatch):
    async def broken(*_a, **_k):
        raise RuntimeError("rate limit exceeded")
    monkeypatch.setattr(main, "run_explain", broken)
    r = ask(client, language="pt")
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]


def test_stream_endpoint_emits_recorded_result_and_errors_as_events(client, monkeypatch):
    monkeypatch.setattr(main, "DEMO_ONLY", True)
    body = {"match_id": MID, "moment_id": "m1", "audience": "coach", "language": "pt"}
    ev = [json.loads(line) for line in client.post("/api/explain/stream", json=body).text.splitlines()]
    assert ev[-1]["event"] == "result" and ev[-1]["result"]["fallback"]["shown"]["language"] == "en"
    body["moment_id"], body["audience"] = "m2", "broadcaster"
    ev = [json.loads(line) for line in client.post("/api/explain/stream", json=body).text.splitlines()]
    assert ev[-1]["event"] == "error" and "Live agents are unavailable" in ev[-1]["message"]


def test_upload_rejects_an_oversized_feed_and_accepts_a_real_one(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1000)
    big = client.post("/api/match/upload", files={"file": ("big.json", b" " * 1001)})
    assert big.status_code == 413
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 25 * 2**20)
    sample = open("tests/fixtures/opta_f24_sample.xml", "rb").read()
    ok = client.post("/api/match/upload", files={"file": ("f24.xml", sample)})
    assert ok.status_code == 200 and ok.json()["source"].startswith("opta-f24")
