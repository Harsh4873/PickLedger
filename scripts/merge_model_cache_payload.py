#!/usr/bin/env python3
"""Merge a generated model cache payload into the latest checked-out cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache_manifest import write_cache_manifest  # noqa: E402
from merge_external_feed_cache_payload import _demote_scraped_feed_picks  # noqa: E402


def _missing_executable_odds(pick: Any) -> bool:
    if not isinstance(pick, dict):
        return True
    odds = pick.get("odds")
    if odds in (None, ""):
        return True
    try:
        return float(odds) == 0
    except (TypeError, ValueError):
        return True


def _demote_unpriced_tennis_picks(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Publish unpriced in-house tennis as research rows, never as bets.

    The tennis model emits a real probability but no market price — ESPN tennis
    moneylines are not on the shared odds attachment. After unpriced wins
    stopped being booked at even money, those rows still showed as 1u BET/LEAN
    recommendations with no measurable P&L. Demote them the same way scraped
    tips are demoted: PASS at 0u, preserve source_decision/source_units.
    """
    demoted = dict(payload)
    changed = 0

    def demote_bucket(bucket: Any) -> Any:
        nonlocal changed
        if not isinstance(bucket, dict):
            return bucket
        picks = bucket.get("picks")
        if not isinstance(picks, list):
            return bucket
        updated_picks: list[Any] = []
        bucket_changed = False
        for pick in picks:
            if not isinstance(pick, dict):
                updated_picks.append(pick)
                continue
            sport = str(pick.get("sport") or "").strip().lower()
            decision = str(pick.get("decision") or "").strip().upper()
            if sport == "tennis" and decision in {"BET", "LEAN"} and _missing_executable_odds(pick):
                revised = dict(pick)
                revised["decision"] = "PASS"
                revised["units"] = 0
                revised["unpriced_tennis_demoted"] = True
                revised.setdefault("source_decision", decision)
                revised.setdefault("source_units", pick.get("units"))
                updated_picks.append(revised)
                bucket_changed = True
                changed += 1
            else:
                updated_picks.append(pick)
        if not bucket_changed:
            return bucket
        revised_bucket = dict(bucket)
        revised_bucket["picks"] = updated_picks
        return revised_bucket

    models = payload.get("models")
    if isinstance(models, dict):
        demoted["models"] = {key: demote_bucket(bucket) for key, bucket in models.items()}
    tennis_alias = payload.get("tennis")
    if isinstance(tennis_alias, dict):
        demoted["tennis"] = demote_bucket(tennis_alias)
    return demoted, changed


MODEL_CACHE_DIR = Path("data/model_cache")
EXTERNAL_FEED_MODEL_KEYS = {
    "sportytrader",
    "sportytrader_nba",
    "sportytrader_nba_summer",
    "sportytrader_mlb",
    "sportytrader_wnba",
    "sportytrader_fifa_world_cup",
    "sportytrader_cfb",
    "sportsgambler",
    "sportsgambler_nba",
    "sportsgambler_nba_summer",
    "sportsgambler_mlb",
    "sportsgambler_wnba",
    "sportsgambler_fifa_world_cup",
    "sportsgambler_cfb",
    "scores24_nba_summer",
    "scores24_wnba",
    "scores24_mlb",
    "scores24_fifa_world_cup",
    "scores24_cfb",
    "forebet_mls",
    "forebet_mlb",
    "forebet_wnba",
    "tennistonic_tennis",
    "scores24_tennis",
}
RETIRED_MODEL_KEYS = {
    "covers_experts_mlb",
    "covers_experts_wnba",
    "covers_computer_mlb",
    "covers_consensus_mlb",
    "covers_consensus_wnba",
    "covers_props_mlb",
}
RETIRED_MODEL_PREFIXES = ("covers_",)
SPLIT_EXTERNAL_FEED_LEGACY_KEYS = {"sportytrader", "sportsgambler"}
DEPLOYED_MODEL_KEYS = {
    "mlb_new",
    "mlb_inning",
    "mlb_first_five",
    "mlb_team_total",
    "wnba",
    "nba",
    "nba_playoffs",
    "nba_summer",
    "fifa_world_cup",
    "mls",
    "nfl",
    "cfb",
    "tennis",
    *EXTERNAL_FEED_MODEL_KEYS,
}
MODEL_ALIAS_KEYS = {
    "nba",
    "nba_old",
    "nba_playoffs",
    "nba_summer",
    "wnba",
    "nba_props",
    "mlb",
    "mlb_old",
    "mlb_new",
    "mlb_inning",
    "mlb_first_five",
    "mlb_team_total",
    "ipl",
    "fifa_world_cup",
    "mls",
    "nfl",
    "cfb",
}
MODEL_ALIAS_TO_MODEL_KEY = {
    "mlb": "mlb_old",
    **{key: key for key in MODEL_ALIAS_KEYS if key != "mlb"},
}
PICK_METADATA_FIELDS = {"result", "start_time", "game_start_time", "pregame_snapshot"}
MARKET_ODDS_METADATA_FIELDS = {
    # Pregame market prices captured by scripts/market_odds.py.  Once a game
    # goes live the attach step skips it, so these captured pregame values
    # must survive later merges instead of being wiped by a regenerated pick.
    "market_odds_provider",
    "market_odds_captured_at",
    "market_updated_at",
    "market_home_odds",
    "market_away_odds",
    "market_draw_odds",
    "market_over_odds",
    "market_under_odds",
    "market_line",
    "selected_odds",
    "opposite_odds",
    "market_no_vig_selected_probability",
    "assumed_odds_replaced",
    "model_assumed_odds",
}
REPLACED_PRICE_FIELDS = ("odds", "pricing_type", "odds_source", "price_source", "market_priced")



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge generated model cache JSON into data/model_cache.")
    parser.add_argument("generated", help="Path to the generated latest.json from refresh_model_cache.py.")
    parser.add_argument("--cache-dir", default=str(MODEL_CACHE_DIR), help="Cache directory to update.")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def stamp_bucket_date_if_missing(bucket: Any, date_iso: str) -> None:
    if not isinstance(bucket, dict):
        return
    existing_date = bucket.get("date")
    if isinstance(existing_date, str) and existing_date.strip():
        return
    bucket["date"] = date_iso


def _is_retired_model_key(value: Any) -> bool:
    return str(value or "").strip().lower().startswith(RETIRED_MODEL_PREFIXES)


def _without_retired_buckets(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop retired feeds from every cache representation."""
    cleaned = dict(payload)
    for container_key in ("models", "external_feeds"):
        container = payload.get(container_key)
        if isinstance(container, dict):
            cleaned[container_key] = {
                key: value
                for key, value in container.items()
                if not _is_retired_model_key(key)
            }
    for key in list(cleaned):
        if _is_retired_model_key(key):
            cleaned.pop(key, None)
    return cleaned


def _seed_external_feeds_from_latest(latest_payload: dict[str, Any]) -> dict[str, Any]:
    """Carry feed buckets across slate rollovers so a new-day model refresh does not wipe them."""
    seeded: dict[str, Any] = {}
    external_feeds = latest_payload.get("external_feeds")
    if isinstance(external_feeds, dict):
        seeded.update({
            key: value
            for key, value in external_feeds.items()
            if not _is_retired_model_key(key)
        })
    models = latest_payload.get("models")
    if isinstance(models, dict):
        for key in EXTERNAL_FEED_MODEL_KEYS:
            if key in models and key not in seeded:
                seeded[key] = models[key]
    for key in EXTERNAL_FEED_MODEL_KEYS:
        if key in latest_payload and key not in seeded:
            seeded[key] = latest_payload[key]
    return seeded


def _current_payload(cache_dir: Path, date_iso: str) -> dict[str, Any]:
    date_payload = _read_json(cache_dir / f"{date_iso}.json")
    if date_payload and str(date_payload.get("date") or "") == date_iso:
        return date_payload
    latest_payload = _read_json(cache_dir / "latest.json")
    if latest_payload and str(latest_payload.get("date") or "") == date_iso:
        return latest_payload
    if latest_payload:
        seeded_feeds = _seed_external_feeds_from_latest(latest_payload)
        if seeded_feeds:
            return {"date": date_iso, "models": {}, "external_feeds": seeded_feeds}
    return {"date": date_iso, "models": {}}


def _legacy_feed_keys_with_split(current: dict[str, Any]) -> set[str]:
    current_keys: set[str] = set()
    models = current.get("models")
    if isinstance(models, dict):
        current_keys.update(str(key) for key in models)
    external_feeds = current.get("external_feeds")
    if isinstance(external_feeds, dict):
        current_keys.update(str(key) for key in external_feeds)
    current_keys.update(str(key) for key in current if key in EXTERNAL_FEED_MODEL_KEYS)
    return {
        legacy_key
        for legacy_key in SPLIT_EXTERNAL_FEED_LEGACY_KEYS
        if any(key.startswith(f"{legacy_key}_") for key in current_keys)
    }


def _merged_models(current: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    current_models = current.get("models") if isinstance(current.get("models"), dict) else {}
    generated_models = generated.get("models") if isinstance(generated.get("models"), dict) else {}
    external_feeds = current.get("external_feeds") if isinstance(current.get("external_feeds"), dict) else {}
    replaced_legacy_keys = _legacy_feed_keys_with_split(current)

    keep_keys = set(DEPLOYED_MODEL_KEYS)
    keep_keys.update(str(key) for key in external_feeds)
    keep_keys.difference_update(replaced_legacy_keys)
    merged = {
        key: current_models[key]
        for key in keep_keys
        if key in current_models
    }
    for key, bucket in generated_models.items():
        if key in EXTERNAL_FEED_MODEL_KEYS and (key in current_models or key in external_feeds):
            # A model refresh can run for several minutes while the local Scores24
            # publisher or another feed writer lands newer data. The latest checked-
            # out external bucket is authoritative; never overwrite it with the
            # refresh job's stale starting snapshot during the push-retry merge.
            continue
        merged[key] = _preserve_pick_metadata(current_models.get(key), bucket)
    return merged


def _pick_key(pick: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(pick.get(key) or "").strip().lower()
        for key in ("source", "sport", "date", "pick", "matchup", "game")
    )


def _replacement_key(pick: dict[str, Any]) -> tuple[str, ...]:
    matchup = str(pick.get("matchup") or pick.get("game") or "").strip().lower()
    market = str(pick.get("market") or pick.get("market_type") or "").strip().lower()
    return tuple(
        str(value or "").strip().lower()
        for value in (
            pick.get("source"),
            pick.get("sport"),
            pick.get("date") or pick.get("game_date") or pick.get("slate_date"),
            matchup,
            market,
        )
    )


def _settled_result(pick: dict[str, Any]) -> bool:
    return str(pick.get("result") or "").strip().lower() in {"win", "loss", "push"}


def _preserve_pick_metadata(current_bucket: Any, generated_bucket: Any) -> Any:
    if not isinstance(current_bucket, dict) or not isinstance(generated_bucket, dict):
        return generated_bucket
    current_picks = current_bucket.get("picks")
    if generated_bucket.get("ok") is False and isinstance(current_picks, list) and current_picks:
        # Keep the already published same-date record when a provider fails.
        # The error remains authoritative, so health checks still request a
        # recovery refresh instead of certifying stale output as healthy.
        retained = {**current_bucket, **generated_bucket}
        retained["picks"] = current_picks
        retained["preserved_after_refresh_error"] = True
        return retained
    generated_picks = generated_bucket.get("picks")
    if not isinstance(current_picks, list) or not isinstance(generated_picks, list):
        return generated_bucket
    def _kept_fields(pick: dict[str, Any]) -> dict[str, Any]:
        kept = {
            field: pick[field]
            for field in (*PICK_METADATA_FIELDS, *MARKET_ODDS_METADATA_FIELDS)
            if field in pick
        }
        if pick.get("assumed_odds_replaced") is True:
            # A real captured price must not be reverted to a regenerated
            # assumed price after the game has started.
            kept.update({field: pick[field] for field in REPLACED_PRICE_FIELDS if field in pick})
        return kept

    metadata = {
        _pick_key(pick): _kept_fields(pick)
        for pick in current_picks
        if isinstance(pick, dict)
    }
    generated_keys = {
        _pick_key(pick)
        for pick in generated_picks
        if isinstance(pick, dict)
    }
    generated_replacement_keys = {
        _replacement_key(pick)
        for pick in generated_picks
        if isinstance(pick, dict) and all(_replacement_key(pick))
    }
    merged = dict(generated_bucket)
    merged["picks"] = [
        {**pick, **metadata.get(_pick_key(pick), {})} if isinstance(pick, dict) else pick
        for pick in generated_picks
    ]
    merged["picks"].extend(
        pick for pick in current_picks
        if isinstance(pick, dict)
        and _pick_key(pick) not in generated_keys
        and (_settled_result(pick) or _replacement_key(pick) not in generated_replacement_keys)
    )
    return merged


def merge_payload(generated: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    date_iso = str(generated.get("date") or "").strip()
    if not date_iso:
        raise SystemExit("Generated model cache is missing date")

    current = _without_retired_buckets(_current_payload(cache_dir, date_iso))
    generated = _without_retired_buckets(generated)
    merged = dict(current)
    for key in ("date", "updatedAt", "generatedAt", "generatedBy", "errors"):
        if key in generated:
            merged[key] = generated[key]
    merged["models"] = _merged_models(current, generated)
    replaced_legacy_keys = _legacy_feed_keys_with_split(current)
    for key in replaced_legacy_keys:
        merged.pop(key, None)
    current_external = current.get("external_feeds") if isinstance(current.get("external_feeds"), dict) else {}
    if current_external:
        merged["external_feeds"] = {
            key: value
            for key, value in current_external.items()
            if key not in replaced_legacy_keys
        }

    for alias_key, model_key in MODEL_ALIAS_TO_MODEL_KEY.items():
        if model_key in merged["models"]:
            merged[alias_key] = merged["models"][model_key]
        elif alias_key in current:
            merged[alias_key] = current[alias_key]
        elif alias_key in generated and generated[alias_key]:
            merged[alias_key] = generated[alias_key]
    for key in EXTERNAL_FEED_MODEL_KEYS:
        if key in replaced_legacy_keys:
            continue
        if key in current:
            merged[key] = current[key]

    for key in ("mlb_new", "wnba"):
        stamp_bucket_date_if_missing(merged["models"].get(key), date_iso)
        stamp_bucket_date_if_missing(merged.get(key), date_iso)

    # Same demotion as the feed-writer merge: a model-cache refresh copies
    # scraped buckets through from the dated file, and without this those
    # rows would republish as BET/LEAN the next time in-house models land.
    # Unpriced tennis is demoted here too so a refresh cannot republish
    # confidence-only rows as staked recommendations.
    scraped = _demote_scraped_feed_picks(_without_retired_buckets(merged))
    demoted, _ = _demote_unpriced_tennis_picks(scraped)
    return demoted


def main() -> int:
    args = _parse_args()
    generated_path = Path(args.generated)
    cache_dir = Path(args.cache_dir)
    generated = _read_json(generated_path)
    if not generated:
        raise SystemExit(f"Could not read generated model cache: {generated_path}")

    merged = merge_payload(generated, cache_dir)
    date_iso = str(merged["date"])
    _write_json(cache_dir / f"{date_iso}.json", merged)
    _write_json(cache_dir / "latest.json", merged)
    write_cache_manifest(cache_dir)
    print(json.dumps({
        "date": date_iso,
        "models": sorted((merged.get("models") or {}).keys()),
        "generated": str(generated_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
