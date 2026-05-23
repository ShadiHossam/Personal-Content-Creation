"""Synchronous scraping helpers used by the ``/refresh`` endpoints.

Each ``scrape_<platform>(handle, ...)`` returns ``(profile_dict, posts_list)``
already shaped for ``scraper_tool.social_db`` (keys match the ``upsert_profile``
and ``upsert_posts`` signatures).

These helpers duplicate a small amount of logic from the existing ``/fetch``
routes in ``server.py`` — on purpose. The /fetch routes run in threads and
write to in-memory stores for the legacy UI; the /refresh routes run
synchronously and write to the per-project SQLite via ``social_db``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _unix_to_iso(ts) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError):
        return None


# ── Instagram (public/anonymous scrape) ─────────────────────────────────


def scrape_instagram(username: str, session_id: str | None = None) -> tuple[dict, list[dict]]:
    username = (username or "").strip().lstrip("@")
    if not username:
        raise ValueError("Instagram username is required")
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    cookies = None
    if session_id:
        if not re.fullmatch(r"[A-Za-z0-9:%._-]+", session_id):
            raise ValueError("Invalid Instagram session id")
        cookies = {"sessionid": session_id}
    url = f"https://www.instagram.com/{username}/"
    r = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    r.raise_for_status()
    text = r.text

    # Extract shared_data JSON from the page
    m = re.search(r'<script type="application/json"[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', text)
    user_data = {}
    if m:
        try:
            data = json.loads(m.group(1))
            user_data = (
                data.get("props", {}).get("pageProps", {}).get("user", {})
                or data.get("props", {}).get("pageProps", {}).get("profile", {})
                or {}
            )
        except (ValueError, KeyError):
            user_data = {}

    # Fallback regex for follower count (Instagram injects meta tags)
    og = re.search(r'<meta property="og:description" content="([^"]+)"', text)
    bio = ""
    followers = 0
    if og:
        og_text = og.group(1)
        fmatch = re.search(r"([\d,\.KM]+)\s+Followers", og_text)
        if fmatch:
            followers = _parse_social_count(fmatch.group(1))
        bio = og_text

    profile = {
        "display_name": user_data.get("full_name") or username,
        "bio": user_data.get("biography") or bio,
        "avatar_url": user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url") or "",
        "followers": int(user_data.get("edge_followed_by", {}).get("count", followers) or followers),
        "following": int(user_data.get("edge_follow", {}).get("count", 0) or 0),
        "posts_count": int(user_data.get("edge_owner_to_timeline_media", {}).get("count", 0) or 0),
        "verified": bool(user_data.get("is_verified")),
    }

    posts: list[dict] = []
    edges = (user_data.get("edge_owner_to_timeline_media") or {}).get("edges") or []
    for e in edges:
        n = e.get("node", {})
        ts = n.get("taken_at_timestamp")
        caption = ""
        cap_edges = (n.get("edge_media_to_caption") or {}).get("edges") or []
        if cap_edges:
            caption = cap_edges[0].get("node", {}).get("text") or ""
        posts.append(
            {
                "post_id": n.get("id") or n.get("shortcode"),
                "url": f"https://www.instagram.com/p/{n.get('shortcode')}/" if n.get("shortcode") else None,
                "text": caption,
                "media_type": ("video" if n.get("is_video") else "image"),
                "media_url": n.get("display_url") or n.get("thumbnail_src"),
                "created_at": _unix_to_iso(ts),
                "likes": int(
                    (n.get("edge_media_preview_like") or {}).get("count")
                    or (n.get("edge_liked_by") or {}).get("count")
                    or 0
                ),
                "comments": int((n.get("edge_media_to_comment") or {}).get("count") or 0),
                "views": int(n.get("video_view_count") or 0),
            }
        )
    return profile, posts


def _parse_social_count(s: str) -> int:
    s = s.strip().replace(",", "").replace(".", "")
    mult = 1
    if s.endswith("K"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


# ── TikTok (public page scrape) ─────────────────────────────────────────


def scrape_tiktok(username: str) -> tuple[dict, list[dict]]:
    username = (username or "").strip().lstrip("@")
    if not username:
        raise ValueError("TikTok username is required")
    headers = {"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    url = f"https://www.tiktok.com/@{username}"
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    text = r.text

    m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', text)
    if not m:
        m = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', text)
    if not m:
        raise RuntimeError(f"TikTok data blob not found for @{username} (possibly rate-limited)")
    page_data = json.loads(m.group(1))

    user_info = {}
    if "__DEFAULT_SCOPE__" in page_data:
        user_info = page_data["__DEFAULT_SCOPE__"].get("webapp.user-detail", {}).get("userInfo", {})
    elif "UserModule" in page_data:
        users = page_data["UserModule"].get("users", {})
        if username in users:
            user_info = {
                "user": users[username],
                "stats": page_data["UserModule"].get("stats", {}).get(username, {}),
            }
    if not user_info:
        raise RuntimeError(f"TikTok profile parsing failed for @{username}")

    user = user_info.get("user", {})
    stats = user_info.get("stats", {})
    profile = {
        "display_name": user.get("nickname", "") or username,
        "bio": user.get("signature", ""),
        "avatar_url": user.get("avatarLarger") or user.get("avatarMedium", ""),
        "followers": int(stats.get("followerCount", 0) or 0),
        "following": int(stats.get("followingCount", 0) or 0),
        "posts_count": int(stats.get("videoCount", 0) or 0),
        "verified": bool(user.get("verified")),
    }

    item_list = []
    if "__DEFAULT_SCOPE__" in page_data:
        item_list = page_data["__DEFAULT_SCOPE__"].get("webapp.user-detail", {}).get("itemList", []) or []
    elif "ItemModule" in page_data:
        item_list = list(page_data["ItemModule"].values())

    posts = []
    for item in item_list:
        stats_v = item.get("stats", {})
        posts.append(
            {
                "post_id": item.get("id", ""),
                "url": f"https://www.tiktok.com/@{username}/video/{item.get('id', '')}",
                "text": (item.get("desc", "") or "")[:500],
                "media_type": "video",
                "media_url": (item.get("video") or {}).get("cover", ""),
                "created_at": _unix_to_iso(item.get("createTime")),
                "likes": int(stats_v.get("diggCount", 0) or 0),
                "comments": int(stats_v.get("commentCount", 0) or 0),
                "shares": int(stats_v.get("shareCount", 0) or 0),
                "views": int(stats_v.get("playCount", 0) or 0),
            }
        )
    return profile, posts


# ── Facebook (public page via facebook_scraper library) ─────────────────


def scrape_facebook(page: str) -> tuple[dict, list[dict]]:
    page = (page or "").strip()
    if page.startswith("http"):
        page = urlparse(page).path.strip("/").split("/")[0] or page
    if not page:
        raise ValueError("Facebook page name is required")

    from facebook_scraper import get_posts, get_profile  # lazy import

    profile = {
        "display_name": page,
        "bio": "",
        "avatar_url": "",
        "followers": 0,
        "following": 0,
        "posts_count": 0,
        "verified": False,
    }
    try:
        prof = get_profile(page, timeout=20) or {}
        profile["display_name"] = prof.get("Name") or prof.get("name") or page
        profile["bio"] = prof.get("About") or prof.get("about") or ""
        profile["followers"] = int(prof.get("followers", 0) or 0)
        profile["avatar_url"] = prof.get("profile_picture") or ""
    except Exception as exc:
        profile["bio"] = f"(profile fetch failed: {exc})"

    posts: list[dict] = []
    try:
        gen = get_posts(page, pages=3, timeout=30, options={"allow_extra_requests": False})
        for p in gen:
            if p is None:
                continue
            ts = p.get("time")
            posts.append(
                {
                    "post_id": str(p.get("post_id") or ""),
                    "url": p.get("post_url") or "",
                    "text": (p.get("text") or p.get("post_text") or "")[:1000],
                    "media_type": "video" if p.get("video") else "image",
                    "media_url": p.get("image") or p.get("image_lowquality") or "",
                    "created_at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts or ""),
                    "likes": int(p.get("likes") or p.get("reactions_count") or 0),
                    "comments": int(p.get("comments") or 0),
                    "shares": int(p.get("shares") or 0),
                    "reactions": int(p.get("reactions_count") or 0),
                }
            )
    except Exception as exc:
        raise RuntimeError(f"Facebook scrape failed: {exc}") from exc
    return profile, posts


# ── Reddit (via reddit_scraper module) ──────────────────────────────────


def scrape_reddit(
    subreddits: list[str],
    keywords: list[str] | None = None,
    exclude: list[str] | None = None,
    sort: str = "hot",
    time_filter: str = "week",
    limit: int = 50,
    min_score: int = 0,
    since_utc: float | None = None,
) -> list[dict]:
    """Return a list of post dicts shaped for ``social_db.upsert_posts``.

    When ``since_utc`` is provided, only posts newer than that are returned —
    this is how the incremental refresh avoids re-saving stale rows.
    """
    from reddit_scraper.filters import filter_by_keywords, filter_by_min_score
    from reddit_scraper.scraper import fetch_posts

    all_records: list[dict] = []
    for sub in subreddits:
        all_records.extend(fetch_posts(sub, sort, time_filter, limit))

    all_records = filter_by_keywords(all_records, keywords or None, exclude or None)
    all_records = filter_by_min_score(all_records, int(min_score or 0))

    if since_utc is not None:
        all_records = [r for r in all_records if float(r.get("created_utc") or 0) > since_utc]

    posts: list[dict] = []
    for p in all_records:
        posts.append(
            {
                "post_id": p.get("fullname") or p.get("id"),
                "url": f"https://www.reddit.com{p.get('permalink', '')}" if p.get("permalink") else p.get("url"),
                "text": (p.get("title") or "") + ("\n\n" + (p.get("selftext") or "") if p.get("selftext") else ""),
                "media_type": "text" if p.get("media", {}).get("is_self") else "link",
                "media_url": p.get("media", {}).get("thumbnail") or p.get("media", {}).get("preview_image") or "",
                "created_at": p.get("created_date") or _unix_to_iso(p.get("created_utc")),
                "score": int(p.get("score") or 0),
                "comments": int(p.get("num_comments") or 0),
                "likes": int(p.get("upvotes") or p.get("score") or 0),
                "subreddit": p.get("subreddit"),
                "author": p.get("author"),
                "upvote_ratio": p.get("upvote_ratio"),
            }
        )
    return posts
