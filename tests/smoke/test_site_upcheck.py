from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.site_upcheck import _missing_ml_player_prop_fields


ROOT = Path(__file__).resolve().parents[2]
MODEL_KEYS = {
    "mlb_new",
    "mlb_inning",
    "mlb_first_five",
    "wnba",
    "nba",
    "nba_playoffs",
    "nfl",
    "cfb",
}
PLAYER_PROP_KEYS = {
    "nba_player_props",
    "mlb_player_props",
    "wnba_player_props",
    "nfl_player_props",
    "cfb_player_props",
}
SCORES24_KEYS = {
    "scores24_mlb",
    "scores24_wnba",
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _market_priced_ml_prop(date: str, sport: str) -> dict:
    return {
        "date": date,
        "scope": "player",
        "sport": sport,
        "pick": f"Test {sport} player prop",
        "decision": "PASS",
        "market_priced": True,
        "odds": -110,
        "odds_source": "posted_market",
        "probability_source": "player_props_ml_v1",
        "ml_probability": 0.61,
        "ml_edge": 0.07,
        "ml_expected_value": 0.11,
        "ml_model_version": "player_props_ml_v1.1.0",
        "ml_market_family": "hits" if sport == "MLB" else "points",
        "ml_rank": 1,
        "baseline_projection": 2.4,
    }


def _upcheck_repo(tmp_path: Path, date: str) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(ROOT / "scripts" / "site_upcheck.py", scripts / "site_upcheck.py")

    model_payload = {
        "date": date,
        "models": {key: {"ok": True, "picks": []} for key in MODEL_KEYS},
        "external_feeds": {
            key: {
                "ok": True,
                "date": date,
                "picks": [],
                "meta": {"expectedMatchups": 0, "matchedPicks": 0, "missingMatchups": []},
            }
            for key in SCORES24_KEYS
        },
    }
    props_payload = {"date": date, "models": {key: {"ok": True, "picks": []} for key in PLAYER_PROP_KEYS}}
    parlay_payload = {
        "date": date,
        "engineVersion": "parlay_cards_v6_proven_legs",
        "summary": {"displayedCards": 0, "threeLegCards": 0},
        "cards": [],
    }
    profit_payload = {
        "schemaVersion": "2",
        "date": date,
        "engineVersion": "profit_desk_v2_live",
        "phase": "live",
        "policy": {"mode": "live", "status": "LIVE", "liveStaking": True},
        "summary": {
            "candidateCount": 0,
            "candidatesEvaluated": 0,
            "shadowQualified": 0,
            "researchQualified": 0,
            "edgeQualified": 0,
            "valueQualified": 0,
            "liveQualified": 0,
        },
        "candidates": [],
        "portfolio": {"team": [], "player": [], "all": [], "live": []},
    }
    for cache_name, payload in (("model_cache", model_payload), ("player_props_cache", props_payload)):
        cache_dir = tmp_path / "data" / cache_name
        _write_json(cache_dir / "latest.json", payload)
        _write_json(cache_dir / f"{date}.json", payload)
        _write_json(cache_dir / "index.json", {"files": [f"{date}.json"]})
    parlay_dir = tmp_path / "data" / "parlay_cards"
    _write_json(parlay_dir / "latest.json", parlay_payload)
    _write_json(parlay_dir / f"{date}.json", parlay_payload)
    _write_json(parlay_dir / "index.json", {"files": [f"{date}.json"]})
    profit_dir = tmp_path / "data" / "profit_desk"
    _write_json(profit_dir / "latest.json", profit_payload)
    _write_json(profit_dir / f"{date}.json", profit_payload)
    _write_json(
        profit_dir / "index.json",
        {
            "engineVersion": "profit_desk_v2_live",
            "files": [f"{date}.json"],
        },
    )
    return scripts / "site_upcheck.py"


def test_data_only_readiness_passes_without_build_or_cannon(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert not (tmp_path / "dist").exists()
    assert "Cannon" not in result.stdout


def test_data_only_readiness_allows_truly_empty_mlb_player_prop_slate(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["models"]["mlb_player_props"].update({"games": 0, "picks": [], "abstained": True})
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout


def test_data_only_readiness_rejects_zero_mlb_props_when_official_games_exist(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    yesterday = (datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=1)).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["models"]["mlb_player_props"].update(
        {"ok": False, "date": yesterday, "games": 1, "picks": [], "abstained": True}
    )
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "mlb_player_props has scheduled games but zero picks" in result.stdout


def test_data_only_readiness_uses_independent_mlb_team_slate(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    model_path = tmp_path / "data" / "model_cache" / "latest.json"
    model_payload = json.loads(model_path.read_text(encoding="utf-8"))
    model_payload["models"]["mlb_inning"]["games"] = [{"game_id": "all-star"}]
    _write_json(model_path, model_payload)
    props_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    props_payload = json.loads(props_path.read_text(encoding="utf-8"))
    props_payload["models"]["mlb_player_props"].update({"games": 0, "picks": [], "abstained": True})
    _write_json(props_path, props_payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "mlb_player_props has scheduled games but zero picks" in result.stdout


def test_data_only_readiness_ignores_next_central_date_mlb_team_game(tmp_path: Path):
    today_dt = datetime.now(ZoneInfo("America/Chicago"))
    today = today_dt.strftime("%Y-%m-%d")
    tomorrow = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    model_path = tmp_path / "data" / "model_cache" / "latest.json"
    model_payload = json.loads(model_path.read_text(encoding="utf-8"))
    model_payload["models"]["mlb_first_five"]["games"] = [
        {
            "matchup": "New York Mets @ Philadelphia Phillies",
            "game_start_time": f"{tomorrow}T23:10:00Z",
        }
    ]
    _write_json(model_path, model_payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout


def test_data_only_readiness_allows_documented_mlb_props_gate_abstention(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    model_path = tmp_path / "data" / "model_cache" / "latest.json"
    model_payload = json.loads(model_path.read_text(encoding="utf-8"))
    model_payload["models"]["mlb_inning"]["games"] = [{"game_id": "all-star"}]
    _write_json(model_path, model_payload)
    props_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    props_payload = json.loads(props_path.read_text(encoding="utf-8"))
    props_payload["models"]["mlb_player_props"].update(
        {
            "ok": True,
            "date": today,
            "games": 1,
            "picks": [],
            "abstained": True,
            "candidate_count": 12,
            "scored_count": 40,
            "consensus_rejected_count": 40,
            "consensus_rejection_reasons": {"under price unavailable": 4},
            "note": "No MLB prop cleared the consensus publication gate.",
        }
    )
    _write_json(props_path, props_payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "documented gate/special-event abstention" in result.stdout


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "market_priced",
        "odds",
        "odds_source",
        "probability_source",
        "ml_probability",
        "ml_edge",
        "ml_expected_value",
        "ml_model_version",
        "ml_market_family",
        "ml_rank",
        "baseline_projection",
    ],
)
def test_market_priced_ml_prop_schema_requires_every_field(field: str):
    prop = _market_priced_ml_prop("2026-07-14", "MLB")
    assert _missing_ml_player_prop_fields(prop) == []

    prop.pop(field)

    assert field in _missing_ml_player_prop_fields(prop)


@pytest.mark.parametrize(("bucket_key", "sport"), [("mlb_player_props", "MLB"), ("wnba_player_props", "WNBA")])
@pytest.mark.parametrize("missing_field", ["baseline_projection", "market_priced", "odds_source", "scope"])
def test_data_only_readiness_rejects_incomplete_market_priced_ml_schema(
    tmp_path: Path,
    bucket_key: str,
    sport: str,
    missing_field: str,
):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    prop = _market_priced_ml_prop(today, sport)
    prop.pop(missing_field)
    payload["models"][bucket_key].update({"games": 1, "picks": [prop]})
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert f"{bucket_key} published pick 1" in result.stdout
    assert missing_field in result.stdout


def test_data_only_readiness_defers_stale_daily_data(tmp_path: Path):
    yesterday = (datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=1)).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, yesterday)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "[readiness] waiting:" in result.stdout
    assert "expected" in result.stdout


def test_data_only_readiness_warns_on_incomplete_scores24_bucket(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"]["scores24_wnba"] = {
        "ok": False,
        "date": today,
        "picks": [{"matchup": "Qatar @ Canada"}],
        "error": "blocked before official slate completed",
        "meta": {
            "expectedMatchups": 2,
            "matchedPicks": 1,
            "missingMatchups": ["South Africa @ Czechia"],
        },
    }
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "[readiness] warning:" in result.stdout
    assert "scores24_wnba failed" in result.stdout


def test_data_only_readiness_warns_on_incomplete_scores24_coverage(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"]["scores24_mlb"]["meta"] = {
        "expectedMatchups": 2,
        "matchedPicks": 0,
        "missingMatchups": ["Yankees @ Red Sox"],
    }
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "[readiness] warning:" in result.stdout
    assert "scores24_mlb has incomplete official-slate coverage" in result.stdout


def test_data_only_readiness_allows_missing_scores24_when_inhouse_ready(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"] = {}
    for key in SCORES24_KEYS:
        payload.get("models", {}).pop(key, None)
    _write_json(cache_path, payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "[readiness] warning:" in result.stdout
    assert "scores24_mlb is missing" in result.stdout
    assert "scores24_wnba is missing" in result.stdout


def test_data_only_readiness_still_fails_missing_inhouse_without_scores24(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"] = {}
    del payload["models"]["mlb_new"]
    _write_json(cache_path, payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "model bucket mlb_new is missing" in result.stdout
    assert "scores24_mlb is missing" in result.stdout
    assert "[readiness] waiting:" in result.stdout


def test_data_only_readiness_allows_stale_but_valid_scores24_feed(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    yesterday = (datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=1)).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    # Scores24 refreshes only from a residential IP, so its published date can lag a day
    # behind the rest of today's data. Yesterday's otherwise-valid MLB/WNBA buckets must
    # warn without freezing the deploy — in-house model/props/parlay data is today's.
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    for key in SCORES24_KEYS:
        payload["external_feeds"][key]["date"] = yesterday
    _write_json(cache_path, payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "[readiness] warning:" in result.stdout
    assert f"scores24_mlb is {yesterday}" in result.stdout


def test_data_only_readiness_ignores_blocked_scores24_cfb(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"]["scores24_cfb"] = {
        "ok": False,
        "date": today,
        "picks": [],
        "error": "blocked before official slate completed",
        "meta": {
            "expectedMatchups": 8,
            "matchedPicks": 0,
            "missingMatchups": ["Toledo @ Michigan State"],
        },
    }
    _write_json(cache_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout
    assert "scores24_cfb" not in result.stdout


def test_data_only_readiness_allows_weak_parlay_slate_without_team_cards(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    model_payload_path = tmp_path / "data" / "model_cache" / "latest.json"
    model_payload = json.loads(model_payload_path.read_text(encoding="utf-8"))
    model_payload["models"]["mlb_new"]["picks"] = [
        {"date": today, "sport": "MLB", "pick": "Visible bet A", "decision": "BET", "grade_supported": True},
        {"date": today, "sport": "MLB", "pick": "Visible bet B", "decision": "BET", "grade_supported": True},
        {"date": today, "sport": "MLB", "pick": "Visible lean C", "decision": "LEAN", "grade_supported": True},
    ]
    _write_json(model_payload_path, model_payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", model_payload)

    parlay_payload = {
        "date": today,
        "engineVersion": "parlay_cards_v6_proven_legs",
        "summary": {
            "eligibleLegs": 3,
            "generatedThreeLegCandidates": 0,
            "displayedCards": 0,
            "threeLegCards": 0,
            "modes": {
                "team": {"displayedCards": 0},
                "player": {"displayedCards": 0},
            },
        },
        "cards": [],
    }
    _write_json(tmp_path / "data" / "parlay_cards" / "latest.json", parlay_payload)
    _write_json(tmp_path / "data" / "parlay_cards" / f"{today}.json", parlay_payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "daily data is ready" in result.stdout


def test_data_only_readiness_rejects_stake_without_live_qualification(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    profit_path = tmp_path / "data" / "profit_desk" / "latest.json"
    payload = json.loads(profit_path.read_text(encoding="utf-8"))
    payload["summary"]["candidateCount"] = 1
    payload["summary"]["candidatesEvaluated"] = 1
    payload["candidates"] = [{
        "id": "unsafe",
        "tier": "value",
        "stakeUnits": 0.5,
        "liveQualified": False,
        "blockers": [],
    }]
    _write_json(profit_path, payload)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "stake without live qualification" in result.stdout


def test_data_only_readiness_requires_profit_desk_manifest(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    (tmp_path / "data" / "profit_desk" / "index.json").unlink()

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "data/profit_desk/index.json is missing or invalid" in result.stdout


def test_upcheck_reports_raw_and_visible_pick_counts(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="./src/styles/pickledger.css">'
        '<script type="module" src="./src/main.ts"></script>',
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/index.css">'
        '<script type="module" src="/assets/index.js"></script>',
        encoding="utf-8",
    )

    model_payload_path = tmp_path / "data" / "model_cache" / "latest.json"
    model_payload = json.loads(model_payload_path.read_text(encoding="utf-8"))
    model_payload["models"]["mlb_new"]["picks"] = [
        {"date": today, "sport": "MLB", "pick": "Raw pass", "decision": "PASS"},
        {"date": today, "sport": "MLB", "pick": "Visible lean", "decision": "LEAN"},
    ]
    _write_json(model_payload_path, model_payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", model_payload)

    props_payload_path = tmp_path / "data" / "player_props_cache" / "latest.json"
    props_payload = json.loads(props_payload_path.read_text(encoding="utf-8"))
    visible_pass = _market_priced_ml_prop(today, "MLB")
    visible_pass["pick"] = "Visible pass"
    hidden_unknown = _market_priced_ml_prop(today, "MLB")
    hidden_unknown.update({"pick": "Hidden unknown", "decision": "UNKNOWN", "ml_rank": 2})
    props_payload["models"]["mlb_player_props"]["picks"] = [visible_pass, hidden_unknown]
    _write_json(props_payload_path, props_payload)
    _write_json(tmp_path / "data" / "player_props_cache" / f"{today}.json", props_payload)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "[upcheck] failure:" not in result.stdout
    assert "teams_raw=" in result.stdout
    assert "teams_visible=" in result.stdout
    assert "player_props_raw=" in result.stdout
    assert "player_props_visible=" in result.stdout
    assert "'mlb_new': 2" in result.stdout
    assert "'mlb_new': 1" in result.stdout
    assert "'mlb_player_props': 2" in result.stdout
    assert "'mlb_player_props': 1" in result.stdout



def test_data_only_readiness_allows_complete_scores24_without_inhouse_models(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    yesterday = (datetime.now(ZoneInfo("America/Chicago")) - timedelta(days=1)).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)

    model_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    payload["models"] = {
        key: payload["external_feeds"][key]
        for key in SCORES24_KEYS
    }
    _write_json(model_path, payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", payload)

    for cache_name in ("player_props_cache", "parlay_cards", "profit_desk"):
        cache_dir = tmp_path / "data" / cache_name
        latest = json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))
        latest["date"] = yesterday
        _write_json(cache_dir / "latest.json", latest)
        _write_json(cache_dir / f"{yesterday}.json", latest)
        (cache_dir / f"{today}.json").unlink()
        manifest = json.loads((cache_dir / "index.json").read_text(encoding="utf-8"))
        manifest["files"] = [f"{yesterday}.json"]
        _write_json(cache_dir / "index.json", manifest)

    result = subprocess.run(
        [sys.executable, str(script), "--data-only"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    assert "daily data is ready" in result.stdout
    assert "today's Scores24 slate is complete" in result.stdout


def test_full_upcheck_allows_missing_scores24_when_inhouse_ready(tmp_path: Path):
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    script = _upcheck_repo(tmp_path, today)
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="./src/styles/pickledger.css">'
        '<script type="module" src="./src/main.ts"></script>',
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/index.css">'
        '<script type="module" src="/assets/index.js"></script>',
        encoding="utf-8",
    )
    cache_path = tmp_path / "data" / "model_cache" / "latest.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["external_feeds"] = {}
    _write_json(cache_path, payload)
    _write_json(tmp_path / "data" / "model_cache" / f"{today}.json", payload)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout
    assert "[upcheck] warning:" in result.stdout
    assert "scores24_mlb is missing" in result.stdout
    assert "[upcheck] failure:" not in result.stdout
    assert "healthy for" in result.stdout
