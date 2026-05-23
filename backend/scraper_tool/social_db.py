"""Per-project SQLite store for Instagram, TikTok, Facebook, Reddit.

Mirrors the pattern in ``youtube_tool/channel_store.py``: one DB file per
project at ``<repo>/Saas Project/data/social/<slug>.db``. Stdlib-only.

Tables are platform-scoped via a ``platform`` column, so a single DB holds all
non-YouTube social data for a project. YouTube keeps its own DB because its
schema (duration_seconds, engagement_rate, tags_json, etc.) is richer and
pre-existing callers rely on it.

Typical flow:
  - scrape → ``upsert_posts(slug, platform, handle, posts)``
  - record sync → ``record_sync_run(slug, platform, run)``
  - dashboard → ``channel_summary(slug, platform)`` + ``list_posts(...)``
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timezone

_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "social"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  platform TEXT NOT NULL,
  handle TEXT NOT NULL,
  display_name TEXT,
  bio TEXT,
  avatar_url TEXT,
  followers INTEGER,
  following INTEGER,
  posts_count INTEGER,
  verified INTEGER DEFAULT 0,
  extra_json TEXT,
  first_seen_at TEXT,
  last_sync_at TEXT,
  PRIMARY KEY (platform, handle)
);

CREATE TABLE IF NOT EXISTS posts (
  platform TEXT NOT NULL,
  handle TEXT NOT NULL,
  post_id TEXT NOT NULL,
  url TEXT,
  text TEXT,
  media_type TEXT,
  media_url TEXT,
  created_at TEXT,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  reactions INTEGER DEFAULT 0,
  score INTEGER DEFAULT 0,
  extra_json TEXT,
  first_seen_at TEXT,
  last_refreshed_at TEXT,
  PRIMARY KEY (platform, post_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_handle ON posts(platform, handle);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(platform, handle, created_at DESC);

CREATE TABLE IF NOT EXISTS comments (
  platform TEXT NOT NULL,
  comment_id TEXT NOT NULL,
  post_id TEXT,
  handle TEXT,
  author TEXT,
  text TEXT,
  likes INTEGER DEFAULT 0,
  created_at TEXT,
  extra_json TEXT,
  first_seen_at TEXT,
  PRIMARY KEY (platform, comment_id)
);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(platform, post_id);

CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  handle TEXT,
  started_at TEXT,
  finished_at TEXT,
  duration_seconds REAL,
  new_posts INTEGER DEFAULT 0,
  refreshed_posts INTEGER DEFAULT 0,
  new_comments INTEGER DEFAULT 0,
  followers INTEGER DEFAULT 0,
  status TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_platform ON sync_runs(platform, started_at DESC);

CREATE TABLE IF NOT EXISTS reddit_queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  subreddits TEXT,
  keywords TEXT,
  sort TEXT,
  time_filter TEXT,
  min_score INTEGER,
  last_run_at TEXT,
  last_max_created REAL,
  created_at TEXT
);
"""


def _slug_safe(slug: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug or "default").strip("-")
    return s or "default"


def db_path(slug: str) -> str:
    os.makedirs(_BASE_DIR, exist_ok=True)
    return os.path.join(_BASE_DIR, f"{_slug_safe(slug)}.db")


def _migrate(conn) -> None:
    """Apply idempotent column additions on pre-existing DBs.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` won't add columns to tables that
    already exist, so new columns need explicit ``ALTER TABLE`` guards.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_runs)").fetchall()}
    if "followers" not in cols:
        try:
            conn.execute("ALTER TABLE sync_runs ADD COLUMN followers INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass


@contextmanager
def connect(slug: str):
    conn = sqlite3.connect(db_path(slug))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ── Profile ─────────────────────────────────────────────────────────────


def upsert_profile(slug: str, platform: str, handle: str, profile: dict) -> None:
    now = now_iso()
    extra = {
        k: v
        for k, v in profile.items()
        if k
        not in {
            "display_name",
            "bio",
            "avatar_url",
            "followers",
            "following",
            "posts_count",
            "verified",
        }
    }
    with connect(slug) as c:
        c.execute(
            """
            INSERT INTO profiles
              (platform, handle, display_name, bio, avatar_url, followers,
               following, posts_count, verified, extra_json, first_seen_at, last_sync_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, handle) DO UPDATE SET
              display_name=excluded.display_name,
              bio=excluded.bio,
              avatar_url=excluded.avatar_url,
              followers=excluded.followers,
              following=excluded.following,
              posts_count=excluded.posts_count,
              verified=excluded.verified,
              extra_json=excluded.extra_json,
              last_sync_at=excluded.last_sync_at
            """,
            (
                platform,
                handle,
                profile.get("display_name"),
                profile.get("bio"),
                profile.get("avatar_url"),
                int(profile.get("followers") or 0),
                int(profile.get("following") or 0),
                int(profile.get("posts_count") or 0),
                1 if profile.get("verified") else 0,
                json.dumps(extra, ensure_ascii=False) if extra else None,
                now,
                now,
            ),
        )


def get_profile(slug: str, platform: str, handle: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute(
            "SELECT * FROM profiles WHERE platform = ? AND handle = ?",
            (platform, handle),
        ).fetchone()
        return dict(row) if row else None


def list_profiles(slug: str, platform: str | None = None) -> list[dict]:
    with connect(slug) as c:
        if platform:
            rows = c.execute(
                "SELECT * FROM profiles WHERE platform = ? ORDER BY last_sync_at DESC",
                (platform,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM profiles ORDER BY platform, last_sync_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_last_sync_at(slug: str, platform: str, handle: str) -> str | None:
    p = get_profile(slug, platform, handle)
    return p.get("last_sync_at") if p else None


# ── Posts ───────────────────────────────────────────────────────────────


def upsert_posts(slug: str, platform: str, handle: str, posts: Iterable[dict]) -> tuple[int, int]:
    """Upsert a batch of posts. Returns (new_count, refreshed_count)."""
    now = now_iso()
    new_count = 0
    refreshed_count = 0
    known = {
        "post_id",
        "url",
        "text",
        "media_type",
        "media_url",
        "created_at",
        "likes",
        "comments",
        "shares",
        "views",
        "reactions",
        "score",
    }
    with connect(slug) as c:
        for p in posts:
            pid = p.get("post_id") or p.get("id")
            if not pid:
                continue
            exists = c.execute(
                "SELECT 1 FROM posts WHERE platform = ? AND post_id = ?",
                (platform, pid),
            ).fetchone()
            if exists:
                refreshed_count += 1
            else:
                new_count += 1
            extra = {k: v for k, v in p.items() if k not in known and k != "id"}
            c.execute(
                """
                INSERT INTO posts
                  (platform, handle, post_id, url, text, media_type, media_url,
                   created_at, likes, comments, shares, views, reactions, score,
                   extra_json, first_seen_at, last_refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, post_id) DO UPDATE SET
                  url=excluded.url,
                  text=excluded.text,
                  media_type=excluded.media_type,
                  media_url=excluded.media_url,
                  likes=excluded.likes,
                  comments=excluded.comments,
                  shares=excluded.shares,
                  views=excluded.views,
                  reactions=excluded.reactions,
                  score=excluded.score,
                  extra_json=excluded.extra_json,
                  last_refreshed_at=excluded.last_refreshed_at
                """,
                (
                    platform,
                    handle,
                    str(pid),
                    p.get("url"),
                    p.get("text"),
                    p.get("media_type"),
                    p.get("media_url"),
                    p.get("created_at"),
                    int(p.get("likes") or 0),
                    int(p.get("comments") or 0),
                    int(p.get("shares") or 0),
                    int(p.get("views") or 0),
                    int(p.get("reactions") or 0),
                    int(p.get("score") or 0),
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    now if not exists else None,
                    now,
                ),
            )
    return new_count, refreshed_count


def list_posts(
    slug: str,
    platform: str,
    handle: str | None = None,
    limit: int = 200,
    order: str = "created_at",
) -> list[dict]:
    order_col = order if order in {"created_at", "likes", "views", "comments", "score"} else "created_at"
    with connect(slug) as c:
        if handle:
            rows = c.execute(
                f"SELECT * FROM posts WHERE platform = ? AND handle = ? "  # noqa: S608
                f"ORDER BY {order_col} DESC LIMIT ?",
                (platform, handle, int(limit)),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM posts WHERE platform = ? ORDER BY {order_col} DESC LIMIT ?",  # noqa: S608
                (platform, int(limit)),
            ).fetchall()
    return [dict(r) for r in rows]


def newest_post_time(slug: str, platform: str, handle: str) -> str | None:
    """Return the ISO timestamp of the newest post we already have, if any."""
    with connect(slug) as c:
        row = c.execute(
            "SELECT MAX(created_at) AS m FROM posts WHERE platform = ? AND handle = ?",
            (platform, handle),
        ).fetchone()
    return row["m"] if row and row["m"] else None


# ── Comments ────────────────────────────────────────────────────────────


def upsert_comments(slug: str, platform: str, comments: Iterable[dict]) -> int:
    now = now_iso()
    new_count = 0
    known = {"comment_id", "id", "post_id", "handle", "author", "text", "likes", "created_at"}
    with connect(slug) as c:
        for cm in comments:
            cid = cm.get("comment_id") or cm.get("id")
            if not cid:
                continue
            exists = c.execute(
                "SELECT 1 FROM comments WHERE platform = ? AND comment_id = ?",
                (platform, cid),
            ).fetchone()
            if not exists:
                new_count += 1
            extra = {k: v for k, v in cm.items() if k not in known}
            c.execute(
                """
                INSERT INTO comments
                  (platform, comment_id, post_id, handle, author, text, likes,
                   created_at, extra_json, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, comment_id) DO UPDATE SET
                  text=excluded.text,
                  likes=excluded.likes
                """,
                (
                    platform,
                    str(cid),
                    cm.get("post_id"),
                    cm.get("handle"),
                    cm.get("author"),
                    cm.get("text"),
                    int(cm.get("likes") or 0),
                    cm.get("created_at"),
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    now if not exists else None,
                ),
            )
    return new_count


def list_comments(slug: str, platform: str, post_id: str | None = None, limit: int = 500) -> list[dict]:
    with connect(slug) as c:
        if post_id:
            rows = c.execute(
                "SELECT * FROM comments WHERE platform = ? AND post_id = ? " "ORDER BY created_at DESC LIMIT ?",
                (platform, post_id, int(limit)),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM comments WHERE platform = ? " "ORDER BY created_at DESC LIMIT ?",
                (platform, int(limit)),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Sync runs ───────────────────────────────────────────────────────────


def record_sync_run(slug: str, platform: str, run: dict) -> int:
    with connect(slug) as c:
        cur = c.execute(
            """
            INSERT INTO sync_runs
              (platform, handle, started_at, finished_at, duration_seconds,
               new_posts, refreshed_posts, new_comments, followers, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                run.get("handle"),
                run.get("started_at"),
                run.get("finished_at"),
                float(run.get("duration_seconds") or 0),
                int(run.get("new_posts") or 0),
                int(run.get("refreshed_posts") or 0),
                int(run.get("new_comments") or 0),
                int(run.get("followers") or 0),
                run.get("status") or "ok",
                run.get("error"),
            ),
        )
        return int(cur.lastrowid)


def sync_runs_history(slug: str, platform: str, handle: str | None = None, limit: int = 30) -> list[dict]:
    """Return sync run rows (newest first) for computing follower deltas etc."""
    with connect(slug) as c:
        if handle:
            rows = c.execute(
                "SELECT * FROM sync_runs WHERE platform = ? AND handle = ? " "ORDER BY id DESC LIMIT ?",
                (platform, handle, int(limit)),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM sync_runs WHERE platform = ? ORDER BY id DESC LIMIT ?",
                (platform, int(limit)),
            ).fetchall()
    return [dict(r) for r in rows]


def latest_sync_run(slug: str, platform: str) -> dict | None:
    with connect(slug) as c:
        row = c.execute(
            "SELECT * FROM sync_runs WHERE platform = ? ORDER BY id DESC LIMIT 1",
            (platform,),
        ).fetchone()
        return dict(row) if row else None


# ── Reddit saved queries ────────────────────────────────────────────────


def save_reddit_query(slug: str, q: dict) -> int:
    with connect(slug) as c:
        cur = c.execute(
            """
            INSERT INTO reddit_queries
              (name, subreddits, keywords, sort, time_filter, min_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                q.get("name") or "",
                json.dumps(q.get("subreddits") or []),
                json.dumps(q.get("keywords") or []),
                q.get("sort") or "new",
                q.get("time_filter") or "week",
                int(q.get("min_score") or 0),
                now_iso(),
            ),
        )
        return int(cur.lastrowid)


def list_reddit_queries(slug: str) -> list[dict]:
    with connect(slug) as c:
        rows = c.execute("SELECT * FROM reddit_queries ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["subreddits"] = json.loads(d.get("subreddits") or "[]")
            d["keywords"] = json.loads(d.get("keywords") or "[]")
        except (TypeError, json.JSONDecodeError):
            d["subreddits"] = []
            d["keywords"] = []
        out.append(d)
    return out


def get_reddit_query(slug: str, query_id: int) -> dict | None:
    rows = list_reddit_queries(slug)
    for r in rows:
        if int(r.get("id") or 0) == int(query_id):
            return r
    return None


def update_reddit_query_run(slug: str, query_id: int, max_created: float | None) -> None:
    with connect(slug) as c:
        c.execute(
            "UPDATE reddit_queries SET last_run_at = ?, "
            "last_max_created = COALESCE(?, last_max_created) WHERE id = ?",
            (now_iso(), max_created, int(query_id)),
        )


def delete_reddit_query(slug: str, query_id: int) -> bool:
    with connect(slug) as c:
        cur = c.execute("DELETE FROM reddit_queries WHERE id = ?", (int(query_id),))
    return cur.rowcount > 0


# ── Totals / summary ────────────────────────────────────────────────────


def channel_summary(slug: str, platform: str, handle: str | None = None) -> dict:
    with connect(slug) as c:
        if handle:
            row = c.execute(
                """
                SELECT
                  COUNT(*) AS posts,
                  COALESCE(SUM(likes), 0) AS total_likes,
                  COALESCE(SUM(comments), 0) AS total_comments,
                  COALESCE(SUM(views), 0) AS total_views,
                  COALESCE(SUM(shares), 0) AS total_shares,
                  COALESCE(AVG(likes + comments), 0) AS avg_engagement
                FROM posts WHERE platform = ? AND handle = ?
                """,
                (platform, handle),
            ).fetchone()
        else:
            row = c.execute(
                """
                SELECT
                  COUNT(*) AS posts,
                  COALESCE(SUM(likes), 0) AS total_likes,
                  COALESCE(SUM(comments), 0) AS total_comments,
                  COALESCE(SUM(views), 0) AS total_views,
                  COALESCE(SUM(shares), 0) AS total_shares,
                  COALESCE(AVG(likes + comments), 0) AS avg_engagement
                FROM posts WHERE platform = ?
                """,
                (platform,),
            ).fetchone()
    return (
        dict(row)
        if row
        else {
            "posts": 0,
            "total_likes": 0,
            "total_comments": 0,
            "total_views": 0,
            "total_shares": 0,
            "avg_engagement": 0,
        }
    )
