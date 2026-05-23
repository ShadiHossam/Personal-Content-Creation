"""YouTube search-by-keyword via the YouTube Data API v3.

Distinct from `youtube_client.py`, which uses per-user OAuth to pull the
caller's OWN channel + uploads. This module uses a server-side API key to
search public videos matching a topic — what the Trend Research tool needs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

_API = "https://youtube.googleapis.com/youtube/v3"


def search(query: str, api_key: str, days: int = 30, limit: int = 25) -> list[dict[str, Any]]:
    """Return up to `limit` videos matching `query` published in the last `days`.

    Costs 100 quota units per call (search.list) + 1 unit per videos.list.
    Default daily quota is 10k units, so ~99 calls/day on a free key.
    Returns [] if no api_key is provided.
    """
    if not query:
        return []
    if not api_key:
        raise RuntimeError("missing YouTube Data API key (Settings → API Keys → YouTube)")

    published_after = (datetime.now(tz=timezone.utc) - timedelta(days=max(1, days))).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")

    try:
        sresp = requests.get(
            f"{_API}/search",
            params={
                "key": api_key,
                "q": query,
                "part": "snippet",
                "type": "video",
                "order": "relevance",
                "publishedAfter": published_after,
                "maxResults": min(max(1, limit), 50),
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"network error: {exc}") from exc
    if sresp.status_code != 200:
        # Surface the actual API error — usually quota exceeded, key invalid,
        # or YouTube Data API not enabled on the GCP project.
        try:
            err = (sresp.json().get("error") or {}).get("message", "")
        except Exception:
            err = sresp.text[:200]
        raise RuntimeError(f"YouTube API {sresp.status_code}: {err}")

    items = (sresp.json() or {}).get("items") or []
    video_ids = [
        ((it.get("id") or {}).get("videoId") or "") for it in items if (it.get("id") or {}).get("videoId")
    ]
    if not video_ids:
        return []

    try:
        vresp = requests.get(
            f"{_API}/videos",
            params={
                "key": api_key,
                "id": ",".join(video_ids),
                "part": "snippet,statistics",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"network error on videos.list: {exc}") from exc
    if vresp.status_code != 200:
        try:
            err = (vresp.json().get("error") or {}).get("message", "")
        except Exception:
            err = vresp.text[:200]
        raise RuntimeError(f"YouTube videos.list {vresp.status_code}: {err}")

    out: list[dict[str, Any]] = []
    for v in (vresp.json() or {}).get("items") or []:
        vid = v.get("id", "")
        snip = v.get("snippet") or {}
        stats = v.get("statistics") or {}
        out.append(
            {
                "source": "youtube",
                "id": vid,
                "title": snip.get("title", ""),
                "url": f"https://youtube.com/watch?v={vid}",
                "snippet": (snip.get("description", "") or "")[:400],
                "author": snip.get("channelTitle", ""),
                "created_at": snip.get("publishedAt", ""),
                "score": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "views": int(stats.get("viewCount") or 0),
                "permalink": f"https://youtube.com/watch?v={vid}",
            }
        )
    return out
