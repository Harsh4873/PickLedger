"""ESPN-backed NFL and CFB player-props projections.

Football follows the basketball/MLB market-priced consensus path: ESPN
scoreboard + posted DraftKings propBets + gamelog priors. Posted markets are
required — there is no synthetic-line fallback, so an off-day or unpriced
slate publishes an empty board instead of invented picks.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from .basketball import (
    _american_odds,
    _athlete_ref_id,
    _canonical_market_name,
    _event_market_provider,
    _injury_map,
    _is_milestone_market,
    _target_value,
    _team_record_pct,
    _team_stats,
)
from .ml import apply_ml_to_pick, market_family_for_stat
from .schema import (
    american_implied_probability,
    build_pick,
    central_calendar_date,
    normal_probability,
    normalize_name,
    safe_float,
)


FOOTBALL_STAT_DEFINITIONS = {
    "passing_yards": {"label": "Passing Yards", "components": ("passing_yards",)},
    "passing_tds": {"label": "Passing Touchdowns", "components": ("passing_tds",)},
    "passing_completions": {"label": "Passing Completions", "components": ("passing_completions",)},
    "interceptions": {"label": "Interceptions", "components": ("interceptions",)},
    "rushing_yards": {"label": "Rushing Yards", "components": ("rushing_yards",)},
    "rushing_attempts": {"label": "Rushing Attempts", "components": ("rushing_attempts",)},
    "rushing_tds": {"label": "Rushing Touchdowns", "components": ("rushing_tds",)},
    "receiving_yards": {"label": "Receiving Yards", "components": ("receiving_yards",)},
    "receptions": {"label": "Receptions", "components": ("receptions",)},
    "receiving_tds": {"label": "Receiving Touchdowns", "components": ("receiving_tds",)},
}

STAT_LABELS = {
    key: str(definition["label"])
    for key, definition in FOOTBALL_STAT_DEFINITIONS.items()
}

FOOTBALL_GAMELOG_ALIASES = {
    "passingyards": "passing_yards",
    "passyards": "passing_yards",
    "py": "passing_yards",
    "passingtouchdowns": "passing_tds",
    "passingtds": "passing_tds",
    "passingtouchdown": "passing_tds",
    "passingcompletions": "passing_completions",
    "completions": "passing_completions",
    "cmp": "passing_completions",
    "interceptions": "interceptions",
    "ints": "interceptions",
    "int": "interceptions",
    "rushingyards": "rushing_yards",
    "rushyards": "rushing_yards",
    "ry": "rushing_yards",
    "rushingattempts": "rushing_attempts",
    "rushattempts": "rushing_attempts",
    "carries": "rushing_attempts",
    "car": "rushing_attempts",
    "rushingtouchdowns": "rushing_tds",
    "rushingtds": "rushing_tds",
    "receivingyards": "receiving_yards",
    "recyards": "receiving_yards",
    "receptions": "receptions",
    "rec": "receptions",
    "receivingtouchdowns": "receiving_tds",
    "receivingtds": "receiving_tds",
    "passingattempts": "passing_attempts",
    "passattempts": "passing_attempts",
    "att": "passing_attempts",
    "targets": "targets",
    "tgts": "targets",
}

FOOTBALL_MARKET_TYPES = {
    "passingyards": ("passing_yards", "Passing Yards"),
    "playerpassingyards": ("passing_yards", "Passing Yards"),
    "playerpassyds": ("passing_yards", "Passing Yards"),
    "passyards": ("passing_yards", "Passing Yards"),
    "passingyardsmilestones": ("passing_yards", "Passing Yards"),
    "passingtouchdowns": ("passing_tds", "Passing Touchdowns"),
    "playerpassingtouchdowns": ("passing_tds", "Passing Touchdowns"),
    "playerpasstds": ("passing_tds", "Passing Touchdowns"),
    "passingtds": ("passing_tds", "Passing Touchdowns"),
    "passingtouchdownsmilestones": ("passing_tds", "Passing Touchdowns"),
    "passingcompletions": ("passing_completions", "Passing Completions"),
    "playerpassingcompletions": ("passing_completions", "Passing Completions"),
    "playerpasscompletions": ("passing_completions", "Passing Completions"),
    "completions": ("passing_completions", "Passing Completions"),
    "interceptions": ("interceptions", "Interceptions"),
    "playerinterceptions": ("interceptions", "Interceptions"),
    "playerpassinginterceptions": ("interceptions", "Interceptions"),
    "passinginterceptions": ("interceptions", "Interceptions"),
    "rushingyards": ("rushing_yards", "Rushing Yards"),
    "playerrushingyards": ("rushing_yards", "Rushing Yards"),
    "playerrushyds": ("rushing_yards", "Rushing Yards"),
    "rushyards": ("rushing_yards", "Rushing Yards"),
    "rushingyardsmilestones": ("rushing_yards", "Rushing Yards"),
    "rushingattempts": ("rushing_attempts", "Rushing Attempts"),
    "playerrushingattempts": ("rushing_attempts", "Rushing Attempts"),
    "playerrushattempts": ("rushing_attempts", "Rushing Attempts"),
    "carries": ("rushing_attempts", "Rushing Attempts"),
    "rushingtouchdowns": ("rushing_tds", "Rushing Touchdowns"),
    "playerrushingtouchdowns": ("rushing_tds", "Rushing Touchdowns"),
    "playerrushtds": ("rushing_tds", "Rushing Touchdowns"),
    "rushingtds": ("rushing_tds", "Rushing Touchdowns"),
    "receivingyards": ("receiving_yards", "Receiving Yards"),
    "playerreceivingyards": ("receiving_yards", "Receiving Yards"),
    "playerreceivingyds": ("receiving_yards", "Receiving Yards"),
    "playerrecyds": ("receiving_yards", "Receiving Yards"),
    "receivingyardsmilestones": ("receiving_yards", "Receiving Yards"),
    "receptions": ("receptions", "Receptions"),
    "playerreceptions": ("receptions", "Receptions"),
    "receptionsmilestones": ("receptions", "Receptions"),
    "receivingtouchdowns": ("receiving_tds", "Receiving Touchdowns"),
    "playerreceivingtouchdowns": ("receiving_tds", "Receiving Touchdowns"),
    "playerrectds": ("receiving_tds", "Receiving Touchdowns"),
    "receivingtds": ("receiving_tds", "Receiving Touchdowns"),
}

OUT_STATUSES = {"out", "doubtful", "injured reserve", "ir", "suspension", "pup"}
LEAGUE_SLUGS = {"NFL": "nfl", "CFB": "college-football"}
MIN_SAMPLE_GAMES = 2


def _event_teams(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((item for item in competitors if item.get("homeAway") == "home"), {})
    away = next((item for item in competitors if item.get("homeAway") == "away"), {})
    return away.get("team") or {}, home.get("team") or {}


def _position_group(position: str) -> str:
    value = str(position or "").strip().upper()
    if value in {"QB"}:
        return "QB"
    if value in {"RB", "HB", "FB"}:
        return "RB"
    if value in {"WR", "TE"}:
        return "WR"
    return value or "Unknown"


def _event_start(event: dict[str, Any]) -> str:
    return str(event.get("date") or ((event.get("competitions") or [{}])[0].get("date")) or "")


def _matches_central_date(event: dict[str, Any], date_iso: str) -> bool:
    stamped = central_calendar_date(_event_start(event))
    if stamped is None:
        return True
    return stamped.isoformat() == date_iso


def _adjacent_dates(date_iso: str) -> list[str]:
    try:
        target = date.fromisoformat(date_iso)
    except ValueError:
        return [date_iso]
    return [target.isoformat(), (target + timedelta(days=1)).isoformat()]


def _football_market_index(
    client: Any,
    league: str,
    event: dict[str, Any],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    market_method = getattr(client, "football_espn_prop_bets", None)
    provider = _event_market_provider(event)
    if not callable(market_method) or provider is None:
        return {}
    provider_id, source = provider
    try:
        payload = market_method(league, str(event.get("id") or ""), provider_id)
    except Exception:
        return {}

    grouped: dict[tuple[str, str, float, str], list[dict[str, Any]]] = defaultdict(list)
    markets: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in payload.get("items") or []:
        type_name = str((row.get("type") or {}).get("name") or "")
        market_type = FOOTBALL_MARKET_TYPES.get(_canonical_market_name(type_name))
        if not market_type:
            continue
        athlete_id = _athlete_ref_id(row)
        if not athlete_id:
            continue
        threshold, display = _target_value(row)
        odds = _american_odds((((row.get("odds") or {}).get("american") or {}).get("value")))
        if threshold <= 0 or odds is None:
            continue
        stat_key, stat_label = market_type
        if _is_milestone_market(type_name, display):
            markets[athlete_id][stat_key].append(
                {
                    "stat_key": stat_key,
                    "stat_label": stat_label,
                    "market_athlete_id": athlete_id,
                    "line": max(0.0, threshold - 0.5),
                    "threshold": threshold,
                    "display": display or f"{threshold:g}+",
                    "over_odds": odds,
                    "market_type": type_name,
                    "market_source": source,
                    "market_updated_at": str(row.get("lastUpdated") or ""),
                    "market_format": "milestone",
                }
            )
            continue
        grouped[(athlete_id, stat_key, threshold, type_name)].append(row)

    for (athlete_id, stat_key, line, type_name), sides in grouped.items():
        if len(sides) < 2:
            continue
        market_type = FOOTBALL_MARKET_TYPES.get(_canonical_market_name(type_name))
        if not market_type:
            continue
        _, stat_label = market_type
        over_odds = _american_odds((((sides[0].get("odds") or {}).get("american") or {}).get("value")))
        under_odds = _american_odds((((sides[1].get("odds") or {}).get("american") or {}).get("value")))
        if over_odds is None or under_odds is None:
            continue
        markets[athlete_id][stat_key].append(
            {
                "stat_key": stat_key,
                "stat_label": stat_label,
                "market_athlete_id": athlete_id,
                "line": line,
                "display": f"{line:g}",
                "over_odds": over_odds,
                "under_odds": under_odds,
                "market_type": type_name,
                "market_source": source,
                "market_updated_at": str(sides[0].get("lastUpdated") or ""),
                "market_format": "total",
            }
        )
    return {player_id: dict(by_stat) for player_id, by_stat in markets.items()}


def _best_football_market(
    markets: list[dict[str, Any]],
    projection: float,
    sigma: float,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_key: tuple[float, float, float, str] | None = None
    for market in markets:
        line = safe_float(market.get("line"))
        over_odds = _american_odds(market.get("over_odds") or market.get("odds"))
        if line < 0 or over_odds is None:
            continue
        over_probability = normal_probability(projection, line, sigma, "Over")
        choices = [("Over", over_probability, over_odds)]
        under_odds = _american_odds(market.get("under_odds"))
        if under_odds is not None:
            choices.append(("Under", 1.0 - over_probability, under_odds))
        for selection, probability, odds in choices:
            implied = american_implied_probability(odds)
            if implied is None:
                continue
            key = (
                probability - implied,
                probability,
                -abs(projection - line),
                selection,
            )
            if best_key is None or key > best_key:
                best_key = key
                best = {
                    **market,
                    "selection": selection,
                    "probability": probability,
                    "odds": odds,
                    "market_implied_probability": implied,
                }
    return best


def _split_combo(value: Any) -> tuple[float | None, float | None]:
    text = str(value or "").strip()
    if not text or "-" not in text:
        number = safe_float(text, float("nan"))
        return (number, None) if math.isfinite(number) else (None, None)
    left, right = text.split("-", 1)
    first = safe_float(left, float("nan"))
    second = safe_float(right, float("nan"))
    return (
        first if math.isfinite(first) else None,
        second if math.isfinite(second) else None,
    )


def _parse_gamelog(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_names = [str(value) for value in payload.get("names") or []]
    names = [FOOTBALL_GAMELOG_ALIASES.get(_canonical_market_name(value), str(value)) for value in raw_names]
    rows: list[dict[str, float]] = []
    for season_type in payload.get("seasonTypes") or []:
        label = str(season_type.get("displayName") or "").lower()
        if "preseason" in label or "spring" in label:
            continue
        for category in season_type.get("categories") or []:
            if category.get("type") != "event":
                continue
            for event in category.get("events") or []:
                values = event.get("stats") or []
                if len(values) < len(names):
                    continue
                row: dict[str, float] = {}
                for index, name in enumerate(names):
                    raw_value = values[index]
                    canonical = FOOTBALL_GAMELOG_ALIASES.get(_canonical_market_name(name), name)
                    if canonical in {"passing_completions_attempts", "cmpatt"} or (
                        "-" in str(raw_value) and canonical in {"passing_completions", "att"}
                    ):
                        made, attempted = _split_combo(raw_value)
                        if made is not None:
                            row["passing_completions"] = made
                        if attempted is not None:
                            row["passing_attempts"] = attempted
                        continue
                    number = safe_float(raw_value, float("nan"))
                    if math.isfinite(number):
                        row[canonical] = number
                rows.append(row)
    if not rows:
        return None
    available_stats = [
        stat_key
        for stat_key in FOOTBALL_STAT_DEFINITIONS
        if any(stat_key in row for row in rows)
    ]
    if not available_stats:
        return None
    averages = {
        stat: statistics.fmean(row[stat] for row in rows if stat in row)
        for stat in (*available_stats, "passing_attempts", "targets")
        if any(stat in row for row in rows)
    }
    recent_source = rows[:5]
    recent = {
        stat: statistics.fmean(row[stat] for row in recent_source if stat in row)
        for stat in averages
        if any(stat in row for row in recent_source)
    }
    deviations = {
        stat: statistics.pstdev([row[stat] for row in rows if stat in row])
        if sum(1 for row in rows if stat in row) > 1
        else max(1.0, averages.get(stat, 1.0) * 0.35)
        for stat in available_stats
    }
    return {
        "games": len(rows),
        "average": averages,
        "recent": recent,
        "deviation": deviations,
        "available_stats": available_stats,
    }


def _opponent_context(stats: dict[str, float], stat_key: str) -> tuple[float, list[str]]:
    points_allowed = stats.get("avgPointsAllowed") or stats.get("avgPoints") or 0.0
    pass_allowed = (
        stats.get("avgPassingYardsAllowed")
        or stats.get("passingYardsAllowed")
        or stats.get("avgPassingYards")
        or 0.0
    )
    rush_allowed = (
        stats.get("avgRushingYardsAllowed")
        or stats.get("rushingYardsAllowed")
        or stats.get("avgRushingYards")
        or 0.0
    )
    factor = 1.0
    notes: list[str] = []
    if stat_key in {"passing_yards", "passing_tds", "passing_completions", "receiving_yards", "receptions", "receiving_tds"}:
        if pass_allowed:
            factor *= max(0.94, min(1.06, pass_allowed / 220.0))
            notes.append(f"Opponent pass-yards allowed proxy {pass_allowed:.1f}")
        elif points_allowed:
            factor *= max(0.96, min(1.04, points_allowed / 23.0))
            notes.append(f"Opponent scoring proxy {points_allowed:.1f} PPG")
    elif stat_key in {"rushing_yards", "rushing_attempts", "rushing_tds"}:
        if rush_allowed:
            factor *= max(0.94, min(1.06, rush_allowed / 120.0))
            notes.append(f"Opponent rush-yards allowed proxy {rush_allowed:.1f}")
        elif points_allowed:
            factor *= max(0.96, min(1.04, points_allowed / 23.0))
            notes.append(f"Opponent scoring proxy {points_allowed:.1f} PPG")
    if not notes:
        notes.append("Opponent defensive context unavailable")
    return factor, notes


def _player_profiles(
    client: Any,
    league: str,
    season: int,
    roster: dict[str, Any],
    wanted_ids: set[str],
    max_workers: int,
) -> list[dict[str, Any]]:
    athletes = [
        athlete
        for athlete in roster.get("athletes") or []
        if str(athlete.get("id") or "") in wanted_ids and athlete.get("displayName")
    ]
    if not athletes:
        return []
    profiles: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(athletes) or 1))) as executor:
        futures = {
            executor.submit(client.football_player_gamelog, league, str(athlete["id"]), season): athlete
            for athlete in athletes
        }
        for future in as_completed(futures):
            athlete = futures[future]
            try:
                parsed = _parse_gamelog(future.result())
            except Exception:
                parsed = None
            if parsed:
                profiles.append(
                    {
                        "id": str(athlete["id"]),
                        "name": str(athlete["displayName"]),
                        "position": str((athlete.get("position") or {}).get("abbreviation") or ""),
                        **parsed,
                    }
                )
    return profiles


def _game_props(
    *,
    client: Any,
    league: str,
    sport: str,
    season: int,
    date_iso: str,
    event: dict[str, Any],
    injuries: dict[str, dict[str, str]],
    max_workers: int,
) -> list[dict[str, Any]]:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    away_competitor = next((item for item in competitors if item.get("homeAway") == "away"), {})
    home_competitor = next((item for item in competitors if item.get("homeAway") == "home"), {})
    away = away_competitor.get("team") or {}
    home = home_competitor.get("team") or {}
    if not away.get("id") or not home.get("id"):
        return []
    market_index = _football_market_index(client, league, event)
    if not market_index:
        return []
    wanted_ids = set(market_index)

    team_payloads: dict[str, dict[str, Any]] = {}
    for side, team in (("away", away), ("home", home)):
        try:
            roster = client.football_roster(league, str(team["id"]))
        except Exception:
            roster = {}
        try:
            stats = _team_stats(client.football_team_stats(league, str(team["id"])))
        except Exception:
            stats = {}
        team_payloads[side] = {
            "team": team,
            "roster": roster,
            "stats": stats,
            "players": _player_profiles(client, league, season, roster, wanted_ids, max_workers),
        }

    candidates: list[dict[str, Any]] = []
    for side, opponent_side in (("away", "home"), ("home", "away")):
        team_data = team_payloads[side]
        opponent_data = team_payloads[opponent_side]
        team_competitor = away_competitor if side == "away" else home_competitor
        opponent_competitor = home_competitor if side == "away" else away_competitor
        team_record_pct = _team_record_pct(team_competitor)
        opponent_record_pct = _team_record_pct(opponent_competitor)
        for player in team_data["players"]:
            injury = injuries.get(normalize_name(player["name"]), {})
            status = str(injury.get("status") or "").lower()
            if status in OUT_STATUSES:
                continue
            if int(player.get("games") or 0) < MIN_SAMPLE_GAMES:
                continue
            available_stats = set(player.get("available_stats") or [])
            player_markets = market_index.get(player["id"]) or {}
            for stat_key, stat_label in STAT_LABELS.items():
                if stat_key not in available_stats or stat_key not in player_markets:
                    continue
                season_avg = safe_float((player.get("average") or {}).get(stat_key))
                recent_avg = safe_float((player.get("recent") or {}).get(stat_key), season_avg)
                if season_avg <= 0 and recent_avg <= 0:
                    continue
                projection = (season_avg * 0.58) + (recent_avg * 0.42)
                opponent_factor, opponent_factors = _opponent_context(opponent_data["stats"], stat_key)
                factors = [
                    f"Season {stat_label.lower()} average {season_avg:.1f}",
                    f"Last-five {stat_label.lower()} average {recent_avg:.1f}",
                    *opponent_factors,
                ]
                if side == "home":
                    projection *= 1.012
                    factors.append("Home-field role adjustment +1.2%")
                else:
                    factors.append("Road context applied")
                projection *= opponent_factor
                if injury:
                    projection *= 0.94
                    factors.append(f"Player injury status {injury.get('status')}: -6% availability adjustment")
                if team_record_pct is not None and opponent_record_pct is not None:
                    record_delta = team_record_pct - opponent_record_pct
                    projection *= max(0.97, min(1.03, 1.0 + (record_delta * 0.06)))
                    factors.append(f"Team record matchup delta {record_delta:+.1%}")
                sigma = max(
                    safe_float((player.get("deviation") or {}).get(stat_key), 1.0),
                    math.sqrt(max(1.0, projection)) * 0.55,
                )
                market = _best_football_market(player_markets.get(stat_key, []), projection, sigma)
                if not market:
                    continue
                line = safe_float(market.get("line"))
                selection = str(market.get("selection") or "Over")
                probability = safe_float(market.get("probability"))
                odds = _american_odds(market.get("odds"))
                if odds is None:
                    continue
                factors = [
                    f"Posted {market['display']} {stat_label.lower()} at {int(odds):+d}",
                    *factors,
                ]
                reason = (
                    f"{player['name']} projects for {projection:.2f} {stat_label.lower()} versus "
                    f"a posted {market['display']} market after recent form, opponent, "
                    f"and {'home' if side == 'home' else 'road'} context."
                )
                pick = build_pick(
                    sport=sport,
                    date_iso=date_iso,
                    game_id=str(event.get("id") or ""),
                    away_team=str(away.get("displayName") or away.get("name") or ""),
                    home_team=str(home.get("displayName") or home.get("name") or ""),
                    start_time=_event_start(event),
                    player_id=player["id"],
                    player_name=player["name"],
                    team=str(team_data["team"].get("displayName") or team_data["team"].get("name") or ""),
                    opponent=str(opponent_data["team"].get("displayName") or opponent_data["team"].get("name") or ""),
                    stat_key=stat_key,
                    stat_label=stat_label,
                    selection=selection,
                    line=line,
                    projection=projection,
                    probability=probability,
                    odds=odds,
                    reason=reason,
                    key_factors=factors,
                    extra={
                        "game_id": str(event.get("id") or ""),
                        "player_id": player["id"],
                        "team_id": str(team_data["team"].get("id") or ""),
                        "opponent_id": str(opponent_data["team"].get("id") or ""),
                        "player_position": str(player.get("position") or ""),
                        "position_group": _position_group(str(player.get("position") or "")),
                        "sample_games": player["games"],
                        "injury_status": str(injury.get("status") or "Healthy"),
                        "pricing_type": "market",
                        "line_source": "posted_market",
                        "odds_source": "posted_market",
                        "market_priced": True,
                        "actionability": "market_priced",
                        "market_source": market.get("market_source"),
                        "market_athlete_id": market.get("market_athlete_id"),
                        "market_over_odds": market.get("over_odds"),
                        "market_under_odds": market.get("under_odds"),
                        "market_type": market.get("market_type"),
                        "market_format": market.get("market_format"),
                        "market_updated_at": market.get("market_updated_at"),
                        "market_threshold": market.get("display"),
                    },
                )
                apply_ml_to_pick(
                    pick,
                    baseline_probability=probability,
                    baseline_projection=projection,
                    market_family=market_family_for_stat(stat_key),
                    apply_precision=False,
                )
                candidates.append(pick)
    return candidates


def _football_schedule(
    client: Any,
    league: str,
    sport: str,
    date_iso: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], int, list[str]]:
    events_by_id: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    season = int(date_iso[:4])
    scoreboard_method = getattr(client, "football_scoreboard", None)
    if not callable(scoreboard_method):
        return [], {}, season, [f"{sport} scoreboard client is unavailable"]
    for lookup_date in _adjacent_dates(date_iso):
        try:
            scoreboard = scoreboard_method(league, lookup_date)
        except Exception as exc:
            errors.append(f"{sport} {lookup_date} scoreboard: {exc}")
            continue
        season = int(((scoreboard.get("season") or {}).get("year")) or season)
        for event in scoreboard.get("events") or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or "")
            if event_id and _matches_central_date(event, date_iso):
                events_by_id[event_id] = event
    events = list(events_by_id.values())
    if not events:
        return [], {}, season, errors
    try:
        injuries = _injury_map(client.football_injuries(league))
    except Exception:
        injuries = {}
    return events, injuries, season, errors


def _soft_empty_bucket(
    sport: str,
    date_iso: str,
    *,
    games: int = 0,
    picks: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "ok": True,
        "sport": sport,
        "date": date_iso,
        "games": games,
        "picks": picks or [],
        "errors": list(errors or []),
        "note": note or f"No {sport} games scheduled; empty slate is healthy.",
        "method": "ESPN football schedule, posted prop markets, rosters, gamelogs, and injuries",
    }


def generate_football_candidate_model(
    client: Any,
    league: str,
    sport: str,
    date_iso: str,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Generate the market-priced NFL/CFB candidate pool. Failures stay empty-ok."""
    sport = str(sport or "").upper()
    league = str(league or LEAGUE_SLUGS.get(sport) or "").strip()
    try:
        events, injuries, season, schedule_errors = _football_schedule(client, league, sport, date_iso)
    except Exception as exc:
        return _soft_empty_bucket(
            sport,
            date_iso,
            errors=[str(exc)],
            note=f"{sport} schedule unavailable; empty slate so other sports can publish.",
        )
    if not events:
        note = (
            f"{sport} schedule unavailable; empty slate so other sports can publish."
            if schedule_errors
            else f"No {sport} games scheduled; empty slate is healthy."
        )
        return _soft_empty_bucket(sport, date_iso, errors=schedule_errors, note=note)

    picks: list[dict[str, Any]] = []
    errors: list[str] = list(schedule_errors)
    for event in events:
        try:
            picks.extend(
                _game_props(
                    client=client,
                    league=league,
                    sport=sport,
                    season=season,
                    date_iso=date_iso,
                    event=event,
                    injuries=injuries,
                    max_workers=max_workers,
                )
            )
        except Exception as exc:
            errors.append(f"{event.get('id')}: {exc}")
    return {
        "ok": True,
        "sport": sport,
        "date": date_iso,
        "games": len(events),
        "picks": picks,
        "errors": errors,
        "method": "ESPN football candidate pool with posted markets, gamelogs, opponent, and injury context",
        "note": "" if picks else f"No {sport} posted player-prop market cleared the in-house input floor.",
    }
