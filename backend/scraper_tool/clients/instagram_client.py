"""Instagram Business (Graph API) client for the connected user's IG account."""

from __future__ import annotations

import os

import requests

from backend.scraper_tool.schema import make_record

_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v19.0")
_API = f"https://graph.facebook.com/{_GRAPH_VERSION}"


def _get(path: str, token: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    params["access_token"] = token
    resp = requests.get(f"{_API}{path}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.json() or {}


def fetch_profile(token_record: dict) -> list[dict]:
    ig_id = token_record.get("ig_user_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not ig_id:
        return []
    data = _get(
        f"/{ig_id}",
        access,
        {"fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website"},
    )
    return [
        make_record(
            "instagram",
            "profile",
            account_handle=data.get("username", ""),
            account_id=str(data.get("id", "")),
            id=str(data.get("id", "")),
            url=f"https://instagram.com/{data.get('username', '')}",
            text=data.get("biography", ""),
            media=[data.get("profile_picture_url", "")],
            metrics={
                "followers": int(data.get("followers_count") or 0),
                "follows": int(data.get("follows_count") or 0),
                "media_count": int(data.get("media_count") or 0),
                "website": data.get("website", ""),
                "name": data.get("name", ""),
            },
            raw=data,
        )
    ]


def fetch_posts(token_record: dict, max_items: int = 50) -> list[dict]:
    ig_id = token_record.get("ig_user_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not ig_id:
        return []
    fields = "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp," "like_count,comments_count"
    out: list[dict] = []
    url = None
    params = {"fields": fields, "limit": min(50, max_items)}
    while len(out) < max_items:
        if url:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json() or {}
        else:
            data = _get(f"/{ig_id}/media", access, params)
        for m in data.get("data") or []:
            out.append(
                make_record(
                    "instagram",
                    "post",
                    account_handle=token_record.get("account_handle", ""),
                    account_id=str(ig_id),
                    id=m.get("id", ""),
                    url=m.get("permalink", ""),
                    created_at=m.get("timestamp", ""),
                    text=m.get("caption", ""),
                    media=[m.get("media_url") or m.get("thumbnail_url") or ""],
                    metrics={
                        "likes": int(m.get("like_count") or 0),
                        "comments": int(m.get("comments_count") or 0),
                        "media_type": m.get("media_type", ""),
                    },
                    raw=m,
                )
            )
            if len(out) >= max_items:
                break
        url = ((data.get("paging") or {}).get("next")) or ""
        if not url:
            break
    return out[:max_items]


def fetch_insights(token_record: dict, max_items: int = 30) -> list[dict]:
    ig_id = token_record.get("ig_user_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not ig_id:
        return []
    metric = ",".join(["reach", "profile_views", "accounts_engaged"])
    data = _get(
        f"/{ig_id}/insights",
        access,
        {"metric": metric, "period": "day", "metric_type": "total_value"},
    )
    out: list[dict] = []
    for m in (data.get("data") or [])[:max_items]:
        tv = (m.get("total_value") or {}).get("value", 0)
        out.append(
            make_record(
                "instagram",
                "insight",
                account_handle=token_record.get("account_handle", ""),
                account_id=str(ig_id),
                id=m.get("name", ""),
                text=m.get("description", m.get("title", "")),
                metrics={"value": tv, "period": m.get("period", "")},
                raw=m,
            )
        )
    return out
