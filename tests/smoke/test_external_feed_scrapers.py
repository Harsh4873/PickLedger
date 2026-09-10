from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_sportytrader_wnba_config_and_card_extraction():
    module = _load_module(
        "sportytrader_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    assert module.SPORT_CONFIG["wnba"]["url"].endswith("/wnba-58202/")
    rows = module._extract_rows(
        [
            {
                "datetime": "Jun 12, 2026, 1:00 AM",
                "league": "USA - WNBA",
                "home": "Indiana Fever",
                "away": "Chicago Sky",
                "tip": "Indiana Fever -9.5",
                "odds": "-110",
                "href": "https://www.sportytrader.com/us/picks/chicago-sky-indiana-fever-354049/",
            }
        ],
        module._parse_target_date("2026-06-11"),
        "wnba",
        ["Chicago Sky @ Indiana Fever"],
    )
    assert rows[0]["league"] == "USA - WNBA"
    assert rows[0]["tip"] == "Indiana Fever -9.5"


def test_sportytrader_nba_summer_uses_official_matchup_identity():
    module = _load_module(
        "sportytrader_nba_summer_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    config = module.SPORT_CONFIG["nba_summer"]
    assert config["url"].endswith("/en/betting-tips/basketball/")
    assert "NBA Summer League" in module.SPORTYTRADER_CARDS_JS

    rows = module._extract_rows(
        [
            {
                "datetime": "Jul 16, 2026, 7:00 PM",
                # Summer cards may be grouped under the provider's NBA page.
                "league": "USA - NBA",
                "home": "Oklahoma City Thunder",
                "away": "Dallas Mavericks",
                "tip": "Oklahoma City Thunder -2.5",
                "odds": "-110",
                "href": "https://www.sportytrader.com/us/picks/dallas-oklahoma-city-1/",
            },
            {
                "datetime": "Jul 16, 2026, 8:00 PM",
                "league": "USA - NBA",
                "home": "Boston Celtics",
                "away": "New York Knicks",
                "tip": "Boston Celtics ML",
                "odds": "-115",
                "href": "https://www.sportytrader.com/us/picks/new-york-boston-2/",
            },
        ],
        module._parse_target_date("2026-07-16"),
        "nba_summer",
        ["Dallas Mavericks @ Oklahoma City Thunder"],
    )

    assert len(rows) == 1
    assert rows[0]["league"] == "USA - NBA Summer League"
    assert rows[0]["tip"] == "Oklahoma City Thunder -2.5"


def test_sportytrader_current_listing_extracts_target_date_editorial_cards_only():
    module = _load_module(
        "sportytrader_current_listing_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    body_text = """
16 Jul 2026, 18:00
USA - NBA Summer League
Chicago Bulls
Chicago Bulls
-
Los Angeles Lakers
Los Angeles Lakers
Chicago Bulls vs Los Angeles Lakers Prediction
Los Angeles Lakers wins
Detail
16 Jul 2026, 19:00
USA - NBA Summer League
New York Knicks
New York Knicks
-
Golden State Warriors
Golden State Warriors
New York Knicks vs Golden State Warriors Prediction
Golden State Warriors -7.5 handicap
Detail
16 Jul 2026, 20:00
USA - NBA Summer League
Atlanta Hawks
Atlanta Hawks
-
Memphis Grizzlies
Memphis Grizzlies
Atlanta Hawks vs Memphis Grizzlies Prediction
Atlanta Hawks wins
Detail
16 Jul 2026, 21:00
USA - NBA Summer League
Miami Heat
Miami Heat
-
Toronto Raptors
Toronto Raptors
Miami Heat vs Toronto Raptors Prediction
Toronto Raptors wins
Detail
16 Jul 2026, 22:00
USA - NBA Summer League
Denver Nuggets
Denver Nuggets
-
Portland Trail Blazers
Portland Trail Blazers
Denver Nuggets vs Portland Trail Blazers Prediction
Over 178.5 points
Detail
20 Jul 2026, 20:00
USA - WNBA
Dallas Wings
Dallas Wings
-
New York Liberty
New York Liberty
Dallas Wings vs New York Liberty Prediction
Dallas Wings wins
Detail
Match Winner predictions model
16 Jul 2026, 16:00
Oklahoma City Thunder
Dallas Mavericks
Probability of 52%
BET NOW!
16 Jul 2026, 16:30
Houston Rockets
Brooklyn Nets
Probability of 54%
BET NOW!
"""
    summer_matchups = [
        "Dallas Mavericks @ Oklahoma City Thunder",
        "Brooklyn Nets @ Houston Rockets",
        "Los Angeles Lakers @ Chicago Bulls",
        "Golden State Warriors @ New York Knicks",
        "Memphis Grizzlies @ Atlanta Hawks",
        "Toronto Raptors @ Miami Heat",
        "Portland Trail Blazers @ Denver Nuggets",
    ]
    cards = module._extract_text_cards(
        body_text,
        module.BASKETBALL_LISTING_URL,
        summer_matchups,
    )
    rows = module._extract_rows(
        cards,
        module._parse_target_date("2026-07-16"),
        "nba_summer",
        summer_matchups,
    )

    assert module._parse_english_datetime("16 Jul 2026, 18:00").date().isoformat() == "2026-07-16"
    assert len(rows) == 5
    assert {row["tip"] for row in rows} == {
        "Los Angeles Lakers wins",
        "Golden State Warriors -7.5 handicap",
        "Atlanta Hawks wins",
        "Toronto Raptors wins",
        "Over 178.5 points",
    }

    wnba_cards = module._extract_text_cards(
        body_text,
        module.BASKETBALL_LISTING_URL,
        ["New York Liberty @ Dallas Wings"],
    )
    wnba_rows = module._extract_rows(
        wnba_cards,
        module._parse_target_date("2026-07-16"),
        "wnba",
        ["New York Liberty @ Dallas Wings"],
    )
    assert wnba_rows == []


def test_sportytrader_current_basketball_wording_preserves_market_identity():
    import pickgrader_server as server

    assert server._clean_sportytrader_pick(
        "Los Angeles Lakers wins",
        "Chicago Bulls vs Los Angeles Lakers",
        "NBA SUMMER",
    ) == "Lakers ML (Bulls vs Lakers)"
    assert server._clean_sportytrader_pick(
        "Golden State Warriors \u20137.5 handicap",
        "New York Knicks vs Golden State Warriors",
        "NBA SUMMER",
    ) == "Warriors -7.5 (Knicks vs Warriors)"
    assert server._clean_sportytrader_pick(
        "Over 178.5 points",
        "Denver Nuggets vs Portland Trail Blazers",
        "NBA SUMMER",
    ) == "Over 178.5 (Nuggets vs Trail Blazers)"
    assert server._clean_sportytrader_pick(
        "Dallas Wings wins",
        "Dallas Wings vs New York Liberty",
        "WNBA",
    ) == "Wings ML (Wings vs Liberty)"


def test_sportytrader_cfb_config_and_card_extraction():
    module = _load_module(
        "sportytrader_cfb_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    config = module.SPORT_CONFIG["cfb"]
    assert config["url"].endswith("/football/usa/ncaa/")
    assert config["aliases"] == {"cfb", "ncaaf", "college_football", "ncaa"}
    assert "football" not in config["aliases"]
    assert "soccer" not in config["aliases"]
    assert module._normalize_sport("ncaaf") == "cfb"
    assert module._normalize_sport("college_football") == "cfb"
    assert module._normalize_sport("ncaa") == "cfb"
    assert module._normalize_sport("football") == "fifa_world_cup"
    assert "NCAAF" in module.SPORTYTRADER_CARDS_JS
    assert "College Football" in module.SPORTYTRADER_CARDS_JS
    assert "NFL" in module.SPORTYTRADER_CARDS_JS
    rows = module._extract_rows(
        [
            {
                "datetime": "Sep 4, 2026, 7:00 PM",
                "league": "USA - NCAA",
                "home": "Michigan State Spartans",
                "away": "Toledo Rockets",
                "tip": "Toledo Rockets +10.5",
                "odds": "-115",
                "href": "https://www.sportytrader.com/us/picks/michigan-state-toledo-1/",
            },
            {
                "datetime": "Sep 4, 2026, 8:20 PM",
                "league": "USA - NFL",
                "home": "Kansas City Chiefs",
                "away": "Baltimore Ravens",
                "tip": "Kansas City Chiefs -3.5",
                "odds": "-110",
                "href": "https://www.sportytrader.com/us/picks/baltimore-kansas-city-2/",
            },
        ],
        module._parse_target_date("2026-09-04"),
        "cfb",
        ["Toledo Rockets @ Michigan State Spartans", "Baltimore Ravens @ Kansas City Chiefs"],
    )
    assert len(rows) == 1
    assert rows[0]["league"] == "USA - NCAA"
    assert rows[0]["tip"] == "Toledo Rockets +10.5"


def test_sportytrader_cfb_text_cards_keep_ncaa_and_drop_nfl():
    module = _load_module(
        "sportytrader_cfb_text_cards_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    body_text = """
04 Sep 2026, 19:00
USA - NCAA
Toledo Rockets
Toledo Rockets
-
Michigan State Spartans
Michigan State Spartans
Toledo Rockets vs Michigan State Spartans Prediction
Toledo Rockets +10.5
Detail
04 Sep 2026, 20:20
USA - NFL
Baltimore Ravens
Baltimore Ravens
-
Kansas City Chiefs
Kansas City Chiefs
Baltimore Ravens vs Kansas City Chiefs Prediction
Kansas City Chiefs -3.5
Detail
"""
    matchups = [
        "Toledo Rockets @ Michigan State Spartans",
        "Baltimore Ravens @ Kansas City Chiefs",
    ]
    cards = module._extract_text_cards(
        body_text,
        module.SPORT_CONFIG["cfb"]["url"],
        matchups,
    )
    rows = module._extract_rows(
        cards,
        module._parse_target_date("2026-09-04"),
        "cfb",
        matchups,
    )
    assert len(rows) == 1
    assert rows[0]["tip"] == "Toledo Rockets +10.5"
    assert rows[0]["league"] == "USA - NCAA"


def test_sportytrader_nfl_config_and_card_extraction():
    module = _load_module(
        "sportytrader_nfl_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    config = module.SPORT_CONFIG["nfl"]
    assert config["url"].endswith("/football/usa/nfl-598/")
    assert config["aliases"] == {"nfl"}
    assert "football" not in config["aliases"]
    assert "soccer" not in config["aliases"]
    assert module._normalize_sport("nfl") == "nfl"
    assert module._normalize_sport("football") == "fifa_world_cup"
    assert "nfl-598" in config["fallback_urls"][0]
    rows = module._extract_rows(
        [
            {
                "datetime": "Sep 10, 2026, 8:20 PM",
                "league": "USA - NFL",
                "home": "Seattle Seahawks",
                "away": "New England Patriots",
                "tip": "Seattle Seahawks -3",
                "odds": "-110",
                "href": "https://www.sportytrader.com/us/picks/new-england-seattle-1/",
            },
            {
                "datetime": "Sep 10, 2026, 7:00 PM",
                "league": "USA - NCAA",
                "home": "Michigan State Spartans",
                "away": "Toledo Rockets",
                "tip": "Toledo Rockets +10.5",
                "odds": "-115",
                "href": "https://www.sportytrader.com/us/picks/toledo-michigan-state-2/",
            },
        ],
        module._parse_target_date("2026-09-10"),
        "nfl",
        ["New England Patriots @ Seattle Seahawks", "Toledo Rockets @ Michigan State Spartans"],
    )
    assert len(rows) == 1
    assert rows[0]["league"] == "USA - NFL"
    assert rows[0]["tip"] == "Seattle Seahawks -3"


def test_sportytrader_nfl_text_cards_keep_nfl_and_drop_ncaa():
    module = _load_module(
        "sportytrader_nfl_text_cards_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    body_text = """
10 Sep 2026, 20:20
USA - NFL
New England Patriots
New England Patriots
-
Seattle Seahawks
Seattle Seahawks
New England Patriots vs Seattle Seahawks Prediction
Seattle Seahawks -3
Detail
10 Sep 2026, 19:00
USA - NCAA
Toledo Rockets
Toledo Rockets
-
Michigan State Spartans
Michigan State Spartans
Toledo Rockets vs Michigan State Spartans Prediction
Toledo Rockets +10.5
Detail
"""
    matchups = [
        "New England Patriots @ Seattle Seahawks",
        "Toledo Rockets @ Michigan State Spartans",
    ]
    cards = module._extract_text_cards(
        body_text,
        module.SPORT_CONFIG["nfl"]["url"],
        matchups,
    )
    rows = module._extract_rows(
        cards,
        module._parse_target_date("2026-09-10"),
        "nfl",
        matchups,
    )
    assert len(rows) == 1
    assert rows[0]["tip"] == "Seattle Seahawks -3"
    assert rows[0]["league"] == "USA - NFL"


def test_sportytrader_fifa_world_cup_config_and_known_matchup_alias():
    module = _load_module(
        "sportytrader_fifa_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
    )
    assert module.SPORT_CONFIG["fifa_world_cup"]["url"].endswith("/world-cup-1811/")
    assert "team !== values[index - 1]" in module.SPORTYTRADER_CARDS_JS
    rows = module._extract_rows(
        [
            {
                "datetime": "Jun 13, 2026, 11:00 PM",
                "league": "World - World Cup",
                "home": "Australia",
                "away": "Türkiye",
                "tip": "Turkey to Win & Under 3.5 Goals",
                "odds": "+130",
                "href": "https://www.sportytrader.com/us/picks/australia-turkiye-123/",
            }
        ],
        module._parse_target_date("2026-06-13"),
        "fifa_world_cup",
        ["Turkey @ Australia", "Switzerland @ Qatar"],
    )
    assert rows[0]["league"] == "World - World Cup"
    assert rows[0]["tip"] == "Turkey to Win & Under 3.5 Goals"


def test_provider_scraper_clis_require_an_official_matchup_whitelist(monkeypatch):
    modules = (
        _load_module(
            "sportytrader_cli_whitelist_test",
            ROOT / "scripts" / "scrapers" / "sportytrader_scraper.py",
        ),
        _load_module(
            "sportsgambler_cli_whitelist_test",
            ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
        ),
    )

    for module in modules:
        monkeypatch.setattr(
            module.sys,
            "argv",
            ["scraper", "--sport", "wnba", "--date", "2026-06-29"],
        )
        try:
            module.main()
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("provider CLI must reject an empty official matchup whitelist")


def test_sportsgambler_wnba_listing_and_detail(monkeypatch):
    module = _load_module(
        "sportsgambler_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    detail_url = "https://www.sportsgambler.com/betting-tips/basketball/chicago-sky-vs-indiana-fever-prediction-odds-2026-06-11/"
    late_url = "https://www.sportsgambler.com/betting-tips/basketball/phoenix-mercury-vs-dallas-wings-prediction-odds-2026-06-11/"
    listing = {
        "@context": "https://schema.org",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Indiana Fever vs Chicago Sky",
                        "startDate": "2026-06-11T23:00:00Z",
                        "url": detail_url,
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Dallas Wings vs Phoenix Mercury",
                        "startDate": "2026-06-13T01:00:00Z",
                        "url": late_url,
                    },
                },
            ],
        },
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div><a class="tpbot_tip"><span>Pick</span><span>Fever -9.5 @ -112</span></a></div>'
    late_html = '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div><a class="tpbot_tip"><span>Pick</span><span>Under 170.5 Points @ -110</span></a></div>'

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response(detail_html if url == detail_url else late_html if url == late_url else listing_html),
    )
    rows = module.scrape_wnba(
        date(2026, 6, 11),
        ["Chicago Sky @ Indiana Fever", "Phoenix Mercury @ Dallas Wings"],
    )
    assert rows == [
        {
            "datetime": "2026-06-11T23:00:00Z",
            "league": "WNBA",
            "matchup": "Indiana Fever vs Chicago Sky",
            "tip": "Fever -9.5",
            "odds": "-112",
            "href": detail_url,
        },
        {
            "datetime": "2026-06-13T01:00:00Z",
            "league": "WNBA",
            "matchup": "Dallas Wings vs Phoenix Mercury",
            "tip": "Under 170.5 Points",
            "odds": "-110",
            "href": late_url,
        },
    ]


def test_sportsgambler_nba_summer_reuses_basketball_listings_with_whitelist(monkeypatch):
    module = _load_module(
        "sportsgambler_nba_summer_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    detail_url = (
        "https://www.sportsgambler.com/betting-tips/basketball/"
        "dallas-mavericks-vs-oklahoma-city-thunder-prediction-odds-2026-07-16/"
    )
    listing = {
        "@context": "https://schema.org",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Dallas Mavericks vs Oklahoma City Thunder",
                        "startDate": "2026-07-16T23:00:00Z",
                        "url": detail_url,
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "New York Knicks vs Boston Celtics",
                        "startDate": "2026-07-16T23:30:00Z",
                        "url": f"{detail_url}regular-nba/",
                    },
                },
            ],
        },
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = (
        '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div>'
        '<a class="tpbot_tip"><span>Pick</span><span>Thunder -2.5 @ -110</span></a></div>'
    )

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response(detail_html if url == detail_url else listing_html),
    )
    rows = module.scrape_nba_summer(
        date(2026, 7, 16),
        ["Dallas Mavericks @ Oklahoma City Thunder"],
    )

    assert rows == [
        {
            "datetime": "2026-07-16T23:00:00Z",
            "league": "NBA SUMMER",
            "matchup": "Dallas Mavericks vs Oklahoma City Thunder",
            "tip": "Thunder -2.5",
            "odds": "-110",
            "href": detail_url,
        }
    ]


def test_sportsgambler_nba_summer_rejects_partial_listing_coverage(monkeypatch):
    module = _load_module(
        "sportsgambler_nba_summer_partial_listing_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )

    class Response:
        status_code = 200
        text = "<html>No current predictions.</html>"

    def fake_get(url, **_kwargs):
        if url == module.NBA_URL:
            raise module.requests.ConnectionError("listing unavailable")
        return Response()

    monkeypatch.setattr(module.requests, "get", fake_get)
    try:
        module.scrape_nba_summer(
            date(2026, 7, 16),
            ["Dallas Mavericks @ Oklahoma City Thunder"],
        )
    except RuntimeError as exc:
        assert "incomplete NBA SUMMER listing coverage" in str(exc)
    else:
        raise AssertionError("partial SportsGambler listing coverage must not publish a false zero")


def test_sportsgambler_rejects_partial_basketball_feed(monkeypatch):
    module = _load_module(
        "sportsgambler_partial_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    detail_url = "https://www.sportsgambler.com/betting-tips/basketball/example-prediction-odds-2026-06-11/"
    listing = {
        "item": {
            "@type": "SportsEvent",
            "name": "Example Away vs Example Home",
            "startDate": "2026-06-11T23:00:00Z",
            "url": detail_url,
        }
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response("<html>No prediction block yet</html>" if url == detail_url else listing_html),
    )

    try:
        module.scrape_wnba(date(2026, 6, 11), ["Example Away @ Example Home"])
    except RuntimeError as exc:
        assert "partial WNBA scrape: parsed 0 of 1" in str(exc)
    else:
        raise AssertionError("partial SportsGambler WNBA scrape must fail instead of publishing")


def test_sportsgambler_uses_known_matchups_as_a_whitelist(monkeypatch):
    module = _load_module(
        "sportsgambler_missing_matchup_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    listing = {
        "item": {
            "@type": "SportsEvent",
            "name": "Indiana Fever vs Chicago Sky",
            "startDate": "2026-06-11T23:00:00Z",
            "url": "https://example.com/fever-sky",
        }
    }

    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div><a class="tpbot_tip"><span>Pick</span><span>Fever -9.5 @ -112</span></a></div>'

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response(detail_html if url == "https://example.com/fever-sky" else listing_html),
    )
    rows = module.scrape_wnba(
        date(2026, 6, 11),
        ["Chicago Sky @ Indiana Fever", "Phoenix Mercury @ Dallas Wings"],
    )
    assert [row["matchup"] for row in rows] == ["Indiana Fever vs Chicago Sky"]


def test_sportsgambler_mlb_uses_known_matchups_as_a_whitelist(monkeypatch):
    module = _load_module(
        "sportsgambler_mlb_slate_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    listing_html = """
    <div class="tipbox_item" id="official">
      <div class="tipsbox_title">
        <h3><span>Chicago Cubs vs St. Louis Cardinals</span></h3>
        <div class="tipsbox_meta"><span>Jun 13, 2026</span><span>- MLB</span></div>
      </div>
      <div class="tipbox_tip"><span>Pick</span><span>Chicago Cubs to Win @ -115</span></div>
    </div>
    <div class="tipbox_item" id="other-date">
      <div class="tipsbox_title">
        <h3><span>Boston Red Sox vs New York Yankees</span></h3>
        <div class="tipsbox_meta"><span>Jun 14, 2026</span><span>- MLB</span></div>
      </div>
      <div class="tipbox_tip"><span>Pick</span><span>New York Yankees to Win @ -120</span></div>
    </div>
    """

    class Response:
        text = listing_html

    monkeypatch.setattr(module.requests, "get", lambda *_args, **_kwargs: Response())
    rows = module.scrape_mlb(
        date(2026, 6, 13),
        ["St. Louis Cardinals @ Chicago Cubs"],
    )

    assert [row["matchup"] for row in rows] == ["Chicago Cubs vs St. Louis Cardinals"]


def test_sportsgambler_fifa_world_cup_preserves_asian_handicap(monkeypatch):
    module = _load_module(
        "sportsgambler_fifa_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    detail_url = "https://www.sportsgambler.com/betting-tips/football/qatar-vs-switzerland-prediction-lineups-odds-2026-06-13/"
    listing = {
        "item": {
            "@type": "SportsEvent",
            "name": "Qatar vs Switzerland",
            "startDate": "2026-06-13T19:00:00Z",
            "url": detail_url,
        }
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = '<div class="tpbot_container"><div class="tpbot_title">Our Match Prediction</div><a class="tpbot_tip"><span>Pick</span><span>Switzerland Asian Hcp -1.75 @ -114</span></a></div>'

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response(detail_html if url == detail_url else listing_html),
    )
    rows = module.scrape_fifa_world_cup(date(2026, 6, 13), ["Switzerland @ Qatar"])
    assert rows[0]["tip"] == "Switzerland Asian Hcp -1.75"
    assert rows[0]["odds"] == "-114"
    assert rows[0]["league"] == "FIFA WC"


def test_sportsgambler_fifa_world_cup_reads_tip_without_visible_title(monkeypatch):
    module = _load_module(
        "sportsgambler_fifa_titleless_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    detail_url = "https://www.sportsgambler.com/betting-tips/football/scotland-vs-morocco-prediction-lineups-odds-2026-06-19/"
    listing = {
        "item": {
            "@type": "SportsEvent",
            "name": "Scotland vs Morocco",
            "startDate": "2026-06-19T19:00:00Z",
            "url": detail_url,
        }
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = (
        '<div class="tpbot_container">'
        '<!-- <div class="tpbot_title">Our Match Prediction</div> -->'
        '<a class="tpbot_tip"><span>Morocco To Win @ -149</span></a>'
        "</div>"
    )

    class Response:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(
        module.requests,
        "get",
        lambda url, **_kwargs: Response(detail_html if url == detail_url else listing_html),
    )
    rows = module.scrape_fifa_world_cup(date(2026, 6, 19), ["Morocco @ Scotland"])
    assert rows[0]["tip"] == "Morocco To Win"
    assert rows[0]["odds"] == "-149"


def test_sportsgambler_cfb_listing_and_detail_filters_nfl(monkeypatch):
    module = _load_module(
        "sportsgambler_cfb_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    ncaaf_url = (
        "https://www.sportsgambler.com/betting-tips/ncaaf/"
        "toledo-rockets-vs-michigan-state-spartans-prediction-odds-2026-09-04/"
    )
    nfl_url = (
        "https://www.sportsgambler.com/betting-tips/nfl/"
        "baltimore-ravens-vs-kansas-city-chiefs-prediction-odds-2026-09-04/"
    )
    listing = {
        "@context": "https://schema.org",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Michigan State Spartans vs Toledo Rockets",
                        "startDate": "2026-09-05T00:00:00Z",
                        "url": ncaaf_url,
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Kansas City Chiefs vs Baltimore Ravens",
                        "startDate": "2026-09-05T00:20:00Z",
                        "url": nfl_url,
                    },
                },
            ],
        },
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = (
        '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div>'
        '<a class="tpbot_tip"><span>Pick</span><span>Toledo +10.5 @ -115</span></a></div>'
    )
    nfl_html = (
        '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div>'
        '<a class="tpbot_tip"><span>Pick</span><span>Chiefs -3.5 @ -110</span></a></div>'
    )
    requested: list[str] = []

    class Response:
        status_code = 200

        def __init__(self, text: str):
            self.text = text

    def fake_get(url, **_kwargs):
        requested.append(url)
        if url == ncaaf_url:
            return Response(detail_html)
        if url == nfl_url:
            return Response(nfl_html)
        return Response(listing_html)

    monkeypatch.setattr(module.requests, "get", fake_get)
    rows = module.scrape_cfb(
        date(2026, 9, 4),
        [
            "Toledo Rockets @ Michigan State Spartans",
            "Baltimore Ravens @ Kansas City Chiefs",
        ],
    )
    assert rows == [
        {
            "datetime": "2026-09-05T00:00:00Z",
            "league": "CFB",
            "matchup": "Michigan State Spartans vs Toledo Rockets",
            "tip": "Toledo +10.5",
            "odds": "-115",
            "href": ncaaf_url,
        }
    ]
    assert ncaaf_url in requested
    assert nfl_url not in requested
    assert any("ncaa-college-football-predictions" in url for url in requested)


def test_sportsgambler_cli_cfb_aliases_do_not_steal_football(monkeypatch):
    module = _load_module(
        "sportsgambler_cfb_cli_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    captured: list[str] = []

    def _cfb_rows(*_args, **_kwargs):
        captured.append("cfb")
        return [{
            "matchup": "Michigan State Spartans vs Toledo Rockets",
            "datetime": "2026-09-04",
            "league": "CFB",
            "tip": "Toledo +10.5",
            "odds": "-115",
            "href": "https://example.com/ncaaf",
        }]

    def _fifa_rows(*_args, **_kwargs):
        captured.append("fifa")
        return [{
            "matchup": "Qatar vs Switzerland",
            "datetime": "2026-06-13",
            "league": "FIFA WC",
            "tip": "Switzerland To Win",
            "odds": "-114",
            "href": "https://example.com/fifa",
        }]

    monkeypatch.setattr(module, "scrape_cfb", _cfb_rows)
    monkeypatch.setattr(module, "scrape_fifa_world_cup", _fifa_rows)
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["scraper", "--sport", "football", "--date", "2026-09-04", "--expected-matchup", "Qatar vs Switzerland"],
    )
    module.main()
    assert captured == ["fifa"]

    captured.clear()
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["scraper", "--sport", "ncaaf", "--date", "2026-09-04", "--expected-matchup", "Toledo Rockets @ Michigan State Spartans"],
    )
    module.main()
    assert captured == ["cfb"]


def test_sportsgambler_nfl_listing_and_detail_filters_ncaaf(monkeypatch):
    module = _load_module(
        "sportsgambler_nfl_scraper_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    ncaaf_url = (
        "https://www.sportsgambler.com/betting-tips/ncaaf/"
        "toledo-rockets-vs-michigan-state-spartans-prediction-odds-2026-09-10/"
    )
    nfl_url = (
        "https://www.sportsgambler.com/betting-tips/nfl/"
        "new-england-patriots-vs-seattle-seahawks-prediction-odds-2026-09-10/"
    )
    listing = {
        "@context": "https://schema.org",
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Seattle Seahawks vs New England Patriots",
                        "startDate": "2026-09-11T00:20:00Z",
                        "url": nfl_url,
                    },
                },
                {
                    "@type": "ListItem",
                    "item": {
                        "@type": "SportsEvent",
                        "name": "Michigan State Spartans vs Toledo Rockets",
                        "startDate": "2026-09-11T00:00:00Z",
                        "url": ncaaf_url,
                    },
                },
            ],
        },
    }
    listing_html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
    detail_html = (
        '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div>'
        '<a class="tpbot_tip"><span>Pick</span><span>Seahawks -3 @ -110</span></a></div>'
    )
    ncaaf_html = (
        '<div class="tpbot_container"><div class="tpbot_title">Our Game Prediction</div>'
        '<a class="tpbot_tip"><span>Pick</span><span>Toledo +10.5 @ -115</span></a></div>'
    )
    requested: list[str] = []

    class Response:
        status_code = 200

        def __init__(self, text: str):
            self.text = text

    def fake_get(url, **_kwargs):
        requested.append(url)
        if url == nfl_url:
            return Response(detail_html)
        if url == ncaaf_url:
            return Response(ncaaf_html)
        return Response(listing_html)

    monkeypatch.setattr(module.requests, "get", fake_get)
    rows = module.scrape_nfl(
        date(2026, 9, 10),
        [
            "New England Patriots @ Seattle Seahawks",
            "Toledo Rockets @ Michigan State Spartans",
        ],
    )
    assert rows == [
        {
            "datetime": "2026-09-11T00:20:00Z",
            "league": "NFL",
            "matchup": "Seattle Seahawks vs New England Patriots",
            "tip": "Seahawks -3",
            "odds": "-110",
            "href": nfl_url,
        }
    ]
    assert nfl_url in requested
    assert ncaaf_url not in requested
    assert any("nfl-predictions" in url for url in requested)


def test_sportsgambler_cli_nfl_does_not_steal_football(monkeypatch):
    module = _load_module(
        "sportsgambler_nfl_cli_test",
        ROOT / "scripts" / "scrapers" / "sportsgambler_scraper.py",
    )
    captured: list[str] = []

    def _nfl_rows(*_args, **_kwargs):
        captured.append("nfl")
        return [{
            "matchup": "Seattle Seahawks vs New England Patriots",
            "datetime": "2026-09-10",
            "league": "NFL",
            "tip": "Seahawks -3",
            "odds": "-110",
            "href": "https://example.com/nfl",
        }]

    def _fifa_rows(*_args, **_kwargs):
        captured.append("fifa")
        return [{
            "matchup": "Qatar vs Switzerland",
            "datetime": "2026-06-13",
            "league": "FIFA WC",
            "tip": "Switzerland To Win",
            "odds": "-114",
            "href": "https://example.com/fifa",
        }]

    monkeypatch.setattr(module, "scrape_nfl", _nfl_rows)
    monkeypatch.setattr(module, "scrape_fifa_world_cup", _fifa_rows)
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["scraper", "--sport", "football", "--date", "2026-09-10", "--expected-matchup", "Qatar vs Switzerland"],
    )
    module.main()
    assert captured == ["fifa"]

    captured.clear()
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["scraper", "--sport", "nfl", "--date", "2026-09-10", "--expected-matchup", "New England Patriots @ Seattle Seahawks"],
    )
    module.main()
    assert captured == ["nfl"]


def test_server_passes_known_matchups_to_sportsgambler(monkeypatch):
    import pickgrader_server as server

    captured: list[str] = []
    monkeypatch.setattr(
        server,
        "_known_external_slate_matchups",
        lambda _date, _sport: ["Phoenix Mercury @ Dallas Wings"],
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        captured.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Dallas Wings vs Phoenix Mercury\n"
                "League: WNBA\n"
                "Tip: Under 170.5 Points\n"
                "Odds: -110\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportsgambler_scraper("2026-06-11", ["wnba"])

    assert result["ok"] is True
    assert captured[-2:] == ["--expected-matchup", "Phoenix Mercury @ Dallas Wings"]
    assert result["picks"][0]["source"] == "SportsGamblerWNBA"


def test_server_accepts_sportsgambler_cfb_league_and_source_label(monkeypatch):
    import pickgrader_server as server

    monkeypatch.setattr(
        server,
        "_known_external_slate_matchups",
        lambda _date, _sport: ["Toledo Rockets @ Michigan State Spartans"],
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        assert command[command.index("--sport") + 1] == "cfb"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Michigan State Spartans vs Toledo Rockets\n"
                "League: CFB\n"
                "Tip: Toledo +10.5\n"
                "Odds: -115\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportsgambler_scraper("2026-09-04", ["cfb"])

    assert result["ok"] is True
    assert result["picks"][0]["source"] == "SportsGamblerCFB"
    assert result["picks"][0]["sport"] == "CFB"
    assert result["picks"][0]["pick"] == "Toledo +10.5 (Michigan State Spartans vs Toledo Rockets)"


def test_cfb_soft_fail_does_not_block_mlb_refresh(monkeypatch):
    import pickgrader_server as server

    def fake_matchups(_date, sport):
        if sport == "mlb":
            return ["St. Louis Cardinals @ Chicago Cubs"]
        if sport == "cfb":
            return ["Toledo Rockets @ Michigan State Spartans"]
        return []

    monkeypatch.setattr(server, "_known_external_slate_matchups", fake_matchups)
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        sport = command[command.index("--sport") + 1]
        if sport == "cfb":
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="Error: SportyTrader CFB page hit Cloudflare verification",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Chicago Cubs vs St. Louis Cardinals\n"
                "League: USA - MLB\n"
                "Tip: Chicago Cubs to win\n"
                "Odds: -115\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    for runner in (server.run_sportytrader_scraper, server.run_sportsgambler_scraper):
        result = runner("2026-09-04", ["mlb", "cfb"])
        assert result["ok"] is True, result
        assert result["picks"][0]["sport"] == "MLB"
        assert "cfb:" in ";".join(result["errors"])
        assert result["meta"]["sportErrors"]["cfb"]
        assert result["picks"][0]["source"] in {"SportyTraderMLB", "SportsGamblerMLB"}


def test_unresolved_cfb_slate_does_not_fail_mlb_provider(monkeypatch):
    import pickgrader_server as server

    def fake_matchups(_date, sport):
        return ["St. Louis Cardinals @ Chicago Cubs"] if sport == "mlb" else []

    monkeypatch.setattr(server, "_known_external_slate_matchups", fake_matchups)
    monkeypatch.setattr(
        server,
        "_espn_event_count_for_date",
        lambda sport, _date: 8 if sport == "CFB" else 0,
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        sport = command[command.index("--sport") + 1]
        assert sport != "cfb"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Chicago Cubs vs St. Louis Cardinals\n"
                "League: MLB\n"
                "Tip: Chicago Cubs to Win\n"
                "Odds: -115\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportsgambler_scraper("2026-09-04", ["mlb", "cfb"])
    assert result["ok"] is True
    assert result["picks"][0]["sport"] == "MLB"
    assert "cfb:" in ";".join(result["errors"])
    assert "no provider scraper was run" in result["meta"]["sportErrors"]["cfb"]


def test_nfl_soft_fail_does_not_block_mlb_refresh(monkeypatch):
    import pickgrader_server as server

    def fake_matchups(_date, sport):
        if sport == "mlb":
            return ["St. Louis Cardinals @ Chicago Cubs"]
        if sport == "nfl":
            return ["New England Patriots @ Seattle Seahawks"]
        return []

    monkeypatch.setattr(server, "_known_external_slate_matchups", fake_matchups)
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        sport = command[command.index("--sport") + 1]
        if sport == "nfl":
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="Error: SportyTrader NFL page hit Cloudflare verification",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Chicago Cubs vs St. Louis Cardinals\n"
                "League: USA - MLB\n"
                "Tip: Chicago Cubs to win\n"
                "Odds: -115\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    for runner in (server.run_sportytrader_scraper, server.run_sportsgambler_scraper):
        result = runner("2026-09-10", ["mlb", "nfl"])
        assert result["ok"] is True, result
        assert result["picks"][0]["sport"] == "MLB"
        assert "nfl:" in ";".join(result["errors"])
        assert result["meta"]["sportErrors"]["nfl"]
        assert result["picks"][0]["source"] in {"SportyTraderMLB", "SportsGamblerMLB"}


def test_unresolved_nfl_slate_does_not_fail_mlb_provider(monkeypatch):
    import pickgrader_server as server

    def fake_matchups(_date, sport):
        return ["St. Louis Cardinals @ Chicago Cubs"] if sport == "mlb" else []

    monkeypatch.setattr(server, "_known_external_slate_matchups", fake_matchups)
    monkeypatch.setattr(
        server,
        "_espn_event_count_for_date",
        lambda sport, _date: 16 if sport == "NFL" else 0,
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        sport = command[command.index("--sport") + 1]
        assert sport != "nfl"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Chicago Cubs vs St. Louis Cardinals\n"
                "League: MLB\n"
                "Tip: Chicago Cubs to Win\n"
                "Odds: -115\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportsgambler_scraper("2026-09-10", ["mlb", "nfl"])
    assert result["ok"] is True
    assert result["picks"][0]["sport"] == "MLB"
    assert "nfl:" in ";".join(result["errors"])
    assert "no provider scraper was run" in result["meta"]["sportErrors"]["nfl"]


def test_external_feed_aliases_keep_football_as_fifa_and_ncaaf_as_cfb():
    import pickgrader_server as server
    from scripts.merge_external_feed_cache_payload import (
        EXTERNAL_FEED_MODEL_KEYS,
        _canonical_sport_label,
        _split_feed_key,
        _split_source_label,
    )

    assert server.external_feed_model_key("sportytrader", "football") == "sportytrader_fifa_world_cup"
    assert server.external_feed_model_key("sportytrader", "ncaaf") == "sportytrader_cfb"
    assert server.external_feed_model_key("sportsgambler", "college_football") == "sportsgambler_cfb"
    assert server.external_feed_source_label("sportytrader", "CFB") == "SportyTraderCFB"
    assert server.external_feed_source_label("sportsgambler", "ncaaf") == "SportsGamblerCFB"
    assert server._normalize_sportytrader_sport("USA - NCAA") == "CFB"
    assert server._normalize_sportytrader_sport("NCAAF") == "CFB"
    assert _canonical_sport_label("football") == "FIFA WC"
    assert _canonical_sport_label("ncaaf") == "CFB"
    assert _canonical_sport_label("ncaa") == "CFB"
    assert _split_feed_key("sportytrader", "CFB") == "sportytrader_cfb"
    assert _split_source_label("sportsgambler", "College Football") == "SportsGamblerCFB"
    assert "sportytrader_cfb" in EXTERNAL_FEED_MODEL_KEYS
    assert "sportsgambler_cfb" in EXTERNAL_FEED_MODEL_KEYS
    assert server.external_feed_model_key("sportytrader", "nfl") == "sportytrader_nfl"
    assert server.external_feed_model_key("sportsgambler", "nfl") == "sportsgambler_nfl"
    assert server.external_feed_source_label("sportytrader", "NFL") == "SportyTraderNFL"
    assert server.external_feed_source_label("sportsgambler", "nfl") == "SportsGamblerNFL"
    assert server._normalize_sportytrader_sport("USA - NFL") == "NFL"
    assert _canonical_sport_label("nfl") == "NFL"
    assert _canonical_sport_label("football") == "FIFA WC"
    assert "sportytrader_nfl" in EXTERNAL_FEED_MODEL_KEYS
    assert "sportsgambler_nfl" in EXTERNAL_FEED_MODEL_KEYS
    assert "scores24_nfl" in EXTERNAL_FEED_MODEL_KEYS


def test_external_provider_scrapers_return_confirmed_zero_slate_without_launching(monkeypatch):
    import pickgrader_server as server

    monkeypatch.setattr(server, "_known_external_slate_matchups", lambda *_args: [])
    monkeypatch.setattr(server, "_espn_event_count_for_date", lambda *_args: 0)
    monkeypatch.setattr(
        server,
        "_subprocess_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider scraper must not run")),
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    for runner in (server.run_sportytrader_scraper, server.run_sportsgambler_scraper):
        result = runner("2026-06-29", ["wnba"])
        assert result["ok"] is True
        assert result["picks"] == []
        assert result["meta"]["zeroSlateSports"] == ["wnba"]
        assert result["meta"]["officialMatchupCounts"] == {}
        assert result["note"] == "No official matchups for selected sports on 2026-06-29."


def test_external_provider_scrapers_fail_closed_when_official_slate_is_unresolved(monkeypatch):
    import pickgrader_server as server

    monkeypatch.setattr(server, "_known_external_slate_matchups", lambda *_args: [])
    monkeypatch.setattr(server, "_espn_event_count_for_date", lambda *_args: None)
    monkeypatch.setattr(
        server,
        "_subprocess_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider scraper must not run")),
    )

    for runner in (server.run_sportytrader_scraper, server.run_sportsgambler_scraper):
        result = runner("2026-06-29", ["wnba"])
        assert result["ok"] is False
        assert result["picks"] == []
        assert "could not resolve an official 2026-06-29 slate" in result["error"]
        assert "no provider scraper was run" in result["error"]


def test_external_slate_whitelists_preserve_every_supported_nonempty_sport(monkeypatch):
    import pickgrader_server as server

    matchups = {
        "nba": ["Boston Celtics @ New York Knicks"],
        "nba_summer": ["Dallas Mavericks @ Oklahoma City Thunder"],
        "wnba": ["Chicago Sky @ Indiana Fever"],
        "mlb": ["St. Louis Cardinals @ Chicago Cubs"],
        "fifa_world_cup": ["Switzerland @ Qatar"],
        "cfb": ["Toledo Rockets @ Michigan State Spartans"],
    }
    monkeypatch.setattr(server, "_known_external_slate_matchups", lambda _date, sport: matchups[sport])
    monkeypatch.setattr(
        server,
        "_espn_event_count_for_date",
        lambda *_args: (_ for _ in ()).throw(AssertionError("nonempty slates need no fallback check")),
    )

    expected, zero_slate_sports, errors = server._external_feed_slate_whitelists(
        "2026-06-13",
        list(matchups),
    )
    assert expected == matchups
    assert zero_slate_sports == []
    assert errors == []


def test_external_slate_whitelist_reports_official_events_it_cannot_resolve(monkeypatch):
    import pickgrader_server as server

    monkeypatch.setattr(server, "_known_external_slate_matchups", lambda *_args: [])
    monkeypatch.setattr(server, "_espn_event_count_for_date", lambda *_args: 2)

    expected, zero_slate_sports, errors = server._external_feed_slate_whitelists(
        "2026-06-13",
        ["fifa_world_cup"],
    )
    assert expected == {}
    assert zero_slate_sports == []
    assert errors == [
        "fifa_world_cup: official 2026-06-13 slate reports 2 event(s), "
        "but no matchup whitelist could be resolved; no provider scraper was run"
    ]


def test_server_preserves_fifa_asian_handicap_without_auto_grading(monkeypatch):
    import pickgrader_server as server

    captured: list[str] = []
    monkeypatch.setattr(
        server,
        "_known_external_slate_matchups",
        lambda _date, _sport: ["Switzerland @ Qatar"],
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        captured.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Qatar vs Switzerland\n"
                "League: FIFA WC\n"
                "Tip: Switzerland Asian Hcp -1.75\n"
                "Odds: -114\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportsgambler_scraper("2026-06-13", ["fifa_world_cup"])

    assert result["ok"] is True
    assert captured[-2:] == ["--expected-matchup", "Switzerland @ Qatar"]
    assert result["picks"][0]["source"] == "SportsGamblerFIFAWorldCup"
    assert result["picks"][0]["pick"] == "Switzerland Asian Hcp -1.75 (Qatar vs Switzerland)"
    assert result["picks"][0]["market_type"] == "soccer_asian_handicap"
    assert result["picks"][0]["line"] == -1.75
    assert result["picks"][0]["grade_supported"] is False
    assert result["picks"][0]["calibration_excluded"] is True


def test_server_normalizes_parenthesized_comma_decimal_soccer_handicap_metadata():
    import pickgrader_server as server

    pick = {
        "source": "Scores24FIFAWorldCup",
        "sport": "FIFA WC",
        "pick": "Senegal Handicap (-1,5) (Iraq @ Senegal)",
        "decision": "BET",
        "result": "win",
    }

    server.apply_external_pick_metadata(pick)

    assert pick["pick"] == "Senegal Handicap (-1,5) (Iraq @ Senegal)"
    assert pick["market_type"] == "soccer_asian_handicap"
    assert pick["line"] == -1.5
    assert pick["grade_supported"] is False
    assert pick["result"] == "pending"


def test_server_routes_external_player_prop_out_of_team_markets(monkeypatch):
    import pickgrader_server as server

    monkeypatch.setattr(
        server,
        "_known_external_slate_matchups",
        lambda _date, _sport: ["Pittsburgh Pirates @ Los Angeles Dodgers"],
    )
    monkeypatch.setattr(server, "_save_admin_picks_doc", lambda *_args, **_kwargs: None)

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "Match: Pittsburgh Pirates vs Los Angeles Dodgers\n"
                "League: MLB\n"
                "Tip: Shohei Ohtani 7+ Strikeouts\n"
                "Odds: +110\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(server, "_subprocess_run", fake_run)
    result = server.run_sportytrader_scraper("2026-06-13", ["mlb"])
    pick = result["picks"][0]

    assert pick["source"] == "SportyTraderMLB"
    assert pick["scope"] == "player"
    assert pick["market_type"] == "external_player_prop"
    assert pick["grade_supported"] is True


def test_external_compound_market_is_not_auto_graded():
    import pickgrader_server as server

    pick = {
        "source": "SportyTraderMLB",
        "sport": "MLB",
        "pick": "Brewers to win and over 7.5 runs (Brewers vs Phillies)",
        "decision": "BET",
        "result": "win",
    }

    assert server.apply_external_pick_metadata(pick) == 3
    assert pick["market_type"] == "compound"
    assert pick["grade_supported"] is False
    assert pick["result"] == "pending"


def test_external_plus_compound_market_is_not_auto_graded():
    import pickgrader_server as server

    pick = {
        "source": "SportyTraderMLB",
        "sport": "MLB",
        "pick": "The Yankees -1.5 runs + Under 8.0 Runs (Red Sox vs Yankees)",
        "decision": "BET",
    }

    assert server.apply_external_pick_metadata(pick) == 2
    assert pick["market_type"] == "compound"
    assert pick["grade_supported"] is False


def test_external_team_mismatch_market_is_not_auto_graded():
    import pickgrader_server as server

    pick = {
        "source": "SportyTraderWNBA",
        "sport": "WNBA",
        "pick": "Las Vegas Aces on the -1.5 line (Valkyries vs Dream)",
        "decision": "BET",
    }

    assert server.apply_external_pick_metadata(pick) == 2
    assert pick["market_type"] == "external_team_mismatch"
    assert pick["grade_supported"] is False


def test_external_feed_refresh_splits_provider_buckets_by_sport():
    module = _load_module(
        "refresh_external_feeds_split_test",
        ROOT / "scripts" / "refresh_external_feeds.py",
    )

    result = module._normalize_feed_result(
        "sportytrader",
        {
            "ok": True,
            "date": "2026-06-16",
            "picks": [
                {"source": "SportyTrader", "sport": "MLB", "pick": "Dodgers ML"},
                {"source": "SportyTrader", "sport": "NBA SUMMER", "pick": "Thunder -2.5"},
                {"source": "SportyTrader", "sport": "WNBA", "pick": "Fever -4.5"},
                {"source": "SportyTrader", "sport": "FIFA WC", "pick": "France team total"},
                {"source": "SportyTrader", "sport": "CFB", "pick": "Toledo +10.5"},
                {"source": "SportyTrader", "sport": "NFL", "pick": "Seahawks -3"},
            ],
        },
        "2026-06-16",
        ["nba_summer", "mlb", "wnba", "fifa_world_cup", "cfb", "nfl"],
        "2026-06-16T12:00:00Z",
    )
    split = module._split_provider_result(
        "sportytrader",
        result,
        "2026-06-16",
        ["nba_summer", "mlb", "wnba", "fifa_world_cup", "cfb", "nfl"],
        "2026-06-16T12:00:00Z",
    )

    assert set(split) == {
        "sportytrader_nba_summer",
        "sportytrader_mlb",
        "sportytrader_wnba",
        "sportytrader_fifa_world_cup",
        "sportytrader_cfb",
        "sportytrader_nfl",
    }
    assert split["sportytrader_nba_summer"]["picks"][0]["source"] == "SportyTraderNBASummer"
    assert split["sportytrader_mlb"]["picks"][0]["source"] == "SportyTraderMLB"
    assert split["sportytrader_wnba"]["picks"][0]["source"] == "SportyTraderWNBA"
    assert split["sportytrader_fifa_world_cup"]["picks"][0]["source"] == "SportyTraderFIFAWorldCup"
    assert split["sportytrader_cfb"]["picks"][0]["source"] == "SportyTraderCFB"
    assert split["sportytrader_nfl"]["picks"][0]["source"] == "SportyTraderNFL"


def test_external_feed_refresh_marks_soft_failed_cfb_bucket_without_dropping_mlb():
    module = _load_module(
        "refresh_external_feeds_cfb_soft_fail_test",
        ROOT / "scripts" / "refresh_external_feeds.py",
    )
    result = module._normalize_feed_result(
        "sportytrader",
        {
            "ok": True,
            "date": "2026-09-04",
            "picks": [{"source": "SportyTraderMLB", "sport": "MLB", "pick": "Cubs ML"}],
            "errors": ["cfb: Cloudflare verification"],
            "meta": {"sportErrors": {"cfb": "cfb: Cloudflare verification"}},
        },
        "2026-09-04",
        ["mlb", "cfb"],
        "2026-09-04T12:00:00Z",
    )
    split = module._split_provider_result(
        "sportytrader",
        result,
        "2026-09-04",
        ["mlb", "cfb"],
        "2026-09-04T12:00:00Z",
    )
    assert split["sportytrader_mlb"]["ok"] is True
    assert split["sportytrader_mlb"]["picks"][0]["pick"] == "Cubs ML"
    assert split["sportytrader_cfb"]["ok"] is False
    assert split["sportytrader_cfb"]["picks"] == []
    assert "Cloudflare" in split["sportytrader_cfb"]["error"]


def test_external_feed_refresh_marks_soft_failed_nfl_bucket_without_dropping_mlb():
    module = _load_module(
        "refresh_external_feeds_nfl_soft_fail_test",
        ROOT / "scripts" / "refresh_external_feeds.py",
    )
    result = module._normalize_feed_result(
        "sportytrader",
        {
            "ok": True,
            "date": "2026-09-10",
            "picks": [{"source": "SportyTraderMLB", "sport": "MLB", "pick": "Cubs ML"}],
            "errors": ["nfl: Cloudflare verification"],
            "meta": {"sportErrors": {"nfl": "nfl: Cloudflare verification"}},
        },
        "2026-09-10",
        ["mlb", "nfl"],
        "2026-09-10T12:00:00Z",
    )
    split = module._split_provider_result(
        "sportytrader",
        result,
        "2026-09-10",
        ["mlb", "nfl"],
        "2026-09-10T12:00:00Z",
    )
    assert split["sportytrader_mlb"]["ok"] is True
    assert split["sportytrader_mlb"]["picks"][0]["pick"] == "Cubs ML"
    assert split["sportytrader_nfl"]["ok"] is False
    assert split["sportytrader_nfl"]["picks"] == []
    assert "Cloudflare" in split["sportytrader_nfl"]["error"]


def test_external_feed_refresh_records_runtime_provenance(monkeypatch):
    module = _load_module(
        "refresh_external_feeds_provenance_test",
        ROOT / "scripts" / "refresh_external_feeds.py",
    )
    args = (
        "scores24_wnba",
        {"ok": True, "date": "2026-07-14", "picks": []},
        "2026-07-14",
        ["wnba"],
        "2026-07-14T13:00:00Z",
    )

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    local = module._normalize_feed_result(*args)
    assert local["generatedBy"] == "local:external-feed-refresh"
    assert local["meta"]["from"] == "local"

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    actions = module._normalize_feed_result(*args)
    assert actions["generatedBy"] == "github-actions:external-feed-refresh"
    assert actions["meta"]["from"] == "github-actions"


def test_known_fifa_slate_uses_in_house_cache_before_external_scrapers(monkeypatch, tmp_path):
    import pickgrader_server as server

    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "2026-06-13.json").write_text(
        json.dumps({
            "date": "2026-06-13",
            "models": {
                "fifa_world_cup": {
                    "games": [
                        {"away_team": "Switzerland", "home_team": "Qatar"},
                        {"matchup": "Türkiye @ Australia"},
                    ]
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "fetch_scoreboard", lambda *_args, **_kwargs: {"events": []})

    matchups = server._known_external_slate_matchups("2026-06-13", "fifa_world_cup")
    assert matchups == ["Switzerland @ Qatar", "Türkiye @ Australia"]


def test_external_feed_schedule_requests_nba_summer_wnba_and_fifa_world_cup():
    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    refresh = (ROOT / "scripts" / "refresh_external_feeds.py").read_text(encoding="utf-8")
    server = (ROOT / "pickgrader_server.py").read_text(encoding="utf-8")
    # nba_summer + fifa_world_cup archived 2026-07-19 (seasons ended).
    assert '--sports "nba,mlb,wnba,cfb,nfl"' in workflow
    assert 'default="nba,mlb,wnba,cfb,nfl"' in refresh
    assert '"nba_summer": "nba_summer"' in server
    assert '"wnba": "wnba"' in server
    assert '"fifa_world_cup": "fifa_world_cup"' in server
    assert '"fifa_world_cup": {"label": "FIFA WC"' in server
    assert '"cfb": "cfb"' in server
    assert '"cfb": {"label": "CFB"' in server
    assert '"nfl": "nfl"' in server
    assert '"nfl": {"label": "NFL"' in server
    assert 'football": "fifa_world_cup"' in server
    assert '"ncaaf": "cfb"' in server


def test_scores24_extracts_our_choice_and_normalizes_pick():
    module = _load_module(
        "scores24_choice_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    html = """
    <section>
      <div>Editorial Prediction</div>
      <p>We are backing the home side.</p>
      <div class="choice">
        <div>Our choice</div>
        <div><span>Pittsburgh Pirates Win</span> at odds of <span>-147*</span></div>
        <div>*The odds are relevant for the time of publication.</div>
      </div>
    </section>
    """
    tip, odds = module.extract_our_choice(html)
    assert tip == "Pittsburgh Pirates Win"
    assert odds == -147
    assert module._clean_pick(
        tip,
        {"away": "Miami Marlins", "home": "Pittsburgh Pirates"},
    ) == "Pittsburgh Pirates ML (Miami Marlins @ Pittsburgh Pirates)"


def test_scores24_extracts_structured_editorial_prediction():
    module = _load_module(
        "scores24_structured_choice_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    matchup = {"away": "Los Angeles Angels", "home": "Baltimore Orioles"}
    moneyline_html = r"""
    <html><body>
      <div>W1 -133 W2 +114</div>
      <script>
        window.__DATA__ = "{\"prediction\":[\"one_two\",\"w1\"],\"predictionValue\":\"1.71\",\"hasSummary\":true}";
      </script>
    </body></html>
    """
    tip, odds = module.extract_our_choice(moneyline_html, matchup=matchup)
    assert tip == "Baltimore Orioles Win"
    assert odds == -133

    totals_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"total_over\",\"9_5\"],\"predictionValue\":\"1.87\"}";
      </script>
    </body></html>
    """
    tip, odds = module.extract_our_choice(
        totals_html,
        matchup={"away": "Athletics", "home": "Cincinnati Reds"},
    )
    assert tip == "Total Over (9,5)"
    assert odds == module._decimal_odds_to_american(1.87)

    under_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"total_under\",\"183_5\"],\"predictionValue\":\"1.65\"}";
      </script>
    </body></html>
    """
    tip, odds = module.extract_our_choice(
        under_html,
        matchup={"away": "Phoenix Mercury", "home": "Atlanta Dream"},
    )
    assert tip == "Total Under (183,5)"
    assert odds == module._decimal_odds_to_american(1.65)

    team_total_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"total_t1_under\",\"88_5\"],\"predictionValue\":\"1.62\"}";
      </script>
    </body></html>
    """
    sparks_sun = {"away": "Los Angeles Sparks", "home": "Connecticut Sun"}
    tip, odds = module.extract_our_choice(team_total_html, matchup=sparks_sun)
    assert tip == "Connecticut Sun Total Under (88,5)"
    assert odds == module._decimal_odds_to_american(1.62)
    assert module._clean_pick(tip, sparks_sun) == (
        "Connecticut Sun Total Under (88,5) (Los Angeles Sparks @ Connecticut Sun)"
    )

    away_total_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"total_t2_over\",\"86_5\"],\"predictionValue\":\"1.80\"}";
      </script>
    </body></html>
    """
    tip, odds = module.extract_our_choice(away_total_html, matchup=sparks_sun)
    assert tip == "Los Angeles Sparks Total Over (86,5)"
    assert odds == module._decimal_odds_to_american(1.80)


def test_scores24_nba_summer_config_and_official_matchup_scrape():
    module = _load_module(
        "scores24_nba_summer_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    config = module.SPORT_CONFIG["nba_summer"]
    assert config["espn_league"] == "nba-summer"
    assert config["cache_keys"] == ("nba_summer",)

    detail_url = (
        "https://scores24.live/en/basketball/"
        "m-16-07-2026-dallas-mavericks-oklahoma-city-thunder-prediction"
    )
    listing_html = f'<a href="{detail_url}">Dallas Mavericks Oklahoma City Thunder prediction</a>'
    detail_html = """
    <html><head><title>Dallas Mavericks vs Oklahoma City Thunder Prediction</title></head>
    <body><div><div>Our choice</div><div>Oklahoma City Thunder Handicap (-2.5) at odds of -110*</div></div></body>
    </html>
    """

    class Client:
        def get_html(self, url: str, attempts: int = 3):
            if url == config["listing_url"]:
                return listing_html, 200, False
            return detail_html, 200, False

        def close(self):
            return None

    result = module.scrape_scores24(
        "nba_summer",
        "2026-07-16",
        client=Client(),
        matchups=[
            {
                "away": "Dallas Mavericks",
                "home": "Oklahoma City Thunder",
                "start_time": "2026-07-16T23:00:00Z",
            }
        ],
    )

    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 1
    assert result["picks"][0]["source"] == "Scores24NBASummer"
    assert result["picks"][0]["sport"] == "NBA SUMMER"
    assert result["picks"][0]["matchup"] == "Dallas Mavericks @ Oklahoma City Thunder"


def test_scores24_nba_summer_transport_failure_cannot_publish_false_zero():
    module = _load_module(
        "scores24_nba_summer_transport_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )

    class UnreachableClient:
        def get_html(self, _url: str, attempts: int = 3):
            return "", 0, False

        def close(self):
            return None

    result = module.scrape_scores24(
        "nba_summer",
        "2026-07-16",
        client=UnreachableClient(),
        matchups=[
            {
                "away": "Dallas Mavericks",
                "home": "Oklahoma City Thunder",
                "start_time": "2026-07-16T23:00:00Z",
            }
        ],
    )

    assert result["ok"] is False
    assert "could not reach a Scores24 editorial listing" in result["error"]
    assert result["meta"]["listingResolved"] is False
    assert result["meta"]["missingMatchups"] == [
        "Dallas Mavericks @ Oklahoma City Thunder"
    ]


def test_scores24_nba_summer_reachable_empty_listing_is_valid_abstention():
    module = _load_module(
        "scores24_nba_summer_abstention_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    config = module.SPORT_CONFIG["nba_summer"]

    class EmptyListingClient:
        def get_html(self, url: str, attempts: int = 3):
            if url in config["listing_urls"]:
                return "<html><body>No NBA Summer League predictions today.</body></html>", 200, False
            return "", 404, False

        def close(self):
            return None

    result = module.scrape_scores24(
        "nba_summer",
        "2026-07-16",
        client=EmptyListingClient(),
        matchups=[
            {
                "away": "Dallas Mavericks",
                "home": "Oklahoma City Thunder",
                "start_time": "2026-07-16T23:00:00Z",
            }
        ],
    )

    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 1
    assert result["meta"]["expectedMatchups"] == 0
    assert result["meta"]["matchedPicks"] == 0
    assert result["meta"]["missingMatchups"] == []
    assert result["meta"]["unpublishedMatchups"] == [
        "Dallas Mavericks @ Oklahoma City Thunder"
    ]


def test_scores24_candidate_urls_cover_wrong_dates_and_site_team_aliases():
    module = _load_module(
        "scores24_candidates_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    wnba_urls = module.candidate_prediction_urls(
        "wnba",
        "2026-06-12",
        {"away": "Golden State Valkyries", "home": "Seattle Storm"},
    )
    mlb_urls = module.candidate_prediction_urls(
        "mlb",
        "2026-06-12",
        {"away": "Detroit Tigers", "home": "Cleveland Guardians"},
    )
    fifa_urls = module.candidate_prediction_urls(
        "fifa_world_cup",
        "2026-06-13",
        {"away": "Switzerland", "home": "Qatar"},
    )
    assert any("m-13-06-2026-seattle-storm-w-golden-state-valkyries-w--prediction" in url for url in wnba_urls)
    assert any("cleveland-gardians-detroit-tigers-prediction" in url for url in mlb_urls)
    assert any("m-14-06-2026-qatar-switzerland-prediction" in url for url in fifa_urls)


def test_scores24_matches_official_slate_and_keeps_separate_sources():
    module = _load_module(
        "scores24_slate_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    listing = """
    <a href="/en/basketball/m-12-06-2026-washington-mystics-w-toronto-tempo-prediction">
      Washington Mystics (W) Toronto Tempo (W) Prediction
    </a>
    <a href="/en/basketball/m-14-06-2026-portland-fire-dallas-wings-w--prediction">
      Portland Fire Dallas Wings (W) Prediction
    </a>
    """
    detail = """
    <html><head><title>Washington Mystics vs Toronto Tempo Prediction</title></head>
    <body><div><div>Our choice</div><div>Total points Over (164.5) at odds of -172*</div></div></body>
    </html>
    """

    class FakeClient:
        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-wnba/predictions"):
                return listing, 200, False
            if "washington-mystics" in url and "toronto-tempo" in url:
                return detail, 200, False
            return "", 404, False

    result = module.scrape_scores24(
        "wnba",
        "2026-06-12",
        client=FakeClient(),
        matchups=[
            {
                "away": "Toronto Tempo",
                "home": "Washington Mystics",
                "start_time": "2026-06-12T23:30:00Z",
            }
        ],
    )
    assert result["ok"] is True
    assert result["meta"]["expectedMatchups"] == 1
    assert result["meta"]["matchedPicks"] == 1
    assert result["picks"] == [
        {
            "source": "Scores24WNBA",
            "pick": "Over 164.5 (Toronto Tempo @ Washington Mystics)",
            "tip": "Total points Over (164.5)",
            "sport": "WNBA",
            "odds": -172,
            "units": 1,
            "probability": None,
            "edge": None,
            "decision": "BET",
            "date": "2026-06-12",
            "matchup": "Toronto Tempo @ Washington Mystics",
            "game": "Toronto Tempo @ Washington Mystics",
            "away_team": "Toronto Tempo",
            "home_team": "Washington Mystics",
            "start_time": "2026-06-12T23:30:00Z",
            "source_url": (
                "https://scores24.live/en/basketball/"
                "m-12-06-2026-washington-mystics-w-toronto-tempo-prediction"
            ),
        }
    ]
    assert module.SPORT_CONFIG["mlb"]["source"] == "Scores24MLB"


def test_scores24_distinguishes_unpublished_official_matchup_from_failure():
    module = _load_module(
        "scores24_unpublished_matchup_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )

    class FakeClient:
        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return '<a href="/en/baseball/m-19-06-2026-other-game-prediction">Other game</a>', 200, False
            return "", 404, False

    result = module.scrape_scores24(
        "mlb",
        "2026-06-19",
        client=FakeClient(),
        matchups=[{"away": "San Francisco Giants", "home": "Miami Marlins", "start_time": ""}],
    )

    assert result["ok"] is True
    assert result["meta"]["officialMatchups"] == 1
    assert result["meta"]["expectedMatchups"] == 0
    assert result["meta"]["matchedPicks"] == 0
    assert result["meta"]["missingMatchups"] == []
    assert result["meta"]["unpublishedMatchups"] == ["San Francisco Giants @ Miami Marlins"]


def test_scores24_treats_resolved_empty_official_slate_as_ok():
    module = _load_module(
        "scores24_offday_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )

    result = module.scrape_scores24(
        "wnba",
        "2026-06-29",
        client=module.Scores24Client(browser_fallback=False),
        matchups=[],
    )

    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 0
    assert result["meta"]["expectedMatchups"] == 0
    assert result["meta"]["matchedPicks"] == 0


def test_scores24_cache_fallback_filters_next_central_date(tmp_path):
    module = _load_module(
        "scores24_cache_date_filter_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch_dir = tmp_path
    module.MODEL_CACHE_DIR = monkeypatch_dir
    payload = {
        "date": "2026-07-15",
        "models": {
            "mlb_first_five": {
                "games": [
                    {
                        "away_team": "New York Mets",
                        "home_team": "Philadelphia Phillies",
                        "game_start_time": "2026-07-16T23:10:00Z",
                    }
                ]
            }
        },
    }
    (monkeypatch_dir / "2026-07-15.json").write_text(json.dumps(payload), encoding="utf-8")

    assert module._cache_matchups("mlb", "2026-07-15") == []
    assert module._cache_matchups("mlb", "2026-07-16") == []


def test_scores24_fifa_world_cup_keeps_specialty_market_ungraded():
    module = _load_module(
        "scores24_fifa_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    payload = module._pick_payload(
        module.SPORT_CONFIG["fifa_world_cup"],
        "2026-06-13",
        {"away": "Morocco", "home": "Brazil", "start_time": "2026-06-13T22:00:00Z"},
        "https://scores24.live/en/soccer/m-14-06-2026-brazil-morocco-prediction",
        "Ismael Saibari 1+ Shot on Target",
        115,
    )
    assert payload["source"] == "Scores24FIFAWorldCup"
    assert payload["sport"] == "FIFA WC"
    assert payload["scope"] == "player"
    assert payload["market_type"] == "external_player_prop"
    assert payload["grade_supported"] is False
    assert payload["calibration_excluded"] is True


def test_scores24_fifa_world_cup_preserves_comma_decimal_handicap_identity():
    module = _load_module(
        "scores24_fifa_handicap_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    payload = module._pick_payload(
        module.SPORT_CONFIG["fifa_world_cup"],
        "2026-06-26",
        {"away": "Iraq", "home": "Senegal", "start_time": "2026-06-26T19:00:00Z"},
        "https://scores24.live/en/soccer/senegal-iraq-prediction",
        "Senegal Handicap (-1,5)",
        -152,
    )

    assert payload["pick"] == "Senegal Handicap (-1,5) (Iraq @ Senegal)"
    assert payload["market_type"] == "soccer_asian_handicap"
    assert payload["line"] == -1.5
    assert payload["grade_supported"] is False


def test_scores24_fifa_world_cup_supports_czech_republic_alias():
    module = _load_module(
        "scores24_czech_alias_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    matchup = {"away": "South Africa", "home": "Czechia", "start_time": ""}
    urls = module.candidate_prediction_urls("fifa_world_cup", "2026-06-18", matchup)

    assert any("czech-republic-south-africa" in url for url in urls)
    assert module._matchup_matches_blob(
        matchup,
        "Czech Republic vs South Africa Prediction",
    )


def test_scores24_fifa_world_cup_supports_usa_alias():
    module = _load_module(
        "scores24_usa_alias_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    matchup = {"away": "Australia", "home": "United States", "start_time": ""}
    urls = module.candidate_prediction_urls("fifa_world_cup", "2026-06-19", matchup)

    assert any("usa-australia" in url for url in urls)
    assert module._matchup_matches_blob(matchup, "USA vs Australia Prediction")


def test_scores24_cfb_config_listing_urls_and_official_matchup_scrape():
    module = _load_module(
        "scores24_cfb_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    config = module.SPORT_CONFIG["cfb"]
    assert config["espn_sport"] == "football"
    assert config["espn_league"] == "college-football"
    assert config["espn_query"] == "limit=1000&groups=80"
    assert config["scores24_sport"] == "american-football"
    assert config["source"] == "Scores24CFB"
    assert config["label"] == "CFB"
    assert config["cache_keys"] == ("cfb",)
    assert config["listing_url"].endswith("/l-ncaa-regular-season-standings/predictions")
    assert config["listing_urls"] == (
        "https://scores24.live/en/american-football/l-ncaa-regular-season-standings/predictions",
        "https://scores24.live/en/predictions/american-football",
        "https://scores24.live/en/predictions/american-football/today",
    )
    espn_url = module._espn_scoreboard_url(config, "2026-09-05")
    assert espn_url.endswith("/football/college-football/scoreboard?dates=20260905&limit=1000&groups=80")
    assert callable(module.run_scores24_cfb)

    ncaa_listing = (
        "https://scores24.live/en/american-football/"
        "m-04-09-2026-michigan-state-spartans-toledo-rockets-prediction"
    )
    sport_listing = (
        "https://scores24.live/en/american-football/"
        "m-05-09-2026-usc-trojans-fresno-state-bulldogs-prediction"
    )
    listing_pages = {
        config["listing_urls"][0]: f'<a href="{ncaa_listing}">Michigan State Spartans Toledo Rockets</a>',
        config["listing_urls"][1]: f'<a href="{sport_listing}">USC Trojans Fresno State Bulldogs</a>',
        config["listing_urls"][2]: "<html><body>today</body></html>",
    }
    details = {
        ncaa_listing: """
        <html><head><title>Michigan State Spartans vs Toledo Rockets Prediction</title></head>
        <body><script>window.__DATA__ = "{\\"prediction\\":[\\"handicap2\\",\\"8_5\\"],\\"predictionValue\\":\\"1.98\\"}";</script></body>
        </html>
        """,
        sport_listing: """
        <html><head><title>USC Trojans vs Fresno State Bulldogs Prediction</title></head>
        <body><script>window.__DATA__ = "{\\"prediction\\":[\\"one_two\\",\\"w1\\"],\\"predictionValue\\":\\"1.70\\"}";</script></body>
        </html>
        """,
    }

    class Client:
        def __init__(self):
            self.listing_urls = []

        def get_html(self, url: str, attempts: int = 3):
            if url in listing_pages:
                self.listing_urls.append(url)
                return listing_pages[url], 200, False
            if url in details:
                return details[url], 200, False
            return "", 404, False

        def close(self):
            return None

    client = Client()
    result = module.scrape_scores24(
        "cfb",
        "2026-09-04",
        client=client,
        matchups=[
            {
                "away": "Toledo Rockets",
                "home": "Michigan State Spartans",
                "start_time": "2026-09-04T23:00:00Z",
            }
        ],
    )

    assert result["ok"] is True
    assert result["picks"][0]["source"] == "Scores24CFB"
    assert result["picks"][0]["sport"] == "CFB"
    assert result["picks"][0]["pick"] == (
        "Toledo Rockets Handicap (+8,5) (Toledo Rockets @ Michigan State Spartans)"
    )
    assert client.listing_urls == list(config["listing_urls"])


def test_scores24_cfb_empty_official_slate_is_ok():
    module = _load_module(
        "scores24_cfb_offday_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    result = module.scrape_scores24(
        "cfb",
        "2026-09-08",
        client=module.Scores24Client(browser_fallback=False),
        matchups=[],
    )
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 0
    assert result["meta"]["expectedMatchups"] == 0
    assert result["meta"]["matchedPicks"] == 0


def test_scores24_cfb_aliases_common_nicknames_and_drops_mascot_slugs():
    module = _load_module(
        "scores24_cfb_alias_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    assert module._team_matches("Ole Miss Rebels", "Mississippi Rebels")
    assert module._team_matches("LSU Tigers", "Louisiana State Tigers")
    assert module._team_matches("USC Trojans", "Southern California Trojans")
    assert module._team_matches("Miami Hurricanes", "Miami Florida Hurricanes")
    assert not module._team_matches("Miami Hurricanes", "Miami (OH) RedHawks")
    slugs = module._team_slug_variants("Ohio State Buckeyes", "cfb")
    assert "ohio-state-buckeyes" in slugs
    assert "ohio-state" in slugs
    urls = module.candidate_prediction_urls(
        "cfb",
        "2026-09-05",
        {"away": "Fresno State Bulldogs", "home": "USC Trojans"},
    )
    assert any("usc-trojans-fresno-state-bulldogs" in url for url in urls)
    assert any("/en/american-football/" in url for url in urls)


def test_scores24_parses_numbered_american_football_handicaps():
    module = _load_module(
        "scores24_cfb_handicap_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    matchup = {"away": "Toledo Rockets", "home": "Michigan State Spartans"}
    away_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"handicap2\",\"8_5\"],\"predictionValue\":\"1.98\"}";
      </script>
    </body></html>
    """
    tip, odds = module.extract_our_choice(away_html, matchup=matchup)
    assert tip == "Toledo Rockets Handicap (+8,5)"
    assert odds == module._decimal_odds_to_american(1.98)

    home_html = r"""
    <html><body>
      <script>
        window.__DATA__ = "{\"prediction\":[\"handicap1\",\"24_5\"],\"predictionValue\":\"1.83\"}";
      </script>
    </body></html>
    """
    stanford_miami = {"away": "Miami Hurricanes", "home": "Stanford Cardinal"}
    tip, odds = module.extract_our_choice(home_html, matchup=stanford_miami)
    assert tip == "Stanford Cardinal Handicap (+24,5)"
    assert odds == module._decimal_odds_to_american(1.83)


def test_scores24_cfb_is_wired_soft_fail_across_the_pipeline():
    key = "scores24_cfb"

    refresh = _load_module("refresh_external_feeds_cfb_test", ROOT / "scripts" / "refresh_external_feeds.py")
    assert key in refresh.FEED_RUNNERS
    assert key not in refresh.SPLIT_PROVIDER_FEEDS

    merge = _load_module("merge_external_feed_cfb_test", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    assert key in merge.EXTERNAL_FEED_MODEL_KEYS
    model_merge = _load_module("merge_model_cache_cfb_test", ROOT / "scripts" / "merge_model_cache_payload.py")
    assert key in model_merge.EXTERNAL_FEED_MODEL_KEYS

    site_upcheck = _load_module("site_upcheck_cfb_test", ROOT / "scripts" / "site_upcheck.py")
    assert key not in site_upcheck.REQUIRED_SCORES24_FEED_KEYS

    data_ts = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    assert "scores24_cfb: 'Scores24CFB'" in data_ts
    assert "cfb: 'CFB Model'" in data_ts

    parlay = (ROOT / "scripts" / "build_parlay_cards.py").read_text(encoding="utf-8")
    assert '"scores24_cfb": "Scores24CFB"' in parlay

    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    assert "scores24_cfb" not in workflow
    assert "scores24_nfl" not in workflow

    publisher = (ROOT / "scripts" / "scrapers" / "scores24_publish.sh").read_text(encoding="utf-8")
    assert 'OPTIONAL_FEEDS="${SCORES24_OPTIONAL_FEEDS:-scores24_cfb,scores24_nfl}"' in publisher
    assert 'PUBLISH_FEEDS="${SCORES24_PUBLISH_FEEDS:-scores24_mlb,scores24_wnba}"' in publisher
    assert "will not block MLB+WNBA publish" in publisher
    assert "OPTIONAL_FEED_TIMEOUT" in publisher


def test_scores24_nfl_config_listing_urls_and_official_matchup_scrape():
    module = _load_module(
        "scores24_nfl_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    config = module.SPORT_CONFIG["nfl"]
    assert config["espn_sport"] == "football"
    assert config["espn_league"] == "nfl"
    assert config["scores24_sport"] == "american-football"
    assert config["source"] == "Scores24NFL"
    assert config["label"] == "NFL"
    assert config["cache_keys"] == ("nfl",)
    assert config["listing_url"].endswith("/l-usa-nfl/predictions")
    assert config["listing_urls"] == (
        "https://scores24.live/en/american-football/l-usa-nfl/predictions",
        "https://scores24.live/en/predictions/american-football",
        "https://scores24.live/en/predictions/american-football/today",
    )
    assert all("ncaa" not in url.lower() for url in config["listing_urls"])
    espn_url = module._espn_scoreboard_url(config, "2026-09-10")
    assert espn_url.endswith("/football/nfl/scoreboard?dates=20260910")
    assert callable(module.run_scores24_nfl)

    nfl_listing = (
        "https://scores24.live/en/american-football/"
        "m-10-09-2026-seattle-seahawks-new-england-patriots-prediction"
    )
    listing_pages = {
        config["listing_urls"][0]: f'<a href="{nfl_listing}">Seattle Seahawks New England Patriots</a>',
        config["listing_urls"][1]: "<html><body>sport</body></html>",
        config["listing_urls"][2]: "<html><body>today</body></html>",
    }
    details = {
        nfl_listing: """
        <html><head><title>Seattle Seahawks vs New England Patriots Prediction</title></head>
        <body><script>window.__DATA__ = "{\\"prediction\\":[\\"one_two\\",\\"w1\\"],\\"predictionValue\\":\\"1.83\\"}";</script></body>
        </html>
        """,
    }

    class Client:
        def __init__(self):
            self.listing_urls = []

        def get_html(self, url: str, attempts: int = 3):
            if url in listing_pages:
                self.listing_urls.append(url)
                return listing_pages[url], 200, False
            if url in details:
                return details[url], 200, False
            return "", 404, False

        def close(self):
            return None

    client = Client()
    result = module.scrape_scores24(
        "nfl",
        "2026-09-10",
        client=client,
        matchups=[
            {
                "away": "New England Patriots",
                "home": "Seattle Seahawks",
                "start_time": "2026-09-11T00:20:00Z",
            }
        ],
    )
    assert result["ok"] is True
    assert result["picks"][0]["source"] == "Scores24NFL"
    assert result["picks"][0]["sport"] == "NFL"
    assert "Seattle Seahawks" in result["picks"][0]["pick"]
    assert client.listing_urls == list(config["listing_urls"])


def test_scores24_nfl_empty_official_slate_is_ok():
    module = _load_module(
        "scores24_nfl_offday_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    result = module.scrape_scores24(
        "nfl",
        "2026-09-08",
        client=module.Scores24Client(browser_fallback=False),
        matchups=[],
    )
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 0
    assert result["meta"]["expectedMatchups"] == 0
    assert result["meta"]["matchedPicks"] == 0


def test_scores24_nfl_is_wired_soft_fail_across_the_pipeline():
    key = "scores24_nfl"

    refresh = _load_module("refresh_external_feeds_nfl_test", ROOT / "scripts" / "refresh_external_feeds.py")
    assert key in refresh.FEED_RUNNERS
    assert key not in refresh.SPLIT_PROVIDER_FEEDS

    merge = _load_module("merge_external_feed_nfl_test", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    assert key in merge.EXTERNAL_FEED_MODEL_KEYS
    model_merge = _load_module("merge_model_cache_nfl_test", ROOT / "scripts" / "merge_model_cache_payload.py")
    assert key in model_merge.EXTERNAL_FEED_MODEL_KEYS

    site_upcheck = _load_module("site_upcheck_nfl_test", ROOT / "scripts" / "site_upcheck.py")
    assert key not in site_upcheck.REQUIRED_SCORES24_FEED_KEYS
    assert "nfl" in site_upcheck.REQUIRED_MODEL_KEYS
    assert "cfb" in site_upcheck.REQUIRED_MODEL_KEYS

    data_ts = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    assert "scores24_nfl: 'Scores24NFL'" in data_ts
    assert "nfl: 'NFL Model'" in data_ts

    parlay = (ROOT / "scripts" / "build_parlay_cards.py").read_text(encoding="utf-8")
    assert '"scores24_nfl": "Scores24NFL"' in parlay

    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    assert "scores24_nfl" not in workflow

    publisher = (ROOT / "scripts" / "scrapers" / "scores24_publish.sh").read_text(encoding="utf-8")
    assert "scores24_nfl" in publisher
    assert 'OPTIONAL_FEEDS="${SCORES24_OPTIONAL_FEEDS:-scores24_cfb,scores24_nfl}"' in publisher
    assert 'PUBLISH_FEEDS="${SCORES24_PUBLISH_FEEDS:-scores24_mlb,scores24_wnba}"' in publisher
    assert "will not block MLB+WNBA publish" in publisher


def test_scores24_retries_blocked_matchup_without_hammering_candidates(monkeypatch):
    module = _load_module(
        "scores24_retry_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_ROUNDS", "1")
    detail = """
    <html><head><title>Los Angeles Angels vs Tampa Bay Rays Prediction</title></head>
    <body><div><div>Our choice</div><div>Tampa Bay Rays Win at odds of -179*</div></div></body>
    </html>
    """

    class FakeClient:
        def __init__(self):
            self.detail_calls = 0

        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return "", 200, False
            self.detail_calls += 1
            if self.detail_calls == 1:
                return "Cloudflare", 429, True
            return detail, 200, False

    client = FakeClient()
    result = module.scrape_scores24(
        "mlb",
        "2026-06-12",
        client=client,
        matchups=[{"away": "Tampa Bay Rays", "home": "Los Angeles Angels", "start_time": ""}],
    )
    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 1
    assert client.detail_calls == 2


def test_scores24_rotates_owned_client_after_blocked_cooldown(monkeypatch):
    module = _load_module(
        "scores24_owned_client_retry_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_ROUNDS", "1")
    detail = """
    <html><head><title>San Francisco Giants vs Miami Marlins Prediction</title></head>
    <body><div><div>Our choice</div><div>Miami Marlins Win at odds of +105*</div></div></body>
    </html>
    """

    class FakeOwnedClient:
        instances = []
        detail_urls = []

        def __init__(self):
            self.closed = False
            self.instance_number = len(self.instances) + 1
            self.instances.append(self)

        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return "", 200, False
            self.detail_urls.append(url)
            if self.instance_number == 1:
                return "Cloudflare", 429, True
            if "m-20-06-2026" in url:
                return detail, 200, False
            return "", 404, False

        def close(self):
            self.closed = True

    monkeypatch.setattr(module, "Scores24Client", FakeOwnedClient)
    result = module.scrape_scores24(
        "mlb",
        "2026-06-19",
        matchups=[{"away": "San Francisco Giants", "home": "Miami Marlins", "start_time": ""}],
    )

    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 1
    assert len(FakeOwnedClient.instances) == 2
    assert all(client.closed for client in FakeOwnedClient.instances)
    assert "m-19-06-2026" in FakeOwnedClient.detail_urls[0]
    assert "m-20-06-2026" in FakeOwnedClient.detail_urls[1]


def test_scores24_fails_closed_when_blocked_retry_stays_blocked(monkeypatch):
    module = _load_module(
        "scores24_blocked_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_ROUNDS", "1")

    class FakeClient:
        def __init__(self):
            self.detail_calls = 0

        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return "", 200, False
            self.detail_calls += 1
            return "Cloudflare", 429, True

    client = FakeClient()
    result = module.scrape_scores24(
        "mlb",
        "2026-06-12",
        client=client,
        matchups=[{"away": "Tampa Bay Rays", "home": "Los Angeles Angels", "start_time": ""}],
    )
    assert result["ok"] is False
    assert "blocked before it could finish" in result["error"]
    assert client.detail_calls == 2


def test_scores24_client_can_disable_inner_attempt_sleep(monkeypatch):
    module = _load_module(
        "scores24_attempt_sleep_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_CAMOUFOX_FALLBACK", "false")
    monkeypatch.setenv("SCORES24_REQUEST_ATTEMPTS", "2")
    monkeypatch.setenv("SCORES24_ATTEMPT_RETRY_DELAY_SECONDS", "0")
    slept = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: slept.append(seconds))

    class FakeResponse:
        text = "Cloudflare"
        status_code = 429

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = 0

        def get(self, url: str, timeout: int = 35):
            self.calls += 1
            return FakeResponse()

    session = FakeSession()
    client = module.Scores24Client(session=session, browser_fallback=False, interval_seconds=0)
    client._prefer_camoufox = False
    monkeypatch.setattr(client, "_impersonated_html", lambda _url: ("", 0))

    _html, status, blocked = client.get_html("https://scores24.live/en/baseball/test")

    assert status == 429
    assert blocked is True
    assert session.calls == 2
    assert slept == []


def test_scores24_checkpoint_resumes_without_refetching_resolved(monkeypatch, tmp_path):
    module = _load_module(
        "scores24_checkpoint_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("SCORES24_BLOCK_RETRY_ROUNDS", "0")
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", tmp_path / "cache")
    angels_detail = """
    <html><head><title>Los Angeles Angels vs Tampa Bay Rays Prediction</title></head>
    <body><div><div>Our choice</div><div>Tampa Bay Rays Win at odds of -179*</div></div></body>
    </html>
    """
    marlins_detail = """
    <html><head><title>Miami Marlins vs San Francisco Giants Prediction</title></head>
    <body><div><div>Our choice</div><div>Miami Marlins Win at odds of +105*</div></div></body>
    </html>
    """
    matchups = [
        {"away": "Tampa Bay Rays", "home": "Los Angeles Angels", "start_time": ""},
        {"away": "San Francisco Giants", "home": "Miami Marlins", "start_time": ""},
    ]

    class FirstClient:
        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return (
                    '<a href="/en/baseball/m-12-06-2026-los-angeles-angels-tampa-bay-rays-prediction">'
                    "Los Angeles Angels Tampa Bay Rays Prediction</a>",
                    200,
                    False,
                )
            if "tampa-bay-rays" in url:
                return angels_detail, 200, False
            return "Cloudflare", 429, True

    first = module.scrape_scores24("mlb", "2026-06-12", client=FirstClient(), matchups=matchups)
    assert first["ok"] is False
    assert first["meta"]["matchedPicks"] == 1
    checkpoint = json.loads((tmp_path / "scores24-mlb-2026-06-12.json").read_text(encoding="utf-8"))
    assert len(checkpoint["picks"]) == 1

    class SecondClient:
        def __init__(self):
            self.urls = []

        def get_html(self, url: str, attempts: int = 3):
            self.urls.append(url)
            if url.endswith("/l-usa-mlb/predictions"):
                return "", 200, False
            if "miami-marlins" in url or "san-francisco-giants" in url:
                return marlins_detail, 200, False
            return "", 404, False

    second_client = SecondClient()
    second = module.scrape_scores24("mlb", "2026-06-12", client=second_client, matchups=matchups)
    assert second["ok"] is True
    assert second["meta"]["matchedPicks"] == 2
    assert second["meta"]["checkpointedPicks"] == 1
    assert all("tampa-bay-rays" not in url for url in second_client.urls)


def test_scores24_historical_url_hints_use_committed_slug_and_date_offset(monkeypatch, tmp_path):
    module = _load_module(
        "scores24_hints_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    monkeypatch.setenv("SCORES24_CHECKPOINT_DIR", str(tmp_path / "state"))
    cache_dir = tmp_path / "model_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", cache_dir)
    (cache_dir / "2026-07-11.json").write_text(
        json.dumps(
            {
                "date": "2026-07-11",
                "external_feeds": {
                    "scores24_mlb": {
                        "ok": True,
                        "picks": [
                            {
                                "source": "Scores24MLB",
                                "away_team": "Milwaukee Brewers",
                                "home_team": "Pittsburgh Pirates",
                                "source_url": (
                                    "https://scores24.live/en/baseball/"
                                    "m-10-07-2026-pittsburgh-pirates-milwaukee-brewers-prediction"
                                ),
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    matchup = {"away": "Milwaukee Brewers", "home": "Pittsburgh Pirates", "start_time": ""}
    hints = module._historical_url_hints("mlb", "2026-07-12", matchup)
    assert hints[0] == (
        "https://scores24.live/en/baseball/m-11-07-2026-pittsburgh-pirates-milwaukee-brewers-prediction"
    )
    assert (
        "https://scores24.live/en/baseball/m-12-07-2026-pittsburgh-pirates-milwaukee-brewers-prediction"
        in hints
    )

    detail = """
    <html><head><title>Pittsburgh Pirates vs Milwaukee Brewers Prediction</title></head>
    <body><div><div>Our choice</div><div>Milwaukee Brewers Win at odds of -136*</div></div></body>
    </html>
    """

    class HintClient:
        def __init__(self):
            self.detail_urls = []

        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return "", 200, False
            self.detail_urls.append(url)
            if url == hints[0]:
                return detail, 200, False
            return "", 404, False

    client = HintClient()
    result = module.scrape_scores24("mlb", "2026-07-12", client=client, matchups=[matchup])
    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 1
    assert client.detail_urls[0] == hints[0]
    assert result["picks"][0]["source_url"] == hints[0]


def test_scores24_resolves_listed_matchups_before_url_guesses():
    module = _load_module(
        "scores24_order_test",
        ROOT / "scripts" / "scrapers" / "scores24_scraper.py",
    )
    listing = (
        '<a href="/en/baseball/m-12-06-2026-los-angeles-angels-tampa-bay-rays-prediction">'
        "Los Angeles Angels Tampa Bay Rays Prediction</a>"
    )
    rays_detail = """
    <html><head><title>Los Angeles Angels vs Tampa Bay Rays Prediction</title></head>
    <body><div><div>Our choice</div><div>Tampa Bay Rays Win at odds of -179*</div></div></body>
    </html>
    """
    marlins_detail = """
    <html><head><title>Miami Marlins vs San Francisco Giants Prediction</title></head>
    <body><div><div>Our choice</div><div>Miami Marlins Win at odds of +105*</div></div></body>
    </html>
    """

    class OrderClient:
        def __init__(self):
            self.detail_urls = []

        def get_html(self, url: str, attempts: int = 3):
            if url.endswith("/l-usa-mlb/predictions"):
                return listing, 200, False
            self.detail_urls.append(url)
            if "tampa-bay-rays" in url:
                return rays_detail, 200, False
            return marlins_detail, 200, False

    client = OrderClient()
    result = module.scrape_scores24(
        "mlb",
        "2026-06-12",
        client=client,
        matchups=[
            {"away": "San Francisco Giants", "home": "Miami Marlins", "start_time": ""},
            {"away": "Tampa Bay Rays", "home": "Los Angeles Angels", "start_time": ""},
        ],
    )
    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 2
    assert "tampa-bay-rays" in client.detail_urls[0]


def test_local_scores24_publisher_registers_separate_models():
    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    refresh = (ROOT / "scripts" / "refresh_external_feeds.py").read_text(encoding="utf-8")
    publisher = (ROOT / "scripts" / "scrapers" / "scores24_publish.sh").read_text(encoding="utf-8")
    for model_key in (
        "scores24_nba_summer",
        "scores24_wnba",
        "scores24_mlb",
        "scores24_fifa_world_cup",
        "scores24_cfb",
        "scores24_nfl",
    ):
        assert model_key in refresh  # runner registry keeps archived keys for manual runs
    for model_key in ("scores24_wnba", "scores24_mlb"):
        assert model_key in publisher
    assert "scores24_cfb" in publisher  # optional same-run scrape, not the completeness gate
    assert "scores24_nfl" in publisher
    for model_key in ("scores24_nba_summer", "scores24_fifa_world_cup"):
        assert model_key not in publisher  # archived from the daily local publish
    for model_key in (
        "sportytrader_mlb",
        "sportytrader_nba_summer",
        "sportytrader_wnba",
        "sportytrader_fifa_world_cup",
        "sportytrader_cfb",
        "sportytrader_nfl",
        "sportsgambler_mlb",
        "sportsgambler_nba_summer",
        "sportsgambler_wnba",
        "sportsgambler_fifa_world_cup",
        "sportsgambler_cfb",
        "sportsgambler_nfl",
    ):
        assert model_key in refresh
    assert 'default="sportytrader,sportsgambler"' in refresh
    assert "scores24_wnba" not in workflow
    assert "scores24_fifa_world_cup" not in workflow
    assert "scores24_cfb" not in workflow
    assert "scores24_nfl" not in workflow
    assert 'GH_BIN="$(command -v gh || true)"' in publisher
    assert "SCORES24_BROWSER_FALLBACK=true" in publisher
    assert "SCORES24_CAMOUFOX_FALLBACK=true" in publisher
    assert 'PUBLISH_FEEDS="${SCORES24_PUBLISH_FEEDS:-scores24_mlb,scores24_wnba}"' in publisher
    assert 'OPTIONAL_FEEDS="${SCORES24_OPTIONAL_FEEDS:-scores24_cfb,scores24_nfl}"' in publisher
    assert 'SCORES24_REQUEST_INTERVAL_SECONDS="${REQUEST_INTERVAL}"' in publisher
    assert 'SCORES24_REQUEST_ATTEMPTS="${REQUEST_ATTEMPTS}"' in publisher
    assert 'SCORES24_ATTEMPT_RETRY_DELAY_SECONDS="${ATTEMPT_RETRY_DELAY}"' in publisher
    assert 'SCORES24_PUBLISH_FEED_COOLDOWN_SECONDS' in publisher
    assert '--feeds "${feed_key}"' in publisher
    assert "--date YYYY-MM-DD" in publisher
    assert "SCORES24_DATE" in publisher
    assert "Scores24 refresh incomplete; refusing to publish" in publisher
    assert 'expected != matched' in publisher
    assert "workflow run deploy-pages.yml" in publisher
    assert "Skipped Pages deploy until the full" in publisher
    assert "steps.commit-feeds.outputs.deployable == 'true'" in workflow
    assert 'cron: "10,40 14 * * *"' in workflow
    assert 'cron: "10 20 * * *"' in workflow


def test_sportsgambler_football_short_names_resolve_from_full_team_slugs(monkeypatch):
    module = _load_module('sportsgambler_football_short_names_test', ROOT / 'scripts/scrapers/sportsgambler_scraper.py')
    for sport, short_names, slug, official in (
        ('nfl', '49ers vs Rams', 'san-francisco-49ers-vs-los-angeles-rams', 'San Francisco 49ers @ Los Angeles Rams'),
        ('cfb', 'Rutgers vs Boston College', 'rutgers-scarlet-knights-vs-boston-college-eagles', 'Rutgers Scarlet Knights @ Boston College Eagles'),
    ):
        path = 'nfl' if sport == 'nfl' else 'ncaaf'
        detail_url = f'https://www.sportsgambler.com/betting-tips/{path}/{slug}-prediction-odds-2026-09-11/'
        off_slate_url = f'https://www.sportsgambler.com/betting-tips/{path}/unlisted-team-vs-another-team-prediction-odds-2026-09-11/'
        listing = {'itemListElement': [
            {'item': {'@type': 'SportsEvent', 'name': short_names, 'url': detail_url, 'startDate': '2026-09-11T23:00:00Z'}},
            {'item': {'@type': 'SportsEvent', 'name': short_names, 'url': off_slate_url, 'startDate': '2026-09-11T23:00:00Z'}},
        ]}
        requested = []

        def fake_get(url, **kwargs):
            from types import SimpleNamespace
            requested.append(url)
            if url == detail_url:
                html = '<div class="tpbot_container"><a class="tpbot_tip"><span>Over 48.5 Points @ -110</span></a></div>'
            else:
                html = f'<script type="application/ld+json">{json.dumps(listing)}</script>'
            return SimpleNamespace(status_code=200, text=html)

        monkeypatch.setattr(module.requests, 'get', fake_get)
        runner = module.scrape_nfl if sport == 'nfl' else module.scrape_cfb
        rows = runner(date(2026, 9, 11), [official])
        assert len(rows) == 1
        assert rows[0]['matchup'] == official
        assert rows[0]['tip'] == 'Over 48.5 Points'
        assert rows[0]['odds'] == '-110'
        assert off_slate_url not in requested
