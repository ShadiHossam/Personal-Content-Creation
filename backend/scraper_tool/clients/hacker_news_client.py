"""Hacker News search client (Algolia HN API).

Free, no auth. Used by the Trend Research tool to pull recent HN stories
matching a topic, ranked by points + comments. Kept deliberately small so it
stays self-contained — no shared state with the other clients.
"""

from __future__ import annotations

import time
from typing import Any

import requests

_API = "https://hn.algolia.com/api/v1/search"


def search(query: str, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
    """Return up to `limit` HN stories matching `query` from the last `days` days.

    Each item is normalized to:
      {source, id, title, url, snippet, author, created_at, score, comments,
       permalink}
    """
    if not query:
        return []

    cutoff = int(time.time() - max(1, days) * 86400)
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{cutoff}",
        "hitsPerPage": min(max(1, limit), 100),
    }
    try:
        resp = requests.get(_API, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    out: list[dict[str, Any]] = []
    for hit in (resp.json() or {}).get("hits", []):
        story_id = hit.get("objectID", "")
        out.append(
            {
                "source": "hackernews",
                "id": str(story_id),
                "title": hit.get("title") or hit.get("story_title") or "",
                "url": hit.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                "snippet": (hit.get("story_text") or "")[:400],
                "author": hit.get("author", ""),
                "created_at": hit.get("created_at", ""),
                "score": int(hit.get("points") or 0),
                "comments": int(hit.get("num_comments") or 0),
                "permalink": f"https://news.ycombinator.com/item?id={story_id}",
            }
        )
    return out
