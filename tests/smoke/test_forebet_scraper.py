from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _forebet_row(
    home: str,
    away: str,
    sign: str,
    probs: str,
    odds: tuple[str, ...],
    kickoff: str = "23/07/2026 01:30",
    two_way: bool = False,
) -> str:
    prob_spans = " ".join(f"<span>{p}</span>" for p in probs.split())
    odds_spans = "".join(f"<span>{o}</span>" for o in (*odds, *([""] if two_way else ["no", "no", "no"])))
    fprc_class = "fprc bsk" if two_way else "fprc"
    # Soccer rows carry schema.org microdata; baseball/basketball rows hold
    # bare spans — mirror that so the selectors stay honest.
    if two_way:
        teams = (
            f'<span class="homeTeam"><span>{home}</span></span>'
            f'<span class="awayTeam"><span>{away}</span></span>'
            f'<span class="date_bah">{kickoff}</span>'
        )
    else:
        teams = (
            f'<span class="homeTeam" itemprop="homeTeam"><span itemprop="name">{home}</span></span>'
            f'<span class="awayTeam" itemprop="awayTeam"><span itemprop="name">{away}</span></span>'
            f'<time datetime="2026-07-23" itemprop="startDate"><span class="date_bah">{kickoff}</span></time>'
        )
    return f"""
    <div class="rcnt tr_0">
      <div class="stcn"><a>Us1</a></div>
      <div class="tnms"><div>
        <a class="tnmscn" href="/en/matches/{home.lower().replace(' ', '-')}-{away.lower().replace(' ', '-')}-2465432">
          {teams}
        </a>
      </div></div>
      <div class="{fprc_class}">{prob_spans}</div>
      <div class="predict"><span class="forepr"><span>{sign}</span></span>
        <span class="scrmobpred ex_sc">1 <span class="scrmobpreddash">-</span> 2</span></div>
      <div class="ex_sc tabonly">1 - 2</div>
      <div class="avg_sc tabonly">2.69</div>
      <div class="bigOnly prmod"><span class="lscrsp">+220</span><div class="haodd">{odds_spans}</div></div>
      <div class="lscr_td lResTdSmall"><a>PRE VIEW</a></div>
      <div class="lmin_td smallFontTd lbord"></div>
    </div>
    """


FIXTURE_HTML = "<html><body><div class='schema'>" + "".join(
    (
        # Away-win tip; Forebet name drifts from the ESPN slate name.
        _forebet_row("Philadelphia Union", "New York Red Bulls", "2", "18 30 52", ("-143", "+310", "+320")),
        # Draw tip.
        _forebet_row("Columbus Crew", "New York City FC", "X", "32 37 31", ("-105", "+270", "+260")),
        # Tip with no posted odds.
        _forebet_row("Charlotte FC", "Atlanta United", "1", "61 22 17", ("no", "no", "no")),
        # Alias cases: ESPN says "LA Galaxy" / "St. Louis CITY SC".
        _forebet_row("Los Angeles Galaxy", "Saint Louis City", "2", "24 37 39", ("-105", "+270", "+250")),
        # Not on the official slate; must be excluded.
        _forebet_row("Volta Redonda", "Sao Goncalo RJ", "1", "44 34 22", ("+100", "+220", "+230")),
    )
) + "</div></body></html>"

SLATE = [
    {"away": "Red Bull New York", "home": "Philadelphia Union", "start_time": "2026-07-23T00:30Z"},
    {"away": "New York City FC", "home": "Columbus Crew", "start_time": "2026-07-23T00:30Z"},
    {"away": "Atlanta United FC", "home": "Charlotte FC", "start_time": "2026-07-23T01:15Z"},
    {"away": "St. Louis CITY SC", "home": "LA Galaxy", "start_time": "2026-07-23T03:30Z"},
    {"away": "Seattle Sounders FC", "home": "Austin FC", "start_time": "2026-07-23T01:30Z"},
]


def _module():
    return _load_module("forebet_scraper_test", ROOT / "scripts" / "scrapers" / "forebet_scraper.py")


def test_forebet_mls_config():
    module = _module()
    config = module.SPORT_CONFIG["mls"]
    assert config["espn_league"] == "usa.1"
    assert config["listing_url"].endswith("/en/football-tips-and-predictions-for-usa/mls")
    assert config["source"] == "ForebetMLS"
    assert config["label"] == "MLS"


def test_parse_forebet_rows_decodes_div_layout():
    module = _module()
    rows = module.parse_forebet_rows(FIXTURE_HTML)
    assert len(rows) == 5
    first = rows[0]
    assert (first["home"], first["away"], first["sign"]) == ("Philadelphia Union", "New York Red Bulls", "2")
    assert (first["prob_home"], first["prob_draw"], first["prob_away"]) == (18, 30, 52)
    assert (first["odds_home"], first["odds_draw"], first["odds_away"]) == (-143, 310, 320)
    assert first["predicted_score"] == "1-2"
    assert first["avg_goals"] == 2.69
    # "PRE VIEW" score-cell text and the date cell must never read as scores.
    no_odds = rows[2]
    assert no_odds["odds_home"] is None and no_odds["odds_draw"] is None and no_odds["odds_away"] is None


def test_scrape_forebet_matches_official_slate_only(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_daily_matchups", lambda sport, date_iso, config=None: (SLATE, True))
    result = module.scrape_forebet("mls", "2026-07-22", html=FIXTURE_HTML)
    assert result["ok"] is True
    picks = {pick["tip"]: pick for pick in result["picks"]}

    away_ml = picks["Red Bull New York ML"]
    assert away_ml["source"] == "ForebetMLS"
    assert away_ml["sport"] == "MLS"
    assert away_ml["odds"] == 320
    assert away_ml["probability"] == 0.52
    assert away_ml["decision"] == "BET"
    assert away_ml["units"] == 1
    assert away_ml["market_type"] == "soccer_moneyline"
    assert away_ml["grade_supported"] is True
    assert away_ml["calibration_excluded"] is True
    assert away_ml["matchup"] == "Red Bull New York @ Philadelphia Union"
    assert away_ml["start_time"] == "2026-07-23T00:30Z"
    assert (away_ml["forebet_prob_home"], away_ml["forebet_prob_draw"], away_ml["forebet_prob_away"]) == (18, 30, 52)

    draw = picks["Draw"]
    assert draw["pick"] == "Draw (New York City FC @ Columbus Crew)"
    assert draw["odds"] == 270
    assert draw["market_type"] == "soccer_standard"
    assert draw["grade_supported"] is True

    no_odds = picks["Charlotte FC ML"]
    assert no_odds["odds"] is None
    assert no_odds["probability"] == 0.61

    # Team-name drift resolves through the shared alias table.
    assert picks["St. Louis CITY SC ML"]["odds"] == 250

    # The off-slate Brazilian match is excluded; the unmatched slate game is reported.
    assert result["meta"]["matchedPicks"] == 4
    assert result["meta"]["officialMatchups"] == 5
    assert result["meta"]["unpublishedMatchups"] == ["Seattle Sounders FC @ Austin FC"]
    assert all("Volta Redonda" not in pick["pick"] for pick in result["picks"])


def test_scrape_forebet_fails_closed_when_slate_unresolved(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_daily_matchups", lambda sport, date_iso, config=None: ([], False))
    result = module.scrape_forebet("mls", "2026-07-22", html=FIXTURE_HTML)
    assert result["ok"] is False
    assert result["picks"] == []
    assert "could not resolve" in result["error"]


def test_scrape_forebet_confirmed_off_day_skips_listing_fetch(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_daily_matchups", lambda sport, date_iso, config=None: ([], True))

    def _no_fetch(url):
        raise AssertionError("listing fetch must not run on a confirmed off-day")

    monkeypatch.setattr(module, "_fetch_listing_html", _no_fetch)
    result = module.scrape_forebet("mls", "2026-07-20")
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 0


MLB_HISTORY_HTML = "<html><body><div class='schema'>" + "".join(
    (
        # Same series matchup on consecutive days: only the row nearest the
        # official start may match, never the stale one.
        _forebet_row("Boston Red Sox", "Baltimore Orioles", "1", "62 38", ("-155", "+130"), kickoff="20/07/2026 23:10", two_way=True),
        _forebet_row("Boston Red Sox", "Baltimore Orioles", "2", "49 51", ("-110", "-105"), kickoff="21/07/2026 23:10", two_way=True),
        # W-suffixed basketball naming.
        _forebet_row("Toronto Tempo W", "Las Vegas Aces W", "2", "29 71", ("-", "-"), kickoff="21/07/2026 02:00", two_way=True),
        # Two-way rows never carry an X sign; a malformed one must be dropped.
        _forebet_row("Chicago Cubs", "Detroit Tigers", "X", "50 50", ("-110", "-110"), kickoff="21/07/2026 23:10", two_way=True),
    )
) + "</div></body></html>"

MLB_SLATE = [
    {"away": "Baltimore Orioles", "home": "Boston Red Sox", "start_time": "2026-07-21T23:10Z"},
    {"away": "Las Vegas Aces", "home": "Toronto Tempo", "start_time": "2026-07-21T02:00Z"},
    {"away": "Detroit Tigers", "home": "Chicago Cubs", "start_time": "2026-07-21T23:10Z"},
]


def test_parse_forebet_rows_decodes_two_way_layout():
    module = _module()
    rows = module.parse_forebet_rows(MLB_HISTORY_HTML)
    # The malformed X-sign two-way row is dropped.
    assert len(rows) == 3
    first = rows[0]
    assert first["two_way"] is True
    assert (first["prob_home"], first["prob_draw"], first["prob_away"]) == (62, None, 38)
    assert (first["odds_home"], first["odds_draw"], first["odds_away"]) == (-155, None, 130)


def test_scrape_forebet_two_way_disambiguates_series_games(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "fetch_daily_matchups", lambda sport, date_iso, config=None: (MLB_SLATE, True))
    result = module.scrape_forebet("mlb", "2026-07-21", html=MLB_HISTORY_HTML)
    assert result["ok"] is True
    picks = {pick["matchup"]: pick for pick in result["picks"]}

    series = picks["Baltimore Orioles @ Boston Red Sox"]
    # The 21/07 row (away tip, -105) must win over the stale 20/07 row (home tip).
    assert series["tip"] == "Baltimore Orioles ML"
    assert series["odds"] == -105
    assert series["probability"] == 0.51
    # Two-way picks are calibrated like other MLB/WNBA external feeds and use
    # the generic moneyline grade path — no soccer metadata.
    assert "calibration_excluded" not in series
    assert "market_type" not in series

    wnba = picks["Las Vegas Aces @ Toronto Tempo"]
    assert wnba["tip"] == "Las Vegas Aces ML"
    assert wnba["odds"] is None
    assert wnba["probability"] == 0.71

    # The Cubs game only had the malformed X row, so it goes unpublished.
    assert result["meta"]["unpublishedMatchups"] == ["Detroit Tigers @ Chicago Cubs"]


def test_scrape_forebet_rejects_rows_outside_the_kickoff_window(monkeypatch):
    module = _module()
    slate = [{"away": "Baltimore Orioles", "home": "Boston Red Sox", "start_time": "2026-07-23T23:10Z"}]
    monkeypatch.setattr(module, "fetch_daily_matchups", lambda sport, date_iso, config=None: (slate, True))
    result = module.scrape_forebet("mlb", "2026-07-23", html=MLB_HISTORY_HTML)
    assert result["picks"] == []
    assert result["meta"]["unpublishedMatchups"] == ["Baltimore Orioles @ Boston Red Sox"]


def test_forebet_feeds_are_registered_across_the_pipeline():
    refresh = _load_module("refresh_external_feeds_test", ROOT / "scripts" / "refresh_external_feeds.py")
    for key in ("forebet_mls", "forebet_mlb", "forebet_wnba"):
        assert key in refresh.FEED_RUNNERS
        assert key not in refresh.SPLIT_PROVIDER_FEEDS

    merge = _load_module("merge_external_feed_test", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    assert {"forebet_mls", "forebet_mlb", "forebet_wnba"} <= merge.EXTERNAL_FEED_MODEL_KEYS

    calibration = _load_module("pick_calibration_test", ROOT / "scripts" / "pick_calibration.py")
    assert "forebet_mls" in calibration.CALIBRATION_EXCLUDED_MODEL_KEYS
    # Two-way US-sport feeds calibrate like the other external feeds.
    assert "forebet_mlb" not in calibration.CALIBRATION_EXCLUDED_MODEL_KEYS
    assert "forebet_wnba" not in calibration.CALIBRATION_EXCLUDED_MODEL_KEYS

    data_ts = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    for label in ("forebet_mls: 'ForebetMLS'", "forebet_mlb: 'ForebetMLB'", "forebet_wnba: 'ForebetWNBA'"):
        assert label in data_ts

    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    assert "forebet_mls,forebet_mlb,forebet_wnba" in workflow


def test_football_feeds_match_official_names_and_keep_missing_odds(monkeypatch):
    module = _module()
    for sport, home, away, official_home, official_away in (
        ('nfl', 'Los Angeles Rams', 'San Francisco 49ers', 'Los Angeles Rams', 'San Francisco 49ers'),
        ('cfb', 'Miami', 'Florida A&M', 'Miami Hurricanes', 'Florida A&M Rattlers'),
    ):
        slate = [{'home': official_home, 'away': official_away, 'start_time': '2026-09-11T00:20Z'}]
        monkeypatch.setattr(module, 'fetch_daily_matchups', lambda *args, **kwargs: (slate, True))
        html = ''.join([
            _forebet_row(home, away, '2', '40 60', ('-110', '+100'), kickoff='04/09/2026 02:20', two_way=True),
            _forebet_row(home, away, 'X', '30 40 30', ('+100', '+200', '+300'), kickoff='11/09/2026 02:20'),
            _forebet_row(home, away, '1', '56 44', ('-', '-'), kickoff='11/09/2026 02:20', two_way=True),
            _forebet_row(away, home, '2', '40 60', ('-110', '+100'), kickoff='11/09/2026 02:20', two_way=True),
        ])
        result = module.scrape_forebet(sport, '2026-09-10', html=html)
        assert result['ok'] is True
        assert len(result['picks']) == 1
        pick = result['picks'][0]
        assert pick['tip'] == f'{official_home} ML'
        assert pick['sport'] == sport.upper()
        assert pick['source'] == f'Forebet{sport.upper()}'
        assert pick['probability'] == 0.56
        assert pick['odds'] is None
        assert pick['date'] == '2026-09-10'
        assert pick['start_time'] == slate[0]['start_time']
        assert result['meta']['unpublishedMatchups'] == []


def test_forebet_missing_kickoff_cannot_match_a_dated_game(monkeypatch):
    module = _module()
    slate = [{'home': 'Los Angeles Rams', 'away': 'San Francisco 49ers', 'start_time': '2026-09-11T00:20Z'}]
    monkeypatch.setattr(module, 'fetch_daily_matchups', lambda *args, **kwargs: (slate, True))
    html = _forebet_row('Los Angeles Rams', 'San Francisco 49ers', '1', '56 44', ('-', '-'), kickoff='', two_way=True)
    result = module.scrape_forebet('nfl', '2026-09-10', html=html)
    assert result['picks'] == []
    assert result['meta']['unpublishedMatchups'] == ['San Francisco 49ers @ Los Angeles Rams']


def test_forebet_retries_challenged_html_and_reports_persistent_block(monkeypatch):
    from types import SimpleNamespace
    module = _module()
    blocked = SimpleNamespace(status_code=403, text='Just a moment: Cloudflare')
    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: blocked)
    calls = []
    delivered_html = FIXTURE_HTML + '<script src="https://static.cloudflareinsights.com/beacon.min.js"></script><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'

    def retry(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=200, text=delivered_html)

    monkeypatch.setattr(module.browser_requests, 'get', retry)
    url = module.SPORT_CONFIG['nfl']['listing_url']
    assert module._fetch_listing_html(url) == (delivered_html, '')
    assert calls[0][0] == url
    assert calls[0][1]['impersonate'] == 'chrome'
    monkeypatch.setattr(module.browser_requests, 'get', lambda *args, **kwargs: blocked)
    html, error = module._fetch_listing_html(url)
    assert not html
    assert 'blocked' in error


def test_football_feeds_merge_as_research_without_hiding_model_pass(tmp_path):
    import json
    refresh = _load_module('refresh_forebet_football_test', ROOT / 'scripts' / 'refresh_external_feeds.py')
    merge = _load_module('merge_forebet_football_test', ROOT / 'scripts' / 'merge_external_feed_cache_payload.py')
    date = '2026-09-10'
    models = {}
    for sport in ('cfb', 'nfl'):
        key = f'forebet_{sport}'
        assert key in refresh.FEED_RUNNERS
        assert key in merge.EXTERNAL_FEED_MODEL_KEYS
        models[key] = {'ok': True, 'date': date, 'picks': [
            {'sport': sport.upper(), 'pick': 'Home ML', 'decision': 'BET', 'units': 1},
        ]}
        models[sport] = {'ok': True, 'shadow_mode': False, 'picks': [
            {'sport': sport.upper(), 'pick': 'Home ML', 'decision': 'PASS', 'units': 0},
        ]}
    (tmp_path / f'{date}.json').write_text(json.dumps({'date': date, 'models': models}))
    result = merge.merge_payload({'date': date, 'models': models}, tmp_path)
    for sport in ('cfb', 'nfl'):
        research = result['models'][f'forebet_{sport}']['picks'][0]
        assert research['decision'] == 'PASS'
        assert research['units'] == 0
        assert research['scraped_tip_demoted'] is True
        assert result['models'][sport]['shadow_mode'] is False
        assert len(result['models'][sport]['picks']) == 1
    workflow = (ROOT / '.github/workflows/external-feed-refresh.yml').read_text()
    publisher = (ROOT / 'scripts/scrapers/forebet_publish.sh').read_text()
    for key in ('forebet_cfb', 'forebet_nfl'):
        assert key in workflow
        assert key in publisher
