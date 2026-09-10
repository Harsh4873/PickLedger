#!/usr/bin/env python3
"""Local sync script for SportyTrader picks via manual runs or launchd."""

import json
import os
from datetime import datetime
from pathlib import Path


def _load_local_env() -> None:
    base_dir = Path(__file__).resolve().parent
    for filename in (".env", ".env.local"):
        path = base_dir / filename
        if not path.exists():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError:
            continue


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


_load_local_env()

if not _env_flag("ENABLE_SPORTYTRADER_LOCALSYNC"):
    print("SportyTrader launchd sync disabled. Set ENABLE_SPORTYTRADER_LOCALSYNC=true to enable it.")
    raise SystemExit(0)

import pickgrader_server as p

date_str = datetime.now().strftime("%Y-%m-%d")
result = p.run_sportytrader_scraper(
    date_str,
    ["nba", "nba_summer", "mlb", "wnba", "fifa_world_cup", "cfb", "nfl"],
)
if not result.get("ok"):
    raise SystemExit(result.get("error") or "SportyTrader sync failed")

payload = {
    "updated_at": datetime.now().isoformat(),
    "date": date_str,
    "leagues": "nba,nba_summer,mlb,wnba,fifa_world_cup,cfb,nfl",
    "note": "Auto-synced locally via macOS launchd.",
    "picks": result.get("picks", []),
}

Path("sportytrader_manual_feed.json").write_text(
    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
)
print(f"Synced {len(payload['picks'])} SportyTrader pick(s) for {date_str}")
if result.get("errors"):
    print("Non-fatal sport errors:", "; ".join(result["errors"]))
