from scripts.train_player_prop_consensus_ml import POLICIES, _publication_plan, _windows


def test_consensus_windows_roll_forward_to_latest_sport_market_date():
    validation, holdout = _windows(
        "WNBA",
        [
            {"sport": "WNBA", "date": "2026-06-01"},
            {"sport": "MLB", "date": "2026-07-31"},
            {"sport": "WNBA", "date": "2026-07-29"},
        ],
    )

    assert validation == ("2026-07-01", "2026-07-02", "2026-07-15")
    assert holdout == ("2026-07-15", "2026-07-16", "2026-07-29")


def test_consensus_windows_require_dated_rows_for_the_requested_sport():
    try:
        _windows("WNBA", [{"sport": "MLB", "date": "2026-07-29"}])
    except ValueError as exc:
        assert "WNBA" in str(exc)
    else:
        raise AssertionError("Expected missing WNBA market history to fail clearly")
    try:
        _windows("NFL", [{"sport": "MLB", "date": "2026-07-29"}])
    except ValueError as exc:
        assert "NFL" in str(exc)
    else:
        raise AssertionError("Expected missing NFL market history to fail clearly")


def test_consensus_preserves_an_active_sport_when_its_candidate_fails():
    candidate = {
        "active": True,
        "sports": {
            "MLB": {"active": True, "source": "new-mlb"},
            "WNBA": {"active": False, "source": "failed-wnba"},
        },
    }
    existing = {
        "active": True,
        "sports": {
            "MLB": {"active": True, "source": "old-mlb"},
            "WNBA": {"active": True, "source": "trusted-wnba"},
        },
    }

    publication, publish_artifacts_for = _publication_plan(candidate, existing)

    assert publish_artifacts_for == {"MLB"}
    assert publication["sports"]["MLB"]["source"] == "new-mlb"
    assert publication["sports"]["WNBA"] == {"active": True, "source": "trusted-wnba"}
    assert publication["preserved_sports"] == ["WNBA"]


def test_consensus_policies_register_nfl_and_cfb_volume_markets():
    assert set(POLICIES) >= {"MLB", "WNBA", "NFL", "CFB"}
    assert set(POLICIES["NFL"]) == {"passing_yards", "rushing_yards", "receiving_yards", "receptions"}
    assert set(POLICIES["CFB"]) == set(POLICIES["NFL"])
