import pytest
import requests

from scripts.scrapers import espn_scoreboard as espn
from scripts.scrapers import scores24_scraper as scores24
from scripts.scrapers import tennis_scraper as tennis


class Session:
    def __init__(self, results):
        self.results = iter(results)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: result})()


def test_http_is_upgraded_and_query_is_preserved():
    session = Session([{"events": []}])
    assert espn.fetch_scoreboard_json("http://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=20260909&groups=80&limit=1000", session=session) == {"events": []}
    assert session.urls == ["https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=20260909&groups=80&limit=1000"]


def test_transient_failure_recovers_with_bounded_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(espn.time, "sleep", sleeps.append)
    response = requests.Response()
    response.status_code = 403
    session = Session([requests.HTTPError(response=response), {"events": []}])
    assert espn.fetch_scoreboard_json(tennis.ESPN_SCOREBOARD_URL, session=session) == {"events": []}
    assert sleeps == [1]
    assert session.urls[0].startswith("https://")
    assert session.urls[1].startswith("http://")


def test_invalid_payload_is_never_an_off_day(monkeypatch):
    monkeypatch.setattr(espn.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="events list"):
        espn.fetch_scoreboard_json(tennis.ESPN_SCOREBOARD_URL, session=Session([{}, {}, {}]))


def test_failed_scoreboard_is_unresolved_without_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(espn.time, "sleep", lambda _: None)
    monkeypatch.setattr(scores24, "MODEL_CACHE_DIR", tmp_path)
    assert scores24.fetch_daily_matchups("mlb", "2026-09-09", session=Session([requests.Timeout()] * 3)) == ([], False)


def test_valid_empty_scoreboard_is_off_day(monkeypatch, tmp_path):
    monkeypatch.setattr(scores24, "MODEL_CACHE_DIR", tmp_path)
    assert scores24.fetch_daily_matchups("wnba", "2026-09-09", session=Session([{"events": []}])) == ([], True)


def test_tennis_requires_both_tours_to_confirm_off_day():
    def partial(url):
        if "/wta/" in url:
            raise requests.Timeout()
        return {"events": []}
    assert tennis.espn_tennis_matches("2026-09-09", fetch_json=partial) == ([], False)


def test_tennis_uses_shared_transport(monkeypatch):
    urls = []
    monkeypatch.setattr(tennis, "fetch_scoreboard_json", lambda url: urls.append(url) or {"events": []})
    assert tennis.espn_tennis_matches("2026-09-09") == ([], True)
    assert len(urls) == 2
    assert all(url.startswith("https://") for url in urls)


def test_cfb_recovers_from_https_403_without_dropping_slate_filters(monkeypatch):
    from CFBPredictionModel import cfb_core

    monkeypatch.setattr(espn.time, "sleep", lambda _: None)
    response = requests.Response()
    response.status_code = 403
    session = Session([requests.HTTPError(response=response), {"events": []}])
    monkeypatch.setattr(espn.requests, "get", session.get)
    coverage = {}
    assert cfb_core.load_live_slate("2026-09-09", coverage=coverage) == []
    assert coverage["official_games"] == 0
    assert session.urls[-1] == "http://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates=20260909&groups=80&limit=1000"
