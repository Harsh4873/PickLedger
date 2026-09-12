"""Shared schema, probability, and staking helpers."""

from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo


SOURCE = "PickLedgerPro In-House Player Props"
ODDS = -110
CENTRAL_TZ = ZoneInfo("America/Chicago")


def central_calendar_date(value: Any) -> date | None:
    """Stamp and filter slates on America/Chicago, matching the live site."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone(CENTRAL_TZ).date()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", ".---", "-.--"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def nearest_half(value: float) -> float:
    return round(math.floor(max(0.0, value)) + 0.5, 1)


def normal_probability(projection: float, line: float, sigma: float, selection: str) -> float:
    sigma = max(0.35, sigma)
    over = 0.5 * (1.0 + math.erf((projection - line) / (sigma * math.sqrt(2.0))))
    probability = over if selection == "Over" else 1.0 - over
    return max(0.01, min(0.99, probability))


def american_implied_probability(odds: int | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def kelly(probability: float, odds: int = ODDS) -> tuple[float, float]:
    decimal_profit = 100.0 / abs(odds) if odds < 0 else odds / 100.0
    full = ((decimal_profit * probability) - (1.0 - probability)) / decimal_profit
    full = max(0.0, min(0.20, full))
    return round(full, 4), round(full / 4.0, 4)


def edge_basis_mode() -> str:
    """Gate strictness switch: 'no_vig' (default) lets a verified market fair
    probability raise the edge baseline; 'vigged' is the legacy escape hatch."""
    value = os.environ.get("PICKLEDGER_EDGE_BASIS", "").strip().lower()
    return "vigged" if value == "vigged" else "no_vig"


def _odds_number(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == 0 or -100.0 < number < 100.0:
        return None
    return int(round(number))


def market_fair_probability(pick: dict[str, Any], selection: str | None = None) -> float | None:
    """Verified no-vig probability of the pick's own side.

    Prefers an explicitly stamped value, then devigs a complete captured
    over/under or selected/opposite pair. A single side is never devigged.
    """
    explicit = safe_float(pick.get("market_no_vig_selected_probability"), -1.0)
    if 0.0 < explicit < 1.0:
        return explicit
    side = str(selection or pick.get("selection") or "").strip().lower()
    over = american_implied_probability(_odds_number(pick.get("market_over_odds")))
    under = american_implied_probability(_odds_number(pick.get("market_under_odds")))
    if over is not None and under is not None and side in {"over", "under"}:
        hold = over + under
        if hold > 0:
            fair_over = over / hold
            return fair_over if side == "over" else 1.0 - fair_over
    selected = american_implied_probability(_odds_number(pick.get("selected_odds")))
    opposite = american_implied_probability(_odds_number(pick.get("opposite_odds")))
    if selected is not None and opposite is not None:
        hold = selected + opposite
        if hold > 0:
            return selected / hold
    return None


def decision_and_stake(
    probability: float,
    odds: int | None = ODDS,
    fair_probability: float | None = None,
) -> tuple[str, float | None, float, float, float]:
    implied = american_implied_probability(odds)
    if implied is None:
        return "PASS", None, 0.0, 0.0, 0.0
    baseline = implied
    if (
        fair_probability is not None
        and 0.0 < fair_probability < 1.0
        and edge_basis_mode() == "no_vig"
    ):
        # The verified fair probability can only raise the bar. With a real
        # executable price the vigged implied is the EV breakeven and already
        # exceeds fair; when the price was assumed (e.g. a -110 default) the
        # captured market keeps a soft assumption from minting phantom edge.
        baseline = max(implied, fair_probability)
    edge_pp = (probability - baseline) * 100.0
    if edge_pp >= 7.0:
        decision = "BET"
    elif edge_pp >= 3.0:
        decision = "LEAN"
    else:
        decision = "PASS"
    full, quarter = kelly(probability, odds)
    units = 0.0 if decision == "PASS" else round(min(2.0, quarter * 100.0), 2)
    return decision, round(edge_pp, 2), full, quarter, units


def confidence_label(probability: float) -> str:
    if probability >= 0.62:
        return "High"
    if probability >= 0.56:
        return "Medium"
    return "Low"


def stable_id(
    sport: str,
    date_iso: str,
    game_id: str,
    player_id: str,
    stat_key: str,
    selection: str,
    line: float,
) -> str:
    raw = "|".join(
        [sport.lower(), date_iso, game_id, player_id, stat_key, selection.lower(), f"{line:.1f}"]
    )
    return f"pp_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def build_pick(
    *,
    sport: str,
    date_iso: str,
    game_id: str,
    away_team: str,
    home_team: str,
    start_time: str,
    player_id: str,
    player_name: str,
    team: str,
    opponent: str,
    stat_key: str,
    stat_label: str,
    selection: str,
    line: float,
    projection: float,
    probability: float,
    reason: str,
    key_factors: list[str],
    odds: int | None = ODDS,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fair_probability = market_fair_probability(extra or {}, selection)
    decision, edge, full_kelly, quarter_kelly, units = decision_and_stake(
        probability, odds, fair_probability=fair_probability
    )
    market_implied = american_implied_probability(odds)
    matchup = f"{away_team} @ {home_team}"
    payload: dict[str, Any] = {
        "id": stable_id(sport, date_iso, game_id, player_id, stat_key, selection, line),
        "source": SOURCE,
        "scope": "player",
        "sport": sport,
        "date": date_iso,
        "matchup": matchup,
        "away_team": away_team,
        "home_team": home_team,
        "start_time": start_time,
        "player_name": player_name,
        "team": team,
        "opponent": opponent,
        "stat_key": stat_key,
        "stat_label": stat_label,
        "selection": selection,
        "line": round(line, 1),
        "pick": f"{player_name} {selection} {line:.1f} {stat_label}",
        "projection": round(projection, 2),
        "probability": round(probability, 4),
        "confidence": confidence_label(probability),
        "edge": edge,
        "decision": decision,
        "odds": odds,
        "market_implied_probability": round(market_implied, 4) if market_implied is not None else None,
        "units": units,
        "full_kelly": full_kelly,
        "quarter_kelly": quarter_kelly,
        "edge_basis": "no_vig" if fair_probability is not None else "vigged",
        "reason": reason,
        "key_factors": key_factors,
        "result": "pending",
    }
    if extra:
        payload.update(extra)
    return payload
