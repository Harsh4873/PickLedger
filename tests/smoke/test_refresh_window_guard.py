import json
from datetime import datetime

import pytest

from scripts.automation.ensure_model_refresh import REQUIRED, recovery_models, refresh_decision


def now(value="2026-09-09T14:20:00Z"):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cache(generated="2026-09-09T14:10:00Z"):
    return {"date": "2026-09-09", "generatedAt": generated,
            "models": {key: {"ok": True} for key in REQUIRED}}


def test_same_day_warmup_does_not_hide_missed_market_refresh():
    payload = cache("2026-09-09T13:00:00Z")
    payload["updatedAt"] = "2026-09-09T14:19:00Z"  # Scores24 publish
    assert refresh_decision(payload, [], now())[0] == "dispatch"


def test_completed_window_is_not_repeated():
    assert refresh_decision(cache(), [], now())[0] == "fresh"


def test_queued_run_keeps_props_from_displacing_it_even_with_fresh_cache():
    assert refresh_decision(cache(), [{"status": "queued"}], now())[0] == "active"


@pytest.mark.parametrize("state", ["queued", "in_progress", "pending", "requested", "waiting"])
def test_active_run_prevents_duplicate_dispatch(state):
    assert refresh_decision({}, [{"status": state}], now())[0] == "active"


def test_bounded_recovery_and_next_window_reset():
    runs = [{"status": "completed", "event": "workflow_dispatch", "createdAt": "2026-09-09T14:06:00Z"}] * 3
    assert refresh_decision({}, runs, now())[0] == "exhausted"
    assert refresh_decision({}, runs, now("2026-09-09T15:40:00Z"))[0] == "dispatch"


def test_cancelled_run_is_retried_after_cooldown():
    runs = [{"status": "completed", "event": "schedule", "createdAt": "2026-09-09T14:06:00Z"}]
    assert refresh_decision({}, runs, now())[0] == "cooldown"
    assert refresh_decision({}, runs, now("2026-09-09T14:30:00Z"))[0] == "dispatch"


def test_unhealthy_or_yesterday_cache_requires_recovery():
    payload = cache()
    payload["models"]["mlb_new"]["ok"] = False
    assert refresh_decision(payload, [], now())[0] == "dispatch"
    payload = cache()
    payload["date"] = "2026-09-08"
    assert refresh_decision(payload, [], now())[0] == "dispatch"


def test_current_window_retries_only_failed_models():
    payload = cache()
    payload["models"]["cfb"]["ok"] = False
    assert recovery_models(payload, now()) == ["cfb"]
    assert recovery_models(payload, now("2026-09-09T15:40:00Z")) == []


def test_before_first_window_is_idle():
    assert refresh_decision({}, [], now("2026-09-09T10:00:00Z"))[0] == "idle"


def test_utc_schedule_works_during_standard_time():
    payload = cache("2026-12-09T14:10:00Z")
    payload["date"] = "2026-12-09"
    assert refresh_decision(payload, [], now("2026-12-09T14:20:00Z"))[0] == "fresh"


@pytest.mark.parametrize("active", [True, False])
def test_local_trigger_uses_serialized_guard_and_skips_duplicates(monkeypatch, active):
    from scripts.automation import ensure_model_refresh as guard

    calls = []

    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("run", "list"):
            return json.dumps([{"status": "queued"}] if active else [])
        return ""

    monkeypatch.setattr(guard, "gh", fake_gh)
    monkeypatch.setattr("sys.argv", ["guard", "--remote", "--dispatch"])
    assert guard.main() == 0
    dispatches = [call for call in calls if call[:2] == ("workflow", "run")]
    assert len(dispatches) == (0 if active else 1)
    if dispatches:
        assert dispatches[0][2] == "model-cache-freshness-guard.yml"


def test_remote_inspection_does_not_dispatch(monkeypatch):
    from scripts.automation import ensure_model_refresh as guard

    calls = []
    monkeypatch.setattr(guard, "gh", lambda *args: calls.append(args) or "[]")
    monkeypatch.setattr("sys.argv", ["guard", "--remote"])
    assert guard.main() == 0
    assert all(call[:2] == ("run", "list") for call in calls)
