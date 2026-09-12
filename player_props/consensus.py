"""Four-model, roster-aware player-prop consensus inference."""

from __future__ import annotations

import json
import math
import os
import statistics
from datetime import date
from pathlib import Path
from typing import Any

from .precision import CATEGORICAL_FEATURES, NUMERIC_FEATURES, history_features
from .schema import american_implied_probability, safe_float


CONSENSUS_VERSION = "player_props_consensus_v2.0.0"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
CONSENSUS_METADATA_PATH = ARTIFACT_DIR / "player_props_consensus_metadata.json"
MODEL_PATHS = {
    ("MLB", "season"): ARTIFACT_DIR / "mlb_player_props_season.joblib",
    ("MLB", "history"): ARTIFACT_DIR / "mlb_player_props_history.joblib",
    ("WNBA", "season"): ARTIFACT_DIR / "wnba_player_props_season.joblib",
    ("WNBA", "history"): ARTIFACT_DIR / "wnba_player_props_history.joblib",
    ("NFL", "season"): ARTIFACT_DIR / "nfl_player_props_season.joblib",
    ("NFL", "history"): ARTIFACT_DIR / "nfl_player_props_history.joblib",
    ("CFB", "season"): ARTIFACT_DIR / "cfb_player_props_season.joblib",
    ("CFB", "history"): ARTIFACT_DIR / "cfb_player_props_history.joblib",
}

OUTCOME_FEATURES = [
    "all_count",
    "all_mean5",
    "all_mean10",
    "all_mean20",
    "all_std10",
    "season_count",
    "season_mean3",
    "season_mean5",
    "season_mean10",
    "season_mean",
    "season_std",
    "usage_mean3",
    "usage_mean5",
    "usage_mean10",
    "usage_std10",
    "last_actual",
    "last_usage",
    "rest_days",
]
OUTCOME_MARKET_FEATURES = OUTCOME_FEATURES + ["line", "over_implied", "under_implied"]

TARGET_STATS = {
    "MLB": {"hits_runs_rbis", "hits", "strikeouts", "pitcher_walks_allowed", "batter_walks", "rbis"},
    "WNBA": {"points", "totalRebounds", "assists", "three_pointers_made", "points_rebounds", "points_assists"},
    "NFL": {"passing_yards", "rushing_yards", "receiving_yards", "receptions"},
    "CFB": {"passing_yards", "rushing_yards", "receiving_yards", "receptions"},
}

_BUNDLE: dict[str, Any] | None | bool = False


def _clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def outcome_profile_key(sport: Any, athlete_id: Any, stat_key: Any) -> str:
    return "|".join((str(sport or "").upper(), str(athlete_id or "").strip(), str(stat_key or "").strip()))


def _mean(rows: list[dict[str, Any]], field: str, count: int | None = None) -> float:
    selected = rows[-count:] if count else rows
    values = [safe_float(row.get(field), float("nan")) for row in selected]
    clean = [value for value in values if math.isfinite(value)]
    return statistics.fmean(clean) if clean else float("nan")


def _std(rows: list[dict[str, Any]], field: str, count: int | None = None) -> float:
    selected = rows[-count:] if count else rows
    values = [safe_float(row.get(field), float("nan")) for row in selected]
    clean = [value for value in values if math.isfinite(value)]
    return statistics.pstdev(clean) if len(clean) > 1 else float("nan")


def outcome_features(
    rows: list[dict[str, Any]],
    *,
    target_date: str,
) -> dict[str, float] | None:
    prior = sorted(
        [row for row in rows if str(row.get("date") or "") < target_date],
        key=lambda row: (str(row.get("date") or ""), str(row.get("event_id") or "")),
    )
    if len(prior) < 3:
        return None
    season = int(target_date[:4])
    season_rows = [row for row in prior if int(row.get("season") or 0) == season]
    if len(season_rows) < 3:
        return None
    last_date = str(season_rows[-1].get("date") or "")
    try:
        rest_days = (date.fromisoformat(target_date) - date.fromisoformat(last_date)).days
    except ValueError:
        rest_days = 0
    return {
        "all_count": float(len(prior)),
        "all_mean5": _mean(prior, "actual", 5),
        "all_mean10": _mean(prior, "actual", 10),
        "all_mean20": _mean(prior, "actual", 20),
        "all_std10": _std(prior, "actual", 10),
        "season_count": float(len(season_rows)),
        "season_mean3": _mean(season_rows, "actual", 3),
        "season_mean5": _mean(season_rows, "actual", 5),
        "season_mean10": _mean(season_rows, "actual", 10),
        "season_mean": _mean(season_rows, "actual"),
        "season_std": _std(season_rows, "actual"),
        "usage_mean3": _mean(season_rows, "usage", 3),
        "usage_mean5": _mean(season_rows, "usage", 5),
        "usage_mean10": _mean(season_rows, "usage", 10),
        "usage_std10": _std(season_rows, "usage", 10),
        "last_actual": _mean(season_rows, "actual", 1),
        "last_usage": _mean(season_rows, "usage", 1),
        "rest_days": float(max(0, rest_days)),
    }


def build_outcome_training_features(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = outcome_profile_key(row.get("sport"), row.get("athlete_id"), row.get("stat_key"))
        grouped.setdefault(key, []).append(row)
    features: list[dict[str, Any]] = []
    profiles: dict[str, list[dict[str, Any]]] = {}
    for key, profile in grouped.items():
        ordered = sorted(profile, key=lambda row: (str(row.get("date") or ""), str(row.get("event_id") or "")))
        profiles[key] = ordered
        for row in ordered:
            built = outcome_features(ordered, target_date=str(row.get("date") or ""))
            if built:
                features.append({**row, **built})
    return features, profiles


def load_consensus_bundle() -> dict[str, Any] | None:
    global _BUNDLE
    if os.environ.get("PICKLEDGER_DISABLE_PRECISION_MODEL", "").strip().lower() in {"1", "true", "yes"}:
        return None
    if _BUNDLE is not False:
        return _BUNDLE if isinstance(_BUNDLE, dict) else None
    try:
        import joblib  # type: ignore

        metadata = json.loads(CONSENSUS_METADATA_PATH.read_text(encoding="utf-8"))
        artifacts = {
            f"{sport}:{role}": joblib.load(path)
            for (sport, role), path in MODEL_PATHS.items()
            if path.exists()
        }
        if not artifacts:
            raise OSError("no consensus artifacts are present")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        _BUNDLE = None
        return None
    _BUNDLE = {"metadata": metadata, "artifacts": artifacts}
    return _BUNDLE


def consensus_active(sport: str | None = None) -> bool:
    bundle = load_consensus_bundle()
    if not bundle:
        return False
    metadata = bundle.get("metadata") or {}
    if metadata.get("active") is not True:
        return False
    if sport:
        return bool(((metadata.get("sports") or {}).get(str(sport).upper()) or {}).get("active"))
    return True


def _market_prediction(artifact: dict[str, Any], pick: dict[str, Any]) -> dict[str, Any] | None:
    stat_key = str(pick.get("stat_key") or "")
    model = (artifact.get("models") or {}).get(stat_key)
    profile = (artifact.get("market_profiles") or {}).get(
        f"{str(pick.get('market_athlete_id') or '').strip()}|{stat_key}"
    )
    if model is None or not isinstance(profile, list):
        return None
    try:
        over_odds = int(pick.get("market_over_odds"))
    except (TypeError, ValueError):
        return None
    try:
        under_odds = int(pick.get("market_under_odds"))
    except (TypeError, ValueError):
        under_odds = None
    over_implied = american_implied_probability(over_odds)
    under_implied = american_implied_probability(under_odds)
    if over_implied is None:
        return None
    features = history_features(
        profile,
        line=safe_float(pick.get("line")),
        over_implied=over_implied,
        under_implied=under_implied,
        stat_key=stat_key,
        market_format=str(pick.get("market_format") or "total"),
    )
    if not features:
        return None
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame([features])[NUMERIC_FEATURES].apply(pd.to_numeric, errors="coerce")
        probability = float(model.predict_proba(frame)[0][1])
    except Exception:
        return None
    return {"over_probability": probability, "features": features}


def _outcome_prediction(artifact: dict[str, Any], pick: dict[str, Any]) -> dict[str, Any] | None:
    sport = str(pick.get("sport") or "").upper()
    stat_key = str(pick.get("stat_key") or "")
    model = (artifact.get("models") or {}).get(stat_key)
    profile = (artifact.get("outcome_profiles") or {}).get(
        outcome_profile_key(sport, pick.get("market_athlete_id"), stat_key)
    )
    if model is None or not isinstance(profile, list):
        return None
    features = outcome_features(profile, target_date=str(pick.get("date") or ""))
    if not features:
        return None
    kind = str((artifact.get("kinds") or {}).get(stat_key) or "regressor")
    model_features = list((artifact.get("model_features") or {}).get(stat_key) or OUTCOME_FEATURES)
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame([features])[model_features]
        if kind == "classifier":
            return {"over_probability": float(model.predict_proba(frame)[0][1]), "features": features}
        return {"projection": float(model.predict(frame)[0]), "features": features}
    except Exception:
        return None


def _outcome_market_prediction(artifact: dict[str, Any], pick: dict[str, Any]) -> dict[str, Any] | None:
    sport = str(pick.get("sport") or "").upper()
    stat_key = str(pick.get("stat_key") or "")
    model = (artifact.get("models") or {}).get(stat_key)
    profile = (artifact.get("outcome_profiles") or {}).get(
        outcome_profile_key(sport, pick.get("market_athlete_id"), stat_key)
    )
    if model is None or not isinstance(profile, list):
        return None
    try:
        over_odds = int(pick.get("market_over_odds"))
    except (TypeError, ValueError):
        return None
    try:
        under_odds = int(pick.get("market_under_odds"))
    except (TypeError, ValueError):
        under_odds = None
    over_implied = american_implied_probability(over_odds)
    under_implied = american_implied_probability(under_odds)
    if over_implied is None:
        return None
    features = outcome_features(profile, target_date=str(pick.get("date") or ""))
    if not features:
        return None
    features.update(
        {
            "line": safe_float(pick.get("line")),
            "over_implied": over_implied,
            "under_implied": under_implied,
        }
    )
    model_features = list((artifact.get("model_features") or {}).get(stat_key) or OUTCOME_MARKET_FEATURES)
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame([features])[model_features].apply(pd.to_numeric, errors="coerce")
        return {"over_probability": float(model.predict_proba(frame)[0][1]), "features": features}
    except Exception:
        return None


def _prediction(artifact: dict[str, Any], pick: dict[str, Any], stat_key: str) -> dict[str, Any] | None:
    kind = str((artifact.get("kinds") or {}).get(stat_key) or "market_classifier")
    if kind == "market_classifier":
        return _market_prediction(artifact, pick)
    if kind == "outcome_market_classifier":
        return _outcome_market_prediction(artifact, pick)
    return _outcome_prediction(artifact, pick)


def evaluate_consensus_pick(pick: dict[str, Any]) -> dict[str, Any]:
    bundle = load_consensus_bundle()
    if not bundle:
        return {"required": False, "qualified": False, "reason": "four-model consensus unavailable"}
    metadata = bundle.get("metadata") or {}
    sport = str(pick.get("sport") or "").upper()
    stat_key = str(pick.get("stat_key") or "")
    sport_meta = ((metadata.get("sports") or {}).get(sport) or {})
    policy = (sport_meta.get("policies") or {}).get(stat_key)
    if metadata.get("active") is not True or sport_meta.get("active") is not True:
        return {"required": True, "qualified": False, "reason": f"{sport} four-model gate inactive"}
    if not isinstance(policy, dict):
        return {"required": True, "qualified": False, "reason": f"{stat_key} has not cleared 70%"}
    validation = policy.get("validation") or {}
    holdout = policy.get("holdout") or {}
    activation = metadata.get("activation_requirements") or {}
    target_accuracy = safe_float(
        metadata.get("target_accuracy"),
        safe_float(activation.get("minimum_accuracy"), 0.70),
    )
    minimum_validation_samples = safe_float(policy.get("minimum_validation_samples"), 0.0)
    minimum_holdout_samples = safe_float(policy.get("minimum_holdout_samples"), 0.0)
    if policy.get("active") is False:
        return {"required": True, "qualified": False, "reason": f"{stat_key} has not cleared 70%"}
    if (
        safe_float(validation.get("samples"), 0.0) < minimum_validation_samples
        or safe_float(holdout.get("samples"), 0.0) < minimum_holdout_samples
    ):
        return {"required": True, "qualified": False, "reason": f"{stat_key} sample size below publication floor"}
    if (
        safe_float(validation.get("accuracy"), 0.0) < target_accuracy
        or safe_float(holdout.get("accuracy"), 0.0) < target_accuracy
    ):
        return {
            "required": True,
            "qualified": False,
            "reason": f"{stat_key} consensus calibration below {target_accuracy:.0%}",
        }
    if stat_key == "hits_runs_rbis" and safe_float(pick.get("line")) != 1.5:
        return {"required": True, "qualified": False, "reason": "HRR is restricted to the 1.5 line"}
    artifacts = bundle.get("artifacts") or {}
    season_artifact = artifacts.get(f"{sport}:season") or {}
    history_artifact = artifacts.get(f"{sport}:history") or {}
    season = _prediction(season_artifact, pick, stat_key)
    history = _prediction(history_artifact, pick, stat_key)
    if not season or not history:
        return {"required": True, "qualified": False, "reason": "missing season/history player profile"}
    line = safe_float(pick.get("line"))
    fixed_selection = str(policy.get("selection") or "")
    if fixed_selection:
        selection = fixed_selection
    else:
        season_over = safe_float(season.get("over_probability")) >= 0.5
        selection = "Over" if season_over else "Under"
    try:
        selected_odds = int(pick.get("market_over_odds") if selection == "Over" else pick.get("market_under_odds"))
    except (TypeError, ValueError):
        return {"required": True, "qualified": False, "reason": f"{selection.lower()} price unavailable"}
    implied = american_implied_probability(selected_odds)
    if implied is None:
        return {"required": True, "qualified": False, "reason": "invalid selected price"}

    season_over_probability = season.get("over_probability")
    history_over_probability = history.get("over_probability")
    season_probability = (
        safe_float(season_over_probability)
        if selection == "Over"
        else 1.0 - safe_float(season_over_probability)
    ) if season_over_probability is not None else None
    history_probability = (
        safe_float(history_over_probability)
        if selection == "Over"
        else 1.0 - safe_float(history_over_probability)
    ) if history_over_probability is not None else None
    season_projection = season.get("projection")
    history_projection = history.get("projection")
    season_margin = (
        safe_float(season_projection) - line if selection == "Over" else line - safe_float(season_projection)
    ) if season_projection is not None else None
    history_margin = (
        safe_float(history_projection) - line if selection == "Over" else line - safe_float(history_projection)
    ) if history_projection is not None else None
    season_features = season.get("features") or {}
    history_features_row = history.get("features") or {}
    season_rate = safe_float(season_features.get("over_rate"), 0.5)
    history_rate = safe_float(history_features_row.get("over_rate"), 0.5)
    if selection == "Under":
        season_rate = 1.0 - season_rate
        history_rate = 1.0 - history_rate

    checks: dict[str, bool] = {"market_implied": implied >= safe_float(policy.get("minimum_implied"), 0.0)}
    if season_probability is not None:
        checks["season_probability"] = season_probability >= safe_float(policy.get("minimum_season_probability"), 0.0)
    if history_probability is not None:
        checks["history_probability"] = history_probability >= safe_float(policy.get("minimum_history_probability"), 0.0)
    if policy.get("require_classifier_agreement"):
        season_says_over = safe_float(season_over_probability) >= 0.5
        history_says_over = safe_float(history_over_probability) >= 0.5
        if fixed_selection == "Over":
            checks["model_agreement"] = season_says_over and history_says_over
        elif fixed_selection == "Under":
            checks["model_agreement"] = (not season_says_over) and (not history_says_over)
        else:
            checks["model_agreement"] = season_says_over == history_says_over
    checks["season_rate"] = season_rate >= safe_float(policy.get("minimum_season_rate"), 0.0)
    checks["history_rate"] = history_rate >= safe_float(policy.get("minimum_history_rate"), 0.0)
    if season_margin is not None:
        checks["season_margin_low"] = season_margin >= safe_float(policy.get("minimum_season_margin"), -99.0)
        checks["season_margin_high"] = season_margin <= safe_float(policy.get("maximum_season_margin"), 99.0)
    if history_margin is not None:
        checks["history_margin_low"] = history_margin >= safe_float(policy.get("minimum_history_margin"), -99.0)
        checks["history_margin_high"] = history_margin <= safe_float(policy.get("maximum_history_margin"), 99.0)
    if "minimum_season_mean_margin" in policy:
        checks["season_mean_margin"] = (
            safe_float(history_features_row.get("season_mean")) - line
            >= safe_float(policy.get("minimum_season_mean_margin"))
        )
    if "minimum_usage_trend" in policy:
        checks["usage_trend"] = (
            safe_float(history_features_row.get("usage_mean3")) - safe_float(history_features_row.get("usage_mean10"))
            >= safe_float(policy.get("minimum_usage_trend"))
        )
    gate_probability = None
    if "meta_gate_threshold" in policy:
        gate = (history_artifact.get("gate_models") or {}).get(stat_key)
        gate_features = list(history_artifact.get("gate_features") or [])
        gate_row = {
            "season_margin": season_margin,
            "history_margin": history_margin,
            "season_mean_margin": safe_float(history_features_row.get("season_mean")) - line,
            "usage_trend": (
                safe_float(history_features_row.get("usage_mean3"))
                - safe_float(history_features_row.get("usage_mean10"))
            ),
            "over_implied": implied,
            "line": line,
            "season_count": safe_float(history_features_row.get("season_count")),
            "rest_days": safe_float(history_features_row.get("rest_days")),
            "season_std": safe_float(history_features_row.get("season_std")),
            "last_actual": safe_float(history_features_row.get("last_actual")),
            "last_usage": safe_float(history_features_row.get("last_usage")),
        }
        try:
            import pandas as pd  # type: ignore

            gate_probability = float(gate.predict_proba(pd.DataFrame([gate_row])[gate_features])[0][1])
        except Exception:
            gate_probability = 0.0
        checks["meta_gate"] = gate_probability >= safe_float(policy.get("meta_gate_threshold"))
    qualified = all(checks.values())
    failed = [name for name, passed in checks.items() if not passed]
    conservative_accuracy = min(safe_float(validation.get("accuracy")), safe_float(holdout.get("accuracy")))
    pick_probability_inputs = [
        value
        for value in (season_probability, history_probability, gate_probability)
        if value is not None and math.isfinite(safe_float(value, float("nan")))
    ]
    pick_probability = statistics.fmean(pick_probability_inputs) if pick_probability_inputs else implied
    return {
        "required": True,
        "qualified": qualified,
        "reason": "qualified" if qualified else f"failed: {', '.join(failed)}",
        "selection": selection,
        "odds": selected_odds,
        "implied_probability": implied,
        "probability": _clamp(pick_probability),
        "conservative_validation_accuracy": conservative_accuracy,
        "season_probability": season_probability,
        "history_probability": history_probability,
        "season_projection": season_projection,
        "history_projection": history_projection,
        "season_margin": season_margin,
        "history_margin": history_margin,
        "season_rate": season_rate,
        "history_rate": history_rate,
        "validation_accuracy": safe_float(validation.get("accuracy")),
        "holdout_accuracy": safe_float(holdout.get("accuracy")),
        "model_version": str(metadata.get("version") or CONSENSUS_VERSION),
        "training_fingerprint": str(metadata.get("training_fingerprint") or ""),
        "agreement": bool(checks.get("model_agreement", True)),
        "consensus_score": (
            gate_probability
            if gate_probability is not None
            else statistics.fmean(
                value
                for value in (season_probability, history_probability, implied)
                if value is not None
            )
        ),
    }
