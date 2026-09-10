#!/usr/bin/env python3
"""Recover missed model refreshes from Actions or the local publisher clock."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = "Harsh4873/pickledger"
WORKFLOW = "model-cache-refresh.yml"
DAILY_WORKFLOW = "daily-refresh.yml"
CENTRAL = ZoneInfo("America/Chicago")
REQUIRED = {"mlb_new", "mlb_inning", "mlb_first_five", "wnba", "nba", "nba_playoffs", "nfl", "cfb"}
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
# Match the Daily Refresh coordinator's America/Chicago schedule, including DST.
SLOTS = (time(6, 30), time(13, 0))


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def latest_slot(now):
    central = now.astimezone(CENTRAL)
    due = [datetime.combine(central.date(), slot, CENTRAL) for slot in SLOTS]
    return max((slot for slot in due if slot <= central), default=None)


def refresh_decision(payload, runs, now):
    slot = latest_slot(now)
    if slot is None:
        return "idle", "Before the first refresh window"
    target = now.astimezone(CENTRAL).date().isoformat()
    if any(run.get("status") in ACTIVE for run in runs):
        return "active", "Model refresh already queued or running"
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    generated = timestamp(payload.get("generatedAt"))
    healthy = all(isinstance(models.get(key), dict) and models[key].get("ok") is True for key in REQUIRED)
    # External-feed writes update updatedAt; only model generation counts here.
    if payload.get("date") == target and healthy and generated and slot <= generated <= now:
        return "fresh", f"Model cache covers the {slot.isoformat()} refresh window"
    attempts = [run for run in runs if (timestamp(run.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc)) >= slot]
    manual = [run for run in attempts if run.get("event") == "workflow_dispatch"]
    if len(manual) >= 3:
        return "exhausted", "Three recovery/manual attempts in this window; inspect failed runs"
    if any(timestamp(run.get("createdAt")) > now - timedelta(minutes=20) for run in attempts):
        return "cooldown", "Waiting 20 minutes between refresh attempts"
    return "dispatch", f"Missing or unhealthy model cache for the {slot.isoformat()} refresh window"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True, timeout=60)


def refresh_runs():
    # Reusable model jobs belong to the coordinator's run in the Actions API.
    # Include both paths so recovery cannot displace its pending writers.
    return [run for workflow in (WORKFLOW, DAILY_WORKFLOW)
            for run in json.loads(gh("run", "list", "--repo", REPO, "--workflow", workflow,
                                     "--branch", "main", "--limit", "100", "--json",
                                     "status,event,createdAt"))]


def recovery_models(payload, now):
    """Retry only failed core models after an otherwise current window ran."""
    slot = latest_slot(now)
    generated = timestamp(payload.get("generatedAt"))
    if (slot and generated and slot <= generated <= now
            and payload.get("date") == now.astimezone(CENTRAL).date().isoformat()):
        models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
        return sorted(key for key in REQUIRED if not isinstance(models.get(key), dict) or models[key].get("ok") is not True)
    return []


def dispatch_recovery(payload, now):
    if models := recovery_models(payload, now):
        target = now.astimezone(CENTRAL).date().isoformat()
        gh("workflow", "run", WORKFLOW, "--repo", REPO, "--ref", "main",
           "-f", f"date={target}", "-f", f"models={','.join(models)}")
    else:
        gh("workflow", "run", DAILY_WORKFLOW, "--repo", REPO, "--ref", "main")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", action="store_true", help="Dispatch recovery when needed; otherwise read only")
    parser.add_argument("--remote", action="store_true", help="Request the serialized hosted guard without touching the working tree")
    parser.add_argument("--local-clock", action="store_true", help="Only check during the Central daytime publishing window")
    parser.add_argument("--date", default="", help="Skip historical publisher runs")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    central = now.astimezone(CENTRAL)
    target = central.date().isoformat()
    if args.date and args.date != target:
        print("Skipping recovery for a historical or future publisher date")
        return 0
    if args.local_clock and not SLOTS[0] <= central.time() < time(19, 0):
        return 0
    if args.remote:
        runs = json.loads(gh("run", "list", "--repo", REPO, "--workflow", "model-cache-freshness-guard.yml", "--branch", "main", "--limit", "20", "--json", "status"))
        if any(run.get("status") in ACTIVE for run in runs):
            print("Freshness guard already queued or running")
        elif args.dispatch:
            gh("workflow", "run", "model-cache-freshness-guard.yml", "--repo", REPO, "--ref", "main")
            print("Requested freshness guard; it will recover only missing refreshes")
        else:
            print("Would request the freshness guard")
        return 0
    try:
        payload = json.loads((Path(__file__).resolve().parents[2] / "data/model_cache/latest.json").read_text())
    except (OSError, ValueError):
        payload = {}
    runs = refresh_runs()
    state, reason = refresh_decision(payload, runs, now)
    print(f"{state}: {reason}", flush=True)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"state={state}\n")
    if state == "dispatch" and args.dispatch:
        dispatch_recovery(payload, now)
    return 1 if state == "exhausted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
