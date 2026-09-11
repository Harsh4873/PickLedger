#!/usr/bin/env python3
"""Run local-only source publishers when today's committed feeds are stale.

GitHub-hosted runners are blocked by Forebet and Scores24. The model guard is
already installed on the owner's Mac, so this companion check uses that same
15-minute clock to recover source feeds without scraping on every tick.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
GROUPS = {
    "scores24": ("scores24_mlb", "scores24_wnba", "scores24_cfb", "scores24_nfl"),
    "forebet": ("forebet_mlb", "forebet_wnba", "forebet_mls", "forebet_cfb", "forebet_nfl"),
    "tennis": ("tennistonic_tennis", "scores24_tennis"),
}
SCRIPTS = {
    "scores24": "scripts/scrapers/scores24_publish.sh",
    "forebet": "scripts/scrapers/forebet_publish.sh",
    "tennis": "scripts/scrapers/tennis_publish.sh",
}


def _today() -> str:
    return datetime.now(timezone.utc).astimezone(CENTRAL).date().isoformat()


def _fresh(bucket: object, date_iso: str) -> bool:
    return isinstance(bucket, dict) and bucket.get("refreshStatus") == "ok" and str(bucket.get("date") or "") == date_iso


def _needs_group(payload: dict, group: str, date_iso: str) -> bool:
    feeds = payload.get("external_feeds") if isinstance(payload.get("external_feeds"), dict) else {}
    # A provider may legitimately publish zero picks on an off-day; status and
    # date, rather than pick count, are the freshness contract.
    return any(not _fresh(feeds.get(key), date_iso) for key in GROUPS[group])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    date_iso = args.date or _today()
    if date_iso != _today():
        print("Skipping historical or future external-feed recovery")
        return 0

    repo = Path(__file__).resolve().parents[2]
    payload_path = repo / "data" / "model_cache" / "latest.json"
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}

    state_dir = Path(os.environ.get("PICKLEDGER_EXTERNAL_STATE_DIR", str(Path.home() / ".cache/pickledger-external"))).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "refresh.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("External feed recovery already running")
            return 0
        for group, script in SCRIPTS.items():
            if not _needs_group(payload, group, date_iso):
                continue
            marker = state_dir / f"{group}-{date_iso}.attempt"
            try:
                age = time.time() - marker.stat().st_mtime
            except OSError:
                age = float("inf")
            if age < float(os.environ.get("PICKLEDGER_EXTERNAL_RETRY_SECONDS", "7200")):
                print(f"{group}: retry cooldown ({int(age)}s)")
                continue
            marker.touch()
            command = ["bash", str(repo / script), "--date", date_iso]
            if args.dry_run:
                print("would run " + " ".join(command))
                continue
            print(f"{group}: running local publisher", flush=True)
            try:
                subprocess.run(command, cwd=repo, timeout=1800, check=False)
            except subprocess.TimeoutExpired:
                print(f"{group}: publisher timed out after 1800s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
