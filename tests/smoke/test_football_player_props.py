from __future__ import annotations

from pathlib import Path

from player_props.football import generate_football_candidate_model
from player_props.generator import generate_payload
from player_props.schema import central_calendar_date
from scripts.build_player_prop_market_history import SPORT_CONFIG as MARKET_SPORTS
from scripts.build_player_prop_outcome_history import SPORT_CONFIG as OUTCOME_SPORTS
from scripts.merge_player_props_cache_payload import (
    PUBLIC_PLAYER_PROP_MODEL_KEYS,
    SOFT_PLAYER_PROP_MODEL_KEYS,
    _sport_from_model_key,
)
from scripts.refresh_player_props import _publication_contract_errors
from scripts.site_upcheck import HARD_PLAYER_PROP_KEYS, SOFT_PLAYER_PROP_KEYS


DATE = "2026-09-12"
STAMP = "2026-09-12T12:00:00Z"


class EmptyFootballClient:
    def football_scoreboard(self, league, date_iso):
        return {"events": [], "season": {"year": 2026}}


class BoomFootballClient:
    def football_scoreboard(self, league, date_iso):
        raise RuntimeError("espn unavailable")


class PartialMlbClient(EmptyFootballClient):
    def basketball_scoreboard(self, league, date_iso):
        return {"events": [], "season": {"year": 2026}}

    def mlb_schedule(self, date_iso):
        return {"dates": []}


class CentralDateClient:
    """ET next-day scoreboard rows still stamp America/Chicago."""

    def football_scoreboard(self, league, date_iso):
        return {
            "season": {"year": 2026},
            "events": [
                {
                    "id": "late-sat",
                    "date": "2026-09-13T04:20:00Z",  # 11:20pm Saturday CT
                    "competitions": [
                        {
                            "date": "2026-09-13T04:20:00Z",
                            "competitors": [
                                {"homeAway": "away", "team": {"id": "1", "displayName": "Away"}},
                                {"homeAway": "home", "team": {"id": "2", "displayName": "Home"}},
                            ],
                            "odds": [{"provider": {"id": "100", "name": "DraftKings"}}],
                        }
                    ],
                },
                {
                    "id": "wrong-day",
                    "date": "2026-09-13T18:00:00Z",  # 1pm CT Sunday
                    "competitions": [
                        {
                            "date": "2026-09-13T18:00:00Z",
                            "competitors": [
                                {"homeAway": "away", "team": {"id": "3", "displayName": "Other Away"}},
                                {"homeAway": "home", "team": {"id": "4", "displayName": "Other Home"}},
                            ],
                            "odds": [{"provider": {"id": "100", "name": "DraftKings"}}],
                        }
                    ],
                },
            ],
        }

    def football_injuries(self, league):
        return {"injuries": []}

    def football_espn_prop_bets(self, league, event_id, provider_id="100"):
        return {"items": []}


class ScheduledUnpricedClient:
    def football_scoreboard(self, league, date_iso):
        return {
            "season": {"year": 2026},
            "events": [
                {
                    "id": "nfl1",
                    "date": "2026-09-12T17:00:00Z",
                    "competitions": [
                        {
                            "date": "2026-09-12T17:00:00Z",
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

    def football_injuries(self, league):
        return {"injuries": []}

    def football_espn_prop_bets(self, league, event_id, provider_id="100"):
        return {"items": []}

    def football_roster(self, league, team_id):
        return {"athletes": [{"id": "99", "displayName": "Star QB", "position": {"abbreviation": "QB"}}]}

    def football_team_stats(self, league, team_id):
        return {"results": {"stats": {"categories": []}}}

    def football_player_gamelog(self, league, player_id, season):
        return {
            "names": ["passingYards", "rushingYards"],
            "seasonTypes": [
                {
                    "displayName": "2026 Regular Season",
                    "categories": [
                        {
                            "type": "event",
                            "events": [{"eventId": "g1", "stats": ["250", "20"]}] * 4,
                        }
                    ],
                }
            ],
        }


class MarketPricedFootballClient:
    def football_scoreboard(self, league, date_iso):
        return {
            "season": {"year": 2026},
            "events": [
                {
                    "id": "nfl1",
                    "date": "2026-09-12T17:00:00Z",
                    "competitions": [
                        {
                            "date": "2026-09-12T17:00:00Z",
                            "competitors": [
                                {
                                    "homeAway": "away",
                                    "team": {"id": "10", "displayName": "Away Club"},
                                    "records": [{"summary": "1-0"}],
                                },
                                {
                                    "homeAway": "home",
                                    "team": {"id": "20", "displayName": "Home Club"},
                                    "records": [{"summary": "0-1"}],
                                },
                            ],
                            "odds": [{"provider": {"id": "100", "name": "DraftKings"}}],
                        }
                    ],
                }
            ],
        }

    def football_injuries(self, league):
        return {"injuries": []}

    def football_roster(self, league, team_id):
        if str(team_id) == "20":
            return {"athletes": [{"id": "7", "displayName": "Home QB", "position": {"abbreviation": "QB"}}]}
        return {"athletes": [{"id": "8", "displayName": "Away RB", "position": {"abbreviation": "RB"}}]}

    def football_team_stats(self, league, team_id):
        return {
            "results": {
                "stats": {
                    "categories": [
                        {
                            "stats": [
                                {"name": "avgPassingYardsAllowed", "value": 240},
                                {"name": "avgRushingYardsAllowed", "value": 110},
                                {"name": "avgPointsAllowed", "value": 22},
                            ]
                        }
                    ]
                }
            }
        }

    def football_player_gamelog(self, league, player_id, season):
        names = ["passingYards", "rushingYards", "receivingYards", "receptions"]
        values = ["265", "18", "0", "0"] if player_id == "7" else ["0", "88", "22", "3"]
        return {
            "names": names,
            "seasonTypes": [
                {
                    "displayName": "2026 Regular Season",
                    "categories": [
                        {
                            "type": "event",
                            "events": [{"eventId": f"g{index}", "stats": values} for index in range(4)],
                        }
                    ],
                }
            ],
        }

    def football_espn_prop_bets(self, league, event_id, provider_id="100"):
        def pair(athlete_id: str, type_name: str, line: float, over: int, under: int) -> list[dict]:
            ref = (
                "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/"
                f"seasons/2026/athletes/{athlete_id}?lang=en&region=us"
            )
            return [
                {
                    "athlete": {"$ref": ref},
                    "type": {"name": type_name},
                    "odds": {"american": {"value": f"{odds:+d}"}, "total": {"value": str(line)}},
                    "current": {"target": {"value": line, "displayValue": str(line)}},
                    "lastUpdated": STAMP,
                }
                for odds in (over, under)
            ]

        items = []
        items.extend(pair("7", "Passing Yards", 249.5, -110, -110))
        items.extend(pair("8", "Rushing Yards", 64.5, -115, -105))
        return {"items": items}


class FailClosedPayloadClient(MarketPricedFootballClient, PartialMlbClient):
    pass


def test_football_sports_are_registered_in_public_and_training_allowlists():
    assert {"nfl_player_props", "cfb_player_props"} <= PUBLIC_PLAYER_PROP_MODEL_KEYS
    assert SOFT_PLAYER_PROP_MODEL_KEYS == {"nfl_player_props", "cfb_player_props"}
    assert _sport_from_model_key("nfl_player_props") == "NFL"
    assert _sport_from_model_key("cfb_player_props") == "CFB"
    assert "NFL" in MARKET_SPORTS and "CFB" in MARKET_SPORTS
    assert "NFL" in OUTCOME_SPORTS and "CFB" in OUTCOME_SPORTS
    assert HARD_PLAYER_PROP_KEYS.isdisjoint(SOFT_PLAYER_PROP_KEYS)
    assert SOFT_PLAYER_PROP_KEYS == {"nfl_player_props", "cfb_player_props"}


def test_empty_football_slate_is_healthy():
    nfl = generate_football_candidate_model(EmptyFootballClient(), "nfl", "NFL", DATE)
    cfb = generate_football_candidate_model(EmptyFootballClient(), "college-football", "CFB", DATE)
    assert nfl["ok"] is True and nfl["games"] == 0 and nfl["picks"] == []
    assert cfb["ok"] is True and cfb["games"] == 0 and cfb["picks"] == []
    payload = generate_payload(DATE, client=PartialMlbClient(), generated_at=STAMP)
    assert {"nfl_player_props", "cfb_player_props"} <= set(payload["models"])
    assert payload["models"]["nfl_player_props"]["ok"] is True
    assert payload["models"]["cfb_player_props"]["ok"] is True
    assert payload["models"]["mlb_player_props"]["ok"] is True


def test_football_date_stamping_uses_america_chicago():
    assert central_calendar_date("2026-09-13T04:20:00Z").isoformat() == "2026-09-12"
    assert central_calendar_date("2026-09-13T18:00:00Z").isoformat() == "2026-09-13"
    model = generate_football_candidate_model(CentralDateClient(), "nfl", "NFL", "2026-09-12")
    assert model["ok"] is True
    assert model["games"] == 1
    assert model["picks"] == []


def test_unpriced_football_slate_is_fail_closed_empty_not_synthetic():
    model = generate_football_candidate_model(ScheduledUnpricedClient(), "nfl", "NFL", DATE)
    assert model["ok"] is True
    assert model["games"] == 1
    assert model["picks"] == []
    assert "posted" in str(model.get("note") or "").lower() or "market" in str(model.get("note") or "").lower()


def test_football_scoreboard_outage_soft_fails_and_does_not_block_mlb():
    boom = generate_football_candidate_model(BoomFootballClient(), "nfl", "NFL", DATE)
    assert boom["ok"] is True
    assert boom["games"] == 0
    assert boom["picks"] == []
    assert boom["errors"]

    payload = generate_payload(DATE, client=PartialMlbClient(), generated_at=STAMP)
    models = payload["models"]
    errors = _publication_contract_errors(models, official_mlb_games=0, target_date=DATE)
    assert errors == []
    assert models["mlb_player_props"]["ok"] is True
    assert models["nfl_player_props"]["ok"] is True


def test_market_priced_football_candidates_reuse_espn_prop_bets():
    model = generate_football_candidate_model(MarketPricedFootballClient(), "nfl", "NFL", DATE)
    assert model["ok"] is True
    assert model["games"] == 1
    assert model["picks"]
    assert all(pick["market_priced"] is True for pick in model["picks"])
    assert all(pick["sport"] == "NFL" for pick in model["picks"])
    assert all(pick["date"] == DATE for pick in model["picks"])
    assert {pick["stat_key"] for pick in model["picks"]} <= {
        "passing_yards",
        "rushing_yards",
        "receiving_yards",
        "receptions",
        "passing_tds",
        "rushing_tds",
        "receiving_tds",
        "passing_completions",
        "rushing_attempts",
        "interceptions",
    }
    assert all(pick["line_source"] == "posted_market" for pick in model["picks"])


def test_football_publication_fail_closes_without_native_consensus_artifacts():
    payload = generate_payload(DATE, client=FailClosedPayloadClient(), generated_at=STAMP)
    nfl = payload["models"]["nfl_player_props"]
    assert nfl["ok"] is True
    assert nfl["games"] == 1
    assert nfl["picks"] == []
    assert nfl.get("abstained") is True
    assert payload["models"]["mlb_player_props"]["ok"] is True


def test_publication_contract_requires_football_buckets_but_allows_empty_boards():
    models = {
        key: {"ok": True, "games": 0, "picks": []}
        for key in PUBLIC_PLAYER_PROP_MODEL_KEYS
    }
    assert _publication_contract_errors(models, official_mlb_games=0) == []

    models["nfl_player_props"] = {"ok": True, "games": 8, "picks": [], "abstained": True}
    models["cfb_player_props"] = {"ok": False, "games": 0, "picks": [], "errors": ["espn 500"]}
    assert _publication_contract_errors(models, official_mlb_games=0) == []

    models.pop("nba_player_props")
    assert _publication_contract_errors(models, official_mlb_games=0) == [
        "required bucket nba_player_props is missing"
    ]


def test_player_props_refresh_workflow_trains_and_histories_include_football():
    workflow = Path(".github/workflows/player-props-refresh.yml").read_text(encoding="utf-8")
    assert "--sports MLB,WNBA,NFL,CFB" in workflow
    assert workflow.count("--sports MLB,WNBA,NFL,CFB") == 2
