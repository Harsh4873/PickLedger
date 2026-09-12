"""CFB pregame projections from posted markets and dated ESPN player history.

The statistical baseline is visible as PASS until native betting calibration is
validated. It does not borrow other sports' artifacts or claim consensus approval.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .football import FOOTBALL_GAMELOG_ALIASES, OUT_STATUSES, _canonical_market_name, _football_schedule
from .schema import american_implied_probability, build_pick, central_calendar_date, safe_float

MARKETS = {
    "core_bet_type_9_passing_yards": ("passing_yards", "Passing Yards"),
    "core_bet_type_12_rushing_yards": ("rushing_yards", "Rushing Yards"),
    "core_bet_type_16_receiving_yards": ("receiving_yards", "Receiving Yards"),
    "core_bet_type_15_receptions": ("receptions", "Receptions"),
}
VERSION = "cfb_history_baseline_v1"


def _name(value: Any) -> str:
    value = re.sub(r"[^a-z0-9 ]", "", str(value or "").lower())
    return " ".join(word for word in value.split() if word not in {"jr", "sr", "ii", "iii", "iv"})


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _roster(payload: dict) -> list[dict]:
    return [athlete for group in payload.get("athletes", [])
            for athlete in (group.get("items", []) if "items" in group else [group])]


def _match_game(event: dict, games: list[dict]) -> dict | None:
    """Require both teams, home/away orientation and kickoff; reject ambiguity."""
    competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
    official = {c.get("homeAway"): c.get("team", {}) for c in competitors}
    kickoff = _time(event.get("date"))
    matches = []
    for game in games:
        start = _time(game.get("start_time"))
        if not kickoff or not start or abs((start - kickoff).total_seconds()) > 900:
            continue
        teams = {str(t.get("id")): t for t in game.get("teams", [])}
        valid = True
        for side in ("home", "away"):
            team = teams.get(str(game.get(f"{side}_team_id")), {})
            expected = official.get(side, {})
            abbr = _name(team.get("abbr"))
            same_abbr = bool(abbr and abbr == _name(expected.get("abbreviation")))
            name = _name(team.get("full_name"))
            same_name = bool(name and name == _name(expected.get("displayName")))
            valid &= same_abbr or same_name
        if valid:
            matches.append(game)
    return matches[0] if len(matches) == 1 else None


def _history(payloads: list[dict], cutoff: str) -> list[dict]:
    """Deduplicate and date-sort played games; keep real zero outcomes."""
    rows = {}
    for payload in payloads:
        names = [FOOTBALL_GAMELOG_ALIASES.get(_canonical_market_name(n), n) for n in payload.get("names", [])]
        details = payload.get("events") or {}
        for season_type in payload.get("seasonTypes", []):
            if any(s in str(season_type.get("displayName", "")).lower() for s in ("spring", "preseason")):
                continue
            for category in season_type.get("categories", []):
                if category.get("type") != "event":
                    continue
                for event in category.get("events", []):
                    event_id = str(event.get("eventId") or "")
                    detail = details.get(event_id, {})
                    day = central_calendar_date(detail.get("gameDate"))
                    if not day or day.isoformat() >= cutoff or event.get("didNotPlay") or detail.get("didNotPlay"):
                        continue
                    values = event.get("stats", [])
                    if len(values) != len(names):
                        continue
                    stats = {key: safe_float(str(value).replace(",", ""), float("nan"))
                             for key, value in zip(names, values)}
                    rows[event_id] = {"id": event_id, "date": day.isoformat(), "stats": stats,
                                      "team_id": str((detail.get("team") or {}).get("id") or "")}
    return sorted(rows.values(), key=lambda row: (row["date"], row["id"]), reverse=True)


def _series(history: list[dict], stat: str) -> list[float]:
    values = []
    for row in history:
        stats = row["stats"]
        # A QB's passing prior excludes games with no passing role. Receivers'
        # zero catches and rushers' zero yards remain observations.
        if stat == "passing_yards" and stats.get("passing_attempts", 0) <= 0:
            continue
        value = stats.get(stat, float("nan"))
        if math.isfinite(value):
            values.append(value)
    return values


def _estimate(values: list[float]) -> tuple[float, float]:
    sample = values[:12]
    weights = [0.85 ** i for i in range(len(sample))]
    mean = sum(v * w for v, w in zip(sample, weights)) / sum(weights)
    variance = sum(w * (v - mean) ** 2 for v, w in zip(sample, weights)) / sum(weights)
    return mean, max(math.sqrt(variance), abs(mean) * 0.25, 1.0)


def _backtest(values: list[float]) -> dict:
    errors = [abs(_estimate(values[i + 1:])[0] - values[i]) for i in range(max(0, len(values) - 4))]
    return {"samples": len(errors), "mae": round(statistics.fmean(errors), 2) if errors else None,
            "method": "rolling origin; each prediction uses only older games"}


def _quotes(payload: dict, books: dict[str, str], game_id: str) -> list[dict]:
    quotes = []
    for market_type, (stat, label) in MARKETS.items():
        for entry in payload.get("player_props", {}).get(market_type, []):
            pid = str(entry.get("player_id") or "")
            player = payload.get("players", {}).get(pid, {})
            for book_id, lines in entry.get("lines", {}).items():
                book = books.get(str(book_id), "")
                # Aggregated/consensus prices cannot identify an executable book.
                if not book or "consensus" in book.lower() or book.lower() in {"open", "opener", "best odds"}:
                    continue
                pairs = defaultdict(dict)
                for line in lines if isinstance(lines, list) else []:
                    value = safe_float(line.get("value"), float("nan"))
                    odds = safe_float(line.get("odds"), float("nan"))
                    if (str(line.get("event_id")) != game_id or str(line.get("player_id")) != pid
                            or line.get("side") not in {"over", "under"} or line.get("period") != "event"
                            or line.get("is_live") is True or line.get("is_alt_market") is True
                            or line.get("line_status", "normal") != "normal"
                            or not math.isfinite(value) or value < 0 or not math.isfinite(odds) or abs(odds) < 100):
                        continue
                    pairs[value][line["side"]] = int(odds)
                for value, pair in pairs.items():
                    if set(pair) != {"over", "under"}:
                        continue
                    quotes.append({"player": player, "stat": stat, "label": label, "line": value,
                                   "over_odds": pair["over"], "under_odds": pair["under"],
                                   "book_id": str(book_id), "book": book})
    return quotes


def _game(client: Any, event: dict, game: dict, books: dict, date_iso: str, injuries: dict, stamp: str) -> tuple[list[dict], dict]:
    game_id = str(game["id"])
    diagnostic = {"game_id": str(event["id"]), "matchup": event.get("name"), "markets": 0,
                  "unmatched_players": [], "insufficient_history": [], "history_errors": []}
    payload = client.cfb_market_json(f"v2/games/{game_id}/props")
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    quotes = _quotes(payload, books, game_id)
    diagnostic["markets"] = len(quotes)
    if not quotes:
        diagnostic["status"] = "no_posted_markets"
        return [], diagnostic
    competitors = (event.get("competitions") or [{}])[0].get("competitors", [])
    official = {c["homeAway"]: c["team"] for c in competitors}
    teams = {str(game[f"{side}_team_id"]): (side, team) for side, team in official.items()}
    rosters = {side: _roster(client.football_roster("college-football", str(team["id"]))) for side, team in official.items()}
    player_history = {}
    picks = []
    grouped = defaultdict(list)
    for quote in quotes:
        grouped[(str(quote["player"].get("id")), quote["stat"])].append(quote)
    for (pid, stat), markets in grouped.items():
        info = markets[0]["player"]
        side_team = teams.get(str(info.get("team_id")))
        if not side_team:
            continue
        side, team = side_team
        matches = [a for a in rosters[side] if _name(a.get("displayName")) == _name(info.get("full_name"))]
        if len(matches) != 1:
            diagnostic["unmatched_players"].append(info.get("full_name"))
            continue
        athlete = matches[0]
        injury = next((v for k, v in injuries.items() if _name(k) == _name(athlete["displayName"])), {})
        if str(injury.get("status") or "").lower() in OUT_STATUSES:
            continue
        athlete_id = str(athlete["id"])
        if athlete_id not in player_history:
            payloads = []
            for season in (int(date_iso[:4]), int(date_iso[:4]) - 1):
                try:
                    payloads.append(client.football_player_gamelog("college-football", athlete_id, season))
                except Exception as exc:
                    diagnostic["history_errors"].append(f"{athlete_id}/{season}: {exc}")
            player_history[athlete_id] = _history(payloads, date_iso)
        history = player_history[athlete_id]
        values = _series(history, stat)
        if len(values) < 4:
            diagnostic["insufficient_history"].append(f"{athlete['displayName']}: {stat}")
            continue
        mean, sigma = _estimate(values)
        # Choose the most balanced main market, independently of the projection.
        quote = min(markets, key=lambda q: (abs(american_implied_probability(q["over_odds"]) - 0.5)
                    + abs(american_implied_probability(q["under_odds"]) - 0.5), q["book_id"], q["line"]))
        line = quote["line"]
        selection = "Over" if mean > line else "Under"
        # Normal baseline distribution with a continuity correction for pushes.
        boundary = math.floor(line) + 0.5 if selection == "Over" else math.ceil(line) - 0.5
        cdf = 0.5 * (1 + math.erf((boundary - mean) / (sigma * math.sqrt(2))))
        probability = 1 - cdf if selection == "Over" else cdf
        opponent = official["away" if side == "home" else "home"]
        validation = _backtest(values)
        reason = (f"Historical baseline projects {mean:.1f} {quote['label'].lower()} versus {line:g} at {quote['book']}. "
                  "PASS: betting probabilities have not passed native CFB calibration. Role changes and opponent strength are not modeled.")
        extra = {"source": "CFBPlayerProps", "model_key": "cfb_player_props", "published_model": "CFBPlayerProps", "game_id": str(event["id"]),
                 "player_id": athlete_id, "espn_athlete_id": athlete_id, "team_id": str(team["id"]),
                 "opponent_id": str(opponent["id"]), "market_athlete_id": athlete_id, "provider_player_id": pid,
                 "provider_game_id": game_id, "sample_games": min(12, len(values)), "history_games": len(values),
                 "history_cutoff": date_iso, "projection_validation": validation, "sigma": round(sigma, 2),
                 "market_source": f"{quote['book']} via Action Network", "market_source_url": f"https://api.actionnetwork.com/web/v2/games/{game_id}/props",
                 "book_id": quote["book_id"], "market_over_odds": quote["over_odds"], "market_under_odds": quote["under_odds"],
                 "market_retrieved_at": stamp, "market_format": "total", "market_priced": True,
                 "line_source": "posted_market", "odds_source": "posted_market", "pricing_type": "market",
                 "baseline_only": True, "model_version": VERSION, "ml_model_active": False,
                 "calibration_excluded": True,
                 "probability_calibrated": False, "actionability": "research_signal", "injury_status": injury.get("status", "Unknown"),
                 "decision": "PASS", "units": 0.0, "full_kelly": 0.0, "quarter_kelly": 0.0, "confidence": "Low"}
        picks.append(build_pick(sport="CFB", date_iso=date_iso, game_id=str(event["id"]),
            away_team=official["away"]["displayName"], home_team=official["home"]["displayName"], start_time=event["date"],
            player_id=athlete_id, player_name=athlete["displayName"], team=team["displayName"], opponent=opponent["displayName"],
            stat_key=stat, stat_label=quote["label"], selection=selection, line=line, projection=mean,
            probability=probability, odds=quote[f"{selection.lower()}_odds"], reason=reason,
            key_factors=[f"Recency-weighted prior from {min(12, len(values))} games before {date_iso}",
                         f"Posted {quote['book']} line {line:g}; Over {quote['over_odds']:+d} / Under {quote['under_odds']:+d}",
                         f"Rolling historical projection MAE {validation['mae']} across {validation['samples']} predictions",
                         "Uncalibrated baseline; no recommended stake"], extra=extra))
    diagnostic["status"] = "projections_available" if picks else "insufficient_inputs"
    return picks, diagnostic


def generate_cfb_candidate_model(client: Any, date_iso: str, max_workers: int = 6) -> dict:
    events, injuries, _, errors = _football_schedule(client, "college-football", "CFB", date_iso)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    bucket = {"ok": True, "sport": "CFB", "date": date_iso, "updatedAt": stamp, "games": len(events), "picks": [], "errors": errors,
              "football_baseline": True, "diagnostics": [], "method": "Posted Action Network markets + dated ESPN history; uncalibrated statistical baseline"}
    if not events:
        bucket["note"] = "CFB schedule unavailable." if errors else "No CFB games scheduled."
        return bucket
    try:
        games = client.cfb_market_json("v2/scoreboard/ncaaf", date_iso).get("games", [])
        books = {str(b["id"]): str(b.get("display_name") or "") for b in client.cfb_market_json("v1/books").get("books", [])}
    except Exception as exc:
        bucket["errors"].append(str(exc))
        bucket["note"] = "CFB player markets unavailable; no projection was evaluated."
        return bucket
    work = []
    now = datetime.now(timezone.utc)
    for event in events:
        game = _match_game(event, games)
        status = ((event.get("status") or {}).get("type") or {}).get("state")
        start = _time(event.get("date"))
        if status in {"in", "post"} or not start or start <= now:
            bucket["diagnostics"].append({"game_id": str(event["id"]), "status": "not_pregame"})
        elif not game:
            bucket["diagnostics"].append({"game_id": str(event["id"]), "status": "unmatched_market_game"})
        elif game.get("status") != "scheduled":
            bucket["diagnostics"].append({"game_id": str(event["id"]), "status": "not_pregame"})
        else:
            work.append((event, game))
    def run(pair):
        event, game = pair
        try:
            return _game(client, event, game, books, date_iso, injuries, stamp)
        except Exception as exc:
            return [], {"game_id": str(event["id"]), "status": "source_error", "error": str(exc)}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for picks, diagnostic in executor.map(run, work):
            bucket["picks"].extend(picks)
            bucket["diagnostics"].append(diagnostic)
            if diagnostic.get("error"):
                bucket["errors"].append(f"{diagnostic['game_id']}: {diagnostic['error']}")
    bucket["note"] = ("Historical CFB projections are visible as PASS while native betting calibration is unvalidated."
                      if bucket["picks"] else "No pregame CFB projection has sufficient posted-market and player-history inputs; see diagnostics.")
    return bucket
