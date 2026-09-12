"""Top-level isolated player-props payload generator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .api import DirectApiClient
from .basketball import generate_basketball_candidate_model, generate_wnba_3pm_candidate_model
from .football import generate_football_candidate_model
from .ml import assign_ml_ranks
from .mlb import generate_mlb_candidate_model
from .variants import build_variant_buckets, build_wnba_3pm_bucket


def _soft_football_candidates(api: Any, league: str, sport: str, date_iso: str) -> dict[str, Any]:
    """Keep NFL/CFB outages from blocking MLB/NBA/WNBA publication."""
    try:
        return generate_football_candidate_model(api, league, sport, date_iso)
    except Exception as exc:
        return {
            "ok": True,
            "sport": sport,
            "date": date_iso,
            "games": 0,
            "picks": [],
            "errors": [str(exc)],
            "note": f"{sport} player-props soft-failed; empty slate so other sports can publish.",
        }


def generate_payload(
    date_iso: str,
    *,
    client: Any | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    api = client or DirectApiClient()
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    nba_candidates = generate_basketball_candidate_model(api, "nba", "NBA", date_iso)
    wnba_candidates = generate_basketball_candidate_model(api, "wnba", "WNBA", date_iso)
    wnba_3pm_candidates = generate_wnba_3pm_candidate_model(api, date_iso)
    mlb_candidates = generate_mlb_candidate_model(api, date_iso)
    nfl_candidates = _soft_football_candidates(api, "nfl", "NFL", date_iso)
    cfb_candidates = _soft_football_candidates(api, "college-football", "CFB", date_iso)
    models = {
        **build_variant_buckets(sport="NBA", date_iso=date_iso, base_model=nba_candidates),
        **build_variant_buckets(sport="WNBA", date_iso=date_iso, base_model=wnba_candidates),
        **build_wnba_3pm_bucket(date_iso=date_iso, base_model=wnba_3pm_candidates),
        **build_variant_buckets(sport="MLB", date_iso=date_iso, base_model=mlb_candidates),
        **build_variant_buckets(sport="NFL", date_iso=date_iso, base_model=nfl_candidates),
        **build_variant_buckets(sport="CFB", date_iso=date_iso, base_model=cfb_candidates),
    }
    payload = {
        "date": date_iso,
        "generatedAt": timestamp,
        "updatedAt": timestamp,
        "models": models,
    }
    for model in payload["models"].values():
        picks = model.get("picks")
        if not isinstance(picks, list) or not picks:
            continue
        model["picks"] = assign_ml_ranks([pick for pick in picks if isinstance(pick, dict)])
        for pick in model["picks"]:
            pick["ranking_updated_at"] = timestamp
        epochs = sorted({str(pick.get("ml_rank_epoch") or "") for pick in model["picks"] if pick.get("ml_rank_epoch")})
        versions = sorted({str(pick.get("ml_model_version") or "") for pick in model["picks"] if pick.get("ml_model_version")})
        fingerprints = sorted({str(pick.get("ml_training_fingerprint") or "") for pick in model["picks"] if pick.get("ml_training_fingerprint")})
        if epochs:
            model["ranking_epoch"] = epochs[0] if len(epochs) == 1 else "|".join(epochs)
        if versions:
            model["model_version"] = versions[0] if len(versions) == 1 else "|".join(versions)
        if fingerprints:
            model["training_fingerprint"] = fingerprints[0] if len(fingerprints) == 1 else "|".join(fingerprints)
        model["ranking_updated_at"] = timestamp
    return payload
