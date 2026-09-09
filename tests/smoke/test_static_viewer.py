from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_frontend_is_static_json_only():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "from './firebase'" not in main
    assert "auth.currentUser" not in main
    assert "Firestore" not in main
    assert "ADMIN_BACKEND" not in main
    assert "./data/model_cache/index.json" in data
    assert "cannon_mlb_daily" not in data
    assert '<link rel="stylesheet" href="./src/styles/pickledger.css">' in html
    assert "See how every source has performed across the picks and results collected here." in html
    assert "sportytrader_cfb: 'SportyTraderCFB'" in data
    assert "sportsgambler_cfb: 'SportsGamblerCFB'" in data


def test_viewer_paints_latest_picks_before_history_archive():
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert "?v=${Date.now()}" not in data
    assert "cache: 'no-store'" not in data
    assert "cache: 'no-cache'" in data
    assert "await loadLatestCaches();" in data
    assert "void ensureHistory()" in data
    assert "./data/model_cache/latest.json" in data
    assert "Finding the latest picks..." in html
    assert "loading records" in main
    ready = main[main.index("document.addEventListener('DOMContentLoaded'") :]
    assert "onLatest:" in ready
    assert "onHistory:" in ready
    assert ready.index("onLatest:") < ready.index("onHistory:")


def test_best_bets_filter_records_replay_settled_slates_at_the_footer():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "const DAILY_FILTER_LEDGER_KEY = 'pickledger_bestbets_filter_ledger_v1'" in main
    assert "function invertFadePick(" in main
    assert "function computeDailyFilterLedger(" in main
    assert "function dailyFilterRecordsHtml(" in main
    assert "localStorage.setItem(DAILY_FILTER_LEDGER_KEY" in main
    assert "function isTeamRankingWindowPick(" in main
    assert "function isBestBetsWindowPick(" in main
    assert ".filter(isBestBetsWindowPick)" in main
    assert "buildDailyShortlist(date, false)" in main
    assert '${dailyFilterRecordsHtml()}' in main
    assert "class=\"daily-filter-records\"" in main or 'class="daily-filter-records"' in main
    daily_render = main[main.index("function renderDaily()") : main.index("function renderProfit()")]
    assert "dailyFilterRecordsHtml()" in daily_render
    assert daily_render.index("daily-active-content") < daily_render.index("dailyFilterRecordsHtml()")
    assert "daily-view-tab" in daily_render
    assert "dailyFilterRecordsHtml()" not in daily_render[daily_render.index("daily-view-nav") : daily_render.index("daily-active-content")]
    assert ".daily-filter-records" in css
    assert ".daily-filter-record-line" in css
    assert "127.0.0.1:7374" not in main


def test_initial_theme_prefers_saved_choice_then_tracks_the_os():
    """A fresh visitor must not be forced onto the dark palette.

    The resolver runs before the stylesheet to prevent the dark canvas from
    flashing first; the runtime copy follows OS changes only until the visitor
    makes an explicit choice.
    """
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    settings = (ROOT / "src" / "settings.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    resolver = "matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'"
    assert resolver in html
    assert html.index(resolver) < html.index('href="./src/styles/pickledger.css"')
    assert "storedTheme() ?? systemTheme()" in settings
    assert "if (storedTheme()) return" in settings
    assert "addEventListener('change'" in settings
    ready_handler = main[main.index("document.addEventListener('DOMContentLoaded'") :]
    assert "initTheme();" in ready_handler
    assert ready_handler.index("initTheme();") < ready_handler.index("await loadAllData({")
    assert ':root[data-theme="light"]' in css
    assert 'color-scheme: light' in css


def test_home_date_trigger_bootstraps_central_today_before_data_load():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")

    trigger_start = html.index('id="home-date-trigger-value"')
    trigger = html[trigger_start:html.index("</span>", trigger_start)]
    assert "April 19" not in trigger

    ready_handler = main[main.index("document.addEventListener('DOMContentLoaded'") :]
    bootstrap = ready_handler[:ready_handler.index("await loadAllData({")]
    assert "followCentralToday = true;" in bootstrap
    assert "selectedDate = centralDateKey();" in bootstrap
    assert "lastCentralDate = selectedDate;" in bootstrap
    assert "if (!calendarMonth) calendarMonth = selectedDate.slice(0, 7);" in bootstrap
    assert "document.getElementById('home-date-trigger-value')" in bootstrap
    assert "document.getElementById('home-date-trigger-meta')" in bootstrap
    assert "dateLabel(selectedDate, true)" in bootstrap
    assert "'Today | CT'" in bootstrap


def test_admin_allowlist_is_runtime_configuration_only():
    """No personal address belongs in a public source-level admin allowlist."""
    server = (ROOT / "pickgrader_server.py").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "CLOUD_RUN.md").read_text(encoding="utf-8")
    start = server.index("PICKLEDGER_ADMIN_EMAILS = {")
    end = server.index("\n}\n", start) + 3
    allowlist = server[start:end]

    assert 'os.environ.get("PICKLEDGER_ADMIN_EMAILS", "")' in allowlist
    assert "@" not in allowlist
    assert "leaving it unset closes admin routes to everyone" in docs


def test_frontend_player_mode_is_persisted_isolated_and_team_defaulted():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    settings = (ROOT / "src" / "settings.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'data-pick-mode="team"' in html
    assert 'data-pick-mode="player"' in html
    assert "const PICK_MODE_KEY = 'pickledger_pick_mode'" in settings
    assert "const mode: PickMode = stored === 'player' ? 'player' : 'team'" in settings
    assert "pickledger:modechange" in settings

    assert "./data/model_cache/index.json" in data
    assert "cannon_mlb_daily" not in data
    assert "./data/player_props_cache/index.json" in data
    assert "./data/player_props_cache/latest.json" in data
    assert "let teamPicks: Pick[] = []" in data
    assert "let playerPicks: Pick[] = []" in data
    assert "function isPlayerScopedPick(" in data
    assert "if (isPlayerScopedPick(pick)) playerById.set(pick.id, pick)" in data
    # getAllPicks still routes strictly by mode, so the two pools never mix.
    assert "activePickMode === 'player' ? playerPicks : teamPicks" in data
    assert "decision === 'BET' || decision === 'LEAN' || decision === 'PASS'" in data

    # Scraped-feed toggle: a view filter over the mode-selected pool and
    # nothing else. It must default to off, must only ever filter (never
    # reassign teamPicks/playerPicks), and must leave the underlying rows
    # loaded so flipping it back restores them.
    assert "const HIDE_SCRAPED_KEY = 'pickledger_hide_scraped'" in data
    assert "let hideScrapedPicks = false" in data
    assert "if (hideScrapedPicks) picks = picks.filter(pick => pick.scraped !== true)" in data
    assert "function isScrapedBucket(" in data
    assert 'id="scraped-mode-toggle"' in html
    assert "toggleScrapedPicks" in main
    assert "hide-scraped" in css

    # Tennis toggle: same view-filter shape, so tennis volume can leave
    # home, rankings, search, and the shortlist together without deleting rows.
    assert "const HIDE_TENNIS_KEY = 'pickledger_hide_tennis'" in data
    assert "let hideTennisPicks = false" in data
    assert "if (hideTennisPicks) picks = picks.filter(pick => !isTennisPick(pick))" in data
    assert 'id="tennis-mode-toggle"' in html
    assert "toggleTennisPicks" in main
    assert "hide-tennis" in css
    assert "NO TENNIS" in main

    assert "const activeFilters = new Set<string>()" in main
    assert "activeFilters.clear()" in main
    assert "selectedDate = ''" in main
    assert "search.value = ''" in main
    assert "function isOpenPick(" in main
    assert "pick.result === 'pending' && !isUnsupportedPendingPick(pick) && isPublishedDailyPick(pick)" in main
    assert "dailyDecision(pick) === 'PASS'" in main
    assert "const pending = getAllPicks().filter(isOpenPick)" in main
    assert "UNTRACKED" in main
    assert "mlbLivePlayerStat(" in main
    assert "espnPlayerStat(" in main
    assert "PLAYER_PROPS_ML_FIRST_SNAPSHOT_AT" in data
    assert "isMlEraPlayerProp(pick)" in data
    assert ".pick-mode-segment" in css
    assert "body.mobile-app-mode .pick-mode-segment" in css
    assert "@media (max-width: 700px)" in css


def test_research_details_use_generator_schema_fields_across_pick_views():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    for field in ("full_kelly", "quarter_kelly", "confidence", "reason", "key_factors"):
        assert f"{field}?" in data
        assert f"pick.{field}" in main
    assert "function researchDetailsHtml(" in main
    assert "Quarter Kelly" in main
    assert "Full Kelly" in main
    assert "Key factors" in main
    assert "expandedResearchPickKeys" in main
    assert "data-research-pick-card" in main
    assert "isPlayer ? '' : `<span class=\"home-feed-row-sport\"" in main
    assert "function bindResearchDetailCards(" in main
    assert "bindPickCards(results)" in main
    assert "function parlayCardHtml(" in main
    assert "Show research details" in main
    assert ".home-player-details" in css
    assert ".home-player-extra" in css
    assert ".home-feed-row.expanded .home-player-extra" in css
    assert ".home-player-factors" in css
    assert 'body[data-pick-mode="player"] .home-feed-row-pick' in css
    player_pick_css = css[css.index('body[data-pick-mode="player"] .home-feed-row-pick'):]
    assert "white-space: normal" in player_pick_css[:350]
    assert "overflow: visible" in player_pick_css[:350]
    assert 'body.mobile-app-mode[data-pick-mode="player"] .home-feed-row' in css


def test_home_team_pick_text_expands_on_hover_focus_and_tap():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'data-home-pick-text role="button" tabindex="0" aria-expanded="false"' in main
    assert "function bindHomePickTextExpansion(" in main
    assert "row.classList.toggle('pick-text-expanded')" in main
    assert "bindHomePickTextExpansion(container)" in main
    assert "@media (hover: hover) and (pointer: fine)" in css
    assert ".home-feed-row:hover .home-feed-row-pick" in css
    assert ".home-feed-row:focus-visible .home-feed-row-pick" in css
    assert ".home-feed-row-pick[data-home-pick-text]:focus-visible" in css
    assert ".home-feed-row.pick-text-expanded .home-feed-row-pick" in css
    expanded_css = css[css.index(".home-feed-row:hover .home-feed-row-pick"):]
    assert "white-space: normal" in expanded_css[:500]
    assert "overflow: visible" in expanded_css[:500]
    assert "text-overflow: clip" in expanded_css[:500]


def test_header_brand_and_freshness_copy_are_friendly_and_accurate():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'class="brand-home" href="#home" onclick="goHome(event)"' in html
    assert "function goHome(" in main
    assert "function latestPayloadTimestamp(" in data
    assert "Picks updated ${updatedAgoLabel(status.updatedAt)}" in main
    # The header keeps one consolidated status line; the old badge and
    # duplicate refresh line were removed in the declutter pass.
    assert "Models refresh each morning and again around 3:30 PM CT" not in html
    assert "Scores are checked automatically every 15 minutes" not in html
    assert 'id="sync-status"' in html
    assert 'id="refresh-status"' not in html
    assert "cache ${status.date}" not in main
    assert ".brand-home" in css


def test_static_viewer_keeps_public_tabs_and_client_grading():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    for tab in ("home", "search", "rankings", "daily", "profit"):
        assert f"id=\"tab-{tab}\"" in html
    assert 'id="tab-trends"' not in html
    assert ">TRENDS</button>" not in html
    assert 'onclick="switchTab(\'daily\')">BEST BETS</button>' in html
    # The standalone Parlays tab merged into Profit Desk (2026-07-19).
    assert ">PARLAYS</button>" not in html
    assert 'onclick="switchTab(\'profit\')">PROFIT DESK</button>' in html
    assert ">YOUR BETS</button>" not in html
    assert html.index(">BEST BETS</button>") < html.index(">PROFIT DESK</button>")
    assert "async function refreshAutoGrades()" in main
    assert "async function gradeDate(" in main
    assert "site.api.espn.com" in main
    assert "setLocalResult(pick.id" in main
    assert "await loadAllData({ includeHistory: false });" in main
    assert "DISPLAY_TIME_ZONE = 'America/Chicago'" in main
    assert "function centralDateKey(" in main
    assert "isOpenPick(pick) && pickDateKey(pick) === selectedDate" in main
    assert "window.setInterval(() => void refreshForCentralClock(), AUTO_REFRESH_MS)" in main
    assert "Find a team, matchup, or source in the selected date’s open picks" in html
    assert "embeddedResult === 'pending' ? localResult : embeddedResult" in data
    assert "function isTrackedPick(" in data
    assert "decision === 'BET' || decision === 'LEAN'" in data
    assert "pick.shadow_mode !== true && isTrackedPick(pick)" in data
    assert "function renderRankings()" in main
    assert "function renderSearch()" in main
    assert "getSourceStatuses" in main
    assert "getResearchPicks" in main
    assert "college-football" in main
    assert 'id="research-board"' in html


def test_rich_static_viewer_restores_consensus_table_and_scores():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "function canonicalTrendSignal(" in main
    assert "matching: !group.pass && new Set(group.picks.map(sourceName)).size >= 2" in main
    assert ".trend-market.matching" in css
    assert "function renderDayOfWeekTable(comparablePicks: Pick[]): void" in main
    assert 'class="dow-table"' in main
    assert 'id="dow-overall-heatmap"' not in html
    assert "async function refreshHomeScores(" in main
    assert "homeScoreChipHtml(" in main
    assert "Open ESPN box score" in main


def test_source_rankings_expand_period_records_and_static_cards_do_not_fake_clicks():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "function sourceRecordLines(" in main
    for label in ("TODAY", "YESTERDAY", "LAST 7 DAYS", "ALL TIME"):
        assert f"label: '{label}'" in main
    assert "function isSettledPick(" in main
    assert "const PLAYER_PROP_RANKING_START_DATE = '2026-06-23'" in main
    assert "if (activePickMode !== 'player') return picks" in main
    assert "date >= PLAYER_PROP_RANKING_START_DATE" in main
    assert "function rankingWindowLabel(" in main
    assert "function picksForRankingBucket(" in main
    assert "sourceRecordLines(picksForRankingBucket(scopedPicks, item.source), centralDateKey())" in main
    assert 'data-source-card="${escapeHtml(item.source)}"' in main
    assert 'role="button" tabindex="0" aria-expanded="${expanded}"' in main
    assert "function bindSourceCards(" in main
    assert "View period records" in main
    assert 'id="source-rankings-title"' in html
    assert 'id="source-rankings-subtitle"' in html
    assert 'id="dow-subtitle"' in html
    assert "Select a source for today, yesterday, last 7 days, and all-time records." in html
    assert ".source-expand-control" in css
    assert ".source-card.expanded .source-deep-dive" in css
    assert ".trend-game-card:hover" not in css
    assert ".search-card:hover" not in css
    assert ".sport-card:hover" not in css
    assert ".home-game-card:hover" not in css
    assert ".daily-bet-card:hover" not in css


def test_profit_desk_is_its_own_precomputed_decision_first_tab():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    for section in ("Live Card", "Watchlist & Rejections", "How a pick earns promotion"):
        assert section in main
    assert 'id="profit-container"' in html
    assert "type ProfitView = 'card' | 'watchlist' | 'method'" in main
    assert "let profitView: ProfitView = 'card'" in main
    assert "function renderProfit(" in main
    assert "getProfitDeskPayload(key)" in main
    assert "function profitDeskCandidateCard(" in main
    assert "function profitDeskMethodHtml(" in main
    assert "Profit Desk Date" in main
    assert "function toggleProfitDatePicker(" in main
    assert "role=\"tablist\" aria-label=\"Profit Desk views\"" in main
    assert "Sit out" in main
    assert "RESEARCH ONLY • 0U" in main
    assert "No recommendation" in main
    assert "will not improvise a recommendation from raw pick feeds or client-side scoring" in main
    assert "Conservative probability" in main
    assert "Expected value" in main
    assert "Pr(EV &gt; 0)" in main
    assert "distinct dates" in main
    assert "Flat-stake evidence" in main
    assert "LIVE STAKE" in main
    assert "Research context is not live proof" in main
    assert "CLOSING LINE" in main
    assert "record.avgClv" in main
    assert "EDGE clears strict segment-level market-alpha gates" in main
    assert "./data/profit_desk/index.json" in data
    assert "./data/profit_desk/latest.json" in data
    assert "export interface ProfitDeskPayload" in data
    assert "export function getProfitDeskPayload(" in data
    assert "liveRecordToDate" in data
    assert ".profit-decision" in css
    assert ".profit-candidate" in css
    assert ".profit-candidate.tier-edge::before" in css
    assert ".profit-shadow-stake.is-live" in css
    assert ".profit-method-steps" in css
    assert ".profit-sport-filter" in css


def test_best_bets_shortlist_is_fully_restored_on_the_daily_tab():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'onclick="switchTab(\'daily\')">BEST BETS</button>' in html
    assert "type DailyView = 'featured' | 'picks' | 'consensus' | 'sources' | 'research'" in main
    assert "let dailyView: DailyView = 'featured'" in main
    assert "function renderDaily(" in main
    assert "The Shortlist" in main
    assert "function dailyPickScore(" in main
    assert "Best Bets Date" in main
    assert "Featured Picks" in main
    assert "function isFeaturedPlayablePick(" in main
    assert "return isTeamRankingWindowPick(pick)" in main
    assert "const FEATURED_SOURCES = new Set([" in main
    assert "'MLB Total'" in main
    assert "'WNBA ML'" in main
    assert "FEATURED_JUICE_EXCEPTIONS" in main
    assert "Sit this one out" in main
    for section in ("Top Picks", "Consensus Signals", "Hot Sources", "Research Queue"):
        assert section in main
    assert "MODEL GREENLIGHT" in main
    assert "PROBABILITY LEADER" in main
    assert "PRICEY FAVORITE" in main
    assert "Quick read, not a blind card." in main
    assert ".daily-hero" in css
    assert ".daily-view-shell" in css
    assert ".daily-bet-card" in css


def test_profit_and_roi_exclude_missing_assumed_and_unverified_prices():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")

    assert "function normalizedPriceProvenance(" in data
    assert "assumed|synthetic|proxy|fallback|default|estimated|model[_ ]price" in data
    assert "raw.market_priced === true && observedMarker" in data
    assert "if (pick.price_verified !== true) return 0" in data
    assert "const pricedPicks = picks.filter(pick => pick.price_verified === true" in main
    assert "P/L untracked" in main


def test_rankings_show_untracked_units_instead_of_zero_when_nothing_is_priced():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    # Buckets with no verified-price settled picks must never render "+0u"
    # as if they broke even; they show an untracked marker instead.
    assert "function trackedUnits(" in main
    assert "return stats.priced ? signedUnits(stats.net) : '—'" in main
    assert "priced: pricedPicks.filter(isSettledPick).length" in main
    assert "P/L untracked — no verified-price picks yet" in main
    assert "'— (no priced picks)'" in main
    assert "Units and ROI count only picks settled at verified sportsbook prices." in html
    assert '<div class="stat-box-val" id="stat-units">&mdash;</div>' in html


def test_parlays_tab_renders_card_level_filters_and_rankings():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_parlay_cards.py").read_text(encoding="utf-8")

    for section in ("Edge Double", "Prop Double"):
        assert section in builder
    assert "type ParlayView = string" in main
    assert "let parlayView: ParlayView = 'all'" in main
    assert "let parlayResultMode: ResultMode = 'pending'" in main
    assert "function renderParlays(" in main
    assert "function setParlayView(" in main
    assert "function setParlayResultMode(" in main
    assert "function parlayFilterOptions(" in main
    assert "function parlayCategoryOptions(" in main
    assert "function parlayCardHtml(" in main
    assert "function parlayRankingCardsForDate(" in main
    assert ".filter(payload => !engineVersion || payload.engineVersion === engineVersion)" in main
    assert "dedupeParlayCards(historical.length ? historical : fallbackCards)" in main
    assert "function parlayRankingsPanel(" in main
    assert "Parlay Rankings" in main
    assert "Whole-card records" in main
    assert "Team / Player" in main
    assert "Switch to ${otherMode === 'team' ? 'Team' : 'Player'} mode for this slate" in main
    assert "ENGINE_VERSION = \"parlay_cards_v6_proven_legs\"" in builder
    assert "def _card_has_positive_ev(" in builder
    assert "ENGINE_CUTOVER_DATE = \"2026-07-01\"" in builder
    assert "Records count each whole parlay slip once" in main
    assert "function parlayCardsForMode(" in main
    assert "function parlayCardPickMode(" in main
    assert "Disciplined 2-leg slips from sources with proven trailing edge over market prices." in main
    assert "Disciplined 2-leg slips from consensus-qualified, market-priced player props." in main
    assert "Parlay Date" in main
    assert "role=\"tablist\" aria-label=\"Parlay board filters\"" in main
    assert ".daily-view-nav" in css
    assert ".daily-view-select-wrap" in css
    assert ".parlay-grid" in css
    assert ".parlay-card" in css
    assert ".parlay-metrics" in css
    assert ".parlay-leg-list" in css


def test_soccer_consensus_keeps_lines_and_specialty_markets_distinct():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    signals = main[main.index("function canonicalTrendSignal("):main.index("function trendSignalGroups(")]
    assert "asian-handicap" in signals
    assert "function canonicalTrendLine(" in main
    assert "canonicalTrendLine(namedHandicap[3])" in signals
    assert "canonicalTrendLine(asian[2])" in signals
    assert "spread:${canonicalTeamForPick(pick, spread[1])}:${canonicalTrendLine(spread[2])}" in signals
    assert "(?:[.,]\\d+)?" in signals
    assert "total:${total[1].toLowerCase()}:${total[2]}" in signals
    assert "(?:ML|moneyline|to win|wins?)$/i" in signals


def test_player_mode_keeps_best_bets_available_and_prop_sources_separate():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    assert 'data-player-hidden-tab="trends"' not in html
    assert "function syncModeTabs(" not in main
    assert 'onclick="switchTab(\'daily\')">BEST BETS</button>' in html
    assert ">PARLAYS</button>" not in html
    assert "dailyView = 'featured'" in main
    assert "profitView = 'card'" in main
    assert "parlayView = 'all'" in main
    assert "Parlay filter" in main
    assert "const requestedDate = selectedDate || today" in main
    assert "getParlayCardsPayload(requestedDate)" in main
    assert "function playerRankingEpoch(" in main
    assert "function rankingComparablePicks(" in main
    assert "const PLAYER_PROP_RANKING_START_DATE = '2026-06-23'" in main
    assert "const MLB_INNING_RANKING_START_DATE = '2026-08-25'" in main
    assert "if (source === 'MLB Inning')" in main
    assert "if (activePickMode !== 'player') return picks" in main
    assert "function latestAvailableDateKey(" in main
    assert "function playerModelRank(" in main
    assert "return 10000 - modelRank" in main
    assert "function consensusModelPanelHtml(" in main
    assert "function consensusApplicableModelLabels(" in main
    assert "startsWith(`${sportPrefix}_`)" in main
    assert "function playerRankingNames(" in main
    assert "function rankingBucketNames(" in main
    assert "function addPickToRankingBuckets(" in main
    assert "scopedPicks.forEach(pick => addPickToRankingBuckets(bySource, pick))" in main
    assert "rankingBucketNames(pick).forEach(source =>" in main
    assert "? 'Model Rankings' : 'Source Rankings'" in main
    assert "? 'Model' : 'Source'" in main
    assert "home-player-model-stack" in main
    assert "Models</strong>" in main
    assert "activePickMode === 'player' ? 'Player Prop' : 'Team'" in main
    for source in ("NBAPlayerProps", "MLBPlayerProps", "WNBAPlayerProps"):
        assert source in data
    assert "playerProp && fallbackSource" in data
    assert ".home-player-model-stack" in (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")


def test_mlb_walk_props_rank_as_their_own_model():
    """Walks come out of the blended MLB prop bucket and rank on their own,
    the same way WNBA3PM does — resolved per row at load time so the split is
    retroactive across every committed prop day."""
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")

    assert "const MLB_WALKS_SOURCE = 'MLBWalks'" in data
    assert "const MLB_PLAYER_PROPS_MODEL_KEY = 'mlb_player_props'" in data
    assert "function isWalkPropMarket(" in data
    assert "function playerPropSourceLabel(" in data
    # stat_key is the field every committed prop row carries; market_type only
    # appeared later, so it can never be the primary key for the split.
    assert "String(raw.stat_key || raw.market_type || raw.market || '')" in data
    assert ".includes('walk')" in data
    # Per row, not per bucket — one model key now feeds two ranked sources.
    assert "addBucket(bucket, raw => playerPropSourceLabel(modelKey, raw))" in data
    assert "bucket.forEach(raw => records.push({ raw, source: sourceFor(raw) }))" in data


def test_home_filters_prioritize_primary_sports_and_use_more_menu():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "const PRIMARY_FILTERS = ['ALL', 'NFL', 'CFB', 'MLB', 'WNBA', 'MLS', 'TENNIS']" in main
    assert "const ARCHIVED_SPORTS = new Set(['NBA', 'NBA SUMMER', 'FIFA WC'])" in data
    assert "!ARCHIVED_SPORTS.has(pick.sport)" in data
    assert "'MLB NEW': 'MLB Model'" in data
    assert "'FIFA WC In-House': 'FIFA Model'" in data
    assert "if (filter === 'NBA SUMMER') return 'SUMMER'" in main
    assert "filter === 'FIFA WC' ? 'FIFA' : filter" in main
    assert "function toggleHomeFilter(" in main
    assert "activeFilters.has(pick.sport)" in main
    assert "activeFilters.has(sourceName(pick))" in main
    assert "aria-pressed=\"${filterActive(filter)}\"" in main
    assert "activeFilterSummary()" in main
    assert 'id="filter-more-btn"' in main
    assert "extraFilters.map(filterButton)" in main
    assert ".filter-more-wrap" in css
    assert ".filter-dropdown.open" in css
    assert "body.mobile-app-mode .filter-more-wrap" in css
    assert "position: static" in css[css.index("body.mobile-app-mode .filter-more-wrap"):][:120]
    mobile_filter = css[css.index("body.mobile-app-mode .filter-bar"):]
    assert "overflow: visible" in mobile_filter[:220]


def test_your_bets_subsystem_is_fully_removed():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    # The dead personal-ledger feature was deleted outright: it never had a
    # tab or container, so no code, markup, or CSS may reference it. User
    # localStorage entries are simply left untouched.
    for source in (main, html, css):
        assert "your-bet" not in source.lower()
        assert "yourbet" not in source.lower()
    assert "UserBet" not in main
    assert ">YOUR BETS</button>" not in html
    assert 'id="tab-your-bets"' not in html
    # Parlays render inside the merged Profit Desk tab.
    assert 'id="tab-parlays"' not in html
    assert 'id="parlays-container"' in html
    assert ".add-ledger-btn" not in css


def test_phone_toggle_keeps_brand_visible_and_more_menu_unclipped():
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    mobile_header = css[css.index("body.mobile-app-mode header {"):]
    assert "grid-template-columns: minmax(0, 1fr)" in mobile_header[:260]
    assert "body.mobile-app-mode .brand-home" in css
    brand = css[css.index("body.mobile-app-mode .brand-home"):]
    assert "width: max-content" in brand[:180]
    assert "overflow: visible" in brand[:180]


def test_tab_ordering_prioritizes_home_start_time_and_actionable_picks_elsewhere():
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")

    for helper in (
        "function pickStartTimestamp(",
        "function gameStartTimestamp(",
        "function compareGameStartAsc(",
        "function startBucket(",
        "function compareActionableStart(",
        "function comparePickActionableStart(",
        "function compareDailyConsensusSignal(",
        "function compareHomePickRows(",
    ):
        assert helper in main
    assert "return timestamp > now ? 0 : 2" in main
    assert "if (leftBucket !== rightBucket) return leftBucket - rightBucket" in main
    assert "return leftBucket === 2 ? right - left : left - right" in main
    assert "const sortedGames = [...groups.entries()].sort((left, right) => compareGameStartAsc(left[1], right[1]))" in main
    assert "const sortedPicks = [...picks].sort(compareHomePickRows)" in main
    assert "homeDecisionRank(left) - homeDecisionRank(right)" in main
    assert "(pickProbability(right) || 0) - (pickProbability(left) || 0)" in main
    assert ".sort(comparePickActionableStart);" in main
    assert "comparePickActionableStart(a.primary, b.primary)" in main
    assert "comparePickActionableStart(left.game, right.game)" in main
    assert ".sort(comparePickActionableStart));" in main


def test_cache_manifest_lists_committed_dated_payloads():
    manifest = json.loads((ROOT / "data" / "model_cache" / "index.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    assert files == sorted(files)
    assert files
    assert "latest.json" not in files
    for filename in files:
        assert (ROOT / "data" / "model_cache" / filename).exists()


def test_auto_grader_updates_nested_model_picks(monkeypatch):
    module = _load_module("auto_grade_picks", ROOT / "scripts" / "auto_grade_picks.py")
    payload = {
        "date": "2026-06-08",
        "models": {
            "mlb_new": {
                "picks": [
                    {
                        "source": "MLB Model",
                        "sport": "MLB",
                        "pick": "Cubs ML (Cubs vs Cardinals)",
                        "decision": "BET",
                        "result": "pending",
                    }
                ]
            }
        },
    }

    def fake_grade(picks, existing, year):
        pick_id = picks[0]["id"]
        return {
            "graded": {pick_id: "win"},
            "startTimes": {pick_id: "2026-06-08T20:00:00Z"},
        }

    monkeypatch.setattr(module.pickgrader_server, "auto_grade", fake_grade)
    assert module.grade_payload(payload) == 2
    pick = payload["models"]["mlb_new"]["picks"][0]
    assert pick["result"] == "win"
    assert pick["start_time"] == "2026-06-08T20:00:00Z"


def test_auto_grader_rechecks_previously_decided_tracked_picks(monkeypatch):
    module = _load_module("auto_grade_recheck_test", ROOT / "scripts" / "auto_grade_picks.py")
    payload = {
        "date": "2026-06-13",
        "models": {
            "wnba_player_props": {
                "picks": [{
                    "id": "aneesah-morrow-rebounds",
                    "source": "PickLedgerPro In-House Player Props",
                    "scope": "player",
                    "sport": "WNBA",
                    "pick": "Aneesah Morrow Over 10.5 Rebounds",
                    "decision": "BET",
                    "result": "win",
                }]
            }
        },
    }

    def fake_grade(picks, existing, year):
        assert picks[0]["result"] == "pending"
        return {"graded": {"aneesah-morrow-rebounds": "loss"}, "startTimes": {}}

    monkeypatch.setattr(module.pickgrader_server, "auto_grade", fake_grade)
    assert module.grade_payload(payload) == 1
    assert payload["models"]["wnba_player_props"]["picks"][0]["result"] == "loss"


def test_auto_grader_only_tracks_bet_and_lean_decisions(monkeypatch):
    module = _load_module("auto_grade_pass_test", ROOT / "scripts" / "auto_grade_picks.py")
    payload = {
        "date": "2026-06-08",
        "models": {
            "mlb_new": {
                "picks": [
                    {
                        "source": "MLB Model",
                        "sport": "MLB",
                        "pick": "Cubs ML (Cubs vs Cardinals)",
                        "decision": "PASS",
                        "result": "pending",
                    },
                    {
                        "source": "MLB Model",
                        "sport": "MLB",
                        "pick": "Cardinals ML (Cubs vs Cardinals)",
                        "decision": "WATCH",
                        "result": "pending",
                    },
                    {
                        "source": "MLB Model",
                        "sport": "MLB",
                        "pick": "Over 8.5 (Cubs vs Cardinals)",
                        "result": "pending",
                    },
                ]
            }
        },
    }

    def fail_if_called(*_args):
        raise AssertionError("PASS decisions must not be sent to the grader")

    monkeypatch.setattr(module.pickgrader_server, "auto_grade", fail_if_called)
    assert module.grade_payload(payload) == 0
    assert all(pick["result"] == "pending" for pick in payload["models"]["mlb_new"]["picks"])


def test_auto_grader_ignores_player_props_from_before_ml_retraining(monkeypatch):
    module = _load_module("auto_grade_ml_cutoff_test", ROOT / "scripts" / "auto_grade_picks.py")
    payload = {
        "date": "2026-06-15",
        "generatedAt": "2026-06-15T22:55:06Z",
        "models": {
            "mlb_player_props": {
                "picks": [{
                    "id": "legacy-prop",
                    "sport": "MLB",
                    "pick": "Player Over 0.5 Hits",
                    "decision": "BET",
                    "result": "pending",
                    "probability_source": "legacy_projection",
                    "ranking_updated_at": "2026-06-15T22:55:06Z",
                }]
            }
        },
    }

    monkeypatch.setattr(module.pickgrader_server, "auto_grade", lambda *_args: (_ for _ in ()).throw(AssertionError("legacy props must not be graded")))
    assert module.grade_payload(payload, ml_player_props_only=True) == 0


def test_scheduled_refreshes_are_json_only_and_use_shared_writer_lock():
    # Heavy cache writers share a concurrency group to avoid merge conflicts.
    # auto-grade.yml intentionally uses its own group (pick-auto-grade) because
    # grading is safe to run beside a cache refresh and shouldn't evict pending
    # model/props/feed refreshes from the queue.
    heavy_writer_workflows = (
        "calibration-refresh.yml",
        "model-cache-refresh.yml",
        "player-props-refresh.yml",
        "external-feed-refresh.yml",
    )
    for name in heavy_writer_workflows:
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "group: pick-cache-writer" in workflow
        assert "cancel-in-progress: false" in workflow

    # auto-grade uses its own concurrency group
    auto_grade = (ROOT / ".github" / "workflows" / "auto-grade.yml").read_text(encoding="utf-8")
    assert "group: pick-auto-grade" in auto_grade
    assert "cancel-in-progress: false" in auto_grade

    model = (ROOT / ".github" / "workflows" / "model-cache-refresh.yml").read_text(encoding="utf-8")
    feeds = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    assert "--skip-firestore" in model
    assert "--skip-firestore" in feeds
    assert "FIREBASE_PROJECT_ID" not in model
    assert "FIREBASE_PROJECT_ID" not in feeds


def test_refresh_timing_and_pages_deploy_are_deterministic():
    workflows = ROOT / ".github" / "workflows"
    model = (workflows / "model-cache-refresh.yml").read_text(encoding="utf-8")
    feeds = (workflows / "external-feed-refresh.yml").read_text(encoding="utf-8")
    grader = (workflows / "auto-grade.yml").read_text(encoding="utf-8")
    calibration = (workflows / "calibration-refresh.yml").read_text(encoding="utf-8")
    props = (workflows / "player-props-refresh.yml").read_text(encoding="utf-8")
    deploy = (workflows / "deploy-pages.yml").read_text(encoding="utf-8")

    assert "cache-gate" not in model
    assert "cron: '*/15 * * * *'" in grader
    assert 'cron: "45 12 * * *"' in model
    assert 'cron: "10,40 14 * * *"' in feeds
    assert "gh workflow run calibration-refresh.yml --ref main" in grader
    assert "decided - last >= 100" in grader
    assert "python scripts/train_pick_calibration.py" in calibration
    assert "gh workflow run player-props-refresh.yml --ref main" in calibration
    for workflow in (model, props, feeds, grader, calibration):
        assert "gh workflow run deploy-pages.yml --ref main" in workflow
        assert "actions: write" in workflow
    assert not (workflows / "cannon-daily-refresh.yml").exists()
    assert "Check daily data readiness" in deploy
    assert "python scripts/site_upcheck.py --data-only" in deploy
    assert "if: needs.readiness.outputs.ready == 'true'" in deploy
    assert "Verify styled Pages artifact" in deploy
    assert "find dist/assets -maxdepth 1 -name '*.js'" in deploy
    assert "! grep -q 'src/main.ts' dist/index.html" in deploy
    assert "python scripts/site_upcheck.py" in deploy
    guard = (workflows / "model-cache-freshness-guard.yml").read_text(encoding="utf-8")
    assert "python scripts/automation/ensure_model_refresh.py --dispatch" in guard
    assert 'models[key].get("ok") is True for key in required' in guard
    assert 'PLAYER_CACHE_HEALTHY="$(python - <<\'PY\'' in guard
    assert '"nba_player_props"' in guard
    assert '"mlb_player_props"' in guard
    assert '"wnba_player_props"' in guard
    assert 'official_mlb_games = max(' in guard
    assert 'str(pick.get("probability_source") or "").strip() != "player_props_ml_v1"' in guard
    assert 'pick.get("preserved_from_prior_refresh")' in guard
    assert 'key == "mlb_player_props" or bucket.get("abstained") is not True' in guard
    assert 'DISPATCHES_TODAY="$(gh run list' in guard
    assert '--json createdAt,displayTitle,event' in guard
    assert '"Player Props Refresh $TARGET_DATE"' in guard
    assert 'morning automation owns any bounded post-fix rerun' in guard
    assert "run-name: Player Props Refresh ${{ github.event.inputs.date || 'today' }}" in props
    assert "continue-on-error: true" in props
    assert "Enforce player-props publication contract" in props


def test_refresh_workflows_commit_as_triggering_actor():
    for name in (
        "auto-grade.yml",
        "calibration-refresh.yml",
        "model-cache-refresh.yml",
        "player-props-refresh.yml",
        "external-feed-refresh.yml",
    ):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert 'git config user.name  "${GITHUB_ACTOR}"' in workflow
        assert 'git config user.email "${ACTOR_EMAIL}"' in workflow
        assert "github-actions[bot]" not in workflow


def test_model_cache_merge_seeds_external_feeds_on_new_slate_day(tmp_path):
    module = _load_module("merge_model_cache_payload_new_day", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    previous = {
        "date": "2026-07-07",
        "models": {
            "wnba": {"ok": True, "picks": [{"pick": "Old"}]},
            "scores24_wnba": {"ok": True, "picks": [{"pick": "S24"}]},
        },
        "external_feeds": {
            "scores24_wnba": {"ok": True, "picks": [{"pick": "S24"}]},
        },
    }
    generated = {
        "date": "2026-07-08",
        "models": {
            "wnba": {"ok": True, "picks": [{"pick": "New"}]},
        },
    }
    (cache_dir / "latest.json").write_text(json.dumps(previous), encoding="utf-8")
    merged = module.merge_payload(generated, cache_dir)
    assert merged["models"]["wnba"]["picks"][0]["pick"] == "New"
    assert merged["external_feeds"]["scores24_wnba"]["picks"][0]["pick"] == "S24"


def test_model_cache_merge_keeps_newer_committed_external_feed_bucket(tmp_path):
    module = _load_module("merge_model_cache_payload_external_race", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-07-14",
        "models": {
            "scores24_wnba": {
                "ok": True,
                "date": "2026-07-14",
                "generatedBy": "local:external-feed-refresh",
                "meta": {"from": "local"},
                "picks": [{"pick": "Current local pick"}],
            }
        },
    }
    generated = {
        "date": "2026-07-14",
        "models": {
            "wnba": {"ok": True, "picks": [{"pick": "Fresh team pick"}]},
            "scores24_wnba": {
                "ok": True,
                "date": "2026-07-14",
                "generatedBy": "github-actions:external-feed-refresh",
                "meta": {"from": "github-actions"},
                "picks": [{"pick": "Stale starting-snapshot pick"}],
            },
        },
    }
    (cache_dir / "2026-07-14.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)

    assert merged["models"]["wnba"]["picks"][0]["pick"] == "Fresh team pick"
    scores = merged["models"]["scores24_wnba"]
    assert scores["generatedBy"] == "local:external-feed-refresh"
    assert scores["meta"]["from"] == "local"
    assert scores["picks"][0]["pick"] == "Current local pick"


def test_model_cache_stamps_mlb_new_and_wnba_bucket_dates(tmp_path):
    from scripts.refresh_model_cache import _build_payload

    date_iso = "2026-08-28"
    payload = _build_payload(date_iso, {"mlb_new": {"ok": True}, "wnba": {"ok": True}}, [])
    for key in ("mlb_new", "wnba"):
        assert payload["models"][key]["date"] == date_iso
        assert payload[key]["date"] == date_iso

    module = _load_module("merge_model_cache_payload_bucket_dates", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    merged = module.merge_payload(
        {
            "date": date_iso,
            "models": {"mlb_new": {"ok": True}, "wnba": {"ok": True}},
        },
        cache_dir,
    )
    for key in ("mlb_new", "wnba"):
        assert merged["models"][key]["date"] == date_iso
        assert merged[key]["date"] == date_iso


def test_model_cache_preserves_existing_mlb_new_and_wnba_bucket_dates(tmp_path):
    module = _load_module("merge_model_cache_payload_preserve_bucket_dates", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    existing_date = "2026-08-27"
    merged = module.merge_payload(
        {
            "date": "2026-08-28",
            "models": {
                "mlb_new": {"date": existing_date, "ok": True},
                "wnba": {"date": existing_date, "ok": True},
            },
        },
        cache_dir,
    )
    for key in ("mlb_new", "wnba"):
        assert merged["models"][key]["date"] == existing_date
        assert merged[key]["date"] == existing_date


def test_model_cache_merge_preserves_other_deployed_buckets(tmp_path):
    module = _load_module("merge_model_cache_payload", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-08",
        "models": {
            "mlb_new": {"ok": True, "picks": [{"pick": "A", "result": "win"}]},
            "sportytrader_mlb": {"ok": True, "picks": [{"pick": "B"}]},
        },
        "mlb_new": {"ok": True, "picks": [{"pick": "A", "result": "win"}]},
    }
    generated = {
        "date": "2026-06-08",
        "models": {
            "nba": {"ok": True, "picks": [{"pick": "C"}]},
        },
        "mlb_new": {},
        "nba": {"ok": True, "picks": [{"pick": "C"}]},
    }
    (cache_dir / "2026-06-08.json").write_text(json.dumps(current), encoding="utf-8")
    merged = module.merge_payload(generated, cache_dir)
    assert merged["models"]["mlb_new"]["picks"][0]["result"] == "win"
    assert merged["models"]["sportytrader_mlb"]["picks"][0]["pick"] == "B"
    assert merged["models"]["nba"]["picks"][0]["pick"] == "C"
    assert merged["mlb_new"]["picks"][0]["pick"] == "A"
    assert merged["nba"]["picks"][0]["pick"] == "C"


def test_model_cache_merge_preserves_committed_grades(tmp_path):
    module = _load_module("merge_model_cache_payload_grades", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-08",
        "models": {
            "mlb_new": {
                "picks": [{
                    "source": "X",
                    "sport": "MLB",
                    "pick": "Cubs ML",
                    "result": "win",
                    "pregame_snapshot": {"probability": 0.61},
                }]
            }
        },
    }
    generated = {
        "date": "2026-06-08",
        "models": {
            "mlb_new": {
                "picks": [{"source": "X", "sport": "MLB", "pick": "Cubs ML", "result": "pending"}]
            }
        },
    }
    (cache_dir / "2026-06-08.json").write_text(json.dumps(current), encoding="utf-8")
    merged = module.merge_payload(generated, cache_dir)
    assert merged["models"]["mlb_new"]["picks"][0]["result"] == "win"
    assert merged["models"]["mlb_new"]["picks"][0]["pregame_snapshot"]["probability"] == 0.61


def test_model_cache_merge_keeps_previous_same_date_picks_when_refresh_drops_them(tmp_path):
    module = _load_module("merge_model_cache_payload_keep_dropped", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-16",
        "models": {
            "fifa_world_cup": {
                "picks": [
                    {"source": "FIFA Model", "sport": "FIFA WC", "date": "2026-06-16", "pick": "France ML", "matchup": "Senegal @ France"},
                    {"source": "FIFA Model", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ]
            }
        },
    }
    generated = {
        "date": "2026-06-16",
        "models": {
            "fifa_world_cup": {
                "picks": [
                    {"source": "FIFA Model", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ]
            }
        },
    }
    (cache_dir / "2026-06-16.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)
    picks = merged["models"]["fifa_world_cup"]["picks"]

    assert [pick["pick"] for pick in picks] == ["Norway ML", "France ML"]


def test_model_cache_merge_replaces_stale_same_game_market_pick(tmp_path):
    module = _load_module("merge_model_cache_payload_replace_market", ROOT / "scripts" / "merge_model_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-22",
        "models": {
            "fifa_world_cup": {
                "picks": [
                    {
                        "source": "FIFA Model",
                        "sport": "FIFA WC",
                        "date": "2026-06-22",
                        "market": "total",
                        "pick": "Over 2.5 (Algeria @ Jordan)",
                        "matchup": "Algeria @ Jordan",
                    },
                    {
                        "source": "FIFA Model",
                        "sport": "FIFA WC",
                        "date": "2026-06-22",
                        "market": "total",
                        "pick": "Under 2.5 (Completed @ Match)",
                        "matchup": "Completed @ Match",
                        "result": "win",
                    },
                ]
            }
        },
    }
    generated = {
        "date": "2026-06-22",
        "models": {
            "fifa_world_cup": {
                "picks": [
                    {
                        "source": "FIFA Model",
                        "sport": "FIFA WC",
                        "date": "2026-06-22",
                        "market": "total",
                        "pick": "Under 2.5 (Algeria @ Jordan)",
                        "matchup": "Algeria @ Jordan",
                    },
                ]
            }
        },
    }
    (cache_dir / "2026-06-22.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)
    picks = merged["models"]["fifa_world_cup"]["picks"]

    assert [pick["pick"] for pick in picks] == [
        "Under 2.5 (Algeria @ Jordan)",
        "Under 2.5 (Completed @ Match)",
    ]


def test_external_feed_merge_replaces_previous_same_date_picks_when_refresh_drops_them(tmp_path):
    module = _load_module("merge_external_feed_cache_payload_replace_dropped", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-16",
        "models": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "external_feeds": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "sportytrader_fifa_world_cup": {
            "ok": True,
            "picks": [
                {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
            ],
        },
    }
    generated = {
        "date": "2026-06-16",
        "models": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "external_feeds": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "sportytrader_fifa_world_cup": {
            "ok": True,
            "picks": [
                {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
            ],
        },
    }
    (cache_dir / "2026-06-16.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)
    picks = merged["models"]["sportytrader_fifa_world_cup"]["picks"]

    assert [pick["pick"] for pick in picks] == ["Norway ML"]
    assert [pick["pick"] for pick in merged["external_feeds"]["sportytrader_fifa_world_cup"]["picks"]] == ["Norway ML"]
    assert [pick["pick"] for pick in merged["sportytrader_fifa_world_cup"]["picks"]] == ["Norway ML"]


def test_external_feed_merge_migrates_legacy_provider_bucket_to_split_key(tmp_path):
    module = _load_module("merge_external_feed_cache_payload_legacy_split", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-16",
        "models": {
            "sportytrader": {
                "ok": True,
                "picks": [
                    {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                    {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "external_feeds": {
            "sportytrader": {
                "ok": True,
                "picks": [
                    {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                    {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "sportytrader": {
            "ok": True,
            "picks": [
                {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Both teams to score", "matchup": "France vs Senegal"},
                {"source": "SportyTrader", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
            ],
        },
    }
    generated = {
        "date": "2026-06-16",
        "models": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
        "external_feeds": {
            "sportytrader_fifa_world_cup": {
                "ok": True,
                "picks": [
                    {"source": "SportyTraderFIFAWorldCup", "sport": "FIFA WC", "date": "2026-06-16", "pick": "Norway ML", "matchup": "Norway @ Iraq"},
                ],
            }
        },
    }
    (cache_dir / "2026-06-16.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)
    picks = merged["models"]["sportytrader_fifa_world_cup"]["picks"]

    assert "sportytrader" not in merged["models"]
    assert "sportytrader" not in merged["external_feeds"]
    assert "sportytrader" not in merged
    assert [pick["pick"] for pick in picks] == ["Norway ML"]
    assert {pick["source"] for pick in picks} == {"SportyTraderFIFAWorldCup"}


def test_player_prop_merge_does_not_carry_results_across_rank_epochs(tmp_path):
    module = _load_module("merge_player_props_cache_payload_epochs", ROOT / "scripts" / "merge_player_props_cache_payload.py")
    cache_dir = tmp_path / "data" / "player_props_cache"
    cache_dir.mkdir(parents=True)
    current = {
        "date": "2026-06-16",
        "models": {
            "mlb_player_props": {
                "picks": [{
                    "id": "same-prop",
                    "source": "PickLedgerPro In-House Player Props",
                    "sport": "MLB",
                    "date": "2026-06-16",
                    "pick": "Player Over 0.5 Hits",
                    "matchup": "Away @ Home",
                    "ml_rank_epoch": "MLB:old",
                    "result": "win",
                }]
            }
        },
    }
    generated = {
        "date": "2026-06-16",
        "models": {
            "mlb_player_props": {
                "picks": [{
                    "id": "same-prop",
                    "source": "PickLedgerPro In-House Player Props",
                    "sport": "MLB",
                    "date": "2026-06-16",
                    "pick": "Player Over 0.5 Hits",
                    "matchup": "Away @ Home",
                    "ml_rank_epoch": "MLB:new",
                    "result": "pending",
                }]
            }
        },
    }
    (cache_dir / "2026-06-16.json").write_text(json.dumps(current), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir)

    assert merged["models"]["mlb_player_props"]["picks"][0]["result"] == "pending"


def test_player_prop_merge_keeps_snapshot_only_props_out_of_latest_board(tmp_path):
    module = _load_module("merge_player_props_cache_payload_current_board", ROOT / "scripts" / "merge_player_props_cache_payload.py")
    cache_dir = tmp_path / "data" / "player_props_cache"
    snapshot_dir = tmp_path / "data" / "player_props_snapshots"
    cache_dir.mkdir(parents=True)
    (snapshot_dir / "2026-06-20").mkdir(parents=True)
    previous = {
        "date": "2026-06-20",
        "models": {
            "mlb_player_props": {
                "ok": True,
                "picks": [
                    {
                        "id": "old",
                        "scope": "player",
                        "source": "MLBPlayerProps",
                        "sport": "MLB",
                        "date": "2026-06-20",
                        "game_id": "1",
                        "player_id": "10",
                        "stat_key": "hits",
                        "selection": "Over",
                        "line": 0.5,
                        "pick": "Old Over 0.5 Hits",
                        "matchup": "A @ B",
                        "market_priced": True,
                        "probability_source": "player_props_ml_v1",
                        "decision": "LEAN",
                        "ml_model_version": "player_props_consensus_v2.0.0",
                        "ml_probability_mode": "four_model_consensus_gate",
                        "consensus_qualified": True,
                        "result": "pending",
                    }
                ],
            }
        },
    }
    generated = {
        "date": "2026-06-20",
        "models": {
            "mlb_player_props": {
                "ok": True,
                "picks": [
                    {
                        "id": "new",
                        "scope": "player",
                        "source": "MLBPlayerProps",
                        "model_key": "mlb_player_props",
                        "sport": "MLB",
                        "date": "2026-06-20",
                        "game_id": "2",
                        "player_id": "20",
                        "stat_key": "hits_runs_rbis",
                        "selection": "Under",
                        "line": 1.5,
                        "pick": "New Under 1.5 HRR",
                        "matchup": "C @ D",
                        "market_priced": True,
                        "probability_source": "player_props_ml_v1",
                        "decision": "LEAN",
                        "ml_model_version": "player_props_consensus_v2.0.0",
                        "ml_probability_mode": "four_model_consensus_gate",
                        "consensus_qualified": True,
                    }
                ],
            }
        },
    }
    (cache_dir / "2026-06-20.json").write_text(json.dumps({"date": "2026-06-20", "models": {}}), encoding="utf-8")
    (snapshot_dir / "2026-06-20" / "snapshot.json").write_text(json.dumps(previous), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir, snapshot_dir)
    picks = merged["models"]["mlb_player_props"]["picks"]

    assert {pick["id"] for pick in picks} == {"new"}
    assert {pick["source"] for pick in picks} == {"MLBPlayerProps"}
    assert {pick["model_key"] for pick in picks} == {"mlb_player_props"}
    assert all("carried_forward" not in pick for pick in picks)


def test_player_prop_merge_keeps_legacy_variant_snapshots_archive_only(tmp_path):
    module = _load_module("merge_player_props_cache_payload_legacy_variants", ROOT / "scripts" / "merge_player_props_cache_payload.py")
    cache_dir = tmp_path / "data" / "player_props_cache"
    snapshot_dir = tmp_path / "data" / "player_props_snapshots"
    cache_dir.mkdir(parents=True)
    (snapshot_dir / "2026-06-24").mkdir(parents=True)
    snapshot = {
        "date": "2026-06-24",
        "models": {
            "wnba_player_props_all_time": {
                "ok": True,
                "picks": [
                    {
                        "id": "pp_michaela_all_time",
                        "scope": "player",
                        "source": "WNBA All Time Props",
                        "sport": "WNBA",
                        "date": "2026-06-24",
                        "game_id": "401857018",
                        "player_id": "4281173",
                        "stat_key": "points",
                        "selection": "Over",
                        "line": 9.5,
                        "pick": "Michaela Onyenwere Over 9.5 Points",
                        "matchup": "A @ B",
                        "market_priced": True,
                        "probability_source": "player_props_ml_v1",
                        "decision": "LEAN",
                        "ml_model_version": "player_props_consensus_v2.0.0",
                        "ml_probability_mode": "four_model_consensus_gate",
                        "consensus_qualified": True,
                        "model_variant": "all_time",
                        "result": "pending",
                    }
                ],
            }
        },
    }
    generated = {
        "date": "2026-06-24",
        "models": {
            "wnba_player_props": {
                "ok": True,
                "ranking_epoch": "WNBA:player_props_consensus_v2.0.0:published:test",
                "picks": [],
            }
        },
    }
    (cache_dir / "2026-06-24.json").write_text(json.dumps({"date": "2026-06-24", "models": {}}), encoding="utf-8")
    (snapshot_dir / "2026-06-24" / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

    merged = module.merge_payload(generated, cache_dir, snapshot_dir)
    picks = merged["models"]["wnba_player_props"]["picks"]

    assert picks == []


def test_external_feed_merge_keeps_newer_local_scores24_over_stale_snapshot(tmp_path):
    """An Actions SportyTrader refresh copies yesterday's Scores24 into generated JSON.

    After a same-day local Scores24 publish, that merge must keep today's buckets.
    """
    module = _load_module(
        "merge_external_feed_cache_payload_scores24_date",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    today = {
        "date": "2026-08-19",
        "models": {key: {"ok": True, "picks": []} for key in module.REQUIRED_TEAM_MODEL_KEYS},
        "external_feeds": {
            "scores24_mlb": {
                "ok": True,
                "date": "2026-08-19",
                "generatedBy": "local:external-feed-refresh",
                "picks": [{"pick": "Yankees ML", "matchup": "Yankees @ Orioles"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            },
            "sportytrader_mlb": {
                "ok": True,
                "date": "2026-08-18",
                "picks": [{"pick": "old ST"}],
            },
        },
    }
    (cache_dir / "2026-08-19.json").write_text(json.dumps(today), encoding="utf-8")
    generated = {
        "date": "2026-08-19",
        "external_feeds": {
            "scores24_mlb": {
                "ok": True,
                "date": "2026-08-18",
                "generatedBy": "local:external-feed-refresh",
                "picks": [{"pick": "stale Scores24", "matchup": "Cubs @ Brewers"}],
                "meta": {"expectedMatchups": 15, "matchedPicks": 15, "missingMatchups": []},
            },
            "sportytrader_mlb": {
                "ok": True,
                "date": "2026-08-19",
                "picks": [{"pick": "new ST"}],
            },
        },
    }

    merged = module.merge_payload(generated, cache_dir)
    scores24 = merged["external_feeds"]["scores24_mlb"]
    sporty = merged["external_feeds"]["sportytrader_mlb"]
    assert scores24["date"] == "2026-08-19"
    assert scores24["picks"][0]["pick"] == "Yankees ML"
    assert sporty["date"] == "2026-08-19"
    assert sporty["picks"][0]["pick"] == "new ST"


def test_external_feed_merge_does_not_promote_partial_cache_to_latest(tmp_path):
    module = _load_module("merge_external_feed_cache_payload", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    previous = {"date": "2026-06-14", "models": {"mlb_new": {"ok": True, "picks": []}}}
    partial = {
        "date": "2026-06-15",
        "models": {"scores24_mlb": {"ok": True, "picks": [{"pick": "Cubs ML"}]}},
    }
    (cache_dir / "latest.json").write_text(json.dumps(previous), encoding="utf-8")

    merged = module.merge_payload(partial, cache_dir)
    latest_updated = module.write_merged_payload(merged, cache_dir)

    assert latest_updated is False
    assert json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-06-14"
    assert json.loads((cache_dir / "2026-06-15.json").read_text(encoding="utf-8"))["models"]["scores24_mlb"]["ok"] is True


def test_external_feed_merge_promotes_complete_cache_to_latest(tmp_path):
    module = _load_module("merge_external_feed_cache_payload_complete", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    complete = {
        "date": "2026-06-15",
        "models": {
            key: {"ok": True, "picks": []}
            for key in module.REQUIRED_TEAM_MODEL_KEYS
        },
    }

    latest_updated = module.write_merged_payload(complete, cache_dir)

    assert latest_updated is True
    assert json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-06-15"


def test_rankings_tab_drops_the_profit_desk_qualification_board():
    """The qualification board moved off Rankings entirely; the Profit Desk
    Method view is now the only place the promotion rules are stated, so no
    copy may keep pointing readers at a section that no longer exists."""
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    data = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'id="profit-qualification-section"' not in html
    assert 'id="profit-qualification-board"' not in html
    assert "Profit Desk Qualification" not in html
    assert "How qualification works" not in html
    assert "renderProfitQualificationBoard" not in main
    assert "QUALIFICATION_GATE_LABELS" not in main
    assert "Rankings &rarr; Profit Desk Qualification" not in main
    assert ".qual-card" not in css
    assert ".qual-gates" not in css
    # The published artifact still carries the per-source evidence; only the
    # board that rendered it is gone.
    assert "export interface ProfitDeskSourceCard" in data
    assert "sources?: ProfitDeskSourceCard[]" in data


def test_rankings_boards_follow_a_sport_and_source_filter_while_overall_stats_stay_global():
    """Rankings gets a Home-style scope filter: sport profitability, source
    rankings, and day-of-week all read from the same scoped pool, while the
    Overall Stats row above stays all-time across every source."""
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert 'id="rank-filter-groups"' in html
    assert 'id="rank-scope-summary"' in html
    assert "Filter Rankings" in html
    # The filter sits between Overall Stats and the three boards it drives.
    assert html.index("Overall Stats") < html.index('id="rank-filter-groups"')
    assert html.index('id="rank-filter-groups"') < html.index("Sport Profitability")

    # Rankings scope is its own state — sharing Home's Set would make every
    # Home tag silently rewrite the leaderboard.
    assert "const rankingSportFilters = new Set<string>()" in main
    assert "const rankingSourceFilters = new Set<string>()" in main
    assert "function rankingScopedPicks(" in main
    assert "const scopedPicks = rankingScopedPicks(comparablePicks)" in main
    assert "const rankingPicks = scopedPicks.filter(isSettledPick)" in main
    assert "renderDayOfWeekTable(scopedPicks)" in main
    assert "function renderDayOfWeekTable(comparablePicks: Pick[]): void" in main
    # Sports and sources intersect; a flat OR would union unrelated buckets.
    assert "comparablePicks.filter(pick => matchesRankingSports(pick) && matchesRankingSources(pick))" in main
    # Overall Stats never reads the scoped pool.
    stats_start = main.index("function updateOverallStats(): void {")
    stats_end = main.index("function ", stats_start + 1)
    assert "rankingScopedPicks" not in main[stats_start:stats_end]
    assert "rankingSportFilters" not in main[stats_start:stats_end]

    # Switching Team/Player mode rebuilds the buckets, so the scope must reset.
    mode_start = main.index("function switchPickMode(mode: PickMode): void {")
    mode_end = main.index("function ", mode_start + 1)
    assert "rankingSportFilters.clear()" in main[mode_start:mode_end]
    assert "rankingSourceFilters.clear()" in main[mode_start:mode_end]

    assert 'data-rank-${kind}="' in main
    assert "button.dataset.rankSport || 'ALL'" in main
    assert "button.dataset.rankSource || 'ALL'" in main

    # A source with picks but nothing decided still gets a card and a filter
    # pill; otherwise a newly added feed is invisible until its first game
    # finishes. Records stay settled-only either way.
    assert "item.stats.wins + item.stats.losses > 0" not in main
    assert "AWAITING FIRST RESULT" in main
    assert "stats: statsFor(picks.filter(isSettledPick))" in main
    assert ".rank-filter-btn" in css
    assert ".rank-filter-btn.active" in css
    assert ".rank-scope-summary" in css


def test_fade_board_is_wired_and_conflict_aware():
    """The Fade view is Day Form's inverse: cold-on-this-weekday AND
    cold-recently sources produce fade candidates, and any in-form source
    on the same selection cancels the fade (anti-consensus rule)."""
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "function dailyFadeBoard(" in main
    assert "function dailyFadeBody(" in main
    assert "function fadeOppositeText(" in main
    assert "function recentSourceRecords(" in main
    # Mixed-signal cancellation + reinforcement both present.
    assert "hotKeys.has(key)" in main
    assert "coldForms.push(form)" in main
    assert "FADE_DAY_MAX_RATE = 0.45" in main
    assert "FADE_BLOCK_DAY_RATE = 0.55" in main
    assert "'fade'" in main
    assert ".daily-fade-card" in css


def test_home_game_cards_organize_picks_into_market_lanes():
    """A game card groups its picks by market and then by the side each source
    takes, so agreement and disagreement are visible without reading rows.
    Classification falls back to the selection text because the scraper feeds
    ship no market type, and anything unrecognized lands in a labelled
    'Other Markets' lane rather than a main one."""
    main = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    css = (ROOT / "src" / "styles" / "pickledger.css").read_text(encoding="utf-8")

    assert "function buildMarketLanes(" in main
    assert "function marketFamilyFor(" in main
    assert "function marketFamilyFromSelection(" in main
    assert "function marketSideFor(" in main
    assert "function marketLaneHtml(" in main
    assert "const lanes = buildMarketLanes(sortedPicks)" in main
    assert "lanes.map(marketLaneHtml).join('')" in main
    # A card with no classifiable lanes still renders its rows.
    assert "sortedPicks.map(renderPickRow).join('')" in main

    # Every main market is exclusive (opposite sides contradict) and every
    # catch-all lane is not (unrelated bets merely stack).
    for family in ("moneyline", "spread", "total", "team_total", "f5_side", "f5_total"):
        assert f"{family}: {{ key: '{family}'" in main
    assert "inning: { key: 'inning', label: 'Innings', order: 7, exclusive: false }" in main
    assert "other: { key: 'other', label: 'Other Markets', order: 9, exclusive: false }" in main

    # The four agreement states, each labelled in words as well as colour.
    assert "type LaneTone = 'consensus' | 'split' | 'stack' | 'solo'" in main
    assert "badge: `${sources} AGREE`" in main
    assert "badge: `SPLIT ${counts.join('–')}`" in main
    assert "`${picks.length} LINES`" in main
    assert "badge: `1 SOURCE | ${sides.length} SIDES`" in main
    assert "badge: `${sides.length} SELECTIONS`" in main
    # One source grading both sides is not a disagreement, and unrelated bets
    # are never "sides" at all — non-exclusive lanes resolve first.
    assert "if (!exclusive) return { tone: 'stack'" in main
    assert "if (sources < 2) return { tone: 'solo'" in main
    assert main.index("if (!exclusive) return { tone: 'stack'") < main.index("if (sources < 2) return { tone: 'solo'")
    # A side is a source's position, so distinct sources drive the split count.
    assert "function distinctSources(" in main

    assert ".home-game-picks.home-market-lanes" in css
    assert ".home-market-lane.tone-consensus::before" in css
    assert ".home-market-lane.tone-split::before" in css
    assert ".home-lane-badge.tone-consensus" in css
    assert ".home-lane-sides.count-2.is-versus" in css
    assert ".home-lane-vs" in css
    assert ".home-consensus-pill" in css
    # Lanes drop the redundant sport column, so the row grid is re-declared for
    # every layout instead of stranding the P/L in a column that is gone.
    assert ".home-lane-side-rows .home-feed-row-sport { display: none; }" in css
    assert ".home-lane-side-rows .home-feed-row { grid-template-columns: minmax(0, 1fr) auto auto; }" in css
    assert "body.mobile-app-mode .home-lane-side-rows .home-feed-row" in css
    assert 'body[data-theme="light"] .home-market-lane' in css
    assert ".home-market-lane.is-wide" in css


def _core_team_model_keys_from_guard() -> set[str]:
    """The team-model set used by the shared freshness guard implementation."""
    from scripts.automation.ensure_model_refresh import REQUIRED

    return REQUIRED


def test_core_team_model_required_sets_do_not_drift():
    """Three places encode "today's core team models"; they must agree.

    They rotted apart once: nba_summer and fifa_world_cup were archived
    2026-07-19 when their seasons ended, and site_upcheck plus the freshness
    guard were pruned while the external-feed merger's copy was not. Because
    that copy gates promotion to latest.json, the stale entries pinned
    latest_updated to False — every local publisher could write {date}.json but
    none could update latest.json, so a day's scraped feeds only reached the
    site if a model-cache refresh happened to run after them. It failed silently
    and in the worst direction, so the sets are pinned together here.
    """
    merger = _load_module(
        "merge_external_feed_cache_payload_drift",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    upcheck = _load_module("site_upcheck_drift", ROOT / "scripts" / "site_upcheck.py")

    assert merger.REQUIRED_TEAM_MODEL_KEYS == upcheck.REQUIRED_MODEL_KEYS
    assert merger.REQUIRED_TEAM_MODEL_KEYS == _core_team_model_keys_from_guard()
    # Archived sports must never creep back in: they stop publishing entirely,
    # so requiring one is equivalent to disabling the gate's success path.
    assert not (merger.REQUIRED_TEAM_MODEL_KEYS & {"nba_summer", "fifa_world_cup"})


def test_external_feed_publish_promotes_latest_without_archived_sports(tmp_path):
    """A publisher must be able to update latest.json on today's real model set.

    This is the regression: the day's live in-house models are all ok, and no
    archived sport is present because none is produced any more.
    """
    module = _load_module(
        "merge_external_feed_cache_payload_archived",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    live_models = ["mlb_new", "mlb_inning", "mlb_first_five", "wnba", "nba", "nba_playoffs", "mls", "nfl", "cfb", "tennis"]
    payload = {
        "date": "2026-07-27",
        "models": {key: {"ok": True, "picks": []} for key in live_models},
        "external_feeds": {"scores24_mlb": {"ok": True, "date": "2026-07-27", "picks": []}},
    }

    assert module.write_merged_payload(payload, cache_dir) is True
    assert json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-07-27"


def test_external_feed_publish_still_refuses_a_day_without_team_models(tmp_path):
    """The guard the gate exists for must survive the fix."""
    module = _load_module(
        "merge_external_feed_cache_payload_guard",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    feeds_only = {
        "date": "2026-07-28",
        "models": {"tennis": {"ok": True, "picks": []}},
        "external_feeds": {"scores24_mlb": {"ok": True, "date": "2026-07-28", "picks": []}},
    }

    assert module.write_merged_payload(feeds_only, cache_dir) is False
    assert not (cache_dir / "latest.json").exists()



def test_external_feed_publish_promotes_complete_scores24_mlb_wnba_without_team_models(tmp_path):
    """Morning Scores24 with a complete MLB+WNBA slate must update latest.json."""
    module = _load_module(
        "merge_external_feed_cache_payload_scores24_promote",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    previous = {"date": "2026-08-26", "models": {"mlb_new": {"ok": True, "picks": []}}}
    (cache_dir / "latest.json").write_text(json.dumps(previous), encoding="utf-8")
    scores24_only = {
        "date": "2026-08-27",
        "models": {
            "scores24_mlb": {"ok": True, "date": "2026-08-27", "picks": [{"pick": "Yankees ML"}]},
            "scores24_wnba": {"ok": True, "date": "2026-08-27", "picks": [{"pick": "Aces ML"}]},
        },
        "external_feeds": {
            "scores24_mlb": {
                "ok": True,
                "date": "2026-08-27",
                "picks": [{"pick": "Yankees ML"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            },
            "scores24_wnba": {
                "ok": True,
                "date": "2026-08-27",
                "picks": [{"pick": "Aces ML"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            },
        },
    }

    assert module.write_merged_payload(scores24_only, cache_dir) is True
    assert json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-08-27"


def test_external_feed_publish_promotes_mlb_wnba_when_scores24_cfb_is_blocked(tmp_path):
    """Incomplete/blocked CFB must not prevent the MLB+WNBA first-paint gate."""
    module = _load_module(
        "merge_external_feed_cache_payload_cfb_soft_fail",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    previous = {"date": "2026-09-03", "models": {"mlb_new": {"ok": True, "picks": []}}}
    (cache_dir / "latest.json").write_text(json.dumps(previous), encoding="utf-8")
    payload = {
        "date": "2026-09-04",
        "models": {
            "scores24_mlb": {"ok": True, "date": "2026-09-04", "picks": [{"pick": "Yankees ML"}]},
            "scores24_wnba": {"ok": True, "date": "2026-09-04", "picks": [{"pick": "Aces ML"}]},
            "scores24_cfb": {
                "ok": False,
                "date": "2026-09-04",
                "error": "blocked before official slate completed",
                "picks": [],
            },
        },
        "external_feeds": {
            "scores24_mlb": {
                "ok": True,
                "date": "2026-09-04",
                "picks": [{"pick": "Yankees ML"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            },
            "scores24_wnba": {
                "ok": True,
                "date": "2026-09-04",
                "picks": [{"pick": "Aces ML"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            },
            "scores24_cfb": {
                "ok": False,
                "date": "2026-09-04",
                "picks": [],
                "error": "blocked before official slate completed",
                "meta": {"expectedMatchups": 12, "matchedPicks": 0, "missingMatchups": ["Toledo @ Michigan State"]},
            },
        },
    }

    assert module.write_merged_payload(payload, cache_dir) is True
    assert json.loads((cache_dir / "latest.json").read_text(encoding="utf-8"))["date"] == "2026-09-04"


def test_external_feed_publish_does_not_promote_cfb_only_slate(tmp_path):
    module = _load_module(
        "merge_external_feed_cache_payload_cfb_only",
        ROOT / "scripts" / "merge_external_feed_cache_payload.py",
    )
    cache_dir = tmp_path / "data" / "model_cache"
    cache_dir.mkdir(parents=True)
    payload = {
        "date": "2026-09-04",
        "models": {"scores24_cfb": {"ok": True, "date": "2026-09-04", "picks": [{"pick": "Ohio State ML"}]}},
        "external_feeds": {
            "scores24_cfb": {
                "ok": True,
                "date": "2026-09-04",
                "picks": [{"pick": "Ohio State ML"}],
                "meta": {"expectedMatchups": 1, "matchedPicks": 1, "missingMatchups": []},
            }
        },
    }

    assert module.write_merged_payload(payload, cache_dir) is False
    assert not (cache_dir / "latest.json").exists()
