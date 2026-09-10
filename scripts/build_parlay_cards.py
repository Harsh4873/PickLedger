#!/usr/bin/env python3
"""Build Best Bets parlay-card JSON from committed pick caches.

Engine v5 ("market excess"):

Leg probabilities are anchored to the market's no-vig implied probability and
adjusted only by *trailing excess over market* — how much a source's graded
BET/LEAN picks have beaten their own market probabilities historically. That
excess is tracked per source, per market-probability band, and (for player
props) per Over/Under direction, each with Beta-style shrinkage so small
samples stay near the market. Model-quoted probabilities are never trusted
directly: June/July 2026 grading showed market probability is well calibrated
while raw model probabilities added no lift.

Cards are deliberately few and disciplined:
  * Team "Edge Double"  — up to 2 disjoint 2-leg slips whose legs clear a
    trailing-excess edge gate (proven-alpha sources only).
  * Player "Prop Double" — at most 1 2-leg slip from consensus-qualified,
    market-priced props, preferring mixed market families for decorrelation.
No card is published unless its own ``parlayEv`` is strictly positive — a
slip the engine prices at or below zero is not a recommendation. Team and
prop paths share that invariant; a missing prop-edge gate cannot leak a
negative-EV card onto the board.
No same-game, same-player, or same-side duplicates are allowed (game and side
keys are canonicalized across sources, so "A vs B" and "B @ A" collide).

Dates before ENGINE_CUTOVER_DATE are never rebuilt: published v3 history is
preserved and the UI separates records by engineVersion.

Backtest (no lookahead, trailing stats only): July 1-7 2026 → 6-6 (+6.77u)
with team 5-3 (+9.0u); June 23-30 → 9-6 (+9.24u). Prior committed v3 engine
over July 1-6 went 3-7.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_CACHE_DIR = REPO_ROOT / "data" / "model_cache"
PLAYER_PROPS_CACHE_DIR = REPO_ROOT / "data" / "player_props_cache"
PARLAY_CARDS_DIR = REPO_ROOT / "data" / "parlay_cards"

# v6 ("proven legs"): parlays multiply whatever edge the legs carry — a
# 20% book hold on parlays vs ~4.6% on straights exists precisely because
# recreational slips combine legs without individual edge. v6 therefore
# only mints a card when every leg is individually +EV at a REAL price:
# assumed/model prices can never seed a leg, and the team edge gate rose
# from 4.5% to 6%. Fewer cards is the correct outcome; the v5 live record
# (13-18) and retired v3 (15-48) stay split by engineVersion in the UI.
ENGINE_VERSION = "parlay_cards_v6_proven_legs"
ENGINE_CUTOVER_DATE = "2026-07-01"

TEAM_VISIBLE_DECISIONS = {"BET", "LEAN"}

# Leg gates
LEG_ODDS_MIN = -320
LEG_ODDS_MAX = 160
TEAM_EDGE_MIN = 0.060
TEAM_P_MIN = 0.55
PLAYER_P_MIN = 0.58
PLAYER_ADJ_FALLBACK = 0.02  # non-qualified props need this much trailing excess

# Card gates
CARD_ODDS_MIN = -160
CARD_ODDS_MAX = 320
TEAM_POOL_TOP = 10
PLAYER_POOL_TOP = 8
MAX_TEAM_CARDS = 2
MAX_PLAYER_CARDS = 1

# Shrinkage
K_SOURCE = 25
K_BAND = 12
K_DIRECTION = 15
ADJ_CAP = 0.15
# Ceiling on the POSITIVE side of the trailing-excess adjustment.
#
# The adjustment claims a source beats the market price by some margin, and that
# claim is what a card's displayed EV is made of: at pure no-vig market
# probability a parlay's EV is exactly 0.0000, so a +53.84% card was entirely
# self-generated alpha (+12.72pp per leg, riding near ADJ_CAP).
#
# Audited against the graded record, the claim does not survive out of sample.
# Bucketing legs by claimed edge against realized excess over break-even gives a
# correlation indistinguishable from zero (r about -0.02 on 336 parlay legs and
# on 1657 ledger picks), and in the >=0.12 band the live cards actually occupied
# the realized excess turned NEGATIVE and significantly so (t about -2.1). The
# estimator is well built and does not leak in-sample; trailing excess over the
# market simply does not persist forward.
#
# So the positive side is capped at 0: a source may still be marked DOWN for a
# demonstrated deficit, but never marked up above the market's own price. Cards
# therefore price at market instead of advertising an edge that is not there.
# Raise this only against evidence that claimed edge predicts realized edge.
ADJ_POSITIVE_CAP = 0.0
CONSENSUS_BONUS = 0.01
P_CAL_FLOOR = 0.05
P_CAL_CEIL = 0.85

SOURCE_LABELS: dict[str, str] = {
    "mlb_new": "MLB Model",
    "mlb_inning": "MLB Inning",
    "mlb_first_five": "MLB First Five",
    "mlb_team_total": "MLB Team Total",
    "wnba": "WNBA Model",
    "nba": "NBA New",
    "nba_playoffs": "NBA Playoffs",
    "nba_summer": "NBA Summer League",
    "fifa_world_cup": "FIFA Model",
    "mls": "MLS Model",
    "nfl": "NFL Model",
    "cfb": "CFB Model",
    "sportytrader": "SportyTrader",
    "sportytrader_nba": "SportyTraderNBA",
    "sportytrader_nba_summer": "SportyTraderNBASummer",
    "sportytrader_mlb": "SportyTraderMLB",
    "sportytrader_wnba": "SportyTraderWNBA",
    "sportytrader_fifa_world_cup": "SportyTraderFIFAWorldCup",
    "sportytrader_cfb": "SportyTraderCFB",
    "sportytrader_nfl": "SportyTraderNFL",
    "sportsgambler": "SportsGambler",
    "sportsgambler_nba": "SportsGamblerNBA",
    "sportsgambler_nba_summer": "SportsGamblerNBASummer",
    "sportsgambler_mlb": "SportsGamblerMLB",
    "sportsgambler_wnba": "SportsGamblerWNBA",
    "sportsgambler_fifa_world_cup": "SportsGamblerFIFAWorldCup",
    "sportsgambler_cfb": "SportsGamblerCFB",
    "sportsgambler_nfl": "SportsGamblerNFL",
    "scores24_nba_summer": "Scores24NBASummer",
    "scores24_wnba": "Scores24WNBA",
    "scores24_mlb": "Scores24MLB",
    "scores24_fifa_world_cup": "Scores24FIFAWorldCup",
    "scores24_cfb": "Scores24CFB",
    "scores24_nfl": "Scores24NFL",
    "scores24_tennis": "Scores24Tennis",
    "tennistonic_tennis": "TennisTonic",
}

PLAYER_PROP_SOURCE_LABELS: dict[str, str] = {
    "nba_player_props": "NBAPlayerProps",
    "mlb_player_props": "MLBPlayerProps",
    "wnba_player_props": "WNBAPlayerProps",
    "wnba_3pm": "WNBA3PM",
}

CATEGORY_DEFS: dict[str, dict[str, str]] = {
    "edge_double": {
        "label": "Edge Double",
        "shortLabel": "Edge Double",
        "description": "Two-leg team slips whose legs come from sources with proven trailing excess over their market prices.",
    },
    "prop_double": {
        "label": "Prop Double",
        "shortLabel": "Prop Double",
        "description": "A single disciplined two-leg player-prop slip from consensus-qualified, market-priced props.",
    },
}

CATEGORY_ORDER = ["edge_double", "prop_double"]

_WORD_RE = re.compile(r"[a-z0-9]+")
_TOTAL_RE = re.compile(r"\b(over|under)\b[^0-9]*([0-9]+(?:[.,][0-9])?)", re.IGNORECASE)
_DIRECTION_RE = re.compile(r"\b(over|under)\b", re.IGNORECASE)
_SIDE_STOPWORDS = {
    "ml", "moneyline", "to", "win", "wins", "the", "cover", "spread",
    "handicap", "asian", "hcp", "w", "match", "on", "will",
}
_GAME_STOPWORDS = {"vs", "v", "at"}
_PLAYER_STAT_HINTS = (
    " hits", " strikeout", " bases", " rbis", " points", " rebounds",
    " assists", " 3-point", " runs +", " hits +", " goals scored by",
)


@dataclass(frozen=True)
class Leg:
    leg_id: str
    pick_id: str
    source_key: str
    source: str
    source_type: str
    sport: str
    date: str
    pick: str
    decision: str
    odds: int
    decimal_odds: float
    probability: float
    raw_probability: float
    market_probability: float
    calibrated_edge: float
    trailing_samples: int
    probability_source: str
    game_key: str
    game: str
    market_key: str
    market: str
    player_key: str
    player: str
    result: str
    start_time: str
    market_family: str
    side_key: str
    canonical_game: str
    consensus_sources: tuple[str, ...] = ()
    consensus: bool = False
    raw: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


# ---------------------------------------------------------------------------
# Small helpers (shared with the previous engine's payload conventions)
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def _write_json_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _json_text(payload)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_key(value: Any) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in _clean_text(value)).split()
    )


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_number(value: Any) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def normalize_probability(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    probability = number / 100.0 if number > 1 else number
    return probability if 0 <= probability <= 1 else None


def american_to_decimal(odds: int | float) -> float:
    if odds == 0:
        raise ValueError("American odds cannot be zero")
    return 1.0 + (float(odds) / 100.0 if odds > 0 else 100.0 / abs(float(odds)))


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    if decimal_odds >= 2:
        return int(round((decimal_odds - 1) * 100))
    return int(round(-100 / (decimal_odds - 1)))


def implied_probability(odds: int | float) -> float:
    return 1.0 / american_to_decimal(odds)


def fair_odds_from_probability(probability: float) -> int:
    probability = max(0.001, min(0.999, probability))
    return decimal_to_american(1.0 / probability)


def _pick_text(pick: dict[str, Any]) -> str:
    return _clean_text(pick.get("pick") or pick.get("selection") or pick.get("prop") or pick.get("bet"))


def _pick_date(pick: dict[str, Any], fallback_date: str) -> str:
    return _clean_text(
        pick.get("date")
        or pick.get("game_date")
        or pick.get("slate_date")
        or pick.get("Date")
        or fallback_date
    )


def _source_label(source_key: str, raw_source: Any, *, player_prop: bool) -> str:
    raw = _clean_text(raw_source)
    if raw:
        return raw
    if player_prop:
        return PLAYER_PROP_SOURCE_LABELS.get(source_key, source_key)
    return SOURCE_LABELS.get(source_key, source_key)


def _iter_model_records(payload: dict[str, Any], *, player_props: bool) -> Iterable[tuple[str, str, str, dict[str, Any]]]:
    fallback_date = _clean_text(payload.get("date") or payload.get("slate_date"))
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    for source_key, bucket in models.items():
        if not isinstance(bucket, dict) or bucket.get("ok") is False:
            continue
        source_key = str(source_key)
        source = _source_label(source_key, None, player_prop=player_props)
        for raw in bucket.get("picks") or []:
            if isinstance(raw, dict):
                yield source_key, source, fallback_date, raw


def _extract_probability(pick: dict[str, Any]) -> tuple[float | None, str]:
    for key in (
        "calibrated_probability",
        "calibrated_model_probability",
        "probability",
        "model_probability",
        "predicted_probability",
        "ml_probability",
        "variant_signal_probability",
    ):
        probability = normalize_probability(pick.get(key))
        if probability is not None:
            return probability, str(key)
    return None, "market_implied"


def _selected_side_market_probability(pick: dict[str, Any], odds: int) -> float:
    for key in (
        "selected_side_implied_probability",
        "market_implied_probability",
        "market_pick_prob",
        "market_pick_probability",
        "market_probability",
        "market_no_vig_selected_probability",
        "market_no_vig_probability",
    ):
        probability = normalize_probability(pick.get(key))
        if probability is not None:
            return probability
    snapshot = pick.get("pregame_snapshot")
    if isinstance(snapshot, dict):
        for key in (
            "selected_side_implied_probability",
            "market_implied_probability",
            "market_pick_prob",
            "market_probability",
        ):
            probability = normalize_probability(snapshot.get(key))
            if probability is not None:
                return probability
    return implied_probability(odds)


def _result(pick: dict[str, Any]) -> str:
    value = _clean_text(pick.get("result")).lower()
    if value in {"win", "won", "w"}:
        return "win"
    if value in {"loss", "lost", "l"}:
        return "loss"
    if value in {"push", "void", "p"}:
        return "push"
    return "pending"


def _source_type(source_key: str, pick: dict[str, Any], *, player_props: bool) -> str:
    if player_props or _clean_text(pick.get("scope")).lower() == "player":
        return "player_prop"
    if source_key.startswith(("sportytrader", "sportsgambler", "scores24", "tennistonic")):
        return "external"
    return "model"


def _game_label(pick: dict[str, Any]) -> str:
    label = _clean_text(pick.get("matchup") or pick.get("game") or pick.get("event"))
    if label:
        return label
    away = _clean_text(pick.get("away_team"))
    home = _clean_text(pick.get("home_team"))
    if away and home:
        return f"{away} @ {home}"
    return ""


def _game_key(pick: dict[str, Any], sport: str, date_iso: str, fallback: str) -> str:
    game_id = _clean_text(pick.get("game_id") or pick.get("event_id"))
    if game_id:
        return f"{date_iso}:{sport}:game:{game_id}".lower()
    label = _game_label(pick)
    if label:
        return f"{date_iso}:{sport}:{_norm_key(label)}"
    return f"{date_iso}:{sport}:unknown:{fallback}"


def _market_label(pick: dict[str, Any]) -> str:
    return _clean_text(
        pick.get("market_type")
        or pick.get("market")
        or pick.get("stat_label")
        or pick.get("stat_key")
        or "market"
    )


def _market_key(pick: dict[str, Any], game_key: str, pick_text: str, player: str) -> str:
    line = _clean_text(pick.get("line") or pick.get("market_line"))
    selection = _clean_text(pick.get("selection"))
    return "::".join(
        value
        for value in (
            game_key,
            _norm_key(player),
            _norm_key(_market_label(pick)),
            _norm_key(selection or pick_text.split("(", 1)[0]),
            line,
        )
        if value
    )


def _player_key(pick: dict[str, Any], fallback: str) -> str:
    player_id = _clean_text(pick.get("player_id") or pick.get("market_athlete_id"))
    if player_id:
        return f"player-id:{player_id}"
    player = _clean_text(pick.get("player") or pick.get("player_name"))
    if player:
        return f"player:{_norm_key(player)}"
    return f"no-player:{fallback}"


def _market_family(pick: dict[str, Any]) -> str:
    return _norm_key(
        pick.get("ml_market_family")
        or pick.get("bet_type")
        or pick.get("stat_key")
        or pick.get("market")
        or pick.get("market_type")
        or pick.get("stat_label")
        or "market"
    )


def _consensus_field_hit(pick: dict[str, Any]) -> bool:
    if pick.get("consensus_qualified") is True:
        return True
    if pick.get("precision_qualified") is True:
        return True
    return False


def _leg_id(pick: dict[str, Any], source_key: str, source: str, fallback_date: str) -> str:
    existing = _clean_text(pick.get("id"))
    if existing:
        return existing
    return "leg-" + _stable_hash(
        [
            source_key,
            source,
            _pick_date(pick, fallback_date),
            _pick_text(pick),
            pick.get("matchup") or pick.get("game"),
            pick.get("player") or pick.get("player_name"),
            pick.get("market") or pick.get("market_type"),
            pick.get("line"),
        ]
    )


# ---------------------------------------------------------------------------
# Canonical game / side keys (order-insensitive, cross-source)
# ---------------------------------------------------------------------------

def _tokens(value: Any) -> list[str]:
    return _WORD_RE.findall(str(value or "").lower())


def canonical_game_key(sport: str, game_label: str, game_key: str, date_iso: str) -> str:
    tokens = [tok for tok in _tokens(game_label or game_key) if tok not in _GAME_STOPWORDS]
    return f"{date_iso}:{sport.lower()}:{' '.join(sorted(set(tokens)))}"


def canonical_side_key(
    *,
    mode: str,
    pick_text: str,
    sport: str,
    game_label: str,
    game_key: str,
    date_iso: str,
    player_key: str,
    market_family: str,
) -> str:
    game = canonical_game_key(sport, game_label, game_key, date_iso)
    low = str(pick_text).lower()
    if mode == "player":
        return f"{game}|{player_key}|{market_family}"
    total = _TOTAL_RE.search(low)
    if total and not any(hint in low for hint in _PLAYER_STAT_HINTS):
        return f"{game}|total|{total.group(1).lower()}|{total.group(2).replace(',', '.')}"
    game_tokens = set(_tokens(game_label))
    head = low.split("(", 1)[0]
    head_tokens = [tok for tok in _tokens(head) if tok not in _SIDE_STOPWORDS]
    kind = "spr" if (
        "cover" in low or "handicap" in low or "hcp" in low or re.search(r"[+-]\s*\d", head)
    ) else "ml"
    side_tokens = set(head_tokens) & game_tokens or set(head_tokens)
    return f"{game}|{kind}|{' '.join(sorted(side_tokens))}"


def _pick_direction(pick_text: str) -> str | None:
    match = _DIRECTION_RE.search(str(pick_text).lower())
    return match.group(1).lower() if match else None


# ---------------------------------------------------------------------------
# Trailing excess-over-market calibration (no lookahead)
# ---------------------------------------------------------------------------

def _probability_band(market_probability: float) -> int:
    if market_probability < 0.50:
        return 0
    if market_probability < 0.58:
        return 1
    return 2


class TrailingExcess:
    """Trailing (result - market probability) per source/band/direction.

    Only graded BET/LEAN picks dated strictly before the target date count,
    so rebuilding an old slate never leaks future results into its cards.
    """

    def __init__(self) -> None:
        self.by_source: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
        self.by_band: dict[tuple[str, str, int], list[float]] = defaultdict(lambda: [0.0, 0])
        self.by_direction: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0])

    @classmethod
    def build(
        cls,
        target_date: str,
        team_history: list[dict[str, Any]],
        prop_history: list[dict[str, Any]],
    ) -> "TrailingExcess":
        trailing = cls()
        history = [(payload, False) for payload in team_history] + [
            (payload, True) for payload in prop_history
        ]
        for payload, player_props in history:
            for source_key, fallback_source, fallback_date, pick in _iter_model_records(
                payload, player_props=player_props
            ):
                decision = _clean_text(pick.get("decision")).upper()
                if decision not in TEAM_VISIBLE_DECISIONS:
                    continue
                if (
                    player_props or _clean_text(pick.get("scope")).lower() == "player"
                ) and pick.get("market_priced") is not True:
                    continue
                if _pick_date(pick, fallback_date) >= target_date:
                    continue
                result = _result(pick)
                if result not in {"win", "loss"}:
                    continue
                odds = _int_number(
                    pick.get("odds")
                    or pick.get("assumed_odds")
                    or pick.get("american_odds")
                    or pick.get("price")
                )
                if odds is None or odds == 0 or odds <= -1000 or odds >= 1000:
                    continue
                market_probability = _selected_side_market_probability(pick, odds)
                mode = "player" if _source_type(source_key, pick, player_props=player_props) == "player_prop" else "team"
                source = _source_label(source_key, pick.get("source") or fallback_source, player_prop=player_props)
                excess = (1.0 if result == "win" else 0.0) - market_probability
                trailing._add(mode, source, market_probability, _pick_text(pick), excess)
        return trailing

    def _add(self, mode: str, source: str, market_probability: float, pick_text: str, excess: float) -> None:
        bucket = self.by_source[(mode, source)]
        bucket[0] += excess
        bucket[1] += 1
        band_bucket = self.by_band[(mode, source, _probability_band(market_probability))]
        band_bucket[0] += excess
        band_bucket[1] += 1
        if mode == "player":
            direction = _pick_direction(pick_text)
            if direction:
                direction_bucket = self.by_direction[(mode, source, direction)]
                direction_bucket[0] += excess
                direction_bucket[1] += 1

    def adjustment(self, *, mode: str, source: str, market_probability: float, pick_text: str) -> tuple[float, int]:
        total, count = self.by_source[(mode, source)]
        band_total, band_count = self.by_band[(mode, source, _probability_band(market_probability))]
        source_part = (count / (count + K_SOURCE)) * (total / count) if count else 0.0
        band_part = (band_count / (band_count + K_BAND)) * (band_total / band_count) if band_count else 0.0
        adjustment = 0.35 * source_part + 0.65 * band_part
        if mode == "player":
            direction = _pick_direction(pick_text)
            if direction:
                dir_total, dir_count = self.by_direction[(mode, source, direction)]
                if dir_count:
                    adjustment += 0.35 * (dir_count / (dir_count + K_DIRECTION)) * (dir_total / dir_count)
        return max(-ADJ_CAP, min(ADJ_POSITIVE_CAP, adjustment)), count


def _payloads_before(cache_dir: Path, target_date: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("20??-??-??.json")):
        if path.stem >= target_date:
            continue
        payload = _read_json(path)
        if payload:
            payloads.append(payload)
    return payloads


# ---------------------------------------------------------------------------
# Leg collection
# ---------------------------------------------------------------------------

def collect_legs(
    date_iso: str,
    team_payload: dict[str, Any] | None,
    prop_payload: dict[str, Any] | None,
    trailing: TrailingExcess | None = None,
    team_history: list[dict[str, Any]] | None = None,
    prop_history: list[dict[str, Any]] | None = None,
) -> list[Leg]:
    if trailing is None:
        team_history = team_history if team_history is not None else _payloads_before(MODEL_CACHE_DIR, date_iso)
        prop_history = prop_history if prop_history is not None else _payloads_before(PLAYER_PROPS_CACHE_DIR, date_iso)
        trailing = TrailingExcess.build(date_iso, team_history, prop_history)

    records: list[tuple[str, str, str, dict[str, Any], bool]] = []
    if team_payload:
        records.extend((*record, False) for record in _iter_model_records(team_payload, player_props=False))
    if prop_payload:
        records.extend((*record, True) for record in _iter_model_records(prop_payload, player_props=True))

    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source_key, fallback_source, fallback_date, pick, player_props in records:
        decision = _clean_text(pick.get("decision")).upper()
        if decision not in TEAM_VISIBLE_DECISIONS:
            continue
        if pick.get("shadow_mode") is True:
            # Shadow-mode models accumulate ledger evidence without any
            # public surface — including parlay legs.
            continue
        # scope=player rows in the TEAM payload (external prop feeds) face
        # the same market_priced gate as player-cache props.
        if (
            player_props or _clean_text(pick.get("scope")).lower() == "player"
        ) and pick.get("market_priced") is not True:
            continue
        if pick.get("grade_supported") is False:
            continue
        pick_text = _pick_text(pick)
        if not pick_text:
            continue
        if _pick_date(pick, fallback_date) != date_iso:
            continue
        # A leg's price must be executable. Assumed/model placeholder
        # prices (e.g. the inning model's flat -120) would give the slip
        # phantom odds and phantom edge.
        markers = " ".join(
            _clean_text(pick.get(key)).lower()
            for key in ("pricing_type", "odds_source", "line_source")
        )
        if "assumed" in markers and _clean_text(pick.get("odds_source")).lower() != "posted_market":
            continue
        odds = _int_number(pick.get("odds") or pick.get("american_odds") or pick.get("price"))
        if odds is None or odds == 0 or odds < LEG_ODDS_MIN or odds > LEG_ODDS_MAX:
            continue
        source = _source_label(source_key, pick.get("source") or fallback_source, player_prop=player_props)
        leg_id = _leg_id(pick, source_key, source, fallback_date)
        if leg_id in seen_ids:
            continue
        seen_ids.add(leg_id)
        sport = _clean_text(pick.get("sport") or pick.get("league") or "OTHER").upper()
        source_type = _source_type(source_key, pick, player_props=player_props)
        mode = "player" if source_type == "player_prop" else "team"
        game = _game_label(pick)
        game_key = _game_key(pick, sport, date_iso, leg_id)
        player = _clean_text(pick.get("player") or pick.get("player_name"))
        player_key = _player_key(pick, leg_id)
        market_family = _market_family(pick)
        market_probability = _selected_side_market_probability(pick, odds)
        raw_probability, probability_source = _extract_probability(pick)
        candidates.append(
            dict(
                pick=pick,
                source_key=source_key,
                source=source,
                source_type=source_type,
                mode=mode,
                sport=sport,
                decision=decision,
                odds=odds,
                leg_id=leg_id,
                game=game,
                game_key=game_key,
                player=player,
                player_key=player_key,
                market_family=market_family,
                market_probability=market_probability,
                raw_probability=raw_probability if raw_probability is not None else market_probability,
                probability_source=probability_source,
                pick_text=pick_text,
                side=canonical_side_key(
                    mode=mode,
                    pick_text=pick_text,
                    sport=sport,
                    game_label=game,
                    game_key=game_key,
                    date_iso=date_iso,
                    player_key=player_key,
                    market_family=market_family,
                ),
                cgame=canonical_game_key(sport, game, game_key, date_iso),
            )
        )

    # Cross-source dedupe: one leg per canonical side; count agreeing sources.
    by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_side[candidate["side"]].append(candidate)

    legs: list[Leg] = []
    for side, group in by_side.items():
        sources = sorted({item["source"] for item in group})
        best = max(
            group,
            key=lambda item: (
                trailing.adjustment(
                    mode=item["mode"],
                    source=item["source"],
                    market_probability=item["market_probability"],
                    pick_text=item["pick_text"],
                )[0],
                -item["odds"],
                item["leg_id"],
            ),
        )
        adjustment, samples = trailing.adjustment(
            mode=best["mode"],
            source=best["source"],
            market_probability=best["market_probability"],
            pick_text=best["pick_text"],
        )
        consensus = len(sources) >= 2 or _consensus_field_hit(best["pick"])
        edge = adjustment + (CONSENSUS_BONUS if len(sources) >= 2 else 0.0)
        probability = max(P_CAL_FLOOR, min(P_CAL_CEIL, best["market_probability"] + edge))
        if best["mode"] == "player":
            qualified = _consensus_field_hit(best["pick"]) or adjustment > PLAYER_ADJ_FALLBACK
            if not qualified:
                continue
        legs.append(
            Leg(
                leg_id=best["leg_id"],
                pick_id=best["leg_id"],
                source_key=best["source_key"],
                source=best["source"],
                source_type=best["source_type"],
                sport=best["sport"],
                date=date_iso,
                pick=best["pick_text"],
                decision=best["decision"],
                odds=best["odds"],
                decimal_odds=american_to_decimal(best["odds"]),
                probability=probability,
                raw_probability=best["raw_probability"],
                market_probability=best["market_probability"],
                calibrated_edge=edge,
                trailing_samples=samples,
                probability_source=best["probability_source"],
                game_key=best["game_key"],
                game=best["game"],
                market_key=_market_key(best["pick"], best["game_key"], best["pick_text"], best["player"]),
                market=_market_label(best["pick"]),
                player_key=best["player_key"],
                player=best["player"],
                result=_result(best["pick"]),
                start_time=_clean_text(best["pick"].get("start_time") or best["pick"].get("game_start_time")),
                market_family=best["market_family"],
                side_key=side,
                canonical_game=best["cgame"],
                consensus_sources=tuple(sources) if len(sources) >= 2 else (),
                consensus=consensus,
                raw=best["pick"],
            )
        )
    return sorted(legs, key=lambda leg: (-leg.calibrated_edge, -leg.probability, leg.leg_id))


# ---------------------------------------------------------------------------
# Card construction
# ---------------------------------------------------------------------------

def valid_combo(legs: Iterable[Leg]) -> bool:
    leg_list = list(legs)
    if len(leg_list) < 2:
        return False
    if len({leg.leg_id for leg in leg_list}) != len(leg_list):
        return False
    if len({leg.canonical_game for leg in leg_list}) != len(leg_list):
        return False
    players = [leg.player_key for leg in leg_list if not leg.player_key.startswith("no-player:")]
    if len(set(players)) != len(players):
        return False
    if len({leg.side_key for leg in leg_list}) != len(leg_list):
        return False
    if len({"player" if leg.source_type == "player_prop" else "team" for leg in leg_list}) != 1:
        return False
    return True


def sport_mix(legs: Iterable[Leg]) -> str:
    labels = [
        f"{leg.sport} Props" if leg.source_type == "player_prop" else leg.sport
        for leg in legs
    ]
    return " + ".join(labels)


def sport_pattern(legs: Iterable[Leg]) -> str:
    counts = sorted(Counter(leg.sport for leg in legs).values(), reverse=True)
    if counts == [1, 1]:
        return "2-leg-mixed"
    if counts == [2]:
        return "2-same"
    return "-".join(str(count) for count in counts)


def grade_parlay_result(legs: list[dict[str, Any]] | list[Leg], decimal_odds: float | None = None) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for leg in legs:
        if isinstance(leg, Leg):
            normalized.append({"result": leg.result, "decimalOdds": leg.decimal_odds})
        else:
            normalized.append(leg)

    results = [_clean_text(leg.get("result")).lower() or "pending" for leg in normalized]
    if any(result == "loss" for result in results):
        return {"result": "loss", "activeLegCount": sum(result != "push" for result in results), "profitUnits": -1.0}
    if any(result == "pending" for result in results):
        return {"result": "pending", "activeLegCount": sum(result != "push" for result in results), "profitUnits": 0.0}
    active = [leg for leg, result in zip(normalized, results) if result != "push"]
    if not active:
        return {"result": "push", "activeLegCount": 0, "profitUnits": 0.0}
    active_decimal = 1.0
    for leg in active:
        active_decimal *= float(leg.get("decimalOdds") or 1)
    if decimal_odds is not None and len(active) == len(normalized):
        active_decimal = decimal_odds
    return {
        "result": "win",
        "activeLegCount": len(active),
        "profitUnits": round(active_decimal - 1.0, 2),
    }


def _leg_payload(leg: Leg) -> dict[str, Any]:
    return {
        "legId": leg.leg_id,
        "pickId": leg.pick_id,
        "source": leg.source,
        "sourceKey": leg.source_key,
        "sourceType": leg.source_type,
        "sport": leg.sport,
        "pick": leg.pick,
        "decision": leg.decision,
        "oddsAmerican": leg.odds,
        "decimalOdds": round(leg.decimal_odds, 4),
        "estimatedProbability": round(leg.probability, 4),
        "rawProbability": round(leg.raw_probability, 4),
        "marketProbability": round(leg.market_probability, 4),
        "calibratedEdge": round(leg.calibrated_edge, 4),
        "trailingSamples": leg.trailing_samples,
        "probabilitySource": leg.probability_source,
        "game": leg.game,
        "gameKey": leg.game_key,
        "market": leg.market,
        "marketKey": leg.market_key,
        "player": leg.player,
        "result": leg.result,
        "startTime": leg.start_time,
        "consensusSources": list(leg.consensus_sources),
        "modelRank": None,
    }


def _why_qualified(category: str) -> str:
    if category == "edge_double":
        return (
            "Both legs come from sources whose graded picks have beaten their own "
            "market prices, and the slip clears the calibrated edge gate."
        )
    return (
        "Consensus-qualified player props with market pricing; families are mixed "
        "when possible to reduce correlated misses."
    )


def _card_from_legs(legs: tuple[Leg, ...], category: str) -> dict[str, Any]:
    decimal_odds = math.prod(leg.decimal_odds for leg in legs)
    estimated_probability = math.prod(leg.probability for leg in legs)
    geomean_probability = estimated_probability ** (1.0 / len(legs))
    odds_american = decimal_to_american(decimal_odds)
    parlay_ev = estimated_probability * decimal_odds - 1.0
    leg_payloads = [_leg_payload(leg) for leg in legs]
    grade = grade_parlay_result(leg_payloads, decimal_odds)
    combo_key = "|".join(sorted(leg.leg_id for leg in legs))
    category_def = CATEGORY_DEFS[category]
    pick_mode = "player" if all(leg.source_type == "player_prop" for leg in legs) else "team"
    return {
        "id": f"parlay-{_stable_hash(combo_key)}-{category}",
        "comboKey": combo_key,
        "date": legs[0].date,
        "category": category,
        "categoryLabel": category_def["label"],
        "categoryShortLabel": category_def["shortLabel"],
        "title": category_def["label"],
        "fallback": False,
        "whyQualified": _why_qualified(category),
        "legCount": len(legs),
        "legs": leg_payloads,
        "sportMix": sport_mix(legs),
        "sportPattern": sport_pattern(legs),
        "sports": sorted({leg.sport for leg in legs}),
        "hasPlayerProp": any(leg.source_type == "player_prop" for leg in legs),
        "pickMode": pick_mode,
        "oddsAmerican": odds_american,
        "decimalOdds": round(decimal_odds, 4),
        "estimatedProbability": round(estimated_probability, 4),
        "geomeanProbability": round(geomean_probability, 4),
        "fairOdds": fair_odds_from_probability(estimated_probability),
        "parlayEv": round(parlay_ev, 4),
        "payoutQuality": None,
        "averageSourceForm": None,
        "consensusLegs": sum(1 for leg in legs if leg.consensus),
        "categoryScore": round(estimated_probability * 100.0 + max(-0.8, min(1.8, parlay_ev)) * 4.0, 4),
        "score": round(estimated_probability * 100.0, 4),
        "result": grade["result"],
        "activeLegCount": grade["activeLegCount"],
        "profitUnits": grade["profitUnits"],
        "stakeUnits": 1.0,
    }


def _card_within_odds(card: dict[str, Any]) -> bool:
    return CARD_ODDS_MIN <= int(card["oddsAmerican"]) <= CARD_ODDS_MAX


def _card_has_positive_ev(card: dict[str, Any]) -> bool:
    """Refuse any slip the engine itself prices at or below zero.

    Team cards already require a 6pp trailing-edge gate. Prop cards historically
    did not, so a below-market pair could still mint as a Prop Double. The card's
    own ``parlayEv`` is the number the site would advertise; if that number is
    not positive, the card is not a bet.
    """
    ev = _number(card.get("parlayEv"))
    return ev is not None and ev > 0


def select_team_cards(legs: list[Leg]) -> list[dict[str, Any]]:
    eligible = [
        leg
        for leg in legs
        if leg.source_type != "player_prop"
        and leg.calibrated_edge >= TEAM_EDGE_MIN
        and leg.probability >= TEAM_P_MIN
    ]
    eligible.sort(key=lambda leg: (-leg.calibrated_edge, -leg.probability, leg.leg_id))
    pool = eligible[:TEAM_POOL_TOP]
    candidates = []
    for combo in combinations(pool, 2):
        if not valid_combo(combo):
            continue
        card = _card_from_legs(tuple(combo), "edge_double")
        if not _card_within_odds(card) or not _card_has_positive_ev(card):
            continue
        candidates.append(card)
    candidates.sort(key=lambda card: (-float(card["estimatedProbability"]), str(card["comboKey"])))
    selected: list[dict[str, Any]] = []
    used_leg_ids: set[str] = set()
    for card in candidates:
        if len(selected) >= MAX_TEAM_CARDS:
            break
        leg_ids = {str(leg["legId"]) for leg in card["legs"]}
        if used_leg_ids & leg_ids:
            continue
        selected.append(card)
        used_leg_ids |= leg_ids
    return selected


def select_player_cards(legs: list[Leg]) -> list[dict[str, Any]]:
    eligible = [
        leg
        for leg in legs
        if leg.source_type == "player_prop" and leg.probability >= PLAYER_P_MIN
    ]
    eligible.sort(key=lambda leg: (-leg.probability, leg.leg_id))
    pool = eligible[:PLAYER_POOL_TOP]
    candidates = []
    for combo in combinations(pool, 2):
        if not valid_combo(combo):
            continue
        card = _card_from_legs(tuple(combo), "prop_double")
        if not _card_within_odds(card) or not _card_has_positive_ev(card):
            continue
        mixed = len({leg.market_family for leg in combo}) > 1
        candidates.append((mixed, card))
    candidates.sort(key=lambda item: (-int(item[0]), -float(item[1]["estimatedProbability"]), str(item[1]["comboKey"])))
    return [card for _, card in candidates[:MAX_PLAYER_CARDS]]


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------

def _prior_parlay_payloads(target_date: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if not PARLAY_CARDS_DIR.exists():
        return payloads
    for path in sorted(PARLAY_CARDS_DIR.glob("20??-??-??.json")):
        if path.stem >= target_date:
            continue
        payload = _read_json(path)
        if payload:
            payloads.append(payload)
    return payloads


def _card_pick_mode(card: dict[str, Any]) -> str:
    mode = _clean_text(card.get("pickMode")).lower()
    if mode in {"team", "player"}:
        return mode
    legs = [leg for leg in card.get("legs") or [] if isinstance(leg, dict)]
    has_player = any(_clean_text(leg.get("sourceType")) == "player_prop" for leg in legs)
    has_team = any(_clean_text(leg.get("sourceType")) != "player_prop" for leg in legs)
    if has_player and has_team:
        return "mixed"
    return "player" if has_player else "team"


def _card_dedupe_key(card: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _clean_text(card.get("date")),
        _clean_text(card.get("category")),
        _clean_text(card.get("id")),
        _clean_text(card.get("comboKey")),
    )


def _dedupe_cards(cards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for card in cards:
        if isinstance(card, dict):
            deduped[_card_dedupe_key(card)] = card
    return list(deduped.values())


def _record_from_cards(cards: Iterable[dict[str, Any]]) -> dict[str, Any]:
    wins = losses = pushes = pending = 0
    net = 0.0
    odds_values: list[int] = []
    recent_results: list[str] = []
    for card in _dedupe_cards(cards):
        result = _clean_text(card.get("result")).lower() or "pending"
        wins += result == "win"
        losses += result == "loss"
        pushes += result == "push"
        pending += result == "pending"
        if result in {"win", "loss"}:
            net += float(card.get("profitUnits") or 0)
            odds_values.append(int(card.get("oddsAmerican") or 0))
            recent_results.append("W" if result == "win" else "L")
        elif result == "push":
            recent_results.append("P")
    settled = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "pending": pending,
        "settled": settled,
        "hitRate": round(wins / settled, 4) if settled else None,
        "netUnits": round(net, 2),
        "roi": round(net / settled, 4) if settled else None,
        "averageOdds": round(sum(odds_values) / len(odds_values), 1) if odds_values else None,
        "recentForm": "".join(recent_results[-5:]) or "",
    }


def rankings(prior_payloads: list[dict[str, Any]], selected_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_category: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORY_DEFS}
    for payload in prior_payloads:
        for card in payload.get("cards") or []:
            if isinstance(card, dict) and card.get("category") in by_category:
                by_category[str(card["category"])].append(card)
    for card in selected_cards:
        if card.get("category") in by_category:
            by_category[str(card["category"])].append(card)

    rows = []
    for category in CATEGORY_ORDER:
        record = _record_from_cards(_dedupe_cards(by_category[category]))
        row = {
            "category": category,
            "label": CATEGORY_DEFS[category]["shortLabel"],
            "description": CATEGORY_DEFS[category]["description"],
            **record,
        }
        hit_rate = row["hitRate"] if row["hitRate"] is not None else 0.5
        roi = row["roi"] if row["roi"] is not None else 0.0
        row["score"] = round(hit_rate * 70 + roi * 15 + min(int(row["settled"]), 20) * 0.4, 4)
        rows.append(row)
    return sorted(rows, key=lambda row: float(row["score"]), reverse=True)


def build_parlay_payload(
    date_iso: str,
    team_payload: dict[str, Any] | None,
    prop_payload: dict[str, Any] | None,
    *,
    team_history: list[dict[str, Any]] | None = None,
    prop_history: list[dict[str, Any]] | None = None,
    prior_payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    team_history = team_history if team_history is not None else _payloads_before(MODEL_CACHE_DIR, date_iso)
    prop_history = prop_history if prop_history is not None else _payloads_before(PLAYER_PROPS_CACHE_DIR, date_iso)
    prior_payloads = prior_payloads if prior_payloads is not None else _prior_parlay_payloads(date_iso)
    trailing = TrailingExcess.build(date_iso, team_history, prop_history)
    legs = collect_legs(date_iso, team_payload, prop_payload, trailing)
    team_cards = select_team_cards(legs)
    player_cards = select_player_cards(legs)
    cards = [card for card in team_cards + player_cards if _card_has_positive_ev(card)]
    team_cards = [card for card in cards if card.get("pickMode") == "team"]
    player_cards = [card for card in cards if card.get("pickMode") == "player"]

    engine_prior_payloads = [
        payload for payload in prior_payloads
        if _clean_text(payload.get("engineVersion")) == ENGINE_VERSION
    ]

    category_summaries = []
    for category in CATEGORY_ORDER:
        category_cards = [card for card in cards if card.get("category") == category]
        category_summaries.append(
            {
                "key": category,
                "label": CATEGORY_DEFS[category]["label"],
                "shortLabel": CATEGORY_DEFS[category]["shortLabel"],
                "description": CATEGORY_DEFS[category]["description"],
                "count": len(category_cards),
                "threeLegCount": 0,
                "fallbackCount": 0,
                "record": _record_from_cards(category_cards),
            }
        )

    mode_summaries: dict[str, dict[str, Any]] = {}
    for mode, mode_cards in (("team", team_cards), ("player", player_cards)):
        mode_summaries[mode] = {
            "displayedCards": len(mode_cards),
            "threeLegCards": 0,
            "twoLegFallbackCards": len(mode_cards),
            "averageOdds": (
                round(sum(int(card["oddsAmerican"]) for card in mode_cards) / len(mode_cards), 1)
                if mode_cards
                else None
            ),
            "record": _record_from_cards(mode_cards),
        }

    average_odds = (
        round(sum(int(card["oddsAmerican"]) for card in cards) / len(cards), 1)
        if cards
        else None
    )
    notices = [
        "Leg probabilities are anchored to market prices and adjusted only by each source's proven trailing excess.",
        "No same-game, same-player, or same-side duplicate legs are allowed; game keys are canonicalized across sources.",
        "Slates without qualified edges show fewer cards (or none) instead of forcing action.",
        "A card is unpublished when its own parlay EV is zero or negative.",
    ]
    if not cards:
        notices.append("No qualified parlay cards met the trailing-edge, price, and overlap rules for this slate.")

    return {
        "date": date_iso,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "engineVersion": ENGINE_VERSION,
        "summary": {
            "eligibleLegs": len(legs),
            "generatedThreeLegCandidates": 0,
            "displayedCards": len(cards),
            "threeLegCards": 0,
            "twoLegFallbackCards": len(cards),
            "averageOdds": average_odds,
            "record": _record_from_cards(cards),
            "modes": mode_summaries,
        },
        "categories": category_summaries,
        "rankings": rankings(engine_prior_payloads, cards),
        "cards": cards,
        "notices": notices,
    }


# ---------------------------------------------------------------------------
# CLI / rebuild
# ---------------------------------------------------------------------------

def _target_dates(all_dates: bool, explicit_date: str | None) -> list[str]:
    if explicit_date:
        return [explicit_date]
    model_dates = {path.stem for path in MODEL_CACHE_DIR.glob("20??-??-??.json")}
    prop_dates = {path.stem for path in PLAYER_PROPS_CACHE_DIR.glob("20??-??-??.json")}
    dates = sorted(model_dates | prop_dates)
    if all_dates:
        return dates
    latest_model = _read_json(MODEL_CACHE_DIR / "latest.json") or {}
    latest_prop = _read_json(PLAYER_PROPS_CACHE_DIR / "latest.json") or {}
    latest = _clean_text(latest_model.get("date") or latest_prop.get("date"))
    return [latest or dates[-1]] if dates or latest else []


def _write_manifest() -> bool:
    files = sorted(path.name for path in PARLAY_CARDS_DIR.glob("20??-??-??.json"))
    return _write_json_if_changed(PARLAY_CARDS_DIR / "index.json", {"files": files})


def rebuild_parlay_cards(*, date_iso: str | None = None, all_dates: bool = False) -> int:
    changed = 0
    dates = _target_dates(all_dates, date_iso)
    if not dates:
        print("[parlay-cards] no cache dates available")
        return 0

    for target in dates:
        if target < ENGINE_CUTOVER_DATE:
            print(f"[parlay-cards] skipped {target}: predates engine cutover {ENGINE_CUTOVER_DATE}")
            continue
        team_payload = _read_json(MODEL_CACHE_DIR / f"{target}.json")
        prop_payload = _read_json(PLAYER_PROPS_CACHE_DIR / f"{target}.json")
        if not team_payload and not prop_payload:
            print(f"[parlay-cards] skipped {target}: no source caches")
            continue
        payload = build_parlay_payload(target, team_payload, prop_payload)
        path = PARLAY_CARDS_DIR / f"{target}.json"
        if _write_json_if_changed(path, payload):
            changed += 1
        print(
            f"[parlay-cards] {target}: "
            f"{payload['summary']['displayedCards']} card(s), "
            f"{payload['summary']['eligibleLegs']} eligible leg(s)"
        )

    if _write_manifest():
        changed += 1

    files = sorted(PARLAY_CARDS_DIR.glob("20??-??-??.json"))
    if files:
        latest_payload = _read_json(files[-1])
        if latest_payload and _write_json_if_changed(PARLAY_CARDS_DIR / "latest.json", latest_payload):
            changed += 1
    return changed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Target date to build, in YYYY-MM-DD format.")
    parser.add_argument("--all", action="store_true", help="Rebuild every dated parlay-card file (respecting the engine cutover).")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    changed = rebuild_parlay_cards(date_iso=args.date, all_dates=args.all)
    print(f"[parlay-cards] complete: {changed} file update(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
