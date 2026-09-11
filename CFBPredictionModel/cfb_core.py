"""Market-free CFB data spine and strict as-of feature builder.

Schedules come from SportsDataverse's ESPN-derived college-football releases.
Sportsbook rows are joined only after originator features have been emitted:
the spread and total are pricing labels/targets, never model inputs.
"""
from __future__ import annotations

import csv
import gzip
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.scrapers.espn_scoreboard import fetch_scoreboard_json

DATA_DIR = REPO_ROOT / "data" / "cfb"
SCHEDULE_DIR = DATA_DIR / "schedules"
BETTING_DIR = DATA_DIR / "betting"

LEGACY_SCHEDULE_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/"
    "schedules/csv/cfb_schedules_{season}.csv"
)
RELEASE_BASE = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
)
SCHEDULE_RELEASE_URL = RELEASE_BASE + "/espn_cfb_schedules/cfb_schedule_{season}.{suffix}"
BETTING_RELEASE_URL = RELEASE_BASE + "/espn_cfb_betting/betting_{season}.{suffix}"
LINE_ODDS_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/"
    "betting/csv/cfb_line_odds.csv.gz"
)
SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
)
REQUEST_TIMEOUT = 60
CURRENT_TTL_SECONDS = 3 * 60 * 60

LEAGUE_POINTS = 28.0
LEAGUE_ELO = 1500.0
EWMA_DECAY = 0.5 ** (1.0 / 5.0)
OFFSEASON_DECAY = 0.58
ELO_K = 22.0
HOME_FIELD_POINTS = 2.4

# Deliberately excludes any sportsbook field. This is the immutable serving
# contract stored in the model artifact metadata and audited by the ledger.
FEATURE_NAMES = [
    "home_offense_ewma",
    "home_defense_ewma",
    "away_offense_ewma",
    "away_defense_ewma",
    "net_efficiency_diff",
    "elo_diff",
    "schedule_strength_diff",
    "home_games_log",
    "away_games_log",
    "home_rest_days",
    "away_rest_days",
    "rest_diff",
    "neutral_site",
    "conference_game",
    "week",
    "early_season",
]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _bool(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "t", "yes"}


def _download(urls: Iterable[str]) -> bytes:
    error: Exception | None = None
    for url in urls:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # pragma: no cover - exercised by CI/network
            error = exc
    raise RuntimeError(f"CFB dataset download failed: {error}")


def _cached_csv(path: Path, urls: Iterable[str], *, refresh: bool) -> list[dict[str, Any]]:
    stamp = path.with_suffix(path.suffix + ".stamp")
    age = time.time() - stamp.stat().st_mtime if stamp.exists() else None
    stale = not path.exists() or (refresh and (age is None or age > CURRENT_TTL_SECONDS))
    if stale:
        try:
            content = _download(urls)
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            stamp.write_text(str(time.time()), encoding="utf-8")
        except Exception as exc:
            if not path.exists():
                raise
            print(f"[cfb] refresh failed for {path.name} ({exc}); using cached copy")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_schedule_season(season: int, *, refresh: bool = False) -> list[dict[str, Any]]:
    """Load one season and normalize the legacy/new release schemas."""

    path = SCHEDULE_DIR / f"{season}.csv"
    urls = (
        LEGACY_SCHEDULE_URL.format(season=season),
        SCHEDULE_RELEASE_URL.format(season=season, suffix="csv"),
        SCHEDULE_RELEASE_URL.format(season=season, suffix="csv.gz"),
    )
    rows = _cached_csv(path, urls, refresh=refresh)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        start = _text(row.get("start_date") or row.get("game_date"))
        completed = _bool(row.get("completed")) or _text(row.get("status")).upper() == "STATUS_FINAL"
        home_score = _num(row.get("home_points") if "home_points" in row else row.get("home_score"))
        away_score = _num(row.get("away_points") if "away_points" in row else row.get("away_score"))
        normalized.append(
            {
                "game_id": _text(row.get("game_id")),
                "season": int(_num(row.get("season"), season) or season),
                "week": int(_num(row.get("week"), 1) or 1),
                "season_type": _text(row.get("season_type") or "regular").lower(),
                "start_time": start,
                "date": start[:10],
                "completed": completed and home_score is not None and away_score is not None,
                "neutral_site": _bool(row.get("neutral_site")),
                "conference_game": _bool(row.get("conference_game") or row.get("conference_competition")),
                "home_team_id": _text(row.get("home_id")),
                "away_team_id": _text(row.get("away_id")),
                "home_team": _text(row.get("home_team")),
                "away_team": _text(row.get("away_team")),
                "home_division": _text(row.get("home_division")).lower(),
                "away_division": _text(row.get("away_division")).lower(),
                "home_score": home_score,
                "away_score": away_score,
            }
        )
    return normalized


def load_betting_season(season: int, *, refresh: bool = False) -> dict[str, dict[str, Any]]:
    path = BETTING_DIR / f"{season}.csv"
    urls = (
        BETTING_RELEASE_URL.format(season=season, suffix="csv"),
        BETTING_RELEASE_URL.format(season=season, suffix="csv.gz"),
    )
    rows = _cached_csv(path, urls, refresh=refresh)
    book: dict[str, dict[str, Any]] = {}
    for row in rows:
        game_id = _text(row.get("game_id"))
        home_line = _num(row.get("home_team_spread"))
        total_line = _num(row.get("over_under"))
        if game_id and home_line is not None and total_line is not None:
            book[game_id] = {
                "home_line": home_line,
                "total_line": total_line,
                "odds_source": _text(row.get("odds_source")) or "sportsdataverse_betting",
            }
    return book


def load_line_odds(first_season: int, last_season: int) -> dict[str, dict[str, Any]]:
    """Median multi-book spread/total history for seasons with sparse releases."""

    path = BETTING_DIR / "cfb_line_odds.csv"
    if not path.exists():
        content = _download((LINE_ODDS_URL,))
        if content.startswith(b"\x1f\x8b"):
            content = gzip.decompress(content)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    aggregate: dict[str, dict[str, list[float]]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            season = int(_num(row.get("season"), 0) or 0)
            if season < first_season or season > last_season:
                continue
            line = _num(row.get("lines"))
            game_id = _text(row.get("game_id"))
            if line is None or not game_id:
                continue
            market = _text(row.get("market_type")).lower()
            bucket = aggregate.setdefault(game_id, {"spread": [], "total": []})
            if market == "total" and _text(row.get("abbr")).lower() == "over":
                bucket["total"].append(line)
            elif market == "spread":
                description = _text(row.get("game_desc"))
                home_name = description.rsplit("@", 1)[-1] if "@" in description else ""
                selection = "".join(char for char in _text(row.get("abbr")).lower() if char.isalnum())
                home = "".join(char for char in home_name.lower() if char.isalnum())
                if selection and home and (selection == home or selection in home or home in selection):
                    bucket["spread"].append(line)

    return {
        game_id: {
            "home_line": float(statistics.median(values["spread"])),
            "total_line": float(statistics.median(values["total"])),
            "odds_source": "cfbfastR_multi_book_median",
        }
        for game_id, values in aggregate.items()
        if values["spread"] and values["total"]
    }


def load_training_rows(first_season: int, last_season: int) -> list[dict[str, Any]]:
    historical = load_line_odds(first_season, last_season)
    rows: list[dict[str, Any]] = []
    for season in range(first_season, last_season + 1):
        schedule = load_schedule_season(season)
        season_game_ids = {game["game_id"] for game in schedule}
        # The rectangular release is the preferred resolved line. The
        # multi-book history fills older seasons where that release is sparse.
        betting = {
            game_id: market
            for game_id, market in historical.items()
            if game_id in season_game_ids
        }
        betting.update(load_betting_season(season))
        for game in schedule:
            market = betting.get(game["game_id"])
            if market:
                rows.append({**game, **market})
    rows.sort(key=lambda row: (row["start_time"], row["game_id"]))
    return rows


class TeamState:
    __slots__ = ("offense", "defense", "elo", "games", "season", "last_date", "opponent_elo")

    def __init__(self) -> None:
        self.offense = LEAGUE_POINTS
        self.defense = LEAGUE_POINTS
        self.elo = LEAGUE_ELO
        self.games = 0
        self.season = 0
        self.last_date: datetime | None = None
        self.opponent_elo = LEAGUE_ELO

    def roll_season(self, season: int) -> None:
        if self.season and season != self.season:
            self.offense = LEAGUE_POINTS + (self.offense - LEAGUE_POINTS) * OFFSEASON_DECAY
            self.defense = LEAGUE_POINTS + (self.defense - LEAGUE_POINTS) * OFFSEASON_DECAY
            self.elo = LEAGUE_ELO + (self.elo - LEAGUE_ELO) * OFFSEASON_DECAY
            self.opponent_elo = LEAGUE_ELO + (self.opponent_elo - LEAGUE_ELO) * OFFSEASON_DECAY
            self.games = 0
            self.last_date = None
        self.season = season


def _parse_time(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rest_days(state: TeamState, start: datetime | None) -> float:
    if state.last_date is None or start is None:
        return 14.0
    return min(21.0, max(3.0, float((start.date() - state.last_date.date()).days)))


def _feature_row(game: Mapping[str, Any], home: TeamState, away: TeamState) -> dict[str, float]:
    start = _parse_time(game.get("start_time"))
    neutral = 1.0 if game.get("neutral_site") is True else 0.0
    home_rest = _rest_days(home, start)
    away_rest = _rest_days(away, start)
    home_net = home.offense - home.defense
    away_net = away.offense - away.defense
    home_field_elo = 0.0 if neutral else 55.0
    return {
        "home_offense_ewma": home.offense,
        "home_defense_ewma": home.defense,
        "away_offense_ewma": away.offense,
        "away_defense_ewma": away.defense,
        "net_efficiency_diff": home_net - away_net,
        "elo_diff": home.elo - away.elo + home_field_elo,
        "schedule_strength_diff": home.opponent_elo - away.opponent_elo,
        "home_games_log": math.log1p(home.games),
        "away_games_log": math.log1p(away.games),
        "home_rest_days": home_rest,
        "away_rest_days": away_rest,
        "rest_diff": home_rest - away_rest,
        "neutral_site": neutral,
        "conference_game": 1.0 if game.get("conference_game") is True else 0.0,
        "week": float(_num(game.get("week"), 1.0) or 1.0),
        "early_season": 1.0 if int(_num(game.get("week"), 1) or 1) <= 4 else 0.0,
    }


def _update_states(game: Mapping[str, Any], home: TeamState, away: TeamState) -> None:
    home_score = _num(game.get("home_score"))
    away_score = _num(game.get("away_score"))
    if home_score is None or away_score is None:
        return
    neutral = game.get("neutral_site") is True
    expected_home = 1.0 / (1.0 + 10.0 ** (-((home.elo - away.elo) + (0.0 if neutral else 55.0)) / 400.0))
    home_result = 1.0 if home_score > away_score else 0.0 if home_score < away_score else 0.5
    margin_multiplier = math.log(abs(home_score - away_score) + 1.0) * 1.35
    delta = ELO_K * margin_multiplier * (home_result - expected_home)
    old_home_elo, old_away_elo = home.elo, away.elo
    home.elo += delta
    away.elo -= delta
    home.opponent_elo = home.opponent_elo * EWMA_DECAY + old_away_elo * (1.0 - EWMA_DECAY)
    away.opponent_elo = away.opponent_elo * EWMA_DECAY + old_home_elo * (1.0 - EWMA_DECAY)
    home.offense = home.offense * EWMA_DECAY + home_score * (1.0 - EWMA_DECAY)
    home.defense = home.defense * EWMA_DECAY + away_score * (1.0 - EWMA_DECAY)
    away.offense = away.offense * EWMA_DECAY + away_score * (1.0 - EWMA_DECAY)
    away.defense = away.defense * EWMA_DECAY + home_score * (1.0 - EWMA_DECAY)
    start = _parse_time(game.get("start_time"))
    home.last_date = start or home.last_date
    away.last_date = start or away.last_date
    home.games += 1
    away.games += 1


def _is_fbs_training_game(game: Mapping[str, Any]) -> bool:
    return (
        _text(game.get("home_division")).lower() == "fbs"
        and _text(game.get("away_division")).lower() == "fbs"
    )


def build_dataset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit finished FBS-vs-FBS rows before updating state with their scores."""

    states: dict[str, TeamState] = {}
    records: list[dict[str, Any]] = []
    for game in sorted(rows, key=lambda row: (row["start_time"], row["game_id"])):
        home_id, away_id = _text(game.get("home_team_id")), _text(game.get("away_team_id"))
        if not home_id or not away_id:
            continue
        season = int(_num(game.get("season"), 0) or 0)
        home = states.setdefault(home_id, TeamState())
        away = states.setdefault(away_id, TeamState())
        home.roll_season(season)
        away.roll_season(season)
        if game.get("completed") is True and _is_fbs_training_game(game):
            home_score = _num(game.get("home_score"))
            away_score = _num(game.get("away_score"))
            home_line = _num(game.get("home_line"))
            total_line = _num(game.get("total_line"))
            if None not in (home_score, away_score, home_line, total_line):
                features = _feature_row(game, home, away)
                records.append(
                    {
                        "game_id": game["game_id"],
                        "season": season,
                        "features": features,
                        "home_margin": float(home_score - away_score),
                        "game_total": float(home_score + away_score),
                        "home_line": float(home_line),
                        "total_line": float(total_line),
                    }
                )
        if game.get("completed") is True:
            _update_states(game, home, away)
    return records


def features_for_slate(history: list[dict[str, Any]], slate: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build target-slate features from completed games strictly before kickoff."""

    target_ids = {_text(game.get("game_id")) for game in slate}
    # The season schedule already contains upcoming games. The live slate is
    # authoritative for each target event, including its current names/prices.
    # Deduplicate history too so a repeated game cannot update team state twice.
    by_event = {_text(game.get("game_id")): game for game in [*history, *slate]
                if _text(game.get("game_id"))}
    combined = list(by_event.values())
    combined.sort(key=lambda row: (_text(row.get("start_time")), _text(row.get("game_id"))))
    states: dict[str, TeamState] = {}
    output: list[dict[str, Any]] = []
    for game in combined:
        home_id, away_id = _text(game.get("home_team_id")), _text(game.get("away_team_id"))
        if not home_id or not away_id:
            continue
        season = int(_num(game.get("season"), 0) or 0)
        home = states.setdefault(home_id, TeamState())
        away = states.setdefault(away_id, TeamState())
        home.roll_season(season)
        away.roll_season(season)
        if _text(game.get("game_id")) in target_ids:
            output.append({"game": game, "features": _feature_row(game, home, away)})
            continue
        if game.get("completed") is True:
            _update_states(game, home, away)
    return output


def _team_names(competitor: Mapping[str, Any]) -> tuple[str, str, str]:
    team = competitor.get("team") if isinstance(competitor.get("team"), Mapping) else {}
    return _text(team.get("id")), _text(team.get("displayName")), _text(team.get("abbreviation"))


def _american(value: Any) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None and (number <= -100 or number >= 100) else None


def _odds_price(node: Any) -> int | None:
    if not isinstance(node, Mapping):
        return None
    for phase in ("close", "current", "open"):
        values = node.get(phase)
        if isinstance(values, Mapping):
            price = _american(values.get("odds") or values.get("american"))
            if price is not None:
                return price
    return _american(node.get("odds") or node.get("american") or node.get("moneyLine"))


def load_live_slate(date_iso: str, *, coverage: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Load pregame identities; missing prices must not erase forecasts."""

    try:
        payload = fetch_scoreboard_json(
            f"{SCOREBOARD_URL}?dates={date_iso.replace('-', '')}&groups=80&limit=1000"
        )
    except ValueError as exc:
        raise ValueError("CFB scoreboard returned an invalid events payload") from exc
    counts = coverage if coverage is not None else {}
    counts.update(official_games=len(payload["events"]), started_games=0, incomplete_games=0,
                  pregame_games=0, unpriced_games=0)
    slate: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        state = _text(((event.get("status") or {}).get("type") or {}).get("state"))
        if state != "pre":
            counts["started_games"] += 1
            continue
        competitions = event.get("competitions") or []
        if not competitions or not isinstance(competitions[0], Mapping):
            counts["incomplete_games"] += 1
            continue
        competition = competitions[0]
        if "neutralSite" not in competition:
            counts["incomplete_games"] += 1
            continue
        competitors = [row for row in competition.get("competitors") or [] if isinstance(row, Mapping)]
        home = next((row for row in competitors if _text(row.get("homeAway")) == "home"), None)
        away = next((row for row in competitors if _text(row.get("homeAway")) == "away"), None)
        if home is None or away is None:
            counts["incomplete_games"] += 1
            continue
        home_id, home_team, home_abbr = _team_names(home)
        away_id, away_team, away_abbr = _team_names(away)
        if not all((home_id, home_team, away_id, away_team, _text(event.get("id")),
                    _text(event.get("date") or competition.get("date")))):
            counts["incomplete_games"] += 1
            continue
        odds_rows = [row for row in competition.get("odds") or [] if isinstance(row, Mapping)]
        odds = odds_rows[0] if odds_rows else {}
        home_line = _num(odds.get("spread"))
        total_line = _num(odds.get("overUnder"))
        moneyline = odds.get("moneyline") if isinstance(odds.get("moneyline"), Mapping) else {}
        home_ml = _odds_price(moneyline.get("home")) or _american((odds.get("homeTeamOdds") or {}).get("moneyLine"))
        away_ml = _odds_price(moneyline.get("away")) or _american((odds.get("awayTeamOdds") or {}).get("moneyLine"))
        point_spread = odds.get("pointSpread") if isinstance(odds.get("pointSpread"), Mapping) else {}
        total = odds.get("total") if isinstance(odds.get("total"), Mapping) else {}
        counts["pregame_games"] += 1
        if None in (home_line, total_line, home_ml, away_ml):
            counts["unpriced_games"] += 1
        season = int(_num((event.get("season") or {}).get("year"), int(date_iso[:4])))
        week = int(_num(((event.get("week") or {}).get("number")), 1) or 1)
        provider = odds.get("provider") if isinstance(odds.get("provider"), Mapping) else {}
        slate.append(
            {
                "game_id": _text(event.get("id")),
                "event_id": _text(event.get("id")),
                "season": season,
                "week": week,
                "season_type": _text(((event.get("season") or {}).get("type"))) or "regular",
                "start_time": _text(event.get("date") or competition.get("date")),
                "date": date_iso,
                "completed": False,
                "neutral_site": bool(competition.get("neutralSite")),
                "conference_game": bool(competition.get("conferenceCompetition")),
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_team": home_team,
                "away_team": away_team,
                "home_abbreviation": home_abbr,
                "away_abbreviation": away_abbr,
                "home_line": home_line,
                "total_line": total_line,
                "home_moneyline": home_ml,
                "away_moneyline": away_ml,
                "home_spread_odds": _odds_price(point_spread.get("home")),
                "away_spread_odds": _odds_price(point_spread.get("away")),
                "over_odds": _odds_price(total.get("over")),
                "under_odds": _odds_price(total.get("under")),
                "odds_source": f"espn_scoreboard:{_text(provider.get('name') or provider.get('displayName')) or 'unknown'}",
            }
        )
    return slate


def serving_rows(date_iso: str, *, coverage: dict[str, int] | None = None) -> list[dict[str, Any]]:
    slate = load_live_slate(date_iso, coverage=coverage)
    if not slate:
        return []
    season = int(date_iso[:4])
    history: list[dict[str, Any]] = []
    for year in range(season - 2, season + 1):
        history.extend(load_schedule_season(year, refresh=year == season))
    known_fbs: set[str] = set()
    for game in history:
        if game.get("home_division") == "fbs":
            known_fbs.add(_text(game.get("home_team_id")))
        if game.get("away_division") == "fbs":
            known_fbs.add(_text(game.get("away_team_id")))
    supported_slate = [
        game
        for game in slate
        if game["home_team_id"] in known_fbs and game["away_team_id"] in known_fbs
    ]
    if coverage is not None:
        coverage["excluded_non_fbs_games"] = len(slate) - len(supported_slate)
        coverage["forecast_games"] = len(supported_slate)
    return features_for_slate(history, supported_slate)


def matrix(records: list[dict[str, Any]]) -> list[list[float]]:
    return [[float(record["features"][name]) for name in FEATURE_NAMES] for record in records]
