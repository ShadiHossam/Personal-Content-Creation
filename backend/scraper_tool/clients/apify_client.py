"""Apify Actor runner.

Single function: run an actor synchronously and return the dataset items it
produced. Used by the social-scraper dispatch shim to swap legacy paths
(Instagram/TikTok/LinkedIn/Meta-Ads) for managed Apify actors.

Uses Apify's `run-sync-get-dataset-items` endpoint so we don't have to poll
the run status ourselves. The endpoint blocks for up to ~5 minutes, which is
why this client uses its own session with a longer timeout — the project-wide
`http_req` (server.py:32) hard-codes 15 s and would cut runs short.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

_API_BASE = "https://api.apify.com/v2"
_USER_AGENT = "cold-automation/1.0 (+https://github.com/)"
_DEFAULT_TIMEOUT = 180


class ApifyRunError(RuntimeError):
    """Raised when an Apify actor run fails or returns a non-2xx status.

    Callers (the dispatch shim) catch this to fall back to the legacy
    scraper path so a flaky actor never takes down a fetch.
    """


def run_actor_sync(
    actor_id: str,
    run_input: dict[str, Any],
    token: str,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[dict]:
    if not token:
        raise ApifyRunError("missing Apify token")
    if not actor_id:
        raise ApifyRunError("missing actor id")

    actor_path = actor_id.replace("/", "~")
    url = f"{_API_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": _USER_AGENT,
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, headers=headers, json=run_input, timeout=timeout)
    except requests.RequestException as e:
        raise ApifyRunError(f"network error calling Apify: {e}") from e

    if resp.status_code >= 400:
        raise ApifyRunError(
            f"Apify actor {actor_id} returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        items = resp.json()
    except ValueError as e:
        raise ApifyRunError(f"Apify response was not JSON: {e}") from e

    if not isinstance(items, list):
        raise ApifyRunError(f"Apify response was not a list: got {type(items).__name__}")
    return items
