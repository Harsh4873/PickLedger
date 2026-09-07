#!/usr/bin/env python3
"""Refresh scheduled model caches for GitHub Actions and Firestore."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_CACHE_DIR = REPO_ROOT / "data" / "model_cache"
sys.path.insert(0, str(REPO_ROOT))

import pickgrader_server as server  # noqa: E402
from scripts.cache_manifest import write_cache_manifest  # noqa: E402
from scripts.market_odds import apply_market_odds_to_payload  # noqa: E402
from scripts.merge_model_cache_payload import merge_payload, stamp_bucket_date_if_missing  # noqa: E402
from scripts.mlb_team_consensus import apply_mlb_team_consensus_to_payload  # noqa: E402
from scripts.pick_calibration import apply_calibration_to_payload  # noqa: E402
from scripts.team_prop_pregame_ledger import (  # noqa: E402
    capture_team_prop_pregame_snapshots,
    stamp_team_prop_pregame_timing,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run PickLedger models and publish cache artifacts.")
    parser.add_argument("--date", default="", help="Target date in YYYY-MM-DD or MM/DD/YYYY format.")
    parser.add_argument(
        "--models",
        default="mlb_new,mlb_inning,mlb_first_five,mlb_team_total,wnba,nba,nba_playoffs,mls,nfl,cfb,tennis",
        help="Comma-separated model keys to refresh, or 'all'.",
    )
    parser.add_argument("--max-workers", type=int, default=3, help="Maximum parallel model jobs.")
    parser.add_argument("--skip-firestore", action="store_true", help="Write JSON only; useful for local smoke checks.")
    return parser.parse_args()


def _model_jobs(date_iso: str) -> dict[str, Callable[[], dict[str, Any]]]:
    jobs: dict[str, Callable[[], dict[str, Any]]] = {
        "nba": lambda: server.run_nba_model(date_iso, "new"),
        "nba_old": lambda: server.run_nba_model(date_iso, "old"),
        "nba_playoffs": lambda: server.run_nba_playoffs_model(date_iso),
        "nba_summer": lambda: server.run_nba_summer_model(date_iso),
        "wnba": lambda: server.run_wnba_model(date_iso),
        "nba_props": lambda: server.run_nba_props_model(date_iso),
        "mlb_old": lambda: server.run_mlb_model(date_iso, "old"),
        "mlb_new": lambda: server.run_mlb_model(date_iso, "new"),
        "mlb_inning": lambda: server.run_mlb_inning_model(date_iso),
        "mlb_first_five": lambda: server.run_mlb_first_five_model(date_iso),
        "mlb_team_total": lambda: server.run_mlb_team_total_model(date_iso),
        "fifa_world_cup": lambda: server.run_fifa_world_cup_model(date_iso),
        "mls": lambda: server.run_mls_model(date_iso),
        "nfl": lambda: server.run_nfl_model(date_iso),
        "cfb": lambda: server.run_cfb_model(date_iso),
        "tennis": lambda: server.run_tennis_model(date_iso),
    }
    if getattr(server, "IPL_AVAILABLE", False):
        jobs["ipl"] = lambda: server._run_ipl_model_subprocess(  # noqa: SLF001
            None,
            None,
            None,
            None,
            None,
            server.LEDGER_DB_FILE,
        )
    return jobs


def _selected_model_keys(raw: str, available: dict[str, Callable[[], dict[str, Any]]]) -> list[str]:
    raw = str(raw or "").strip()
    if raw.lower() == "all":
        return list(available)
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [key for key in keys if key not in available]
    if unknown:
        raise SystemExit(f"Unknown model key(s): {', '.join(unknown)}")
    return keys


def _build_payload(date_iso: str, models: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "date": date_iso,
        "updatedAt": now_iso,
        "generatedAt": now_iso,
        "generatedBy": "github-actions:model-cache-refresh",
        "models": models,
        "nba": models.get("nba", {}),
        "nba_old": models.get("nba_old", {}),
        "nba_playoffs": models.get("nba_playoffs", {}),
        "nba_summer": models.get("nba_summer", {}),
        "wnba": models.get("wnba", {}),
        "nba_props": models.get("nba_props", {}),
        "mlb": models.get("mlb_old", {}),
        "mlb_old": models.get("mlb_old", {}),
        "mlb_new": models.get("mlb_new", {}),
        "mlb_inning": models.get("mlb_inning", {}),
        "mlb_first_five": models.get("mlb_first_five", {}),
        "mlb_team_total": models.get("mlb_team_total", {}),
        "fifa_world_cup": models.get("fifa_world_cup", {}),
        "mls": models.get("mls", {}),
        "nfl": models.get("nfl", {}),
        "cfb": models.get("cfb", {}),
        "tennis": models.get("tennis", {}),
        "ipl": models.get("ipl", {}),
        "errors": errors,
    }
    for key in ("mlb_new", "wnba"):
        stamp_bucket_date_if_missing(payload["models"].get(key), date_iso)
        stamp_bucket_date_if_missing(payload.get(key), date_iso)
    return payload


def _is_transient_model_error(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("ok") is True:
        return False
    error = str(result.get("error") or "").lower()
    return bool(re.search(r"\b(?:429|500|502|503|504)\s+(?:server error|client error|error|bad gateway|service unavailable|gateway timeout)", error)) or any(
        marker in error
        for marker in (
            "readtimeout",
            "read timed out",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "remote disconnected",
            "bad gateway",
            "service unavailable",
        )
    )


def _run_model_job_with_retries(
    key: str,
    job: Callable[[], dict[str, Any]],
    attempts: int = 2,
) -> dict[str, Any]:
    max_attempts = max(1, attempts)
    result: dict[str, Any] = {"ok": False, "error": "model did not run"}
    for attempt in range(1, max_attempts + 1):
        try:
            result = job()
        except Exception as exc:  # pragma: no cover - defensive for scheduled jobs
            result = {"ok": False, "error": str(exc)}
        if not _is_transient_model_error(result) or attempt >= max_attempts:
            return result
        print(f"[model-cache] {key}: transient failure on attempt {attempt}; retrying")
        time.sleep(3 * attempt)
    return result


def _write_json_cache(date_iso: str, payload: dict[str, Any]) -> dict[str, Any]:
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # This is the only normal publication path that is allowed to certify a
    # team pick.  The marker is per-pick (not inferred later from a mutable
    # daily cache timestamp), and it does not alter any model value or
    # decision.
    stamp_team_prop_pregame_timing(
        payload,
        published_at=str(payload.get("generatedAt") or ""),
        data_as_of=str(payload.get("generatedAt") or ""),
    )
    merged = merge_payload(payload, MODEL_CACHE_DIR)
    # Attach real pregame market prices to every bucket in the merged slate
    # (in-house models and external feeds alike) before it is snapshotted.
    apply_market_odds_to_payload(merged)
    # Calibration and the MLB consensus gate must see the real observed
    # prices, so they run only after the market attach; recalibration is
    # idempotent because it always restarts from each pick's raw probability.
    apply_mlb_team_consensus_to_payload(apply_calibration_to_payload(merged))
    for target in (MODEL_CACHE_DIR / f"{date_iso}.json", MODEL_CACHE_DIR / "latest.json"):
        with target.open("w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
    write_cache_manifest(MODEL_CACHE_DIR)
    summary = capture_team_prop_pregame_snapshots(merged, repo_root=REPO_ROOT)
    print(
        "[team-pregame-ledger] "
        f"captured={summary['added']} unchanged={summary['unchanged']} "
        f"team_picks={summary['team_picks']}"
    )
    return merged


def main() -> int:
    args = _parse_args()
    date_iso, _ = server._parse_model_date_arg(args.date or None)  # noqa: SLF001
    available = _model_jobs(date_iso)
    selected = _selected_model_keys(args.models, available)
    workers = max(1, min(int(args.max_workers or 1), len(selected) or 1))
    print(f"[model-cache] refreshing {', '.join(selected)} for {date_iso} with {workers} worker(s)")

    results: dict[str, Any] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_model_job_with_retries, key, available[key]): key
            for key in selected
        }
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive for scheduled jobs
                result = {"ok": False, "error": str(exc)}
            results[key] = result
            ok = bool(result.get("ok")) if isinstance(result, dict) else False
            pick_count = len(result.get("picks") or []) if isinstance(result, dict) else 0
            if not ok:
                errors.append(f"{key}: {result.get('error') if isinstance(result, dict) else result}")
            print(f"[model-cache] {key}: {'ok' if ok else 'error'} ({pick_count} pick(s))")

    payload = _write_json_cache(date_iso, _build_payload(date_iso, results, errors))
    if args.skip_firestore:
        print("[model-cache] skipped Firestore write")
    else:
        server._write_admin_picks_cache(date_iso, payload)  # noqa: SLF001
        print(f"[model-cache] wrote Firestore admin_picks/{date_iso}")
    print(f"[model-cache] wrote {MODEL_CACHE_DIR / f'{date_iso}.json'}")
    print(f"[model-cache] wrote {MODEL_CACHE_DIR / 'latest.json'}")
    print(json.dumps({"ok": not errors, "date": date_iso, "models": selected, "errors": errors}, indent=2))
    success_count = sum(
        1 for result in results.values()
        if isinstance(result, dict) and result.get("ok")
    )
    return 0 if success_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
