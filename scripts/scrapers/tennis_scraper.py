#!/usr/bin/env python3
"""Scrape tennis match-winner predictions by official ESPN slate.

Tennis is player-vs-player, so it does not fit the team-based Scores24/Forebet
scrapers. The official slate and the graded result both come from ESPN's ATP and
WTA scoreboards, where individual matches live under
``event["groupings"][].competitions[]`` (not the team-sport ``event.competitions``)
and each competitor carries an ``athlete`` (singles) rather than a ``team``. The
match outcome is the competitor-level ``winner`` boolean, never a score.

Two prediction sources hang off that slate:

* **TennisTonic** (``tennistonic_tennis``) — the reliable primary. Every upcoming
  match has a head-to-head page at
  ``/head-to-head-compare/First-Last-Vs-First-Last/`` whose ``prediction_set``
  element reads ``"Prediction <Surname> in <N>"``. Plain HTTP, no Cloudflare
  challenge, so it also runs on GitHub Actions. Completed matches drop the
  prediction, so this scrapes the pregame slate.

* **Scores24** (``scores24_tennis``) — best-effort secondary with real odds. Same
  ``"Our choice … at odds of …"`` editorial cell the team Scores24 scraper parses,
  at ``/en/tennis/m-DD-MM-YYYY-last-first-last-first-prediction``. Scores24
  Cloudflare-challenges datacenter IPs, so it rides the Camoufox local-publisher
  path and often has no tennis pick — a zero-pick bucket is healthy here.

Both feeds only ever publish match-winner (moneyline) picks that map cleanly onto
one of the two official ESPN athletes, so every published pick grades through
:func:`grade_tennis_picks` against the ESPN ``winner`` flag.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.scrapers.scores24_scraper import (  # noqa: E402
    CLOUDFLARE_SIGNALS,
    Scores24Client,
    _norm_space,
    _normalize_team,
    extract_listing_links,
    extract_our_choice,
)

CENTRAL = ZoneInfo("America/Chicago")
ESPN_SCOREBOARD_URL = (
    "http://site.api.espn.com/apis/site/v2/sports/tennis/{league}/scoreboard?dates={date}"
)
TENNISTONIC_BASE = "https://tennistonic.com"
SCORES24_BASE = "https://scores24.live"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# One "Tennis" sport tag on the board; the two ATP/WTA boards are unioned by the
# grader so a single sport label covers both tours.
SPORT_CONFIG: dict[str, dict[str, Any]] = {
    "tennis": {
        "espn_sport": "tennis",
        "espn_leagues": ("atp", "wta"),
        "label": "Tennis",
        "scores24_source": "Scores24Tennis",
        "tennistonic_source": "TennisTonic",
        "scores24_listing_url": f"{SCORES24_BASE}/en/tennis/predictions",
    },
}
TOUR_LABELS = {"atp": "ATP", "wta": "WTA"}


def _parse_target_date(raw: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported date: {raw}")


def _central_date(value: Any) -> date | None:
    text = _norm_space(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(CENTRAL).date()


def _name_tokens(value: str) -> list[str]:
    return [token for token in _normalize_team(value).split() if token]


def _same_person(a: str, b: str) -> bool:
    ta, tb = _name_tokens(a), _name_tokens(b)
    return bool(ta) and ta == tb


def _match_key(a: str, b: str) -> tuple[str, str] | None:
    names = sorted((_normalize_team(a), _normalize_team(b)))
    return (names[0], names[1]) if all(names) else None


def _default_fetch_json(url: str) -> Any:
    response = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
    response.raise_for_status()
    return response.json()


def espn_tennis_matches(
    date_iso: str,
    *,
    fetch_json: Callable[[str], Any] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return the official ATP+WTA singles slate for ``date_iso`` and whether it resolved.

    Each match dict carries the two athletes (``away``/``home`` by ESPN homeAway),
    the tour, kickoff, live status and — once final — the ``winner`` display name.
    Doubles rows (no ``athlete``) and unfilled draws (a ``TBD`` opponent) are
    dropped. ``resolved`` is True when at least one ESPN board answered, so an
    empty slate on a genuine off-day is distinguishable from a total fetch
    failure.
    """
    fetch_json = fetch_json or _default_fetch_json
    target = _parse_target_date(date_iso)
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    resolved = False
    for league in SPORT_CONFIG["tennis"]["espn_leagues"]:
        url = ESPN_SCOREBOARD_URL.format(league=league, date=date_iso.replace("-", ""))
        try:
            payload = fetch_json(url)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        resolved = True
        for event in payload.get("events", []) if isinstance(payload.get("events"), list) else []:
            if not isinstance(event, dict):
                continue
            for grouping in event.get("groupings", []) if isinstance(event.get("groupings"), list) else []:
                if not isinstance(grouping, dict):
                    continue
                round_name = _norm_space((grouping.get("grouping") or {}).get("displayName"))
                if "singles" not in round_name.lower():
                    continue
                event_name = _norm_space(event.get("name") or event.get("shortName"))
                event_venue = _norm_space(
                    (event.get("venue") or {}).get("displayName") if isinstance(event.get("venue"), dict) else ""
                )
                for comp in grouping.get("competitions", []) if isinstance(grouping.get("competitions"), list) else []:
                    match = _espn_competition_to_match(comp, league, round_name, target)
                    if match is None:
                        continue
                    # Tournament and venue live on the event, not the
                    # competition. The in-house model needs both to resolve
                    # surface and tier — the venue city is the stable one,
                    # since sponsor names change from season to season.
                    match["tournament"] = event_name
                    match["venue"] = event_venue
                    key = _match_key(match["away"], match["home"])
                    if key and key not in matches:
                        matches[key] = match
    return list(matches.values()), resolved


def _espn_competition_to_match(
    comp: Any,
    league: str,
    round_name: str,
    target: date,
) -> dict[str, Any] | None:
    if not isinstance(comp, dict):
        return None
    if _central_date(comp.get("date")) != target:
        return None
    competitors = comp.get("competitors") if isinstance(comp.get("competitors"), list) else []
    away = home = ""
    winner = ""
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        athlete = competitor.get("athlete") if isinstance(competitor.get("athlete"), dict) else {}
        name = _norm_space(athlete.get("displayName") or athlete.get("fullName"))
        if not name or name.upper() == "TBD":
            return None  # doubles (no athlete) or an unfilled draw slot
        side = competitor.get("homeAway")
        if side == "away":
            away = name
        elif side == "home":
            home = name
        else:
            # ESPN always tags tennis singles with homeAway, but stay defensive.
            if not away:
                away = name
            elif not home:
                home = name
        if competitor.get("winner") is True:
            winner = name
    if not away or not home:
        return None
    status = _norm_space(((comp.get("status") or {}).get("type") or {}).get("name"))
    return {
        "league": league,
        "tour": TOUR_LABELS.get(league, league.upper()),
        "away": away,
        "home": home,
        "start_time": _norm_space(comp.get("date")) or None,
        # `round` stays the grouping label ("Men's Singles") the existing feeds
        # were built against; the draw position lives beside it.
        "round": round_name,
        "round_display": _norm_space(((comp.get("round") or {}) if isinstance(comp.get("round"), dict) else {}).get("displayName")) or None,
        "status": status,
        "winner": winner or None,
    }


def _pick_payload(
    source: str,
    date_iso: str,
    match: dict[str, Any],
    winner: str,
    *,
    odds: int | None,
    tip: str,
    source_url: str,
    sets_prediction: int | None = None,
) -> dict[str, Any]:
    matchup_label = f"{match['away']} vs {match['home']}"
    payload: dict[str, Any] = {
        "source": source,
        "pick": f"{winner} ML ({matchup_label})",
        "tip": tip,
        "sport": SPORT_CONFIG["tennis"]["label"],
        "league": match.get("tour"),
        "espn_league": match.get("league"),
        "odds": odds,
        "units": 1,
        "probability": None,
        "edge": None,
        "decision": "BET",
        "date": date_iso,
        "matchup": matchup_label,
        "game": matchup_label,
        "away_team": match["away"],
        "home_team": match["home"],
        "selected_player": winner,
        "start_time": match.get("start_time"),
        "source_url": source_url,
        # No tennis calibration model exists and neither feed publishes a
        # probability, so keep tennis out of calibration training like FIFA WC;
        # site win-loss records are still computed client-side from `result`.
        "calibration_excluded": True,
        "grade_supported": True,
        "market_type": "tennis_moneyline",
    }
    if sets_prediction is not None:
        payload["tennis_sets_prediction"] = sets_prediction
    return payload


def _empty_meta(matches: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "officialMatchups": len(matches),
        "expectedMatchups": 0,
        "matchedPicks": 0,
        "missingMatchups": [],
        "unpublishedMatchups": [f"{m['away']} vs {m['home']}" for m in matches],
        "attemptedUrls": 0,
        "blockedUrls": 0,
    }


def _result_envelope(
    source: str,
    date_iso: str,
    matches: list[dict[str, Any]],
    picks: list[dict[str, Any]],
    unpublished: list[str],
    *,
    attempted: int,
    blocked: int,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Tennis is best-effort by design: a large slate with partial prediction
    # coverage is valid. A blocked or failed fetch cannot establish that a
    # source has no prediction, so transport outages remain explicit.
    meta = {
        "officialMatchups": len(matches),
        "expectedMatchups": len(picks),
        "matchedPicks": len(picks),
        "missingMatchups": [],
        "unpublishedMatchups": unpublished,
        "attemptedUrls": attempted,
        "blockedUrls": blocked,
    }
    if extra_meta:
        meta.update(extra_meta)
    unavailable = (
        bool(meta["unavailableMatchups"])
        if "unavailableMatchups" in meta
        else bool(blocked or meta.get("failedUrls"))
    )
    result = {
        "ok": bool(picks) or not unavailable,
        "date": date_iso,
        "picks": picks,
        "note": (
            f"{source} matched {len(picks)} tennis prediction(s) against "
            f"{len(matches)} official {date_iso} singles matchup(s)."
        ),
        "meta": meta,
    }
    if unavailable and not picks:
        result["error"] = (
            f"{source} returned no verified predictions while source requests "
            f"were blocked or failed ({blocked} blocked, {meta.get('failedUrls', 0)} failed)."
        )
        result["note"] = result["error"]
    return result


# --------------------------------------------------------------------------- #
# TennisTonic (primary)                                                        #
# --------------------------------------------------------------------------- #

_TENNISTONIC_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def _tennistonic_slug(name: str) -> str:
    ascii_name = "".join(
        ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)
    )
    return _TENNISTONIC_SLUG_RE.sub("-", ascii_name).strip("-")


def tennistonic_urls(match: dict[str, Any]) -> list[str]:
    away = _tennistonic_slug(match["away"])
    home = _tennistonic_slug(match["home"])
    urls = []
    for first, second in ((away, home), (home, away)):
        if first and second:
            urls.append(f"{TENNISTONIC_BASE}/head-to-head-compare/{first}-Vs-{second}/")
    return list(dict.fromkeys(urls))


def parse_tennistonic_prediction(html: str, match: dict[str, Any]) -> tuple[str, int | None] | None:
    """Return (winner display name, predicted sets) from a head-to-head page.

    The pick lives in ``class="prediction_set"`` as ``"Prediction <Surname> in
    <N>"``. The greyed ``prediction_set_not`` variant means no confident call.
    The surname is mapped back onto whichever official athlete it uniquely
    identifies; an ambiguous or unmatched surname yields no pick.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    node = soup.find(class_="prediction_set")
    if node is None:
        return None
    text = _norm_space(node.get_text(" ", strip=True))
    body = re.sub(r"^prediction[:\s]+", "", text, flags=re.IGNORECASE).strip()
    body = re.sub(r"\bin\s+(\d+)\s*(?:sets?)?\s*$", "", body, flags=re.IGNORECASE).strip()
    sets_match = re.search(r"\bin\s+(\d+)\b", text, flags=re.IGNORECASE)
    sets_prediction = int(sets_match.group(1)) if sets_match else None
    predicted_tokens = _name_tokens(body)
    if not predicted_tokens:
        return None
    winner = _resolve_named_player(predicted_tokens, match)
    if winner is None:
        return None
    return winner, sets_prediction


def _resolve_named_player(predicted_tokens: list[str], match: dict[str, Any]) -> str | None:
    """Map a name fragment onto exactly one of the match's two athletes."""
    candidates: list[str] = []
    predicted = set(predicted_tokens)
    for player in (match["away"], match["home"]):
        player_tokens = set(_name_tokens(player))
        # A surname-only prediction matches when its tokens are a subset of the
        # athlete's tokens (or share the surname), and the OTHER athlete does not.
        if predicted <= player_tokens or (predicted_tokens[-1] in player_tokens):
            candidates.append(player)
    return candidates[0] if len(candidates) == 1 else None


def _fetch_tennistonic_html(url: str) -> tuple[str, int, bool]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException:
        return "", 0, False
    lowered = response.text.lower()
    blocked = response.status_code in {403, 429} or any(
        signal in lowered[:12000] for signal in CLOUDFLARE_SIGNALS if signal != "cloudflare"
    )
    return response.text, response.status_code, blocked


def scrape_tennistonic(
    date_iso: str,
    *,
    matches: list[dict[str, Any]] | None = None,
    fetch_html: Callable[[str], tuple[str, int, bool]] | None = None,
    fetch_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    _parse_target_date(date_iso)
    source = SPORT_CONFIG["tennis"]["tennistonic_source"]
    if matches is None:
        matches, resolved = espn_tennis_matches(date_iso, fetch_json=fetch_json)
        if not resolved:
            return {
                "ok": False,
                "date": date_iso,
                "picks": [],
                "error": f"{source} could not resolve an official {date_iso} tennis slate",
            }
    if not matches:
        return {
            "ok": True,
            "date": date_iso,
            "picks": [],
            "note": f"{source} has no official {date_iso} singles matchups.",
            "meta": _empty_meta([]),
        }

    fetch_html = fetch_html or _fetch_tennistonic_html
    picks: list[dict[str, Any]] = []
    unpublished: list[str] = []
    attempted = 0
    blocked_count = 0
    failed_count = 0
    unavailable_matchups: list[str] = []
    for match in matches:
        label = f"{match['away']} vs {match['home']}"
        found = None
        unavailable = False
        resolved = False
        for url in tennistonic_urls(match):
            attempted += 1
            html, status, blocked = fetch_html(url)
            if blocked:
                blocked_count += 1
                unavailable = True
                continue
            if status == 0 or status >= 500:
                failed_count += 1
                unavailable = True
                continue
            if status != 200 or not html:
                continue
            # Guard against soft-404s: the served page must name both athletes.
            title = _norm_space(BeautifulSoup(html, "html.parser").title)
            blob = f"{title} {url.replace('-', ' ')}"
            if not (_name_tokens(match["away"])[-1] in _normalize_team(blob) and _name_tokens(match["home"])[-1] in _normalize_team(blob)):
                continue
            resolved = True
            prediction = parse_tennistonic_prediction(html, match)
            if prediction is None:
                continue
            winner, sets_prediction = prediction
            found = _pick_payload(
                source,
                date_iso,
                match,
                winner,
                odds=None,
                tip=f"{winner} to win",
                source_url=url,
                sets_prediction=sets_prediction,
            )
            break
        if found is not None:
            picks.append(found)
        elif unavailable and not resolved:
            unavailable_matchups.append(label)
        else:
            unpublished.append(label)
    return _result_envelope(
        source,
        date_iso,
        matches,
        picks,
        unpublished,
        attempted=attempted,
        blocked=blocked_count,
        extra_meta={"failedUrls": failed_count, "unavailableMatchups": unavailable_matchups},
    )


# --------------------------------------------------------------------------- #
# Scores24 (best-effort secondary)                                            #
# --------------------------------------------------------------------------- #


def _scores24_name_slug(name: str) -> str:
    ascii_name = "".join(
        ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)
    )
    parts = [p for p in re.split(r"\s+", ascii_name.strip()) if p]
    if len(parts) >= 2:
        # Scores24 slugs read "lastname-firstname"; treat the final token as the
        # surname and the rest as given names.
        surname = parts[-1]
        given = "-".join(parts[:-1])
        ordered = f"{surname}-{given}"
    else:
        ordered = "-".join(parts)
    return _TENNISTONIC_SLUG_RE.sub("-", ordered).strip("-").lower()


def scores24_tennis_candidate_urls(date_iso: str, match: dict[str, Any]) -> list[str]:
    base = _parse_target_date(date_iso)
    day_candidates = [base, base + timedelta(days=1), base - timedelta(days=1)]
    away = _scores24_name_slug(match["away"])
    home = _scores24_name_slug(match["home"])
    urls: list[str] = []
    for first, second in ((away, home), (home, away)):
        if not first or not second:
            continue
        for day in day_candidates:
            slug = day.strftime("%d-%m-%Y")
            urls.append(f"{SCORES24_BASE}/en/tennis/m-{slug}-{first}-{second}-prediction")
    return list(dict.fromkeys(urls))


def _scores24_tip_winner(tip: str, match: dict[str, Any]) -> str | None:
    """Map a Scores24 'Our choice' tip to one athlete, moneyline markets only."""
    selection = _norm_space(tip)
    lowered = selection.lower()
    # Only match-winner markets are published; skip totals/handicaps/games lines.
    if re.search(r"\b(total|over|under|handicap|hcp|games?|set|point)\b", lowered):
        return None
    selection = re.sub(r"\b(to\s+win|win(?:ner)?|money\s*line|ml)\b", " ", selection, flags=re.IGNORECASE)
    tokens = _name_tokens(selection)
    if not tokens:
        return None
    return _resolve_named_player(tokens, match)


def scrape_scores24_tennis(
    date_iso: str,
    *,
    client: Scores24Client | None = None,
    matches: list[dict[str, Any]] | None = None,
    fetch_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    _parse_target_date(date_iso)
    source = SPORT_CONFIG["tennis"]["scores24_source"]
    if matches is None:
        matches, resolved = espn_tennis_matches(date_iso, fetch_json=fetch_json)
        if not resolved:
            return {
                "ok": False,
                "date": date_iso,
                "picks": [],
                "error": f"{source} could not resolve an official {date_iso} tennis slate",
            }
    if not matches:
        return {
            "ok": True,
            "date": date_iso,
            "picks": [],
            "note": f"{source} has no official {date_iso} singles matchups.",
            "meta": _empty_meta([]),
        }

    owns_client = client is None
    scores_client = client or Scores24Client()
    listing_url = SPORT_CONFIG["tennis"]["scores24_listing_url"]
    picks: list[dict[str, Any]] = []
    unpublished: list[str] = []
    attempted = 0
    blocked_urls: set[str] = set()
    listing_resolved = False
    try:
        listing_links: list[dict[str, str]] = []
        listing_html, listing_status, listing_blocked = scores_client.get_html(listing_url)
        if listing_blocked:
            blocked_urls.add(listing_url)
        elif listing_status == 200:
            listing_resolved = True
            listing_links = extract_listing_links(listing_html)

        for match in matches:
            label = f"{match['away']} vs {match['home']}"
            listed = _matching_listing_urls(listing_links, match)
            # Only chase detail pages Scores24 actually lists for today plus the
            # exact-slug guesses; the tennis slate is far too large to brute the
            # full URL grid past a blocked host.
            candidates = list(dict.fromkeys([*listed, *scores24_tennis_candidate_urls(date_iso, match)]))
            pick = None
            for url in candidates[:6]:
                attempted += 1
                html, status, blocked = scores_client.get_html(url)
                if blocked:
                    blocked_urls.add(url)
                    break
                if status != 200 or not html:
                    continue
                title = _norm_space(BeautifulSoup(html, "html.parser").title)
                blob = _normalize_team(f"{title} {url.replace('-', ' ')}")
                if not (_name_tokens(match["away"])[-1] in blob and _name_tokens(match["home"])[-1] in blob):
                    continue
                tip, odds = extract_our_choice(html, matchup=match)
                if not tip:
                    continue
                winner = _scores24_tip_winner(tip, match)
                if winner is None:
                    break
                pick = _pick_payload(
                    source,
                    date_iso,
                    match,
                    winner,
                    odds=odds,
                    tip=tip,
                    source_url=url,
                )
                break
            if pick is not None:
                picks.append(pick)
            else:
                unpublished.append(label)
    finally:
        if owns_client:
            scores_client.close()

    return _result_envelope(
        source,
        date_iso,
        matches,
        picks,
        unpublished,
        attempted=attempted,
        blocked=len(blocked_urls),
        extra_meta={"listingResolved": listing_resolved},
    )


def _matching_listing_urls(links: list[dict[str, str]], match: dict[str, Any]) -> list[str]:
    away_last = _name_tokens(match["away"])[-1]
    home_last = _name_tokens(match["home"])[-1]
    out = []
    for link in links:
        blob = _normalize_team(f"{link.get('text', '')} {link.get('url', '').replace('-', ' ')}")
        if away_last in blob and home_last in blob:
            out.append(link["url"])
    return out


# --------------------------------------------------------------------------- #
# Grading (isolated from the team ESPN grader)                                #
# --------------------------------------------------------------------------- #


def is_tennis_pick(pick: Any) -> bool:
    return isinstance(pick, dict) and str(pick.get("sport") or "").strip().lower() == "tennis"


def grade_tennis_picks(
    picks: list[dict[str, Any]],
    *,
    fetch_json: Callable[[str], Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Grade tennis match-winner picks against the ESPN ``winner`` flag.

    Returns ``{id: {"result": win|loss|push|pending, "start_time": iso}}``. Picks
    whose match is not yet final stay ``pending``; a match found without a clear
    winner (walkover with no flag) also stays pending rather than guessing.
    """
    by_date: dict[str, list[dict[str, Any]]] = {}
    for pick in picks:
        if not isinstance(pick, dict) or not pick.get("id"):
            continue
        date_iso = str(pick.get("date") or "").strip()
        if not date_iso:
            continue
        by_date.setdefault(date_iso, []).append(pick)

    graded: dict[str, dict[str, Any]] = {}
    board_cache: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for date_iso, date_picks in by_date.items():
        board = board_cache.get(date_iso)
        if board is None:
            try:
                matches, _ = espn_tennis_matches(date_iso, fetch_json=fetch_json)
            except Exception:
                matches = []
            board = {}
            for match in matches:
                key = _match_key(match["away"], match["home"])
                if key:
                    board[key] = match
            board_cache[date_iso] = board
        for pick in date_picks:
            key = _match_key(str(pick.get("away_team") or ""), str(pick.get("home_team") or ""))
            match = board.get(key) if key else None
            entry: dict[str, Any] = {"result": "pending"}
            if match is not None:
                if match.get("start_time"):
                    entry["start_time"] = match["start_time"]
                winner = match.get("winner")
                status = str(match.get("status") or "").upper()
                if winner and "FINAL" in status:
                    selected = str(pick.get("selected_player") or "").strip()
                    if not selected:
                        selected = re.sub(r"\s+ML\s*\(.*$", "", str(pick.get("pick") or "")).strip()
                    entry["result"] = "win" if _same_person(selected, winner) else "loss"
            graded[str(pick["id"])] = entry
    return graded


# --------------------------------------------------------------------------- #
# Feed entry points                                                            #
# --------------------------------------------------------------------------- #


def run_tennistonic_tennis(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_tennistonic(date_iso)


def run_scores24_tennis(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24_tennis(date_iso)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape tennis match-winner predictions by official slate.")
    parser.add_argument("--source", default="tennistonic", choices=("tennistonic", "scores24"))
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    if args.source == "tennistonic":
        result = scrape_tennistonic(args.date)
    else:
        result = scrape_scores24_tennis(args.date)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
