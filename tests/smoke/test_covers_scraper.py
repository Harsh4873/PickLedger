from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATE = "2026-07-20"
# Pregame relative to the 02:10Z kickoff used across the fixtures.
PREGAME_NOW = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
POSTGAME_NOW = datetime(2026, 7, 21, 4, 0, tzinfo=timezone.utc)

SLATE = [
    {
        "away": "St. Louis Cardinals",
        "home": "Los Angeles Angels",
        "start_time": "2026-07-21T02:10Z",
    },
    # Not promoted on /picks — discoverable only through the odds hub.
    {
        "away": "Pittsburgh Pirates",
        "home": "New York Yankees",
        "start_time": "2026-07-20T23:05Z",
    },
]
WNBA_SLATE = [
    {"away": "Minnesota Lynx", "home": "Seattle Storm", "start_time": "2026-07-21T02:00Z"}
]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _module():
    module = _load_module("covers_scraper_test", ROOT / "scripts" / "scrapers" / "covers_scraper.py")
    module.clear_caches()
    return module


def _tracking(text: str) -> str:
    return json.dumps({"type": "expert pick", "text": text}).replace('"', "&quot;")


TRACK_CURRENT = "STL vs LAA, Mon, Jul 20 • 10:10 PM ET"
TRACK_STALE = "STL vs LAA, Thu, Jun 25 • 7:45 PM ET"


def _expert_card(
    card_id: str,
    types: str,
    team: str,
    selection: str,
    author: str = "Quinn Allen",
    author_slug: str = "quinn-allen",
    player_href: str = "",
    tracking: str = TRACK_CURRENT,
) -> str:
    player = f'<a class="player-link" href="{player_href}"><span></span></a>' if player_href else ""
    return f"""
    <div id="{card_id}" class="pick-cards-expert-component" data-pick="" data-pick-teams="{team}" data-pick-types="{types}">
      <div class="card profile-card">
        <div class="card-thumbnail"><img alt="{author} image"></div>
        <div class="card-text">
          <div><a class="link-underline-primary link-offset-2" href="https://www.covers.com/writers/{author_slug}">{author}</a></div>
          <div class="lh-1">Betting Analyst</div>
        </div>
      </div>
      <div class="w-100 fw-bold small">{player}{selection}</div>
      <div class="picks-best-odds"><a class="deeplink" href="/go/b?q[0].LId=1&q[0].SId=2" data-tracking="{_tracking(tracking)}"><span><b>x</b></span><span><img alt="Novig"></span></a></div>
    </div>
    """


def _projection_row(
    row_id: str,
    market_id: str,
    badge: str,
    category: str,
    prediction: str,
    ev: str,
    best_text: str,
    odds_columns: tuple[str, ...] = (),
) -> str:
    columns = "".join(
        f'<div class="compare-odds-column"><img class="sportsbook-logo" alt="Book"><a class="book-odds">{col}</a></div>'
        for col in odds_columns
    )
    row = f"""
    <tr class="game-projections-container" data-id="{row_id}" data-market-id="{market_id}" data-ev="{ev}" data-rating="{ev}">
      <td><section class="picks-card game-projections-container" data-id="{row_id}" data-market-id="{market_id}">
        <span class="me-2 _badge _badge-sm badge-style-primary-subtle">{badge}</span>
        <span class="category fw-bold">{category}</span>
        <span class="prediction fw-normal">{prediction}</span>
        <div class="picks-best-odds"><a class="deeplink" href="/go/b" data-tracking="{_tracking(TRACK_CURRENT)}">{best_text}<img alt="Novig"></a></div>
        {columns}
      </section></td>
    </tr>
    """
    # Covers emits every section twice (desktop + mobile); mirror that so the
    # dedupe-on-data-id behavior stays honest.
    return row + row


MATCHUP_HTML = f"""
<html><body>
  {_expert_card('41d5fd75-0679-4a71-9d0e-0574f831fc57', 'Best Bets,Moneyline', 'St. Louis Cardinals', 'STL (+101)')}
  {_expert_card('aaf0d27d-2953-4dfb-93c4-0574f831fc58', 'Total', '', 'u9.5 (-131)')}
  {_expert_card('89025bc5-93e8-4111-9222-0574f831fc59', 'Game Prop', 'St. Louis Cardinals', 'o2.5 Team Total (-115)', author='Colby Marchio', author_slug='colby-marchio')}
  {_expert_card('be7ff6ba-d071-4222-8333-0574f831fc60', 'Spread', 'Los Angeles Angels', 'LAA -1.5 (-110)')}
  {_expert_card('e954d5c0-e281-4333-9444-0574f831fc61', 'Earned Runs Allowed', 'Los Angeles Angels', 'Zac Gallen o2.5 Earned Runs Allowed (-141)', player_href='/sport/baseball/mlb/players/13765/zac-gallen')}
  {_expert_card('11111111-2222-4333-9444-000000000001', 'Best Bets,Moneyline', 'St. Louis Cardinals', 'STL (-120)', tracking=TRACK_STALE)}
  {_expert_card('11111111-2222-4333-9444-000000000002', 'First Inning', '', 'NR1 (-120)')}
  {_expert_card('11111111-2222-4333-9444-000000000003', 'Total Bases', 'Los Angeles Angels', 'Mike Trout o1.5 Total Bases (+122)')}
  {_expert_card('11111111-2222-4333-9444-000000000004', 'Total', 'Los Angeles Angels', 'u4.5 (-118)')}
  <table><tbody id="projections-body">
    {_projection_row('128420114', '0', 'MONEYLINE', 'LAA', '-102 moneyline', '3.39', '-102', ('-108', '-102'))}
    {_projection_row('128434538', '0', 'TOTAL', 'Under', '9.0 Total', '6.57', 'u9.5 -133', ('u8.5 +114', 'o9.0 -102', 'u9.0 -105', 'u9.0 -130'))}
    {_projection_row('128423204', '0', 'SPREAD', 'LAA', '+1.5 spread', '9.77', '+1.5 -167', ('+1.5 -175',))}
    {_projection_row('128999999', '154', 'TOTAL RBIS', 'M. Trout (CF)', '0.5 Total RBIs', '12.0', 'o0.5 +170')}
  </tbody></table>
  <div class="pick-detail-section">
    <h3 class="pick-heading">62% picking St. Louis</h3>
    <div class="consensus-pick-progressBar">
      <div class="pick-team pick-team-away"><progress value="62" max="100"></progress></div>
      <div class="pick-team pick-team-home"><progress value="38" max="100"></progress></div>
    </div>
    <p class="total-picks-count">Total Picks&#183;STL 392, LAA 238</p>
  </div>
</body></html>
"""

LEAGUE_HTML = f"""
<html><body>
  <script type="application/ld+json">{json.dumps({
      "@type": "SportsEvent", "identifier": "369418",
      "name": "St. Louis Cardinals vs Los Angeles Angels",
      "startDate": "2026-07-21T02:10:00+00:00",
      "homeTeam": {"name": "Los Angeles Angels"},
      "awayTeam": {"name": "St. Louis Cardinals"},
  })}</script>
  <script type="application/ld+json">{json.dumps({
      "@type": "SportsEvent", "identifier": "369596",
      "name": "Arizona Diamondbacks vs St. Louis Cardinals",
      "startDate": "2026-07-23T21:15:00+00:00",
      "homeTeam": {"name": "St. Louis Cardinals"},
      "awayTeam": {"name": "Arizona Diamondbacks"},
  })}</script>
  <div id="369418" class="picks-card mb-3">
    <span class="teams-component h4"><img alt="St. Louis Cardinals logo"> STL</span>
    <small>@</small>
    <span class="teams-component h4"><img alt="Los Angeles Angels logo"> LAA</span>
    <span class="_badge badge-style-date-time">Mon, Jul 20 &#8226; 10:10 PM ET</span>
    <div class="pick-cards-counter-badge">
      <span class="_badge _badge-sm badge-style-primary-subtle">2 Expert Picks</span>
      <span class="_badge _badge-sm badge-style-label-subtle">10 Computer Picks</span>
    </div>
    <a href="/sport/baseball/mlb/matchup/369418/picks" class="btn btn-primary">View 12 Picks</a>
  </div>
  <div id="369596" class="picks-card mb-3">
    <span class="teams-component h4"><img alt="Arizona Diamondbacks logo"> AZ</span>
    <small>@</small>
    <span class="teams-component h4"><img alt="St. Louis Cardinals logo"> STL</span>
    <div class="pick-cards-counter-badge">
      <span class="_badge _badge-sm badge-style-primary-subtle">6 Expert Picks</span>
    </div>
    <a href="/sport/baseball/mlb/matchup/369596/picks" class="btn btn-primary">View 6 Picks</a>
  </div>
</body></html>
"""


def _props_row(
    row_id: str,
    game_id: str,
    market_name: str,
    market_id: str,
    stars: int,
    prediction: str,
    player_href: str,
    best_text: str,
    diff: str = "+0.1",
    ev: str = "17.75",
) -> str:
    player = f'<span class="category"><a class="player-link" href="{player_href}">P</a></span>' if player_href else '<span class="category">Over</span>'
    row = f"""
    <tr class="game-projections-container" data-game-id="{game_id}" data-id="{row_id}" data-market-name="{market_name}" data-diff="{diff}" data-ev="{ev}" data-rating="{ev}">
      <td><section class="picks-card" data-id="{row_id}" data-market-id="{market_id}">
        {player}
        <span class="prediction">{prediction}</span>
        <div class="projections-container"><div class="projections"><span class="fs-11">0.64</span></div></div>
        <div class="rating"><span><span class="visually-hidden">Star rating: {stars} out of 5</span></span></div>
        <div class="best-odd-container"><div class="picks-best-odds"><a class="deeplink" href="/go/b">{best_text} <img alt="Novig"></a></div></div>
      </section></td>
    </tr>
    """
    return row + row


PROPS_HTML = f"""
<html><body><table><tbody id="projections-body">
  {_props_row('128563339', '369418', 'mlb_game_player_rbis', '154', 4, '0.5 Total RBIs', '/sport/baseball/mlb/players/247593/tim-tawa', 'o0.5 +182')}
  {_props_row('128563340', '369418', 'mlb_game_player_bases', '167', 3, '1.5 Total Bases', '/sport/baseball/mlb/players/1/low-star', 'o1.5 +120')}
  {_props_row('128563341', '369418', 'total-competition', '0', 4, '8.5 Total', '', 'o8.5 -107')}
  {_props_row('128563342', '369418', 'mlb_game_player_mystery', '199', 4, '0.5 Mystery', '/sport/baseball/mlb/players/2/some-guy', 'o0.5 +100')}
  {_props_row('128563343', '369418', 'mlb_game_player_bases', '167', 4, '1.5 Total Bases', '/sport/baseball/mlb/players/247113/dominic-canzone', 'u1.5 -199')}
  {_props_row('128563344', '369999', 'mlb_game_player_rbis', '154', 5, '0.5 Total RBIs', '/sport/baseball/mlb/players/3/future-game', 'o0.5 +150')}
</tbody></table></body></html>
"""

# The odds hub uses "Name vs Name-<id>" identifiers and US-ordered dates.
ODDS_HTML = f"""
<html><body>
  <script type="application/ld+json">{json.dumps({
      "@type": "SportsEvent",
      "identifier": "Pittsburgh Pirates vs New York Yankees-369041",
      "name": "Pittsburgh Pirates vs New York Yankees",
      "startDate": "7-20-2026T19:05:00-04:00",
      "homeTeam": {"name": "New York Yankees"},
      "awayTeam": {"name": "Pittsburgh Pirates"},
  })}</script>
</body></html>
"""

TRACK_NYY = "PIT vs NYY, Mon, Jul 20 • 7:05 PM ET"

NYY_MATCHUP_HTML = f"""
<html><body>
  <table><tbody id="projections-body">
    {_projection_row('228420114', '0', 'MONEYLINE', 'NYY', '-150 moneyline', '5.10', '-150', ('-155', '-150'))}
  </tbody></table>
</body></html>
""".replace(_tracking(TRACK_CURRENT), _tracking(TRACK_NYY))

PAGES = {
    "league": LEAGUE_HTML,
    "odds": ODDS_HTML,
    "matchup:369418": MATCHUP_HTML,
    "matchup:369041": NYY_MATCHUP_HTML,
    "props": PROPS_HTML,
}


def _slate_patch(module, monkeypatch, slate):
    monkeypatch.setattr(
        module, "fetch_daily_matchups", lambda sport, date_iso, config=None: (slate, True)
    )


def test_covers_config():
    module = _module()
    assert module.SPORT_CONFIG["mlb"]["espn_league"] == "mlb"
    assert module.SPORT_CONFIG["wnba"]["cache_keys"] == ("wnba",)
    assert not module.SPORT_CONFIG["wnba"]["has_computer_board"]
    assert not module.SPORT_CONFIG["wnba"]["has_props_board"]
    assert module.ENGINE_SOURCES["props"]["mlb"] == "Covers Props (BAT X)"


def test_parse_league_page_extracts_events_and_groups():
    module = _module()
    league = module.parse_league_page(LEAGUE_HTML)
    assert league["events"]["369418"]["away"] == "St. Louis Cardinals"
    assert league["events"]["369418"]["home"] == "Los Angeles Angels"
    assert league["groups"]["369418"]["expert_count"] == 2
    assert league["groups"]["369418"]["computer_count"] == 10
    assert league["groups"]["369418"]["detail_url"].endswith("/matchup/369418/picks")
    assert league["groups"]["369596"]["expert_count"] == 6


def test_experts_parse_all_markets_and_reject_stale_cards(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    picks = {pick["tip"]: pick for pick in result["picks"]}
    assert len(picks) == 5

    ml = picks["St. Louis Cardinals ML"]
    assert ml["source"] == "Covers · Quinn Allen"
    assert ml["covers_author"] == "Quinn Allen"
    assert ml["covers_author_url"] == "https://www.covers.com/writers/quinn-allen"
    assert ml["covers_author_role"] == "Betting Analyst"
    assert ml["odds"] == 101
    assert ml["scope"] == "team"
    assert ml["market"] == "moneyline"
    assert ml["pick"] == "St. Louis Cardinals ML (St. Louis Cardinals @ Los Angeles Angels)"
    assert ml["decision"] == "BET" and ml["units"] == 1
    assert ml["sport"] == "MLB"

    total = picks["Under 9.5"]
    assert total["market"] == "total" and total["line"] == 9.5 and total["odds"] == -131

    team_total = picks["St. Louis Cardinals Team Total Over 2.5"]
    assert team_total["market"] == "team_total"
    assert team_total["source"] == "Covers · Colby Marchio"
    assert team_total["team"] == "St. Louis Cardinals"

    spread = picks["Los Angeles Angels -1.5"]
    assert spread["market"] == "spread" and spread["line"] == -1.5

    prop = picks["Zac Gallen Over 2.5 Earned Runs Allowed"]
    assert prop["scope"] == "player"
    assert prop["external_player_feed"] is True
    assert prop["market_type"] == "external_player_prop"
    assert prop["player_name"] == "Zac Gallen"
    assert prop["stat_key"] == "pitcher_earned_runs_allowed"
    assert prop["selection"] == "OVER" and prop["line"] == 2.5

    assert result["meta"]["staleCards"] == 1
    assert any("unsupported market" in reason for reason in result["meta"]["skipped"])
    # A prop-labeled card whose player link is missing must be skipped, not
    # published as a full-game total; same for a team-anchored "Total" card.
    assert any("prop card missing player link" in reason for reason in result["meta"]["skipped"])
    assert any("ambiguous team-anchored total" in reason for reason in result["meta"]["skipped"])
    assert result["meta"]["authors"] == ["Colby Marchio", "Quinn Allen"]
    assert all(pick["id"] == pick["covers_external_id"] for pick in result["picks"])


def test_expert_pick_texts_grade_through_the_team_grader(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    import pickgrader_server

    # STL 4 @ LAA 6: Cardinals ML loses, Under 9.5 loses (10 runs), STL team
    # total o2.5 wins, LAA -1.5 wins.
    game = {
        "competitors": [
            {"raw": {"team": {"displayName": "St. Louis Cardinals"}}, "score": 4, "homeAway": "away", "linescores": []},
            {"raw": {"team": {"displayName": "Los Angeles Angels"}}, "score": 6, "homeAway": "home", "linescores": []},
        ],
    }
    graded = {
        pick["tip"]: pickgrader_server.grade_pick(pick, game)
        for pick in result["picks"]
        if pick["scope"] == "team"
    }
    assert graded == {
        "St. Louis Cardinals ML": "loss",
        "Under 9.5": "loss",
        "St. Louis Cardinals Team Total Over 2.5": "win",
        "Los Angeles Angels -1.5": "win",
    }
    for pick in result["picks"]:
        if pick["scope"] == "player":
            parsed = pickgrader_server.parse_player_prop_pick(pick)
            assert parsed is not None
            assert parsed["stat_key"] == pick["stat_key"]


def test_computer_board_emits_line_matched_game_markets(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "computer", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    assert result["meta"]["oddsPageUsed"] is True
    assert result["meta"]["coversMatchups"] == 2
    picks = {pick["tip"]: pick for pick in result["picks"]}
    assert len(picks) == 4

    # The Yankees game exists only on the odds hub, never on /picks.
    nyy = picks["New York Yankees ML"]
    assert nyy["matchup"] == "Pittsburgh Pirates @ New York Yankees"
    assert nyy["odds"] == -150

    ml = picks["Los Angeles Angels ML"]
    assert ml["source"] == "Covers Computer MLB"
    assert ml["odds"] == -102
    assert ml["covers_ev"] == 3.39

    total = picks["Under 9"]
    # The best-odds chip quotes 9.5 while the board line is 9.0 — odds must
    # come from a book at the board's own line AND side: never the drifted
    # chip, never the opposite side's better price (o9.0 -102).
    assert total["line"] == 9.0
    assert total["odds"] == -105

    spread = picks["Los Angeles Angels +1.5"]
    assert spread["odds"] == -167
    assert spread["covers_ev"] == 9.77

    # The player-prop row on the projections board belongs to the props feed.
    assert all(pick["scope"] == "team" for pick in result["picks"])


def test_consensus_majority_and_thresholds(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "consensus", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    assert len(result["picks"]) == 1
    pick = result["picks"][0]
    assert pick["source"] == "Covers Consensus MLB"
    assert pick["tip"] == "St. Louis Cardinals ML"
    assert pick["covers_consensus_pct"] == 62
    assert pick["covers_consensus_votes"] == 630
    assert pick["odds"] is None

    # A 52/48 split must not publish.
    weak = MATCHUP_HTML.replace('value="62"', 'value="52"').replace('value="38"', 'value="48"')
    module.clear_caches()
    result = module.scrape_covers(
        "mlb", "consensus", DATE, pages={**PAGES, "matchup:369418": weak}, now=PREGAME_NOW
    )
    assert result["picks"] == []
    assert any("no clear majority" in note for note in result["meta"]["unpublishedMatchups"])


def test_props_board_star_floor_sides_and_slate_scoping(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "props", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    picks = {pick["player_name"]: pick for pick in result["picks"]}
    # Tim Tawa (4 stars) and Dominic Canzone (4 stars, under side) publish;
    # the 3-star row, the game-market row, the unmapped market, and the
    # off-slate game are all excluded.
    assert set(picks) == {"Tim Tawa", "Dominic Canzone"}

    tawa = picks["Tim Tawa"]
    assert tawa["source"] == "Covers Props (BAT X)"
    assert tawa["tip"] == "Tim Tawa Over 0.5 RBIs"
    assert tawa["stat_key"] == "rbis"
    assert tawa["odds"] == 182
    assert tawa["covers_stars"] == 4
    assert tawa["external_player_feed"] is True
    assert tawa["scope"] == "player"

    canzone = picks["Dominic Canzone"]
    assert canzone["selection"] == "UNDER"
    assert canzone["tip"] == "Dominic Canzone Under 1.5 Total Bases"
    assert canzone["odds"] == -199

    assert any("below star floor" in reason for reason in result["meta"]["skipped"])
    assert any("unsupported prop market" in reason for reason in result["meta"]["skipped"])


def test_pregame_gate_blocks_started_games(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=POSTGAME_NOW)
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["pregameSkipped"] >= 1
    assert any("game already started" in note for note in result["meta"]["unpublishedMatchups"])


def test_carry_forward_preserves_and_replaces(monkeypatch, tmp_path):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", tmp_path)
    committed = {
        "date": DATE,
        "models": {
            "covers_experts_mlb": {
                "ok": True,
                "picks": [
                    {
                        # Same market identity as the fresh Quinn Allen ML pick
                        # (line drift case) — must be replaced, not duplicated.
                        "source": "Covers · Quinn Allen",
                        "covers_matchup_id": "369418",
                        "matchup": "St. Louis Cardinals @ Los Angeles Angels",
                        "market": "moneyline",
                        "team": "St. Louis Cardinals",
                        "pick": "St. Louis Cardinals ML (St. Louis Cardinals @ Los Angeles Angels)",
                        "odds": 110,
                        "result": "pending",
                    },
                    {
                        # A settled pick Covers no longer lists — must survive.
                        "source": "Covers · Departed Author",
                        "covers_matchup_id": "369001",
                        "matchup": "Chicago Cubs @ Detroit Tigers",
                        "market": "total",
                        "direction": "Over",
                        "pick": "Over 8.5 (Chicago Cubs @ Detroit Tigers)",
                        "result": "win",
                    },
                ],
            }
        },
    }
    (tmp_path / f"{DATE}.json").write_text(json.dumps(committed), encoding="utf-8")

    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["meta"]["carriedForward"] == 1
    ml_picks = [
        pick for pick in result["picks"]
        if pick.get("market") == "moneyline" and pick.get("source") == "Covers · Quinn Allen"
    ]
    assert len(ml_picks) == 1
    assert ml_picks[0]["odds"] == 101
    carried = [pick for pick in result["picks"] if pick.get("source") == "Covers · Departed Author"]
    assert len(carried) == 1
    assert carried[0]["result"] == "win"


def test_carry_forward_never_replaces_a_decided_row(monkeypatch, tmp_path):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", tmp_path)
    committed = {
        "date": DATE,
        "models": {
            "covers_experts_mlb": {
                "ok": True,
                "picks": [
                    {
                        # Same identity as the fresh Quinn Allen ML pick, but
                        # already graded (e.g. postponed-game push) — the
                        # fresh duplicate must be discarded, not the record.
                        "source": "Covers · Quinn Allen",
                        "covers_matchup_id": "369418",
                        "matchup": "St. Louis Cardinals @ Los Angeles Angels",
                        "market": "moneyline",
                        "team": "St. Louis Cardinals",
                        "pick": "St. Louis Cardinals ML (St. Louis Cardinals @ Los Angeles Angels)",
                        "odds": 110,
                        "result": "push",
                    }
                ],
            }
        },
    }
    (tmp_path / f"{DATE}.json").write_text(json.dumps(committed), encoding="utf-8")

    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    ml_picks = [
        pick for pick in result["picks"]
        if pick.get("market") == "moneyline" and pick.get("source") == "Covers · Quinn Allen"
    ]
    assert len(ml_picks) == 1
    assert ml_picks[0]["result"] == "push"
    assert ml_picks[0]["odds"] == 110


def test_carry_forward_replaces_pending_side_flips_and_renames(monkeypatch, tmp_path):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", tmp_path)
    committed = {
        "date": DATE,
        "models": {
            "covers_experts_mlb": {
                "ok": True,
                "picks": [
                    {
                        # Same source+game+market slot, opposite side (the
                        # author re-picked LAA after opening on STL) — the
                        # pending row must be replaced, not duplicated.
                        "source": "Covers · Quinn Allen",
                        "covers_matchup_id": "369418",
                        "matchup": "St. Louis Cardinals @ Los Angeles Angels",
                        "market": "moneyline",
                        "team": "Los Angeles Angels",
                        "pick": "Los Angeles Angels ML (St. Louis Cardinals @ Los Angeles Angels)",
                        "result": "pending",
                    },
                    {
                        # Same card GUID under a drifted source label (author
                        # parse failure on a prior run) — replaced by card id.
                        "source": "Covers Expert",
                        "covers_matchup_id": "369418",
                        "covers_external_id": "covers:expert:mlb:369418:aaf0d27d-2953-4dfb-93c4-0574f831fc58",
                        "matchup": "St. Louis Cardinals @ Los Angeles Angels",
                        "market": "total",
                        "direction": "Under",
                        "pick": "Under 9.5 (St. Louis Cardinals @ Los Angeles Angels)",
                        "result": "pending",
                    },
                ],
            }
        },
    }
    (tmp_path / f"{DATE}.json").write_text(json.dumps(committed), encoding="utf-8")

    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["meta"]["carriedForward"] == 0
    ml_picks = [pick for pick in result["picks"] if pick.get("market") == "moneyline"]
    assert [pick["team"] for pick in ml_picks] == ["St. Louis Cardinals"]
    totals = [pick for pick in result["picks"] if pick.get("market") == "total"]
    assert [pick["source"] for pick in totals] == ["Covers · Quinn Allen"]


def test_empty_slate_carries_committed_picks(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(
        module, "fetch_daily_matchups", lambda sport, date_iso, config=None: ([], True)
    )
    monkeypatch.setattr(module, "MODEL_CACHE_DIR", tmp_path)
    committed = {
        "date": DATE,
        "models": {
            "covers_experts_mlb": {
                "ok": True,
                "picks": [
                    {
                        "source": "Covers · Quinn Allen",
                        "covers_matchup_id": "369418",
                        "matchup": "St. Louis Cardinals @ Los Angeles Angels",
                        "market": "moneyline",
                        "team": "St. Louis Cardinals",
                        "pick": "St. Louis Cardinals ML (St. Louis Cardinals @ Los Angeles Angels)",
                        "result": "win",
                    }
                ],
            }
        },
    }
    (tmp_path / f"{DATE}.json").write_text(json.dumps(committed), encoding="utf-8")

    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    # A transiently empty ESPN slate must never wipe published picks.
    assert len(result["picks"]) == 1
    assert result["picks"][0]["result"] == "win"
    assert result["meta"]["carriedForward"] == 1


def test_doubleheader_publishes_only_the_earliest_game(monkeypatch):
    module = _module()
    dh_slate = [
        dict(SLATE[0]),
        {**SLATE[0], "start_time": "2026-07-21T06:10Z"},
    ]
    _slate_patch(module, monkeypatch, dh_slate)
    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is True
    # Game 1 publishes; game 2 is excluded (grading matches by team names
    # only and would settle against game 1's score).
    assert len({pick["covers_matchup_id"] for pick in result["picks"]}) == 1
    assert any("doubleheader game 2" in note for note in result["meta"]["unpublishedMatchups"])


def test_fails_closed_when_slate_unresolved(monkeypatch):
    module = _module()
    monkeypatch.setattr(
        module, "fetch_daily_matchups", lambda sport, date_iso, config=None: ([], False)
    )
    result = module.scrape_covers("mlb", "experts", DATE, pages=PAGES, now=PREGAME_NOW)
    assert result["ok"] is False
    assert "could not resolve" in result["error"]


def test_confirmed_off_day_skips_fetches(monkeypatch):
    module = _module()
    monkeypatch.setattr(
        module, "fetch_daily_matchups", lambda sport, date_iso, config=None: ([], True)
    )

    def _no_fetch(url):
        raise AssertionError("no fetch on a confirmed off-day")

    monkeypatch.setattr(module, "_fetch_html", _no_fetch)
    result = module.scrape_covers("mlb", "experts", DATE)
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["officialMatchups"] == 0


def test_league_page_failure_fails_closed(monkeypatch):
    module = _module()
    _slate_patch(module, monkeypatch, SLATE)
    result = module.scrape_covers("mlb", "experts", DATE, pages={}, now=PREGAME_NOW)
    assert result["ok"] is False
    assert result["picks"] == []


def test_wnba_has_no_computer_or_props_engines():
    module = _module()
    import pytest

    with pytest.raises(ValueError):
        module.scrape_covers("wnba", "computer", DATE, pages=PAGES)
    with pytest.raises(ValueError):
        module.scrape_covers("wnba", "props", DATE, pages=PAGES)


def test_covers_feeds_are_retired_across_the_pipeline(tmp_path):
    refresh = _load_module("refresh_external_feeds_covers_test", ROOT / "scripts" / "refresh_external_feeds.py")
    keys = (
        "covers_experts_mlb",
        "covers_experts_wnba",
        "covers_computer_mlb",
        "covers_consensus_mlb",
        "covers_consensus_wnba",
        "covers_props_mlb",
    )
    for key in keys:
        assert key not in refresh.FEED_RUNNERS
        assert key not in refresh.SPLIT_PROVIDER_FEEDS

    merge = _load_module("merge_external_feed_covers_test", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    assert not (set(keys) & merge.EXTERNAL_FEED_MODEL_KEYS)
    assert set(keys) <= merge.RETIRED_MODEL_KEYS

    model_merge = _load_module("merge_model_cache_covers_test", ROOT / "scripts" / "merge_model_cache_payload.py")
    assert not (set(keys) & model_merge.EXTERNAL_FEED_MODEL_KEYS)
    assert set(keys) <= model_merge.RETIRED_MODEL_KEYS
    assert {"forebet_mls", "forebet_mlb", "forebet_wnba"} <= model_merge.EXTERNAL_FEED_MODEL_KEYS

    current = {
        "date": DATE,
        "models": {
            "mlb_new": {"ok": True, "picks": [{"pick": "Keep model"}]},
            "covers_future_mlb": {"ok": True, "picks": [{"pick": "Drop model"}]},
        },
        "external_feeds": {
            "covers_experts_mlb": {"ok": True, "picks": [{"pick": "Drop feed"}]},
        },
        "covers_props_mlb": {"ok": True, "picks": [{"pick": "Drop alias"}]},
    }
    generated = {
        "date": DATE,
        "models": {
            "wnba": {"ok": True, "picks": [{"pick": "Keep generated"}]},
            "covers_consensus_wnba": {"ok": True, "picks": [{"pick": "Drop generated"}]},
        },
        "external_feeds": {
            "covers_computer_mlb": {"ok": True, "picks": [{"pick": "Drop generated feed"}]},
        },
        "covers_future_wnba": {"ok": True, "picks": [{"pick": "Drop generated alias"}]},
    }
    cache_dir = tmp_path / "model-cache"
    cache_dir.mkdir()
    (cache_dir / f"{DATE}.json").write_text(json.dumps(current), encoding="utf-8")
    for module in (merge, model_merge):
        merged = module.merge_payload(generated, cache_dir)
        assert not any(key.startswith("covers_") for key in merged)
        assert not any(key.startswith("covers_") for key in merged.get("models", {}))
        assert not any(key.startswith("covers_") for key in merged.get("external_feeds", {}))

    rollover_dir = tmp_path / "rollover-cache"
    rollover_dir.mkdir()
    previous = {**current, "date": "2026-07-19"}
    (rollover_dir / "latest.json").write_text(json.dumps(previous), encoding="utf-8")
    rollover_generated = {**generated, "date": DATE}
    for module in (merge, model_merge):
        rolled = module.merge_payload(rollover_generated, rollover_dir)
        assert not any(key.startswith("covers_") for key in rolled)
        assert not any(key.startswith("covers_") for key in rolled.get("models", {}))
        assert not any(key.startswith("covers_") for key in rolled.get("external_feeds", {}))

    profit_desk_text = (ROOT / "scripts" / "build_profit_desk.py").read_text(encoding="utf-8")
    assert 'RETIRED_SOURCE_KEY_PREFIXES = ("covers_",)' in profit_desk_text
    assert '"covers_", "forebet_"' not in profit_desk_text
    assert '"forebet_"' in profit_desk_text

    data_ts = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    assert "const RETIRED_BUCKET_PREFIXES = ['covers_']" in data_ts
    assert "if (isRetiredBucket(modelKey)" in data_ts
    assert "withoutRetiredProfitDeskSources" in data_ts
    assert "covers_experts_mlb: 'Covers Expert'" not in data_ts

    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    default_feeds = (
        "sportytrader,sportsgambler,forebet_mls,forebet_mlb,forebet_wnba,"
        "tennistonic_tennis"
    )
    # Both the dispatch default and schedule fallback retain the active feeds,
    # while a bare refresh can never reactivate a retired provider.
    assert workflow.count(default_feeds) >= 2
    assert "covers_" not in workflow
