#!/usr/bin/env python3
"""Install the lightweight macOS backup clock for missed GitHub refreshes."""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def main():
    if sys.platform != "darwin":
        raise SystemExit("This installer requires macOS launchd")
    if not shutil.which("gh"):
        raise SystemExit("Install and authenticate gh before installing the clock")
    subprocess.run(["gh", "auth", "status"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    label = "bet.harsh.pickledger.model-refresh-guard"
    script = Path(__file__).resolve().with_name("ensure_model_refresh.py")
    logs = Path.home() / "Library/Logs/PickLedger"
    logs.mkdir(parents=True, exist_ok=True)
    path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "Label": label,
        "ProgramArguments": [sys.executable, str(script), "--remote", "--dispatch", "--local-clock", "--external-feeds"],
        "StartInterval": 900,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PATH": os.environ["PATH"]},
        "StandardOutPath": str(logs / "model-refresh-guard.log"),
        "StandardErrorPath": str(logs / "model-refresh-guard.error.log"),
    }
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    path.write_bytes(plistlib.dumps(config))
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    print("Installed the 15-minute model refresh backup clock (Central daytime; catches up after sleep).")


if __name__ == "__main__":
    main()
