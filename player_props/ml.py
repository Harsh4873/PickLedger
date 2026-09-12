"""Lightweight ML artifact loading, scoring, and EV ranking for player props."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .schema import (
    american_implied_probability,
    decision_and_stake,
    market_fair_probability,
    safe_float,
)


ML_SOURCE = "player_props_ml_v1"
ML_MODEL_VERSION = "player_props_ml_v1.1.0"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

BASE_FEATURE_NAMES = [
    "line",
    "odds_implied",
    "baseline_probability",
    "baseline_projection",
    "projection_over_line",
    "selection_over",
    "market_priced",
]
MARKET_FAMILY_NAMES = sorted({
    "3pm",
    "assists",
    "batter_strikeouts",
    "batter_walks",
    "blocks",
    "doubles",
    "hits",
    "home_runs",
    "hrr",
    "pa",
    "pitcher_earned_runs_allowed",
    "pitcher_hits_allowed",
    "pitcher_outs_recorded",
    "pitcher_walks_allowed",
    "points",
    "pr",
    "pra",
    "rbis",
    "rebounds",
    "runs",
    "singles",
    "steals",
    "stocks",
    "stolen_bases",
    "strikeouts",
    "total_bases",
    "triples",
    "passing_yards",
    "passing_tds",
    "passing_completions",
    "interceptions",
    "rushing_yards",
    "rushing_attempts",
    "rushing_tds",
    "receiving_yards",
    "receptions",
    "receiving_tds",
})
FEATURE_NAMES = BASE_FEATURE_NAMES + [f"family::{family}" for family in MARKET_FAMILY_NAMES]

MAX_PUBLISHED_PROPS_PER_GAME = 8
MAX_PUBLISHED_PROPS_PER_PLAYER = 1
MIN_PUBLISHED_PROBABILITY = 0.52
MIN_PUBLISHED_EDGE = 0.04
MIN_PUBLISHED_EXPECTED_VALUE = 0.05
MAX_PUBLISHED_POSITIVE_ODDS = 250

SPORT_ARTIFACTS = {
    "MLB": {
        "model": ARTIFACT_DIR / "mlb_player_props_ml.joblib",
        "metadata": ARTIFACT_DIR / "mlb_player_props_ml_metadata.json",
        "artifact_sport": "MLB",
    },
    "WNBA": {
        "model": ARTIFACT_DIR / "wnba_player_props_ml.joblib",
        "metadata": ARTIFACT_DIR / "wnba_player_props_ml_metadata.json",
        "artifact_sport": "WNBA",
    },
    # No NBA training data has been captured yet, so NBA props borrow the
    # WNBA artifact. Cross-sport-scored picks are labeled and capped at LEAN
    # until a native NBA artifact exists.
    "NBA": {
        "model": ARTIFACT_DIR / "wnba_player_props_ml.joblib",
        "metadata": ARTIFACT_DIR / "wnba_player_props_ml_metadata.json",
        "artifact_sport": "WNBA",
    },
    # Football stays native and fail-closed: no basketball artifact borrowing.
    "NFL": {
        "model": ARTIFACT_DIR / "nfl_player_props_ml.joblib",
        "metadata": ARTIFACT_DIR / "nfl_player_props_ml_metadata.json",
        "artifact_sport": "NFL",
    },
    "CFB": {
        "model": ARTIFACT_DIR / "cfb_player_props_ml.joblib",
        "metadata": ARTIFACT_DIR / "cfb_player_props_ml_metadata.json",
        "artifact_sport": "CFB",
    },
}


def artifact_sport_for(sport: str) -> str | None:
    artifact = SPORT_ARTIFACTS.get(str(sport or "").strip().upper())
    if artifact is None:
        return None
    return str(artifact.get("artifact_sport") or "") or None

_BUNDLES: dict[str, dict[str, Any] | None] = {}


def _clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def _family_hash(market_family: str) -> float:
    digest = hashlib.sha256(str(market_family or "unknown").encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return (bucket * 2.0) - 1.0


def market_family_for_stat(stat_key: str) -> str:
    key = str(stat_key or "").strip()
    aliases = {
        "totalRebounds": "rebounds",
        "hits_runs_rbis": "hrr",
        "points_rebounds_assists": "pra",
        "points_rebounds": "pr",
        "points_assists": "pa",
        "three_pointers_made": "3pm",
        "steals_blocks": "stocks",
        "batter_walks": "batter_walks",
        "batter_strikeouts": "batter_strikeouts",
        "pitcher_walks_allowed": "pitcher_walks_allowed",
        "pitcher_outs_recorded": "pitcher_outs_recorded",
        "pitcher_hits_allowed": "pitcher_hits_allowed",
        "pitcher_earned_runs_allowed": "pitcher_earned_runs_allowed",
    }
    return aliases.get(key, key.replace(" ", "_").lower() or "unknown")


def expected_value(probability: float, odds: int | None) -> float:
    if odds is None or odds == 0:
        return 0.0
    profit = 100.0 / abs(odds) if odds < 0 else odds / 100.0
    return (probability * profit) - (1.0 - probability)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_ml_bundle(sport: str) -> dict[str, Any] | None:
    normalized = str(sport or "").strip().upper()
    artifact = SPORT_ARTIFACTS.get(normalized)
    if artifact is None:
        return None
    cache_key = normalized
    if cache_key in _BUNDLES:
        return _BUNDLES[cache_key]
    metadata = _load_json(artifact["metadata"])
    try:
        import joblib  # type: ignore

        model_payload = joblib.load(artifact["model"])
    except Exception:
        model_payload = None
    if isinstance(model_payload, dict):
        model = model_payload.get("model")
        feature_names = model_payload.get("features") or FEATURE_NAMES
    else:
        model = model_payload
        feature_names = FEATURE_NAMES
    if model is None:
        _BUNDLES[cache_key] = None
        return None
    bundle = {"model": model, "features": list(feature_names), "metadata": metadata}
    _BUNDLES[cache_key] = bundle
    return bundle


def feature_vector(
    pick: dict[str, Any],
    *,
    baseline_probability: float,
    baseline_projection: float,
    market_family: str,
    feature_names: list[str] | None = None,
) -> list[float]:
    line = safe_float(pick.get("line"))
    odds = pick.get("odds")
    try:
        odds_int = int(odds) if odds is not None else None
    except (TypeError, ValueError):
        odds_int = None
    implied = american_implied_probability(odds_int) or 0.5
    selection_over = 1.0 if str(pick.get("selection") or "").strip().lower() == "over" else 0.0
    normalized_family = market_family_for_stat(market_family)
    values = {
        "line": line,
        "odds_implied": implied,
        "baseline_probability": _clamp(baseline_probability),
        "baseline_projection": safe_float(baseline_projection),
        "projection_over_line": safe_float(baseline_projection) - line,
        "selection_over": selection_over,
        "market_family_hash": _family_hash(normalized_family),
        "market_priced": 1.0 if pick.get("market_priced") is True else 0.0,
    }
    for family in MARKET_FAMILY_NAMES:
        values[f"family::{family}"] = 1.0 if normalized_family == family else 0.0
    return [safe_float(values.get(name)) for name in (feature_names or FEATURE_NAMES)]


def _predict_bundle_probability(bundle: dict[str, Any] | None, vector: list[float]) -> float | None:
    if not bundle:
        return None
    model = bundle.get("model")
    if model is None:
        return None
    try:
        probabilities = model.predict_proba([vector])
        return _clamp(float(probabilities[0][1]))
    except Exception:
        return None


def _score_probability_details(
    pick: dict[str, Any],
    *,
    baseline_probability: float,
    baseline_projection: float,
    market_family: str,
) -> tuple[float, str, str, bool, str, float | None]:
    bundle = load_ml_bundle(str(pick.get("sport") or ""))
    feature_names = list(bundle.get("features") or FEATURE_NAMES) if bundle else FEATURE_NAMES
    vector = feature_vector(
        pick,
        baseline_probability=baseline_probability,
        baseline_projection=baseline_projection,
        market_family=market_family,
        feature_names=feature_names,
    )
    raw_model_probability = _predict_bundle_probability(bundle, vector)
    metadata = (bundle.get("metadata") or {}) if bundle else {}
    model_active = bool(metadata.get("active") is True and raw_model_probability is not None)
    try:
        odds = int(pick["odds"]) if pick.get("odds") not in (None, "") else None
    except (TypeError, ValueError):
        odds = None
    implied = american_implied_probability(odds)
    baseline = _clamp(baseline_probability)
    if implied is None:
        model_probability = baseline
        mode = "baseline_fallback"
    elif model_active:
        blended = (raw_model_probability * 0.55) + (baseline * 0.25) + (implied * 0.20)
        model_probability = implied + max(-0.12, min(0.12, blended - implied))
        mode = "validated_model_market_anchor"
    else:
        # Until forward validation beats both the market and the projection baseline,
        # only allow a small fraction of the live projection edge away from the price.
        anchored_edge = max(-0.06, min(0.08, (baseline - implied) * 0.35))
        model_probability = implied + anchored_edge
        mode = "market_anchor_validation_gate"
    model_version = str(metadata.get("version") or f"{ML_MODEL_VERSION}-fallback")
    fingerprint = str(metadata.get("training_fingerprint") or "fallback")
    return (
        round(_clamp(model_probability), 4),
        model_version,
        fingerprint,
        model_active,
        mode,
        round(raw_model_probability, 4) if raw_model_probability is not None else None,
    )


def score_probability(
    pick: dict[str, Any],
    *,
    baseline_probability: float,
    baseline_projection: float,
    market_family: str,
) -> tuple[float, str, str]:
    probability, version, fingerprint, _, _, _ = _score_probability_details(
        pick,
        baseline_probability=baseline_probability,
        baseline_projection=baseline_projection,
        market_family=market_family,
    )
    return probability, version, fingerprint


def apply_ml_to_pick(
    pick: dict[str, Any],
    *,
    baseline_probability: float,
    baseline_projection: float,
    market_family: str | None = None,
    apply_precision: bool = True,
) -> dict[str, Any]:
    family = market_family or market_family_for_stat(str(pick.get("stat_key") or ""))
    (
        ml_probability,
        model_version,
        fingerprint,
        model_active,
        probability_mode,
        raw_model_probability,
    ) = _score_probability_details(
        pick,
        baseline_probability=baseline_probability,
        baseline_projection=baseline_projection,
        market_family=family,
    )
    odds_raw = pick.get("odds")
    try:
        odds = int(odds_raw) if odds_raw is not None else None
    except (TypeError, ValueError):
        odds = None
    fair_probability = market_fair_probability(pick)
    decision, edge, full_kelly, quarter_kelly, units = decision_and_stake(
        ml_probability, odds, fair_probability=fair_probability
    )
    pick_sport = str(pick.get("sport") or "").strip().upper()
    scored_sport = artifact_sport_for(pick_sport)
    cross_sport = bool(scored_sport and pick_sport and scored_sport != pick_sport)
    if cross_sport:
        pick["ml_artifact_sport"] = scored_sport
        pick["cross_sport_artifact"] = True
        if decision == "BET":
            decision = "LEAN"
        pick.setdefault("key_factors", []).insert(
            0,
            f"Scored with {scored_sport}-trained model (no {pick_sport} training data yet) — treat as research",
        )
    market_implied = american_implied_probability(odds)
    stake_cap = 1.0 if model_active else 0.5
    if cross_sport:
        stake_cap = min(stake_cap, 0.5)
    quarter_kelly = min(quarter_kelly, stake_cap / 100.0)
    full_kelly = min(full_kelly, quarter_kelly * 4.0)
    units = 0.0 if decision == "PASS" else round(quarter_kelly * 100.0, 2)
    edge_fraction = (edge or 0.0) / 100.0
    confidence = (
        "High"
        if ml_probability >= 0.58 and edge_fraction >= 0.07
        else "Medium"
        if ml_probability >= MIN_PUBLISHED_PROBABILITY and edge_fraction >= MIN_PUBLISHED_EDGE
        else "Low"
    )
    epoch_fingerprint = fingerprint[:16] if fingerprint else "unfingerprinted"
    rank_epoch = f"{str(pick.get('sport') or '').strip().upper()}:{model_version}:{epoch_fingerprint}"
    pick.update(
        {
            "probability_source": ML_SOURCE,
            "ml_probability": ml_probability,
            "ml_edge": round(ml_probability - (market_implied or 0.0), 6) if market_implied is not None else None,
            "ml_expected_value": round(expected_value(ml_probability, odds), 6),
            "ml_model_version": model_version,
            "ml_model_active": model_active,
            "ml_probability_mode": probability_mode,
            "ml_raw_probability": raw_model_probability,
            "ml_training_fingerprint": fingerprint,
            "ml_rank_epoch": rank_epoch,
            "ranking_epoch": rank_epoch,
            "model_epoch": rank_epoch,
            "ml_market_family": family,
            "baseline_projection": round(safe_float(baseline_projection), 3),
            "baseline_probability": round(_clamp(baseline_probability), 6),
            "ml_calibration_excluded": True,
            "probability": ml_probability,
            "confidence": confidence,
            "edge": edge,
            "edge_basis": "no_vig" if fair_probability is not None else "vigged",
            "decision": decision,
            "full_kelly": full_kelly,
            "quarter_kelly": quarter_kelly,
            "units": units,
            "ml_stake_cap": stake_cap,
        }
    )
    if not apply_precision:
        return pick

    from .precision import apply_precision_to_pick

    return apply_precision_to_pick(pick)


def ev_sort_key(prop: dict[str, Any]) -> tuple[float, int, float, float, str]:
    decision_rank = {"BET": 0, "LEAN": 1, "PASS": 2}
    return (
        -safe_float(prop.get("ml_expected_value"), -100.0),
        decision_rank.get(str(prop.get("decision") or ""), 3),
        -safe_float(prop.get("ml_edge"), -100.0),
        -safe_float(prop.get("ml_probability") or prop.get("probability")),
        str(prop.get("id") or ""),
    )


def assign_ml_ranks(props: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(props, key=ev_sort_key)
    for index, prop in enumerate(ranked, start=1):
        prop["ml_rank"] = index
        prop["model_rank"] = index
        prop["rank"] = index
    return ranked


def is_publishable_ml_pick(prop: dict[str, Any]) -> bool:
    if prop.get("precision_required") is True:
        return bool(
            prop.get("precision_qualified") is True
            and prop.get("market_priced") is True
            and str(prop.get("decision") or "") in {"BET", "LEAN"}
            and safe_float(prop.get("probability")) >= 0.70
        )
    if prop.get("market_priced") is not True:
        return False
    if str(prop.get("decision") or "") not in {"BET", "LEAN"}:
        return False
    odds = int(safe_float(prop.get("odds")))
    if odds > MAX_PUBLISHED_POSITIVE_ODDS:
        return False
    return (
        safe_float(prop.get("ml_probability") or prop.get("probability")) >= MIN_PUBLISHED_PROBABILITY
        and safe_float(prop.get("ml_edge")) >= MIN_PUBLISHED_EDGE
        and safe_float(prop.get("ml_expected_value")) >= MIN_PUBLISHED_EXPECTED_VALUE
    )


def select_top_props(
    props: list[dict[str, Any]],
    *,
    max_picks: int = MAX_PUBLISHED_PROPS_PER_GAME,
    max_per_player: int = MAX_PUBLISHED_PROPS_PER_PLAYER,
) -> list[dict[str, Any]]:
    from .precision import precision_model_required

    ranked = assign_ml_ranks(props)
    has_market = any(prop.get("market_priced") is True for prop in ranked)
    precision_required = precision_model_required()
    selection_pool = [prop for prop in ranked if is_publishable_ml_pick(prop)] if has_market else ranked
    if precision_required:
        selection_pool = [prop for prop in selection_pool if prop.get("precision_qualified") is True]
        selection_pool.sort(
            key=lambda prop: (
                -safe_float(prop.get("consensus_score")),
                -safe_float(prop.get("ml_edge")),
                -safe_float(prop.get("ml_probability") or prop.get("probability")),
                str(prop.get("id") or ""),
            )
        )
        sport = str((selection_pool[0] if selection_pool else ranked[0] if ranked else {}).get("sport") or "").upper()
        max_picks = min(max_picks, 3 if sport == "WNBA" else 1)
    selected: list[dict[str, Any]] = []
    per_player: dict[str, int] = {}
    for prop in selection_pool:
        player_id = str(prop.get("player_id") or prop.get("player_name") or "")
        if per_player.get(player_id, 0) >= max_per_player:
            continue
        selected.append(prop)
        per_player[player_id] = per_player.get(player_id, 0) + 1
        if len(selected) >= max_picks:
            break
    return selected
