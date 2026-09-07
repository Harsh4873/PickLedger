"""A transient upstream outage must not erase an already published slate."""
from __future__ import annotations

import json

import pytest

from scripts.merge_model_cache_payload import merge_payload
from scripts.refresh_model_cache import _is_transient_model_error, _run_model_job_with_retries


@pytest.mark.parametrize("error", [
    "502 Server Error: Bad Gateway for url: schedule",
    "429 Client Error: Too Many Requests",
    "503 Server Error: Service Unavailable",
    "504 Server Error: Gateway Timeout",
    "Connection reset by peer",
])
def test_temporary_upstream_errors_are_retryable(error):
    assert _is_transient_model_error({"ok": False, "error": error})


def test_transient_error_retries_and_returns_recovered_model(monkeypatch):
    from scripts import refresh_model_cache

    responses = iter([{"ok": False, "error": "502 Server Error: Bad Gateway"}, {"ok": True, "picks": []}])
    sleeps = []
    monkeypatch.setattr(refresh_model_cache.time, "sleep", sleeps.append)
    assert _run_model_job_with_retries("mlb_new", lambda: next(responses)) == {"ok": True, "picks": []}
    assert sleeps == [3]


def test_invalid_model_is_not_retried(monkeypatch):
    from scripts import refresh_model_cache

    monkeypatch.setattr(refresh_model_cache.time, "sleep", lambda _seconds: pytest.fail("unexpected retry"))
    failure = {"ok": False, "error": "model artifact is invalid"}
    assert _run_model_job_with_retries("cfb", lambda: failure) == failure


def test_failed_refresh_keeps_same_date_picks_and_failure_visible(tmp_path):
    pick = {"source": "MLB", "sport": "MLB", "date": "2026-09-06", "pick": "Home ML", "result": "win"}
    current = {"date": "2026-09-06", "models": {"mlb_new": {"ok": True, "picks": [pick], "games": 1}}}
    (tmp_path / "latest.json").write_text(json.dumps(current))
    generated = {"date": "2026-09-06", "models": {"mlb_new": {"ok": False, "error": "502 Bad Gateway"}}}
    merged = merge_payload(generated, tmp_path)
    bucket = merged["models"]["mlb_new"]
    assert bucket["picks"] == [pick]
    assert bucket["games"] == 1
    assert bucket["ok"] is False
    assert bucket["error"] == "502 Bad Gateway"
    assert bucket["preserved_after_refresh_error"] is True
    assert merged["mlb_new"] == bucket


def test_failed_refresh_never_carries_yesterdays_model_picks(tmp_path):
    current = {"date": "2026-09-05", "models": {"mlb_new": {"ok": True, "picks": [{"pick": "Old pick"}]}}}
    (tmp_path / "latest.json").write_text(json.dumps(current))
    generated = {"date": "2026-09-06", "models": {"mlb_new": {"ok": False, "error": "502 Bad Gateway"}}}
    bucket = merge_payload(generated, tmp_path)["models"]["mlb_new"]
    assert bucket["ok"] is False
    assert not bucket.get("picks")


def test_later_success_clears_failed_refresh_marker(tmp_path):
    current = {"date": "2026-09-06", "models": {"cfb": {"ok": False, "picks": [], "preserved_after_refresh_error": True}}}
    (tmp_path / "latest.json").write_text(json.dumps(current))
    generated = {"date": "2026-09-06", "models": {"cfb": {"ok": True, "picks": []}}}
    bucket = merge_payload(generated, tmp_path)["models"]["cfb"]
    assert bucket["ok"] is True
    assert "preserved_after_refresh_error" not in bucket
