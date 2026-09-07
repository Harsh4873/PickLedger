from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.scrapers.tennis_scraper as tn  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _competition(away, home, *, date, status="STATUS_FINAL", winner=None, doubles=False, tbd=False):
    def competitor(name, side, is_winner):
        athlete = None if doubles else {"displayName": name}
        if tbd and side == "home":
            athlete = {"displayName": "TBD"}
        return {"homeAway": side, "winner": is_winner, "athlete": athlete}

    return {
        "date": date,
        "status": {"type": {"name": status}},
        "competitors": [
            competitor(away, "away", winner == away),
            competitor(home, "home", winner == home),
        ],
    }


def _board(round_name, competitions):
    return {"events": [{"groupings": [{"grouping": {"displayName": round_name}, "competitions": competitions}]}]}


def _espn_fetch(atp_board, wta_board=None):
    def fetch(url):
        if "/atp/" in url:
            return atp_board
        if "/wta/" in url:
            return wta_board if wta_board is not None else {"events": []}
        raise AssertionError(f"unexpected url {url}")

    return fetch


def _tennistonic_html(title, prediction=None, not_prediction=False):
    body = ""
    if prediction:
        body = f'<div class="prediction_set">Prediction {prediction}</div>'
    elif not_prediction:
        body = '<div class="prediction_set_not">No confident prediction</div>'
    return f"<html><head><title>H2H {title} stats, prediction</title></head><body>{body}</body></html>"


def _scores24_html(title, tip, odds):
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<div>Our choice {tip} at odds of {odds}</div></body></html>"
    )


class _FakeScores24Client:
    def __init__(self, responses):
        # responses: dict[url -> (html, status, blocked)]; a "listing" key seeds
        # the tennis predictions page.
        self.responses = responses
        self.closed = False

    def get_html(self, url, attempts=None):
        if "/tennis/predictions" in url:
            return self.responses.get("listing", ("", 200, False))
        return self.responses.get(url, ("", 404, False))

    def close(self):
        self.closed = True


# --------------------------------------------------------------------------- #
# Config + ESPN slate                                                          #
# --------------------------------------------------------------------------- #


def test_tennis_config():
    cfg = tn.SPORT_CONFIG["tennis"]
    assert cfg["espn_sport"] == "tennis"
    assert cfg["espn_leagues"] == ("atp", "wta")
    assert cfg["label"] == "Tennis"
    assert cfg["scores24_source"] == "Scores24Tennis"
    assert cfg["tennistonic_source"] == "TennisTonic"
    assert "tennis/predictions" in cfg["scores24_listing_url"]


def test_espn_slate_parses_singles_and_skips_doubles_tbd_and_offdate():
    atp = _board(
        "Men's Singles",
        [
            _competition("Andrey Rublev", "Timofey Skatov", date="2026-07-22T09:30Z", winner="Andrey Rublev"),
            _competition("A", "B", date="2026-07-21T09:30Z", winner="A"),  # off-date -> skipped
            _competition("C", "TBD", date="2026-07-22T09:30Z", tbd=True, status="STATUS_SCHEDULED"),  # unfilled draw
        ],
    )
    atp["events"][0]["groupings"].append(
        {
            "grouping": {"displayName": "Men's Doubles"},
            "competitions": [_competition("X", "Y", date="2026-07-22T09:30Z", doubles=True)],
        }
    )
    wta = _board(
        "Women's Singles",
        [_competition("Barbora Krejcikova", "Lucie Havlickova", date="2026-07-22T10:00Z", status="STATUS_SCHEDULED")],
    )
    matches, resolved = tn.espn_tennis_matches("2026-07-22", fetch_json=_espn_fetch(atp, wta))
    assert resolved is True
    labels = {f"{m['away']} vs {m['home']}" for m in matches}
    assert labels == {"Andrey Rublev vs Timofey Skatov", "Barbora Krejcikova vs Lucie Havlickova"}
    tours = {m["tour"] for m in matches}
    assert tours == {"ATP", "WTA"}


def test_espn_slate_unresolved_when_both_boards_fail():
    def boom(url):
        raise RuntimeError("network down")

    matches, resolved = tn.espn_tennis_matches("2026-07-22", fetch_json=boom)
    assert matches == []
    assert resolved is False


# --------------------------------------------------------------------------- #
# TennisTonic                                                                  #
# --------------------------------------------------------------------------- #


def test_tennistonic_slug_and_urls():
    assert tn._tennistonic_slug("Barbora Krejcikova") == "Barbora-Krejcikova"
    assert tn._tennistonic_slug("Jan-Lennard Struff") == "Jan-Lennard-Struff"
    urls = tn.tennistonic_urls({"away": "Reda Bennani", "home": "Adam Lynch"})
    assert urls[0].endswith("/head-to-head-compare/Reda-Bennani-Vs-Adam-Lynch/")
    assert any("Adam-Lynch-Vs-Reda-Bennani" in u for u in urls)


def test_tennistonic_prediction_parsing():
    match = {"away": "Barbora Krejcikova", "home": "Lucie Havlickova"}
    html = _tennistonic_html("Barbora Krejcikova Vs Lucie Havlickova", prediction="Krejcikova in 2")
    assert tn.parse_tennistonic_prediction(html, match) == ("Barbora Krejcikova", 2)

    # Greyed "no confident prediction" variant -> no pick.
    html_not = _tennistonic_html("x", not_prediction=True)
    assert tn.parse_tennistonic_prediction(html_not, match) is None

    # No prediction element at all (completed match) -> no pick.
    assert tn.parse_tennistonic_prediction(_tennistonic_html("x"), match) is None

    # Surname that matches neither athlete -> no pick.
    html_wrong = _tennistonic_html("x", prediction="Federer in 3")
    assert tn.parse_tennistonic_prediction(html_wrong, match) is None


def test_scrape_tennistonic_matches_official_slate():
    matches = [
        {"away": "Barbora Krejcikova", "home": "Lucie Havlickova", "tour": "WTA", "league": "wta", "start_time": "t"},
        {"away": "Reda Bennani", "home": "Adam Lynch", "tour": "ATP", "league": "atp", "start_time": "t"},
    ]
    pages = {
        "Barbora-Krejcikova-Vs-Lucie-Havlickova": _tennistonic_html(
            "Barbora Krejcikova Vs Lucie Havlickova", prediction="Krejcikova in 2"
        ),
        "Reda-Bennani-Vs-Adam-Lynch": _tennistonic_html("Reda Bennani Vs Adam Lynch"),  # no prediction
    }

    def fetch_html(url):
        for slug, html in pages.items():
            if slug in url:
                return html, 200, False
        return "", 200, False

    result = tn.scrape_tennistonic("2026-07-22", matches=matches, fetch_html=fetch_html)
    assert result["ok"] is True
    assert result["meta"]["officialMatchups"] == 2
    assert result["meta"]["matchedPicks"] == 1
    assert result["meta"]["expectedMatchups"] == 1  # keeps the strict gate happy
    assert result["meta"]["missingMatchups"] == []
    assert "Reda Bennani vs Adam Lynch" in result["meta"]["unpublishedMatchups"]
    pick = result["picks"][0]
    assert pick["source"] == "TennisTonic"
    assert pick["sport"] == "Tennis"
    assert pick["decision"] == "BET"
    assert pick["calibration_excluded"] is True
    assert pick.get("scope") is None
    assert pick["pick"] == "Barbora Krejcikova ML (Barbora Krejcikova vs Lucie Havlickova)"
    assert pick["selected_player"] == "Barbora Krejcikova"


def test_tennistonic_does_not_label_blocked_pages_as_unpublished_predictions():
    match = {"away": "Carlos Alcaraz", "home": "Tommy Paul"}
    result = tn.scrape_tennistonic(
        "2026-09-06", matches=[match], fetch_html=lambda _url: ("Challenge", 403, True),
    )
    assert result["ok"] is False
    assert result["picks"] == []
    assert "blocked" in result["error"]
    assert result["meta"]["blockedUrls"] == len(tn.tennistonic_urls(match))
    assert result["meta"]["unavailableMatchups"] == ["Carlos Alcaraz vs Tommy Paul"]
    assert result["meta"]["unpublishedMatchups"] == []


def test_tennistonic_reports_network_failure_separately_from_no_prediction():
    match = {"away": "Carlos Alcaraz", "home": "Tommy Paul"}
    result = tn.scrape_tennistonic(
        "2026-09-06", matches=[match], fetch_html=lambda _url: ("", 0, False),
    )
    assert result["ok"] is False
    assert result["meta"]["failedUrls"] == len(tn.tennistonic_urls(match))
    assert result["meta"]["blockedUrls"] == 0


def test_tennistonic_keeps_verified_prediction_when_another_match_is_blocked():
    matches = [
        {"away": "Carlos Alcaraz", "home": "Tommy Paul"},
        {"away": "Barbora Krejcikova", "home": "Lucie Havlickova"},
    ]

    def fetch(url):
        if "Alcaraz" in url:
            return "Challenge", 403, True
        return _tennistonic_html("Barbora Krejcikova Vs Lucie Havlickova", prediction="Krejcikova in 2"), 200, False

    result = tn.scrape_tennistonic("2026-09-06", matches=matches, fetch_html=fetch)
    assert result["ok"] is True
    assert len(result["picks"]) == 1
    assert result["meta"]["unavailableMatchups"] == ["Carlos Alcaraz vs Tommy Paul"]


def test_tennistonic_accepts_verified_no_prediction_even_if_alternative_url_is_blocked():
    match = {"away": "Carlos Alcaraz", "home": "Tommy Paul"}

    def fetch(url):
        if "Carlos-Alcaraz-Vs" in url:
            return _tennistonic_html("Carlos Alcaraz Vs Tommy Paul", not_prediction=True), 200, False
        return "Challenge", 403, True

    result = tn.scrape_tennistonic("2026-09-06", matches=[match], fetch_html=fetch)
    assert result["ok"] is True
    assert result["picks"] == []
    assert result["meta"]["unpublishedMatchups"] == ["Carlos Alcaraz vs Tommy Paul"]
    assert result["meta"]["unavailableMatchups"] == []


# --------------------------------------------------------------------------- #
# Scores24 tennis                                                              #
# --------------------------------------------------------------------------- #


def test_scores24_slug_matches_the_scores24_url_convention():
    # Scores24 slugs read "lastname-firstname" (the user's own example URL).
    assert tn._scores24_name_slug("Andrey Rublev") == "rublev-andrey"
    assert tn._scores24_name_slug("Timofey Skatov") == "skatov-timofey"
    urls = tn.scores24_tennis_candidate_urls("2026-07-22", {"away": "Andrey Rublev", "home": "Timofey Skatov"})
    assert (
        "https://scores24.live/en/tennis/m-22-07-2026-rublev-andrey-skatov-timofey-prediction" in urls
    )


def test_scrape_scores24_tennis_moneyline_only():
    matches = [
        {"away": "Andrey Rublev", "home": "Timofey Skatov", "tour": "ATP", "league": "atp", "start_time": "t"},
        {"away": "Carlos Alcaraz", "home": "Jannik Sinner", "tour": "ATP", "league": "atp", "start_time": "t"},
    ]
    rublev_url = "https://scores24.live/en/tennis/m-22-07-2026-rublev-andrey-skatov-timofey-prediction"
    sinner_url = "https://scores24.live/en/tennis/m-22-07-2026-sinner-jannik-alcaraz-carlos-prediction"
    responses = {
        "listing": ("<html></html>", 200, False),
        rublev_url: (_scores24_html("Rublev Skatov tennis", "Andrey Rublev Win", "-160"), 200, False),
        # A totals market must NOT publish (only match-winner picks are graded).
        sinner_url: (_scores24_html("Sinner Alcaraz tennis", "Total Over (22.5)", "-110"), 200, False),
    }
    client = _FakeScores24Client(responses)
    result = tn.scrape_scores24_tennis("2026-07-22", client=client, matches=matches)
    assert result["ok"] is True
    assert result["meta"]["matchedPicks"] == 1
    pick = result["picks"][0]
    assert pick["source"] == "Scores24Tennis"
    assert pick["pick"] == "Andrey Rublev ML (Andrey Rublev vs Timofey Skatov)"
    assert pick["odds"] == -160
    assert pick["calibration_excluded"] is True


# --------------------------------------------------------------------------- #
# Grading (isolated ESPN winner-flag path)                                     #
# --------------------------------------------------------------------------- #


def test_grade_tennis_picks_win_loss_pending():
    atp = _board(
        "Men's Singles",
        [
            _competition("Andrey Rublev", "Timofey Skatov", date="2026-07-22T09:30Z", winner="Andrey Rublev"),
            _competition("Carlos Alcaraz", "Jannik Sinner", date="2026-07-22T11:00Z", status="STATUS_SCHEDULED"),
        ],
    )
    fetch = _espn_fetch(atp)

    def pick(pid, away, home, selected):
        return {
            "id": pid,
            "date": "2026-07-22",
            "sport": "Tennis",
            "away_team": away,
            "home_team": home,
            "selected_player": selected,
            "pick": f"{selected} ML ({away} vs {home})",
        }

    picks = [
        pick("win", "Andrey Rublev", "Timofey Skatov", "Andrey Rublev"),
        pick("loss", "Andrey Rublev", "Timofey Skatov", "Timofey Skatov"),
        pick("pending", "Carlos Alcaraz", "Jannik Sinner", "Carlos Alcaraz"),
        pick("nomatch", "Nobody One", "Nobody Two", "Nobody One"),
    ]
    graded = tn.grade_tennis_picks(picks, fetch_json=fetch)
    assert graded["win"]["result"] == "win"
    assert graded["loss"]["result"] == "loss"
    assert graded["pending"]["result"] == "pending"
    assert graded["nomatch"]["result"] == "pending"


def test_grade_tennis_picks_falls_back_to_pick_string():
    atp = _board(
        "Men's Singles",
        [_competition("Andrey Rublev", "Timofey Skatov", date="2026-07-22T09:30Z", winner="Andrey Rublev")],
    )
    picks = [
        {
            "id": "x",
            "date": "2026-07-22",
            "sport": "Tennis",
            "away_team": "Andrey Rublev",
            "home_team": "Timofey Skatov",
            "pick": "Andrey Rublev ML (Andrey Rublev vs Timofey Skatov)",
        }
    ]
    graded = tn.grade_tennis_picks(picks, fetch_json=_espn_fetch(atp))
    assert graded["x"]["result"] == "win"


# --------------------------------------------------------------------------- #
# Pipeline registration + isolation                                           #
# --------------------------------------------------------------------------- #


def test_tennis_feeds_are_registered_across_the_pipeline():
    keys = ("tennistonic_tennis", "scores24_tennis")

    refresh = _load_module("refresh_external_feeds_tennis_test", ROOT / "scripts" / "refresh_external_feeds.py")
    for key in keys:
        assert key in refresh.FEED_RUNNERS
        assert key not in refresh.SPLIT_PROVIDER_FEEDS

    merge = _load_module("merge_external_feed_tennis_test", ROOT / "scripts" / "merge_external_feed_cache_payload.py")
    assert set(keys) <= merge.EXTERNAL_FEED_MODEL_KEYS
    model_merge = _load_module("merge_model_cache_tennis_test", ROOT / "scripts" / "merge_model_cache_payload.py")
    assert set(keys) <= model_merge.EXTERNAL_FEED_MODEL_KEYS

    # Tennis publishes no probability and has no calibration model, so it relies
    # on the per-pick calibration_excluded flag, not the bucket-key exclusion set.
    calibration = _load_module("pick_calibration_tennis_test", ROOT / "scripts" / "pick_calibration.py")
    assert not (set(keys) & calibration.CALIBRATION_EXCLUDED_MODEL_KEYS)

    profit_desk_text = (ROOT / "scripts" / "build_profit_desk.py").read_text(encoding="utf-8")
    assert '"tennistonic_"' in profit_desk_text
    parlay_text = (ROOT / "scripts" / "build_parlay_cards.py").read_text(encoding="utf-8")
    assert '"tennistonic"' in parlay_text
    assert "tennistonic_tennis" in parlay_text

    data_ts = (ROOT / "src" / "data.ts").read_text(encoding="utf-8")
    assert "scores24_tennis: 'Scores24Tennis'" in data_ts
    assert "tennistonic_tennis: 'TennisTonic'" in data_ts

    main_ts = (ROOT / "src" / "main.ts").read_text(encoding="utf-8")
    assert "'TENNIS'" in main_ts

    # TennisTonic is plain-HTTP so it runs on Actions; Scores24 tennis is
    # Cloudflare-blocked there and must stay local-only.
    workflow = (ROOT / ".github" / "workflows" / "external-feed-refresh.yml").read_text(encoding="utf-8")
    assert workflow.count("tennistonic_tennis") >= 2
    assert "scores24_tennis" not in workflow

    # Scores24 tennis must NOT ride the Scores24 MLB/WNBA publisher gate (a
    # partial tennis slate would wedge that whole commit). It gets its own
    # isolated publisher instead.
    scores24_publish = (ROOT / "scripts" / "scrapers" / "scores24_publish.sh").read_text(encoding="utf-8")
    assert "tennis" not in scores24_publish.lower()
    tennis_publish = (ROOT / "scripts" / "scrapers" / "tennis_publish.sh").read_text(encoding="utf-8")
    assert "tennistonic_tennis" in tennis_publish
    assert "scores24_tennis" in tennis_publish

    # Soft-launch: never a hard-required feed.
    site_upcheck = _load_module("site_upcheck_tennis_test", ROOT / "scripts" / "site_upcheck.py")
    assert not (set(keys) & site_upcheck.REQUIRED_SCORES24_FEED_KEYS)


def test_is_tennis_pick():
    assert tn.is_tennis_pick({"sport": "Tennis"}) is True
    assert tn.is_tennis_pick({"sport": "TENNIS"}) is True
    assert tn.is_tennis_pick({"sport": "MLB"}) is False
    assert tn.is_tennis_pick({}) is False


def test_tennis_grading_is_isolated_from_the_team_engine(monkeypatch):
    import scripts.auto_grade_picks as ag
    import pickgrader_server as server

    atp = _board(
        "Men's Singles",
        [_competition("Andrey Rublev", "Timofey Skatov", date="2026-07-22T09:30Z", winner="Andrey Rublev")],
    )
    monkeypatch.setattr(tn, "espn_tennis_matches", lambda date_iso, **k: _slate(atp))

    seen_by_team_engine = {}

    def fake_auto_grade(pending, _extra, _year):
        seen_by_team_engine["sports"] = {p.get("sport") for p in pending}
        return {"graded": {}, "startTimes": {}, "unsupported": {}, "gradeAnomalies": []}

    monkeypatch.setattr(server, "auto_grade", fake_auto_grade)
    monkeypatch.setattr(server, "apply_external_pick_metadata", lambda pick: 0)

    payload = {
        "date": "2026-07-22",
        "models": {
            "tennistonic_tennis": {
                "picks": [
                    {
                        "sport": "Tennis",
                        "decision": "BET",
                        "away_team": "Andrey Rublev",
                        "home_team": "Timofey Skatov",
                        "selected_player": "Andrey Rublev",
                        "pick": "Andrey Rublev ML (Andrey Rublev vs Timofey Skatov)",
                        "result": "pending",
                    }
                ]
            },
            "mlb_new": {"picks": [{"sport": "MLB", "decision": "BET", "pick": "Team ML", "result": "pending"}]},
        },
    }
    ag.grade_payload(payload)
    tennis_pick = payload["models"]["tennistonic_tennis"]["picks"][0]
    assert tennis_pick["result"] == "win"
    # The tennis pick was graded by the isolated path and never reached the team
    # engine; only the MLB pick did.
    assert seen_by_team_engine["sports"] == {"MLB"}


def _slate(board):
    matches = []
    for ev in board.get("events", []):
        for g in ev.get("groupings", []):
            for c in g.get("competitions", []):
                m = tn._espn_competition_to_match(c, "atp", g["grouping"]["displayName"], __import__("datetime").date(2026, 7, 22))
                if m:
                    matches.append(m)
    return matches, True
