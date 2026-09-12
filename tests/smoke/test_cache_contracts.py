from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts import site_upcheck


ROOT = Path(__file__).resolve().parents[2]
PLAYER_PROP_MODEL_KEYS = {
    "nba_player_props",
    "mlb_player_props",
    "wnba_player_props",
    "nfl_player_props",
    "cfb_player_props",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_files(cache_dir: Path) -> list[Path]:
    manifest = _read_json(cache_dir / "index.json")
    return [cache_dir / file for file in manifest.get("files") or []]


def _iter_model_picks(payload: dict):
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    for model_key, bucket in models.items():
        if not isinstance(bucket, dict):
            continue
        for pick in bucket.get("picks") or []:
            if isinstance(pick, dict):
                yield str(model_key), pick


def test_committed_cache_ids_are_unique_within_each_date():
    for cache_dir in (ROOT / "data" / "model_cache", ROOT / "data" / "player_props_cache"):
        for path in _manifest_files(cache_dir):
            payload = _read_json(path)
            date = str(payload.get("date") or payload.get("slate_date") or path.stem)
            ids = [
                str(pick.get("id") or "").strip()
                for _, pick in _iter_model_picks(payload)
                if str(pick.get("id") or "").strip()
            ]
            duplicates = [pick_id for pick_id, count in Counter(ids).items() if count > 1]
            assert not duplicates, f"{cache_dir.name}/{path.name} duplicate ids for {date}: {duplicates[:5]}"


def test_latest_player_props_cache_is_preserved_in_snapshot_archive():
    latest = _read_json(ROOT / "data" / "player_props_cache" / "latest.json")
    latest_date = str(latest.get("date") or "")

    assert latest_date
    latest_keys = site_upcheck._published_player_prop_keys(latest, latest_date)
    snapshot_keys = site_upcheck._snapshot_player_prop_keys(latest_date)

    if not snapshot_keys:
        return
    # Snapshots are the immutable reliability archive. The latest board is a capped,
    # EV-ranked public subset and must not be forced to carry every prior snapshot row.
    assert not (latest_keys - snapshot_keys)


def test_latest_player_prop_records_use_one_bucket_per_sport():
    latest = _read_json(ROOT / "data" / "player_props_cache" / "latest.json")
    models = latest.get("models") if isinstance(latest.get("models"), dict) else {}

    hard_keys = {"nba_player_props", "mlb_player_props", "wnba_player_props"}
    assert hard_keys.issubset(set(models))
    assert set(models).issubset(PLAYER_PROP_MODEL_KEYS)
    for model_key, bucket in models.items():
        assert bucket["ok"] is True
        sources = {
            str(pick.get("source") or "").strip()
            for pick in bucket.get("picks") or []
            if isinstance(pick, dict)
        }
        assert "Player Props" not in sources
        for pick in bucket.get("picks") or []:
            assert pick["scope"] == "player"
            assert pick["model_key"] == model_key
            rank_epoch = str(pick.get("ml_rank_epoch") or "")
            expected_prefix = f"{pick['sport']}:player_props_consensus_v2.0.0:published:"
            assert rank_epoch.startswith(expected_prefix)


def test_latest_player_prop_boards_stay_ranked_and_deduped():
    latest = _read_json(ROOT / "data" / "player_props_cache" / "latest.json")
    models = latest.get("models") if isinstance(latest.get("models"), dict) else {}

    hard_keys = {"nba_player_props", "mlb_player_props", "wnba_player_props"}
    for model_key in PLAYER_PROP_MODEL_KEYS:
        bucket = models.get(model_key)
        if not isinstance(bucket, dict):
            assert model_key not in hard_keys
            continue
        picks = bucket.get("picks") or []
        ranks = [int(pick["ml_rank"]) for pick in picks]
        assert ranks == list(range(1, len(picks) + 1))
        assert not any(pick.get("carried_forward") for pick in picks)
        market_keys = [
            site_upcheck._player_prop_market_key(pick)
            for pick in picks
            if isinstance(pick, dict)
        ]
        assert len(market_keys) == len(set(market_keys))
