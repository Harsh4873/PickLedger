"""Published player-prop model variants for separate records."""

from __future__ import annotations

import copy
import hashlib
import math
import os
import statistics
from typing import Any

from .consensus import evaluate_consensus_pick, load_consensus_bundle, outcome_profile_key
from .ml import (
    MAX_PUBLISHED_POSITIVE_ODDS,
    MIN_PUBLISHED_EDGE,
    MIN_PUBLISHED_EXPECTED_VALUE,
    MIN_PUBLISHED_PROBABILITY,
    ML_SOURCE,
    expected_value,
    market_family_for_stat,
)
from .schema import (
    american_implied_probability,
    decision_and_stake,
    market_fair_probability,
    normal_probability,
    safe_float,
)


VARIANT_VERSION = "player_props_variant_v1.0.0"
MAX_VARIANT_PICKS = 8
MAX_VARIANT_PICKS_PER_GAME = 8
MAX_PER_PLAYER = 1
MIN_VARIANT_EDGE = 0.025
MIN_VARIANT_EV = 0.015

VARIANT_LABELS = {
    "season": "Season",
    "all_time": "All Time",
    "hot_l10": "Hot (L10)",
    "matchup_h2h": "Matchup (H2H)",
}

VARIANT_ORDER = ("season", "all_time", "hot_l10", "matchup_h2h")
HISTORY_WINDOWS = {"MLB": "2022-26", "WNBA": "2024-26", "NFL": "2024-26", "CFB": "2024-26"}
WNBA_3PM_MODEL_KEY = "wnba_3pm"
WNBA_3PM_SOURCE = "WNBA3PM"
WNBA_3PM_VARIANT = "wnba_3pm"
WNBA_3PM_VARIANT_LABEL = "WNBA 3PM"
WNBA_3PM_RELAXED_CONSENSUS_FLOOR = 0.55
WNBA_3PM_RELAXED_CONSENSUS_GATE_DROP = 0.15


def player_prop_variant_keys(sport: str) -> dict[str, str]:
    prefix = str(sport or "").strip().lower()
    return {variant: f"{prefix}_player_props_{variant}" for variant in VARIANT_ORDER}


def player_prop_variant_source(sport: str, variant: str) -> str:
    return f"{str(sport or '').strip().upper()} {VARIANT_LABELS[variant]} Props"


def player_prop_sport_key(sport: str) -> str:
    return f"{str(sport or '').strip().lower()}_player_props"


def player_prop_sport_source(sport: str) -> str:
    return f"{str(sport or '').strip().upper()}PlayerProps"


def _clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def _consensus_gate_disabled() -> bool:
    return os.environ.get("PICKLEDGER_DISABLE_PRECISION_MODEL", "").strip().lower() in {"1", "true", "yes"}


def _consensus_allows_ml_fallback(reason: str) -> bool:
    """ML publication may substitute only when an active policy failed probability gates."""
    blocked_fragments = (
        "has not cleared 70%",
        "consensus calibration below",
        "sample size below publication floor",
        "four-model gate inactive",
        "HRR is restricted to the 1.5 line",
        "missing season/history player profile",
        "price unavailable",
        "invalid selected price",
    )
    normalized = str(reason or "").strip().lower()
    if not normalized.startswith("failed:"):
        return False
    return not any(fragment in normalized for fragment in blocked_fragments)


def _ml_variant_publication_qualified(pick: dict[str, Any]) -> bool:
    """True when variant ML signals clear publication EV thresholds without consensus."""
    if pick.get("market_priced") is not True:
        return False
    try:
        odds = int(safe_float(pick.get("variant_signal_odds") or pick.get("odds")))
    except (TypeError, ValueError):
        return False
    if odds > MAX_PUBLISHED_POSITIVE_ODDS:
        return False
    probability = safe_float(pick.get("variant_signal_probability") or pick.get("ml_probability") or pick.get("probability"))
    edge = safe_float(pick.get("variant_signal_edge") or pick.get("ml_edge"))
    ev = safe_float(pick.get("variant_signal_expected_value") or pick.get("ml_expected_value"))
    if probability < MIN_PUBLISHED_PROBABILITY or edge < MIN_VARIANT_EDGE or ev < MIN_VARIANT_EV:
        return False
    decision, _, _, _, _ = decision_and_stake(
        probability, odds, fair_probability=market_fair_probability(pick)
    )
    return decision in {"BET", "LEAN"}


def _restore_ml_variant_publication(pick: dict[str, Any], *, consensus_reason: str) -> dict[str, Any]:
    selection = str(pick.get("variant_signal_selection") or pick.get("selection") or "Over")
    probability = _clamp(safe_float(pick.get("variant_signal_probability") or pick.get("ml_probability") or pick.get("probability"), 0.5))
    try:
        odds = int(safe_float(pick.get("variant_signal_odds") or pick.get("odds")))
    except (TypeError, ValueError):
        odds = int(safe_float(pick.get("odds")) or -110)
    implied = american_implied_probability(odds) or safe_float(pick.get("market_implied_probability"), 0.5)
    decision, edge_pp, full_kelly, quarter_kelly, units = decision_and_stake(
        probability, odds, fair_probability=market_fair_probability(pick, selection)
    )
    edge_fraction = probability - implied
    variant = str(pick.get("model_variant") or "season")
    variant_label = str(pick.get("model_variant_label") or VARIANT_LABELS.get(variant, variant))
    pick.update(
        {
            "selection": selection,
            "odds": odds,
            "market_implied_probability": round(implied, 4),
            "probability": round(probability, 4),
            "ml_probability": round(probability, 4),
            "ml_raw_probability": round(probability, 4),
            "ml_edge": round(edge_fraction, 6),
            "ml_expected_value": round(expected_value(probability, odds), 6),
            "ml_model_active": True,
            "ml_probability_mode": f"{variant}_variant",
            "decision": decision,
            "confidence": (
                "High"
                if probability >= 0.60 and edge_fraction >= 0.06
                else "Medium"
                if probability >= MIN_PUBLISHED_PROBABILITY
                else "Low"
            ),
            "edge": edge_pp,
            "full_kelly": full_kelly,
            "quarter_kelly": quarter_kelly,
            "units": 0.0 if decision == "PASS" else min(units, 1.0),
            "actionability": "market_priced",
            "ml_calibration_excluded": True,
            "reason": (
                f"{pick.get('source')} rates this {selection.lower()} at {probability:.1%} against a "
                f"{implied:.1%} market price using the {variant_label.lower()} signal."
            ),
        }
    )
    pick.update(_market_probability_context(pick, selection))
    pick.setdefault("key_factors", []).insert(
        0,
        f"Consensus gate withheld publication ({consensus_reason}); ML EV thresholds qualified this market.",
    )
    return pick


def _market_probability_context(pick: dict[str, Any], selection: str) -> dict[str, Any]:
    over_implied = american_implied_probability(_market_odds(pick, "Over"))
    under_implied = american_implied_probability(_market_odds(pick, "Under"))
    no_vig_over = None
    no_vig_selected = None
    if over_implied is not None and under_implied is not None and over_implied + under_implied > 0:
        no_vig_over = over_implied / (over_implied + under_implied)
        no_vig_selected = no_vig_over if selection == "Over" else 1.0 - no_vig_over
    selected_implied = over_implied if selection == "Over" else under_implied
    return {
        "selected_side_implied_probability": round(selected_implied, 4) if selected_implied is not None else None,
        "market_no_vig_over_probability": round(no_vig_over, 4) if no_vig_over is not None else None,
        "market_no_vig_selected_probability": round(no_vig_selected, 4) if no_vig_selected is not None else None,
        "closing_line_movement": None,
        "closing_line_source": "not_tracked",
    }


def _variant_fingerprint() -> str:
    bundle = load_consensus_bundle() or {}
    metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
    fingerprint = str(metadata.get("training_fingerprint") or "")
    if not fingerprint:
        fingerprint = hashlib.sha256(VARIANT_VERSION.encode("utf-8")).hexdigest()
    return fingerprint[:16]


def _history_artifact(sport: str) -> dict[str, Any]:
    bundle = load_consensus_bundle() or {}
    artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), dict) else {}
    artifact = artifacts.get(f"{str(sport).upper()}:history")
    return artifact if isinstance(artifact, dict) else {}


def _season_artifact(sport: str) -> dict[str, Any]:
    bundle = load_consensus_bundle() or {}
    artifacts = bundle.get("artifacts") if isinstance(bundle.get("artifacts"), dict) else {}
    artifact = artifacts.get(f"{str(sport).upper()}:season")
    return artifact if isinstance(artifact, dict) else {}


def _prediction(artifact: dict[str, Any], pick: dict[str, Any]) -> dict[str, Any] | None:
    from .consensus import _prediction as consensus_prediction  # noqa: PLC0415

    stat_key = str(pick.get("stat_key") or "")
    if not stat_key or not artifact:
        return None
    return consensus_prediction(artifact, pick, stat_key)


def _profile_rows(pick: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = _history_artifact(str(pick.get("sport") or ""))
    profiles = artifact.get("outcome_profiles") if isinstance(artifact.get("outcome_profiles"), dict) else {}
    sport = str(pick.get("sport") or "").upper()
    athlete_id = pick.get("market_athlete_id") or pick.get("player_id")
    stat_key = pick.get("stat_key")
    rows = profiles.get(outcome_profile_key(sport, athlete_id, stat_key))
    return rows if isinstance(rows, list) else []


def _prior_rows(pick: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    target_date = str(pick.get("date") or "")
    source_rows = rows if rows is not None else _profile_rows(pick)
    return sorted(
        [row for row in source_rows if str(row.get("date") or "") < target_date],
        key=lambda row: (str(row.get("date") or ""), str(row.get("event_id") or "")),
    )


def _hit(value: float, line: float, selection: str) -> bool:
    return value > line if selection == "Over" else value < line


def _hit_rate(
    pick: dict[str, Any],
    selection: str,
    *,
    limit: int | None = None,
    opponent_only: bool = False,
) -> tuple[float | None, int, int]:
    rows = _prior_rows(pick)
    if opponent_only:
        opponent_id = str(pick.get("opponent_id") or "").strip()
        rows = [row for row in rows if opponent_id and str(row.get("opponent_id") or "").strip() == opponent_id]
    if limit:
        rows = rows[-limit:]
    line = safe_float(pick.get("line"))
    actuals = [safe_float(row.get("actual"), float("nan")) for row in rows]
    clean = [value for value in actuals if math.isfinite(value)]
    if not clean:
        return None, 0, 0
    wins = sum(1 for value in clean if _hit(value, line, selection))
    return wins / len(clean), wins, len(clean)


def _market_odds(pick: dict[str, Any], selection: str) -> int | None:
    field = "market_over_odds" if selection == "Over" else "market_under_odds"
    raw = pick.get(field)
    if raw in (None, "") and str(pick.get("selection") or "") == selection:
        raw = pick.get("odds")
    try:
        odds = int(raw)
    except (TypeError, ValueError):
        return None
    return odds if odds else None


def _selection_choices(pick: dict[str, Any], over_probability: float) -> list[tuple[str, float, int, float]]:
    choices: list[tuple[str, float, int, float]] = []
    for selection, probability in (("Over", over_probability), ("Under", 1.0 - over_probability)):
        odds = _market_odds(pick, selection)
        implied = american_implied_probability(odds)
        if odds is None or implied is None:
            continue
        choices.append((selection, _clamp(probability), odds, implied))
    return choices


def _best_market_choice(pick: dict[str, Any], over_probability: float) -> tuple[str, float, int, float] | None:
    choices = _selection_choices(pick, over_probability)
    if not choices:
        return None
    return max(choices, key=lambda row: (row[1] - row[3], expected_value(row[1], row[2]), row[1]))


def _projection_over_probability(projection: float, line: float) -> float:
    sigma = max(0.9, math.sqrt(max(0.5, abs(projection))) * 0.85)
    return normal_probability(projection, line, sigma, "Over")


def _all_time_choice(pick: dict[str, Any]) -> tuple[str, float, int, float, list[str]] | None:
    prediction = _prediction(_history_artifact(str(pick.get("sport") or "")), pick)
    notes: list[str] = []
    if prediction and prediction.get("over_probability") is not None:
        over_probability = safe_float(prediction.get("over_probability"), 0.5)
        notes.append(f"History model over probability {over_probability:.1%}")
    elif prediction and prediction.get("projection") is not None:
        projection = safe_float(prediction.get("projection"))
        over_probability = _projection_over_probability(projection, safe_float(pick.get("line")))
        notes.append(f"History model projection {projection:.2f}")
    else:
        over_rate, wins, total = _hit_rate(pick, "Over")
        if over_rate is None:
            return None
        over_probability = over_rate
        notes.append(f"All-time over hit rate {wins}-{total} ({over_rate:.1%})")
    choice = _best_market_choice(pick, over_probability)
    if not choice:
        return None
    selection, probability, odds, implied = choice
    rate, wins, total = _hit_rate(pick, selection)
    if rate is not None:
        notes.append(f"{selection} history hit rate {wins}-{total} ({rate:.1%})")
    return selection, probability, odds, implied, notes


def _season_choice(pick: dict[str, Any]) -> tuple[str, float, int, float, list[str]] | None:
    selection = str(pick.get("selection") or "Over")
    odds = _market_odds(pick, selection)
    implied = american_implied_probability(odds)
    if odds is None or implied is None:
        return None
    probability = safe_float(pick.get("ml_probability") or pick.get("probability"), 0.5)
    season_prediction = _prediction(_season_artifact(str(pick.get("sport") or "")), pick)
    notes = [f"Current-season ML probability {probability:.1%}"]
    if season_prediction and season_prediction.get("over_probability") is not None:
        over_probability = safe_float(season_prediction.get("over_probability"), 0.5)
        side_probability = over_probability if selection == "Over" else 1.0 - over_probability
        probability = (probability * 0.55) + (side_probability * 0.45)
        notes.append(f"Season artifact {selection.lower()} probability {side_probability:.1%}")
    return selection, _clamp(probability), odds, implied, notes


def _hot_choice(pick: dict[str, Any]) -> tuple[str, float, int, float, list[str]] | None:
    choices: list[tuple[str, float, int, float, int, int]] = []
    for selection in ("Over", "Under"):
        odds = _market_odds(pick, selection)
        implied = american_implied_probability(odds)
        if odds is None or implied is None:
            continue
        rate, wins, total = _hit_rate(pick, selection, limit=10)
        if rate is None or total < 3 or rate < 0.50:
            continue
        probability = (wins + 1.0) / (total + 2.0)
        choices.append((selection, _clamp(probability), odds, implied, wins, total))
    if not choices:
        return None
    selection, probability, odds, implied, wins, total = max(
        choices,
        key=lambda row: (row[4] / row[5], row[1] - row[3], expected_value(row[1], row[2])),
    )
    rate = wins / total
    notes = [
        f"Last-10 hit rate {wins}-{total} ({rate:.1%}) for {selection.lower()} {safe_float(pick.get('line')):.1f}",
        f"Hot model requires at least 50% over the recent sample",
    ]
    return selection, probability, odds, implied, notes


def _h2h_hits_over_probability(pick: dict[str, Any]) -> tuple[float | None, str | None]:
    if str(pick.get("stat_key") or "") != "hits":
        return None, None
    h2h = pick.get("h2h") if isinstance(pick.get("h2h"), dict) else {}
    at_bats = int(safe_float(h2h.get("at_bats"))) if h2h else 0
    hits = int(safe_float(h2h.get("hits"))) if h2h else 0
    if at_bats < 3:
        return None, None
    average = hits / at_bats
    expected_at_bats = 4.1
    line = safe_float(pick.get("line"))
    threshold = max(1, int(math.floor(line)) + 1)
    probability = 0.0
    trials = max(1, int(round(expected_at_bats)))
    p = _clamp(average, 0.03, 0.62)
    for successes in range(threshold, trials + 1):
        probability += math.comb(trials, successes) * (p ** successes) * ((1.0 - p) ** (trials - successes))
    return _clamp(probability), f"Batter-vs-pitcher H2H {hits}-for-{at_bats} ({average:.3f})"


def _matchup_choice(pick: dict[str, Any]) -> tuple[str, float, int, float, list[str]] | None:
    notes: list[str] = []
    opponent_rate, opponent_wins, opponent_total = _hit_rate(pick, "Over", opponent_only=True)
    if opponent_rate is not None and opponent_total >= 2:
        over_probability = (opponent_wins + 1.0) / (opponent_total + 2.0)
        notes.append(f"Opponent H2H over hit rate {opponent_wins}-{opponent_total} ({opponent_rate:.1%})")
    else:
        h2h_probability, h2h_note = _h2h_hits_over_probability(pick)
        if h2h_probability is not None:
            over_probability = h2h_probability
            notes.append(str(h2h_note))
        else:
            selection = str(pick.get("selection") or "Over")
            base_probability = safe_float(pick.get("ml_probability") or pick.get("probability"), 0.5)
            matchup_factor = safe_float(pick.get("matchup_factor"), 1.0)
            if matchup_factor == 0:
                matchup_factor = safe_float(pick.get("pitch_type_factor"), 1.0)
            if matchup_factor == 0:
                matchup_factor = safe_float(pick.get("h2h_adjustment"), 1.0)
            over_probability = base_probability if selection == "Over" else 1.0 - base_probability
            over_probability = _clamp(over_probability + ((matchup_factor - 1.0) * 0.85))
            notes.append(f"Current matchup factor {matchup_factor:.3f}")
    for field in ("matchup_notes",):
        values = pick.get(field)
        if isinstance(values, list):
            notes.extend(str(value) for value in values[:3])
    if pick.get("opponent_lineup_strikeout_rate") is not None:
        notes.append(f"Opponent lineup K rate {safe_float(pick.get('opponent_lineup_strikeout_rate')):.1%}")
    choice = _best_market_choice(pick, over_probability)
    if not choice:
        return None
    selection, probability, odds, implied = choice
    rate, wins, total = _hit_rate(pick, selection, opponent_only=True)
    if rate is not None and total:
        notes.append(f"{selection} H2H record vs opponent {wins}-{total} ({rate:.1%})")
    return selection, probability, odds, implied, notes


def _choice_for_variant(pick: dict[str, Any], variant: str) -> tuple[str, float, int, float, list[str]] | None:
    if variant == "season":
        return _season_choice(pick)
    if variant == "all_time":
        return _all_time_choice(pick)
    if variant == "hot_l10":
        return _hot_choice(pick)
    if variant == "matchup_h2h":
        return _matchup_choice(pick)
    return None


def _clean_variant_fields(pick: dict[str, Any]) -> None:
    for key in list(pick):
        if key.startswith("consensus_") or key.startswith("precision_"):
            pick.pop(key, None)


def _variant_pick(
    base: dict[str, Any],
    *,
    model_key: str,
    variant: str,
    selection: str,
    probability: float,
    odds: int,
    implied: float,
    notes: list[str],
) -> dict[str, Any]:
    sport = str(base.get("sport") or "").upper()
    pick = copy.deepcopy(base)
    _clean_variant_fields(pick)
    line = safe_float(pick.get("line"))
    stat_label = str(pick.get("stat_label") or pick.get("market_type") or pick.get("stat_key") or "").strip()
    player_name = str(pick.get("player_name") or pick.get("player") or "").strip()
    decision, edge_pp, full_kelly, quarter_kelly, units = decision_and_stake(
        probability, odds, fair_probability=market_fair_probability(pick, selection)
    )
    edge_fraction = (probability - implied) if implied is not None else 0.0
    source = player_prop_variant_source(sport, variant)
    fingerprint = _variant_fingerprint()
    rank_epoch = f"{sport}:{VARIANT_VERSION}:{variant}:{fingerprint}"
    variant_label = VARIANT_LABELS[variant]
    pick.update(
        {
            "id": f"{str(base.get('id') or '').strip() or 'pp'}_{variant}",
            "source": source,
            "model_key": model_key,
            "model_variant": variant,
            "model_variant_label": variant_label,
            "scope": "player",
            "selection": selection,
            "pick": f"{player_name} {selection} {line:.1f} {stat_label}",
            "odds": odds,
            "market_implied_probability": round(implied, 4),
            "probability_source": ML_SOURCE,
            "probability": round(_clamp(probability), 4),
            "ml_probability": round(_clamp(probability), 4),
            "ml_raw_probability": round(_clamp(probability), 4),
            "ml_edge": round(edge_fraction, 6),
            "ml_expected_value": round(expected_value(probability, odds), 6),
            "ml_model_active": True,
            "ml_model_version": VARIANT_VERSION,
            "ml_probability_mode": f"{variant}_variant",
            "ml_training_fingerprint": fingerprint,
            "ml_rank_epoch": rank_epoch,
            "ranking_epoch": rank_epoch,
            "model_epoch": rank_epoch,
            "ml_market_family": market_family_for_stat(str(pick.get("stat_key") or "")),
            "decision": decision,
            "confidence": "High" if probability >= 0.60 and edge_fraction >= 0.06 else "Medium" if probability >= 0.54 else "Low",
            "edge": edge_pp,
            "full_kelly": full_kelly,
            "quarter_kelly": quarter_kelly,
            "units": 0.0 if decision == "PASS" else min(units, 1.0),
            "actionability": "market_priced" if pick.get("market_priced") is True else pick.get("actionability"),
            "ml_calibration_excluded": True,
            "research_details": "; ".join(notes),
            "reason": (
                f"{source} rates this {selection.lower()} at {probability:.1%} against a "
                f"{implied:.1%} market price using the {variant_label.lower()} signal."
            ),
            "key_factors": [
                f"{variant_label} model signal",
                *notes,
                *[str(value) for value in (base.get("key_factors") or [])],
            ],
            "result": str(base.get("result") or "pending"),
        }
    )
    if variant == "hot_l10":
        rate, wins, total = _hit_rate(base, selection, limit=10)
        if rate is not None:
            pick["hot_l10_hit_rate"] = round(rate, 4)
            pick["hot_l10_record"] = f"{wins}-{total}"
    if variant == "matchup_h2h":
        rate, wins, total = _hit_rate(base, selection, opponent_only=True)
        if rate is not None and total:
            pick["h2h_hit_rate"] = round(rate, 4)
            pick["h2h_record"] = f"{wins}-{total}"
    return pick


def _apply_consensus_publication_gate(pick: dict[str, Any]) -> dict[str, Any]:
    pick.update(
        {
            "variant_signal_selection": pick.get("selection"),
            "variant_signal_probability": pick.get("probability"),
            "variant_signal_edge": pick.get("ml_edge"),
            "variant_signal_expected_value": pick.get("ml_expected_value"),
            "variant_signal_odds": pick.get("odds"),
        }
    )
    pick.update(_market_probability_context(pick, str(pick.get("selection") or "Over")))
    if _consensus_gate_disabled():
        pick["consensus_required"] = False
        return pick

    result = evaluate_consensus_pick(pick)
    if result.get("required") is not True:
        result = {
            **result,
            "required": True,
            "qualified": False,
            "reason": result.get("reason") or "four-model consensus unavailable",
        }
    reason = str(result.get("reason") or "unknown consensus result")
    qualified = bool(result.get("qualified"))
    pick.update(
        {
            "consensus_required": True,
            "consensus_evaluated": True,
            "consensus_qualified": qualified,
            "precision_required": True,
            "precision_evaluated": True,
            "precision_qualified": qualified,
            "precision_reason": reason,
            "consensus_rejection_reason": None if qualified else reason,
            "consensus_season_probability": result.get("season_probability"),
            "consensus_history_probability": result.get("history_probability"),
            "consensus_season_projection": result.get("season_projection"),
            "consensus_history_projection": result.get("history_projection"),
            "consensus_model_agreement": result.get("agreement"),
            "consensus_score": safe_float(result.get("consensus_score")),
            "consensus_validation_accuracy": result.get("validation_accuracy"),
            "consensus_holdout_accuracy": result.get("holdout_accuracy"),
            "consensus_conservative_validation_accuracy": result.get("conservative_validation_accuracy"),
        }
    )
    if not qualified:
        pick.update(
            {
                "decision": "PASS",
                "units": 0.0,
                "full_kelly": 0.0,
                "quarter_kelly": 0.0,
                "confidence": "Low",
                "actionability": "research_signal",
                "ml_model_active": False,
                "ml_probability_mode": f"{pick.get('model_variant')}_variant_research_only",
                "reason": (
                    f"{pick.get('source')} is research-only: the active four-model consensus gate "
                    f"rejected this signal ({reason})."
                ),
            }
        )
        pick.setdefault("key_factors", []).insert(0, f"Consensus gate rejected publication: {reason}")
        return pick

    selection = str(result.get("selection") or pick.get("selection") or "Over")
    odds = int(result["odds"])
    implied = safe_float(result.get("implied_probability"), american_implied_probability(odds) or 0.0)
    probability = _clamp(safe_float(result.get("probability"), safe_float(pick.get("probability"), 0.5)))
    decision, edge_pp, full_kelly, quarter_kelly, units = decision_and_stake(
        probability, odds, fair_probability=market_fair_probability(pick, selection)
    )
    line = safe_float(pick.get("line"))
    stat_label = str(pick.get("stat_label") or pick.get("market_type") or pick.get("stat_key") or "").strip()
    player_name = str(pick.get("player_name") or pick.get("player") or "").strip()
    model_version = str(result.get("model_version") or pick.get("ml_model_version") or VARIANT_VERSION)
    fingerprint = str(result.get("training_fingerprint") or pick.get("ml_training_fingerprint") or "unfingerprinted")
    rank_epoch = f"{str(pick.get('sport') or '').upper()}:{model_version}:{pick.get('model_variant')}:consensus:{fingerprint[:16]}"
    pick.update(
        {
            "selection": selection,
            "pick": f"{player_name} {selection} {line:.1f} {stat_label}",
            "odds": odds,
            "market_implied_probability": round(implied, 4),
            "probability": round(probability, 4),
            "ml_probability": round(probability, 4),
            "ml_raw_probability": round(probability, 4),
            "ml_edge": round(probability - implied, 6),
            "ml_expected_value": round(expected_value(probability, odds), 6),
            "ml_model_active": True,
            "ml_model_version": model_version,
            "ml_probability_mode": "four_model_consensus_gate",
            "ml_training_fingerprint": fingerprint,
            "ml_rank_epoch": rank_epoch,
            "ranking_epoch": rank_epoch,
            "model_epoch": rank_epoch,
            "decision": decision,
            "confidence": "High" if probability >= 0.58 and probability - implied >= 0.07 else "Medium",
            "edge": edge_pp,
            "full_kelly": full_kelly,
            "quarter_kelly": quarter_kelly,
            "units": 0.0 if decision == "PASS" else min(units, 1.0),
            "actionability": "consensus_qualified",
            "precision_probability": round(probability, 4),
            "reason": (
                f"The active four-model consensus gate qualifies this market at {probability:.1%}; "
                f"the {pick.get('model_variant_label')} variant is retained as a supporting signal."
            ),
        }
    )
    pick.update(_market_probability_context(pick, selection))
    pick.setdefault("key_factors", []).insert(0, "Active four-model consensus gate qualified publication")
    return pick


def _score_sort_key(pick: dict[str, Any]) -> tuple[float, int, float, float, str]:
    decision_rank = {"BET": 0, "LEAN": 1, "PASS": 2}
    return (
        -safe_float(pick.get("ml_expected_value"), -100),
        decision_rank.get(str(pick.get("decision") or ""), 3),
        -safe_float(pick.get("ml_edge"), -100),
        -safe_float(pick.get("ml_probability") or pick.get("probability")),
        str(pick.get("id") or ""),
    )


def _market_identity(pick: dict[str, Any]) -> tuple[str, str, str, str, str, str, float]:
    return (
        str(pick.get("sport") or "").upper(),
        str(pick.get("date") or ""),
        str(pick.get("game_id") or pick.get("event_id") or pick.get("matchup") or ""),
        str(pick.get("player_id") or pick.get("market_athlete_id") or pick.get("player_name") or ""),
        str(pick.get("stat_key") or pick.get("market_type") or pick.get("stat_label") or ""),
        str(pick.get("selection") or ""),
        safe_float(pick.get("line")),
    )


def _game_identity(pick: dict[str, Any]) -> tuple[str, str, str]:
    game = str(
        pick.get("game_id") or pick.get("event_id") or pick.get("matchup") or ""
    ).strip().lower()
    return (
        str(pick.get("sport") or "").strip().upper(),
        str(pick.get("date") or "").strip(),
        game or "unknown-game",
    )


def _select_variant(scored: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    filtered = [
        pick for pick in scored
        if pick.get("market_priced") is True
        and (pick.get("consensus_required") is not True or pick.get("consensus_qualified") is True)
        and (pick.get("precision_required") is not True or pick.get("precision_qualified") is True)
        and str(pick.get("decision") or "") in {"BET", "LEAN"}
        and safe_float(pick.get("ml_probability") or pick.get("probability")) >= 0.52
        and safe_float(pick.get("ml_edge")) >= MIN_VARIANT_EDGE
        and safe_float(pick.get("ml_expected_value")) >= MIN_VARIANT_EV
        and int(safe_float(pick.get("odds"))) <= MAX_PUBLISHED_POSITIVE_ODDS
    ]
    if variant == "hot_l10":
        filtered = [pick for pick in filtered if safe_float(pick.get("hot_l10_hit_rate")) >= 0.50]
    selected: list[dict[str, Any]] = []
    per_player: dict[str, int] = {}
    per_game: dict[tuple[str, str, str], int] = {}
    for pick in sorted(filtered, key=_score_sort_key):
        player_id = str(pick.get("player_id") or pick.get("player_name") or "")
        game_id = _game_identity(pick)
        if per_player.get(player_id, 0) >= MAX_PER_PLAYER:
            continue
        if per_game.get(game_id, 0) >= MAX_VARIANT_PICKS_PER_GAME:
            continue
        selected.append(pick)
        per_player[player_id] = per_player.get(player_id, 0) + 1
        per_game[game_id] = per_game.get(game_id, 0) + 1
    for index, pick in enumerate(selected, start=1):
        pick["ml_rank"] = index
        pick["model_rank"] = index
        pick["rank"] = index
    return selected


def _dedupe_variant_publications(selected_by_variant: dict[str, list[dict[str, Any]]]) -> None:
    winners: dict[tuple[str, str, str, str, str, str, float], tuple[str, tuple[float, int, float, float, str]]] = {}
    for variant in VARIANT_ORDER:
        for pick in selected_by_variant.get(variant, []):
            key = _market_identity(pick)
            score = _score_sort_key(pick)
            current = winners.get(key)
            if current is None or score < current[1]:
                winners[key] = (variant, score)

    for variant in VARIANT_ORDER:
        unique = [
            pick
            for pick in selected_by_variant.get(variant, [])
            if winners.get(_market_identity(pick), ("",))[0] == variant
        ]
        for index, pick in enumerate(unique, start=1):
            pick["ml_rank"] = index
            pick["model_rank"] = index
            pick["rank"] = index
        selected_by_variant[variant] = unique


def _sport_pick_id(pick: dict[str, Any]) -> str:
    existing = str(pick.get("id") or "").strip()
    for variant in VARIANT_ORDER:
        suffix = f"_{variant}"
        if existing.endswith(suffix):
            return f"{existing[:-len(suffix)]}_consensus"
    return f"{existing or 'pp'}_consensus"


def _rank_sport_picks(selected_by_variant: dict[str, list[dict[str, Any]]], sport: str) -> list[dict[str, Any]]:
    winners: dict[tuple[str, str, str, str, str, str, float], dict[str, Any]] = {}
    for variant in VARIANT_ORDER:
        for pick in selected_by_variant.get(variant, []):
            key = _market_identity(pick)
            current = winners.get(key)
            if current is None or _score_sort_key(pick) < _score_sort_key(current):
                winners[key] = pick

    selected: list[dict[str, Any]] = []
    per_player: dict[str, int] = {}
    per_game: dict[tuple[str, str, str], int] = {}
    model_key = player_prop_sport_key(sport)
    source = player_prop_sport_source(sport)
    fingerprint = _variant_fingerprint()
    rank_epoch = f"{sport}:player_props_consensus_v2.0.0:published:{fingerprint}"
    for pick in sorted(winners.values(), key=_score_sort_key):
        player_id = str(pick.get("player_id") or pick.get("player_name") or "")
        game_id = _game_identity(pick)
        if per_player.get(player_id, 0) >= MAX_PER_PLAYER:
            continue
        if per_game.get(game_id, 0) >= MAX_VARIANT_PICKS_PER_GAME:
            continue
        finalized = copy.deepcopy(pick)
        finalized.update(
            {
                "id": _sport_pick_id(finalized),
                "source": source,
                "model_key": model_key,
                "ml_rank_epoch": rank_epoch,
                "ranking_epoch": rank_epoch,
                "model_epoch": rank_epoch,
                "ranking_model": source,
                "published_model": source,
                "supporting_variant": finalized.get("model_variant"),
                "supporting_variant_label": finalized.get("model_variant_label"),
            }
        )
        selected.append(finalized)
        per_player[player_id] = per_player.get(player_id, 0) + 1
        per_game[game_id] = per_game.get(game_id, 0) + 1
    for index, pick in enumerate(selected, start=1):
        pick["ml_rank"] = index
        pick["model_rank"] = index
        pick["rank"] = index
    return selected


def _merge_reason_counts(*counts: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for count in counts:
        for reason, value in count.items():
            merged[reason] = merged.get(reason, 0) + int(value)
    return merged


def _consensus_rejection_diagnostics(scored: list[dict[str, Any]]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    reason_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    for pick in scored:
        if pick.get("consensus_required") is not True or pick.get("consensus_qualified") is True:
            continue
        reason = str(pick.get("consensus_rejection_reason") or pick.get("precision_reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if len(examples) < 12:
            examples.append(
                {
                    "id": pick.get("id"),
                    "player_name": pick.get("player_name"),
                    "stat_key": pick.get("stat_key"),
                    "selection": pick.get("selection"),
                    "line": pick.get("line"),
                    "odds": pick.get("odds"),
                    "reason": reason,
                }
            )
    return reason_counts, examples


def _wnba_3pm_rank_epoch() -> str:
    return f"WNBA3PM:player_props_consensus_v2.0.0:published:{_variant_fingerprint()}"


def _wnba_3pm_pick(base: dict[str, Any]) -> dict[str, Any]:
    pick = copy.deepcopy(base)
    pick_id = str(pick.get("id") or "pp").strip()
    player_name = str(pick.get("player_name") or "").strip()
    line = safe_float(pick.get("line"))
    stat_label = str(pick.get("stat_label") or "3-Point Field Goals")
    selection = str(pick.get("selection") or "Over")
    odds = _market_odds(pick, selection) or int(safe_float(pick.get("odds"), -110) or -110)
    implied = american_implied_probability(odds) or american_implied_probability(-110) or 0.5238
    pick.update(
        {
            "id": f"{pick_id}_wnba_3pm",
            "source": WNBA_3PM_SOURCE,
            "model_key": WNBA_3PM_MODEL_KEY,
            "model_variant": WNBA_3PM_VARIANT,
            "model_variant_label": WNBA_3PM_VARIANT_LABEL,
            "scope": "player",
            "stat_key": "three_pointers_made",
            "stat_label": stat_label,
            "selection": selection,
            "pick": f"{player_name} {selection} {line:.1f} {stat_label}",
            "odds": odds,
            "market_implied_probability": round(implied, 4),
            "market_athlete_id": str(pick.get("market_athlete_id") or pick.get("player_id") or ""),
            "market_over_odds": _market_odds(pick, "Over") or -110,
            "market_under_odds": _market_odds(pick, "Under") or -110,
            "probability_source": ML_SOURCE,
            "ranking_model": WNBA_3PM_SOURCE,
            "published_model": WNBA_3PM_SOURCE,
            "ml_market_family": "3pm",
            "ml_calibration_excluded": True,
            "result": str(pick.get("result") or "pending"),
        }
    )
    pick = _apply_consensus_publication_gate(pick)
    qualified = pick.get("consensus_qualified") is True
    rank_epoch = _wnba_3pm_rank_epoch()
    pick.update(
        {
            "source": WNBA_3PM_SOURCE,
            "model_key": WNBA_3PM_MODEL_KEY,
            "ranking_model": WNBA_3PM_SOURCE,
            "published_model": WNBA_3PM_SOURCE,
            "ml_rank_epoch": rank_epoch,
            "ranking_epoch": rank_epoch,
            "model_epoch": rank_epoch,
            "supporting_variant": WNBA_3PM_VARIANT,
            "supporting_variant_label": WNBA_3PM_VARIANT_LABEL,
        }
    )
    if qualified:
        return pick
    if pick.get("consensus_required") is True:
        pick = _restore_wnba_3pm_relaxed_publication(pick)
        if pick.get("wnba_3pm_relaxed_consensus_gate") is True:
            return pick
    pick.update(
        {
            "decision": "PASS",
            "units": 0.0,
            "full_kelly": 0.0,
            "quarter_kelly": 0.0,
            "confidence": "Low",
            "actionability": "research_signal",
            "ml_model_active": False,
            "ml_probability_mode": "wnba_3pm_consensus_research_only",
            "reason": (
                f"{WNBA_3PM_SOURCE} is research-only until the active season/history consensus gate "
                f"qualifies this 3PM signal ({pick.get('consensus_rejection_reason') or pick.get('precision_reason') or 'pending validation'})."
            ),
        }
    )
    pick.setdefault("key_factors", []).insert(0, "WNBA3PM consensus gate required before BET/LEAN publication")
    return pick


def _restore_wnba_3pm_relaxed_publication(pick: dict[str, Any]) -> dict[str, Any]:
    probability = _clamp(
        safe_float(pick.get("variant_signal_probability") or pick.get("probability") or pick.get("ml_probability"), 0.5)
    )
    if probability < WNBA_3PM_RELAXED_CONSENSUS_FLOOR:
        return pick
    try:
        odds = int(safe_float(pick.get("variant_signal_odds") or pick.get("odds") or -110))
    except (TypeError, ValueError):
        odds = -110
    if odds > MAX_PUBLISHED_POSITIVE_ODDS:
        return pick
    selection = str(pick.get("variant_signal_selection") or pick.get("selection") or "Over")
    decision, edge_pp, full_kelly, quarter_kelly, units = decision_and_stake(
        probability, odds, fair_probability=market_fair_probability(pick, selection)
    )
    if decision not in {"BET", "LEAN"}:
        return pick
    implied = american_implied_probability(odds) or safe_float(pick.get("market_implied_probability"), 0.5)
    line = safe_float(pick.get("line"))
    stat_label = str(pick.get("stat_label") or "3-Point Field Goals")
    player_name = str(pick.get("player_name") or pick.get("player") or "").strip()
    pick.update(
        {
            "selection": selection,
            "pick": f"{player_name} {selection} {line:.1f} {stat_label}",
            "odds": odds,
            "market_implied_probability": round(implied, 4),
            "probability": round(probability, 4),
            "ml_probability": round(probability, 4),
            "ml_raw_probability": round(probability, 4),
            "ml_edge": round(probability - implied, 6),
            "ml_expected_value": round(expected_value(probability, odds), 6),
            "ml_model_active": True,
            "ml_probability_mode": "wnba_3pm_relaxed_consensus_gate",
            "decision": decision,
            "confidence": "High" if probability >= 0.62 else "Medium",
            "edge": edge_pp,
            "full_kelly": full_kelly,
            "quarter_kelly": quarter_kelly,
            "units": 0.0 if decision == "PASS" else min(units, 1.0),
            "actionability": "relaxed_consensus_gate",
            "precision_qualified": False,
            "wnba_3pm_relaxed_consensus_gate": True,
            "wnba_3pm_relaxed_consensus_floor": WNBA_3PM_RELAXED_CONSENSUS_FLOOR,
            "wnba_3pm_consensus_gate_drop": WNBA_3PM_RELAXED_CONSENSUS_GATE_DROP,
            "reason": (
                f"{WNBA_3PM_SOURCE} publishes this in-house 3PM signal at {probability:.1%} after lowering "
                f"the WNBA3PM publication floor to {WNBA_3PM_RELAXED_CONSENSUS_FLOOR:.0%}; "
                f"full consensus remains unqualified ({pick.get('consensus_rejection_reason') or 'pending validation'})."
            ),
        }
    )
    pick.update(_market_probability_context(pick, selection))
    pick.setdefault("key_factors", []).insert(
        0,
        (
            f"WNBA3PM relaxed consensus floor active at "
            f"{WNBA_3PM_RELAXED_CONSENSUS_FLOOR:.0%} ({WNBA_3PM_RELAXED_CONSENSUS_GATE_DROP:.0%} lower)."
        ),
    )
    return pick


def _wnba_3pm_sort_key(pick: dict[str, Any]) -> tuple[int, int, float, float, float, str]:
    decision_rank = {"BET": 0, "LEAN": 1, "PASS": 2}
    return (
        decision_rank.get(str(pick.get("decision") or ""), 3),
        0 if pick.get("consensus_qualified") is True else 1,
        -safe_float(pick.get("ml_expected_value"), -100.0),
        -safe_float(pick.get("probability") or pick.get("ml_probability")),
        -abs(safe_float(pick.get("projection")) - safe_float(pick.get("line"))),
        str(pick.get("id") or ""),
    )


def build_wnba_3pm_bucket(
    *,
    date_iso: str,
    base_model: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw_candidates = [
        pick for pick in (base_model.get("picks") or [])
        if isinstance(pick, dict)
        and str(pick.get("sport") or "").upper() == "WNBA"
        and str(pick.get("stat_key") or "") == "three_pointers_made"
    ]
    scored = [_wnba_3pm_pick(candidate) for candidate in raw_candidates]
    selected: list[dict[str, Any]] = []
    per_player: dict[str, int] = {}
    for pick in sorted(scored, key=_wnba_3pm_sort_key):
        player_id = str(pick.get("player_id") or pick.get("player_name") or "")
        if per_player.get(player_id, 0) >= MAX_PER_PLAYER:
            continue
        selected.append(pick)
        per_player[player_id] = per_player.get(player_id, 0) + 1
        if len(selected) >= MAX_VARIANT_PICKS:
            break
    for index, pick in enumerate(selected, start=1):
        pick["ml_rank"] = index
        pick["model_rank"] = index
        pick["rank"] = index
    rejection_reasons, rejection_examples = _consensus_rejection_diagnostics(scored)
    rejected_count = sum(
        pick.get("consensus_required") is True and pick.get("consensus_qualified") is not True
        for pick in scored
    )
    bucket = {
        "ok": bool(base_model.get("ok", True)),
        "sport": "WNBA",
        "date": date_iso,
        "games": int(base_model.get("games") or 0),
        "picks": selected,
        "errors": list(base_model.get("errors") or []),
        "model": WNBA_3PM_SOURCE,
        "model_key": WNBA_3PM_MODEL_KEY,
        "model_variants": [WNBA_3PM_VARIANT],
        "ranking_epoch": _wnba_3pm_rank_epoch(),
        "method": (
            "WNBA 3PM props using 3PA volume, shrinkage-adjusted 3P%, season/history "
            "profiles, L10 form, venue, opponent, injury, and consensus gates"
        ),
        "candidate_count": len(raw_candidates),
        "scored_count": len(scored),
        "consensus_required": any(pick.get("consensus_required") is True for pick in scored),
        "consensus_rejected_count": rejected_count,
        "consensus_rejection_reasons": rejection_reasons,
        "consensus_rejections": rejection_examples[:12],
        "abstained": bool(raw_candidates and not selected),
        "note": "" if selected else "No WNBA 3PM candidate cleared the model input floor.",
    }
    return {WNBA_3PM_MODEL_KEY: bucket}


def build_variant_buckets(
    *,
    sport: str,
    date_iso: str,
    base_model: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    sport = str(sport or "").upper()
    keys = player_prop_variant_keys(sport)
    raw_candidates = [
        pick for pick in (base_model.get("picks") or [])
        if isinstance(pick, dict) and str(pick.get("sport") or "").upper() == sport
        and not (sport == "WNBA" and str(pick.get("stat_key") or "") == "three_pointers_made")
    ]
    market_candidates = [pick for pick in raw_candidates if pick.get("market_priced") is True]
    candidates = market_candidates or raw_candidates
    scored_by_variant: dict[str, list[dict[str, Any]]] = {}
    selected_by_variant: dict[str, list[dict[str, Any]]] = {}
    for variant in VARIANT_ORDER:
        model_key = keys[variant]
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            choice = _choice_for_variant(candidate, variant)
            if not choice:
                continue
            selection, probability, odds, implied, notes = choice
            scored.append(
                _apply_consensus_publication_gate(
                    _variant_pick(
                        candidate,
                        model_key=model_key,
                        variant=variant,
                        selection=selection,
                        probability=probability,
                        odds=odds,
                        implied=implied,
                        notes=notes,
                    )
                )
            )
        scored_by_variant[variant] = scored
        selected_by_variant[variant] = _select_variant(scored, variant)
    _dedupe_variant_publications(selected_by_variant)
    picks = _rank_sport_picks(selected_by_variant, sport)
    rejection_diagnostics = [
        _consensus_rejection_diagnostics(scored_by_variant[variant])
        for variant in VARIANT_ORDER
    ]
    rejection_reasons = _merge_reason_counts(*(reasons for reasons, _examples in rejection_diagnostics))
    rejection_examples = [
        example
        for _reasons, examples in rejection_diagnostics
        for example in examples
    ][:12]
    scored_count = sum(len(scored_by_variant[variant]) for variant in VARIANT_ORDER)
    rejected_count = sum(
        pick.get("consensus_required") is True and pick.get("consensus_qualified") is not True
        for variant in VARIANT_ORDER
        for pick in scored_by_variant[variant]
    )
    model_key = player_prop_sport_key(sport)
    fingerprint = _variant_fingerprint()
    bucket = {
        "ok": bool(base_model.get("ok", True)),
        "sport": sport,
        "date": date_iso,
        "games": int(base_model.get("games") or 0),
        "picks": picks,
        "errors": list(base_model.get("errors") or []),
        "model": player_prop_sport_source(sport),
        "model_key": model_key,
        "model_variants": list(VARIANT_ORDER),
        "ranking_epoch": f"{sport}:player_props_consensus_v2.0.0:published:{fingerprint}",
        "method": "Consensus-qualified player props using season, history, L10, and matchup signals as supporting inputs",
        "candidate_count": len(candidates),
        "scored_count": scored_count,
        "consensus_required": any(
            pick.get("consensus_required") is True
            for variant in VARIANT_ORDER
            for pick in scored_by_variant[variant]
        ),
        "consensus_rejected_count": rejected_count,
        "consensus_rejection_reasons": rejection_reasons,
        "consensus_rejections": rejection_examples,
        "abstained": bool(candidates and not picks),
        "note": "" if picks else f"No {sport} prop cleared the consensus publication gate.",
    }
    return {model_key: bucket}
