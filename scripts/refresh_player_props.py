#!/usr/bin/env python3
"""Generate isolated in-house player-props cache artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "player_props_cache"
sys.path.insert(0, str(REPO_ROOT))

from scripts.site_upcheck import _mlb_player_props_documented_abstention as documented_abstention
from player_props import generate_payload  # noqa: E402
from scripts.merge_player_props_cache_payload import (  # noqa: E402
    HARD_PLAYER_PROP_MODEL_KEYS,
    PUBLIC_PLAYER_PROP_MODEL_KEYS,
    SOFT_PLAYER_PROP_MODEL_KEYS,
)
from scripts.pick_calibration import apply_calibration_to_payload  # noqa: E402


def _default_central_date() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).date().isoformat()


def _target_date(raw: str | None) -> str:
    value = str(raw or "").strip()
    return value or _default_central_date()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh direct-API player-props cache.")
    default_date = _default_central_date()
    parser.add_argument("--date", default=default_date, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _scheduled_game_count(bucket: Any, *, target_date: str | None = None) -> int:
    if not isinstance(bucket, dict):
        return 0
    games = bucket.get("games")
    if isinstance(games, list):
        return sum(1 for row in games if isinstance(row, dict) and _row_matches_target_date(row, target_date))
    try:
        return max(0, int(games or 0))
    except (TypeError, ValueError):
        return 0


def _official_mlb_scheduled_games(target_date: str) -> int:
    dated = _read_json(REPO_ROOT / "data" / "model_cache" / f"{target_date}.json")
    latest = _read_json(REPO_ROOT / "data" / "model_cache" / "latest.json")
    payload = dated if str(dated.get("date") or "") == target_date else latest
    if str(payload.get("date") or "") != target_date:
        return 0
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    return max(
        (
            _scheduled_game_count(models.get(key), target_date=target_date)
            for key in ("mlb_new", "mlb_inning", "mlb_first_five")
        ),
        default=0,
    )


def _publication_contract_errors(
    models: dict[str, Any],
    *,
    official_mlb_games: int,
    target_date: str | None = None,
) -> list[str]:
    errors: list[str] = []
    for model_name in sorted(HARD_PLAYER_PROP_MODEL_KEYS):
        model = models.get(model_name)
        if not isinstance(model, dict):
            errors.append(f"required bucket {model_name} is missing")
            continue
        if model.get("ok") is not True:
            errors.append(f"required bucket {model_name} is not ok")
    for model_name in sorted(SOFT_PLAYER_PROP_MODEL_KEYS):
        model = models.get(model_name)
        if not isinstance(model, dict):
            errors.append(f"required bucket {model_name} is missing")
            continue
        # Football slates soft-fail: an empty or unpriced day is valid, and an
        # upstream outage must not block MLB/NBA/WNBA publication.
        if model.get("ok") is not True:
            continue
    mlb = models.get("mlb_player_props") if isinstance(models.get("mlb_player_props"), dict) else {}
    scheduled_games = max(_scheduled_game_count(mlb, target_date=target_date), official_mlb_games)
    if scheduled_games > 0 and not (mlb.get("picks") or []) and not documented_abstention(mlb):
        errors.append(f"scheduled MLB games ({scheduled_games}) have zero published picks")
    return errors


def main() -> int:
    args = _parse_args()
    target_date = _target_date(args.date)
    payload = apply_calibration_to_payload(generate_payload(target_date))
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    payload = {
        **payload,
        "models": {
            key: bucket
            for key, bucket in models.items()
            if key in PUBLIC_PLAYER_PROP_MODEL_KEYS
        },
    }
    output_dir = args.output_dir.resolve()
    _write_json(output_dir / f"{target_date}.json", payload)
    _write_json(output_dir / "latest.json", payload)
    files = sorted(path.name for path in output_dir.glob("20??-??-??.json"))
    _write_json(output_dir / "index.json", {"files": files})

    contract_errors = _publication_contract_errors(
        payload["models"],
        official_mlb_games=_official_mlb_scheduled_games(target_date),
        target_date=target_date,
    )
    for model_name, model in payload["models"].items():
        if not isinstance(model, dict):
            continue
        picks = model.get("picks") or []
        ok = bool(model.get("ok"))
        print(f"[player-props] {model_name}: {'ok' if ok else 'error'} ({len(picks)} pick(s))")
        for error in model.get("errors") or []:
            print(f"[player-props] {model_name} warning: {error}")
    for error in contract_errors:
        print(f"[player-props] publication contract error: {error}")
    print(f"[player-props] wrote {output_dir / f'{target_date}.json'}")
    print(f"[player-props] wrote {output_dir / 'latest.json'}")
    return 1 if contract_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
