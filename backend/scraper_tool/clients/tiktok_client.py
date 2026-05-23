"""TikTok Display API client for the connected user's own account."""

from __future__ import annotations

import requests

from backend.scraper_tool.schema import make_record

_API = "https://open.tiktokapis.com/v2"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_profile(access_token: str) -> list[dict]:
    resp = requests.get(
        f"{_API}/user/info/",
        headers=_headers(access_token),
        params={
            "fields": (
                "open_id,union_id,avatar_url,display_name,username,bio_description,"
                "profile_deep_link,is_verified,follower_count,following_count,"
                "likes_count,video_count"
            )
        },
        timeout=20,
    )
    resp.raise_for_status()
    user = (resp.json() or {}).get("data", {}).get("user", {}) or {}
    if not user:
        return []
    return [
        make_record(
            "tiktok",
            "profile",
            account_handle=user.get("username", ""),
            account_id=user.get("open_id", "") or user.get("union_id", ""),
            id=user.get("open_id", ""),
            url=user.get("profile_deep_link", ""),
            text=user.get("bio_description", ""),
            media=[user.get("avatar_url", "")],
            metrics={
                "followers": int(user.get("follower_count") or 0),
                "following": int(user.get("following_count") or 0),
                "likes": int(user.get("likes_count") or 0),
                "videos": int(user.get("video_count") or 0),
                "is_verified": bool(user.get("is_verified")),
                "display_name": user.get("display_name", ""),
            },
            raw=user,
        )
    ]


def fetch_posts(access_token: str, max_items: int = 50) -> list[dict]:
    """TikTok /video/list/ is a POST with pagination via ``cursor`` + ``max_count``."""
    fields = (
        "id,title,video_description,create_time,cover_image_url,share_url,"
        "duration,view_count,like_count,comment_count,share_count"
    )
    out: list[dict] = []
    cursor = 0
    has_more = True
    while has_more and len(out) < max_items:
        body = {"max_count": min(20, max_items - len(out))}
        if cursor:
            body["cursor"] = cursor
        resp = requests.post(
            f"{_API}/video/list/",
            headers=_headers(access_token),
            params={"fields": fields},
            json=body,
            timeout=20,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data", {}) or {}
        videos = data.get("videos") or []
        for v in videos:
            out.append(
                make_record(
                    "tiktok",
                    "post",
                    account_handle="",
                    account_id="",
                    id=str(v.get("id", "")),
                    url=v.get("share_url", ""),
                    created_at=str(v.get("create_time", "")),
                    text=(v.get("title") or "")
                    + (" " + v.get("video_description", "") if v.get("video_description") else ""),
                    media=[v.get("cover_image_url", "")],
                    metrics={
                        "views": int(v.get("view_count") or 0),
                        "likes": int(v.get("like_count") or 0),
                        "comments": int(v.get("comment_count") or 0),
                        "shares": int(v.get("share_count") or 0),
                        "duration": int(v.get("duration") or 0),
                    },
                    raw=v,
                )
            )
        cursor = data.get("cursor") or 0
        has_more = bool(data.get("has_more"))
    return out[:max_items]
