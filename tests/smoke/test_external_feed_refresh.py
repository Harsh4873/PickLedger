from __future__ import annotations

import json
import os
import sys
import time
from types import SimpleNamespace

from scripts import refresh_external_feeds as refresh


def _configure(monkeypatch, tmp_path, feeds, *, date="2026-09-06"):
    monkeypatch.setattr(refresh, "MODEL_CACHE_DIR", tmp_path)
    monkeypatch.setattr(refresh, "FEED_RUNNERS", feeds)
    monkeypatch.setattr(refresh, "apply_market_odds_to_payload", lambda *_args: None)
    monkeypatch.setattr(refresh, "apply_calibration_to_payload", lambda *_args: None)
    monkeypatch.setattr(
        refresh,
        "_parse_args",
        lambda: SimpleNamespace(date=date, feeds=",".join(feeds), sports="mlb,cfb", skip_firestore=True),
    )
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def _write_previous(tmp_path, bucket, *, date="2026-09-06"):
    payload = {"date": date, "models": {}, "external_feeds": {"forebet_mlb": bucket}}
    (tmp_path / "latest.json").write_text(json.dumps(payload))


def test_refresh_publishes_outage_diagnostics_without_redating_last_good_picks(monkeypatch, tmp_path):
    prior = {
        "ok": True,
        "date": "2026-09-05",
        "updatedAt": "2026-09-05T14:00:00Z",
        "picks": [{"id": "verified", "date": "2026-09-05", "decision": "PASS", "units": 0}],
    }
    _write_previous(tmp_path, prior, date="2026-09-05")
    _configure(
        monkeypatch, tmp_path,
        {"forebet_mlb": lambda *_args: {"ok": False, "error": "Listing blocked by Cloudflare"}},
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    assert refresh.main() == 1

    published = json.loads((tmp_path / "latest.json").read_text())
    bucket = published["external_feeds"]["forebet_mlb"]
    assert bucket["picks"] == prior["picks"]
    assert bucket["date"] == "2026-09-05"
    assert bucket["updatedAt"] == prior["updatedAt"]
    assert bucket["lastSuccessAt"] == prior["updatedAt"]
    assert bucket["lastAttemptDate"] == "2026-09-06"
    assert bucket["refreshStatus"] == "error"
    assert "Cloudflare" in bucket["lastError"]
    assert published["external_feed_errors"] == ["forebet_mlb: Listing blocked by Cloudflare"]
    assert "| forebet_mlb | error | 2026-09-05 | 1 |" in summary.read_text()


def test_refresh_publishes_todays_partial_scores24_cfb_instead_of_yesterday(monkeypatch, tmp_path):
    yesterday = {
        "ok": True,
        "date": "2026-09-10",
        "updatedAt": "2026-09-10T19:12:03Z",
        "picks": [{"pick": "Miami Under", "date": "2026-09-10", "decision": "PASS", "units": 0}],
    }
    (tmp_path / "latest.json").write_text(
        json.dumps({"date": "2026-09-10", "models": {}, "external_feeds": {"scores24_cfb": yesterday}})
    )
    _configure(
        monkeypatch,
        tmp_path,
        {
            "scores24_cfb": lambda *_args: {
                "ok": False,
                "date": "2026-09-11",
                "error": "Scores24CFB scrape timed out after 180s with 4 matched pick(s) of 5 official matchup(s)",
                "picks": [
                    {"pick": "Louisville ML", "date": "2026-09-11", "source": "Scores24CFB"},
                    {"pick": "Stanford ML", "date": "2026-09-11", "source": "Scores24CFB"},
                    {"pick": "Ole Miss ML", "date": "2026-09-11", "source": "Scores24CFB"},
                    {"pick": "Alabama ML", "date": "2026-09-11", "source": "Scores24CFB"},
                ],
            }
        },
        date="2026-09-11",
    )

    assert refresh.main() == 1

    published = json.loads((tmp_path / "latest.json").read_text())
    bucket = published["external_feeds"]["scores24_cfb"]
    assert bucket["date"] == "2026-09-11"
    assert bucket["ok"] is False
    assert bucket["refreshStatus"] == "error"
    assert bucket["lastAttemptDate"] == "2026-09-11"
    assert len(bucket["picks"]) == 4
    assert all(pick["date"] == "2026-09-11" for pick in bucket["picks"])
    assert "timed out" in bucket["lastError"]


def test_optional_timeout_salvages_checkpoint_instead_of_redating_yesterday(tmp_path):
    from scripts.scrapers import scores24_optional_publish as optional

    checkpoint_dir = tmp_path / "state"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "scores24-cfb-2026-09-11.json").write_text(
        json.dumps(
            {
                "sport": "cfb",
                "date": "2026-09-11",
                "picks": [
                    {
                        "source": "Scores24CFB",
                        "pick": "Louisville ML",
                        "date": "2026-09-11",
                        "away_team": "Villanova Wildcats",
                        "home_team": "Louisville Cardinals",
                    },
                    {
                        "source": "Scores24CFB",
                        "pick": "Stanford ML",
                        "date": "2026-09-11",
                        "away_team": "Miami Hurricanes",
                        "home_team": "Stanford Cardinal",
                    },
                    {
                        "source": "Scores24CFB",
                        "pick": "Ole Miss ML",
                        "date": "2026-09-11",
                        "away_team": "Kentucky Wildcats",
                        "home_team": "Ole Miss Rebels",
                    },
                    {
                        "source": "Scores24CFB",
                        "pick": "Alabama ML",
                        "date": "2026-09-11",
                        "away_team": "South Florida Bulls",
                        "home_team": "Alabama Crimson Tide",
                    },
                ],
            }
        )
    )
    yesterday = {
        "ok": True,
        "date": "2026-09-10",
        "updatedAt": "2026-09-10T19:12:03Z",
        "picks": [{"pick": "Miami Under", "date": "2026-09-10", "source": "Scores24CFB"}],
    }
    cache_path = tmp_path / "2026-09-11.json"
    cache_path.write_text(
        json.dumps(
            {
                "date": "2026-09-11",
                "models": {"scores24_mlb": {"ok": True, "date": "2026-09-11", "picks": [{"pick": "Cubs ML"}]}},
                "external_feeds": {
                    "scores24_mlb": {"ok": True, "date": "2026-09-11", "picks": [{"pick": "Cubs ML"}]},
                    "scores24_cfb": yesterday,
                },
            }
        )
    )

    bucket = optional.apply_optional_timeout_to_cache(
        cache_path,
        "scores24_cfb",
        "2026-09-11",
        180,
        checkpoint_dir=str(checkpoint_dir),
        now_iso="2026-09-11T12:00:00Z",
    )
    published = json.loads(cache_path.read_text())
    assert bucket["date"] == "2026-09-11"
    assert bucket["ok"] is False
    assert bucket["refreshStatus"] == "error"
    assert len(bucket["picks"]) == 4
    assert published["external_feeds"]["scores24_mlb"]["ok"] is True
    assert published["external_feeds"]["scores24_cfb"]["picks"][0]["pick"] == "Louisville ML"


def test_optional_timeout_without_checkpoint_keeps_yesterday_date(tmp_path):
    from scripts.scrapers import scores24_optional_publish as optional

    yesterday = {
        "ok": True,
        "date": "2026-09-10",
        "updatedAt": "2026-09-10T19:12:03Z",
        "picks": [{"pick": "Miami Under", "date": "2026-09-10", "source": "Scores24CFB"}],
    }
    cache_path = tmp_path / "2026-09-11.json"
    cache_path.write_text(
        json.dumps({"date": "2026-09-11", "models": {}, "external_feeds": {"scores24_cfb": yesterday}})
    )

    bucket = optional.apply_optional_timeout_to_cache(
        cache_path,
        "scores24_cfb",
        "2026-09-11",
        180,
        checkpoint_dir=str(tmp_path / "empty"),
        now_iso="2026-09-11T12:00:00Z",
    )
    assert bucket["date"] == "2026-09-10"
    assert bucket["picks"] == yesterday["picks"]
    assert bucket["lastAttemptDate"] == "2026-09-11"
    assert bucket["refreshStatus"] == "error"
    assert "timed out" in bucket["lastError"]


def test_optional_feed_hard_timeout_kills_child_and_returns_soft_fail(tmp_path):
    from scripts.scrapers import scores24_optional_publish as optional

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "refresh_external_feeds.py").write_text("import time\ntime.sleep(30)\n")
    cache_path = tmp_path / "2026-09-11.json"
    cache_path.write_text(json.dumps({"date": "2026-09-11", "models": {}, "external_feeds": {}}))

    started = time.monotonic()
    rc = optional.run_optional_scores24_feed(
        python_bin=sys.executable,
        repo=str(repo),
        date_iso="2026-09-11",
        feed_key="scores24_cfb",
        sports="cfb",
        timeout_seconds=0.5,
        cache_path=str(cache_path),
        checkpoint_dir=str(tmp_path / "state"),
    )
    elapsed = time.monotonic() - started
    assert rc == 0
    assert elapsed < 8
    bucket = json.loads(cache_path.read_text())["external_feeds"]["scores24_cfb"]
    assert bucket["refreshStatus"] == "error"
    assert bucket["lastAttemptDate"] == "2026-09-11"
    assert bucket["ok"] is False
    assert "timed out" in bucket["lastError"]


def test_optional_timeout_salvage_does_not_leak_checkpoint_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SCORES24_CHECKPOINT_DIR", raising=False)
    from scripts.scrapers import scores24_optional_publish as optional

    checkpoint_dir = tmp_path / "state"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "scores24-cfb-2026-09-11.json").write_text(
        json.dumps(
            {
                "sport": "cfb",
                "date": "2026-09-11",
                "picks": [
                    {
                        "source": "Scores24CFB",
                        "pick": "Louisville ML",
                        "date": "2026-09-11",
                    }
                ],
            }
        )
    )
    cache_path = tmp_path / "2026-09-11.json"
    cache_path.write_text(json.dumps({"date": "2026-09-11", "models": {}, "external_feeds": {}}))

    optional.apply_optional_timeout_to_cache(
        cache_path,
        "scores24_cfb",
        "2026-09-11",
        180,
        checkpoint_dir=str(checkpoint_dir),
        now_iso="2026-09-11T12:00:00Z",
    )
    assert os.environ.get("SCORES24_CHECKPOINT_DIR") in {None, ""}
    published = json.loads(cache_path.read_text())
    assert len(published["external_feeds"]["scores24_cfb"]["picks"]) == 1


def test_refresh_recovers_and_clears_previous_source_error(monkeypatch, tmp_path):
    _write_previous(tmp_path, {
        "ok": True, "date": "2026-09-06", "picks": [],
        "refreshStatus": "error", "lastError": "Previous source outage",
    })
    previous = json.loads((tmp_path / "latest.json").read_text())
    previous["external_feed_errors"] = ["forebet_mlb: Previous source outage"]
    (tmp_path / "latest.json").write_text(json.dumps(previous))
    _configure(monkeypatch, tmp_path, {"forebet_mlb": lambda *_args: {"ok": True, "picks": []}})

    assert refresh.main() == 0

    published = json.loads((tmp_path / "latest.json").read_text())
    assert published["external_feed_errors"] == []
    bucket = published["external_feeds"]["forebet_mlb"]
    assert bucket["refreshStatus"] == "ok"
    assert bucket["lastSuccessAt"] == bucket["lastAttemptAt"]
    assert "lastError" not in bucket


def test_refresh_exposes_failed_source_that_has_never_published(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, {"forebet_mlb": lambda *_args: {"ok": False, "error": "Timed out"}})

    assert refresh.main() == 1

    published = json.loads((tmp_path / "latest.json").read_text())
    for bucket in (
        published["external_feeds"]["forebet_mlb"],
        published["models"]["forebet_mlb"],
        published["forebet_mlb"],
    ):
        assert bucket["ok"] is False
        assert bucket["picks"] == []
        assert bucket["refreshStatus"] == "error"
        assert bucket["lastError"] == "Timed out"


def test_refresh_reports_sport_failure_while_publishing_valid_other_sport(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, {
        "sportytrader": lambda *_args: {
            "ok": True,
            "picks": [{"sport": "MLB", "pick": "Cubs ML", "decision": "BET", "units": 1}],
            "errors": ["cfb: Official CFB slate unavailable"],
            "meta": {"sportErrors": {"cfb": "Official CFB slate unavailable"}},
        },
    })

    assert refresh.main() == 0

    published = json.loads((tmp_path / "latest.json").read_text())
    assert published["external_feed_errors"] == ["sportytrader_cfb: Official CFB slate unavailable"]
    assert published["sportytrader_cfb"]["refreshStatus"] == "error"
    mlb = published["sportytrader_mlb"]
    assert mlb["refreshStatus"] == "ok"
    assert mlb["errors"] == []
    assert published["sportytrader_cfb"]["errors"] == ["Official CFB slate unavailable"]
    assert mlb["picks"][0]["pick"] == "Cubs ML"
    assert mlb["picks"][0]["decision"] == "PASS"
    assert mlb["picks"][0]["units"] == 0


def test_workflow_publishes_diagnostics_before_marking_total_outage_failed():
    workflow = (refresh.REPO_ROOT / ".github/workflows/external-feed-refresh.yml").read_text()
    assert "id: refresh-feeds\n" in workflow
    assert "continue-on-error: true" in workflow
    assert workflow.index("Report refresh failure after publishing diagnostics") > workflow.index("Deploy updated external feeds")
    assert "if: steps.refresh-feeds.outcome == 'failure'" in workflow
