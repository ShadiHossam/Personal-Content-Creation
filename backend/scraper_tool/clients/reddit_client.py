"""Reddit API client using the OAuth bearer token for the connected user.

Uses the documented oauth.reddit.com endpoints directly — no third-party SDK
needed for the small slice we use (own profile + own submissions + comments).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from backend.scraper_tool.schema import make_record

_BASE = "https://oauth.reddit.com"


def _ua() -> str:
    return os.environ.get("REDDIT_OAUTH_USER_AGENT", "cold-automation-scraper/1.0")


def _headers(access_token: str) -> dict:
    return {"Authorization": f"bearer {access_token}", "User-Agent": _ua()}


def _iso(epoch: float | int | None) -> str:
    if not epoch:
        return ""
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(timespec="seconds")


def fetch_profile(access_token: str) -> list[dict]:
    resp = requests.get(f"{_BASE}/api/v1/me", headers=_headers(access_token), timeout=15)
    resp.raise_for_status()
    me = resp.json() or {}
    return [
        make_record(
            "reddit",
            "profile",
            account_handle=me.get("name", ""),
            account_id=me.get("id", ""),
            id=me.get("id", ""),
            url=f"https://www.reddit.com/user/{me.get('name', '')}",
            created_at=_iso(me.get("created_utc")),
            text=(me.get("subreddit") or {}).get("public_description", ""),
            metrics={
                "link_karma": me.get("link_karma", 0),
                "comment_karma": me.get("comment_karma", 0),
                "total_karma": me.get("total_karma", 0),
                "is_gold": bool(me.get("is_gold")),
                "is_mod": bool(me.get("is_mod")),
            },
            raw=me,
        )
    ]


def _paged_listing(path: str, access_token: str, max_items: int = 100) -> list[dict]:
    """Iterate Reddit's listing pagination (`after` cursor), up to max_items."""
    out: list[dict] = []
    after: str | None = None
    while len(out) < max_items:
        params = {"limit": min(100, max_items - len(out))}
        if after:
            params["after"] = after
        resp = requests.get(f"{_BASE}{path}", headers=_headers(access_token), params=params, timeout=15)
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        children = data.get("children") or []
        if not children:
            break
        out.extend(c.get("data") or {} for c in children)
        after = data.get("after")
        if not after:
            break
    return out[:max_items]


def fetch_posts(access_token: str, username: str, max_items: int = 100) -> list[dict]:
    items = _paged_listing(f"/user/{username}/submitted", access_token, max_items=max_items)
    records = []
    for p in items:
        records.append(
            make_record(
                "reddit",
                "post",
                account_handle=username,
                account_id=p.get("author_fullname", "") or "",
                id=p.get("id", ""),
                url=f"https://www.reddit.com{p.get('permalink', '')}",
                created_at=_iso(p.get("created_utc")),
                text=(p.get("title") or "") + ("\n\n" + p["selftext"] if p.get("selftext") else ""),
                media=[p["url"]] if p.get("url") and not p.get("is_self") else [],
                metrics={
                    "score": p.get("score", 0),
                    "upvote_ratio": p.get("upvote_ratio", 0),
                    "num_comments": p.get("num_comments", 0),
                    "subreddit": p.get("subreddit", ""),
                    "over_18": bool(p.get("over_18")),
                },
                raw=p,
            )
        )
    return records


def fetch_comments(access_token: str, username: str, max_items: int = 100) -> list[dict]:
    items = _paged_listing(f"/user/{username}/comments", access_token, max_items=max_items)
    records = []
    for c in items:
        records.append(
            make_record(
                "reddit",
                "comment",
                account_handle=username,
                account_id=c.get("author_fullname", "") or "",
                id=c.get("id", ""),
                url=f"https://www.reddit.com{c.get('permalink', '')}",
                created_at=_iso(c.get("created_utc")),
                text=c.get("body", ""),
                metrics={
                    "score": c.get("score", 0),
                    "subreddit": c.get("subreddit", ""),
                    "parent_id": c.get("parent_id", ""),
                    "link_id": c.get("link_id", ""),
                },
                raw=c,
            )
        )
    return records
