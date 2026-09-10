#!/usr/bin/env python3
"""Merge generated external feed cache payloads into the latest cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cache_manifest import write_cache_manifest  # noqa: E402


MODEL_CACHE_DIR = Path("data/model_cache")
EXTERNAL_FEED_MODEL_KEYS = {
    "sportytrader",
    "sportytrader_nba",
    "sportytrader_nba_summer",
    "sportytrader_mlb",
    "sportytrader_wnba",
    "sportytrader_fifa_world_cup",
    "sportytrader_cfb",
    "sportytrader_nfl",
    "sportsgambler",
    "sportsgambler_nba",
    "sportsgambler_nba_summer",
    "sportsgambler_mlb",
    "sportsgambler_wnba",
    "sportsgambler_fifa_world_cup",
    "sportsgambler_cfb",
    "sportsgambler_nfl",
    "scores24_nba_summer",
    "scores24_wnba",
    "scores24_mlb",
    "scores24_fifa_world_cup",
    "scores24_cfb",
    "scores24_nfl",
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
EXTERNAL_FEED_SPORT_KEYS = {
    "NBA": "nba",
    "NBA SUMMER": "nba_summer",
    "WNBA": "wnba",
    "MLB": "mlb",
    "FIFA WC": "fifa_world_cup",
    "CFB": "cfb",
    "NFL": "nfl",
}
EXTERNAL_FEED_SOURCE_LABELS = {
    "sportytrader": {
        "NBA": "SportyTraderNBA",
        "NBA SUMMER": "SportyTraderNBASummer",
        "WNBA": "SportyTraderWNBA",
        "MLB": "SportyTraderMLB",
        "FIFA WC": "SportyTraderFIFAWorldCup",
        "CFB": "SportyTraderCFB",
        "NFL": "SportyTraderNFL",
    },
    "sportsgambler": {
        "NBA": "SportsGamblerNBA",
        "NBA SUMMER": "SportsGamblerNBASummer",
        "WNBA": "SportsGamblerWNBA",
        "MLB": "SportsGamblerMLB",
        "FIFA WC": "SportsGamblerFIFAWorldCup",
        "CFB": "SportsGamblerCFB",
        "NFL": "SportsGamblerNFL",
    },
}
# The in-house team models that, when all ok, promote a day to latest.json.
# A complete Scores24 MLB+WNBA slate also promotes (team_ready or scores24_ready),
# so the 9:30 local scrape can first-paint today without waiting on in-house
# models — and in-house models can publish without waiting on Scores24. Tennis-only,
# CFB-only, FIFA/NBA Summer, and other feed-only days still must not promote
# — that is what left 2026-07-25 showing a tennis-only slate.
#
# Scores24 CFB and NFL are scraped on the same weekday morning/afternoon run
# as MLB+WNBA, but they remain soft-fail external feeds. Incomplete, blocked,
# or hung Scores24 CFB/NFL must not prevent publishing a complete MLB+WNBA
# slate; the in-house CFB and NFL models are still part of the required
# team-model set below.
#
# Keep this identical to site_upcheck.REQUIRED_MODEL_KEYS and to the required
# set in model-cache-freshness-guard.yml; a drift test pins all three together.
# It matters because a stale entry here fails silently in the worst direction:
# nba_summer and fifa_world_cup were archived 2026-07-19 when their seasons
# ended and were never published again, which pinned latest_updated to False
# from that day on. Every local publisher could still write {date}.json but
# none could ever update latest.json, so today's scraped feeds only reached the
# site if a model-cache refresh happened to run afterwards.
REQUIRED_TEAM_MODEL_KEYS = {
    "mlb_new",
    "mlb_inning",
    "mlb_first_five",
    "wnba",
    "nba",
    "nba_playoffs",
    "nfl",
    "cfb",
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
    parser = argparse.ArgumentParser(description="Merge generated feed cache JSON into data/model_cache.")
    parser.add_argument("generated", help="Path to the generated latest.json from refresh_external_feeds.py.")
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


def _demote_scraped_feed_picks(payload: dict[str, Any]) -> dict[str, Any]:
    """Publish scraped tipster feeds as untracked research rows, never as bets.

    Every source in EXTERNAL_FEED_MODEL_KEYS republishes a third party's FINISHED
    pick (SportsGambler's tip anchor, SportyTrader's tip box, Scores24's "Our
    choice", Forebet's tip sign, TennisTonic's prediction_set). Those arrive with
    no probability of their own, and the scrapers hardcode decision="BET" with
    units=1, so a stranger's opinion entered the book at full stake and counted
    as a high-conviction pick.

    Audited against the graded ledger, this class runs about -5.5% ROI with a
    t-statistic near -3.5 -- provably negative rather than unlucky -- and it is
    what made the BET tier perform WORSE than the LEAN tier.

    Demoting decision to PASS with units 0 keeps every scraped row visible,
    attributed, and gradeable as a sentiment column while removing it from
    anything that reads as a recommendation: isTrackedPick() posts in-house
    PASS but keeps scraped PASS on the research board, and the parlay
    builder's TEAM_VISIBLE_DECISIONS still admits only BET/LEAN.
    Applied at merge time so it holds for every writer and cannot be reintroduced
    by an individual scraper.
    """
    demoted = dict(payload)

    def demote_bucket(bucket: Any) -> Any:
        if not isinstance(bucket, dict):
            return bucket
        picks = bucket.get("picks")
        if not isinstance(picks, list):
            return bucket
        updated_picks: list[Any] = []
        changed = False
        for pick in picks:
            if not isinstance(pick, dict):
                updated_picks.append(pick)
                continue
            decision = str(pick.get("decision") or "").strip().upper()
            if decision in {"BET", "LEAN"}:
                revised = dict(pick)
                revised["decision"] = "PASS"
                revised["units"] = 0
                revised["scraped_tip_demoted"] = True
                # Preserve what the source actually said so the demotion is
                # auditable and reversible rather than destructive.
                revised.setdefault("source_decision", decision)
                revised.setdefault("source_units", pick.get("units"))
                updated_picks.append(revised)
                changed = True
            else:
                updated_picks.append(pick)
        if not changed:
            return bucket
        revised_bucket = dict(bucket)
        revised_bucket["picks"] = updated_picks
        revised_bucket["scraped_tip_feed"] = True
        return revised_bucket

    for container_key in ("models", "external_feeds"):
        container = demoted.get(container_key)
        if isinstance(container, dict):
            demoted[container_key] = {
                key: (demote_bucket(value) if key in EXTERNAL_FEED_MODEL_KEYS else value)
                for key, value in container.items()
            }
    for key in list(demoted):
        if key in EXTERNAL_FEED_MODEL_KEYS:
            demoted[key] = demote_bucket(demoted[key])
    return demoted


def _seed_external_feeds_from_latest(latest_payload: dict[str, Any]) -> dict[str, Any]:
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


def _feed_keys(generated: dict[str, Any]) -> set[str]:
    keys = set(EXTERNAL_FEED_MODEL_KEYS)
    external_feeds = generated.get("external_feeds")
    if isinstance(external_feeds, dict):
        keys.update(str(key) for key in external_feeds)
    return keys


def _legacy_feed_keys_replaced_by(generated: dict[str, Any]) -> set[str]:
    generated_keys: set[str] = set()
    models = generated.get("models")
    if isinstance(models, dict):
        generated_keys.update(str(key) for key in models)
    external_feeds = generated.get("external_feeds")
    if isinstance(external_feeds, dict):
        generated_keys.update(str(key) for key in external_feeds)
    generated_keys.update(str(key) for key in generated if key in EXTERNAL_FEED_MODEL_KEYS)
    return {
        legacy_key
        for legacy_key in SPLIT_EXTERNAL_FEED_LEGACY_KEYS
        if any(key.startswith(f"{legacy_key}_") for key in generated_keys)
    }


def _canonical_sport_label(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "nba": "NBA",
        "basketball": "NBA",
        "nba_summer": "NBA SUMMER",
        "nba_summer_league": "NBA SUMMER",
        "summer_league": "NBA SUMMER",
        "wnba": "WNBA",
        "mlb": "MLB",
        "baseball": "MLB",
        "fifa": "FIFA WC",
        "fifa_wc": "FIFA WC",
        "fifa_world_cup": "FIFA WC",
        "world_cup": "FIFA WC",
        "soccer": "FIFA WC",
        "football": "FIFA WC",
        "cfb": "CFB",
        "ncaaf": "CFB",
        "college_football": "CFB",
        "ncaa": "CFB",
        "ncaa_football": "CFB",
        "nfl": "NFL",
    }
    if normalized in aliases:
        return aliases[normalized]
    upper = raw.upper()
    if upper == "FIFA WORLD CUP":
        return "FIFA WC"
    return upper if upper in EXTERNAL_FEED_SPORT_KEYS else ""


def _split_feed_key(provider_key: str, sport: Any) -> str:
    sport_label = _canonical_sport_label(sport)
    sport_key = EXTERNAL_FEED_SPORT_KEYS.get(sport_label)
    return f"{provider_key}_{sport_key}" if sport_key else provider_key


def _split_source_label(provider_key: str, sport: Any) -> str:
    sport_label = _canonical_sport_label(sport)
    return EXTERNAL_FEED_SOURCE_LABELS.get(provider_key, {}).get(sport_label, provider_key)


def _split_legacy_bucket(provider_key: str, bucket: Any) -> dict[str, Any]:
    if not isinstance(bucket, dict):
        return {}
    split: dict[str, Any] = {}
    for raw_pick in bucket.get("picks") or []:
        if not isinstance(raw_pick, dict):
            continue
        split_key = _split_feed_key(provider_key, raw_pick.get("sport"))
        if split_key == provider_key:
            continue
        split_bucket = split.setdefault(
            split_key,
            {
                **bucket,
                "picks": [],
                "meta": {
                    **(bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}),
                    "feed": split_key,
                    "provider": provider_key,
                },
            },
        )
        pick = dict(raw_pick)
        pick["source"] = _split_source_label(provider_key, pick.get("sport"))
        split_bucket["picks"].append(pick)
    return split


def _split_legacy_buckets(provider_key: str, buckets: dict[str, Any]) -> dict[str, Any]:
    split: dict[str, Any] = {}
    for split_key, split_bucket in _split_legacy_bucket(provider_key, buckets.get(provider_key)).items():
        split[split_key] = _preserve_pick_metadata(split.get(split_key), split_bucket)
    return split


def _pick_key(pick: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(pick.get(key) or "").strip().lower()
        for key in ("source", "sport", "date", "pick", "matchup", "game")
    )


def _bucket_date(bucket: Any) -> str:
    if not isinstance(bucket, dict):
        return ""
    meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
    return str(bucket.get("date") or meta.get("date") or "").strip()


def _prefer_feed_bucket(current_bucket: Any, generated_bucket: Any) -> Any:
    """Keep a newer checked-out feed when the generated snapshot is a day behind.

    External-feed jobs copy the whole latest.json, including Scores24 buckets
    they did not refresh. A later merge must not replace today's local
    Scores24 publish with that stale starting snapshot.
    """
    current_date = _bucket_date(current_bucket)
    generated_date = _bucket_date(generated_bucket)
    if current_date and generated_date and generated_date < current_date:
        return current_bucket
    return _preserve_pick_metadata(current_bucket, generated_bucket)


def _preserve_pick_metadata(current_bucket: Any, generated_bucket: Any) -> Any:
    if not isinstance(current_bucket, dict) or not isinstance(generated_bucket, dict):
        return generated_bucket
    current_picks = current_bucket.get("picks")
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
    merged = dict(generated_bucket)
    merged["picks"] = [
        {**pick, **metadata.get(_pick_key(pick), {})} if isinstance(pick, dict) else pick
        for pick in generated_picks
    ]
    return merged


def _merge_feed_buckets(
    current_buckets: dict[str, Any],
    generated_buckets: dict[str, Any],
    feed_keys: set[str],
) -> dict[str, Any]:
    merged = dict(current_buckets)
    for key in feed_keys:
        if key in generated_buckets:
            merged[key] = _prefer_feed_bucket(current_buckets.get(key), generated_buckets[key])
    return merged


def merge_payload(generated: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    date_iso = str(generated.get("date") or "").strip()
    if not date_iso:
        raise SystemExit("Generated external feed cache is missing date")

    current = _without_retired_buckets(_current_payload(cache_dir, date_iso))
    generated = _without_retired_buckets(generated)
    merged = dict(current)
    for key in ("date", "updatedAt", "externalFeedsUpdatedAt", "external_feed_errors"):
        if key in generated:
            merged[key] = generated[key]

    feed_keys = _feed_keys(generated)
    replaced_legacy_keys = _legacy_feed_keys_replaced_by(generated)
    for key in replaced_legacy_keys:
        merged.pop(key, None)

    current_models = current.get("models") if isinstance(current.get("models"), dict) else {}
    generated_models = generated.get("models") if isinstance(generated.get("models"), dict) else {}
    models = dict(current_models)
    for key in replaced_legacy_keys:
        for split_key, split_bucket in _split_legacy_buckets(key, current_models).items():
            models[split_key] = _preserve_pick_metadata(models.get(split_key), split_bucket)
        models.pop(key, None)
    for key in feed_keys:
        if key in replaced_legacy_keys:
            continue
        if key in generated_models:
            models[key] = _prefer_feed_bucket(models.get(key), generated_models[key])
    merged["models"] = models

    current_external = current.get("external_feeds") if isinstance(current.get("external_feeds"), dict) else {}
    generated_external = generated.get("external_feeds") if isinstance(generated.get("external_feeds"), dict) else {}
    current_external = {
        key: value
        for key, value in current_external.items()
        if key not in replaced_legacy_keys
    }
    for key in replaced_legacy_keys:
        source_buckets = current.get("external_feeds") if isinstance(current.get("external_feeds"), dict) else {}
        for split_key, split_bucket in _split_legacy_buckets(key, source_buckets).items():
            current_external[split_key] = _preserve_pick_metadata(current_external.get(split_key), split_bucket)
    generated_external = {
        key: value
        for key, value in generated_external.items()
        if key not in replaced_legacy_keys
    }
    if current_external or generated_external:
        merged["external_feeds"] = _merge_feed_buckets(current_external, generated_external, feed_keys)

    for key in feed_keys:
        if key in replaced_legacy_keys:
            continue
        if key in generated:
            merged[key] = _prefer_feed_bucket(current.get(key), generated[key])
    for key in replaced_legacy_keys:
        for split_key, split_bucket in _split_legacy_buckets(key, current).items():
            if split_key in merged:
                merged[split_key] = _preserve_pick_metadata(split_bucket, merged[split_key])
            else:
                merged[split_key] = split_bucket

    return _demote_scraped_feed_picks(_without_retired_buckets(merged))


def _scores24_feed_bucket(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    feeds = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    bucket = feeds.get(key) or models.get(key) or payload.get(key)
    return bucket if isinstance(bucket, dict) else None


def _scores24_mlb_wnba_complete(payload: dict[str, Any], date_iso: str) -> bool:
    """True when today's official Scores24 MLB and WNBA slates are complete.

    Used as one side of latestUpdated (team_ready or scores24_ready). Complete
    Scores24 can first-paint without in-house models; in-house models can
    publish without Scores24. Tennis, CFB, NFL, FIFA, and NBA Summer must still
    not promote latest.json on their own. scores24_cfb and scores24_nfl are
    scraped best-effort on the same local run; their absence or failure must
    not block this helper.
    """
    for key in ("scores24_mlb", "scores24_wnba"):
        bucket = _scores24_feed_bucket(payload, key)
        if not isinstance(bucket, dict) or bucket.get("ok") is not True:
            return False
        if str(bucket.get("date") or "") != date_iso:
            return False
        meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
        missing = meta.get("missingMatchups") if isinstance(meta.get("missingMatchups"), list) else []
        expected = meta.get("expectedMatchups")
        matched = meta.get("matchedPicks")
        if missing or expected != matched or matched != len(bucket.get("picks") or []):
            return False
    return True


def write_merged_payload(merged: dict[str, Any], cache_dir: Path) -> bool:
    date_iso = str(merged["date"])
    models = merged.get("models") if isinstance(merged.get("models"), dict) else {}
    team_ready = all(
        isinstance(models.get(key), dict) and models[key].get("ok") is True
        for key in REQUIRED_TEAM_MODEL_KEYS
    )
    scores24_ready = _scores24_mlb_wnba_complete(merged, date_iso)
    latest_updated = team_ready or scores24_ready

    _write_json(cache_dir / f"{date_iso}.json", merged)
    if latest_updated:
        _write_json(cache_dir / "latest.json", merged)
    write_cache_manifest(cache_dir)
    return latest_updated


def main() -> int:
    args = _parse_args()
    generated_path = Path(args.generated)
    cache_dir = Path(args.cache_dir)
    generated = _read_json(generated_path)
    if not generated:
        raise SystemExit(f"Could not read generated external feed cache: {generated_path}")

    merged = merge_payload(generated, cache_dir)
    date_iso = str(merged["date"])
    latest_updated = write_merged_payload(merged, cache_dir)
    print(json.dumps({
        "date": date_iso,
        "models": sorted((merged.get("models") or {}).keys()),
        "generated": str(generated_path),
        "latestUpdated": latest_updated,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
