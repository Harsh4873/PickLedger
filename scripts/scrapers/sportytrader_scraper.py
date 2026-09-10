#!/usr/bin/env python3
"""
SportyTrader Scraper
====================
    Scrapes NBA, NBA Summer League, WNBA, MLB, FIFA World Cup, CFB, and NFL picks from
SportyTrader and prints structured pick blocks for the backend parser.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta


def _default_playwright_browsers_path() -> str:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured:
        return configured
    darwin_cache = os.path.expanduser("~/Library/Caches/ms-playwright")
    if sys.platform == "darwin" and os.path.isdir(darwin_cache):
        return darwin_cache
    return ""


_playwright_browsers_path = _default_playwright_browsers_path()
if _playwright_browsers_path:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _playwright_browsers_path

from playwright.sync_api import TimeoutError as PwTimeout
from playwright.sync_api import sync_playwright

BASKETBALL_LISTING_URL = "https://www.sportytrader.com/en/betting-tips/basketball/"

SPORT_CONFIG = {
    "nba": {
        "aliases": {"nba", "basketball"},
        "league": "USA - NBA",
        "league_aliases": {"USA - NBA"},
        "title": "NBA",
        "url": "https://www.sportytrader.com/us/picks/basketball/usa/nba-306/",
    },
    "nba_summer": {
        "aliases": {"nba_summer", "nba_summer_league", "summer_league"},
        "league": "USA - NBA Summer League",
        # SportyTrader groups Summer League and WNBA editorial cards on its
        # current basketball listing. The official matchup whitelist below
        # keeps other competitions out of this bucket.
        "league_aliases": {
            "USA - NBA",
            "USA - NBA Summer League",
            "NBA Summer League",
            "Summer League",
        },
        "title": "NBA Summer League",
        "url": BASKETBALL_LISTING_URL,
    },
    "wnba": {
        "aliases": {"wnba"},
        "league": "USA - WNBA",
        "league_aliases": {"USA - WNBA"},
        "title": "WNBA",
        "url": "https://www.sportytrader.com/us/picks/basketball/usa/wnba-58202/",
    },
    "mlb": {
        "aliases": {"mlb", "baseball"},
        "league": "USA - MLB",
        "league_aliases": {"USA - MLB"},
        "title": "MLB",
        "url": "https://www.sportytrader.com/us/picks/baseball/usa/mlb-597/",
    },
    "fifa_world_cup": {
        "aliases": {"fifa", "fifa_world_cup", "football", "soccer", "world_cup"},
        "league": "World - World Cup",
        "league_aliases": {"World - World Cup"},
        "title": "FIFA World Cup",
        "url": "https://www.sportytrader.com/us/picks/soccer/world/world-cup-1811/",
    },
    "cfb": {
        "aliases": {"cfb", "ncaaf", "college_football", "ncaa"},
        "league": "USA - NCAA",
        "league_aliases": {
            "USA - NCAA",
            "USA - NCAAF",
            "NCAA",
            "NCAAF",
            "College Football",
            "NCAA Football",
            "NCAA College Football",
        },
        "title": "CFB",
        # NCAA-only listing (Cloudflare typically requires Playwright).
        # No numeric league id analogous to mlb-597 is published; NFL is nfl-598.
        "url": "https://www.sportytrader.com/us/picks/football/usa/ncaa/",
        "fallback_urls": (
            "https://www.sportytrader.com/en/betting-tips/american-football/usa/ncaa/",
            "https://www.sportytrader.com/en/betting-tips/american-football/",
        ),
        # Mixed American-football fallbacks may 403 independently of the NCAA
        # listing; CFB is optional at the provider runner, so one working page
        # is enough to publish a partial slate.
        "allow_partial_listings": True,
    },
    "nfl": {
        "aliases": {"nfl"},
        "league": "USA - NFL",
        "league_aliases": {
            "USA - NFL",
            "NFL",
        },
        "title": "NFL",
        # League page nfl-598 (US picks + EN betting-tips mirrors). Mixed
        # American-football fallbacks may 403 independently; NFL is optional
        # at the provider runner, so one working page is enough.
        "url": "https://www.sportytrader.com/us/picks/football/usa/nfl-598/",
        "fallback_urls": (
            "https://www.sportytrader.com/en/betting-tips/american-football/usa/nfl-598/",
            "https://www.sportytrader.com/en/betting-tips/american-football/",
        ),
        "allow_partial_listings": True,
    },
}

SPORT_ALIAS_MAP = {
    alias: key
    for key, cfg in SPORT_CONFIG.items()
    for alias in cfg["aliases"]
}

CLOUDFLARE_SIGNALS = (
    "just a moment",
    "performing security verification",
    "enable javascript and cookies to continue",
    "privacy pass",
    "cloudflare",
)

SPORTYTRADER_CARDS_JS = r"""
() => {
    const cards = Array.from(new Set([
        ...document.querySelectorAll('.pronostics-wrapper .card'),
        ...document.querySelectorAll('[data-navigation-url-value]'),
    ]));
    return cards.map((card) => {
        const text = (value) => (value || '').replace(/\s+/g, ' ').trim();
        const hrefFromCard = card.getAttribute('data-navigation-url-value') || '';
        const anchors = Array.from(card.querySelectorAll(
            'a[href*="/us/picks/"], a[href*="/en/betting-tips/"]'
        ));
        const pickAnchor = anchors.find((anchor) => /^(?:detail|picks?)$/i.test(text(anchor.textContent))) || anchors[0] || null;
        const href = pickAnchor
            ? pickAnchor.href
            : (hrefFromCard ? new URL(hrefFromCard, window.location.origin).href : window.location.href);

        const heading = Array.from(card.querySelectorAll('h1, h2, h3, h4, p, a'))
            .map((node) => text(node.textContent))
            .find((line) => /^.+?\s+vs\.?\s+.+?\s+prediction$/i.test(line)) || '';
        const headingMatch = heading.match(/^(.+?)\s+vs\.?\s+(.+?)\s+prediction$/i);
        const spanTeams = Array.from(card.querySelectorAll('span.font-semibold'))
            .map((node) => text(node.textContent))
            .filter(Boolean)
            .filter((team, index, values) => index === 0 || team !== values[index - 1]);
        const teams = headingMatch ? [headingMatch[1], headingMatch[2]] : spanTeams;
        const paragraphs = Array.from(card.querySelectorAll('p'))
            .map((node) => text(node.textContent))
            .filter(Boolean);
        const dateText = paragraphs.find((line) => (
            /\b\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4},\s+\d{1,2}:\d{2}\b/.test(line)
            || /\b[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}/.test(line)
        )) || '';
        const league = paragraphs.find((line) => /\b(?:NBA Summer League|Summer League|NBA|WNBA|MLB|World Cup|NCAAF|College Football|NCAA|NFL)\b/i.test(line)) || '';
        const tipNode = card.querySelector('.bg-gray-100 p.font-semibold');
        const lines = (card.innerText || '').split(/\n+/).map(text).filter(Boolean);
        const headingIndex = lines.findIndex((line) => line === heading);
        const textTip = headingIndex < 0 ? '' : (lines.slice(headingIndex + 1).find((line) => (
            !/^(?:detail|bet now!?|exclusive offer)$/i.test(line)
        )) || '');
        const tip = text(tipNode ? tipNode.textContent : textTip);

        let odds = '';
        for (const node of card.querySelectorAll('.bg-gray-100 span')) {
            const value = text(node.textContent);
            if (/^[+-]?\d+(?:\.\d+)?$/.test(value)) {
                const numericValue = Number(value);
                if (numericValue > 1 || numericValue <= -100) {
                    odds = value;
                    break;
                }
            }
        }

        return {
            datetime: dateText,
            league,
            home: teams[0] || '',
            away: teams[1] || '',
            tip,
            odds,
            href,
        };
    }).filter((row) => row.home && row.away && row.tip && row.href);
}
"""


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line or "").strip()


def _parse_target_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_english_datetime(text: str) -> datetime | None:
    compact = _normalize_line(text)
    for fmt in (
        "%d %b %Y, %H:%M",
        "%d %B %Y, %H:%M",
        "%b %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M %p",
    ):
        try:
            return datetime.strptime(compact, fmt)
        except ValueError:
            continue
    return None


def _matches_target_date(text: str, target_date: datetime | None) -> bool:
    if not target_date:
        return True
    parsed = _parse_english_datetime(text)
    if not parsed:
        return False
    if parsed.date() == target_date.date():
        return True

    # The legacy US competition pages can label late games after midnight in
    # their provider timezone. Only admit that narrow rollover; the current
    # day-first listing must match the requested Chicago slate date exactly.
    is_legacy_month_first = bool(re.match(r"^[A-Z][a-z]+\s+\d{1,2},", text))
    next_date = target_date.date() + timedelta(days=1)
    return is_legacy_month_first and parsed.date() == next_date and parsed.hour < 6


def _normalize_sport(raw: str) -> str:
    key = _normalize_line(raw).lower()
    if key in SPORT_ALIAS_MAP:
        return SPORT_ALIAS_MAP[key]
    return ""


def _looks_like_cloudflare_block(title: str, body_text: str) -> bool:
    blob = f"{title}\n{body_text}".lower()
    return any(signal in blob for signal in CLOUDFLARE_SIGNALS)

def _matchup_key(raw: str) -> tuple[str, str] | None:
    teams = re.split(r"\s+(?:vs\.?|@)\s+", _normalize_line(raw), maxsplit=1, flags=re.IGNORECASE)
    if len(teams) != 2:
        return None
    aliases = {"turkiye": "turkey"}
    normalized = []
    for team in teams:
        text = unicodedata.normalize("NFKD", team)
        text = "".join(char for char in text if not unicodedata.combining(char))
        key = re.sub(r"[^a-z0-9]+", "", text.lower())
        normalized.append(aliases.get(key, key))
    normalized.sort()
    return (normalized[0], normalized[1]) if all(normalized) else None


def _launch_browser(pw):
    launch_kwargs = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    preferred_channel = os.environ.get("SPORTYTRADER_BROWSER_CHANNEL", "chrome").strip()
    if preferred_channel:
        try:
            return pw.chromium.launch(channel=preferred_channel, **launch_kwargs)
        except Exception:
            pass
    return pw.chromium.launch(**launch_kwargs)


def _new_context(browser):
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1365, "height": 900},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script(
        """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
"""
    )
    return ctx


def _load_cards(page, url: str) -> tuple[list[dict[str, str]], str]:
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    last_title = ""
    last_text = ""
    for attempt in range(4):
        page.wait_for_timeout(3000 + (attempt * 700))
        last_title = page.title()
        last_text = page.evaluate("() => document.body?.innerText || ''")
        if not _looks_like_cloudflare_block(last_title, last_text):
            cards = page.evaluate(SPORTYTRADER_CARDS_JS)
            if isinstance(cards, list):
                return cards, last_text
        if attempt < 3:
            page.reload(timeout=45000, wait_until="domcontentloaded")
    return [], last_text


def _extract_text_cards(
    body_text: str,
    listing_url: str,
    expected_matchups: list[str],
) -> list[dict[str, str]]:
    """Extract editorial cards from the current listing's accessible text."""
    lines = [_normalize_line(line) for line in body_text.splitlines()]
    lines = [line for line in lines if line]
    expected_keys = {
        key
        for matchup in expected_matchups
        if (key := _matchup_key(matchup))
    }
    rows: list[dict[str, str]] = []

    for index, line in enumerate(lines):
        heading = re.fullmatch(
            r"(.+?)\s+vs\.?\s+(.+?)\s+Prediction",
            line,
            flags=re.IGNORECASE,
        )
        if not heading:
            continue
        home, away = (_normalize_line(value) for value in heading.groups())
        if _matchup_key(f"{home} vs {away}") not in expected_keys:
            continue

        tip = ""
        for candidate in lines[index + 1:index + 5]:
            if re.fullmatch(
                r"(?:Detail|BET NOW!?|Exclusive Offer)",
                candidate,
                flags=re.IGNORECASE,
            ):
                continue
            tip = candidate
            break
        if not tip or tip.lower().startswith("probability of "):
            continue

        preceding = lines[max(0, index - 16):index]
        clipped: list[str] = []
        for candidate in reversed(preceding):
            if re.fullmatch(
                r".+?\s+vs\.?\s+.+?\s+Prediction",
                candidate,
                flags=re.IGNORECASE,
            ):
                break
            clipped.append(candidate)
        preceding = list(reversed(clipped))
        date_text = next(
            (candidate for candidate in reversed(preceding) if _parse_english_datetime(candidate)),
            "",
        )
        league = next(
            (
                candidate
                for candidate in reversed(preceding)
                if re.search(
                    r"\b(?:NBA Summer League|Summer League|NBA|WNBA|MLB|World Cup|NCAAF|College Football|NCAA|NFL)\b",
                    candidate,
                    flags=re.IGNORECASE,
                )
            ),
            "",
        )
        if not date_text or not league:
            continue
        rows.append(
            {
                "datetime": date_text,
                "league": league,
                "home": home,
                "away": away,
                "tip": tip,
                "odds": "",
                "href": listing_url,
            }
        )

    return rows


def _extract_rows(
    cards: list[dict[str, str]],
    target_date: datetime | None,
    sport_key: str,
    expected_matchups: list[str] | None = None,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    sport_config = SPORT_CONFIG[sport_key]
    sport_league = sport_config["league"]
    league_aliases = sport_config.get("league_aliases", {sport_league})
    expected = {
        key: matchup
        for matchup in expected_matchups or []
        if (key := _matchup_key(matchup))
    }

    for raw in cards:
        row = {key: _normalize_line(str(raw.get(key, ""))) for key in ("datetime", "league", "home", "away", "tip", "odds", "href")}
        if row["league"] and row["league"] not in league_aliases:
            continue
        if not row["home"] or not row["away"] or not row["tip"]:
            continue
        matchup_key = _matchup_key(f"{row['home']} vs {row['away']}")
        if expected and matchup_key not in expected:
            continue
        if target_date and not _matches_target_date(row["datetime"], target_date):
            continue
        matchup_identity = ":".join(matchup_key or ())
        key = (row["datetime"], matchup_identity, row["tip"].casefold())
        if key in seen:
            continue
        seen.add(key)
        row["league"] = sport_league
        out.append(row)

    return out


def _print_pick(row: dict[str, str]) -> None:
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Match:          {row['home']} vs {row['away']}")
    print(f"Date/Time:      {row['datetime']}")
    print(f"League:         {row['league']}")
    print(f"Tip:            {row['tip']}")
    print(f"Odds:           {row['odds'] or '[not found on page]'}")
    print("Confidence:     [not found on page]")
    print("User vote:      [not found on page]")
    print(f"Source URL:     {row['href']}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def main() -> None:
    ap = argparse.ArgumentParser(description="SportyTrader scraper")
    ap.add_argument(
        "--sport",
        "-s",
        default="nba",
        help="Supported: nba/nba_summer/wnba/mlb/fifa_world_cup/cfb/nfl",
    )
    ap.add_argument("--date", "-d", help="Date in YYYY-MM-DD")
    ap.add_argument("--expected-matchup", action="append", default=[])
    args = ap.parse_args()

    expected_matchups = [
        _normalize_line(matchup)
        for matchup in args.expected_matchup
        if _matchup_key(matchup)
    ]
    if not expected_matchups or len(expected_matchups) != len(args.expected_matchup):
        print("Error: SportyTrader requires a valid official matchup whitelist.")
        sys.exit(1)

    sport_key = _normalize_sport(args.sport or "")
    if not sport_key:
        print(
            "Error: SportyTrader scraper supports NBA/basketball, NBA Summer League, "
            "WNBA, MLB/baseball, FIFA World Cup/soccer, CFB/NCAAF, and NFL."
        )
        sys.exit(1)

    target_date = _parse_target_date(args.date)
    sport_config = SPORT_CONFIG[sport_key]
    target_urls = list(
        dict.fromkeys(
            [sport_config["url"], *sport_config.get("fallback_urls", ())]
        )
    )
    target_title = sport_config["title"]

    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        ctx = _new_context(browser)
        page = ctx.new_page()
        cards: list[dict[str, str]] = []
        page_texts: list[str] = []
        load_errors: list[str] = []
        try:
            visited_urls: set[str] = set()
            target_index = 0
            while target_index < len(target_urls) and len(visited_urls) < 8:
                target_url = target_urls[target_index]
                target_index += 1
                if target_url in visited_urls:
                    continue
                visited_urls.add(target_url)
                try:
                    page_cards, page_text = _load_cards(page, target_url)
                except PwTimeout:
                    load_errors.append(f"timed out loading {target_url}")
                    continue
                except Exception as exc:
                    load_errors.append(f"{target_url}: {exc}")
                    continue
                cards.extend(page_cards)
                cards.extend(
                    _extract_text_cards(page_text, target_url, expected_matchups)
                )
                page_texts.append(page_text)
        finally:
            page.close()
            browser.close()

    if not page_texts:
        detail = "; ".join(load_errors[:2]) or "no listing page loaded"
        print(f"Error loading SportyTrader {target_title} page: {detail}")
        sys.exit(1)
    if page_texts and all(_looks_like_cloudflare_block("", text) for text in page_texts):
        print(f"Error: SportyTrader {target_title} page hit Cloudflare verification")
        sys.exit(1)
    blocked_page_count = sum(
        1 for text in page_texts if _looks_like_cloudflare_block("", text)
    )
    allow_partial = bool(sport_config.get("allow_partial_listings"))
    unblocked_page_count = sum(
        1 for text in page_texts if not _looks_like_cloudflare_block("", text)
    )
    if load_errors or blocked_page_count:
        if not (allow_partial and unblocked_page_count):
            detail = "; ".join(load_errors[:2])
            if blocked_page_count:
                prefix = f"{detail}; " if detail else ""
                detail = f"{prefix}{blocked_page_count} listing page(s) were blocked"
            print(
                f"Error: incomplete SportyTrader {target_title} listing coverage: {detail}"
            )
            sys.exit(1)

    try:
        rows = _extract_rows(cards, target_date, sport_key, expected_matchups)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    if not rows:
        print(f"No SportyTrader {target_title} picks parsed.")
        expected_keys = {
            key
            for matchup in expected_matchups
            if (key := _matchup_key(matchup))
        }
        official_card_count = sum(
            1
            for card in cards
            if _matchup_key(f"{card.get('home', '')} vs {card.get('away', '')}")
            in expected_keys
        )
        print(
            f"Diagnostics: listingPages={len(page_texts)} cards={len(cards)} "
            f"officialMatchupCards={official_card_count}."
        )
        return

    for row in rows:
        _print_pick(row)


if __name__ == "__main__":
    main()
