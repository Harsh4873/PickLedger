from __future__ import annotations

import json
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
