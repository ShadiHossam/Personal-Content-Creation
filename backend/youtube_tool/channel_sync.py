"""Incremental YouTube Data API v3 sync for a single channel.

Stateful: reads/writes SQLite via ``channel_store``. Incremental strategy:
  1. Refresh channel row (1 unit).
  2. Walk uploads playlist page-by-page; stop after the first page whose IDs
     are all already in the local DB.
  3. Refresh stats for the 50 most-recently-published known videos.
  4. Hydrate full detail for newly-discovered videos.
  5. For new videos + existing videos whose commentCount changed, page through
     commentThreads (order=time), stopping at comments older than last_sync_at
     or the newest comment we already have.
  6. Persist sync run audit row; update channel.last_sync_at.

Public entry point: ``sync_channel(slug, api_key, channel_url, progress_cb=None)``.
"""

from __future__ import annotations

import re
import time
from typing import Callable
from urllib.parse import urlparse

from . import channel_store as store

BASE = "https://www.googleapis.com/youtube/v3"


# ── Helpers ─────────────────────────────────────────────────────────────

_ISO_DURATION_RE = re.compile(r"PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?")


def parse_iso_duration(iso: str | None) -> int:
    if not iso:
        return 0
    m = _ISO_DURATION_RE.fullmatch(iso)
    if not m:
        return 0
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    return h * 3600 + mi * 60 + s


def _extract_channel_hint(channel_url: str) -> tuple[str | None, str | None, str | None]:
    """Return (channel_id, handle, custom_or_username).

    Examples handled:
      - https://www.youtube.com/channel/UCxxxxxxxx  → ("UCxxxx", None, None)
      - https://www.youtube.com/@handle             → (None, "handle", None)
      - https://www.youtube.com/c/CustomName        → (None, None, "CustomName")
      - https://www.youtube.com/user/Username       → (None, None, "Username")
      - bare "@handle" or "UCxxxx" or "SomeName"    → best-effort
    """
    if not channel_url:
        return None, None, None
    s = channel_url.strip()
    if s.startswith("@"):
        return None, s[1:], None
    if s.startswith("UC") and len(s) > 20 and "/" not in s and "." not in s:
        return s, None, None
    try:
        parsed = urlparse(s if "://" in s else f"https://{s}")
    except ValueError:
        return None, None, s
    path = (parsed.path or "").strip("/")
    if not path:
        return None, None, None
    parts = path.split("/")
    first = parts[0]
    if first.startswith("@"):
        return None, first[1:], None
    if first == "channel" and len(parts) > 1:
        return parts[1], None, None
    if first in ("c", "user") and len(parts) > 1:
        return None, None, parts[1]
    return None, None, first


class YouTubeAPI:
    """Thin wrapper over the Data API v3 REST endpoints.

    Uses the server's shared ``http_req`` session when one is injected;
    falls back to the ``requests`` library otherwise.
    """

    def __init__(self, api_key: str, http=None, timeout: int = 20):
        if not api_key:
            raise ValueError("YouTube API key is required")
        self.api_key = api_key
        self.timeout = timeout
        if http is None:
            import requests

            http = requests
        self.http = http
        self.units_used = 0

    def _get(self, path: str, params: dict, cost: int = 1) -> dict:
        params = {**params, "key": self.api_key}
        r = self.http.get(f"{BASE}{path}", params=params, timeout=self.timeout)
        self.units_used += cost
        if r.status_code >= 400:
            try:
                body = r.json()
                err = body.get("error", {}).get("message") or r.text
            except ValueError:
                err = r.text
            raise RuntimeError(f"YouTube API {r.status_code}: {err}")
        return r.json()

    # — Channel resolution —

    def resolve_channel_id(self, channel_url: str) -> str:
        cid, handle, custom = _extract_channel_hint(channel_url)
        if cid:
            return cid
        if handle:
            try:
                data = self._get("/channels", {"part": "id", "forHandle": f"@{handle}"}, cost=1)
                items = data.get("items") or []
                if items:
                    return items[0]["id"]
            except RuntimeError:
                pass
        query = custom or handle or channel_url
        data = self._get(
            "/search",
            {"part": "snippet", "q": query, "type": "channel", "maxResults": 1},
            cost=100,
        )
        items = data.get("items") or []
        if not items:
            raise RuntimeError(f"Channel not found for: {channel_url}")
        return items[0]["snippet"]["channelId"]

    # — Channel —

    def get_channel(self, channel_id: str) -> dict:
        data = self._get(
            "/channels",
            {"part": "snippet,statistics,contentDetails", "id": channel_id},
            cost=1,
        )
        items = data.get("items") or []
        if not items:
            raise RuntimeError(f"Channel {channel_id} returned no data")
        ch = items[0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})
        content = ch.get("contentDetails", {}).get("relatedPlaylists", {})
        return {
            "channel_id": ch["id"],
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url"),
            "uploads_playlist_id": content.get("uploads"),
            "subscriber_count": int(stats.get("subscriberCount") or 0),
            "view_count": int(stats.get("viewCount") or 0),
            "video_count": int(stats.get("videoCount") or 0),
            "published_at": snippet.get("publishedAt"),
        }

    # — Playlist walk —

    def iter_playlist_items(self, playlist_id: str):
        page_token = None
        while True:
            params = {
                "part": "contentDetails,snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("/playlistItems", params, cost=1)
            yield data.get("items") or []
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    # — Videos batch —

    def videos_details(self, video_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i : i + 50]
            data = self._get(
                "/videos",
                {"part": "snippet,statistics,contentDetails", "id": ",".join(chunk)},
                cost=1,
            )
            for v in data.get("items") or []:
                snippet = v.get("snippet", {})
                stats = v.get("statistics", {})
                details = v.get("contentDetails", {})
                out.append(
                    {
                        "video_id": v["id"],
                        "title": snippet.get("title"),
                        "description": snippet.get("description"),
                        "published_at": snippet.get("publishedAt"),
                        "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                        "duration_iso": details.get("duration"),
                        "duration_seconds": parse_iso_duration(details.get("duration")),
                        "view_count": int(stats.get("viewCount") or 0),
                        "like_count": int(stats.get("likeCount") or 0),
                        "comment_count": int(stats.get("commentCount") or 0),
                        "tags": snippet.get("tags") or [],
                    }
                )
        return out

    # — Comments —

    def iter_comment_threads(self, video_id: str):
        page_token = None
        while True:
            params = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": 100,
                "order": "time",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            try:
                data = self._get("/commentThreads", params, cost=1)
            except RuntimeError as exc:
                msg = str(exc).lower()
                # Comments disabled or not accessible: skip silently.
                if "disabled" in msg or "403" in msg or "commentsdisabled" in msg:
                    return
                raise
            yield data.get("items") or []
            page_token = data.get("nextPageToken")
            if not page_token:
                return


def _top_level_comment_from_thread(item: dict) -> dict | None:
    top = (item.get("snippet") or {}).get("topLevelComment") or {}
    snippet = top.get("snippet") or {}
    cid = top.get("id")
    if not cid:
        return None
    return {
        "comment_id": cid,
        "video_id": snippet.get("videoId") or (item.get("snippet") or {}).get("videoId"),
        "author": snippet.get("authorDisplayName"),
        "text": snippet.get("textDisplay") or snippet.get("textOriginal"),
        "like_count": int(snippet.get("likeCount") or 0),
        "published_at": snippet.get("publishedAt"),
        "updated_at": snippet.get("updatedAt"),
    }


# ── Orchestrator ────────────────────────────────────────────────────────


ProgressCb = Callable[[str, dict], None]


def sync_channel(
    slug: str,
    api_key: str,
    channel_url: str,
    progress_cb: ProgressCb | None = None,
    http=None,
) -> dict:
    """Run an incremental sync. Returns a summary dict suitable for the sync_runs row."""

    def _progress(msg: str, extra: dict | None = None):
        if progress_cb:
            progress_cb(msg, extra or {})

    start_ts = time.time()
    started_at = store.now_iso()
    api = YouTubeAPI(api_key, http=http)

    existing = store.get_channel(slug)
    last_sync_at = existing.get("last_sync_at") if existing else None
    uploads_playlist_id = existing.get("uploads_playlist_id") if existing else None
    channel_id = existing.get("channel_id") if existing else None

    _progress("Resolving channel...", {})
    if not channel_id:
        channel_id = api.resolve_channel_id(channel_url)

    _progress("Fetching channel info...", {})
    ch = api.get_channel(channel_id)
    ch["last_sync_at"] = started_at
    store.upsert_channel(slug, ch)
    uploads_playlist_id = ch.get("uploads_playlist_id") or uploads_playlist_id

    if not uploads_playlist_id:
        raise RuntimeError("Could not determine uploads playlist for channel")

    known_ids = store.get_known_video_ids(slug)
    is_first_sync = not known_ids

    _progress("Discovering uploads...", {})
    new_ids: list[str] = []
    pages_walked = 0
    for page in api.iter_playlist_items(uploads_playlist_id):
        pages_walked += 1
        page_ids = [
            (p.get("contentDetails") or {}).get("videoId")
            for p in page
            if (p.get("contentDetails") or {}).get("videoId")
        ]
        newly = [vid for vid in page_ids if vid not in known_ids]
        new_ids.extend(newly)
        # Stop if every ID on this page is already known AND we are not on first sync.
        if not is_first_sync and page_ids and all(vid in known_ids for vid in page_ids):
            break
        _progress(f"Discovered {len(new_ids)} new videos so far...", {})

    _progress("Refreshing stats for recent videos...", {})
    refresh_ids: list[str] = []
    if known_ids:
        refresh_ids = store.get_recent_video_ids_for_refresh(slug, limit=50, before_iso=started_at)
    pre_refresh_counts: dict[str, int] = {}
    if refresh_ids:
        # Capture current comment_count before refresh so we can detect which videos got new comments.
        for vid in refresh_ids:
            row = store.get_video(slug, vid)
            if row:
                pre_refresh_counts[vid] = int(row.get("comment_count") or 0)
        refreshed = api.videos_details(refresh_ids)
        store.upsert_videos(slug, refreshed, refreshed_at=started_at)

    _progress(f"Hydrating {len(new_ids)} new videos...", {})
    new_video_rows: list[dict] = []
    if new_ids:
        new_video_rows = api.videos_details(new_ids)
        store.upsert_videos(slug, new_video_rows, refreshed_at=started_at)

    # Comment fetch set = new videos + refreshed videos whose comment_count grew.
    comment_target_ids: list[str] = [v["video_id"] for v in new_video_rows if int(v.get("comment_count") or 0) > 0]
    for vid in refresh_ids:
        post = store.get_video(slug, vid)
        if not post:
            continue
        post_count = int(post.get("comment_count") or 0)
        if post_count > pre_refresh_counts.get(vid, 0):
            comment_target_ids.append(vid)

    new_comments_total = 0
    for idx, vid in enumerate(comment_target_ids, 1):
        _progress(
            f"Fetching comments for video {idx}/{len(comment_target_ids)}...",
            {"done": idx, "total": len(comment_target_ids)},
        )
        newest_seen = store.newest_comment_time(slug, vid)
        cutoff = max(x for x in [newest_seen, last_sync_at] if x) if (newest_seen or last_sync_at) else None
        stop = False
        for page in api.iter_comment_threads(vid):
            batch: list[dict] = []
            for item in page:
                cm = _top_level_comment_from_thread(item)
                if not cm:
                    continue
                if cutoff and cm.get("published_at") and cm["published_at"] <= cutoff:
                    stop = True
                    break
                batch.append(cm)
            if batch:
                new_comments_total += store.upsert_comments(slug, batch, seen_at=started_at)
            if stop:
                break

    store.set_last_sync_at(slug, started_at)

    summary = {
        "started_at": started_at,
        "finished_at": store.now_iso(),
        "duration_seconds": round(time.time() - start_ts, 2),
        "new_videos": len(new_ids),
        "refreshed_videos": len(refresh_ids),
        "new_comments": new_comments_total,
        "api_units_estimated": api.units_used,
        "status": "ok",
        "error": None,
    }
    store.record_sync_run(slug, summary)
    _progress("Done", summary)
    return summary
