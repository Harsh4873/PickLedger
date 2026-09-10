#!/usr/bin/env python3
"""Scrape Scores24 editorial choices by official slate matchup."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://scores24.live"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.scrapers.espn_scoreboard import fetch_scoreboard_json

MODEL_CACHE_DIR = REPO_ROOT / "data" / "model_cache"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
SPORT_CONFIG = {
    "nba_summer": {
        "espn_sport": "basketball",
        "espn_league": "nba-summer",
        "scores24_sport": "basketball",
        "listing_url": f"{BASE_URL}/en/basketball/l-usa-nba-summer-league/predictions",
        "listing_urls": (
            f"{BASE_URL}/en/basketball/l-usa-nba-summer-league/predictions",
            f"{BASE_URL}/en/basketball/predictions",
        ),
        "source": "Scores24NBASummer",
        "label": "NBA SUMMER",
        "cache_keys": ("nba_summer",),
    },
    "wnba": {
        "espn_sport": "basketball",
        "espn_league": "wnba",
        "scores24_sport": "basketball",
        "listing_url": f"{BASE_URL}/en/basketball/l-usa-wnba/predictions",
        "source": "Scores24WNBA",
        "label": "WNBA",
        "cache_keys": ("wnba",),
    },
    "mlb": {
        "espn_sport": "baseball",
        "espn_league": "mlb",
        "scores24_sport": "baseball",
        "listing_url": f"{BASE_URL}/en/baseball/l-usa-mlb/predictions",
        "source": "Scores24MLB",
        "label": "MLB",
        "cache_keys": ("mlb_first_five", "mlb_inning", "mlb_new"),
    },
    "fifa_world_cup": {
        "espn_sport": "soccer",
        "espn_league": "fifa.world",
        "scores24_sport": "soccer",
        "listing_url": f"{BASE_URL}/en/soccer/l-international-world-championship/predictions",
        "source": "Scores24FIFAWorldCup",
        "label": "FIFA WC",
        "cache_keys": ("fifa_world_cup",),
    },
    # Sport key `cfb` matches the in-house CFB Model bucket; the feed cache key is
    # scores24_cfb. ESPN uses football/college-football (FBS via groups=80).
    # Scores24 NCAA and sport-wide American Football listings cover complementary
    # days, so scrape_scores24 walks the full listing_urls tuple.
    "cfb": {
        "espn_sport": "football",
        "espn_league": "college-football",
        "espn_query": "limit=1000&groups=80",
        "scores24_sport": "american-football",
        "listing_url": f"{BASE_URL}/en/american-football/l-ncaa-regular-season-standings/predictions",
        "listing_urls": (
            f"{BASE_URL}/en/american-football/l-ncaa-regular-season-standings/predictions",
            f"{BASE_URL}/en/predictions/american-football",
            f"{BASE_URL}/en/predictions/american-football/today",
        ),
        "source": "Scores24CFB",
        "label": "CFB",
        "cache_keys": ("cfb",),
    },
    # NFL listings are USA NFL, not NCAA. Sport-wide American Football pages are
    # fallbacks; the official ESPN NFL whitelist keeps college games out.
    "nfl": {
        "espn_sport": "football",
        "espn_league": "nfl",
        "scores24_sport": "american-football",
        "listing_url": f"{BASE_URL}/en/american-football/l-usa-nfl/predictions",
        "listing_urls": (
            f"{BASE_URL}/en/american-football/l-usa-nfl/predictions",
            f"{BASE_URL}/en/predictions/american-football",
            f"{BASE_URL}/en/predictions/american-football/today",
        ),
        "source": "Scores24NFL",
        "label": "NFL",
        "cache_keys": ("nfl",),
    },
}
CLOUDFLARE_SIGNALS = (
    "attention required",
    "just a moment",
    "performing security verification",
    "sorry, you have been blocked",
    "cf-error-details",
    "challenge-platform",
    "cloudflare",
)
TEAM_TEXT_ALIASES = {
    "cleveland gardians": "cleveland guardians",
    "czech republic": "czechia",
    "los angeles fc": "lafc",
    "oakland athletics": "athletics",
    "saint louis": "st louis",
    "turkiye": "turkey",
    "usa": "united states",
    "ole miss": "mississippi",
    "lsu": "louisiana state",
    "usc": "southern california",
    "tcu": "texas christian",
    "smu": "southern methodist",
    "byu": "brigham young",
    "ucf": "central florida",
    "utep": "texas el paso",
    "utsa": "texas san antonio",
    "miami hurricanes": "miami florida",
    "miami fl": "miami florida",
    "miami oh": "miami ohio",
    "miami redhawks": "miami ohio",
}
TEAM_SLUG_ALIASES = {
    "Cleveland Guardians": ("Cleveland Gardians",),
    "Czechia": ("Czech Republic",),
    "Athletics": ("Oakland Athletics",),
    "United States": ("USA", "United States of America"),
    "LSU Tigers": ("LSU", "Louisiana State"),
    "Ole Miss Rebels": ("Ole Miss", "Mississippi"),
    "USC Trojans": ("USC", "Southern California"),
    "Miami Hurricanes": ("Miami FL", "Miami Florida", "Miami (FL)"),
    "Miami (OH) RedHawks": ("Miami OH", "Miami Ohio", "Miami (OH)"),
}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _norm_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_team(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s*\(w\)\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    for alias, canonical in TEAM_TEXT_ALIASES.items():
        text = re.sub(rf"\b{re.escape(alias)}\b", canonical, text)
    return text


def _team_matches(expected: str, candidate: str) -> bool:
    expected_norm = _normalize_team(expected)
    candidate_norm = _normalize_team(candidate)
    if not expected_norm or not candidate_norm:
        return False
    if expected_norm == candidate_norm:
        return True
    if len(expected_norm) >= 4 and expected_norm in candidate_norm:
        return True
    if len(candidate_norm) >= 4 and candidate_norm in expected_norm:
        return True
    expected_tokens = expected_norm.split()
    candidate_tokens = candidate_norm.split()
    return bool(expected_tokens and expected_tokens[-1] in candidate_tokens)


def _matchup_matches_blob(matchup: dict[str, str], blob: str) -> bool:
    return _team_matches(matchup.get("away", ""), blob) and _team_matches(matchup.get("home", ""), blob)


def _matchup_key(away: str, home: str) -> tuple[str, str] | None:
    teams = sorted((_normalize_team(away), _normalize_team(home)))
    return (teams[0], teams[1]) if all(teams) else None


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
    return parsed.astimezone(ZoneInfo("America/Chicago")).date()


def _row_matches_target_date(row: dict[str, Any], date_iso: str) -> bool:
    target = _parse_target_date(date_iso)
    for key in ("start_time", "game_start_time", "gameDate", "game_date", "date"):
        row_date = _central_date(row.get(key))
        if row_date is not None:
            return row_date == target
    return True


def _cache_matchups(
    sport: str,
    date_iso: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    config = config or SPORT_CONFIG[sport]
    for path in (MODEL_CACHE_DIR / f"{date_iso}.json", MODEL_CACHE_DIR / "latest.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or str(payload.get("date") or "") != date_iso:
            continue
        models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
        matchups: dict[tuple[str, str], dict[str, str]] = {}
        for model_key in config["cache_keys"]:
            bucket = models.get(model_key) if isinstance(models.get(model_key), dict) else {}
            rows = bucket.get("games") if isinstance(bucket.get("games"), list) else bucket.get("picks")
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                if not _row_matches_target_date(row, date_iso):
                    continue
                away = _norm_space(row.get("away_team"))
                home = _norm_space(row.get("home_team"))
                if not away or not home:
                    continue
                key = _matchup_key(away, home)
                if not key:
                    continue
                matchups.setdefault(
                    key,
                    {
                        "away": away,
                        "home": home,
                        "start_time": _norm_space(row.get("start_time") or row.get("game_start_time")),
                    },
                )
        if matchups:
            return list(matchups.values())
    return []


def _espn_scoreboard_url(config: dict[str, Any], date_iso: str) -> str:
    compact = date_iso.replace("-", "")
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        f"{config['espn_sport']}/{config['espn_league']}/scoreboard?dates={compact}"
    )
    extra = str(config.get("espn_query") or "").strip().lstrip("&")
    if extra:
        url = f"{url}&{extra}"
    return url


def fetch_daily_matchups(
    sport: str,
    date_iso: str,
    session: requests.Session | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Return official daily matchups and whether the slate was resolved.

    The second value is True when ESPN returned a scoreboard for the date or
    committed cache supplied fallback matchups. A successful ESPN response with
    zero events is still resolved (off-day). `config` lets other scrapers
    (e.g. Forebet) reuse this slate resolution with their own sport table.
    """
    config = config or SPORT_CONFIG[sport]
    url = _espn_scoreboard_url(config, date_iso)
    matchups: dict[tuple[str, str], dict[str, str]] = {}
    espn_resolved = False
    try:
        # Pass through an injected session (tests/mocks). When none is given,
        # leave session unset so fetch_scoreboard_json can use curl_cffi after
        # ESPN 403s plain requests from datacenter IPs.
        if session is None:
            payload = fetch_scoreboard_json(url)
        else:
            payload = fetch_scoreboard_json(url, session=session)
        espn_resolved = True
    except (requests.RequestException, ValueError):
        payload = {}

    for event in payload.get("events", []) if isinstance(payload, dict) else []:
        target = _parse_target_date(date_iso)
        event_date = _central_date(event.get("date")) if isinstance(event, dict) else None
        if event_date not in {None, target}:
            continue
        competitions = event.get("competitions") if isinstance(event, dict) else []
        competition = competitions[0] if isinstance(competitions, list) and competitions else {}
        competition_date = _central_date(competition.get("date")) if isinstance(competition, dict) else None
        if competition_date not in {None, target}:
            continue
        competitors = competition.get("competitors") if isinstance(competition, dict) else []
        away = home = ""
        for competitor in competitors if isinstance(competitors, list) else []:
            team = competitor.get("team") if isinstance(competitor, dict) else {}
            name = _norm_space(team.get("displayName") or team.get("shortDisplayName")) if isinstance(team, dict) else ""
            if competitor.get("homeAway") == "away":
                away = name
            elif competitor.get("homeAway") == "home":
                home = name
        key = _matchup_key(away, home)
        if key:
            matchups[key] = {
                "away": away,
                "home": home,
                "start_time": _norm_space(event.get("date") or competition.get("date")),
            }

    cached = _cache_matchups(sport, date_iso, config=config)
    for matchup in cached:
        key = _matchup_key(matchup["away"], matchup["home"])
        if key:
            matchups.setdefault(key, matchup)
    return list(matchups.values()), espn_resolved or bool(cached)


def _checkpoint_dir() -> Path | None:
    raw = os.environ.get("SCORES24_CHECKPOINT_DIR", "").strip()
    if not raw:
        return None
    directory = Path(raw).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


def _checkpoint_path(sport_key: str, date_iso: str) -> Path | None:
    directory = _checkpoint_dir()
    if directory is None:
        return None
    return directory / f"scores24-{sport_key}-{date_iso}.json"


def _load_checkpoint(
    sport_key: str,
    date_iso: str,
    expected: list[dict[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return same-day picks already resolved by an earlier run.

    Scores24 blocks tend to hit late-slate matchups after the request budget
    is spent, so partial progress must survive across publisher runs instead
    of every retry starting from zero. Entries whose matchup is no longer on
    the official slate are dropped. Enabled only when SCORES24_CHECKPOINT_DIR
    is set (the local publisher sets it).
    """
    path = _checkpoint_path(sport_key, date_iso)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("date") != date_iso
        or payload.get("sport") != sport_key
    ):
        return {}
    expected_keys: set[tuple[str, str]] = set()
    for matchup in expected:
        key = _matchup_key(matchup.get("away", ""), matchup.get("home", ""))
        if key:
            expected_keys.add(key)
    resolved: dict[tuple[str, str], dict[str, Any]] = {}
    rows = payload.get("picks") if isinstance(payload.get("picks"), list) else []
    for row in rows:
        if not isinstance(row, dict) or not row.get("pick") or not row.get("source"):
            continue
        key = _matchup_key(row.get("away_team", ""), row.get("home_team", ""))
        if key and key in expected_keys:
            resolved.setdefault(key, row)
    return resolved


def _save_checkpoint(sport_key: str, date_iso: str, picks: list[dict[str, Any]]) -> None:
    path = _checkpoint_path(sport_key, date_iso)
    if path is None:
        return
    try:
        staged = path.with_name(path.name + ".tmp")
        staged.write_text(
            json.dumps(
                {
                    "sport": sport_key,
                    "date": date_iso,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "picks": picks,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        staged.replace(path)
    except OSError:
        return
    try:
        cutoff = time.time() - 3 * 24 * 3600
        for stale in path.parent.glob("scores24-*.json"):
            if stale.name != path.name and stale.stat().st_mtime < cutoff:
                stale.unlink()
    except OSError:
        pass


def _historical_url_hints(sport_key: str, date_iso: str, matchup: dict[str, str]) -> list[str]:
    """Derive exact prediction URLs from recently committed Scores24 picks.

    Detail slugs (team spelling, home/away order, and the URL date's offset
    from the slate date) are stable across days, so a matchup's most recent
    published source_url beats blind slug guessing — Scores24 challenges
    wrong-date guesses instead of returning 404. Enabled only when
    SCORES24_CHECKPOINT_DIR is set (the local publisher sets it).
    """
    if not os.environ.get("SCORES24_CHECKPOINT_DIR", "").strip():
        return []
    key = _matchup_key(matchup.get("away", ""), matchup.get("home", ""))
    if not key:
        return []
    config = SPORT_CONFIG[sport_key]
    feed_key = f"scores24_{sport_key}"
    try:
        base_date = _parse_target_date(date_iso)
    except ValueError:
        return []
    url_parts: tuple[str, str, str] | None = None
    url_date: date | None = None
    history_day: date | None = None
    for offset in range(1, 15):
        day = base_date - timedelta(days=offset)
        path = MODEL_CACHE_DIR / f"{day.isoformat()}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        feeds = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
        bucket = feeds.get(feed_key) if isinstance(feeds.get(feed_key), dict) else {}
        rows = bucket.get("picks") if isinstance(bucket.get("picks"), list) else []
        for row in rows:
            if not isinstance(row, dict) or row.get("source") != config["source"]:
                continue
            if _matchup_key(row.get("away_team", ""), row.get("home_team", "")) != key:
                continue
            match = re.search(r"^(.*/m-)(\d{2}-\d{2}-\d{4})-(.+)$", _norm_space(row.get("source_url")))
            if not match:
                continue
            url_parts = (match.group(1), match.group(2), match.group(3))
            try:
                url_date = datetime.strptime(match.group(2), "%d-%m-%Y").date()
            except ValueError:
                url_date = None
            history_day = day
            break
        if url_parts:
            break
    if not url_parts:
        return []
    prefix, _, tail = url_parts
    day_candidates: list[date] = []
    if url_date is not None and history_day is not None:
        day_candidates.append(base_date + (url_date - history_day))
    day_candidates.extend(
        [base_date, base_date - timedelta(days=1), base_date + timedelta(days=1)]
    )
    return list(
        dict.fromkeys(
            f"{prefix}{candidate_day.strftime('%d-%m-%Y')}-{tail}"
            for candidate_day in day_candidates
        )
    )


def _looks_blocked(status: int, html: str) -> bool:
    if status in {403, 429}:
        return True
    blob = (html or "")[:12000].lower()
    return any(signal in blob for signal in CLOUDFLARE_SIGNALS)


class Scores24Client:
    """Paced requests client with a lazy headless-Playwright fallback."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        interval_seconds: float | None = None,
        browser_fallback: bool | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.interval_seconds = (
            _env_float("SCORES24_REQUEST_INTERVAL_SECONDS", 2.0)
            if interval_seconds is None
            else max(0.0, interval_seconds)
        )
        self.browser_fallback = (
            _env_flag("SCORES24_BROWSER_FALLBACK", True)
            if browser_fallback is None
            else browser_fallback
        )
        self._last_request_at = 0.0
        self._pw = None
        self._browser = None
        self._context = None
        self._curl_session = None
        self._curl_request_count = 0
        self._camoufox_manager = None
        self._camoufox_context = None
        self._camoufox_failed = False
        self._camoufox_block_failures = 0
        self._prefer_camoufox = _env_flag("SCORES24_CAMOUFOX_FALLBACK", True)
        self._browser_failed = False
        self._blocked_until = 0.0

    def __enter__(self) -> Scores24Client:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._curl_session is not None:
            try:
                self._curl_session.close()
            except Exception:
                pass
        if self._camoufox_context is not None:
            try:
                self._camoufox_context.close()
            except Exception:
                pass
        if self._camoufox_manager is not None:
            try:
                self._camoufox_manager.__exit__(None, None, None)
            except Exception:
                pass
        for resource in (self._context, self._browser, self._pw):
            if resource is None:
                continue
            try:
                resource.close() if resource is not self._pw else resource.stop()
            except Exception:
                pass
        self._context = self._browser = self._pw = None
        self._curl_session = None
        self._curl_request_count = 0
        self._camoufox_manager = None
        self._camoufox_context = None

    def _pace(self) -> None:
        remaining = self.interval_seconds - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _browser_html(self, url: str) -> tuple[str, int]:
        if not self.browser_fallback or self._browser_failed:
            return "", 0
        try:
            from playwright.sync_api import sync_playwright

            if self._pw is None:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                self._context = self._browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="en-US",
                    timezone_id="America/Chicago",
                    no_viewport=True,
                )
                self._context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )
            page = self._context.new_page()
            try:
                response = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                html = page.content()
                status = response.status if response else 0
                return html, status
            finally:
                page.close()
        except Exception:
            self._browser_failed = True
            return "", 0

    def _camoufox_html(self, url: str) -> tuple[str, int]:
        if not _env_flag("SCORES24_CAMOUFOX_FALLBACK", True) or self._camoufox_failed:
            return "", 0
        try:
            from camoufox.sync_api import Camoufox

            if self._camoufox_manager is None:
                launch_options: dict[str, Any] = {
                    "headless": True,
                    "humanize": True,
                }
                proxy_server = os.environ.get("PLAYWRIGHT_PROXY_SERVER", "").strip()
                if proxy_server:
                    launch_options["proxy"] = {"server": proxy_server}
                profile_dir = os.environ.get("SCORES24_CAMOUFOX_PROFILE_DIR", "").strip()
                if profile_dir:
                    # A persistent profile lets one cleared challenge cover the
                    # rest of the slate and same-day reruns instead of every
                    # fresh launch facing the challenge again.
                    try:
                        profile_path = Path(profile_dir).expanduser()
                        profile_path.mkdir(parents=True, exist_ok=True)
                        self._camoufox_manager = Camoufox(
                            persistent_context=True,
                            user_data_dir=str(profile_path),
                            **launch_options,
                        )
                        self._camoufox_context = self._camoufox_manager.__enter__()
                    except Exception:
                        if self._camoufox_manager is not None:
                            try:
                                self._camoufox_manager.__exit__(None, None, None)
                            except Exception:
                                pass
                        self._camoufox_manager = None
                        self._camoufox_context = None
                if self._camoufox_manager is None:
                    self._camoufox_manager = Camoufox(**launch_options)
                    browser = self._camoufox_manager.__enter__()
                    self._camoufox_context = browser.new_context(
                        locale="en-US",
                        timezone_id="America/Chicago",
                        no_viewport=True,
                    )
            page = self._camoufox_context.new_page()
            try:
                response = page.goto(url, timeout=90000, wait_until="domcontentloaded")
                status = response.status if response else 0
                html = ""
                challenge_waits = int(_env_float("SCORES24_CAMOUFOX_CHALLENGE_WAITS", 24, 1))
                for attempt in range(challenge_waits):
                    page.wait_for_timeout(5000)
                    html = page.content()
                    title = _norm_space(page.title()).lower()
                    if status == 200 and not _looks_blocked(status, html) and "just a moment" not in title:
                        return html, status
                    if attempt < challenge_waits - 1 and attempt % 4 == 3:
                        response = page.reload(timeout=90000, wait_until="domcontentloaded")
                        status = response.status if response else status
                return html, status
            finally:
                page.close()
        except Exception:
            self._camoufox_failed = True
            return "", 0

    def _impersonated_html(self, url: str) -> tuple[str, int]:
        try:
            from curl_cffi import requests as curl_requests

            max_requests = int(_env_float("SCORES24_CURL_SESSION_MAX_REQUESTS", 4, 1))
            if self._curl_session is None or self._curl_request_count >= max_requests:
                if self._curl_session is not None:
                    self._curl_session.close()
                self._curl_session = curl_requests.Session(impersonate="chrome")
                self._curl_request_count = 0
            response = self._curl_session.get(url, headers=HEADERS, timeout=35)
            self._curl_request_count += 1
            return response.text, response.status_code
        except Exception:
            return "", 0

    def get_html(self, url: str, attempts: int | None = None) -> tuple[str, int, bool]:
        max_attempts = (
            int(_env_float("SCORES24_REQUEST_ATTEMPTS", 3, 1))
            if attempts is None
            else max(1, attempts)
        )
        attempt_retry_delay = _env_float("SCORES24_ATTEMPT_RETRY_DELAY_SECONDS", 1.0)
        if self._prefer_camoufox:
            self._pace()
            camoufox_html, camoufox_status = self._camoufox_html(url)
            if camoufox_status == 200 and not _looks_blocked(camoufox_status, camoufox_html):
                return camoufox_html, camoufox_status, False
            self._prefer_camoufox = False
        if time.monotonic() < self._blocked_until:
            return "", 429, True
        last_html = ""
        last_status = 0
        blocked = False
        for attempt in range(max_attempts):
            self._pace()
            last_html, last_status = self._impersonated_html(url)
            if not last_status:
                try:
                    response = self.session.get(url, timeout=35)
                    last_html = response.text
                    last_status = response.status_code
                except requests.RequestException:
                    last_html = ""
                    last_status = 0
            blocked = _looks_blocked(last_status, last_html)
            if last_status == 200 and not blocked:
                self._blocked_until = 0.0
                return last_html, last_status, False
            if last_status == 404:
                return last_html, last_status, False
            if attempt + 1 < max_attempts:
                sleep_seconds = (4.0 if blocked else 2.0) * (attempt + 1) * attempt_retry_delay
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

        if blocked:
            camoufox_html, camoufox_status = self._camoufox_html(url)
            if camoufox_status == 200 and not _looks_blocked(camoufox_status, camoufox_html):
                self._prefer_camoufox = True
                self._blocked_until = 0.0
                return camoufox_html, camoufox_status, False
            # One challenged page must not permanently kill the transport for
            # the rest of the slate: the browser can still clear challenges on
            # other URLs, so only repeated block failures disable it.
            self._camoufox_block_failures += 1
            if self._camoufox_block_failures >= int(
                _env_float("SCORES24_CAMOUFOX_BLOCK_TOLERANCE", 2, 1)
            ):
                self._camoufox_failed = True
            browser_html, browser_status = self._browser_html(url)
            if browser_status == 200 and not _looks_blocked(browser_status, browser_html):
                self._blocked_until = 0.0
                return browser_html, browser_status, False
            self._browser_failed = True
            if self._curl_session is not None:
                try:
                    self._curl_session.close()
                except Exception:
                    pass
            self._curl_session = None
            self._curl_request_count = 0
            self._blocked_until = time.monotonic() + _env_float("SCORES24_HOST_BLOCK_COOLDOWN_SECONDS", 8.0)
        return last_html, last_status, blocked


def extract_listing_links(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = _norm_space(anchor.get("href"))
        if "/m-" not in href or "prediction" not in href:
            continue
        url = urljoin(BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "text": _norm_space(anchor.get_text(" ", strip=True))})
    return out


def _decimal_odds_to_american(value: float) -> int | None:
    if value <= 1.0:
        return None
    if value >= 2.0:
        return int(round((value - 1.0) * 100))
    return int(round(-100.0 / (value - 1.0)))


def _scores24_line_token(token: str) -> str:
    """Scores24 encodes 9.5 as 9_5; historical tips keep the European comma."""
    cleaned = str(token or "").strip().strip("\\")
    if re.fullmatch(r"\d+_\d+", cleaned):
        return cleaned.replace("_", ",")
    if re.fullmatch(r"\d+", cleaned):
        return cleaned
    return cleaned.replace("_", ",")


def _tip_from_prediction_codes(
    market: str,
    selection: str,
    matchup: dict[str, str] | None,
) -> str:
    market_key = str(market or "").strip().strip("\\").lower()
    selection_key = str(selection or "").strip().strip("\\")
    if market_key == "one_two":
        if not matchup:
            return ""
        if selection_key == "w1":
            return f"{matchup['home']} Win"
        if selection_key == "w2":
            return f"{matchup['away']} Win"
        return ""
    if market_key == "total_over":
        return f"Total Over ({_scores24_line_token(selection_key)})"
    if market_key == "total_under":
        return f"Total Under ({_scores24_line_token(selection_key)})"
    team_total = re.fullmatch(r"total_t([12])_(over|under)", market_key)
    if team_total:
        if not matchup:
            return ""
        team = matchup["home"] if team_total.group(1) == "1" else matchup["away"]
        return (
            f"{team} Total {team_total.group(2).title()} "
            f"({_scores24_line_token(selection_key)})"
        )
    numbered_handicap = re.fullmatch(r"handicap([12])", market_key)
    if numbered_handicap:
        if not matchup:
            return ""
        team = matchup["home"] if numbered_handicap.group(1) == "1" else matchup["away"]
        line = _scores24_line_token(selection_key)
        if line and not line.startswith(("+", "-")):
            line = f"+{line}"
        return f"{team} Handicap ({line})"
    if market_key in {"handicap", "european_handicap", "ah"} or market_key.startswith("handicap"):
        if not matchup:
            return ""
        line = _scores24_line_token(selection_key)
        # h1_+1_5 / h2_-1_5 / +1_5 with side inferred from leading h1/h2.
        side_match = re.fullmatch(r"h([12])[_]?([+-]?\d+(?:_\d+)?)", selection_key, re.IGNORECASE)
        if side_match:
            team = matchup["home"] if side_match.group(1) == "1" else matchup["away"]
            line = _scores24_line_token(side_match.group(2))
            if not line.startswith(("+", "-")):
                line = f"+{line}"
            return f"{team} Handicap ({line})"
        signed = re.fullmatch(r"([+-]?\d+(?:_\d+)?)", selection_key)
        if signed and matchup:
            # Ambiguous side — prefer home (W1) only when the token is a bare line.
            line = _scores24_line_token(signed.group(1))
            if not line.startswith(("+", "-")):
                line = f"+{line}"
            return f"{matchup['home']} Handicap ({line})"
    return ""


def _american_odds_from_w1_w2_header(html: str, selection: str) -> int | None:
    text = _norm_space(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True))
    match = re.search(r"\bW1\s+([+-]\d+)\s+W2\s+([+-]\d+)\b", text)
    if not match:
        return None
    if selection == "w1":
        return int(match.group(1))
    if selection == "w2":
        return int(match.group(2))
    return None


def _extract_structured_prediction(
    html: str,
    matchup: dict[str, str] | None = None,
) -> tuple[str, int | None]:
    """Parse Scores24's post-2026-08 editorial payload (prediction + predictionValue).

    The visible "Our choice … at odds of …" cell was removed site-wide; tips now
    live in embedded JSON as ["one_two","w1"] / ["total_over","9_5"] /
    ["total_t1_under","88_5"] plus a decimal predictionValue.
    """
    normalized = (html or "").replace('\\"', '"')
    match = re.search(
        r'"prediction"\s*:\s*\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]\s*,\s*"predictionValue"\s*:\s*"([^"]+)"',
        normalized,
    )
    if not match:
        return "", None
    market, selection, raw_value = match.group(1), match.group(2), match.group(3)
    tip = _tip_from_prediction_codes(market, selection, matchup)
    if not tip:
        return "", None
    odds = None
    if str(market).strip().strip("\\").lower() == "one_two":
        odds = _american_odds_from_w1_w2_header(html, str(selection).strip().strip("\\").lower())
    if odds is None:
        try:
            odds = _decimal_odds_to_american(float(raw_value))
        except ValueError:
            odds = None
    return tip, odds


def extract_our_choice(
    html: str,
    matchup: dict[str, str] | None = None,
) -> tuple[str, int | None]:
    soup = BeautifulSoup(html or "", "html.parser")
    label = soup.find(string=lambda value: value and _norm_space(value).lower() == "our choice")
    candidates: list[str] = []
    if label:
        parent = label.parent
        for _ in range(5):
            if parent is None:
                break
            text = _norm_space(parent.get_text(" ", strip=True))
            if "at odds of" in text.lower():
                candidates.append(text)
            parent = parent.parent
    candidates.append(_norm_space(soup.get_text(" ", strip=True)))

    for text in candidates:
        match = re.search(
            r"Our choice\s+(.+?)\s+at odds of\s+([+-]?\d+(?:\.\d+)?)\*?",
            text,
            re.IGNORECASE,
        )
        if not match:
            continue
        tip = _norm_space(match.group(1)).rstrip(" .:")
        try:
            odds = int(float(match.group(2)))
        except ValueError:
            odds = None
        if tip:
            return tip, odds
    return _extract_structured_prediction(html, matchup=matchup)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _team_slug_variants(team: str, sport: str) -> list[str]:
    labels = [team, *TEAM_SLUG_ALIASES.get(team, ())]
    if sport == "wnba":
        labels.extend(f"{label} W" for label in list(labels))
    if sport == "cfb":
        # ESPN uses "Ohio State Buckeyes"; Scores24 often keeps the mascot in
        # the slug but sometimes drops it. Keep both.
        for label in list(labels):
            tokens = [token for token in str(label).split() if token]
            if len(tokens) >= 2:
                labels.append(" ".join(tokens[:-1]))
    return list(dict.fromkeys(_slugify(label) for label in labels if _slugify(label)))


def candidate_prediction_urls(sport: str, target_date: str, matchup: dict[str, str]) -> list[str]:
    config = SPORT_CONFIG[sport]
    base_date = _parse_target_date(target_date)
    date_candidates = [base_date, base_date + timedelta(days=1), base_date - timedelta(days=1)]
    home_slugs = _team_slug_variants(matchup["home"], sport)
    away_slugs = _team_slug_variants(matchup["away"], sport)
    urls: list[str] = []
    orders = (
        [(home_slug, away_slug) for home_slug in home_slugs for away_slug in away_slugs],
        [(away_slug, home_slug) for home_slug in home_slugs for away_slug in away_slugs],
    )
    for ordered_pairs in orders:
        for first, second in ordered_pairs:
            for day in date_candidates:
                date_slug = day.strftime("%d-%m-%Y")
                root = f"{BASE_URL}/en/{config['scores24_sport']}/m-{date_slug}-{first}-{second}"
                urls.append(f"{root}-prediction")
                if sport == "wnba":
                    urls.append(f"{root}--prediction")
    return list(dict.fromkeys(urls))


def _clean_pick(tip: str, matchup: dict[str, str]) -> str:
    compact = re.sub(r"\s*\(inc\.?\s*OT\)\s*", "", _norm_space(tip), flags=re.IGNORECASE)
    compact = compact.rstrip(" .:")
    market = compact
    total = re.fullmatch(
        r"(?:Total(?:\s+(?:points|runs|goals))?|Total points)\s+(Over|Under)\s*\((\d+(?:\.\d+)?)\)",
        compact,
        re.IGNORECASE,
    )
    if total:
        market = f"{total.group(1).title()} {total.group(2)}"
    else:
        winner = re.fullmatch(r"(.+?)\s+Win", compact, re.IGNORECASE)
        handicap = re.fullmatch(r"(.+?)\s+Handicap\s*\(([+-]?\d+(?:\.\d+)?)\)", compact, re.IGNORECASE)
        if winner:
            market = f"{_norm_space(winner.group(1))} ML"
        elif handicap:
            market = f"{_norm_space(handicap.group(1))} {handicap.group(2)}"
    return f"{market} ({matchup['away']} @ {matchup['home']})"


def _team_market_selection(pick: str) -> str:
    selection = re.sub(
        r"\s+\([^()]*(?:@|vs\.?)\s+[^()]*\)\s*$",
        "",
        str(pick or "").strip(),
        flags=re.IGNORECASE,
    ).strip()
    return re.sub(r"(?<=\d),(?=\d)", ".", selection)


def _soccer_market_metadata(pick: str) -> dict[str, Any]:
    selection = _team_market_selection(pick)
    lower = selection.lower()
    named_handicap = re.fullmatch(
        r".+?\s+(?:asian\s+)?(?:hcp|handicap)\s*\(\s*([+-]?\d+(?:\.\d+)?)\s*\)",
        selection,
        flags=re.IGNORECASE,
    )
    asian = re.search(r"\basian\s+(?:hcp|handicap)\s*([+-]?\d+(?:\.\d+)?)", lower)
    if named_handicap or asian:
        line_match = named_handicap or asian
        return {
            "market_type": "soccer_asian_handicap",
            "line": float(line_match.group(1)),
            "grade_supported": False,
        }
    spread = re.fullmatch(r".+?\s+([+-]\d+(?:\.\d+)?)", selection)
    if spread:
        line = float(spread.group(1))
        quarter_line = abs((line * 4) - round(line * 4)) < 1e-9 and abs((line * 2) - round(line * 2)) > 1e-9
        return {"market_type": "soccer_handicap", "line": line, "grade_supported": not quarter_line}
    if re.fullmatch(r"(?:over|under)\s+\d+(?:\.\d+)?", lower):
        return {"market_type": "soccer_total", "grade_supported": True}
    if re.fullmatch(r".+?\s+(?:ml|moneyline|to win|wins?)", lower):
        return {"market_type": "soccer_moneyline", "grade_supported": True}
    if re.fullmatch(r"draw|btts\s+(?:yes|no)", lower):
        return {"market_type": "soccer_standard", "grade_supported": True}
    return {"market_type": "soccer_specialty", "grade_supported": False}


def _player_market_metadata(pick: str) -> dict[str, Any] | None:
    selection = pick.split("(", 1)[0].strip()
    supported = any(
        re.search(pattern, selection, flags=re.IGNORECASE)
        for pattern in (
            r"^.+?\s+(?:(?:over|under)\s+\d+(?:\.\d+)?\s+|\d+(?:\.\d+)?\+\s+)"
            r"(?:points|rebounds|assists|hits|strikeouts)\b",
            r"^.+?\s+(?:points|rebounds|assists|hits|strikeouts)\s+(?:over|under)\s+\d+(?:\.\d+)?\b",
        )
    )
    looks_like_player_market = supported or bool(
        re.search(
            r"\b\d+(?:\.\d+)?\+\s+(?:shots?(?:\s+on\s+target)?|goals?|cards?)\b",
            selection,
            flags=re.IGNORECASE,
        )
    )
    if not looks_like_player_market:
        return None
    return {
        "scope": "player",
        "market_type": "external_player_prop",
        "grade_supported": supported,
    }


def _external_market_metadata(sport: str, pick: str) -> dict[str, Any]:
    if player_metadata := _player_market_metadata(pick):
        return player_metadata
    selection = pick.split("(", 1)[0].strip()
    if re.search(r"\b(?:and|&)\b", selection, flags=re.IGNORECASE):
        return {"market_type": "compound", "grade_supported": False}
    if sport == "FIFA WC":
        return _soccer_market_metadata(pick)
    return {}


def _matching_listing_urls(links: list[dict[str, str]], matchup: dict[str, str]) -> list[str]:
    return [
        link["url"]
        for link in links
        if _matchup_matches_blob(matchup, f"{link.get('text', '')} {link.get('url', '').replace('-', ' ')}")
    ]


def _pick_payload(
    config: dict[str, Any],
    date_iso: str,
    matchup: dict[str, str],
    source_url: str,
    tip: str,
    odds: int | None,
) -> dict[str, Any]:
    matchup_label = f"{matchup['away']} @ {matchup['home']}"
    payload = {
        "source": config["source"],
        "pick": _clean_pick(tip, matchup),
        "tip": tip,
        "sport": config["label"],
        "odds": odds,
        "units": 1,
        "probability": None,
        "edge": None,
        "decision": "BET",
        "date": date_iso,
        "matchup": matchup_label,
        "game": matchup_label,
        "away_team": matchup["away"],
        "home_team": matchup["home"],
        "start_time": matchup.get("start_time") or None,
        "source_url": source_url,
    }
    payload.update(_external_market_metadata(config["label"], payload["pick"]))
    if config["label"] == "FIFA WC":
        payload["calibration_excluded"] = True
    return payload


def scrape_scores24(
    sport: str,
    date_iso: str,
    *,
    client: Scores24Client | None = None,
    matchups: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    sport_key = sport.strip().lower()
    if sport_key not in SPORT_CONFIG:
        raise ValueError(f"unsupported Scores24 sport: {sport}")
    _parse_target_date(date_iso)
    config = SPORT_CONFIG[sport_key]
    if matchups is not None:
        expected = matchups
        slate_resolved = True
    else:
        expected, slate_resolved = fetch_daily_matchups(sport_key, date_iso)
    if not expected:
        if not slate_resolved:
            return {
                "ok": False,
                "date": date_iso,
                "picks": [],
                "error": f"{config['source']} could not resolve an official {date_iso} slate",
            }
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
                "blockRetryRounds": 0,
                "checkpointedPicks": 0,
            },
        }

    owns_client = client is None
    scores_client = client or Scores24Client()
    blocked_urls: list[str] = []
    blocked_matchups: set[tuple[str, str]] = set()
    block_retry_rounds = 0
    attempted_urls = 0
    listing_links: list[dict[str, str]] = []
    listing_resolved = False
    listing_urls_attempted = 0
    listed_matchup_keys: set[tuple[str, str]] = set()
    detail_matchup_keys: set[tuple[str, str]] = set()
    checkpointed = _load_checkpoint(sport_key, date_iso, expected)
    picks: list[dict[str, Any]] = list(checkpointed.values())
    remaining = [
        matchup
        for matchup in expected
        if _matchup_key(matchup["away"], matchup["home"]) not in checkpointed
    ]
    unresolved: list[tuple[dict[str, str], list[str]]] = []
    try:
        if remaining:
            configured_listing_urls = config.get("listing_urls") or (config["listing_url"],)
            seen_listing_links: set[str] = set()
            for listing_url in dict.fromkeys(configured_listing_urls):
                listing_urls_attempted += 1
                listing_html, listing_status, listing_blocked = scores_client.get_html(listing_url)
                if listing_blocked:
                    blocked_urls.append(listing_url)
                    continue
                if listing_status != 200:
                    continue
                listing_resolved = True
                for link in extract_listing_links(listing_html):
                    if link["url"] in seen_listing_links:
                        continue
                    seen_listing_links.add(link["url"])
                    listing_links.append(link)
                # Keep walking listing_urls: CFB's NCAA page and the sport-wide
                # American Football pages cover complementary days. A first
                # non-empty listing must not hide later tips.

            max_candidates = int(_env_float("SCORES24_MAX_CANDIDATES_PER_MATCHUP", 36, 1))

            def resolve_candidates(
                matchup: dict[str, str],
                candidates: list[str],
                candidate_limit: int,
            ) -> dict[str, Any] | None:
                nonlocal attempted_urls
                for url in candidates[:candidate_limit]:
                    attempted_urls += 1
                    html, status, blocked = scores_client.get_html(url)
                    if blocked:
                        blocked_urls.append(url)
                        key = _matchup_key(matchup["away"], matchup["home"])
                        if key:
                            blocked_matchups.add(key)
                        # Scores24 can challenge a nonexistent date/order variant
                        # instead of returning 404. Move that candidate behind the
                        # untried variants so the next cooled-down retry progresses
                        # through the official matchup's alternate URL dates/orders.
                        candidates.remove(url)
                        candidates.append(url)
                        break
                    if status != 200:
                        continue
                    if not _matchup_matches_blob(matchup, f"{url.replace('-', ' ')} {_norm_space(BeautifulSoup(html, 'html.parser').title)}"):
                        continue
                    key = _matchup_key(matchup["away"], matchup["home"])
                    if key:
                        detail_matchup_keys.add(key)
                    tip, odds = extract_our_choice(html, matchup=matchup)
                    if not tip:
                        continue
                    if key:
                        blocked_matchups.discard(key)
                    return _pick_payload(config, date_iso, matchup, url, tip, odds)
                return None

            listed_queue: list[tuple[dict[str, str], list[str]]] = []
            unlisted_queue: list[tuple[dict[str, str], list[str]]] = []
            for matchup in remaining:
                listing_urls = _matching_listing_urls(listing_links, matchup)
                matchup_key = _matchup_key(matchup["away"], matchup["home"])
                if listing_urls and matchup_key:
                    listed_matchup_keys.add(matchup_key)
                candidates = list(
                    dict.fromkeys(
                        [
                            *listing_urls,
                            *_historical_url_hints(sport_key, date_iso, matchup),
                            *candidate_prediction_urls(sport_key, date_iso, matchup),
                        ]
                    )
                )
                # Matchups with listed detail links are near-certain
                # single-request wins; resolve them before URL guessing so a
                # mid-run block leaves the checkpoint holding as much of the
                # slate as possible.
                (listed_queue if listing_urls else unlisted_queue).append((matchup, candidates))

            for matchup, candidates in [*listed_queue, *unlisted_queue]:
                pick = resolve_candidates(matchup, candidates, max_candidates)
                if not pick:
                    unresolved.append((matchup, candidates))
                    continue
                picks.append(pick)
                _save_checkpoint(sport_key, date_iso, picks)

            max_retry_rounds = int(_env_float("SCORES24_BLOCK_RETRY_ROUNDS", 3, 0))
            retry_delay = _env_float("SCORES24_BLOCK_RETRY_DELAY_SECONDS", 45.0)
            while unresolved and block_retry_rounds < max_retry_rounds:
                unresolved_blocked = any(
                    _matchup_key(matchup["away"], matchup["home"]) in blocked_matchups
                    for matchup, _ in unresolved
                )
                if not unresolved_blocked:
                    break
                block_retry_rounds += 1
                time.sleep(retry_delay)
                if owns_client:
                    # A blocked Camoufox/Playwright transport is intentionally marked
                    # failed for the rest of its client lifetime. Reusing that client
                    # makes every retry fall back to the same already-blocked HTTP
                    # path, so late-slate matchups can never recover. Start a fresh
                    # paced transport after the cooldown and retry only unresolved
                    # matchups.
                    scores_client.close()
                    scores_client = Scores24Client()
                still_unresolved: list[tuple[dict[str, str], list[str]]] = []
                for matchup, candidates in unresolved:
                    pick = resolve_candidates(matchup, candidates, min(max_candidates, 6))
                    if pick:
                        picks.append(pick)
                        _save_checkpoint(sport_key, date_iso, picks)
                    else:
                        still_unresolved.append((matchup, candidates))
                unresolved = still_unresolved
    finally:
        if owns_client:
            scores_client.close()

    unresolved_matchups = [f"{matchup['away']} @ {matchup['home']}" for matchup, _ in unresolved]
    blocked_missing = [
        f"{matchup['away']} @ {matchup['home']}"
        for matchup, _ in unresolved
        if _matchup_key(matchup["away"], matchup["home"]) in blocked_matchups
    ]
    if blocked_missing:
        return {
            "ok": False,
            "date": date_iso,
            "picks": picks,
            "error": (
                f"{config['source']} was blocked before it could finish today's official matchups: "
                f"{', '.join(blocked_missing[:3])}"
            ),
            "meta": {
                "officialMatchups": len(expected),
                "expectedMatchups": len(expected),
                "matchedPicks": len(picks),
                "missingMatchups": unresolved_matchups,
                "unpublishedMatchups": [],
                "attemptedUrls": attempted_urls,
                "blockedUrls": len(set(blocked_urls)),
                "blockRetryRounds": block_retry_rounds,
                "checkpointedPicks": len(checkpointed),
                "listingResolved": listing_resolved,
                "listingUrlsAttempted": listing_urls_attempted,
            },
        }
    unverifiable_missing = [
        f"{matchup['away']} @ {matchup['home']}"
        for matchup, _ in unresolved
        if (
            not listing_resolved
            or _matchup_key(matchup["away"], matchup["home"]) in listed_matchup_keys
            or _matchup_key(matchup["away"], matchup["home"]) in detail_matchup_keys
        )
    ]
    if unverifiable_missing:
        reason = (
            "could not reach a Scores24 editorial listing"
            if not listing_resolved
            else "found matchup prediction page(s) without a parseable editorial choice"
        )
        return {
            "ok": False,
            "date": date_iso,
            "picks": picks,
            "error": (
                f"{config['source']} {reason}: "
                f"{', '.join(unverifiable_missing[:3])}"
            ),
            "meta": {
                "officialMatchups": len(expected),
                "expectedMatchups": len(expected),
                "matchedPicks": len(picks),
                "missingMatchups": unverifiable_missing,
                "unpublishedMatchups": [
                    matchup
                    for matchup in unresolved_matchups
                    if matchup not in unverifiable_missing
                ],
                "attemptedUrls": attempted_urls,
                "blockedUrls": len(set(blocked_urls)),
                "blockRetryRounds": block_retry_rounds,
                "checkpointedPicks": len(checkpointed),
                "listingResolved": listing_resolved,
                "listingUrlsAttempted": listing_urls_attempted,
            },
        }
    return {
        "ok": True,
        "date": date_iso,
        "picks": picks,
        "note": (
            f"{config['source']} matched {len(picks)} published editorial choice(s) "
            f"against {len(expected)} official {date_iso} matchup(s)."
        ),
        "meta": {
            "officialMatchups": len(expected),
            "expectedMatchups": len(picks),
            "matchedPicks": len(picks),
            "missingMatchups": [],
            "unpublishedMatchups": unresolved_matchups,
            "attemptedUrls": attempted_urls,
            "blockedUrls": len(set(blocked_urls)),
            "blockRetryRounds": block_retry_rounds,
            "listingLinks": len(listing_links),
            "listingResolved": listing_resolved,
            "listingUrlsAttempted": listing_urls_attempted,
            "checkpointedPicks": len(checkpointed),
        },
    }


def run_scores24_wnba(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("wnba", date_iso)


def run_scores24_nba_summer(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("nba_summer", date_iso)


def run_scores24_mlb(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("mlb", date_iso)


def run_scores24_fifa_world_cup(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("fifa_world_cup", date_iso)


def run_scores24_cfb(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("cfb", date_iso)


def run_scores24_nfl(date_iso: str, _sports: list[str] | None = None) -> dict[str, Any]:
    return scrape_scores24("nfl", date_iso)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape Scores24 editorial choices by official matchup.")
    parser.add_argument("--sport", required=True, choices=sorted(SPORT_CONFIG))
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    result = scrape_scores24(args.sport, args.date)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
