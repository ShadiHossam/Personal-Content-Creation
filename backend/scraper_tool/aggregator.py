"""Trend Research aggregator.

Fans out a topic query to multiple sources in parallel, normalizes results
into a common shape, ranks them by an engagement score, and dedupes
near-identical items across sources.
"""

from __future__ import annotations

import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from backend.scraper_tool.clients import (
    brave_search_client,
    hacker_news_client,
    twitter_client,
    youtube_search_client,
)


def _reddit_search_all(*args, **kwargs):
    """Lazy import — reddit_scraper is an optional sibling package."""
    from reddit_scraper.scraper import search_all
    return search_all(*args, **kwargs)


def _reddit_search_subreddit(*args, **kwargs):
    from reddit_scraper.scraper import search_subreddit
    return search_subreddit(*args, **kwargs)

# Available source ids → human label. UI uses this to render the source picker.
SOURCES = {
    "reddit": "Reddit",
    "hackernews": "Hacker News",
    "youtube": "YouTube",
    "twitter": "X / Twitter",
    "brave": "Web (Brave)",
}


# ─── Normalization helpers ────────────────────────────────────────────


def _reddit_to_common(post: dict) -> dict:
    """Adapt a reddit_scraper post dict to the common trend-research shape."""
    permalink = post.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = f"https://www.reddit.com{permalink}"
    return {
        "source": "reddit",
        "id": post.get("id") or "",
        "title": post.get("title", ""),
        "url": post.get("url", "") or permalink,
        "snippet": (post.get("selftext", "") or "")[:400],
        "author": post.get("author", ""),
        "created_at": post.get("created_date", ""),
        "score": int(post.get("score") or 0),
        "comments": int(post.get("num_comments") or 0),
        "permalink": permalink,
        "subreddit": post.get("subreddit", ""),
    }


def _engagement_score(item: dict) -> float:
    """Per-source log-normalized 0–100 score so big-number platforms (Reddit
    upvotes, YouTube views) don't drown out small-number ones (HN points)."""
    src = item.get("source", "")
    score = item.get("score") or 0
    comments = item.get("comments") or 0
    if src == "reddit":
        raw = score + comments * 2
    elif src == "hackernews":
        raw = score + comments * 2
    elif src == "youtube":
        views = item.get("views") or 0
        raw = views / 1000 + score * 5 + comments * 2
    elif src == "twitter":
        raw = score + comments * 2 + (item.get("retweets") or 0) * 3
    elif src == "brave":
        # No engagement data — use rank position (already inverted in client).
        raw = score * 5
    else:
        raw = score + comments
    if raw <= 0:
        return 0.0
    # log10(1+x) keeps differences visible without letting one viral item
    # dominate. Cap at 100 for UI consistency.
    return min(100.0, math.log10(1 + raw) * 18)


# ─── URL canonicalization for dedup ───────────────────────────────────

_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_|ref(_|$)|igshid)", re.IGNORECASE)


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    host = (parts.netloc or "").lower().lstrip("www.")
    query = "&".join(
        seg
        for seg in (parts.query or "").split("&")
        if seg and not _TRACKING_PARAMS.match(seg.split("=", 1)[0])
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", host, path, query, ""))


def _dedup_key(item: dict) -> str:
    url = _canonical_url(item.get("url", ""))
    if url and not url.startswith("https://x.com"):
        return url
    # X posts dedup by author + first-80-char snippet (URLs are unique per tweet
    # but share the same content when retweeted/quoted).
    author = (item.get("author") or "").lower()
    snippet = (item.get("snippet") or item.get("title") or "")[:80].strip().lower()
    return f"{item.get('source', '')}::{author}::{snippet}"


def merge_dedup(items: list[dict]) -> list[dict]:
    """Collapse duplicates, preferring the higher-engagement copy."""
    by_key: dict[str, dict] = {}
    for it in items:
        k = _dedup_key(it)
        if not k:
            continue
        existing = by_key.get(k)
        if existing is None or _engagement_score(it) > _engagement_score(existing):
            by_key[k] = it
    return list(by_key.values())


# ─── Per-source fan-out ───────────────────────────────────────────────


def _run_reddit(query: str, days: int, limit: int, _keys: dict, opts: dict | None = None) -> list[dict]:
    """Search Reddit, optionally scoped to specific subreddits and a location.

    `opts` (passed through from the start endpoint):
      - subreddits      : list[str] — restrict search to these subs (per-sub
                          search_subreddit calls in parallel, then merged).
                          Empty/None → search r/all.
      - location_kw     : str — appended to query as a hint for relevance.
      - location_filter : bool — drop items whose title+body don't mention
                          location_kw (case-insensitive).
    """
    opts = opts or {}
    subreddits = [s.strip().lstrip("r/").lstrip("/") for s in (opts.get("subreddits") or []) if s and s.strip()]
    location_kw = (opts.get("location_kw") or "").strip()
    location_filter = bool(opts.get("location_filter"))

    if days <= 1:
        tf = "day"
    elif days <= 7:
        tf = "week"
    elif days <= 31:
        tf = "month"
    elif days <= 365:
        tf = "year"
    else:
        tf = "all"

    effective_query = f"{query} {location_kw}".strip() if location_kw else query

    raw_posts: list[dict] = []
    if subreddits:
        # Fan out per-subreddit so one failing sub doesn't poison the rest.
        # Cap concurrency to be polite to Reddit's rate limit.
        per_sub_limit = max(5, limit // max(1, len(subreddits)) + 5)
        with ThreadPoolExecutor(max_workers=min(len(subreddits), 4)) as pool:
            futures = {
                pool.submit(_reddit_search_subreddit, sub, effective_query, "relevance", tf, per_sub_limit): sub
                for sub in subreddits
            }
            for fut in as_completed(futures):
                try:
                    raw_posts.extend(fut.result() or [])
                except Exception:
                    # Soft-fail per subreddit; surface nothing — empty merges harmlessly.
                    continue
    else:
        # Reddit's `relevance` sort = BM25 + recency + score, much better than
        # `top` for topical research (which returns viral threads that just
        # mention the keyword).
        raw_posts = _reddit_search_all(effective_query, sort="relevance", time_filter=tf, limit=limit) or []

    items = [_reddit_to_common(p) for p in raw_posts]

    if location_filter and location_kw:
        kw = location_kw.lower()
        items = [
            it for it in items
            if kw in (it.get("title") or "").lower() or kw in (it.get("snippet") or "").lower()
        ]

    # When merging multiple subs we may exceed `limit` — trim by engagement.
    if len(items) > limit:
        items.sort(key=lambda x: (x.get("score") or 0) + (x.get("comments") or 0) * 2, reverse=True)
        items = items[:limit]

    return items


def _run_hn(query: str, days: int, limit: int, _keys: dict, _opts: dict | None = None) -> list[dict]:
    return hacker_news_client.search(query, days=days, limit=limit)


def _run_youtube(query: str, days: int, limit: int, keys: dict, _opts: dict | None = None) -> list[dict]:
    return youtube_search_client.search(query, api_key=keys.get("youtube_key", ""), days=days, limit=limit)


def _run_twitter(query: str, days: int, limit: int, keys: dict, _opts: dict | None = None) -> list[dict]:
    return twitter_client.search(
        query,
        auth_token=keys.get("twitter_auth_token", ""),
        ct0=keys.get("twitter_ct0", ""),
        days=days,
        limit=limit,
    )


def _run_brave(query: str, days: int, limit: int, keys: dict, _opts: dict | None = None) -> list[dict]:
    return brave_search_client.search(query, api_key=keys.get("brave_key", ""), days=days, limit=limit)


_SOURCE_RUNNERS: dict[str, Callable[..., list[dict]]] = {
    "reddit": _run_reddit,
    "hackernews": _run_hn,
    "youtube": _run_youtube,
    "twitter": _run_twitter,
    "brave": _run_brave,
}


# ─── Public entry point ───────────────────────────────────────────────


def run_research(
    query: str,
    sources: list[str],
    days: int = 30,
    limit_per_source: int = 25,
    api_keys: dict | None = None,
    source_opts: dict[str, dict] | None = None,
    progress_cb: Callable[[str, int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Fan out `query` to each enabled source in parallel and aggregate.

    `progress_cb(source, step, message)` is called as each source completes —
    the server uses this to drive the UI progress bar.

    Returns a dict:
      {
        "by_source": {source_id: [items...]},
        "ranked":     [items sorted by engagement_score desc, dedup'd],
        "errors":     {source_id: "error message"},
        "stats":      {source_id: count},
      }
    """
    api_keys = api_keys or {}
    source_opts = source_opts or {}
    selected = [s for s in sources if s in _SOURCE_RUNNERS] or list(_SOURCE_RUNNERS.keys())

    by_source: dict[str, list[dict]] = {s: [] for s in selected}
    errors: dict[str, str] = {}

    def _do_source(src: str) -> tuple[str, list[dict] | None, str | None]:
        if cancel_event and cancel_event.is_set():
            return src, None, "cancelled"
        try:
            results = _SOURCE_RUNNERS[src](
                query, days, limit_per_source, api_keys, source_opts.get(src) or {}
            ) or []
            return src, results, None
        except Exception as exc:  # noqa: BLE001 — soft per-source failure
            return src, None, str(exc)[:200]

    completed = 0
    with ThreadPoolExecutor(max_workers=min(len(selected), 5)) as pool:
        futures = {pool.submit(_do_source, s): s for s in selected}
        for fut in as_completed(futures):
            src, results, err = fut.result()
            completed += 1
            if err:
                errors[src] = err
                if progress_cb:
                    progress_cb(src, completed, f"{src}: {err}")
            else:
                items = results or []
                # Annotate each item with its computed engagement score so the
                # UI can show it directly without re-computing client-side.
                for it in items:
                    it["engagement_score"] = round(_engagement_score(it), 1)
                by_source[src] = items
                if progress_cb:
                    progress_cb(src, completed, f"{src}: {len(items)} items")

    all_items: list[dict] = []
    for items in by_source.values():
        all_items.extend(items)
    ranked = sorted(merge_dedup(all_items), key=lambda x: x.get("engagement_score", 0), reverse=True)

    return {
        "by_source": by_source,
        "ranked": ranked,
        "errors": errors,
        "stats": {s: len(by_source.get(s, [])) for s in selected},
    }
