"""AI performance report for a YouTube channel.

Reads stored video rows from ``channel_store``, pre-computes local stats,
sends a compressed summary + top-30/bottom-30 titles to the AI, parses the
JSON reply, and persists it as a ``reports`` row of kind='performance'.
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime
from typing import Callable

from . import channel_store as store
from .generator import _safe_json_parse

_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "channel_performance.txt")


def _load_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_iso(dt: str | None) -> datetime | None:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket_duration(seconds: int) -> str:
    if seconds <= 60:
        return "<=1m"
    if seconds <= 180:
        return "1-3m"
    if seconds <= 480:
        return "3-8m"
    if seconds <= 900:
        return "8-15m"
    if seconds <= 1800:
        return "15-30m"
    return ">30m"


def _compute_stats(videos: list[dict]) -> dict:
    if not videos:
        return {
            "video_count": 0,
            "median_views": 0,
            "mean_views": 0,
            "median_engagement": 0,
            "duration_buckets": {},
            "publish_day_histogram": {},
        }
    views = [int(v.get("view_count") or 0) for v in videos]
    engs = [float(v.get("engagement_rate") or 0) for v in videos]
    durations = [int(v.get("duration_seconds") or 0) for v in videos]

    by_bucket: dict[str, list[int]] = {}
    for v in videos:
        b = _bucket_duration(int(v.get("duration_seconds") or 0))
        by_bucket.setdefault(b, []).append(int(v.get("view_count") or 0))
    bucket_stats = {b: {"count": len(vs), "median_views": int(statistics.median(vs))} for b, vs in by_bucket.items()}

    day_hist: dict[str, int] = {d: 0 for d in _DAY_NAMES}
    for v in videos:
        dt = _parse_iso(v.get("published_at"))
        if dt:
            day_hist[_DAY_NAMES[dt.weekday()]] += 1

    return {
        "video_count": len(videos),
        "median_views": int(statistics.median(views)),
        "mean_views": int(statistics.mean(views)),
        "median_engagement": round(statistics.median(engs), 4),
        "median_duration_seconds": int(statistics.median(durations)),
        "duration_buckets": bucket_stats,
        "publish_day_histogram": day_hist,
    }


def _compact_video(v: dict) -> dict:
    return {
        "video_id": v["video_id"],
        "title": v.get("title"),
        "published_at": v.get("published_at"),
        "duration_seconds": int(v.get("duration_seconds") or 0),
        "views": int(v.get("view_count") or 0),
        "likes": int(v.get("like_count") or 0),
        "comments": int(v.get("comment_count") or 0),
        "engagement_rate": round(float(v.get("engagement_rate") or 0), 4),
    }


def build_input_block(videos: list[dict], project: dict | None) -> tuple[str, dict]:
    stats = _compute_stats(videos)
    by_views = sorted(videos, key=lambda v: int(v.get("view_count") or 0), reverse=True)
    top = [_compact_video(v) for v in by_views[:30]]
    bottom = [_compact_video(v) for v in by_views[-30:][::-1]]

    project_block = ""
    if project:
        lang = project.get("language") or "en"
        project_block = (
            f"## Channel project\n"
            f"Name: {project.get('name','')}\n"
            f"About: {project.get('description','')}\n"
            f"Output language: {lang}\n\n"
        )

    payload = {
        "channel_stats": stats,
        "top_30_by_views": top,
        "bottom_30_by_views": bottom,
    }
    block = (
        f"{project_block}"
        f"## Input data (compressed)\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Produce the JSON analysis now."
    )
    return block, stats


CallAi = Callable[[str, str, list, dict, int], tuple[str, dict]]


def generate_performance_report(
    slug: str,
    project: dict | None,
    call_ai: CallAi,
    provider: str = "claude_cli",
    model: str = "",
    api_keys: dict | None = None,
    video_ids: list | None = None,
) -> dict:
    """If `video_ids` is provided, restrict analysis to that subset."""
    api_keys = api_keys or {}
    videos, total = store.list_videos(slug, sort="published", order="desc", limit=100000, offset=0)
    if video_ids:
        wanted = set(video_ids)
        videos = [v for v in videos if v.get("video_id") in wanted]
        total = len(videos)
    if not videos:
        raise RuntimeError("No videos available for analysis — run a sync first, or widen the scope.")

    user_block, stats = build_input_block(videos, project)
    system = _load_prompt()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_block},
    ]
    content, usage = call_ai(provider, model, messages, api_keys, 180)
    try:
        payload = _safe_json_parse(content)
    except Exception as exc:
        raise ValueError(f"AI returned invalid JSON: {exc}\n\nRaw output:\n{content[:2000]}") from exc

    payload["_meta"] = {
        "video_count": total,
        "stats": stats,
        "usage": usage,
    }
    store.save_report(
        slug,
        "performance",
        payload,
        provider=provider,
        model=model,
        input_summary=f"{total} videos",
    )
    return payload
