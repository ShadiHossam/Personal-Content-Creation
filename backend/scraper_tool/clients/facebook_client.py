"""Facebook Pages client — reads the connected user's Page content."""

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
    page_id = token_record.get("page_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not page_id:
        return []
    data = _get(
        f"/{page_id}",
        access,
        {"fields": "id,name,about,category,fan_count,followers_count,link,username,picture"},
    )
    return [
        make_record(
            "facebook",
            "profile",
            account_handle=data.get("username") or data.get("name", ""),
            account_id=str(data.get("id", "")),
            id=str(data.get("id", "")),
            url=data.get("link", ""),
            text=data.get("about", ""),
            media=[((data.get("picture") or {}).get("data") or {}).get("url", "")],
            metrics={
                "followers": int(data.get("followers_count") or 0),
                "fans": int(data.get("fan_count") or 0),
                "category": data.get("category", ""),
            },
            raw=data,
        )
    ]


def fetch_posts(token_record: dict, max_items: int = 50) -> list[dict]:
    page_id = token_record.get("page_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not page_id:
        return []
    fields = (
        "id,message,created_time,permalink_url,full_picture," "reactions.summary(true),comments.summary(true),shares"
    )
    out: list[dict] = []
    url = None
    params = {"fields": fields, "limit": min(100, max_items)}
    while len(out) < max_items:
        if url:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json() or {}
        else:
            data = _get(f"/{page_id}/posts", access, params)
        for p in data.get("data") or []:
            reactions = ((p.get("reactions") or {}).get("summary") or {}).get("total_count", 0)
            comments = ((p.get("comments") or {}).get("summary") or {}).get("total_count", 0)
            shares = (p.get("shares") or {}).get("count", 0)
            out.append(
                make_record(
                    "facebook",
                    "post",
                    account_handle=token_record.get("account_handle", ""),
                    account_id=str(page_id),
                    id=p.get("id", ""),
                    url=p.get("permalink_url", ""),
                    created_at=p.get("created_time", ""),
                    text=p.get("message", ""),
                    media=[p["full_picture"]] if p.get("full_picture") else [],
                    metrics={
                        "reactions": int(reactions or 0),
                        "comments": int(comments or 0),
                        "shares": int(shares or 0),
                    },
                    raw=p,
                )
            )
            if len(out) >= max_items:
                break
        url = ((data.get("paging") or {}).get("next")) or ""
        if not url:
            break
    return out[:max_items]


def fetch_insights(token_record: dict, max_items: int = 30) -> list[dict]:
    """Page-level daily insights for the past ~30 days.

    ``max_items`` is interpreted as the number of metrics returned, not days.
    """
    page_id = token_record.get("page_id") or token_record.get("account_id")
    access = token_record.get("access_token", "")
    if not page_id:
        return []
    metric = ",".join(
        [
            "page_impressions",
            "page_post_engagements",
            "page_views_total",
            "page_fan_adds",
        ]
    )
    data = _get(f"/{page_id}/insights", access, {"metric": metric, "period": "day"})
    out: list[dict] = []
    for m in (data.get("data") or [])[:max_items]:
        values = m.get("values") or []
        latest = values[-1] if values else {}
        out.append(
            make_record(
                "facebook",
                "insight",
                account_handle=token_record.get("account_handle", ""),
                account_id=str(page_id),
                id=m.get("name", ""),
                url="",
                created_at=latest.get("end_time", ""),
                text=m.get("description", m.get("title", "")),
                metrics={"latest_value": latest.get("value", 0), "period": m.get("period", "")},
                raw=m,
            )
        )
    return out
