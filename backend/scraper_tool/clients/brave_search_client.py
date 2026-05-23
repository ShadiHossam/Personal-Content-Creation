"""Brave Search API client.

Free 2k requests/month with an API key. Used by the Trend Research tool as a
general-web fallback for sources we don't directly scrape.
"""

from __future__ import annotations

from typing import Any

import requests

_API = "https://api.search.brave.com/res/v1/web/search"


def _freshness_for_days(days: int) -> str:
    if days <= 1:
        return "pd"
    if days <= 7:
        return "pw"
    if days <= 31:
        return "pm"
    return "py"


def search(query: str, api_key: str, days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    """Return up to `limit` web results matching `query`, filtered by recency.

    Each item is normalized to:
      {source, id, title, url, snippet, author, created_at, score, comments}
    Brave returns no engagement data so `score` is set from the result rank
    (higher = better) and `comments` is 0.
    """
    if not query or not api_key:
        return []

    try:
        resp = requests.get(
            _API,
            params={
                "q": query,
                "count": min(max(1, limit), 20),
                "freshness": _freshness_for_days(max(1, days)),
                "safesearch": "moderate",
            },
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    results = ((resp.json() or {}).get("web") or {}).get("results") or []
    out: list[dict[str, Any]] = []
    for rank, hit in enumerate(results[:limit]):
        url = hit.get("url", "")
        out.append(
            {
                "source": "brave",
                "id": url,
                "title": hit.get("title", ""),
                "url": url,
                "snippet": hit.get("description", "")[:400],
                "author": (hit.get("profile") or {}).get("name", "")
                or (hit.get("meta_url") or {}).get("hostname", ""),
                "created_at": hit.get("page_age", "") or "",
                # Higher rank → higher score so ranking is preserved when merged.
                "score": max(0, len(results) - rank),
                "comments": 0,
                "permalink": url,
            }
        )
    return out
