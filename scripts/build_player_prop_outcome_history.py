#!/usr/bin/env python3
"""Build compact prior-season player game outcomes for prop features.

Archived books do not retain complete historical prop prices. ESPN does retain
player game logs, so this corpus is deliberately outcomes-only: it may provide
prior-performance features, but it is never treated as a betting-market label.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from player_props.api import DirectApiClient  # noqa: E402
from player_props.schema import safe_float  # noqa: E402


DEFAULT_MARKETS = REPO_ROOT / "data" / "player_props_training" / "market_history_2026.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "player_props_training" / "outcome_history_2022_2026.jsonl.gz"
DEFAULT_MAX_FAILURE_RATE = 0.02
SPORT_CONFIG = {
    "MLB": ("baseball", "mlb"),
    "WNBA": ("basketball", "wnba"),
    "NFL": ("football", "nfl"),
    "CFB": ("football", "college-football"),
}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", type=Path, default=DEFAULT_MARKETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seasons", default="2024,2025")
    parser.add_argument("--sports", default="MLB,WNBA,NFL,CFB")
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--max-failure-rate", type=float, default=DEFAULT_MAX_FAILURE_RATE)
    parser.add_argument("--refresh", action="store_true", help="Refetch profiles already present in the output.")
    return parser.parse_args()


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text.lower() in {"nan", "--", "-"}:
        return None
    if "-" in text and not text.startswith("-"):
        text = text.split("-", 1)[0]
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_stat_name(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _made_attempted(value: Any) -> tuple[float | None, float | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    if "-" not in text:
        return _number(text), None
    made_text, attempted_text = text.split("-", 1)
    return _number(made_text), _number(attempted_text)


def _outs(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "." not in text:
        innings = _number(text)
        return innings * 3.0 if innings is not None else None
    whole, partial = text.split(".", 1)
    innings = _number(whole)
    remainder = _number(partial[:1])
    if innings is None or remainder is None:
        return None
    return innings * 3.0 + max(0.0, min(2.0, remainder))


def _requested_athletes(path: Path, sports: set[str]) -> dict[str, set[str]]:
    athletes = {sport: set() for sport in sports}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        sport = str(row.get("sport") or "").upper()
        athlete_id = str(row.get("athlete_id") or "").strip()
        if sport in athletes and athlete_id:
            athletes[sport].add(athlete_id)
    return athletes


def _read_existing(path: Path) -> tuple[list[dict[str, Any]], set[tuple[str, int, str]]]:
    if not path.exists():
        return [], set()
    rows: list[dict[str, Any]] = []
    completed: set[tuple[str, int, str]] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            rows.append(row)
            completed.add((str(row.get("sport") or ""), int(row.get("season") or 0), str(row.get("athlete_id") or "")))
    return rows, completed


def _event_rows(sport: str, athlete_id: str, season: int, payload: dict[str, Any]) -> list[dict[str, Any]]:
    names = [str(value) for value in payload.get("names") or []]
    event_index = payload.get("events") if isinstance(payload.get("events"), dict) else {}
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for season_type in payload.get("seasonTypes") or []:
        if "preseason" in str(season_type.get("displayName") or "").lower():
            continue
        for category in season_type.get("categories") or []:
            if category.get("type") != "event":
                continue
            for item in category.get("events") or []:
                event_id = str(item.get("eventId") or "")
                values = item.get("stats") or []
                event = event_index.get(event_id) if isinstance(event_index.get(event_id), dict) else {}
                if not event_id or event_id in seen or len(values) < len(names):
                    continue
                stats: dict[str, float | None] = {}
                for index, name in enumerate(names):
                    value = values[index]
                    stats[name] = _number(value)
                    if _canonical_stat_name(name) in {
                        "threepointfieldgoalsmadethreepointfieldgoalsattempted",
                        "fg3mfg3a",
                        "3pm3pa",
                    }:
                        made, attempted = _made_attempted(value)
                        stats["three_pointers_made"] = made
                        stats["three_pointers_attempted"] = attempted
                    elif _canonical_stat_name(name) in {"threepointfieldgoalsmade", "fg3m", "3pm"}:
                        stats["three_pointers_made"] = _number(value)
                    elif _canonical_stat_name(name) in {"threepointfieldgoalsattempted", "fg3a", "3pa"}:
                        stats["three_pointers_attempted"] = _number(value)
                    football_aliases = {
                        "passingyards": "passing_yards",
                        "passyards": "passing_yards",
                        "passingtouchdowns": "passing_tds",
                        "passingtds": "passing_tds",
                        "passingcompletions": "passing_completions",
                        "completions": "passing_completions",
                        "interceptions": "interceptions",
                        "rushingyards": "rushing_yards",
                        "rushyards": "rushing_yards",
                        "rushingattempts": "rushing_attempts",
                        "carries": "rushing_attempts",
                        "rushingtouchdowns": "rushing_tds",
                        "receivingyards": "receiving_yards",
                        "receptions": "receptions",
                        "receivingtouchdowns": "receiving_tds",
                        "passingattempts": "passing_attempts",
                        "targets": "targets",
                    }
                    mapped = football_aliases.get(_canonical_stat_name(name))
                    if mapped:
                        stats[mapped] = _number(value)
                    if "-" in str(value) and _canonical_stat_name(name) in {"cmpatt", "completionattempts"}:
                        made, attempted = _made_attempted(value)
                        stats["passing_completions"] = made
                        stats["passing_attempts"] = attempted
                context = {
                    "minutes": stats.get("minutes"),
                    "usage": (
                        stats.get("minutes")
                        if sport == "WNBA"
                        else (
                            (stats.get("passing_attempts") or 0)
                            + (stats.get("rushing_attempts") or 0)
                            + (stats.get("targets") or stats.get("receptions") or 0)
                            if sport in {"NFL", "CFB"}
                            else stats.get("battersFaced") if "innings" in stats else stats.get("atBats")
                        )
                    ),
                    "opponent_id": str((event.get("opponent") or {}).get("id") or ""),
                    "team_id": str((event.get("team") or {}).get("id") or ""),
                    "home_away": str(event.get("atVs") or ""),
                }
                actuals: dict[str, float | None]
                if sport == "MLB" and "innings" in stats:
                    actuals = {
                        "strikeouts": stats.get("strikeouts"),
                        "pitcher_walks_allowed": stats.get("walks"),
                        "pitcher_hits_allowed": stats.get("hits"),
                        "pitcher_earned_runs_allowed": stats.get("earnedRuns"),
                        "pitcher_outs_recorded": _outs(values[names.index("innings")]),
                    }
                elif sport == "MLB":
                    hits = stats.get("hits")
                    runs = stats.get("runs")
                    rbis = stats.get("RBIs")
                    actuals = {
                        "hits": hits,
                        "runs": runs,
                        "rbis": rbis,
                        "home_runs": stats.get("homeRuns"),
                        "batter_walks": stats.get("walks"),
                        "batter_strikeouts": stats.get("strikeouts"),
                        "hits_runs_rbis": hits + runs + rbis if hits is not None and runs is not None and rbis is not None else None,
                    }
                elif sport in {"NFL", "CFB"}:
                    actuals = {
                        "passing_yards": stats.get("passing_yards"),
                        "passing_tds": stats.get("passing_tds"),
                        "passing_completions": stats.get("passing_completions"),
                        "interceptions": stats.get("interceptions"),
                        "rushing_yards": stats.get("rushing_yards"),
                        "rushing_attempts": stats.get("rushing_attempts"),
                        "rushing_tds": stats.get("rushing_tds"),
                        "receiving_yards": stats.get("receiving_yards"),
                        "receptions": stats.get("receptions"),
                        "receiving_tds": stats.get("receiving_tds"),
                    }
                else:
                    points = stats.get("points")
                    rebounds = stats.get("totalRebounds")
                    assists = stats.get("assists")
                    actuals = {
                        "points": points,
                        "totalRebounds": rebounds,
                        "assists": assists,
                        "three_pointers_made": stats.get("three_pointers_made"),
                        "points_rebounds": points + rebounds if points is not None and rebounds is not None else None,
                        "points_assists": points + assists if points is not None and assists is not None else None,
                        "points_rebounds_assists": (
                            points + rebounds + assists
                            if points is not None and rebounds is not None and assists is not None
                            else None
                        ),
                    }
                game_timestamp = str(event.get("gameDate") or "")
                try:
                    game_date = (
                        datetime.fromisoformat(game_timestamp.replace("Z", "+00:00"))
                        .astimezone(ZoneInfo("America/Chicago"))
                        .date()
                        .isoformat()
                    )
                except ValueError:
                    game_date = game_timestamp[:10]
                for stat_key, actual in actuals.items():
                    if actual is None or not math.isfinite(float(actual)):
                        continue
                    output.append({
                        "sport": sport,
                        "season": season,
                        "date": game_date,
                        "event_id": event_id,
                        "athlete_id": athlete_id,
                        "stat_key": stat_key,
                        "actual": float(actual),
                        "source": "ESPN player gamelog",
                        **context,
                        **(
                            {
                                "three_pointers_attempted": stats.get("three_pointers_attempted"),
                            }
                            if sport == "WNBA" and stat_key == "three_pointers_made"
                            else {}
                        ),
                    })
                seen.add(event_id)
    return output


def _fetch(sport: str, athlete_id: str, season: int) -> tuple[str, int, str, list[dict[str, Any]], str | None]:
    segment, league = SPORT_CONFIG[sport]
    client = DirectApiClient(timeout=30.0, attempts=3)
    try:
        payload = client._get(  # noqa: SLF001 - ESPN has no public SDK for this endpoint
            f"https://site.web.api.espn.com/apis/common/v3/sports/{segment}/{league}/athletes/{athlete_id}/gamelog",
            {"season": season, "region": "us", "lang": "en", "contentorigin": "espn"},
        )
        return sport, season, athlete_id, _event_rows(sport, athlete_id, season, payload), None
    except Exception as exc:  # network failures are reported and retried on the next run
        return sport, season, athlete_id, [], str(exc)


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    deduped = {
        (row["sport"], row["season"], row["event_id"], row["athlete_id"], row["stat_key"]): row
        for row in rows
    }
    ordered = sorted(deduped.values(), key=lambda row: (
        row["date"], row["sport"], row["event_id"], row["athlete_id"], row["stat_key"]
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        for row in ordered:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _fetch_task_batch(
    tasks: list[tuple[str, str, int]],
    *,
    max_workers: int,
    rows: list[dict[str, Any]],
    label: str,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if not tasks:
        return failures
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
        futures = {executor.submit(_fetch, *task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), start=1):
            sport, season, athlete_id, fetched, error = future.result()
            rows.extend(fetched)
            if error:
                failures.append({"sport": sport, "season": season, "athlete_id": athlete_id, "error": error})
            if index % 100 == 0 or index == len(tasks):
                print(
                    f"[outcome-history] {label} completed {index}/{len(tasks)} profiles; "
                    f"rows={len(rows)}; failures={len(failures)}"
                )
    return failures


def main() -> int:
    args = _arguments()
    seasons = sorted({int(value.strip()) for value in str(args.seasons).split(",") if value.strip()})
    sports = {value.strip().upper() for value in str(args.sports).split(",") if value.strip()}
    unknown = sports - set(SPORT_CONFIG)
    if unknown:
        raise SystemExit(f"Unsupported sport(s): {', '.join(sorted(unknown))}")
    athletes = _requested_athletes(args.markets.resolve(), sports)
    existing, completed = _read_existing(args.output.resolve())
    tasks = [
        (sport, athlete_id, season)
        for sport in sorted(sports)
        for athlete_id in sorted(athletes[sport])
        for season in seasons
        if args.refresh or (sport, season, athlete_id) not in completed
    ]
    rows = list(existing)
    failures = _fetch_task_batch(
        tasks,
        max_workers=max(1, int(args.max_workers)),
        rows=rows,
        label="primary",
    )
    if failures:
        retry_tasks = [
            (str(failure["sport"]), str(failure["athlete_id"]), int(failure["season"]))
            for failure in failures
        ]
        retry_workers = max(1, min(len(retry_tasks), max(1, int(args.max_workers) // 4)))
        print(f"[outcome-history] retrying {len(retry_tasks)} failed profile(s) with {retry_workers} worker(s)")
        failures = _fetch_task_batch(
            retry_tasks,
            max_workers=retry_workers,
            rows=rows,
            label="retry",
        )
    _write(args.output.resolve(), rows)
    failure_rate = len(failures) / len(tasks) if tasks else 0.0
    ok = bool(rows) and failure_rate <= max(0.0, float(args.max_failure_rate))
    if failures and ok:
        print(
            "[outcome-history] warning: accepted partial history refresh "
            f"with {len(failures)}/{len(tasks)} profile failure(s) "
            f"({failure_rate:.2%}; threshold={float(args.max_failure_rate):.2%})"
        )
    elif failures:
        print(
            "[outcome-history] failure: too many profile failures after retry "
            f"({len(failures)}/{len(tasks)}; {failure_rate:.2%}; "
            f"threshold={float(args.max_failure_rate):.2%})"
        )
    if not rows:
        print("[outcome-history] failure: output would be empty")
    print(json.dumps({
        "ok": ok,
        "output": str(args.output.resolve()),
        "rows": len(rows),
        "athletes": {sport: len(values) for sport, values in athletes.items()},
        "seasons": seasons,
        "profiles": len(tasks),
        "failureRate": failure_rate,
        "maxFailureRate": float(args.max_failure_rate),
        "failures": failures,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
