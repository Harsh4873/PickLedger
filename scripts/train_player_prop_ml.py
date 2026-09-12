#!/usr/bin/env python3
"""Train lightweight player-prop ML artifacts from ledger and stat priors."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from player_props.ml import (  # noqa: E402
    ARTIFACT_DIR,
    FEATURE_NAMES,
    ML_MODEL_VERSION,
    SPORT_ARTIFACTS,
    feature_vector,
    market_family_for_stat,
)
from player_props.schema import american_implied_probability, safe_float  # noqa: E402
from scripts.pick_calibration import rebuild_outcome_ledger, read_json  # noqa: E402


MLB_FAMILIES = [
    "hits",
    "hrr",
    "runs",
    "rbis",
    "batter_walks",
    "batter_strikeouts",
    "total_bases",
    "singles",
    "doubles",
    "triples",
    "home_runs",
    "stolen_bases",
    "strikeouts",
    "pitcher_walks_allowed",
    "pitcher_outs_recorded",
    "pitcher_hits_allowed",
    "pitcher_earned_runs_allowed",
]

WNBA_FAMILIES = [
    "points",
    "rebounds",
    "assists",
    "pr",
    "pa",
    "pra",
    "3pm",
    "steals",
    "blocks",
    "stocks",
]

FOOTBALL_FAMILIES = [
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
]


MIN_TRAINING_SAMPLES = {"MLB": 200, "WNBA": 100, "NFL": 100, "CFB": 100}
MIN_VALIDATION_SAMPLES = {"MLB": 100, "WNBA": 40, "NFL": 40, "CFB": 40}
MIN_VALIDATION_DATES = 2
MAX_VALIDATION_CALIBRATION_GAP = 0.08


def _ledger_rows(
    repo_root: Path,
    sport: str,
    season: int,
) -> tuple[list[list[float]], list[int], list[str], list[float], list[float]]:
    ledger = read_json(repo_root / "data" / "calibration" / "outcome_ledger.json") or {}
    rows: list[list[float]] = []
    labels: list[int] = []
    dates: list[str] = []
    market_probabilities: list[float] = []
    baseline_probabilities: list[float] = []
    for record in ledger.get("records") or []:
        if not isinstance(record, dict):
            continue
        if str(record.get("cache_type") or "") != "player_props_cache":
            continue
        if str(record.get("sport") or "").upper() != sport:
            continue
        record_date = str(record.get("date") or "").strip()
        if not record_date.startswith(f"{season:04d}-"):
            continue
        outcome = record.get("outcome")
        if outcome not in {0, 1}:
            continue
        snapshot = record.get("pregame_snapshot") if isinstance(record.get("pregame_snapshot"), dict) else {}
        stat_key = str(snapshot.get("stat_key") or record.get("bet_type") or "").strip()
        baseline_probability = safe_float(
            snapshot.get("baseline_probability")
            or snapshot.get("raw_probability")
            or record.get("raw_probability")
            or record.get("probability"),
            0.5,
        )
        baseline_projection = safe_float(
            snapshot.get("baseline_projection")
            or snapshot.get("projection")
            or snapshot.get("line"),
            safe_float(snapshot.get("line"), 0.0),
        )
        pick = {
            "sport": sport,
            "stat_key": stat_key,
            "line": snapshot.get("line"),
            "odds": snapshot.get("odds"),
            "selection": snapshot.get("selection") or "Over",
            "market_priced": snapshot.get("market_priced") is not False,
        }
        odds = pick.get("odds")
        try:
            odds_int = int(odds) if odds not in (None, "") else None
        except (TypeError, ValueError):
            odds_int = None
        market_probability = safe_float(
            snapshot.get("market_implied_probability"),
            american_implied_probability(odds_int) or 0.5,
        )
        rows.append(
            feature_vector(
                pick,
                baseline_probability=baseline_probability,
                baseline_projection=baseline_projection,
                market_family=market_family_for_stat(stat_key),
            )
        )
        labels.append(int(outcome))
        dates.append(record_date)
        market_probabilities.append(market_probability)
        baseline_probabilities.append(baseline_probability)
    return rows, labels, dates, market_probabilities, baseline_probabilities


def _brier(labels: list[int], probabilities: list[float]) -> float | None:
    if not labels or len(labels) != len(probabilities):
        return None
    return sum((probability - label) ** 2 for label, probability in zip(labels, probabilities)) / len(labels)


def _fit_classifier(rows: list[list[float]], labels: list[int]) -> Any:
    from sklearn.linear_model import LogisticRegression  # type: ignore
    from sklearn.pipeline import Pipeline  # type: ignore
    from sklearn.preprocessing import StandardScaler  # type: ignore

    model = Pipeline([
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(C=0.20, max_iter=2000, random_state=42)),
    ])
    model.fit(rows, labels)
    return model


def _forward_validation(
    rows: list[list[float]],
    labels: list[int],
    dates: list[str],
    market_probabilities: list[float],
    baseline_probabilities: list[float],
) -> dict[str, Any]:
    predictions: list[float] = []
    validation_labels: list[int] = []
    validation_market: list[float] = []
    validation_baseline: list[float] = []
    validated_dates: list[str] = []
    for test_date in sorted(set(dates))[1:]:
        train_indices = [index for index, date in enumerate(dates) if date < test_date]
        test_indices = [index for index, date in enumerate(dates) if date == test_date]
        if len(train_indices) < 30 or len({labels[index] for index in train_indices}) < 2 or not test_indices:
            continue
        model = _fit_classifier(
            [rows[index] for index in train_indices],
            [labels[index] for index in train_indices],
        )
        fold_predictions = model.predict_proba([rows[index] for index in test_indices])[:, 1]
        predictions.extend(float(value) for value in fold_predictions)
        validation_labels.extend(labels[index] for index in test_indices)
        validation_market.extend(market_probabilities[index] for index in test_indices)
        validation_baseline.extend(baseline_probabilities[index] for index in test_indices)
        validated_dates.append(test_date)

    actual_rate = sum(validation_labels) / len(validation_labels) if validation_labels else None
    predicted_rate = sum(predictions) / len(predictions) if predictions else None
    return {
        "samples": len(validation_labels),
        "dates": validated_dates,
        "model_brier": _brier(validation_labels, predictions),
        "market_brier": _brier(validation_labels, validation_market),
        "baseline_brier": _brier(validation_labels, validation_baseline),
        "predicted_rate": predicted_rate,
        "actual_rate": actual_rate,
        "calibration_gap": abs(predicted_rate - actual_rate)
        if predicted_rate is not None and actual_rate is not None
        else None,
    }


def _fit_artifact(
    *,
    sport: str,
    families: list[str],
    repo_root: Path,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    artifact = SPORT_ARTIFACTS[sport]
    model_path = Path(artifact["model"])
    metadata_path = Path(artifact["metadata"])
    if model_path.exists() and metadata_path.exists() and not force and not dry_run:
        return {"sport": sport, "changed": False, "path": str(model_path)}

    existing_metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            loaded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded_metadata, dict):
                existing_metadata = loaded_metadata
        except (OSError, json.JSONDecodeError):
            pass

    try:
        import joblib  # type: ignore
    except Exception as exc:
        raise SystemExit(f"Missing ML training dependencies: {exc}") from exc

    season = datetime.now(ZoneInfo("America/Chicago")).year
    rows, labels, dates, market_probabilities, baseline_probabilities = _ledger_rows(
        repo_root,
        sport,
        season,
    )
    if len(rows) < 30 or len(set(labels)) < 2:
        if sport in {"NFL", "CFB"}:
            return {
                "sport": sport,
                "changed": False,
                "skipped": True,
                "reason": f"Not enough real {season} {sport} outcomes to train: {len(rows)}",
                "path": str(model_path),
            }
        raise SystemExit(f"Not enough real {season} {sport} outcomes to train: {len(rows)}")
    validation = _forward_validation(
        rows,
        labels,
        dates,
        market_probabilities,
        baseline_probabilities,
    )
    model = _fit_classifier(rows, labels)
    model_brier = validation.get("model_brier")
    market_brier = validation.get("market_brier")
    baseline_brier = validation.get("baseline_brier")
    calibration_gap = validation.get("calibration_gap")
    active = bool(
        len(rows) >= MIN_TRAINING_SAMPLES[sport]
        and int(validation.get("samples") or 0) >= MIN_VALIDATION_SAMPLES[sport]
        and len(validation.get("dates") or []) >= MIN_VALIDATION_DATES
        and model_brier is not None
        and market_brier is not None
        and baseline_brier is not None
        and calibration_gap is not None
        and model_brier < market_brier
        and model_brier < baseline_brier
        and calibration_gap <= MAX_VALIDATION_CALIBRATION_GAP
    )
    training_fingerprint = hashlib.sha256(
        json.dumps({"season": season, "rows": rows, "labels": labels, "dates": dates}, sort_keys=True).encode("utf-8")
    ).hexdigest()

    metadata = {
        "version": ML_MODEL_VERSION,
        "sport": sport,
        "model_type": "StandardScaler+LogisticRegression",
        "feature_names": FEATURE_NAMES,
        "market_families": families,
        "training_sources": [
            "current_season_projection_features",
            "current_season_pickledger_outcome_ledger",
        ],
        "training_season": season,
        "bootstrap_samples": 0,
        "ledger_samples": len(rows),
        "training_dates": sorted(set(dates)),
        "positive_rate": sum(labels) / len(labels),
        "validation": validation,
        "activation_requirements": {
            "minimum_training_samples": MIN_TRAINING_SAMPLES[sport],
            "minimum_validation_samples": MIN_VALIDATION_SAMPLES[sport],
            "minimum_validation_dates": MIN_VALIDATION_DATES,
            "maximum_calibration_gap": MAX_VALIDATION_CALIBRATION_GAP,
            "must_beat_market_brier": True,
            "must_beat_baseline_brier": True,
        },
        "active": active,
        "probability_mode": "validated_model_market_anchor" if active else "market_anchor_validation_gate",
        "training_fingerprint": training_fingerprint,
    }
    result = {
        "sport": sport,
        "changed": not dry_run,
        "path": str(model_path),
        "ledger_samples": len(rows),
        "active": active,
        "validation": validation,
    }
    if dry_run:
        result["changed"] = False
        result["candidate"] = metadata
        return result
    if active is not True and existing_metadata.get("active") is True:
        result["changed"] = False
        result["candidate_rejected"] = True
        return result
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": FEATURE_NAMES}, model_path)
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-evaluate artifacts even if present; rejected candidates cannot replace active artifacts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Train and evaluate candidates without replacing any artifacts.",
    )
    parser.add_argument("--rebuild-ledger", action="store_true", help="Rebuild outcome ledger before training.")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.rebuild_ledger:
        _, changed = rebuild_outcome_ledger(repo_root)
        print(f"[player-prop-ml] rebuilt outcome ledger (changed={str(changed).lower()})")

    results = [
        _fit_artifact(
            sport="MLB",
            families=MLB_FAMILIES,
            repo_root=repo_root,
            force=args.force,
            dry_run=args.dry_run,
        ),
        _fit_artifact(
            sport="WNBA",
            families=WNBA_FAMILIES,
            repo_root=repo_root,
            force=args.force,
            dry_run=args.dry_run,
        ),
        _fit_artifact(
            sport="NFL",
            families=FOOTBALL_FAMILIES,
            repo_root=repo_root,
            force=args.force,
            dry_run=args.dry_run,
        ),
        _fit_artifact(
            sport="CFB",
            families=FOOTBALL_FAMILIES,
            repo_root=repo_root,
            force=args.force,
            dry_run=args.dry_run,
        ),
    ]
    for result in results:
        status = (
            "skipped"
            if result.get("skipped")
            else "rejected"
            if result.get("candidate_rejected")
            else "candidate"
            if result.get("candidate")
            else "trained"
            if result.get("changed")
            else "existing"
        )
        print(f"[player-prop-ml] {result['sport']}: {status} {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
