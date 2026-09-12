#!/usr/bin/env python3
"""Merge generated player-prop models while preserving committed grades."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from cache_manifest import write_cache_manifest
except ModuleNotFoundError:  # pragma: no cover - exercised when tests import by file path
    from scripts.cache_manifest import write_cache_manifest


PLAYER_PROPS_CACHE_DIR = Path("data/player_props_cache")
PLAYER_PROPS_SNAPSHOT_DIR = Path("data/player_props_snapshots")
CONSENSUS_METADATA_PATH = Path("player_props/artifacts/player_props_consensus_metadata.json")
PUBLIC_PLAYER_PROP_MODEL_KEYS = {
    "nba_player_props",
    "mlb_player_props",
    "wnba_player_props",
    "nfl_player_props",
    "cfb_player_props",
}
HARD_PLAYER_PROP_MODEL_KEYS = {
    "nba_player_props",
    "mlb_player_props",
    "wnba_player_props",
}
SOFT_PLAYER_PROP_MODEL_KEYS = {
    "nfl_player_props",
    "cfb_player_props",
}
PICK_METADATA_FIELDS = {"result", "start_time", "game_start_time", "pregame_snapshot"}
MARKET_METADATA_FIELDS = {"start_time", "game_start_time", "pregame_snapshot"}
MAX_PUBLISHED_PROPS_PER_GAME = 8
MAX_PUBLISHED_PROPS_PER_PLAYER = 1
_CONSENSUS_MODELS: list[str] | None = None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _consensus_models() -> list[str]:
    global _CONSENSUS_MODELS
    if _CONSENSUS_MODELS is not None:
        return _CONSENSUS_MODELS
    metadata = _read_json(CONSENSUS_METADATA_PATH) or {}
    model_map = metadata.get("models") if isinstance(metadata.get("models"), dict) else {}
    _CONSENSUS_MODELS = [f"{name}: {description}" for name, description in sorted(model_map.items())]
    return _CONSENSUS_MODELS


def _consensus_models_for_sport(sport: str) -> list[str]:
    sport_prefix = f"{sport.strip().lower()}_"
    return [label for label in _consensus_models() if label.lower().startswith(sport_prefix)]


def _ensure_consensus_fields(pick: dict[str, Any]) -> dict[str, Any]:
    if str(pick.get("ml_model_version") or "").strip() != "player_props_consensus_v2.0.0":
        return pick
    models = _consensus_models()
    sport = str(pick.get("sport") or "").strip().upper()
    applicable_models = _consensus_models_for_sport(sport)
    if models:
        pick.setdefault("consensus_model_count", len(models))
        pick.setdefault("consensus_models", models)
    if applicable_models:
        pick.setdefault("consensus_applicable_models", applicable_models)
        pick.setdefault("consensus_record_models", applicable_models)
    model_names = ", ".join(label.split(":", 1)[0] for label in models)
    if model_names:
        factors = pick.get("key_factors")
        if not isinstance(factors, list):
            factors = []
        if not any("Four-model consensus suite active" in str(factor) for factor in factors):
            pick["key_factors"] = [f"Four-model consensus suite active: {model_names}", *factors]
    reason = str(pick.get("reason") or "")
    if reason.startswith("The 2026 season model and roster-aware history model qualify this market"):
        pick["reason"] = reason.replace(
            "The 2026 season model and roster-aware history model qualify this market",
            f"The active four-model consensus suite qualifies this market through the {sport} season and roster-aware history voters",
            1,
        )
    return pick


def _pick_key(pick: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(pick.get(key) or "").strip().lower()
        for key in ("id", "source", "sport", "date", "pick", "matchup", "ml_rank_epoch", "ranking_epoch", "model_epoch")
    )


def _market_key(pick: dict[str, Any]) -> tuple[str, ...]:
    primary = tuple(
        str(pick.get(key) or "").strip().lower()
        for key in ("sport", "date", "game_id", "player_id", "stat_key", "selection", "line")
    )
    if all(primary[:6]) and primary[6]:
        return primary
    return tuple(
        str(pick.get(key) or "").strip().lower()
        for key in ("source", "sport", "date", "pick", "matchup")
    )


def _rank_epoch(pick: dict[str, Any]) -> str:
    return str(
        pick.get("ml_rank_epoch")
        or pick.get("ranking_epoch")
        or pick.get("model_epoch")
        or ""
    ).strip()


def _sport_from_model_key(model_key: str) -> str:
    value = str(model_key or "").strip().lower()
    if value == "wnba_3pm":
        return "WNBA"
    if value.startswith("mlb_player_props"):
        return "MLB"
    if value.startswith("wnba_player_props"):
        return "WNBA"
    if value.startswith("nba_player_props"):
        return "NBA"
    if value.startswith("nfl_player_props"):
        return "NFL"
    if value.startswith("cfb_player_props"):
        return "CFB"
    return ""


def _same_sport_model_bucket(model_key: str, bucket_key: str) -> bool:
    if "wnba_3pm" in {
        str(model_key or "").strip().lower(),
        str(bucket_key or "").strip().lower(),
    }:
        return str(model_key or "").strip().lower() == str(bucket_key or "").strip().lower()
    sport = _sport_from_model_key(model_key)
    return bool(sport and _sport_from_model_key(bucket_key) == sport)


def _snapshot_buckets(date_iso: str, model_key: str, snapshot_dir: Path) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for path in sorted((snapshot_dir / date_iso).glob("*.json")):
        snapshot = _read_json(path)
        if not snapshot or str(snapshot.get("date") or "").strip() != date_iso:
            continue
        models = snapshot.get("models") if isinstance(snapshot.get("models"), dict) else {}
        for bucket_key, bucket in models.items():
            if isinstance(bucket, dict) and _same_sport_model_bucket(model_key, str(bucket_key)):
                buckets.append(bucket)
    return buckets


def _current_buckets(current_models: dict[str, Any], model_key: str) -> list[dict[str, Any]]:
    return [
        bucket
        for bucket_key, bucket in current_models.items()
        if isinstance(bucket, dict) and _same_sport_model_bucket(model_key, str(bucket_key))
    ]


def _ml_owned_market_pick(pick: dict[str, Any]) -> bool:
    return bool(
        pick.get("market_priced") is True
        and str(pick.get("probability_source") or "").strip() == "player_props_ml_v1"
    )


def _rank_pick_sort_key(
    pick: dict[str, Any],
) -> tuple[int, float, float, float, float, int, str, str]:
    decision_rank = {"BET": 0, "LEAN": 1}
    decision = decision_rank.get(str(pick.get("decision") or "").strip().upper(), 2)
    expected_value = -float(pick.get("ml_expected_value") or 0.0)
    if _ml_owned_market_pick(pick):
        primary_rank = expected_value
        secondary_rank = float(decision)
    else:
        primary_rank = float(decision)
        secondary_rank = expected_value
    return (
        0 if _ml_owned_market_pick(pick) else 1,
        primary_rank,
        secondary_rank,
        -float(pick.get("ml_edge") or 0.0),
        -float(pick.get("ml_probability") or pick.get("probability") or 0.0),
        int(pick.get("ml_rank") or pick.get("rank") or 9999),
        str(pick.get("id") or ""),
        "|".join(_market_key(pick)),
    )


def _game_key(pick: dict[str, Any]) -> tuple[str, str, str]:
    game = str(
        pick.get("game_id") or pick.get("event_id") or pick.get("matchup") or ""
    ).strip().lower()
    return (
        str(pick.get("sport") or "").strip().upper(),
        str(pick.get("date") or "").strip(),
        game or "unknown-game",
    )


def _player_key(pick: dict[str, Any]) -> tuple[str, str]:
    player = str(
        pick.get("player_id")
        or pick.get("market_athlete_id")
        or pick.get("player_name")
        or ""
    ).strip().lower()
    if not player:
        player = "|".join(_market_key(pick))
    return str(pick.get("sport") or "").strip().upper(), player


def _rank_published_picks(fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_market: dict[tuple[str, ...], dict[str, Any]] = {}
    for pick in sorted(fresh, key=_rank_pick_sort_key):
        best_by_market.setdefault(_market_key(pick), pick)

    ranked: list[dict[str, Any]] = []
    per_player: dict[tuple[str, str], int] = {}
    per_game: dict[tuple[str, str, str], int] = {}
    for pick in sorted(best_by_market.values(), key=_rank_pick_sort_key):
        player_key = _player_key(pick)
        game_key = _game_key(pick)
        if per_player.get(player_key, 0) >= MAX_PUBLISHED_PROPS_PER_PLAYER:
            continue
        if per_game.get(game_key, 0) >= MAX_PUBLISHED_PROPS_PER_GAME:
            continue
        ranked.append(pick)
        per_player[player_key] = per_player.get(player_key, 0) + 1
        per_game[game_key] = per_game.get(game_key, 0) + 1

    for index, pick in enumerate(ranked, start=1):
        pick["ml_rank"] = index
        pick["model_rank"] = index
        pick["rank"] = index
    return ranked


def _preserve_pick_metadata(
    source_buckets: list[Any],
    generated_bucket: Any,
) -> Any:
    if not isinstance(generated_bucket, dict):
        return generated_bucket
    generated_picks = generated_bucket.get("picks")
    if not isinstance(generated_picks, list):
        return generated_bucket
    source_picks = [
        pick
        for bucket in source_buckets
        if isinstance(bucket, dict) and isinstance(bucket.get("picks"), list)
        for pick in bucket.get("picks") or []
        if isinstance(pick, dict)
    ]
    metadata = {
        _pick_key(pick): {field: pick[field] for field in PICK_METADATA_FIELDS if field in pick}
        for pick in source_picks
    }
    metadata_by_market = {
        _market_key(pick): {field: pick[field] for field in MARKET_METADATA_FIELDS if field in pick}
        for pick in source_picks
    }
    result_by_market_epoch: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    for pick in source_picks:
        if "result" not in pick:
            continue
        key = (_market_key(pick), _rank_epoch(pick))
        candidate = str(pick.get("result") or "").strip().lower()
        current = str((result_by_market_epoch.get(key) or {}).get("result") or "").strip().lower()
        if candidate not in {"", "pending"} or not current:
            result_by_market_epoch[key] = {"result": pick["result"]}
    merged = dict(generated_bucket)
    generated_with_metadata = [
        _ensure_consensus_fields({
            **pick,
            **metadata_by_market.get(_market_key(pick), {}),
            **result_by_market_epoch.get((_market_key(pick), _rank_epoch(pick)), {}),
            **metadata.get(_pick_key(pick), {}),
        }) if isinstance(pick, dict) else pick
        for pick in generated_picks
    ]
    fresh_picks = [
        pick
        for pick in generated_with_metadata
        if isinstance(pick, dict)
    ]
    if generated_bucket.get("football_baseline") is True:
        # Staking concentration limits should not hide zero-stake projections.
        unique = {_market_key(pick): pick for pick in fresh_picks}
        merged["picks"] = sorted(unique.values(), key=lambda p: (str(p.get("start_time")), str(p.get("player_name")), str(p.get("stat_key"))))
        for index, pick in enumerate(merged["picks"], 1):
            pick["rank"] = index
    else:
        merged["picks"] = _rank_published_picks(fresh_picks)
    return merged


def merge_payload(
    generated: dict[str, Any],
    cache_dir: Path,
    snapshot_dir: Path = PLAYER_PROPS_SNAPSHOT_DIR,
    *,
    include_current: bool = True,
) -> dict[str, Any]:
    date_iso = str(generated.get("date") or "").strip()
    if not date_iso:
        raise SystemExit("Generated player-props cache is missing date")
    current = _read_json(cache_dir / f"{date_iso}.json") or {}
    current_models = current.get("models") if isinstance(current.get("models"), dict) else {}
    generated_models = generated.get("models") if isinstance(generated.get("models"), dict) else {}
    public_generated_models = {
        key: bucket
        for key, bucket in generated_models.items()
        if key in PUBLIC_PLAYER_PROP_MODEL_KEYS
    }

    merged = dict(generated)
    merged["models"] = {
        key: _preserve_pick_metadata(
            _snapshot_buckets(date_iso, key, snapshot_dir)
            + (_current_buckets(current_models, key) if include_current else []),
            bucket,
        )
        for key, bucket in public_generated_models.items()
    }
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", help="Generated player-props latest.json")
    parser.add_argument("--cache-dir", default=str(PLAYER_PROPS_CACHE_DIR))
    parser.add_argument("--snapshot-dir", default=str(PLAYER_PROPS_SNAPSHOT_DIR))
    parser.add_argument("--ignore-current-cache", action="store_true")
    args = parser.parse_args()

    generated = _read_json(Path(args.generated))
    if not generated:
        raise SystemExit(f"Could not read generated player-props cache: {args.generated}")
    cache_dir = Path(args.cache_dir)
    merged = merge_payload(
        generated,
        cache_dir,
        Path(args.snapshot_dir),
        include_current=not args.ignore_current_cache,
    )
    date_iso = str(merged["date"])
    _write_json(cache_dir / f"{date_iso}.json", merged)
    _write_json(cache_dir / "latest.json", merged)
    write_cache_manifest(cache_dir)
    print(json.dumps({"date": date_iso, "models": sorted(merged["models"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
