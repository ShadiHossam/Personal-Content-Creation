"""AI comments-insights report.

Pulls stored comments from SQLite (filtered by recency + capped per video),
dedupes near-duplicates, chunks them to a safe prompt size, runs a two-pass
AI summarization (map-reduce), and persists the final JSON as a ``reports``
row of kind='comments'.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import channel_store as store
from .generator import _safe_json_parse

_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "comments_insights.txt")

# Rough token budget per chunk. 4 chars/token is the typical English approximation;
# we pick 24000 chars which maps to ~6k tokens, leaving room for the prompt envelope.
_CHUNK_CHAR_BUDGET = 24000


def _load_prompt() -> str:
    with open(_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _normalize(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]


def _since_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dedupe(comments: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in comments:
        key = _normalize(c.get("text") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _format_comment_line(c: dict) -> str:
    text = (c.get("text") or "").replace("\n", " ").strip()
    return f'- [v:{c.get("video_id")} | "{c.get("video_title","")[:60]}"] "{text[:500]}" (👍{c.get("like_count", 0)})'


def _chunk_comments(comments: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for c in comments:
        line_len = len(_format_comment_line(c)) + 1
        if current_chars + line_len > _CHUNK_CHAR_BUDGET and current:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(c)
        current_chars += line_len
    if current:
        chunks.append(current)
    return chunks


def _build_chunk_prompt(chunk: list[dict], project: dict | None, chunk_idx: int, chunk_total: int) -> str:
    lang = (project or {}).get("language") or "en"
    header = (
        f"## Channel: {(project or {}).get('name','')}\n"
        f"Output language (for user-facing strings): {lang}\n"
        f"Batch {chunk_idx}/{chunk_total}. Raw top-level comments follow.\n\n"
    )
    body = "\n".join(_format_comment_line(c) for c in chunk)
    return header + body + "\n\nProduce the JSON insights for this batch now."


def _build_merge_prompt(partials: list[dict], project: dict | None) -> str:
    lang = (project or {}).get("language") or "en"
    header = (
        f"## Channel: {(project or {}).get('name','')}\n"
        f"Output language (for user-facing strings): {lang}\n"
        f"BATCH MERGE INPUT — merge and deduplicate these {len(partials)} partial JSON results into one final JSON.\n\n"
    )
    body = "```json\n" + json.dumps(partials, ensure_ascii=False, indent=2) + "\n```\n"
    return header + body + "\nProduce the merged JSON now."


CallAi = Callable[[str, str, list, dict, int], tuple[str, dict]]


def generate_comments_report(
    slug: str,
    project: dict | None,
    call_ai: CallAi,
    provider: str = "claude_cli",
    model: str = "",
    api_keys: dict | None = None,
    days: int = 180,
    per_video_cap: int = 200,
    max_comments: int = 2000,
) -> dict:
    api_keys = api_keys or {}
    since = _since_iso(days) if days and days > 0 else None
    raw = store.fetch_comments_for_report(slug, since_iso=since, per_video_cap=per_video_cap)
    if not raw:
        raise RuntimeError("No comments stored — run a sync first, or widen the date window.")

    deduped = _dedupe(raw)
    # Hard cap to avoid runaway cost on very large catalogs.
    if len(deduped) > max_comments:
        deduped = deduped[:max_comments]

    chunks = _chunk_comments(deduped)
    system = _load_prompt()

    partials: list[dict] = []
    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for idx, chunk in enumerate(chunks, 1):
        user = _build_chunk_prompt(chunk, project, idx, len(chunks))
        content, usage = call_ai(
            provider,
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            api_keys,
            180,
        )
        try:
            partials.append(_safe_json_parse(content))
        except Exception:
            # If a single batch fails to parse, skip it but keep going.
            continue
        for k in total_usage:
            total_usage[k] += int((usage or {}).get(k) or 0)

    if not partials:
        raise RuntimeError("All comment batches failed AI parsing.")

    if len(partials) == 1:
        final = partials[0]
    else:
        merge_user = _build_merge_prompt(partials, project)
        content, usage = call_ai(
            provider,
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": merge_user}],
            api_keys,
            180,
        )
        for k in total_usage:
            total_usage[k] += int((usage or {}).get(k) or 0)
        try:
            final = _safe_json_parse(content)
        except Exception:
            final = partials[0]

    final["_meta"] = {
        "comments_analyzed": len(deduped),
        "raw_comments_fetched": len(raw),
        "chunks": len(chunks),
        "window_days": days,
        "usage": total_usage,
    }
    store.save_report(
        slug,
        "comments",
        final,
        provider=provider,
        model=model,
        input_summary=f"{len(deduped)} comments, {len(chunks)} batches",
    )
    return final
