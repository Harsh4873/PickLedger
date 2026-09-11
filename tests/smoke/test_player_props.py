from __future__ import annotations

import json
from pathlib import Path

import pytest

from player_props.generator import generate_payload
from player_props.basketball import generate_basketball_model
from player_props.ml import select_top_props
from player_props.mlb import generate_mlb_model
from player_props.schema import decision_and_stake
from scripts.refresh_player_props import _publication_contract_errors, _scheduled_game_count


ROOT = Path(__file__).resolve().parents[2]
DATE = "2026-06-12"
STAMP = "2026-06-12T12:00:00Z"
PLAYER_PROP_MODEL_KEYS = {"nba_player_props", "wnba_player_props", "wnba_3pm", "mlb_player_props"}


def _public_prop_buckets() -> dict:
    return {
        key: {"ok": True, "games": 0, "picks": []}
        for key in ("nba_player_props", "mlb_player_props", "wnba_player_props")
    }


def test_refresh_publication_contract_requires_every_public_bucket():
    models = _public_prop_buckets()
    models.pop("nba_player_props")

    assert _publication_contract_errors(models, official_mlb_games=0) == [
        "required bucket nba_player_props is missing"
    ]


def test_refresh_publication_contract_uses_independent_mlb_slate():
    models = _public_prop_buckets()
    models["mlb_player_props"].update({"games": 0, "abstained": True})

    assert _publication_contract_errors(models, official_mlb_games=1) == [
        "scheduled MLB games (1) have zero published picks"
    ]


def test_refresh_scheduled_game_count_filters_next_central_date():
    bucket = {
        "games": [
            {
                "matchup": "New York Mets @ Philadelphia Phillies",
                "game_start_time": "2026-07-16T23:10:00Z",
            }
        ]
    }

    assert _scheduled_game_count(bucket, target_date="2026-07-15") == 0
    assert _scheduled_game_count(bucket, target_date="2026-07-16") == 1


@pytest.fixture(autouse=True)
def _disable_live_precision_artifact(monkeypatch):
    """Legacy generator fixtures exercise projections, not the production artifact."""
    import player_props.precision as precision
    import player_props.consensus as consensus

    monkeypatch.setenv("PICKLEDGER_DISABLE_PRECISION_MODEL", "true")
    precision._BUNDLE = False
    consensus._BUNDLE = False
    yield
    precision._BUNDLE = False
    consensus._BUNDLE = False


def _gamelog(name: str, values: list[list[str]]) -> dict:
    names = ["minutes", "points", "totalRebounds", "assists", "threePointFieldGoalsMade-threePointFieldGoalsAttempted"]
    rows = [row if len(row) >= len(names) else [*row, "2-5"] for row in values]
    return {
        "names": names,
        "seasonTypes": [
            {
                "displayName": "2026 Regular Season",
                "categories": [
                    {
                        "type": "event",
                        "events": [
                            {"eventId": f"{name}-{index}", "stats": row}
                            for index, row in enumerate(rows)
                        ],
                    }
                ],
            }
        ],
    }


def _statcast_rows(
    pitch_type: str,
    *,
    pitches: int,
    whiffs: int,
    strikeouts: int,
    hits: int = 0,
    outs: int = 0,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index in range(pitches):
        description = "swinging_strike" if index < whiffs else "foul"
        event = ""
        if index < strikeouts:
            event = "strikeout"
        elif index < strikeouts + hits:
            event = "single"
        elif index < strikeouts + hits + outs:
            event = "field_out"
        rows.append({"pitch_type": pitch_type, "description": description, "events": event})
    return rows


def _market_pair(athlete_id: int, type_name: str, line: float, over_odds: int, under_odds: int) -> list[dict]:
    def row(odds: int) -> dict:
        return {
            "athlete": {
                "$ref": (
                    "http://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/"
                    f"seasons/2026/athletes/{athlete_id}?lang=en&region=us"
                )
            },
            "type": {"name": type_name},
            "odds": {"american": {"value": f"{odds:+d}"}, "total": {"value": str(line)}},
            "current": {"target": {"value": line, "displayValue": str(line)}},
            "lastUpdated": STAMP,
        }

    return [row(over_odds), row(under_odds)]


def _basketball_milestone(athlete_id: int, type_name: str, threshold: float, odds: int) -> dict:
    return {
        "athlete": {
            "$ref": (
                "http://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/"
                f"seasons/2026/athletes/{athlete_id}?lang=en&region=us"
            )
        },
        "type": {"name": type_name},
        "odds": {"american": {"value": f"{odds:+d}"}, "total": {"value": f"{threshold:g}+"}},
        "current": {"target": {"value": threshold, "displayValue": f"{threshold:g}+"}},
        "lastUpdated": STAMP,
    }


class EmptyClient:
    def basketball_scoreboard(self, league, date_iso):
        return {"events": [], "season": {"year": 2026}}

    def mlb_schedule(self, date_iso):
        return {"dates": []}


class MockClient(EmptyClient):
    players = {
        "1": _gamelog("star", [["34", "22", "8", "5"]] * 6),
        "2": _gamelog("next", [["32", "18", "6", "7"], ["34", "24", "7", "9"]] * 3),
        "3": _gamelog("wing", [["30", "14", "5", "3"], ["31", "16", "6", "4"]] * 3),
        "4": _gamelog("center", [["29", "12", "11", "2"], ["30", "13", "12", "2"]] * 3),
        "5": _gamelog("roadstar", [["35", "21", "7", "6"], ["36", "25", "8", "7"]] * 3),
        "6": _gamelog("guard", [["31", "17", "4", "8"], ["32", "19", "5", "9"]] * 3),
        "7": _gamelog("forward", [["28", "15", "9", "3"], ["29", "17", "10", "4"]] * 3),
        "8": _gamelog("bench", [["24", "11", "4", "3"], ["25", "13", "5", "4"]] * 3),
    }

    def basketball_scoreboard(self, league, date_iso):
        if league == "nba":
            return {"events": [], "season": {"year": 2026}}
        return {
            "season": {"year": 2026},
            "events": [
                {
                    "id": "w1",
                    "date": "2026-06-12T23:30Z",
                    "competitions": [
                        {
                            "competitors": [
                                {"homeAway": "away", "team": {"id": "10", "displayName": "Away Club"}},
                                {"homeAway": "home", "team": {"id": "20", "displayName": "Home Club"}},
                            ],
                            "odds": [{"provider": {"id": "100", "name": "DraftKings"}}],
                        }
                    ],
                }
            ],
        }

    def basketball_injuries(self, league):
        return {
            "injuries": [
                {
                    "injuries": [
                        {
                            "status": "Out",
                            "shortComment": "Unavailable",
                            "athlete": {"displayName": "Star Player"},
                        }
                    ]
                }
            ]
        }

    def basketball_roster(self, league, team_id):
        names = (
            [("1", "Star Player"), ("2", "Next Guard"), ("3", "Home Wing"), ("4", "Home Center")]
            if team_id == "20"
            else [("5", "Road Star"), ("6", "Road Guard"), ("7", "Road Forward"), ("8", "Road Bench")]
        )
        return {"athletes": [{"id": player_id, "displayName": name, "position": {"abbreviation": "G"}} for player_id, name in names]}

    def basketball_team_stats(self, league, team_id):
        return {
            "results": {
                "stats": {
                    "categories": [
                        {"stats": [{"name": "avgPoints", "value": 83}, {"name": "avgBlocks", "value": 5}, {"name": "avgSteals", "value": 7}]}
                    ]
                }
            }
        }

    def basketball_player_gamelog(self, league, player_id, season):
        return self.players[player_id]

    def basketball_espn_prop_bets(self, league, event_id, provider_id="100"):
        items = []
        for athlete_id in range(2, 9):
            items.extend(
                [
                    _basketball_milestone(athlete_id, "Points Milestones", 14, -108),
                    _basketball_milestone(athlete_id, "Rebounds Milestones", 6, 112),
                    _basketball_milestone(athlete_id, "Assists Milestones", 4, -102),
                ]
            )
        return {"items": items}

    def mlb_schedule(self, date_iso):
        return {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 99,
                            "gameDate": "2026-06-12T20:00Z",
                            "venue": {"id": 19, "name": "Test Park"},
                            "teams": {
                                "away": {"team": {"id": 1, "name": "Away Nine"}, "probablePitcher": {"id": 101, "fullName": "Away Pitcher"}},
                                "home": {"team": {"id": 2, "name": "Home Nine"}, "probablePitcher": {"id": 202, "fullName": "Home Pitcher"}},
                            },
                        }
                    ]
                }
            ]
        }

    def mlb_live_feed(self, game_pk):
        return {
            "gameData": {
                "venue": {"id": 19, "name": "Test Park"},
                "weather": {"condition": "Sunny", "temp": "82", "wind": "12 mph, Out To CF"},
            },
            "liveData": {"boxscore": {"teams": {"away": {}, "home": {}}}},
        }

    def mlb_roster(self, team_id, date_iso, season):
        return {
            "roster": [
                {
                    "person": {
                        "id": team_id * 10 + index,
                        "fullName": f"Hitter {team_id}-{index}",
                        "stats": [{
                            "splits": [{
                                "stat": {
                                    "atBats": 180,
                                    "hits": 55 - index,
                                    "runs": 40 - index,
                                    "rbi": 45 - index,
                                    "baseOnBalls": 18 + index,
                                    "gamesPlayed": 55,
                                    "avg": ".300",
                                    "ops": ".820",
                                    "strikeOuts": 35 + index,
                                    "plateAppearances": 200,
                                    "doubles": 10,
                                    "triples": 1,
                                    "homeRuns": 7,
                                    "stolenBases": 5,
                                    "totalBases": 88 - index,
                                }
                            }]
                        }],
                    },
                    "position": {"abbreviation": "OF"},
                }
                for index in range(4)
            ]
        }

    def mlb_player_stats(self, player_id, group, season):
        return {
            "stats": [
                {
                    "splits": [
                        {
                            "stat": {
                                "gamesStarted": 2 if player_id == 101 else 10,
                                "gamesPitched": 21 if player_id == 101 else 10,
                                "inningsPitched": "36.1" if player_id == 101 else "60.0",
                                "strikeOuts": 41 if player_id == 101 else 70,
                                "hitsPer9Inn": "5.20" if player_id == 101 else "8.10",
                                "baseOnBalls": 18 if player_id == 101 else 22,
                                "walksPer9Inn": "4.40" if player_id == 101 else "3.30",
                                "era": "3.85" if player_id == 101 else "3.20",
                            }
                        }
                    ]
                }
            ]
        }

    def mlb_h2h(self, batter_id, pitcher_id):
        if batter_id % 2:
            return {"stats": []}
        return {
            "stats": [
                {
                    "type": {"displayName": "vsPlayerTotal"},
                    "splits": [{"stat": {"atBats": 8, "hits": 3}}],
                }
            ]
        }

    def mlb_statcast_player_pitches(self, player_id, player_type, end_date_iso, days=45):
        if player_type == "pitcher":
            return (
                _statcast_rows("FC", pitches=36, whiffs=16, strikeouts=6, outs=10)
                + _statcast_rows("ST", pitches=24, whiffs=12, strikeouts=5, outs=8)
            )
        return (
            _statcast_rows("FC", pitches=22, whiffs=10, strikeouts=5, hits=2, outs=8)
            + _statcast_rows("ST", pitches=18, whiffs=8, strikeouts=4, hits=1, outs=6)
        )

    def mlb_statcast_team_pitches(self, team_abbr, end_date_iso, days=30):
        return (
            _statcast_rows("FC", pitches=42, whiffs=20, strikeouts=12, hits=3, outs=14)
            + _statcast_rows("ST", pitches=30, whiffs=14, strikeouts=9, hits=2, outs=9)
        )

    def mlb_espn_scoreboard(self, date_iso):
        return {
            "events": [{
                "id": "espn-99",
                "competitions": [{
                    "competitors": [
                        {"homeAway": "away", "team": {"displayName": "Away Nine"}},
                        {"homeAway": "home", "team": {"displayName": "Home Nine"}},
                    ],
                    "odds": [{"provider": {"id": "100", "name": "DraftKings"}}],
                }],
            }]
        }

    def mlb_espn_summary(self, event_id):
        athletes = [
            {"id": "101", "displayName": "Away Pitcher"},
            {"id": "202", "displayName": "Home Pitcher"},
            *[
                {"id": str(team_id * 10 + index), "displayName": f"Hitter {team_id}-{index}"}
                for team_id in (1, 2)
                for index in range(4)
            ],
        ]
        return {"rosters": [{"roster": [{"athlete": athlete} for athlete in athletes]}]}

    def mlb_espn_prop_bets(self, event_id, provider_id="100"):
        items = _market_pair(202, "Total Strikeouts", 6.5, 105, -125)
        items.extend(_market_pair(202, "Total Outs Recorded", 17.5, -105, -115))
        items.extend(_market_pair(202, "Total Walks Allowed", 1.5, 115, -140))
        for team_id in (1, 2):
            for index in range(4):
                athlete_id = team_id * 10 + index
                items.extend(_market_pair(athlete_id, "Total Hits", 0.5, -400, 280))
                items.extend(_market_pair(athlete_id, "Total Hits + Runs + RBIs", 1.5, 110, -135))
                items.extend(_market_pair(athlete_id, "Total Runs", 0.5, 140, -165))
                items.extend(_market_pair(athlete_id, "Total Walks (Batter)", 0.5, 160, -190))
                items.extend(_market_pair(athlete_id, "Total Bases", 1.5, 120, -145))
        return {"items": items}


class MissingSummaryRosterClient(MockClient):
    def mlb_espn_summary(self, event_id):
        return {"rosters": []}

    def mlb_espn_athlete(self, athlete_id):
        names = {
            "101": "Away Pitcher",
            "202": "Home Pitcher",
            **{
                str(team_id * 10 + index): f"Hitter {team_id}-{index}"
                for team_id in (1, 2)
                for index in range(4)
            },
        }
        return {"athlete": {"displayName": names[str(athlete_id)]}}


class ScheduledWithoutMarketsClient(MockClient):
    def mlb_espn_prop_bets(self, event_id, provider_id="100"):
        return {"items": []}


class ScheduledWithoutBasketballMarketsClient(MockClient):
    def basketball_espn_prop_bets(self, league, event_id, provider_id="100"):
        return {"items": []}


def _active_test_policy(**overrides) -> dict:
    policy = {
        "active": True,
        "minimum_validation_samples": 4,
        "minimum_holdout_samples": 2,
        "validation": {"accuracy": 0.75, "samples": 4, "wins": 3, "losses": 1},
        "holdout": {"accuracy": 0.75, "samples": 4, "wins": 3, "losses": 1},
    }
    policy.update(overrides)
    return policy


def _consensus_metadata_for_tests() -> dict:
    return {
        "active": True,
        "target_accuracy": 0.70,
        "version": "player_props_consensus_v2.0.0",
        "training_fingerprint": "test-consensus-fingerprint",
        "sports": {
            "WNBA": {
                "active": True,
                "policies": {
                    "points": _active_test_policy(
                        selection="Over",
                        minimum_implied=0.55,
                        minimum_season_probability=0.55,
                        minimum_history_probability=0.50,
                        minimum_season_rate=0.55,
                        minimum_history_rate=0.0,
                    )
                },
            },
            "MLB": {
                "active": True,
                "policies": {
                    "hits_runs_rbis": _active_test_policy(
                        line=1.5,
                        minimum_implied=0.55,
                        minimum_season_probability=0.625,
                        minimum_history_probability=0.70,
                        minimum_season_rate=0.50,
                        minimum_history_rate=0.0,
                        require_classifier_agreement=True,
                    )
                },
            },
        },
    }


def _variant_candidate(
    sport: str,
    stat_key: str,
    *,
    line: float,
    over_odds: int = -110,
    under_odds: int = -110,
) -> dict:
    sport = sport.upper()
    return {
        "id": f"{sport.lower()}-{stat_key}",
        "sport": sport,
        "date": DATE,
        "game_id": f"{sport.lower()}-game",
        "start_time": STAMP,
        "player_id": f"{sport.lower()}-player",
        "market_athlete_id": f"{sport.lower()}-player",
        "player_name": "Test Player",
        "team": "Test Team",
        "opponent": "Opp Team",
        "opponent_id": "opp",
        "stat_key": stat_key,
        "stat_label": stat_key,
        "market_type": stat_key,
        "line": line,
        "selection": "Over",
        "odds": over_odds,
        "market_over_odds": over_odds,
        "market_under_odds": under_odds,
        "market_priced": True,
        "pricing_type": "market",
        "market_source": "DraftKings via ESPN",
        "line_source": "posted_market",
        "odds_source": "posted_market",
        "probability": 0.91,
        "ml_probability": 0.91,
        "ml_edge": 0.3862,
        "ml_expected_value": 0.73,
        "decision": "BET",
        "units": 1.0,
        "actionability": "market_priced",
        "key_factors": ["synthetic candidate"],
        "result": "pending",
    }


def test_empty_leagues_are_healthy():
    payload = generate_payload(DATE, client=EmptyClient(), generated_at=STAMP)
    assert set(payload) == {"date", "generatedAt", "updatedAt", "models"}
    assert PLAYER_PROP_MODEL_KEYS == set(payload["models"])
    assert all(model["ok"] for model in payload["models"].values())
    assert all(model["picks"] == [] for model in payload["models"].values())


def test_refresh_script_blank_date_uses_central_today(monkeypatch):
    from scripts import refresh_player_props

    monkeypatch.setattr(refresh_player_props, "_default_central_date", lambda: "2026-06-13")
    assert refresh_player_props._target_date("") == "2026-06-13"
    assert refresh_player_props._target_date("   ") == "2026-06-13"
    assert refresh_player_props._target_date("2026-06-12") == "2026-06-12"


def test_basketball_props_use_actual_markets_and_apply_next_man_up():
    first = generate_payload(DATE, client=MockClient(), generated_at=STAMP)
    second = generate_payload(DATE, client=MockClient(), generated_at="2026-06-12T13:00:00Z")
    picks = first["models"]["wnba_player_props"]["picks"]

    assert 5 <= len(picks) <= 8
    assert [pick["id"] for pick in picks] == [
        pick["id"] for pick in second["models"]["wnba_player_props"]["picks"]
    ]
    assert all(pick["scope"] == "player" and pick["result"] == "pending" for pick in picks)
    assert all(pick["player_name"] != "Star Player" for pick in picks)
    assert all(pick["selection"] == "Over" for pick in picks)
    assert all(pick["market_source"] == "DraftKings via ESPN" for pick in picks)
    assert all(pick["pricing_type"] == "market" for pick in picks)
    assert all(pick["line_source"] == "posted_market" for pick in picks)
    assert all(pick["odds_source"] == "posted_market" for pick in picks)
    assert all(pick["market_priced"] is True for pick in picks)
    assert all(pick["probability_source"] == "player_props_ml_v1" for pick in picks)
    assert all(pick["ml_probability"] == pick["probability"] for pick in picks)
    assert all(pick["ml_expected_value"] is not None for pick in picks)
    assert all(pick["ml_rank"] >= 1 for pick in picks)
    assert [pick["rank"] for pick in picks] == [pick["ml_rank"] for pick in picks]
    assert all(pick["ml_rank_epoch"].startswith("WNBA:player_props_consensus_v2.0.0:published:") for pick in picks)
    assert all(pick["ranking_epoch"] == pick["ml_rank_epoch"] for pick in picks)
    assert all(pick["model_epoch"] == pick["ml_rank_epoch"] for pick in picks)
    assert all(pick["ranking_updated_at"] == STAMP for pick in picks)
    assert all(pick["actionability"] == "market_priced" for pick in picks)
    assert all(pick["model_variant"] in {"season", "all_time", "hot_l10", "matchup_h2h"} for pick in picks)
    assert all(pick["model_key"] == "wnba_player_props" for pick in picks)
    assert len({pick["id"] for pick in picks}) == len(picks)
    assert all(pick["market_implied_probability"] is not None for pick in picks)
    assert all(
        str(pick["ml_probability_mode"]).endswith("_variant")
        for pick in picks
    )
    assert all(pick["units"] <= (1.0 if pick["ml_model_active"] else 0.5) for pick in picks)
    assert len({pick["player_id"] for pick in picks}) == len(picks)
    assert any("Next-man-up redistribution" in " ".join(pick["key_factors"]) for pick in picks)


def test_basketball_props_fall_back_to_synthetic_lines_when_markets_are_missing():
    picks = generate_basketball_model(
        ScheduledWithoutBasketballMarketsClient(),
        "wnba",
        "WNBA",
        DATE,
    )["picks"]

    assert picks
    assert all(pick["pricing_type"] == "synthetic" for pick in picks)
    assert all(pick["line_source"] == "in_house_baseline" for pick in picks)
    assert all(pick["odds_source"] == "default_assumed" for pick in picks)
    assert all(pick["market_priced"] is False for pick in picks)
    assert all(pick["actionability"] == "research_signal" for pick in picks)


def test_wnba_3pm_bucket_publishes_research_only_synthetic_rows_without_markets():
    model = generate_payload(DATE, client=ScheduledWithoutBasketballMarketsClient(), generated_at=STAMP)[
        "models"
    ]["wnba_3pm"]
    picks = model["picks"]

    assert model["ok"] is True
    assert model["model_key"] == "wnba_3pm"
    assert model["model"] == "WNBA3PM"
    assert picks
    assert all(pick["source"] == "WNBA3PM" for pick in picks)
    assert all(pick["model_key"] == "wnba_3pm" for pick in picks)
    assert all(pick["stat_key"] == "three_pointers_made" for pick in picks)
    assert all(pick["stat_label"] == "3-Point Field Goals" for pick in picks)
    assert all(pick["pricing_type"] == "synthetic" for pick in picks)
    assert all(pick["line_source"] == "in_house_3pm_model" for pick in picks)
    assert all(pick["market_priced"] is False for pick in picks)
    assert all(pick["actionability"] == "research_signal" for pick in picks)
    assert all(pick["decision"] == "PASS" for pick in picks)
    assert all(pick["ml_rank_epoch"].startswith("WNBA3PM:player_props_consensus_v2.0.0:published:") for pick in picks)
    assert all(pick["three_point_attempt_projection"] > 0 for pick in picks)
    assert all(pick["three_point_make_rate_projection"] > 0 for pick in picks)
    assert all("WNBA3PM consensus gate required" in " ".join(pick["key_factors"]) for pick in picks)


def test_mlb_props_use_actual_markets_and_reject_reliever_starter_lines():
    payload = generate_payload(DATE, client=MockClient(), generated_at=STAMP)
    model = payload["models"]["mlb_player_props"]
    picks = model["picks"]

    assert model["ok"] is True
    assert 5 <= len(picks) <= 8
    assert {"hits_runs_rbis", "batter_walks"} & {pick["stat_key"] for pick in picks}
    assert all(pick["odds"] != -110 and pick["decision"] in {"BET", "LEAN", "PASS"} for pick in picks)
    assert all(pick["market_source"] == "DraftKings via ESPN" for pick in picks)
    assert all(pick["pricing_type"] == "market" for pick in picks)
    assert all(pick["line_source"] == "posted_market" for pick in picks)
    assert all(pick["odds_source"] == "posted_market" for pick in picks)
    assert all(pick["market_priced"] is True for pick in picks)
    assert all(pick["probability_source"] == "player_props_ml_v1" for pick in picks)
    assert all(pick["ml_probability"] == pick["probability"] for pick in picks)
    assert all(pick["ml_expected_value"] is not None for pick in picks)
    assert [pick["ml_rank"] for pick in picks] == sorted(pick["ml_rank"] for pick in picks)
    assert [pick["rank"] for pick in picks] == [pick["ml_rank"] for pick in picks]
    assert all(pick["ml_rank_epoch"].startswith("MLB:player_props_consensus_v2.0.0:published:") for pick in picks)
    assert all(pick["ranking_epoch"] == pick["ml_rank_epoch"] for pick in picks)
    assert all(pick["model_epoch"] == pick["ml_rank_epoch"] for pick in picks)
    assert all(pick["ranking_updated_at"] == STAMP for pick in picks)
    assert model["ranking_epoch"] == picks[0]["ml_rank_epoch"]
    assert model["ranking_updated_at"] == STAMP
    assert all(pick["actionability"] == "market_priced" for pick in picks)
    assert all(pick["model_variant"] in {"season", "all_time", "hot_l10", "matchup_h2h"} for pick in picks)
    assert all(pick["model_key"] == "mlb_player_props" for pick in picks)
    assert len({pick["id"] for pick in picks}) == len(picks)
    assert all(pick["market_implied_probability"] is not None for pick in picks)
    assert all(
        str(pick["ml_probability_mode"]).endswith("_variant")
        for pick in picks
    )
    assert all(pick["units"] <= (1.0 if pick["ml_model_active"] else 0.5) for pick in picks)
    assert len({pick["player_id"] for pick in picks}) == len(picks)
    assert all(pick["player_name"] != "Away Pitcher" for pick in picks)
    assert any(pick.get("prop_role") == "batter_hrr" and pick["line"] == 1.5 for pick in picks)
    assert all("Venue Test Park" in " ".join(pick["key_factors"]) for pick in picks)
    assert all("Wind 12 mph, Out To CF" in " ".join(pick["key_factors"]) for pick in picks)


def test_mlb_props_resolve_athletes_when_pregame_summary_has_no_rosters():
    model = generate_payload(DATE, client=MissingSummaryRosterClient(), generated_at=STAMP)["models"]["mlb_player_props"]

    assert model["ok"] is True
    assert model["picks"]


def test_scheduled_mlb_games_with_no_usable_markets_fail_health_check():
    model = generate_mlb_model(ScheduledWithoutMarketsClient(), DATE)

    assert model["ok"] is False
    assert model["games"] == 1
    assert model["picks"] == []
    assert "No MLB player props generated" in model["error"]


def test_units_follow_quarter_kelly_and_passes_are_zero():
    bet = decision_and_stake(0.64)
    passed = decision_and_stake(0.53)
    overpriced = decision_and_stake(0.64, -250)
    missing = decision_and_stake(0.75, None)
    assert bet[0] == "BET"
    assert bet[4] == min(2.0, round(bet[3] * 100.0, 2))
    assert passed[0] == "PASS"
    assert passed[4] == 0.0
    assert overpriced[0] == "PASS"
    assert missing == ("PASS", None, 0.0, 0.0, 0.0)


def test_ml_training_uses_real_current_season_outcomes_and_validation_gate():
    for sport in ("mlb", "wnba"):
        metadata = json.loads(
            (ROOT / "player_props" / "artifacts" / f"{sport}_player_props_ml_metadata.json").read_text()
        )
        assert metadata["version"] == "player_props_ml_v1.1.0"
        assert metadata["training_season"] == 2026
        assert metadata["bootstrap_samples"] == 0
        assert metadata["ledger_samples"] > 0
        assert metadata["training_sources"] == [
            "current_season_projection_features",
            "current_season_pickledger_outcome_ledger",
        ]
        assert isinstance(metadata["active"], bool)
        assert metadata["probability_mode"] in {
            "market_anchor_validation_gate",
            "validated_model_market_anchor",
        }
        assert "force_active" not in metadata
        assert "model_brier" in metadata["validation"]


def test_four_model_consensus_clears_70_percent_on_validation_and_later_holdout(monkeypatch):
    import player_props.precision as precision
    import player_props.consensus as consensus

    metadata = json.loads(
        (ROOT / "player_props" / "artifacts" / "player_props_consensus_metadata.json").read_text()
    )
    assert metadata["active"] is True
    assert metadata["target_accuracy"] == 0.70
    assert metadata["history_years"] == {"MLB": 5, "WNBA": 3}
    assert set(metadata["history_years_by_market"]["MLB"].values()) == {5}
    assert set(metadata["history_years_by_market"]["WNBA"].values()) == {3}
    assert metadata["sports"]["MLB"]["active"] is True
    assert any(metadata["sports"][sport]["active"] is True for sport in ("MLB", "WNBA"))
    for sport in ("MLB", "WNBA"):
        sport_metadata = metadata["sports"][sport]
        if sport_metadata["active"] is not True:
            assert not sport_metadata["policies"]
            continue
        assert sport_metadata["combined_out_of_sample"]["accuracy"] >= 0.70
        for policy in sport_metadata["policies"].values():
            assert policy["validation"]["accuracy"] >= 0.70
            assert policy["holdout"]["accuracy"] >= 0.70
    assert metadata["sports"]["WNBA"]["failed_policies"]["totalRebounds"]["active"] is False
    assert (
        "three_pointers_made" in metadata["sports"]["WNBA"]["policies"]
        or "three_pointers_made" in metadata["sports"]["WNBA"]["failed_policies"]
    )
    for name in (
        "mlb_player_props_season.joblib",
        "mlb_player_props_history.joblib",
        "wnba_player_props_season.joblib",
        "wnba_player_props_history.joblib",
    ):
        assert (ROOT / "player_props" / "artifacts" / name).exists()

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    precision._BUNDLE = False
    consensus._BUNDLE = False
    assert precision.precision_model_active("MLB") is True
    assert precision.precision_model_active("WNBA") is bool(metadata["sports"]["WNBA"]["active"])
    source = (ROOT / "player_props" / "precision.py").read_text(encoding="utf-8")
    assert '"consensus_model_count": len(consensus_models)' in source
    assert '"consensus_applicable_models": consensus_applicable_models or consensus_models' in source
    assert '"consensus_record_models": consensus_applicable_models or consensus_models' in source
    assert "Four-model consensus suite active" in source


def test_inactive_precision_artifact_abstains_instead_of_using_legacy_ranker(monkeypatch):
    import player_props.precision as precision
    import player_props.consensus as consensus

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    consensus._BUNDLE = {"metadata": {"active": False}, "artifacts": {}}
    selected = select_top_props([
        {
            "id": "legacy-pick",
            "player_id": "player",
            "market_priced": True,
            "decision": "BET",
            "odds": 100,
            "ml_probability": 0.80,
            "ml_edge": 0.20,
            "ml_expected_value": 0.60,
        }
    ])
    assert selected == []


@pytest.mark.parametrize(
    ("sport", "stat_key", "line", "expected_reason"),
    [
        ("WNBA", "totalRebounds", 5.5, "totalRebounds has not cleared 70%"),
        ("WNBA", "assists", 4.5, "assists has not cleared 70%"),
        ("MLB", "hits", 0.5, "hits has not cleared 70%"),
        ("MLB", "hits_runs_rbis", 2.5, "HRR is restricted to the 1.5 line"),
        ("WNBA", "steals", 1.5, "steals has not cleared 70%"),
    ],
)
def test_variant_boards_abstain_when_consensus_policy_rejects_publication(
    monkeypatch,
    sport: str,
    stat_key: str,
    line: float,
    expected_reason: str,
):
    import player_props.consensus as consensus
    import player_props.variants as variants

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    consensus._BUNDLE = {"metadata": _consensus_metadata_for_tests(), "artifacts": {}}

    def high_probability_signal(pick, variant):
        if variant != "season":
            return None
        return "Over", 0.91, int(pick["market_over_odds"]), 0.5238, ["synthetic high-probability signal"]

    monkeypatch.setattr(variants, "_choice_for_variant", high_probability_signal)
    base_model = {
        "ok": True,
        "sport": sport,
        "date": DATE,
        "games": 1,
        "picks": [_variant_candidate(sport, stat_key, line=line)],
    }

    bucket = variants.build_variant_buckets(sport=sport, date_iso=DATE, base_model=base_model)[
        f"{sport.lower()}_player_props"
    ]

    assert bucket["picks"] == []
    assert bucket["abstained"] is True
    assert bucket["scored_count"] == 1
    assert bucket["consensus_required"] is True
    assert bucket["consensus_rejected_count"] == 1
    assert bucket["consensus_rejection_reasons"] == {expected_reason: 1}
    assert bucket["consensus_rejections"][0]["reason"] == expected_reason


def test_wnba_3pm_bucket_uses_relaxed_gate_when_consensus_policy_rejects(monkeypatch):
    import player_props.consensus as consensus
    import player_props.variants as variants

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    consensus._BUNDLE = {"metadata": _consensus_metadata_for_tests(), "artifacts": {}}
    base_model = {
        "ok": True,
        "sport": "WNBA",
        "date": DATE,
        "games": 1,
        "picks": [_variant_candidate("WNBA", "three_pointers_made", line=1.5)],
    }

    bucket = variants.build_wnba_3pm_bucket(date_iso=DATE, base_model=base_model)["wnba_3pm"]

    assert bucket["picks"]
    assert bucket["picks"][0]["decision"] == "BET"
    assert bucket["picks"][0]["model_key"] == "wnba_3pm"
    assert bucket["picks"][0]["source"] == "WNBA3PM"
    assert bucket["picks"][0]["actionability"] == "relaxed_consensus_gate"
    assert bucket["picks"][0]["ml_probability_mode"] == "wnba_3pm_relaxed_consensus_gate"
    assert bucket["picks"][0]["wnba_3pm_relaxed_consensus_floor"] == 0.55
    assert bucket["picks"][0]["wnba_3pm_consensus_gate_drop"] == 0.15
    assert bucket["picks"][0]["consensus_qualified"] is False
    assert bucket["consensus_required"] is True
    assert bucket["consensus_rejected_count"] == 1
    assert bucket["consensus_rejection_reasons"] == {"three_pointers_made has not cleared 70%": 1}


def test_wnba_3pm_bucket_keeps_weak_relaxed_gate_candidates_research_only(monkeypatch):
    import player_props.consensus as consensus
    import player_props.variants as variants

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    consensus._BUNDLE = {"metadata": _consensus_metadata_for_tests(), "artifacts": {}}
    candidate = _variant_candidate("WNBA", "three_pointers_made", line=1.5)
    candidate.update(
        {
            "probability": 0.54,
            "ml_probability": 0.54,
            "ml_edge": 0.0162,
            "ml_expected_value": 0.0309,
        }
    )
    base_model = {
        "ok": True,
        "sport": "WNBA",
        "date": DATE,
        "games": 1,
        "picks": [candidate],
    }

    bucket = variants.build_wnba_3pm_bucket(date_iso=DATE, base_model=base_model)["wnba_3pm"]

    assert bucket["picks"]
    assert bucket["picks"][0]["decision"] == "PASS"
    assert bucket["picks"][0]["actionability"] == "research_signal"
    assert "wnba_3pm_relaxed_consensus_gate" not in bucket["picks"][0]
    assert bucket["consensus_rejection_reasons"] == {"three_pointers_made has not cleared 70%": 1}


def test_variant_board_uses_consensus_probability_when_gate_qualifies(monkeypatch):
    import player_props.variants as variants

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    monkeypatch.setattr(
        variants,
        "load_consensus_bundle",
        lambda: {"metadata": {"training_fingerprint": "qualified-test-fingerprint"}, "artifacts": {}},
    )

    def high_probability_signal(pick, variant):
        if variant != "season":
            return None
        return "Over", 0.91, int(pick["market_over_odds"]), 0.5238, ["synthetic high-probability signal"]

    monkeypatch.setattr(variants, "_choice_for_variant", high_probability_signal)
    monkeypatch.setattr(
        variants,
        "evaluate_consensus_pick",
        lambda pick: {
            "required": True,
            "qualified": True,
            "reason": "qualified",
            "selection": "Under",
            "odds": 120,
            "implied_probability": 100 / 220,
            "probability": 0.62,
            "season_probability": 0.61,
            "history_probability": 0.63,
            "season_projection": 12.1,
            "history_projection": 12.4,
            "agreement": True,
            "consensus_score": 0.62,
            "validation_accuracy": 0.72,
            "holdout_accuracy": 0.71,
            "conservative_validation_accuracy": 0.71,
            "model_version": "player_props_consensus_v2.0.0",
            "training_fingerprint": "qualified-test-fingerprint",
        },
    )
    base_model = {
        "ok": True,
        "sport": "WNBA",
        "date": DATE,
        "games": 1,
        "picks": [_variant_candidate("WNBA", "points", line=14.5, over_odds=-150, under_odds=120)],
    }

    bucket = variants.build_variant_buckets(sport="WNBA", date_iso=DATE, base_model=base_model)[
        "wnba_player_props"
    ]

    assert len(bucket["picks"]) == 1
    pick = bucket["picks"][0]
    assert pick["selection"] == "Under"
    assert pick["odds"] == 120
    assert pick["probability"] == 0.62
    assert pick["ml_probability_mode"] == "four_model_consensus_gate"
    assert pick["variant_signal_probability"] == 0.91
    assert pick["consensus_qualified"] is True
    assert pick["precision_qualified"] is True
    assert pick["precision_reason"] == "qualified"
    assert pick["actionability"] == "consensus_qualified"
    assert pick["selected_side_implied_probability"] == 0.4545
    assert pick["market_no_vig_selected_probability"] is not None
    assert pick["consensus_conservative_validation_accuracy"] == 0.71
    assert pick["model_key"] == "wnba_player_props"
    assert pick["source"] == "WNBAPlayerProps"
    assert pick["supporting_variant"] == "season"


def test_consensus_ml_fallback_stays_research_only_when_gate_rejects(monkeypatch):
    import player_props.variants as variants

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    monkeypatch.setattr(
        variants,
        "load_consensus_bundle",
        lambda: {"metadata": {"training_fingerprint": "fallback-test-fingerprint"}, "artifacts": {}},
    )
    monkeypatch.setattr(
        variants,
        "evaluate_consensus_pick",
        lambda pick: {
            "required": True,
            "qualified": False,
            "reason": "failed: season_probability, history_probability, model_agreement",
        },
    )
    base_model = {
        "ok": True,
        "sport": "MLB",
        "date": DATE,
        "games": 1,
        "picks": [_variant_candidate("MLB", "strikeouts", line=5.5, over_odds=-115, under_odds=-105)],
    }
    monkeypatch.setattr(
        variants,
        "_season_choice",
        lambda pick: ("Over", 0.58, -115, 0.5349, ["season signal"]),
    )

    bucket = variants.build_variant_buckets(sport="MLB", date_iso=DATE, base_model=base_model)[
        "mlb_player_props"
    ]

    assert bucket["picks"] == []
    assert bucket["abstained"] is True
    assert bucket["consensus_required"] is True
    assert bucket["consensus_rejected_count"] >= 1


def test_consensus_rejects_miscalibrated_publication_policy(monkeypatch):
    import player_props.consensus as consensus

    monkeypatch.delenv("PICKLEDGER_DISABLE_PRECISION_MODEL", raising=False)
    metadata = _consensus_metadata_for_tests()
    metadata["sports"]["WNBA"]["policies"]["points"] = _active_test_policy(
        selection="Over",
        minimum_validation_samples=10,
        minimum_holdout_samples=10,
        validation={"accuracy": 0.95, "samples": 40, "wins": 38, "losses": 2},
        holdout={"accuracy": 0.55, "samples": 20, "wins": 11, "losses": 9},
    )
    consensus._BUNDLE = {"metadata": metadata, "artifacts": {}}

    result = consensus.evaluate_consensus_pick(_variant_candidate("WNBA", "points", line=14.5))

    assert result["required"] is True
    assert result["qualified"] is False
    assert result["reason"] == "points consensus calibration below 70%"


def test_ml_selection_caps_board_and_rejects_weak_or_extreme_props():
    def candidate(index: int, player: str, **overrides):
        pick = {
            "id": f"pick-{index}",
            "player_id": player,
            "market_priced": True,
            "decision": "BET",
            "odds": 110,
            "ml_probability": 0.58,
            "ml_edge": 0.08,
            "ml_expected_value": 0.20 - (index * 0.01),
        }
        pick.update(overrides)
        return pick

    selected = select_top_props(
        [
            candidate(0, "a"),
            candidate(1, "a"),
            candidate(2, "b"),
            candidate(3, "c"),
            candidate(4, "d"),
            candidate(5, "e"),
            candidate(6, "f"),
            candidate(7, "g"),
            candidate(8, "h", decision="LEAN", ml_expected_value=0.25),
            candidate(9, "i"),
            candidate(10, "j", odds=300),
            candidate(11, "k", ml_probability=0.51),
        ]
    )

    assert len(selected) == 8
    assert len({pick["player_id"] for pick in selected}) == 8
    assert selected[0]["id"] == "pick-8"
    assert [pick["ml_expected_value"] for pick in selected] == sorted(
        (pick["ml_expected_value"] for pick in selected),
        reverse=True,
    )
    assert all(pick["odds"] <= 250 and pick["ml_probability"] >= 0.52 for pick in selected)


def test_variant_selection_caps_each_game_instead_of_the_entire_sport():
    import player_props.variants as variants

    candidates = []
    for game_index, game_id in enumerate(("game-a", "game-b")):
        for player_index in range(10):
            candidates.append(
                {
                    "id": f"{game_id}-{player_index}_season",
                    "sport": "MLB",
                    "date": DATE,
                    "game_id": game_id,
                    "matchup": f"Away {game_index} @ Home {game_index}",
                    "player_id": f"{game_id}-player-{player_index}",
                    "player_name": f"{game_id} Player {player_index}",
                    "stat_key": "hits",
                    "selection": "Over",
                    "line": 0.5,
                    "market_priced": True,
                    "decision": "BET",
                    "odds": 100,
                    "ml_probability": 0.70,
                    "ml_edge": 0.20,
                    "ml_expected_value": 0.40 - player_index * 0.01 - game_index * 0.001,
                    "model_variant": "season",
                    "model_variant_label": "Season",
                }
            )

    variant_picks = variants._select_variant(candidates, "season")
    published = variants._rank_sport_picks({"season": variant_picks}, "MLB")

    assert len(variant_picks) == 16
    assert len(published) == 16
    for game_id in ("game-a", "game-b"):
        game_picks = [pick for pick in published if pick["game_id"] == game_id]
        assert len(game_picks) == 8
        assert {pick["player_id"] for pick in game_picks} == {
            f"{game_id}-player-{index}" for index in range(8)
        }
    assert len({pick["player_id"] for pick in published}) == len(published)
    assert [pick["ml_expected_value"] for pick in published] == sorted(
        (pick["ml_expected_value"] for pick in published),
        reverse=True,
    )


class AllStarOnlyClient(EmptyClient):
    """A slate whose only WNBA event is the All-Star Game."""

    def basketball_scoreboard(self, league, date_iso):
        if league == "nba":
            return {"events": [], "season": {"year": 2026}}
        return {
            "season": {"year": 2026, "slug": "regular-season"},
            "events": [
                {
                    "id": "allstar",
                    "date": "2026-07-25T23:30Z",
                    "name": "AT&T WNBA All-Star Game",
                    "competitions": [
                        {
                            "type": {"id": "6", "abbreviation": "ALLSTAR"},
                            "competitors": [
                                {"homeAway": "away", "team": {"id": "133383", "displayName": "TEAM SPOON"}},
                                {"homeAway": "home", "team": {"id": "133384", "displayName": "TEAM COOP"}},
                            ],
                        }
                    ],
                }
            ],
        }


def test_allstar_slate_is_not_a_rateable_props_game():
    """An All-Star exhibition must not count as a scheduled props game.

    Its squads are ad-hoc, so ESPN has no team statistics for them and the
    scorer can never produce a candidate. If it counted, the publication
    contract would demand picks that cannot exist and the deploy readiness
    gate would defer for the whole All-Star break.
    """
    from player_props.basketball import generate_basketball_model

    result = generate_basketball_model(AllStarOnlyClient(), "wnba", "WNBA", "2026-07-25")
    assert result["ok"] is True
    assert result["games"] == 0, "the All-Star Game must not be counted as a scheduled game"
    assert result["picks"] == []
    assert "empty slate is healthy" in str(result.get("note") or "")


def test_real_games_are_still_counted_alongside_an_allstar_event():
    """The exclusion must be surgical — a genuine game still counts."""
    from player_props.basketball import _basketball_schedule

    class MixedClient(AllStarOnlyClient):
        def basketball_scoreboard(self, league, date_iso):
            board = AllStarOnlyClient.basketball_scoreboard(self, league, date_iso)
            if league == "nba":
                return board
            board["events"] = list(board["events"]) + [
                {
                    "id": "real",
                    "date": "2026-07-25T23:30Z",
                    "competitions": [
                        {
                            "type": {"id": "1", "abbreviation": "STD"},
                            "competitors": [
                                {"homeAway": "away", "team": {"id": "10", "displayName": "Away Club"}},
                                {"homeAway": "home", "team": {"id": "20", "displayName": "Home Club"}},
                            ],
                        }
                    ],
                }
            ]
            return board

    _, events, _, _, errors = _basketball_schedule(MixedClient(), "wnba", "WNBA", "2026-07-25")
    assert errors == []
    assert [event["id"] for event in events] == ["real"]


def test_untyped_competitions_are_never_treated_as_exhibitions():
    """Most ESPN competitions carry no `type`; those must still be rated."""
    from player_props.basketball import _is_exhibition

    assert _is_exhibition({"competitions": [{"competitors": []}]}) is False
    assert _is_exhibition({}) is False
    assert _is_exhibition({"competitions": [{"type": {"abbreviation": "STD"}}]}) is False
    assert _is_exhibition({"competitions": [{"type": {"abbreviation": "allstar"}}]}) is True


def test_refresh_publication_contract_accepts_documented_abstention():
    models = _public_prop_buckets()
    models['mlb_player_props'].update({
        'games': 5, 'abstained': True, 'candidate_count': 1445,
        'scored_count': 3969, 'consensus_rejected_count': 3673,
        'consensus_rejection_reasons': {'hits has not cleared the gate': 603},
    })
    assert _publication_contract_errors(models, official_mlb_games=5) == []
    models['mlb_player_props']['ok'] = False
    assert _publication_contract_errors(models, official_mlb_games=5)


def test_guard_and_publication_share_documented_abstention_rule():
    from scripts.site_upcheck import _mlb_player_props_documented_abstention as documented_abstention
    from scripts.site_upcheck import _mlb_player_props_documented_abstention
    assert documented_abstention is _mlb_player_props_documented_abstention
    assert not documented_abstention({'ok': True, 'abstained': True, 'picks': []})
    assert not documented_abstention({'ok': False, 'abstained': True, 'candidate_count': 10})
