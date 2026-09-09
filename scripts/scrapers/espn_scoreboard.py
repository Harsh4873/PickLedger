"""Validated ESPN scoreboard transport with bounded edge-failure recovery."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


def fetch_scoreboard_json(url: str, *, session: Any = None) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.hostname != "site.api.espn.com":
        raise ValueError("Expected an ESPN scoreboard URL")
    url = urlunsplit(parts._replace(scheme="https"))
    client = session or requests
    for attempt in range(3):
        try:
            response = client.get(
                url, headers={"User-Agent": "PickLedger/1.0", "Accept": "application/json"}, timeout=20
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise ValueError("ESPN response is missing the scoreboard events list")
            return payload
        except (requests.RequestException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == 2 or (status is not None and 400 <= status < 500 and status not in {403, 429}):
                raise
            if status == 403:
                # ESPN's public HTTP and HTTPS edges can fail independently.
                # No credentials or private data are sent to either endpoint.
                scheme = "http" if urlsplit(url).scheme == "https" else "https"
                url = urlunsplit(parts._replace(scheme=scheme))
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")
