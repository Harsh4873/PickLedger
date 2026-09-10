#!/usr/bin/env python3
"""Validate the committed model cache and built static frontend without a browser."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_CACHE_DIR = REPO_ROOT / "data" / "model_cache"
PLAYER_PROPS_CACHE_DIR = REPO_ROOT / "data" / "player_props_cache"
PLAYER_PROPS_SNAPSHOT_DIR = REPO_ROOT / "data" / "player_props_snapshots"
PARLAY_CARDS_DIR = REPO_ROOT / "data" / "parlay_cards"
PROFIT_DESK_DIR = REPO_ROOT / "data" / "profit_desk"
PARLAY_ENGINE_VERSION = "parlay_cards_v6_proven_legs"
PROFIT_DESK_ENGINE_VERSION = "profit_desk_v2_live"
PROFIT_DESK_FIRST_LIVE_DATE = "2026-07-11"
REQUIRED_MODEL_KEYS = {
    "mlb_new",
    "mlb_inning",
    "mlb_first_five",
    "wnba",
    "nba",
    "nba_playoffs",
    "nfl",
    "cfb",
}
REQUIRED_PLAYER_PROP_KEYS = {
    "nba_player_props",
    "mlb_player_props",
    "wnba_player_props",
}
ML_PLAYER_PROP_KEYS = {"mlb_player_props", "wnba_player_props"}
REQUIRED_ML_PLAYER_PROP_FIELDS = (
    "ml_probability",
    "ml_edge",
    "ml_expected_value",
    "ml_model_version",
    "ml_market_family",
    "ml_rank",
    "baseline_projection",
)
REQUIRED_SCORES24_FEED_KEYS = {
    "scores24_mlb",
    "scores24_wnba",
}
# Watched Scores24 MLB+WNBA buckets: warn when missing/stale/incomplete, and a
# complete today's slate can still first-paint latest.json / allow deploy when
# in-house models are not ready yet. They are not a hard Pages / --data-only
# gate. scores24_cfb and scores24_nfl are scraped on the same local Scores24
# run but are never freshness/upcheck requirements (soft-fail like tennis).
TEAM_VISIBLE_DECISIONS = {"BET", "LEAN"}
PLAYER_VISIBLE_DECISIONS = {"BET", "LEAN", "PASS"}
LEGACY_PUBLIC_PLAYER_PROP_SUFFIXES = (
    "_season",
    "_all_time",
    "_hot_l10",
    "_matchup_h2h",
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Check whether today's committed model and player-props data is ready to deploy.",
    )
    return parser.parse_args()


def _player_prop_market_key(pick: dict[str, Any]) -> tuple[str, ...]:
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


def _consensus_qualified_player_prop(pick: dict[str, Any]) -> bool:
    mode = str(pick.get("ml_probability_mode") or "").strip()
    return (
        pick.get("consensus_qualified") is True
        or pick.get("precision_qualified") is True
        or mode == "four_model_consensus_gate"
    )


def _published_player_prop_keys(payload: dict[str, Any], date_iso: str) -> set[tuple[str, ...]]:
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    keys: set[tuple[str, ...]] = set()
    for bucket in models.values():
        if not isinstance(bucket, dict):
            continue
        for pick in bucket.get("picks") or []:
            if not isinstance(pick, dict):
                continue
            if str(pick.get("date") or "").strip() != date_iso:
                continue
            if str(pick.get("scope") or "").strip().lower() != "player":
                continue
            if (
                pick.get("market_priced") is True
                and str(pick.get("probability_source") or "").strip() == "player_props_ml_v1"
                and _consensus_qualified_player_prop(pick)
            ):
                keys.add(_player_prop_market_key(pick))
    return keys


def _snapshot_player_prop_keys(date_iso: str) -> set[tuple[str, ...]]:
    snapshot_keys: set[tuple[str, ...]] = set()
    for path in sorted((PLAYER_PROPS_SNAPSHOT_DIR / date_iso).glob("*.json")):
        payload = _read_json(path)
        if payload and str(payload.get("date") or "").strip() == date_iso:
            snapshot_keys |= _published_player_prop_keys(payload, date_iso)
    return snapshot_keys


def _decision(pick: dict[str, Any]) -> str:
    return str(pick.get("decision") or "").strip().upper()


def _pick_text(pick: dict[str, Any]) -> str:
    return str(pick.get("pick") or pick.get("selection") or pick.get("prop") or pick.get("bet") or "").strip()


def _team_pick_key(pick: dict[str, Any], fallback_source: str) -> tuple[str, ...]:
    return tuple(
        str(value or "").strip().lower()
        for value in (
            pick.get("source") or fallback_source,
            pick.get("sport"),
            pick.get("date") or pick.get("game_date") or pick.get("slate_date") or pick.get("Date"),
            _pick_text(pick),
            pick.get("matchup"),
            pick.get("game"),
        )
    )


def _bucket_picks(bucket: Any) -> list[dict[str, Any]]:
    if not isinstance(bucket, dict):
        return []
    return [pick for pick in bucket.get("picks") or [] if isinstance(pick, dict)]


def _visible_team_picks(bucket: Any) -> list[dict[str, Any]]:
    return [pick for pick in _bucket_picks(bucket) if _pick_text(pick) and _decision(pick) in TEAM_VISIBLE_DECISIONS]


def _visible_player_picks(bucket: Any) -> list[dict[str, Any]]:
    return [
        pick
        for pick in _bucket_picks(bucket)
        if _pick_text(pick)
        and _decision(pick) in PLAYER_VISIBLE_DECISIONS
        and str(pick.get("scope") or "").strip().lower() == "player"
    ]


def _positive_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _mlb_player_props_documented_abstention(bucket: dict[str, Any]) -> bool:
    """True when MLB props refreshed ok and documented a gate/special-event abstention.

    Special-event / one-sided boards (e.g. All-Star) can leave scheduled MLB games with
    zero published props after the scorer evaluates real candidates. That is a degraded
    props state, but it must not block deploying an otherwise healthy team slate.
    """
    if bucket.get("ok") is not True or bucket.get("abstained") is not True:
        return False
    if _bucket_picks(bucket):
        return False
    evaluated = max(
        _positive_int(bucket.get("candidate_count")),
        _positive_int(bucket.get("scored_count")),
        _positive_int(bucket.get("consensus_rejected_count")),
    )
    reasons = bucket.get("consensus_rejection_reasons")
    has_reasons = isinstance(reasons, dict) and any(_positive_int(count) > 0 for count in reasons.values())
    return evaluated > 0 or has_reasons


CENTRAL_TZ = ZoneInfo("America/Chicago")


def _central_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(CENTRAL_TZ).date()


def _row_matches_target_date(row: dict[str, Any], target_date: str | None) -> bool:
    if not target_date:
        return True
    for key in ("start_time", "game_start_time", "gameDate", "game_date", "date"):
        central = _central_date(row.get(key))
        if central is not None:
            return central.isoformat() == target_date
    return True



def _scores24_feed_bucket(payload: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    feeds = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    bucket = feeds.get(key) or models.get(key) or payload.get(key)
    return bucket if isinstance(bucket, dict) else None


def _scores24_slate_complete(bucket: dict[str, Any], today: str) -> bool:
    if bucket.get("ok") is not True:
        return False
    if str(bucket.get("date") or "") != today:
        return False
    meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
    missing = meta.get("missingMatchups") if isinstance(meta.get("missingMatchups"), list) else []
    expected = meta.get("expectedMatchups")
    matched = meta.get("matchedPicks")
    if missing or expected != matched or matched != len(bucket.get("picks") or []):
        return False
    return True


def _today_scores24_complete(payload: dict[str, Any] | None, today: str) -> bool:
    return all(
        (bucket := _scores24_feed_bucket(payload, key)) is not None
        and _scores24_slate_complete(bucket, today)
        for key in REQUIRED_SCORES24_FEED_KEYS
    )


def _inhouse_unreadiness_when_scores24_ready(
    message: str,
    today: str,
    player_date: str,
    parlay_date: str,
    profit_date: str,
) -> bool:
    """True when the failure is only 'in-house data is not today's yet'.

    A complete Scores24 MLB+WNBA slate can still first-paint the site when
    in-house team models have not landed. Broken *today's* player/parlay/profit
    artifacts stay hard failures. Missing/stale Scores24 must not block deploy
    when the required in-house models are already ready.
    """
    if message.startswith("model bucket "):
        return True
    if "player-props" in message or message.startswith("data/player_props_cache/"):
        return player_date != today
    if "parlay" in message.lower() or message.startswith("data/parlay_cards/"):
        return parlay_date != today
    if "Profit Desk" in message or "profit_desk" in message:
        return profit_date != today
    return False


def _scheduled_game_count(bucket: dict[str, Any], *, target_date: str | None = None) -> int:
    games = bucket.get("games")
    if isinstance(games, list):
        return sum(1 for row in games if isinstance(row, dict) and _row_matches_target_date(row, target_date))
    try:
        return max(0, int(games or 0))
    except (TypeError, ValueError):
        return 0


def _official_mlb_scheduled_game_count(models: dict[str, Any], *, target_date: str | None = None) -> int:
    """Use independent team-model slates so a broken props parser cannot claim no games."""
    return max(
        (
            _scheduled_game_count(bucket, target_date=target_date)
            for key in ("mlb_new", "mlb_inning", "mlb_first_five")
            if isinstance((bucket := models.get(key)), dict)
        ),
        default=0,
    )


def _missing_ml_player_prop_fields(pick: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if str(pick.get("scope") or "").strip().lower() != "player":
        missing.append("scope")
    if pick.get("market_priced") is not True:
        missing.append("market_priced")
    if str(pick.get("odds_source") or "").strip() != "posted_market":
        missing.append("odds_source")
    if pick.get("odds") in (None, ""):
        missing.append("odds")
    if str(pick.get("probability_source") or "").strip() != "player_props_ml_v1":
        missing.append("probability_source")
    for field in REQUIRED_ML_PLAYER_PROP_FIELDS:
        if field not in pick or pick.get(field) is None or (
            isinstance(pick.get(field), str) and not str(pick.get(field)).strip()
        ):
            missing.append(field)
    return missing


def _cache_contract_messages(cache_dir: Path, *, player_props: bool, today: str) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    warnings: list[str] = []
    manifest = _read_json(cache_dir / "index.json") or {}
    files = [
        file
        for file in manifest.get("files") or []
        if isinstance(file, str) and re.fullmatch(r"20\d\d-\d\d-\d\d\.json", file)
    ]
    for file in files:
        payload = _read_json(cache_dir / file)
        if not payload:
            warnings.append(f"{cache_dir.name}/{file} is listed in manifest but is missing or invalid")
            continue
        date_iso = str(payload.get("date") or payload.get("slate_date") or file[:10]).strip()
        models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
        id_counts: dict[tuple[str, str], int] = {}
        duplicate_keys = 0
        missing_dates = 0
        for model_key, bucket in models.items():
            picks = _bucket_picks(bucket)
            market_counts: dict[tuple[str, ...], int] = {}
            for pick in picks:
                pick_id = str(pick.get("id") or "").strip()
                if pick_id:
                    id_key = (date_iso, pick_id)
                    id_counts[id_key] = id_counts.get(id_key, 0) + 1
                if not str(pick.get("date") or pick.get("game_date") or pick.get("slate_date") or pick.get("Date") or "").strip():
                    missing_dates += 1
                key = _player_prop_market_key(pick) if player_props else _team_pick_key(pick, str(model_key))
                if any(key):
                    market_counts[key] = market_counts.get(key, 0) + 1
            duplicate_keys += sum(1 for count in market_counts.values() if count > 1)
        duplicate_ids = sum(1 for count in id_counts.values() if count > 1)
        if duplicate_ids:
            message = f"{cache_dir.name}/{file} has {duplicate_ids} duplicate date/id pair(s)"
            if date_iso == today:
                failures.append(message)
            else:
                warnings.append(message)
        if duplicate_keys:
            warnings.append(f"{cache_dir.name}/{file} has {duplicate_keys} duplicate market key(s)")
        if missing_dates:
            warnings.append(
                f"{cache_dir.name}/{file} has {missing_dates} pick row(s) without embedded dates; "
                "the viewer falls back to the payload date"
            )
    return failures, warnings


def main() -> int:
    args = _parse_args()
    failures: list[str] = []
    warnings: list[str] = []
    today = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")

    latest = _read_json(MODEL_CACHE_DIR / "latest.json")
    dated = _read_json(MODEL_CACHE_DIR / f"{today}.json")
    manifest = _read_json(MODEL_CACHE_DIR / "index.json")
    if not latest:
        failures.append("data/model_cache/latest.json is missing or invalid")
    elif str(latest.get("date") or "") < today:
        # Only STALE data blocks a deploy. A refresh dispatched after UTC
        # midnight legitimately produces tomorrow's (Central) slate early;
        # deferring on that wedges every deploy until Central midnight.
        failures.append(f"latest model cache is {latest.get('date') or 'undated'}, expected {today}")
    if not dated:
        failures.append(f"data/model_cache/{today}.json is missing or invalid")
    if manifest and f"{today}.json" not in (manifest.get("files") or []):
        failures.append(f"model-cache manifest does not include {today}.json")

    models = latest.get("models") if isinstance(latest, dict) else {}
    models = models if isinstance(models, dict) else {}
    for key in sorted(REQUIRED_MODEL_KEYS):
        bucket = models.get(key)
        if not isinstance(bucket, dict):
            failures.append(f"model bucket {key} is missing")
        elif bucket.get("ok") is not True:
            failures.append(f"model bucket {key} failed: {bucket.get('error') or 'unknown error'}")

    # Scores24 MLB/WNBA still first-paint latest.json when complete, but they are
    # not a Pages requirement. CI cannot scrape Scores24, so missing, errored,
    # incomplete, or yesterday-dated buckets are warnings in both --data-only
    # readiness and the full upcheck. In-house team models, player props, parlays,
    # and Profit Desk still hard-fail when unreadiness is not covered by a complete
    # today's Scores24 slate.
    for key in sorted(REQUIRED_SCORES24_FEED_KEYS):
        bucket = _scores24_feed_bucket(latest, key)
        if not isinstance(bucket, dict):
            warnings.append(f"external-feed bucket {key} is missing")
            continue
        if bucket.get("ok") is not True:
            warnings.append(f"external-feed bucket {key} failed: {bucket.get('error') or 'unknown error'}")
            continue
        if str(bucket.get("date") or "") != today:
            warnings.append(f"external-feed bucket {key} is {bucket.get('date') or 'undated'}, expected {today}")
        meta = bucket.get("meta") if isinstance(bucket.get("meta"), dict) else {}
        missing = meta.get("missingMatchups") if isinstance(meta.get("missingMatchups"), list) else []
        expected = meta.get("expectedMatchups")
        matched = meta.get("matchedPicks")
        if missing or expected != matched or matched != len(bucket.get("picks") or []):
            warnings.append(
                f"external-feed bucket {key} has incomplete official-slate coverage: "
                f"matched={matched!r}, expected={expected!r}, missing={missing!r}"
            )

    player_latest = _read_json(PLAYER_PROPS_CACHE_DIR / "latest.json")
    player_dated = _read_json(PLAYER_PROPS_CACHE_DIR / f"{today}.json")
    player_manifest = _read_json(PLAYER_PROPS_CACHE_DIR / "index.json")
    if not player_latest:
        failures.append("data/player_props_cache/latest.json is missing or invalid")
    elif str(player_latest.get("date") or "") < today:
        failures.append(f"latest player-props cache is {player_latest.get('date') or 'undated'}, expected {today}")
    if not player_dated:
        failures.append(f"data/player_props_cache/{today}.json is missing or invalid")
    if player_manifest and f"{today}.json" not in (player_manifest.get("files") or []):
        failures.append(f"player-props manifest does not include {today}.json")

    player_models = player_latest.get("models") if isinstance(player_latest, dict) else {}
    player_models = player_models if isinstance(player_models, dict) else {}
    if player_latest:
        unexpected_models = sorted(key for key in player_models if key not in REQUIRED_PLAYER_PROP_KEYS)
        if unexpected_models:
            failures.append(
                "latest player-props cache has unexpected public bucket(s): "
                + ", ".join(unexpected_models)
            )
        legacy_public_models = sorted(
            key for key in player_models if any(key.endswith(suffix) for suffix in LEGACY_PUBLIC_PLAYER_PROP_SUFFIXES)
        )
        if legacy_public_models:
            failures.append(
                "latest player-props cache reintroduced legacy public bucket(s): "
                + ", ".join(legacy_public_models)
            )
    official_mlb_scheduled_games = _official_mlb_scheduled_game_count(models, target_date=today)
    for key in sorted(REQUIRED_PLAYER_PROP_KEYS):
        bucket = player_models.get(key)
        if not isinstance(bucket, dict):
            failures.append(f"player-props bucket {key} is missing")
            continue

        picks = _bucket_picks(bucket)
        scheduled_games = _scheduled_game_count(bucket, target_date=today)
        if key == "mlb_player_props":
            scheduled_games = max(scheduled_games, official_mlb_scheduled_games)
        if bucket.get("ok") is not True:
            failures.append(f"player-props bucket {key} failed: {bucket.get('error') or 'unknown error'}")
        if scheduled_games > 0 and not picks:
            if key == "mlb_player_props" and _mlb_player_props_documented_abstention(bucket):
                warnings.append(
                    f"player-props bucket {key} abstained with scheduled games and zero picks "
                    "(documented gate/special-event abstention; team deploy still allowed)"
                )
            elif key == "mlb_player_props" or bucket.get("abstained") is not True:
                failures.append(f"player-props bucket {key} has scheduled games but zero picks")

        if picks:
            if key in REQUIRED_PLAYER_PROP_KEYS:
                ranks = [
                    int(pick.get("ml_rank") or 0)
                    for pick in picks
                    if isinstance(pick, dict) and str(pick.get("ml_rank") or "").strip()
                ]
                if ranks and ranks != list(range(1, len(ranks) + 1)):
                    failures.append(f"player-props bucket {key} has non-contiguous ML ranks: {ranks}")
                if any(
                    isinstance(pick, dict)
                    and (pick.get("carried_forward") or pick.get("preserved_from_prior_refresh"))
                    for pick in picks
                ):
                    failures.append(f"player-props bucket {key} includes prior-refresh props in latest board")
            if key in ML_PLAYER_PROP_KEYS:
                for position, pick in enumerate(picks, start=1):
                    missing_fields = _missing_ml_player_prop_fields(pick)
                    if missing_fields:
                        failures.append(
                            f"player-props bucket {key} published pick {position} is missing "
                            f"player_props_ml_v1 fields: {', '.join(missing_fields)}"
                        )
            market_picks = [pick for pick in picks if isinstance(pick, dict) and pick.get("market_priced") is True]
            if key not in ML_PLAYER_PROP_KEYS and market_picks and any(
                str(pick.get("probability_source") or "") != "player_props_ml_v1"
                for pick in market_picks
            ):
                failures.append(f"player-props bucket {key} has market-priced picks without player_props_ml_v1 probability")
            public_picks = [
                pick for pick in picks
                if str(pick.get("decision") or "").strip().upper() in {"BET", "LEAN"}
            ]
            if any(not _consensus_qualified_player_prop(pick) for pick in public_picks):
                failures.append(f"player-props bucket {key} has visible picks that did not pass strict consensus")

    contract_failures, contract_warnings = _cache_contract_messages(MODEL_CACHE_DIR, player_props=False, today=today)
    failures.extend(contract_failures)
    warnings.extend(contract_warnings)
    contract_failures, contract_warnings = _cache_contract_messages(PLAYER_PROPS_CACHE_DIR, player_props=True, today=today)
    failures.extend(contract_failures)
    warnings.extend(contract_warnings)

    parlay_latest = _read_json(PARLAY_CARDS_DIR / "latest.json")
    parlay_dated = _read_json(PARLAY_CARDS_DIR / f"{today}.json")
    parlay_manifest = _read_json(PARLAY_CARDS_DIR / "index.json")
    if not parlay_latest:
        failures.append("data/parlay_cards/latest.json is missing or invalid")
    elif str(parlay_latest.get("date") or "") < today:
        failures.append(f"latest parlay cards are {parlay_latest.get('date') or 'undated'}, expected {today}")
    if not parlay_dated:
        failures.append(f"data/parlay_cards/{today}.json is missing or invalid")
    if parlay_manifest and f"{today}.json" not in (parlay_manifest.get("files") or []):
        failures.append(f"parlay-card manifest does not include {today}.json")
    if parlay_latest:
        parlay_cards = [card for card in parlay_latest.get("cards") or [] if isinstance(card, dict)]
        if str(parlay_latest.get("engineVersion") or "") != PARLAY_ENGINE_VERSION:
            failures.append(
                f"latest parlay cards use {parlay_latest.get('engineVersion') or 'unknown'} engine, expected {PARLAY_ENGINE_VERSION}"
            )
        mode_cards: dict[str, list[dict[str, Any]]] = {"team": [], "player": []}
        for card in parlay_cards:
            mode = str(card.get("pickMode") or "").strip().lower()
            if mode in mode_cards:
                mode_cards[mode].append(card)
        oversized_modes = {mode: len(cards) for mode, cards in mode_cards.items() if len(cards) > 6}
        if oversized_modes:
            failures.append(f"latest parlay board has mode count(s) above 6: {oversized_modes}")
        if any(int(card.get("legCount") or 0) < 2 for card in parlay_cards):
            failures.append("latest parlay board includes a 1-leg card")
        nonpositive_ev = []
        for card in parlay_cards:
            try:
                ev = float(card.get("parlayEv"))
            except (TypeError, ValueError):
                ev = None
            if ev is None or ev <= 0:
                nonpositive_ev.append(str(card.get("id") or card.get("category") or "card"))
        if nonpositive_ev:
            failures.append(
                "latest parlay board publishes a card with parlayEv <= 0: "
                + ", ".join(nonpositive_ev[:4])
            )
        category_counts: dict[tuple[str, str], int] = {}
        for mode, cards in mode_cards.items():
            for card in cards:
                category = str(card.get("category") or "").strip()
                category_counts[(mode, category)] = category_counts.get((mode, category), 0) + 1
        oversized = {f"{mode}:{category}": count for (mode, category), count in category_counts.items() if count > 2}
        if oversized:
            failures.append(f"latest parlay board has mode/category count(s) above 2: {oversized}")
        team_visible_leg_count = sum(
            1
            for bucket in models.values()
            if isinstance(bucket, dict)
            for pick in bucket.get("picks") or []
            if isinstance(pick, dict)
            and str(pick.get("decision") or "").strip().upper() in TEAM_VISIBLE_DECISIONS
            and str(pick.get("pick") or "").strip()
            and pick.get("grade_supported") is not False
        )
        summary = parlay_latest.get("summary") if isinstance(parlay_latest.get("summary"), dict) else {}
        generated_three_leg_candidates = int(summary.get("generatedThreeLegCandidates") or 0)
        if team_visible_leg_count >= 3 and not mode_cards["team"] and generated_three_leg_candidates > 0:
            failures.append("latest parlay board has eligible team parlay candidates but zero team-mode cards")
        if int(summary.get("displayedCards") or 0) != len(parlay_cards):
            failures.append("latest parlay summary displayedCards does not match cards length")
        mode_summary = summary.get("modes") if isinstance(summary.get("modes"), dict) else {}
        for mode, cards in mode_cards.items():
            values = mode_summary.get(mode) if isinstance(mode_summary.get(mode), dict) else {}
            if values and int(values.get("displayedCards") or 0) != len(cards):
                failures.append(f"latest parlay summary {mode} displayedCards does not match cards length")

    profit_latest = _read_json(PROFIT_DESK_DIR / "latest.json")
    profit_dated = _read_json(PROFIT_DESK_DIR / f"{today}.json")
    profit_manifest = _read_json(PROFIT_DESK_DIR / "index.json")
    if not profit_latest:
        failures.append("data/profit_desk/latest.json is missing or invalid")
    elif str(profit_latest.get("date") or "") < today:
        failures.append(f"latest Profit Desk is {profit_latest.get('date') or 'undated'}, expected {today}")
    if not profit_dated:
        failures.append(f"data/profit_desk/{today}.json is missing or invalid")
    if not profit_manifest:
        failures.append("data/profit_desk/index.json is missing or invalid")
    else:
        if f"{today}.json" not in (profit_manifest.get("files") or []):
            failures.append(f"Profit Desk manifest does not include {today}.json")
        if str(profit_manifest.get("engineVersion") or "") != PROFIT_DESK_ENGINE_VERSION:
            failures.append(
                f"Profit Desk manifest uses {profit_manifest.get('engineVersion') or 'unknown'} engine, "
                f"expected {PROFIT_DESK_ENGINE_VERSION}"
            )
    if profit_latest:
        if str(profit_latest.get("engineVersion") or "") != PROFIT_DESK_ENGINE_VERSION:
            failures.append(
                f"latest Profit Desk uses {profit_latest.get('engineVersion') or 'unknown'} engine, "
                f"expected {PROFIT_DESK_ENGINE_VERSION}"
            )
        candidates = [row for row in profit_latest.get("candidates") or [] if isinstance(row, dict)]
        summary = profit_latest.get("summary") if isinstance(profit_latest.get("summary"), dict) else {}
        candidate_count = int(summary.get("candidatesEvaluated") or summary.get("candidateCount") or 0)
        if candidate_count != len(candidates):
            failures.append("latest Profit Desk candidate summary does not match candidates length")
        phase = str(profit_latest.get("phase") or (profit_latest.get("policy") or {}).get("mode") or "").lower()
        expected_phase = "live" if today >= PROFIT_DESK_FIRST_LIVE_DATE else "research_backfill"
        if phase != expected_phase:
            failures.append(f"latest Profit Desk phase is {phase or 'missing'}, expected {expected_phase}")
        live_candidates = [row for row in candidates if row.get("liveQualified") is True]
        if int(summary.get("liveQualified") or 0) != len(live_candidates):
            failures.append("latest Profit Desk liveQualified summary does not match candidates")
        for row in candidates:
            stake = float(row.get("stakeUnits") or 0)
            if stake != 0 and row.get("liveQualified") is not True:
                failures.append("Profit Desk candidate has a stake without live qualification")
                break
            if row.get("liveQualified") is True and (
                stake <= 0 or str(row.get("tier") or "") not in {"edge", "value"}
            ):
                failures.append("Profit Desk live candidate is missing a lane stake")
                break
        if phase != "live" and live_candidates:
            failures.append("non-live Profit Desk artifact reports live-qualified picks")
        if any(str(row.get("tier") or "") not in {"edge", "value", "watch", "avoid"} for row in candidates):
            failures.append("latest Profit Desk includes an invalid candidate tier")
        if any(not isinstance(row.get("blockers"), list) for row in candidates):
            failures.append("latest Profit Desk candidate is missing explicit blockers")


    if latest and _today_scores24_complete(latest, today):
        player_date = str((player_latest or {}).get("date") or "")
        parlay_date = str((parlay_latest or {}).get("date") or "")
        profit_date = str((profit_latest or {}).get("date") or "")
        kept: list[str] = []
        for message in failures:
            if _inhouse_unreadiness_when_scores24_ready(
                message, today, player_date, parlay_date, profit_date
            ):
                warnings.append(
                    "in-house data not ready; today's Scores24 slate is complete "
                    f"so deploy can proceed: {message}"
                )
            else:
                kept.append(message)
        failures = kept

    if args.data_only:
        for message in warnings:
            print(f"[readiness] warning: {message}")
        for message in failures:
            print(f"[readiness] waiting: {message}")
        if failures:
            return 1
        print(f"[readiness] daily data is ready for {today}")
        return 0

    source_html = (REPO_ROOT / "index.html").read_text(encoding="utf-8")
    if 'href="./src/styles/pickledger.css"' not in source_html:
        failures.append("source HTML is missing the main stylesheet")
    if 'type="module" src="./src/main.ts"' not in source_html:
        failures.append("source HTML is missing the Vite module entrypoint")

    dist_html_path = REPO_ROOT / "dist" / "index.html"
    if not dist_html_path.exists():
        failures.append("dist/index.html is missing; run the production build")
    else:
        dist_html = dist_html_path.read_text(encoding="utf-8")
        if not re.search(r'<link[^>]+href="[^"]+\.css"', dist_html):
            failures.append("built HTML has no CSS asset")
        if not re.search(r'<script[^>]+src="[^"]+\.js"', dist_html):
            failures.append("built HTML has no JavaScript asset")
        if ".ts" in dist_html:
            failures.append("built HTML still references TypeScript")

    for message in warnings:
        print(f"[upcheck] warning: {message}")
    for message in failures:
        print(f"[upcheck] failure: {message}")
    if failures:
        return 1

    team_counts = {
        key: len(bucket.get("picks") or [])
        for key, bucket in models.items()
        if key in REQUIRED_MODEL_KEYS and isinstance(bucket, dict)
    }
    team_visible_counts = {
        key: len(_visible_team_picks(bucket))
        for key, bucket in models.items()
        if key in REQUIRED_MODEL_KEYS and isinstance(bucket, dict)
    }
    player_counts = {
        key: len(bucket.get("picks") or [])
        for key, bucket in player_models.items()
        if key in REQUIRED_PLAYER_PROP_KEYS and isinstance(bucket, dict)
    }
    player_visible_counts = {
        key: len(_visible_player_picks(bucket))
        for key, bucket in player_models.items()
        if key in REQUIRED_PLAYER_PROP_KEYS and isinstance(bucket, dict)
    }
    parlay_count = len(parlay_latest.get("cards") or []) if parlay_latest else 0
    parlay_summary = parlay_latest.get("summary") if isinstance(parlay_latest, dict) and isinstance(parlay_latest.get("summary"), dict) else {}
    parlay_three_leg_count = int(parlay_summary.get("threeLegCards") or 0)
    profit_count = len(profit_latest.get("candidates") or []) if profit_latest else 0
    profit_qualified = int(
        (profit_latest.get("summary") or {}).get("researchQualified")
        or (profit_latest.get("summary") or {}).get("shadowQualified")
        or 0
    ) if profit_latest else 0
    profit_live = int(
        (profit_latest.get("summary") or {}).get("liveQualified") or 0
    ) if profit_latest else 0
    print(
        f"[upcheck] healthy for {today}: "
        f"teams_raw={team_counts}, teams_visible={team_visible_counts}, "
        f"player_props_raw={player_counts}, player_props_visible={player_visible_counts}, "
        f"parlay_cards={parlay_count}, parlay_3_leg={parlay_three_leg_count}, "
        f"profit_candidates={profit_count}, profit_qualified={profit_qualified}, "
        f"profit_live={profit_live}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
