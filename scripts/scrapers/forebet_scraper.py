#!/usr/bin/env python3
"""Scrape Forebet predictions by official slate matchup.

Forebet renders predictions as div-based rows (`div.rcnt`), not a table.
Each row decodes as:

  .stcn   league short code            .fprc    "44 34 22" = P(home/draw/away) %
  .tnms   teams + kickoff (schema.org) .forepr  tip sign: 1=home, X=draw, 2=away
  .ex_sc  predicted correct score      .avg_sc  expected total goals/runs/points
  .haodd  American odds [home, draw, away] ("no"/"-" when unposted)
  .lmin_td match status (minute/FT/Postp.)  .lscr_td live/final score

Two-way sports (baseball/basketball/American football) use a `bsk`-classed
probability cell holding just "56 44" = P(home/away), signs limited to 1/2,
and a two-entry odds list.

Rows are matched against the official ESPN slate for the target date (same
identity-based convention as the Scores24 scraper), disambiguated by kickoff
time because Forebet league pages carry weeks of history and series opponents
repeat on consecutive days. Grading then runs through the standard ESPN
auto-grade path, so Forebet's own score cells are unused.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from curl_cffi import requests as browser_requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.scrapers.scores24_scraper import (  # noqa: E402
    CLOUDFLARE_SIGNALS,
    _soccer_market_metadata,
    _team_matches,
    fetch_daily_matchups,
)


BASE_URL = "https://www.forebet.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
SPORT_CONFIG = {
    "mls": {
        "espn_sport": "soccer",
        "espn_league": "usa.1",
        "listing_url": f"{BASE_URL}/en/football-tips-and-predictions-for-usa/mls",
        "source": "ForebetMLS",
        "label": "MLS",
        "cache_keys": ("mls",),
        "market": "soccer_1x2",
    },
    "mlb": {
        "espn_sport": "baseball",
        "espn_league": "mlb",
        "listing_url": f"{BASE_URL}/en/baseball/usa/mlb",
        "source": "ForebetMLB",
        "label": "MLB",
        "cache_keys": ("mlb_first_five", "mlb_inning", "mlb_new"),
        "market": "two_way",
    },
    "wnba": {
        "espn_sport": "basketball",
        "espn_league": "wnba",
        "listing_url": f"{BASE_URL}/en/basketball/usa/wnba",
        "source": "ForebetWNBA",
        "label": "WNBA",
        "cache_keys": ("wnba",),
        "market": "two_way",
    },
    "cfb": {
        "espn_sport": "football",
        "espn_league": "college-football",
        "espn_query": "groups=80&limit=200",
        "listing_url": f"{BASE_URL}/en/american-football/usa/ncaa",
        "source": "ForebetCFB",
        "label": "CFB",
        "cache_keys": ("cfb",),
        "market": "two_way",
    },
    "nfl": {
        "espn_sport": "football",
        "espn_league": "nfl",
        "listing_url": f"{BASE_URL}/en/american-football/usa/nfl",
        "source": "ForebetNFL",
        "label": "NFL",
        "cache_keys": ("nfl",),
        "market": "two_way",
    },
}
SIGN_INDEX = {"1": 0, "X": 1, "2": 2}
TWO_WAY_SIGN_INDEX = {"1": 0, "2": 1}
SCORE_RE = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})")
AMERICAN_ODDS_RE = re.compile(r"^[+-]\d+$")
KICKOFF_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
# Forebet timestamps sit within a few hours of UTC; series games are >=20h
# apart, so this window disambiguates them regardless of the exact site zone.
KICKOFF_MATCH_WINDOW_SECONDS = 8 * 3600


def _cell_text(row: Any, selector: str) -> str:
    node = row.select_one(selector)
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def _american_odds(token: str) -> int | None:
    token = str(token or "").strip()
    return int(token) if AMERICAN_ODDS_RE.match(token) else None


def _parse_kickoff(text: str) -> datetime | None:
    match = KICKOFF_RE.search(text or "")
    if not match:
        return None
    day, month, year, hour, minute = match.groups()
    if hour is None:
        return None
    try:
        return datetime(int(year), int(month), int(day), int(hour), int(minute))
    except ValueError:
        return None


def parse_forebet_rows(html: str) -> list[dict[str, Any]]:
    """Extract normalized prediction rows from a Forebet listing page."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for row in soup.select("div.rcnt"):
        # Soccer rows wrap names in schema.org microdata; baseball/basketball
        # rows carry bare spans, so select the container and take its text.
        home = _cell_text(row, ".homeTeam")
        away = _cell_text(row, ".awayTeam")
        sign = _cell_text(row, ".forepr span")
        if not home or not away or sign not in SIGN_INDEX:
            continue

        fprc = row.select_one(".fprc")
        two_way = bool(fprc is not None and "bsk" in (fprc.get("class") or []))
        if two_way and sign == "X":
            continue
        prob_ints = [int(tok) for tok in re.findall(r"\d{1,3}", _cell_text(row, ".fprc"))]
        width = 2 if two_way else 3
        valid = len(prob_ints) >= width and 90 <= sum(prob_ints[:width]) <= 110
        if two_way:
            probs = [prob_ints[0], None, prob_ints[1]] if valid else [None, None, None]
        else:
            probs = list(prob_ints[:3]) if valid else [None, None, None]

        # .haodd spans hold [home, draw, away] for soccer and [home, away, ""]
        # for two-way sports; normalize both to the home/draw/away triple.
        odds: list[int | None] = [None, None, None]
        haodd = row.select_one(".haodd")
        if haodd:
            tokens = [span.get_text(strip=True) for span in haodd.find_all("span")][:3]
            parsed = [_american_odds(token) for token in tokens] + [None] * (3 - len(tokens))
            odds = [parsed[0], None, parsed[1]] if two_way else parsed

        predicted = SCORE_RE.search(_cell_text(row, ".ex_sc"))
        avg_goals = re.search(r"\d+\.\d+", _cell_text(row, ".avg_sc"))
        kickoff = _cell_text(row, ".date_bah")
        rows.append(
            {
                "home": home,
                "away": away,
                "sign": sign,
                "two_way": two_way,
                "prob_home": probs[0],
                "prob_draw": probs[1],
                "prob_away": probs[2],
                "odds_home": odds[0],
                "odds_draw": odds[1],
                "odds_away": odds[2],
                "predicted_score": f"{predicted.group(1)}-{predicted.group(2)}" if predicted else None,
                "avg_goals": float(avg_goals.group()) if avg_goals else None,
                "kickoff": kickoff,
                "kickoff_dt": _parse_kickoff(kickoff),
            }
        )
    return rows


def _listing_is_blocked(html: str) -> bool:
    # Successful listings include Cloudflare analytics and challenge-platform
    # scripts too. Only visible challenge text signals a blocked page.
    visible = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    return any(signal in visible for signal in CLOUDFLARE_SIGNALS)


def _fetch_listing_html(url: str) -> tuple[str, str]:
    """Return (html, error), retrying challenged listings with browser TLS."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        return "", f"listing fetch failed: {exc}"
    if response.status_code == 403 or _listing_is_blocked(response.text):
        try:
            response = browser_requests.get(url, headers=HEADERS, impersonate="chrome", timeout=30)
        except Exception as exc:
            return "", f"listing browser-TLS retry failed: {exc}"
    if _listing_is_blocked(response.text):
        return "", "listing fetch blocked by Cloudflare"
    if response.status_code != 200:
        return "", f"listing fetch returned HTTP {response.status_code}"
    return response.text, ""


def _parse_slate_start(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _match_row(matchup: dict[str, str], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Strict orientation: the tip sign is only meaningful relative to the home
    # side, so a swapped-orientation match must not count.
    candidates = [
        row
        for row in rows
        if _team_matches(matchup["home"], row["home"]) and _team_matches(matchup["away"], row["away"])
    ]
    if not candidates:
        return None
    slate_start = _parse_slate_start(matchup.get("start_time"))
    timed = [row for row in candidates if row["kickoff_dt"] is not None]
    if slate_start is None:
        return candidates[0]
    if not timed:
        return None
    # League pages list weeks of history and series opponents repeat daily;
    # only the row nearest the official start (within the window) is the game.
    best = min(timed, key=lambda row: abs((row["kickoff_dt"] - slate_start).total_seconds()))
    if abs((best["kickoff_dt"] - slate_start).total_seconds()) <= KICKOFF_MATCH_WINDOW_SECONDS:
        return best
    return None


def _pick_payload(
    config: dict[str, Any],
    date_iso: str,
    matchup: dict[str, str],
    row: dict[str, Any],
) -> dict[str, Any]:
    sign = row["sign"]
    tip = {"1": f"{matchup['home']} ML", "X": "Draw", "2": f"{matchup['away']} ML"}[sign]
    matchup_label = f"{matchup['away']} @ {matchup['home']}"
    probability = (row["prob_home"], row["prob_draw"], row["prob_away"])[SIGN_INDEX[sign]]
    payload = {
        "source": config["source"],
        "pick": f"{tip} ({matchup_label})",
        "tip": tip,
        "sport": config["label"],
        "odds": (row["odds_home"], row["odds_draw"], row["odds_away"])[SIGN_INDEX[sign]],
        "units": 1,
        "probability": round(probability / 100.0, 4) if probability is not None else None,
        "edge": None,
        "decision": "BET",
        "date": date_iso,
        "matchup": matchup_label,
        "game": matchup_label,
        "away_team": matchup["away"],
        "home_team": matchup["home"],
        "start_time": matchup.get("start_time") or None,
        "source_url": config["listing_url"],
        "forebet_prob_home": row["prob_home"],
        "forebet_prob_draw": row["prob_draw"],
        "forebet_prob_away": row["prob_away"],
        "forebet_predicted_score": row["predicted_score"],
        "forebet_avg_goals": row["avg_goals"],
    }
    if config["market"] == "soccer_1x2":
        # Soccer sources are calibration-excluded and carry 3-way market
        # metadata; two-way ML picks grade through the generic path like the
        # other MLB/WNBA external feeds and need neither.
        payload["calibration_excluded"] = True
        payload.update(_soccer_market_metadata(payload["pick"]))
    return payload


def scrape_forebet(sport: str, date_iso: str, *, html: str | None = None) -> dict[str, Any]:
    sport_key = sport.strip().lower()
    if sport_key not in SPORT_CONFIG:
        raise ValueError(f"unsupported Forebet sport: {sport}")
    config = SPORT_CONFIG[sport_key]
    expected, slate_resolved = fetch_daily_matchups(sport_key, date_iso, config=config)
    if not slate_resolved:
        return {
            "ok": False,
            "date": date_iso,
            "picks": [],
            "error": f"{config['source']} could not resolve an official {date_iso} slate",
        }
    if not expected:
        return {
            "ok": True,
            "date": date_iso,
            "picks": [],
            "note": f"{config['source']} has no official {date_iso} matchups.",
            "meta": {
                "officialMatchups": 0,
                "expectedMatchups": 0,
                "matchedPicks": 0,
                "missingMatchups": [],
                "unpublishedMatchups": [],
                "attemptedUrls": 0,
                "blockedUrls": 0,
            },
        }

    blocked = 0
    if html is None:
        html, fetch_error = _fetch_listing_html(config["listing_url"])
        if fetch_error:
            blocked = int("Cloudflare" in fetch_error)
            return {
                "ok": False,
                "date": date_iso,
                "picks": [],
                "error": f"{config['source']}: {fetch_error}",
                "meta": {
                    "officialMatchups": len(expected),
                    "expectedMatchups": 0,
                    "matchedPicks": 0,
                    "missingMatchups": [f"{m['away']} @ {m['home']}" for m in expected],
                    "unpublishedMatchups": [],
                    "attemptedUrls": 1,
                    "blockedUrls": blocked,
                },
            }

    rows = parse_forebet_rows(html)
    if config["market"] == "two_way":
        rows = [row for row in rows if row["two_way"]]
    picks: list[dict[str, Any]] = []
    unpublished: list[str] = []
    for matchup in expected:
        row = _match_row(matchup, rows)
        if row is None:
            unpublished.append(f"{matchup['away']} @ {matchup['home']}")
            continue
        picks.append(_pick_payload(config, date_iso, matchup, row))

    return {
        "ok": True,
        "date": date_iso,
        "picks": picks,
        "note": (
            f"{config['source']} matched {len(picks)} published prediction(s) "
            f"against {len(expected)} official {date_iso} matchup(s)."
        ),
        "meta": {
            "officialMatchups": len(expected),
            "expectedMatchups": len(picks),
            "matchedPicks": len(picks),
            "missingMatchups": [],
            "unpublishedMatchups": unpublished,
            "attemptedUrls": 1,
            "blockedUrls": blocked,
            "listedRows": len(rows),
        },
    }


def run_forebet_mls(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_forebet("mls", date_iso)


def run_forebet_mlb(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_forebet("mlb", date_iso)


def run_forebet_wnba(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_forebet("wnba", date_iso)


def run_forebet_cfb(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_forebet("cfb", date_iso)


def run_forebet_nfl(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_forebet("nfl", date_iso)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Forebet predictions by official matchup.")
    parser.add_argument("--sport", default="mls", choices=sorted(SPORT_CONFIG))
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--html-file", default="", help="Parse a saved listing page instead of fetching.")
    args = parser.parse_args()
    html = None
    if args.html_file:
        with open(args.html_file, encoding="utf-8") as handle:
            html = handle.read()
    result = scrape_forebet(args.sport, args.date, html=html)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
