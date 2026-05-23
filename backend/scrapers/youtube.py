import asyncio
from datetime import datetime, timezone
from typing import Optional
import httpx


def parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def fetch_channel_info(channel_id: str, api_key: str) -> dict:
    url = "https://www.googleapis.com/youtube/v3/channels"
    params = {
        "part": "snippet,statistics",
        "id": channel_id,
        "key": api_key
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    items = data.get("items", [])
    if not items:
        return {}
    item = items[0]
    snippet = item.get("snippet", {})
    return {
        "name": snippet.get("title"),
        "country": snippet.get("country"),
        "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
    }


async def fetch_videos(
    channel_id: str,
    api_key: str,
    published_after: Optional[datetime] = None,
    published_before: Optional[datetime] = None,
    max_results: int = 20,
    paginate_all: bool = False,
) -> list[dict]:
    # Use the uploads playlist (UU + channel_id[2:]) — always returns true latest videos
    # in chronological order, unlike the Search API which can return stale/cached results.
    uploads_playlist_id = "UU" + channel_id[2:]

    all_playlist_items = []
    page_token = None
    per_page = 50 if paginate_all else max_results
    cap = 500  # quota safety cap

    async with httpx.AsyncClient() as client:
        while True:
            playlist_params = {
                "part": "snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": per_page,
                "key": api_key,
            }
            if page_token:
                playlist_params["pageToken"] = page_token

            r = await client.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params=playlist_params,
                timeout=15,
            )
            r.raise_for_status()
            playlist_data = r.json()

            batch = playlist_data.get("items", [])
            all_playlist_items.extend(batch)

            next_token = playlist_data.get("nextPageToken")
            if not paginate_all or not next_token or len(all_playlist_items) >= cap:
                break
            page_token = next_token

    items = all_playlist_items
    if not items:
        return []

    # Filter by published_after if incremental fetch
    if published_after:
        # Ensure timezone-aware for comparison (SQLite may return naive datetimes)
        if published_after.tzinfo is None:
            published_after = published_after.replace(tzinfo=timezone.utc)
        items = [
            it for it in items
            if parse_iso(it.get("snippet", {}).get("publishedAt")) and
               parse_iso(it["snippet"]["publishedAt"]) > published_after
        ]
        if not items:
            return []

    # Filter by published_before for backfill / date-range fetches
    if published_before:
        if published_before.tzinfo is None:
            published_before = published_before.replace(tzinfo=timezone.utc)
        items = [
            it for it in items
            if parse_iso(it.get("snippet", {}).get("publishedAt")) and
               parse_iso(it["snippet"]["publishedAt"]) <= published_before
        ]
        if not items:
            return []

    video_ids = [
        it["snippet"]["resourceId"]["videoId"]
        for it in items
        if it.get("snippet", {}).get("resourceId", {}).get("videoId")
    ]
    if not video_ids:
        return []

    # Fetch stats in batches of 50 (YouTube API limit per request)
    all_stat_items = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i + 50]
            r = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,statistics",
                    "id": ",".join(batch_ids),
                    "key": api_key,
                },
                timeout=15,
            )
            r.raise_for_status()
            all_stat_items.extend(r.json().get("items", []))

    results = []
    for item in all_stat_items:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        results.append({
            "platform": "youtube",
            "title": snippet.get("title", ""),
            "body": snippet.get("description", "")[:2000],
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "published_at": parse_iso(snippet.get("publishedAt")),
            "format": "video",
            "likes": int(stats.get("likeCount", 0)),
            "comments_count": int(stats.get("commentCount", 0)),
            "shares": 0,
            "image_url": (
                snippet.get("thumbnails", {}).get("high") or
                snippet.get("thumbnails", {}).get("medium") or
                snippet.get("thumbnails", {}).get("default") or {}
            ).get("url"),
        })
    return results


async def fetch_video_comments(video_id: str, api_key: str, max_results: int = 20) -> list[dict]:
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max_results,
        "key": api_key,
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []

    comments = []
    for item in data.get("items", []):
        top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        comments.append({
            "author": top.get("authorDisplayName", ""),
            "text": top.get("textDisplay", ""),
            "likes": int(top.get("likeCount", 0)),
            "published_at": parse_iso(top.get("publishedAt")),
        })
    return comments


async def fetch_all_video_comments(video_id: str, api_key: str, max_results: int = 200) -> list[dict]:
    """Paginated comment fetch, up to max_results."""
    comments = []
    page_token = None
    async with httpx.AsyncClient() as client:
        while len(comments) < max_results:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": min(100, max_results - len(comments)),
                "key": api_key,
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/commentThreads",
                    params=params,
                    timeout=15,
                )
                r.raise_for_status()
                data = r.json()
            except Exception:
                break

            for item in data.get("items", []):
                top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                comments.append({
                    "author": top.get("authorDisplayName", ""),
                    "text": top.get("textDisplay", ""),
                    "likes": int(top.get("likeCount", 0)),
                    "published_at": parse_iso(top.get("publishedAt")),
                })

            page_token = data.get("nextPageToken")
            if not page_token:
                break

    return comments


async def fetch_video_full_description(video_id: str, api_key: str) -> str:
    """Fetch the full (untruncated) description for a single video."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet", "id": video_id, "key": api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    items = data.get("items", [])
    if not items:
        return ""
    return items[0].get("snippet", {}).get("description", "")


def _fetch_transcript_sync(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    try:
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        return " ".join(s["text"] for s in segments)
    except (NoTranscriptFound, TranscriptsDisabled):
        return ""
    except Exception:
        return ""


async def fetch_video_transcript(video_id: str) -> str:
    """Async wrapper — runs the blocking youtube-transcript-api call in a thread."""
    return await asyncio.to_thread(_fetch_transcript_sync, video_id)
