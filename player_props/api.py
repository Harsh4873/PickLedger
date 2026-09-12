"""Direct ESPN and MLB StatsAPI client used by the player-props generator."""

from __future__ import annotations

import csv
import io
import time
from datetime import date, timedelta
from typing import Any

import requests


class DirectApiClient:
    """Small retrying client with an in-memory response cache."""

    def __init__(self, timeout: float = 20.0, attempts: int = 3) -> None:
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PickLedgerPro-player-props/1.0"})
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}
        self._csv_cache: dict[tuple[str, tuple[tuple[str, str], ...]], list[dict[str, str]]] = {}

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        cache_key = (url, normalized)
        if cache_key in self._cache:
            return self._cache[cache_key]

        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected object response from {url}")
                self._cache[cache_key] = payload
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Direct API request failed for {url}: {last_error}") from last_error

    def _get_csv(self, url: str, params: dict[str, Any] | None = None) -> list[dict[str, str]]:
        normalized = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        cache_key = (url, normalized)
        if cache_key in self._csv_cache:
            return self._csv_cache[cache_key]

        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                text = response.text.lstrip("\ufeff")
                rows = [dict(row) for row in csv.DictReader(io.StringIO(text)) if isinstance(row, dict)]
                self._csv_cache[cache_key] = rows
                return rows
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Direct CSV request failed for {url}: {last_error}") from last_error

    def basketball_scoreboard(self, league: str, date_iso: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/basketball/{league}/scoreboard",
            {"dates": date_iso.replace("-", ""), "limit": 100},
        )

    def basketball_roster(self, league: str, team_id: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/basketball/{league}/teams/{team_id}/roster"
        )

    def basketball_injuries(self, league: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/basketball/{league}/injuries"
        )

    def basketball_team_stats(self, league: str, team_id: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/basketball/{league}/teams/{team_id}/statistics"
        )

    def basketball_player_gamelog(
        self,
        league: str,
        player_id: str,
        season: int,
    ) -> dict[str, Any]:
        return self._get(
            f"https://site.web.api.espn.com/apis/common/v3/sports/basketball/{league}/athletes/{player_id}/gamelog",
            {"season": season},
        )

    def basketball_espn_prop_bets(self, league: str, event_id: str, provider_id: str = "100") -> dict[str, Any]:
        return self._get(
            (
                f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/{league}/"
                f"events/{event_id}/competitions/{event_id}/odds/{provider_id}/propBets"
            ),
            {"lang": "en", "region": "us", "limit": 1000},
        )

    def football_scoreboard(self, league: str, date_iso: str) -> dict[str, Any]:
        params: dict[str, Any] = {"dates": date_iso.replace("-", ""), "limit": 1000}
        if str(league or "").strip() == "college-football":
            params["groups"] = 80
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard",
            params,
        )

    def football_roster(self, league: str, team_id: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/football/{league}/teams/{team_id}/roster"
        )

    def football_injuries(self, league: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/football/{league}/injuries"
        )

    def football_team_stats(self, league: str, team_id: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/football/{league}/teams/{team_id}/statistics"
        )

    def football_player_gamelog(
        self,
        league: str,
        player_id: str,
        season: int,
    ) -> dict[str, Any]:
        return self._get(
            f"https://site.web.api.espn.com/apis/common/v3/sports/football/{league}/athletes/{player_id}/gamelog",
            {"season": season},
        )

    def football_espn_prop_bets(self, league: str, event_id: str, provider_id: str = "100") -> dict[str, Any]:
        return self._get(
            (
                f"https://sports.core.api.espn.com/v2/sports/football/leagues/{league}/"
                f"events/{event_id}/competitions/{event_id}/odds/{provider_id}/propBets"
            ),
            {"lang": "en", "region": "us", "limit": 1000},
        )

    def football_espn_summary(self, league: str, event_id: str) -> dict[str, Any]:
        return self._get(
            f"http://site.api.espn.com/apis/site/v2/sports/football/{league}/summary",
            {"event": event_id},
        )

    def mlb_schedule(self, date_iso: str) -> dict[str, Any]:
        return self._get(
            "https://statsapi.mlb.com/api/v1/schedule",
            {"sportId": 1, "date": date_iso, "hydrate": "probablePitcher,venue"},
        )

    def mlb_espn_scoreboard(self, date_iso: str) -> dict[str, Any]:
        return self._get(
            "http://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
            {"dates": date_iso.replace("-", ""), "limit": 100},
        )

    def mlb_espn_summary(self, event_id: str) -> dict[str, Any]:
        return self._get(
            "http://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary",
            {"event": event_id},
        )

    def mlb_espn_prop_bets(self, event_id: str, provider_id: str = "100") -> dict[str, Any]:
        return self._get(
            (
                "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/"
                f"events/{event_id}/competitions/{event_id}/odds/{provider_id}/propBets"
            ),
            {"lang": "en", "region": "us", "limit": 1000},
        )

    def mlb_espn_athlete(self, athlete_id: str) -> dict[str, Any]:
        return self._get(
            f"https://site.web.api.espn.com/apis/common/v3/sports/baseball/mlb/athletes/{athlete_id}"
        )

    def mlb_live_feed(self, game_pk: int) -> dict[str, Any]:
        return self._get(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")

    def mlb_roster(self, team_id: int, date_iso: str, season: int) -> dict[str, Any]:
        return self._get(
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster",
            {
                "rosterType": "active",
                "date": date_iso,
                "hydrate": f"person(stats(group=[hitting],type=[season],season={season}))",
            },
        )

    def mlb_player_stats(self, player_id: int, group: str, season: int) -> dict[str, Any]:
        return self._get(
            f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats",
            {"stats": "season", "group": group, "season": season},
        )

    def mlb_h2h(self, batter_id: int, pitcher_id: int) -> dict[str, Any]:
        return self._get(
            f"https://statsapi.mlb.com/api/v1/people/{batter_id}/stats",
            {"stats": "vsPlayer", "group": "hitting", "opposingPlayerId": pitcher_id},
        )

    def mlb_statcast_player_pitches(
        self,
        player_id: int,
        player_type: str,
        end_date_iso: str,
        days: int = 45,
    ) -> list[dict[str, str]]:
        try:
            end_date = date.fromisoformat(str(end_date_iso))
        except ValueError:
            return []
        player_type = "pitcher" if str(player_type).lower() == "pitcher" else "batter"
        lookup_key = "pitchers_lookup[]" if player_type == "pitcher" else "batters_lookup[]"
        return self._get_csv(
            "https://baseballsavant.mlb.com/statcast_search/csv",
            {
                "all": "true",
                "type": "details",
                "player_type": player_type,
                "game_date_gt": (end_date - timedelta(days=max(7, days))).isoformat(),
                "game_date_lt": end_date.isoformat(),
                lookup_key: int(player_id),
            },
        )

    def mlb_statcast_team_pitches(
        self,
        team_abbr: str,
        end_date_iso: str,
        days: int = 30,
    ) -> list[dict[str, str]]:
        try:
            end_date = date.fromisoformat(str(end_date_iso))
        except ValueError:
            return []
        team = str(team_abbr or "").strip().upper()
        if not team:
            return []
        return self._get_csv(
            "https://baseballsavant.mlb.com/statcast_search/csv",
            {
                "all": "true",
                "type": "details",
                "player_type": "batter",
                "game_date_gt": (end_date - timedelta(days=max(7, days))).isoformat(),
                "game_date_lt": end_date.isoformat(),
                "team": team,
            },
        )
