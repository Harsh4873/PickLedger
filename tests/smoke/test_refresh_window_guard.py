import json
from datetime import datetime

import pytest

from scripts.automation.ensure_model_refresh import REQUIRED, recovery_models, refresh_decision


def now(value="2026-09-09T11:50:00Z"):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cache(generated="2026-09-09T11:40:00Z"):
    return {"date": "2026-09-09", "generatedAt": generated,
            "models": {key: {"ok": True} for key in REQUIRED}}


def test_same_day_warmup_does_not_hide_missed_market_refresh():
    payload = cache("2026-09-09T11:00:00Z")
    payload["updatedAt"] = "2026-09-09T11:49:00Z"  # Scores24 publish
    assert refresh_decision(payload, [], now())[0] == "dispatch"


def test_completed_window_is_not_repeated():
    assert refresh_decision(cache(), [], now())[0] == "fresh"


def test_queued_run_keeps_props_from_displacing_it_even_with_fresh_cache():
    assert refresh_decision(cache(), [{"status": "queued"}], now())[0] == "active"


@pytest.mark.parametrize("state", ["queued", "in_progress", "pending", "requested", "waiting"])
def test_active_run_prevents_duplicate_dispatch(state):
    assert refresh_decision({}, [{"status": state}], now())[0] == "active"


def test_bounded_recovery_and_next_window_reset():
    runs = [{"status": "completed", "event": "workflow_dispatch", "createdAt": "2026-09-09T11:36:00Z"}] * 3
    assert refresh_decision({}, runs, now())[0] == "exhausted"
    assert refresh_decision({}, runs, now("2026-09-09T18:10:00Z"))[0] == "dispatch"


def test_cancelled_run_is_retried_after_cooldown():
    runs = [{"status": "completed", "event": "schedule", "createdAt": "2026-09-09T11:36:00Z"}]
    assert refresh_decision({}, runs, now())[0] == "cooldown"
    assert refresh_decision({}, runs, now("2026-09-09T12:00:00Z"))[0] == "dispatch"


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
    assert recovery_models(payload, now("2026-09-09T18:10:00Z")) == []


def test_before_first_window_is_idle():
    assert refresh_decision({}, [], now("2026-09-09T10:00:00Z"))[0] == "idle"


def test_central_schedule_works_during_standard_time():
    payload = cache("2026-12-09T12:40:00Z")
    payload["date"] = "2026-12-09"
    assert refresh_decision(payload, [], now("2026-12-09T12:50:00Z"))[0] == "fresh"


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


@pytest.mark.parametrize('day,utc_morning,utc_afternoon', [
    ('2026-03-07', '12:30', '19:00'),
    ('2026-03-08', '11:30', '18:00'),
    ('2026-10-31', '11:30', '18:00'),
    ('2026-11-01', '12:30', '19:00'),
])
def test_windows_follow_central_time_across_dst(day, utc_morning, utc_afternoon):
    from datetime import timedelta
    from scripts.automation.ensure_model_refresh import latest_slot

    morning = now(f'{day}T{utc_morning}:00Z')
    afternoon = now(f'{day}T{utc_afternoon}:00Z')
    assert latest_slot(morning - timedelta(seconds=1)) is None
    assert latest_slot(morning) == morning
    assert latest_slot(afternoon - timedelta(seconds=1)) == morning
    assert latest_slot(afternoon) == afternoon


def test_scheduled_coordinator_counts_as_an_active_writer(monkeypatch):
    from scripts.automation import ensure_model_refresh as guard

    def fake_gh(*args):
        return json.dumps([{'status': 'in_progress'}] if guard.DAILY_WORKFLOW in args else [])

    monkeypatch.setattr(guard, 'gh', fake_gh)
    assert refresh_decision({}, guard.refresh_runs(), now())[0] == 'active'


def test_missed_window_recovers_all_feeds_but_failed_model_retry_stays_focused(monkeypatch):
    from scripts.automation import ensure_model_refresh as guard

    calls = []
    monkeypatch.setattr(guard, 'gh', lambda *args: calls.append(args))
    guard.dispatch_recovery({}, now())
    assert calls[-1][2] == 'daily-refresh.yml'
    payload = cache()
    payload['models']['cfb']['ok'] = False
    guard.dispatch_recovery(payload, now())
    assert calls[-1][2] == 'model-cache-refresh.yml'
    assert 'models=cfb' in calls[-1]
    assert 'date=2026-09-09' in calls[-1]


def test_daily_schedule_runs_writers_sequentially_and_requests_deployment():
    from pathlib import Path

    workflows = Path(__file__).resolve().parents[2] / ".github/workflows"
    daily = (workflows / "daily-refresh.yml").read_text(encoding="utf-8")
    assert 'cron: "30 6 * * *"' in daily
    assert 'cron: "0 13 * * *"' in daily
    assert daily.count('timezone: "America/Chicago"') == 2
    assert "uses: ./.github/workflows/model-cache-refresh.yml" in daily
    assert "uses: ./.github/workflows/player-props-refresh.yml" in daily
    assert "uses: ./.github/workflows/external-feed-refresh.yml" in daily
    assert "needs: models" in daily
    assert "needs: props" in daily
    assert "needs: feeds" in daily
    assert daily.count("if: ${{ !cancelled() }}") == 3
    assert "gh workflow run deploy-pages.yml --ref main" in daily
    for name in ("model-cache-refresh.yml", "player-props-refresh.yml", "external-feed-refresh.yml"):
        writer = (workflows / name).read_text(encoding="utf-8")
        assert "  workflow_call:" in writer
        assert "  workflow_dispatch:" in writer
        assert "\n  schedule:" not in writer
        assert "group: pick-cache-writer" in writer


def test_local_backup_and_bot_docs_use_the_daily_coordinator():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/automation/daily_local_refresh.sh").read_text(encoding="utf-8")
    assert 'dispatch daily-refresh.yml' in script
    assert "--workflow daily-refresh.yml" in script
    assert "dispatch model-cache-refresh.yml" not in script
    assert "dispatch player-props-refresh.yml" not in script
    assert "dispatch external-feed-refresh.yml" not in script
    bot = (root / "docs/cursor-automations.md").read_text(encoding="utf-8")
    assert "6:30 a.m. and 1:00 p.m. America/Chicago" in bot
    assert "gh workflow run daily-refresh.yml --ref main" in bot
    assert "shadow_mode=false" in bot
    runbook = (root / "docs/automations/pickledgerpro-daily-upcheck.md").read_text(encoding="utf-8")
    assert "6:30 a.m. and 1 p.m. America/Chicago" in runbook
    assert "sportytrader_cfb" in runbook and "forebet_nfl" in runbook
    assert "shadow_mode=false" in runbook
