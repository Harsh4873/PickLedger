"""CFB serving model, pipeline, settlement, and containment contracts."""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _game(game_id: str, date: str, home_score: int, away_score: int, *, fbs: bool = True) -> dict:
    return {
        "game_id": game_id,
        "season": 2025,
        "week": int(game_id[-1]),
        "start_time": f"{date}T17:00:00Z",
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "home_team_id": "1",
        "away_team_id": str(int(game_id[-1]) + 1),
        "home_team": "Home State",
        "away_team": "Away Tech",
        "home_division": "fbs" if fbs else "fcs",
        "away_division": "fbs",
        "home_score": float(home_score),
        "away_score": float(away_score),
        "home_line": -3.5,
        "total_line": 52.5,
    }


def test_originator_is_strictly_as_of_and_market_free():
    from CFBPredictionModel.cfb_core import FEATURE_NAMES, build_dataset

    rows = [
        _game("g1", "2025-08-30", 70, 0),
        _game("g2", "2025-09-06", 28, 21),
    ]
    records = build_dataset(rows)
    assert len(records) == 2
    assert records[0]["features"]["home_offense_ewma"] == 28.0
    assert records[1]["features"]["home_offense_ewma"] > 28.0
    assert not {"home_line", "spread", "total_line", "moneyline"} & set(FEATURE_NAMES)


def test_training_population_filters_non_fbs_and_missing_lines():
    from CFBPredictionModel.cfb_core import build_dataset

    fcs = _game("g1", "2025-08-30", 30, 10, fbs=False)
    missing_line = _game("g2", "2025-09-06", 28, 21)
    missing_line["total_line"] = None
    assert build_dataset([fcs, missing_line]) == []


def test_public_serving_emits_exactly_three_stable_market_rows(monkeypatch):
    from CFBPredictionModel import cfb_model
    from CFBPredictionModel.cfb_core import FEATURE_NAMES

    features = {name: 0.0 for name in FEATURE_NAMES}
    entry = {
        "features": features,
        "game": {
            "game_id": "401900001",
            "event_id": "401900001",
            "home_team_id": "1",
            "away_team_id": "2",
            "home_team": "Home State Wildcats",
            "away_team": "Away Tech Owls",
            "start_time": "2026-09-05T17:00:00Z",
            "neutral_site": False,
            "home_line": -3.5,
            "total_line": 52.5,
            "home_moneyline": -155,
            "away_moneyline": 135,
            "odds_source": "espn_scoreboard:DraftKings",
        },
    }
    monkeypatch.setattr(cfb_model, "serving_rows", lambda _date, **_kwargs: [entry])
    payload = cfb_model.generate_cfb_picks("2026-09-05")
    assert payload["ok"] is True
    assert payload["shadow_mode"] is False
    assert payload["model"] == "CFB Model"
    assert payload["actionability"] == "bet_signal"
    assert len(payload["games"]) == 1
    assert len(payload["picks"]) == 3
    assert {pick["source"] for pick in payload["picks"]} == {"CFB ML", "CFB Spread", "CFB Total"}
    assert {pick["market"] for pick in payload["picks"]} == {"h2h", "spread", "totals"}
    for pick in payload["picks"]:
        assert pick["shadow_mode"] is False
        assert pick["actionability"] == "bet_signal"
        assert pick["espn_event_id"] == "401900001"
        assert pick["home_team_id"] == "1"
        assert pick["away_team_id"] == "2"
        assert 0 <= pick["push_probability"] < 1
        assert pick["decision"] in {"BET", "LEAN", "PASS"}
        assert pick["units"] == (0.5 if pick["decision"] == "BET" else 0.25 if pick["decision"] == "LEAN" else 0)


def test_artifact_records_walk_forward_calibration_and_feature_contract():
    metadata = json.loads((ROOT / "CFBPredictionModel" / "artifacts" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["model_version"].startswith("cfb_")
    assert metadata["games"] > 5000
    assert metadata["walk_forward"]
    assert metadata["selected_family"] in {"ridge", "hist_gradient_boosting"}
    assert metadata["residual_distribution"]["kind"] == "bivariate_gaussian_oof"
    assert metadata["residual_distribution"]["samples"] > 3000
    assert set(metadata["calibration"]) == {"moneyline", "spread", "total"}
    assert metadata["market_features"] == []
    assert metadata["promotion_status"] == "not_qualified"
    assert (ROOT / "CFBPredictionModel" / "artifacts" / "cfb_model.joblib").stat().st_size > 1000


def test_cfb_model_is_a_core_freshness_requirement():
    import pickgrader_server as server
    from scripts import site_upcheck
    from scripts.market_odds import SPORT_LEAGUES, TEAM_MODEL_BUCKET_KEYS
    from scripts.merge_external_feed_cache_payload import REQUIRED_TEAM_MODEL_KEYS
    from scripts.merge_model_cache_payload import DEPLOYED_MODEL_KEYS, MODEL_ALIAS_KEYS
    from scripts.pick_calibration import CALIBRATION_EXCLUDED_MODEL_KEYS
    from scripts.refresh_model_cache import _model_jobs
    from scripts.team_prop_model_evaluator import SUPPORTED_MODEL_KEYS
    from scripts.team_prop_pregame_ledger import TEAM_PROP_MODEL_KEYS

    assert server.SPORT_TO_ESPNSLUG["CFB"] == ("football", "college-football")
    assert callable(server.run_cfb_model)
    assert SPORT_LEAGUES["CFB"] == ("football", "college-football")
    assert "cfb" in TEAM_MODEL_BUCKET_KEYS
    assert "cfb" in DEPLOYED_MODEL_KEYS
    assert "cfb" in MODEL_ALIAS_KEYS
    assert "cfb" in TEAM_PROP_MODEL_KEYS
    assert "cfb" in SUPPORTED_MODEL_KEYS
    assert "cfb" in CALIBRATION_EXCLUDED_MODEL_KEYS
    assert "cfb" in _model_jobs("2026-09-05")
    assert "cfb" in site_upcheck.REQUIRED_MODEL_KEYS
    assert "cfb" in REQUIRED_TEAM_MODEL_KEYS
    assert "scores24_cfb" not in site_upcheck.REQUIRED_SCORES24_FEED_KEYS


def test_research_rows_are_contained_from_staked_recommendations():
    parlay = (ROOT / "scripts" / "build_parlay_cards.py").read_text(encoding="utf-8")
    profit = (ROOT / "scripts" / "build_profit_desk.py").read_text(encoding="utf-8")
    serving = (ROOT / "CFBPredictionModel" / "cfb_model.py").read_text(encoding="utf-8")
    assert "if pick.get(\"shadow_mode\") is True:" in parlay
    assert "if record.get(\"shadow_mode\") is True:" in profit
    assert '"shadow_mode": False' in serving
    assert '"actionability": "bet_signal"' in serving
    assert '"model": "CFB Model"' in serving
    assert "TEAM_VISIBLE_DECISIONS = {\"BET\", \"LEAN\"}" in parlay


def test_pass_rows_enter_forecast_audit_ledger(tmp_path):
    from scripts.team_prop_pregame_ledger import (
        capture_team_prop_pregame_snapshots,
        load_team_prop_pregame_ledger,
        stamp_team_prop_pregame_timing,
    )

    payload = {
        "date": "2026-09-05",
        "generatedAt": "2026-09-05T12:00:00Z",
        "models": {
            "cfb": {
                "ok": True,
                "model_version": "cfb_v1",
                "picks": [{
                    "game_id": "401900001",
                    "sport": "CFB",
                    "date": "2026-09-05",
                    "pick": "Away Tech +3.5 (Away Tech @ Home State)",
                    "market": "spread",
                    "decision": "PASS",
                    "start_time": "2026-09-05T17:00:00Z",
                    "odds": -110,
                    "pricing_type": "assumed",
                    "features": {"elo_diff": 20.0},
                }],
            }
        },
    }
    stamp_team_prop_pregame_timing(payload, published_at=payload["generatedAt"])
    summary = capture_team_prop_pregame_snapshots(payload, repo_root=tmp_path)
    assert summary == {"added": 1, "unchanged": 0, "team_picks": 1}
    records = load_team_prop_pregame_ledger(tmp_path)["records"]
    assert len(records) == 1
    assert records[0]["model_key"] == "cfb"
    assert records[0]["financial_eligible"] is False


def test_cfb_pass_ledger_rows_are_graded_for_forecast_evaluation():
    from scripts.auto_grade_picks import _pending_certified_team_prop_candidate

    record = {
        "id": "cfb-pass-record",
        "model_key": "cfb",
        "result": "pending",
        "decision": "PASS",
        "certification": {"status": "certified"},
        "pregame_snapshot": {
            "decision": "PASS",
            "date": "2026-09-05",
            "sport": "CFB",
            "pick": "Away Tech +3.5 (Away Tech @ Home State)",
        },
    }
    candidate = _pending_certified_team_prop_candidate(record)
    assert candidate is not None
    assert candidate[1]["decision"] == "PASS"


def _graded_game(home_score: int, away_score: int) -> dict:
    return {
        "competitors": [
            {"score": home_score, "raw": {"team": {"id": "1", "displayName": "Home State Wildcats", "abbreviation": "HST"}}},
            {"score": away_score, "raw": {"team": {"id": "2", "displayName": "Away Tech Owls", "abbreviation": "ATO"}}},
        ]
    }


def test_generic_grader_settles_cfb_moneyline_spread_total_and_pushes():
    import pickgrader_server as server

    game = _graded_game(30, 27)
    assert server.grade_pick({"sport": "CFB", "pick": "Home State Wildcats ML"}, game) == "win"
    assert server.grade_pick({"sport": "CFB", "pick": "Away Tech Owls +2.5"}, game) == "loss"
    assert server.grade_pick({"sport": "CFB", "pick": "Home State Wildcats -3"}, game) == "push"
    assert server.grade_pick({"sport": "CFB", "pick": "Over 57"}, game) == "push"
    assert server.grade_pick({"sport": "CFB", "pick": "Under 57.5"}, game) == "win"


def test_cfb_scoreboard_fetch_uses_fbs_group_and_large_limit(monkeypatch):
    import pickgrader_server as server

    seen: dict[str, str] = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"events": []}

    def fake_get(url, **_kwargs):
        seen["url"] = url
        return Response()

    monkeypatch.setattr(server.requests, "get", fake_get)
    assert server.fetch_scoreboard("football", "college-football", "20260905") == {"events": []}
    assert "limit=1000" in seen["url"]
    assert "groups=80" in seen["url"]


def test_cfb_training_workflow_is_manual_and_isolated():
    workflow = (ROOT / ".github" / "workflows" / "cfb-train.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "group: cfb-train" in workflow
    assert "CFBPredictionModel/requirements.txt" in workflow


def _scoreboard_event(*, state="pre", odds=None):
    return {
        "id": "401900001", "date": "2026-09-05T17:00:00Z",
        "status": {"type": {"state": state}}, "season": {"year": 2026},
        "competitions": [{
            "neutralSite": False,
            "competitors": [
                {"homeAway": "home", "team": {"id": "1", "displayName": "Home State"}},
                {"homeAway": "away", "team": {"id": "2", "displayName": "Away Tech"}},
            ],
            "odds": [odds] if odds else [],
        }],
    }


def _mock_scoreboard(monkeypatch, payload):
    from CFBPredictionModel import cfb_core
    from scripts.scrapers import espn_scoreboard

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    monkeypatch.setattr(cfb_core.requests, "get", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(espn_scoreboard, "_fetch_via_curl_cffi", lambda _url: None)
    monkeypatch.setattr(espn_scoreboard.time, "sleep", lambda _seconds: None)


def test_cfb_scoreboard_preserves_unpriced_pregame_games_and_explains_started_games(monkeypatch):
    from CFBPredictionModel.cfb_core import load_live_slate

    _mock_scoreboard(monkeypatch, {"events": [_scoreboard_event(), _scoreboard_event(state="post")]})
    coverage = {}
    slate = load_live_slate("2026-09-05", coverage=coverage)
    assert len(slate) == 1
    assert slate[0]["home_moneyline"] is None
    assert slate[0]["home_line"] is None
    assert coverage == {"official_games": 2, "started_games": 1, "incomplete_games": 0,
                        "pregame_games": 1, "unpriced_games": 1}


def test_cfb_scoreboard_reads_current_nested_market_prices(monkeypatch):
    from CFBPredictionModel.cfb_core import load_live_slate

    odds = {
        "spread": -3.5, "overUnder": 52.5,
        "moneyline": {"home": {"current": {"odds": "-155"}}, "away": {"close": {"odds": "+135"}}},
        "pointSpread": {"home": {"close": {"odds": "-115"}}, "away": {"close": {"odds": "-105"}}},
        "total": {"over": {"open": {"odds": "-108"}}, "under": {"open": {"odds": "-112"}}},
    }
    _mock_scoreboard(monkeypatch, {"events": [_scoreboard_event(odds=odds)]})
    game = load_live_slate("2026-09-05")[0]
    assert (game["home_moneyline"], game["away_moneyline"]) == (-155, 135)
    assert (game["home_spread_odds"], game["away_spread_odds"]) == (-115, -105)
    assert (game["over_odds"], game["under_odds"]) == (-108, -112)


def test_cfb_scoreboard_invalid_payload_does_not_claim_no_games(monkeypatch):
    from CFBPredictionModel.cfb_core import load_live_slate

    _mock_scoreboard(monkeypatch, {"error": "unavailable"})
    with pytest.raises(ValueError, match="invalid events"):
        load_live_slate("2026-09-05")


@pytest.mark.parametrize("home_line,total_line,markets", [
    (None, None, {"h2h"}),
    (None, 52.5, {"h2h", "totals"}),
    (-3.5, None, {"h2h", "spread"}),
    (-3.5, 52.5, {"h2h", "spread", "totals"}),
])
def test_cfb_unpriced_forecasts_have_no_fabricated_prices_or_stakes(monkeypatch, home_line, total_line, markets):
    from CFBPredictionModel import cfb_model
    from CFBPredictionModel.cfb_core import FEATURE_NAMES

    game = {
        "game_id": "401900001", "home_team_id": "1", "away_team_id": "2",
        "home_team": "Home State", "away_team": "Away Tech",
        "start_time": "2026-09-05T17:00:00Z", "home_line": home_line, "total_line": total_line,
        "home_moneyline": None, "away_moneyline": None, "odds_source": "espn_scoreboard:unknown",
    }
    entry = {"game": game, "features": {name: 0.0 for name in FEATURE_NAMES}}
    monkeypatch.setattr(cfb_model, "serving_rows", lambda _date, **_kwargs: [entry])
    payload = cfb_model.generate_cfb_picks("2026-09-05")
    assert payload["ok"] is True
    assert {pick["market"] for pick in payload["picks"]} == markets
    for pick in payload["picks"]:
        assert pick["date"] == "2026-09-05"
        assert pick["odds"] is None
        assert pick["expected_value"] is None
        assert pick["edge"] is None
        assert pick["units"] == 0
        assert pick["decision"] == "PASS"
        assert pick["shadow_mode"] is False
        assert pick["market_priced"] is False


def test_cfb_missing_artifacts_fail_visibly(monkeypatch):
    from CFBPredictionModel import cfb_model

    monkeypatch.setattr(cfb_model, "_load_artifacts", lambda: None)
    payload = cfb_model.generate_cfb_picks("2026-09-05")
    assert payload["ok"] is False
    assert "artifacts" in payload["error"]
    assert payload["picks"] == []


def test_cfb_no_game_day_has_explicit_coverage(monkeypatch):
    from CFBPredictionModel import cfb_model

    def empty_slate(_date, *, coverage):
        coverage.update(official_games=0, pregame_games=0)
        return []

    monkeypatch.setattr(cfb_model, "serving_rows", empty_slate)
    payload = cfb_model.generate_cfb_picks("2026-09-05")
    assert payload["ok"] is True
    assert payload["coverage"]["official_games"] == 0
    assert "No FBS games" in payload["note"]


def test_live_slate_replaces_same_event_in_history_and_duplicate_history():
    from CFBPredictionModel.cfb_core import features_for_slate
    prior = _game('g1', '2025-08-30', 70, 0)
    live = {**_game('g2', '2025-09-06', 0, 0), 'completed': False,
            'home_team': 'Boston College Eagles', 'away_team': 'Rutgers Scarlet Knights',
            'home_moneyline': -162, 'away_moneyline': 136}
    scheduled = {**live, 'home_team': 'Boston College', 'away_team': 'Rutgers',
                 'home_moneyline': None, 'away_moneyline': None,
                 'start_time': '2025-09-06T17:00:00.000Z'}
    expected = features_for_slate([prior], [live])
    actual = features_for_slate([prior, prior, scheduled], [live, live])
    assert actual == expected
    assert len(actual) == 1
    assert actual[0]['game']['home_moneyline'] == -162
    assert actual[0]['game']['home_team'] == 'Boston College Eagles'


def test_alias_refresh_replaces_old_decision_and_preserves_same_selection_grade(tmp_path):
    from scripts.merge_model_cache_payload import merge_payload
    date = '2026-09-11'
    old = {'source': 'CFB ML', 'sport': 'CFB', 'date': date, 'event_id': '401858214',
           'market': 'h2h', 'side': 'home', 'pick': 'Boston College ML',
           'matchup': 'Rutgers @ Boston College', 'decision': 'PASS', 'units': 0}
    fresh = {**old, 'pick': 'Boston College Eagles ML',
             'matchup': 'Rutgers Scarlet Knights @ Boston College Eagles',
             'decision': 'BET', 'units': 0.5}
    current = {'date': date, 'models': {'cfb': {'ok': True, 'picks': [old]}}}
    (tmp_path / f'{date}.json').write_text(json.dumps(current))
    generated = {'date': date, 'models': {'cfb': {'ok': True, 'picks': [fresh]}}}
    result = merge_payload(generated, tmp_path)
    assert result['models']['cfb']['picks'] == [fresh]
    old['result'] = 'win'
    (tmp_path / f'{date}.json').write_text(json.dumps(current))
    result = merge_payload(generated, tmp_path)
    assert len(result['models']['cfb']['picks']) == 1
    assert result['models']['cfb']['picks'][0]['result'] == 'win'


def test_publication_rejects_alias_duplicate_but_keeps_distinct_markets(tmp_path):
    from scripts.site_upcheck import _cache_contract_messages, _team_pick_key
    date = '2026-09-11'
    base = {'source': 'CFB ML', 'sport': 'CFB', 'date': date, 'event_id': '401858214',
            'market': 'h2h', 'side': 'home', 'pick': 'Boston College ML', 'decision': 'PASS'}
    duplicate = {**base, 'pick': 'Boston College Eagles ML', 'decision': 'BET'}
    assert _team_pick_key(base, 'cfb') == _team_pick_key(duplicate, 'cfb')
    for changes in ({'event_id': 'different'}, {'source': 'Different provider'}, {'side': 'away'},
                    {'date': '2026-09-12'}, {'market': 'spread', 'line': -3.5}, {'period': 'first_half'}):
        assert _team_pick_key(base, 'cfb') != _team_pick_key({**base, **changes}, 'cfb')
    spread = {**base, 'market': 'spread', 'line': 0}
    assert _team_pick_key(spread, 'cfb') != _team_pick_key({**spread, 'line': 1}, 'cfb')
    (tmp_path / 'index.json').write_text(json.dumps({'files': [f'{date}.json']}))
    (tmp_path / f'{date}.json').write_text(json.dumps({'date': date, 'models': {
        'cfb': {'ok': True, 'picks': [base, duplicate]},
    }}))
    failures, _ = _cache_contract_messages(tmp_path, player_props=False, today=date)
    assert any('duplicate event/source/market' in failure for failure in failures)


def _tamu_asu_entry(**game_overrides):
    from CFBPredictionModel.cfb_core import FEATURE_NAMES

    game = {
        "game_id": "401900002", "event_id": "401900002",
        "home_team_id": "1", "away_team_id": "2",
        "home_team": "Texas A&M Aggies", "away_team": "Arizona State Sun Devils",
        "start_time": "2026-09-12T17:00:00Z", "neutral_site": False,
        "home_line": None, "total_line": None,
        "home_moneyline": -600, "away_moneyline": 500,
        "odds_source": "espn_scoreboard:DraftKings",
    }
    game.update(game_overrides)
    return {"features": {name: 0.0 for name in FEATURE_NAMES}, "game": game}


def test_ml_card_shows_model_favored_side_not_ev_max_longshot(monkeypatch):
    """A +500 dog the model gives ~25% must not be surfaced as the ML pick.

    Live 2026-09-12 TAMU case: model_home_win_probability≈0.753, ASU +500 EV is
    fat, but A&M is the side the model actually likes. A&M clears the LEAN
    probability floor so it ranks as the actionable side; EV is still negative
    so the published decision stays PASS.
    """
    from CFBPredictionModel import cfb_model

    monkeypatch.setattr(cfb_model, "serving_rows", lambda _date, **_kwargs: [_tamu_asu_entry()])
    monkeypatch.setattr(cfb_model, "_published_probability", lambda *_args, **_kwargs: (0.753, False))
    payload = cfb_model.generate_cfb_picks("2026-09-12")
    ml = next(pick for pick in payload["picks"] if pick["source"] == "CFB ML")
    assert ml["side"] == "home"
    assert ml["selection"] == "Texas A&M Aggies"
    assert "Arizona State" not in ml["selection"]
    assert ml["model_home_win_probability"] >= 0.55
    assert ml["decision"] == "PASS"
    assert cfb_model._board_eligible(ml) is True


def test_ml_card_still_prefers_actionable_side_by_ev():
    """When a side clears the LEAN floor, EV still drives the selection."""
    from CFBPredictionModel import cfb_model

    priced = True
    fav = cfb_model._selection_rank(cfb_model._ev(0.58, 0.0, -140), 0.58, priced=priced)
    dog = cfb_model._selection_rank(cfb_model._ev(0.42, 0.0, 160), 0.42, priced=priced)
    # Actionable favored side (>=0.52) outranks a non-actionable dog.
    assert fav > dog
    high_ev = cfb_model._selection_rank(0.12, 0.55, priced=True)
    low_ev = cfb_model._selection_rank(0.04, 0.60, priced=True)
    assert high_ev > low_ev


def test_non_actionable_sides_prefer_model_probability_not_plus_money_ev():
    """When neither side clears 0.52, show the model's favorite, not the dog EV."""
    from CFBPredictionModel import cfb_model

    fav = cfb_model._selection_rank(cfb_model._ev(0.51, 0.0, -190), 0.51, priced=True)
    dog = cfb_model._selection_rank(cfb_model._ev(0.49, 0.0, 450), 0.49, priced=True)
    assert fav[0] == dog[0] == 0
    assert fav > dog


def test_spread_flat_calibrator_falls_back_to_raw_probability():
    """Degenerate flat isotonic region must not publish a meaningless 0.5.

    Regression for early-season spread cards showing calibrated_probability=0.5.
    """
    from CFBPredictionModel import cfb_model

    class FlatCalibrator:
        def predict(self, values):
            return [0.5 for _ in values]

    out, fallback = cfb_model._published_probability(FlatCalibrator(), 0.401, 0.0)
    assert fallback is True
    assert out == pytest.approx(0.401, abs=1e-9)
    assert cfb_model._calibrated_probability_or_raw(FlatCalibrator(), 0.401, 0.0) == pytest.approx(0.401)


def test_spread_informative_calibrator_is_respected():
    """A calibrator with local slope is used as-is (no raw fallback)."""
    from CFBPredictionModel import cfb_model

    class ShiftCalibrator:
        def predict(self, values):
            return [min(0.98, max(0.02, v + 0.1)) for v in values]

    out, fallback = cfb_model._published_probability(ShiftCalibrator(), 0.401, 0.0)
    assert fallback is False
    assert out == pytest.approx(0.501, abs=1e-6)


def test_uncalibrated_complement_cannot_mint_a_bet():
    """Raw fallback on a 0.401 cover must not BET the complementary 0.599 side."""
    from CFBPredictionModel import cfb_model
    from CFBPredictionModel.cfb_core import FEATURE_NAMES

    base = {"matchup": "Arizona State Sun Devils @ Texas A&M Aggies", "odds_source": "espn"}
    features = {name: 0.0 for name in FEATURE_NAMES}
    kwargs = dict(
        source="CFB Spread",
        pick="Arizona State Sun Devils +14.5",
        market="spread",
        selection="Arizona State Sun Devils",
        odds=-112,
        raw_probability=0.599,
        probability=0.599,
        push_probability=0.0,
        market_probability=0.5,
        features=features,
        extra={},
        price_observed=True,
    )
    staked = cfb_model._row(base, **kwargs, uncalibrated=False)
    assert staked["decision"] == "BET"
    held = cfb_model._row(base, **kwargs, uncalibrated=True)
    assert held["decision"] == "PASS"
    assert held["units"] == 0
    assert held["expected_value"] == staked["expected_value"]


def test_low_prob_pass_is_hidden_from_board_but_kept_in_payload(monkeypatch):
    """PASS below the LEAN win% floor stays in the cache, not on the board."""
    from CFBPredictionModel import cfb_model

    assert cfb_model._board_eligible({"decision": "BET", "probability": 0.2}) is True
    assert cfb_model._board_eligible({"decision": "LEAN", "probability": 0.53}) is True
    assert cfb_model._board_eligible({"decision": "PASS", "probability": 0.74}) is True
    assert cfb_model._board_eligible({"decision": "PASS", "probability": 0.52}) is True
    assert cfb_model._board_eligible({"decision": "PASS", "probability": 0.247}) is False
    assert cfb_model._board_eligible({"decision": "PASS", "probability": 0.5}) is False

    monkeypatch.setattr(cfb_model, "serving_rows", lambda _date, **_kwargs: [_tamu_asu_entry()])
    monkeypatch.setattr(cfb_model, "_published_probability", lambda *_args, **_kwargs: (0.51, False))
    payload = cfb_model.generate_cfb_picks("2026-09-12")
    ml = next(pick for pick in payload["picks"] if pick["source"] == "CFB ML")
    assert ml["selection"] == "Texas A&M Aggies"
    assert ml["probability"] == pytest.approx(0.51)
    assert ml["decision"] == "PASS"
    assert cfb_model._board_eligible(ml) is False
    assert payload["picks"] == [ml]


def test_viewer_pass_board_floor_matches_lean_probability():
    from CFBPredictionModel.cfb_model import LEAN_PROBABILITY

    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    assert f"IN_HOUSE_PASS_BOARD_MIN_PROBABILITY = {LEAN_PROBABILITY}" in data
    nfl = (ROOT / "NFLPredictionModel" / "nfl_model.py").read_text(encoding="utf-8")
    assert "probability >= 0.52" in nfl
