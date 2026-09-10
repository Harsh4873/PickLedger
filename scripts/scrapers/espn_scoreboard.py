"""Validated ESPN scoreboard transport with bounded edge-failure recovery."""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


def _validated_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("ESPN response is missing the scoreboard events list")
    return payload


def _fetch_via_curl_cffi(url: str) -> dict[str, Any] | None:
    """Browser-impersonated fallback when ESPN's edge 403s plain requests.

    Only used when no injected session was supplied. Returns None when
    curl_cffi is unavailable or the impersonated request also fails.
    """
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    try:
        response = curl_requests.get(
            url,
            headers={"Accept": "application/json"},
            impersonate="chrome",
            timeout=20,
        )
        if int(getattr(response, "status_code", 0) or 0) != 200:
            return None
        return _validated_payload(response.json())
    except Exception:
        return None


def fetch_scoreboard_json(url: str, *, session: Any = None) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.hostname != "site.api.espn.com":
        raise ValueError("Expected an ESPN scoreboard URL")
    url = urlunsplit(parts._replace(scheme="https"))
    client = session or requests
    last_exc: BaseException | None = None
    for attempt in range(3):
        try:
            response = client.get(
                url, headers={"User-Agent": "PickLedger/1.0", "Accept": "application/json"}, timeout=20
            )
            response.raise_for_status()
            return _validated_payload(response.json())
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if attempt == 2 or (status is not None and 400 <= status < 500 and status not in {403, 429}):
                break
            if status == 403:
                # ESPN's public HTTP and HTTPS edges can fail independently.
                # No credentials or private data are sent to either endpoint.
                scheme = "http" if urlsplit(url).scheme == "https" else "https"
                url = urlunsplit(parts._replace(scheme=scheme))
            time.sleep(2 ** attempt)
    # Datacenter / bot edges often 403 plain requests while chrome impersonation
    # still returns a public scoreboard. Never use this path when a test or
    # caller injected a session — that would escape the mock onto the network.
    if session is None:
        https_url = urlunsplit(parts._replace(scheme="https"))
        payload = _fetch_via_curl_cffi(https_url)
        if payload is not None:
            return payload
    if last_exc is not None:
        raise last_exc
    raise AssertionError("unreachable")
