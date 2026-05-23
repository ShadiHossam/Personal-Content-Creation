"""SQLite store for per-project YouTube channel data.

One DB file per project at ``<repo>/Saas Project/data/youtube_channels/<slug>.db``.
Stdlib-only (``sqlite3``). Tables: channel, videos, comments, sync_runs, reports.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "youtube_channels"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel (
  channel_id TEXT PRIMARY KEY,
  title TEXT,
  description TEXT,
  thumbnail_url TEXT,
  uploads_playlist_id TEXT,
  subscriber_count INTEGER,
  view_count INTEGER,
  video_count INTEGER,
  published_at TEXT,
  last_sync_at TEXT
);

CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY,
  title TEXT,
  description TEXT,
  published_at TEXT,
  thumbnail_url TEXT,
  duration_seconds INTEGER,
  duration_iso TEXT,
  view_count INTEGER,
  like_count INTEGER,
  comment_count INTEGER,
  engagement_rate REAL,
  tags_json TEXT,
  last_refreshed_at TEXT,
  first_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_views ON videos(view_count DESC);

CREATE TABLE IF NOT EXISTS comments (
  comment_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  author TEXT,
  text TEXT,
  like_count INTEGER,
  published_at TEXT,
  updated_at TEXT,
  last_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
CREATE INDEX IF NOT EXISTS idx_comments_published ON comments(published_at DESC);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  finished_at TEXT,
  duration_seconds REAL,
  new_videos INTEGER DEFAULT 0,
  refreshed_videos INTEGER DEFAULT 0,
  new_comments INTEGER DEFAULT 0,
  api_units_estimated INTEGER DEFAULT 0,
  status TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  generated_at TEXT,
  provider TEXT,
  model TEXT,
  input_summary TEXT,
  payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_kind_gen ON reports(kind, generated_at DESC);
"""


def _slug_safe(slug: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug or "default").strip("-")
    return s or "default"


def db_path(slug: str) -> str:
    os.makedirs(_BASE_DIR, exist_ok=True)
    return os.path.join(_BASE_DIR, f"{_slug_safe(slug)}.db")


@contextmanager
def connect(slug: str):
    path = db_path(slug)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── Channel ─────────────────────────────────────────────────────────────


def get_channel(slug: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute("SELECT * FROM channel LIMIT 1").fetchone()
        return dict(row) if row else None


def upsert_channel(slug: str, ch: dict) -> None:
    with connect(slug) as c:
        c.execute(
            """
            INSERT INTO channel
              (channel_id, title, description, thumbnail_url, uploads_playlist_id,
               subscriber_count, view_count, video_count, published_at, last_sync_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
              title=excluded.title,
              description=excluded.description,
              thumbnail_url=excluded.thumbnail_url,
              uploads_playlist_id=COALESCE(excluded.uploads_playlist_id, channel.uploads_playlist_id),
              subscriber_count=excluded.subscriber_count,
              view_count=excluded.view_count,
              video_count=excluded.video_count,
              published_at=COALESCE(excluded.published_at, channel.published_at),
              last_sync_at=COALESCE(excluded.last_sync_at, channel.last_sync_at)
            """,
            (
                ch["channel_id"],
                ch.get("title"),
                ch.get("description"),
                ch.get("thumbnail_url"),
                ch.get("uploads_playlist_id"),
                int(ch.get("subscriber_count") or 0),
                int(ch.get("view_count") or 0),
                int(ch.get("video_count") or 0),
                ch.get("published_at"),
                ch.get("last_sync_at"),
            ),
        )


def set_last_sync_at(slug: str, iso: str) -> None:
    with connect(slug) as c:
        c.execute("UPDATE channel SET last_sync_at = ?", (iso,))


# ── Videos ──────────────────────────────────────────────────────────────


def get_known_video_ids(slug: str) -> set[str]:
    with connect(slug) as c:
        rows = c.execute("SELECT video_id FROM videos").fetchall()
    return {r["video_id"] for r in rows}


def get_video(slug: str, video_id: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def get_recent_video_ids_for_refresh(slug: str, limit: int = 50, before_iso: str | None = None) -> list[str]:
    """Return up to `limit` most-recently-published video_ids whose
    last_refreshed_at < before_iso (defaults to now)."""
    before = before_iso or now_iso()
    with connect(slug) as c:
        rows = c.execute(
            """
            SELECT video_id FROM videos
            WHERE (last_refreshed_at IS NULL OR last_refreshed_at < ?)
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (before, limit),
        ).fetchall()
    return [r["video_id"] for r in rows]


def list_videos(
    slug: str,
    sort: str = "published",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[dict], int]:
    sort_col = {
        "published": "published_at",
        "views": "view_count",
        "likes": "like_count",
        "comments": "comment_count",
        "engagement": "engagement_rate",
    }.get(sort, "published_at")
    order_sql = "DESC" if (order or "").lower() != "asc" else "ASC"
    where = []
    params: list = []
    if since:
        where.append("published_at >= ?")
        params.append(since)
    if until:
        where.append("published_at < ?")
        params.append(until)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with connect(slug) as c:
        total = c.execute(
            f"SELECT COUNT(*) AS n FROM videos {where_sql}",  # noqa: S608
            tuple(params),
        ).fetchone()["n"]
        rows = c.execute(
            f"SELECT * FROM videos {where_sql} ORDER BY {sort_col} {order_sql}, published_at DESC LIMIT ? OFFSET ?",  # noqa: S608
            (*tuple(params), int(limit), int(offset)),
        ).fetchall()
    return [dict(r) for r in rows], int(total)


def upsert_videos(slug: str, videos: Iterable[dict], refreshed_at: str | None = None) -> int:
    """Upsert a batch of videos. Returns the number of NEW rows inserted."""
    refreshed_at = refreshed_at or now_iso()
    new_count = 0
    with connect(slug) as c:
        for v in videos:
            vid = v["video_id"]
            exists = c.execute("SELECT 1 FROM videos WHERE video_id = ?", (vid,)).fetchone()
            if not exists:
                new_count += 1
            views = int(v.get("view_count") or 0)
            likes = int(v.get("like_count") or 0)
            comments = int(v.get("comment_count") or 0)
            eng = ((likes + comments) / views) if views > 0 else 0.0
            c.execute(
                """
                INSERT INTO videos
                  (video_id, title, description, published_at, thumbnail_url,
                   duration_seconds, duration_iso, view_count, like_count, comment_count,
                   engagement_rate, tags_json, last_refreshed_at, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  title=excluded.title,
                  description=excluded.description,
                  thumbnail_url=excluded.thumbnail_url,
                  duration_seconds=excluded.duration_seconds,
                  duration_iso=excluded.duration_iso,
                  view_count=excluded.view_count,
                  like_count=excluded.like_count,
                  comment_count=excluded.comment_count,
                  engagement_rate=excluded.engagement_rate,
                  tags_json=excluded.tags_json,
                  last_refreshed_at=excluded.last_refreshed_at
                """,
                (
                    vid,
                    v.get("title"),
                    v.get("description"),
                    v.get("published_at"),
                    v.get("thumbnail_url"),
                    int(v.get("duration_seconds") or 0),
                    v.get("duration_iso"),
                    views,
                    likes,
                    comments,
                    eng,
                    json.dumps(v.get("tags") or []),
                    refreshed_at,
                    refreshed_at if not exists else None,
                ),
            )
            if exists:
                # Ensure first_seen_at remains non-null for existing rows from earlier schemas.
                c.execute(
                    "UPDATE videos SET first_seen_at = COALESCE(first_seen_at, ?) WHERE video_id = ?",
                    (refreshed_at, vid),
                )
    return new_count


# ── Comments ────────────────────────────────────────────────────────────


def newest_comment_time(slug: str, video_id: str) -> str | None:
    with connect(slug) as c:
        row = c.execute(
            "SELECT MAX(published_at) AS m FROM comments WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    return row["m"] if row and row["m"] else None


def comment_count_for_video(slug: str, video_id: str) -> int:
    with connect(slug) as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM comments WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    return int(row["n"] or 0)


def upsert_comments(slug: str, comments: Iterable[dict], seen_at: str | None = None) -> int:
    """Insert-or-update a batch of comments. Returns the number of NEW rows."""
    seen_at = seen_at or now_iso()
    new_count = 0
    with connect(slug) as c:
        for cm in comments:
            cid = cm["comment_id"]
            exists = c.execute("SELECT 1 FROM comments WHERE comment_id = ?", (cid,)).fetchone()
            if not exists:
                new_count += 1
            c.execute(
                """
                INSERT INTO comments
                  (comment_id, video_id, author, text, like_count, published_at, updated_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(comment_id) DO UPDATE SET
                  author=excluded.author,
                  text=excluded.text,
                  like_count=excluded.like_count,
                  updated_at=excluded.updated_at,
                  last_seen_at=excluded.last_seen_at
                """,
                (
                    cid,
                    cm["video_id"],
                    cm.get("author"),
                    cm.get("text"),
                    int(cm.get("like_count") or 0),
                    cm.get("published_at"),
                    cm.get("updated_at"),
                    seen_at,
                ),
            )
    return new_count


def fetch_comments_for_report(
    slug: str,
    since_iso: str | None = None,
    per_video_cap: int = 200,
) -> list[dict]:
    """Return comments joined with video titles, capped per video by like_count."""
    with connect(slug) as c:
        where = ""
        params: list = []
        if since_iso:
            where = "WHERE v.published_at >= ?"
            params.append(since_iso)
        rows = c.execute(
            f"""
            SELECT c.comment_id, c.video_id, c.author, c.text, c.like_count,
                   c.published_at, v.title AS video_title, v.published_at AS video_published_at
            FROM comments c
            JOIN videos v ON v.video_id = c.video_id
            {where}
            ORDER BY c.video_id, c.like_count DESC, c.published_at DESC
            """,  # noqa: S608
            params,
        ).fetchall()

    out: list[dict] = []
    by_video: dict[str, int] = {}
    for r in rows:
        vid = r["video_id"]
        if by_video.get(vid, 0) >= per_video_cap:
            continue
        by_video[vid] = by_video.get(vid, 0) + 1
        out.append(dict(r))
    return out


# ── Sync runs ───────────────────────────────────────────────────────────


def record_sync_run(slug: str, run: dict) -> int:
    with connect(slug) as c:
        cur = c.execute(
            """
            INSERT INTO sync_runs
              (started_at, finished_at, duration_seconds, new_videos,
               refreshed_videos, new_comments, api_units_estimated, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.get("started_at"),
                run.get("finished_at"),
                float(run.get("duration_seconds") or 0),
                int(run.get("new_videos") or 0),
                int(run.get("refreshed_videos") or 0),
                int(run.get("new_comments") or 0),
                int(run.get("api_units_estimated") or 0),
                run.get("status") or "ok",
                run.get("error"),
            ),
        )
        return int(cur.lastrowid)


def latest_sync_run(slug: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


# ── Reports ─────────────────────────────────────────────────────────────


def save_report(
    slug: str, kind: str, payload: dict, provider: str = "", model: str = "", input_summary: str = ""
) -> int:
    with connect(slug) as c:
        cur = c.execute(
            """
            INSERT INTO reports (kind, generated_at, provider, model, input_summary, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (kind, now_iso(), provider, model, input_summary, json.dumps(payload, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def get_latest_report(slug: str, kind: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute(
            "SELECT * FROM reports WHERE kind = ? ORDER BY id DESC LIMIT 1",
            (kind,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        d["payload"] = {}
    return d


# ── Misc ────────────────────────────────────────────────────────────────


def channel_totals(slug: str) -> dict:
    with connect(slug) as c:
        row = c.execute(
            """
            SELECT
              COUNT(*) AS videos,
              COALESCE(SUM(view_count), 0) AS total_views,
              COALESCE(SUM(like_count), 0) AS total_likes,
              COALESCE(SUM(comment_count), 0) AS total_comments,
              COALESCE(AVG(engagement_rate), 0) AS avg_engagement
            FROM videos
            """
        ).fetchone()
    return (
        dict(row)
        if row
        else {
            "videos": 0,
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
            "avg_engagement": 0,
        }
    )
