"""YouTube Data API v3 client for the connected user's own channel."""

from __future__ import annotations

import requests

from backend.scraper_tool.schema import make_record

_API = "https://youtube.googleapis.com/youtube/v3"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, token: str, params: dict) -> dict:
    resp = requests.get(f"{_API}{path}", headers=_headers(token), params=params, timeout=20)
    resp.raise_for_status()
    return resp.json() or {}


def _my_channel(token: str) -> dict:
    data = _get("/channels", token, {"part": "snippet,statistics,contentDetails", "mine": "true"})
    items = data.get("items") or []
    return items[0] if items else {}


def fetch_profile(access_token: str) -> list[dict]:
    channel = _my_channel(access_token)
    if not channel:
        return []
    snip = channel.get("snippet") or {}
    stats = channel.get("statistics") or {}
    return [
        make_record(
            "youtube",
            "profile",
            account_handle=snip.get("customUrl", "") or snip.get("title", ""),
            account_id=channel.get("id", ""),
            id=channel.get("id", ""),
            url=f"https://youtube.com/channel/{channel.get('id', '')}",
            created_at=snip.get("publishedAt", ""),
            text=snip.get("description", ""),
            media=[((snip.get("thumbnails") or {}).get("high") or {}).get("url", "")],
            metrics={
                "subscribers": int(stats.get("subscriberCount") or 0),
                "videos": int(stats.get("videoCount") or 0),
                "views": int(stats.get("viewCount") or 0),
                "hidden_subscriber_count": bool(stats.get("hiddenSubscriberCount")),
            },
            raw=channel,
        )
    ]


def _list_my_video_ids(access_token: str, max_items: int) -> list[str]:
    """Use the uploads playlist rather than search (1 quota unit vs 100)."""
    channel = _my_channel(access_token)
    uploads_id = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or ""
    if not uploads_id:
        return []
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_items:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_id,
            "maxResults": min(50, max_items - len(ids)),
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get("/playlistItems", access_token, params)
        for item in data.get("items") or []:
            vid = ((item.get("contentDetails") or {}).get("videoId")) or ""
            if vid:
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_items]


def fetch_posts(access_token: str, max_items: int = 50) -> list[dict]:
    ids = _list_my_video_ids(access_token, max_items=max_items)
    if not ids:
        return []
    records: list[dict] = []
    # /videos accepts up to 50 ids per call.
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        data = _get(
            "/videos",
            access_token,
            {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)},
        )
        for v in data.get("items") or []:
            snip = v.get("snippet") or {}
            stats = v.get("statistics") or {}
            thumbs = snip.get("thumbnails") or {}
            records.append(
                make_record(
                    "youtube",
                    "post",
                    account_handle=snip.get("channelTitle", ""),
                    account_id=snip.get("channelId", ""),
                    id=v.get("id", ""),
                    url=f"https://youtu.be/{v.get('id', '')}",
                    created_at=snip.get("publishedAt", ""),
                    text=(snip.get("title") or "")
                    + ("\n\n" + snip.get("description") if snip.get("description") else ""),
                    media=[((thumbs.get("high") or {}).get("url") or "")],
                    metrics={
                        "views": int(stats.get("viewCount") or 0),
                        "likes": int(stats.get("likeCount") or 0),
                        "comments": int(stats.get("commentCount") or 0),
                        "favorites": int(stats.get("favoriteCount") or 0),
                        "duration": (v.get("contentDetails") or {}).get("duration", ""),
                        "tags": snip.get("tags") or [],
                    },
                    raw=v,
                )
            )
    return records


def fetch_comments(access_token: str, max_items: int = 100) -> list[dict]:
    channel = _my_channel(access_token)
    cid = channel.get("id") or ""
    if not cid:
        return []
    records: list[dict] = []
    page_token: str | None = None
    while len(records) < max_items:
        params = {
            "part": "snippet",
            "allThreadsRelatedToChannelId": cid,
            "maxResults": min(100, max_items - len(records)),
            "order": "time",
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get("/commentThreads", access_token, params)
        for t in data.get("items") or []:
            top = ((t.get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
            records.append(
                make_record(
                    "youtube",
                    "comment",
                    account_handle=top.get("authorDisplayName", ""),
                    account_id=((top.get("authorChannelId") or {}).get("value")) or "",
                    id=t.get("id", ""),
                    url=top.get("authorChannelUrl", ""),
                    created_at=top.get("publishedAt", ""),
                    text=top.get("textDisplay", ""),
                    metrics={
                        "likes": int(top.get("likeCount") or 0),
                        "video_id": top.get("videoId", ""),
                        "channel_id": cid,
                    },
                    raw=t,
                )
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return records[:max_items]
