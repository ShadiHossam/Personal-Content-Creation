"""Period-based aggregates for a channel's video catalog.

Buckets stored videos by publish date into month / quarter / half-year / year
periods and returns per-period stats (videos posted, views, likes, comments,
engagement) ready for the UI to render a table or chart.
"""

from __future__ import annotations

from datetime import datetime
from statistics import mean

from . import channel_store as store


def _parse(dt):
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket_key(dt, period):
    if period == "month":
        return f"{dt.year:04d}-{dt.month:02d}"
    if period == "quarter":
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year:04d}-Q{q}"
    if period == "half":
        h = 1 if dt.month <= 6 else 2
        return f"{dt.year:04d}-H{h}"
    return f"{dt.year:04d}"


def _label(key, period):
    if period == "month":
        y, m = key.split("-")
        return datetime(int(y), int(m), 1).strftime("%b %Y")
    return key


def _safe_mean(xs):
    return round(mean(xs), 2) if xs else 0


def compute(slug, period="month"):
    period = period if period in ("month", "quarter", "half", "year") else "month"
    videos, _ = store.list_videos(slug, sort="published", order="asc", limit=100000, offset=0)

    buckets = {}
    for v in videos:
        dt = _parse(v.get("published_at"))
        if not dt:
            continue
        key = _bucket_key(dt, period)
        b = buckets.setdefault(
            key,
            {"period": key, "label": _label(key, period), "videos": []},
        )
        b["videos"].append(v)

    rows = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        vs = b["videos"]
        views = [int(v.get("view_count") or 0) for v in vs]
        likes = [int(v.get("like_count") or 0) for v in vs]
        comments = [int(v.get("comment_count") or 0) for v in vs]
        engs = [float(v.get("engagement_rate") or 0) for v in vs]
        durations = [int(v.get("duration_seconds") or 0) for v in vs]
        top = max(vs, key=lambda x: int(x.get("view_count") or 0)) if vs else None
        rows.append(
            {
                "period": b["period"],
                "label": b["label"],
                "videos_posted": len(vs),
                "total_views": sum(views),
                "avg_views": int(_safe_mean(views)),
                "total_likes": sum(likes),
                "avg_likes": int(_safe_mean(likes)),
                "total_comments": sum(comments),
                "avg_comments": int(_safe_mean(comments)),
                "avg_engagement_pct": round(_safe_mean(engs) * 100, 2),
                "avg_duration_seconds": int(_safe_mean(durations)),
                "top_video": (
                    {
                        "video_id": top["video_id"],
                        "title": top.get("title"),
                        "views": int(top.get("view_count") or 0),
                    }
                    if top
                    else None
                ),
            }
        )

    # Reverse so most-recent period is on top in the UI.
    rows.reverse()
    return {"period": period, "rows": rows}
