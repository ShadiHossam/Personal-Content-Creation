"""Follow-up chat on top of a saved channel-analysis report.

Given a slug and report kind ('performance' or 'comments'), builds a concise
system prompt that grounds the AI in the stored report payload plus a compact
snapshot of the channel, then sends the user's message along with prior turns.
Returns the AI reply + the `usage` dict so the UI can show a cost estimate.
"""

from __future__ import annotations

import json
from typing import Callable

from . import channel_store as store

SYSTEM_TEMPLATE = """You are a YouTube growth analyst answering follow-up questions about a channel you already analyzed.

## Channel snapshot
{channel_block}

## Totals
{totals_block}

## Latest {kind_label} report (your earlier output)
```json
{report_json}
```

Rules:
- Ground every claim in the report and the channel data above. If the user asks something
  the data doesn't cover, say so and suggest what to fetch/analyze next.
- Be concrete and actionable. When quoting a video, use its title (and ID if helpful).
- Use plain text; tables allowed but no code blocks unless showing data.
- Keep answers under ~300 words unless the user asks for depth.
"""


def _channel_block(ch):
    if not ch:
        return "(no channel row stored yet)"
    return (
        f"- Title: {ch.get('title')}\n"
        f"- Subscribers: {ch.get('subscriber_count')}\n"
        f"- Total views (API): {ch.get('view_count')}\n"
        f"- Videos (API): {ch.get('video_count')}\n"
        f"- Last sync: {ch.get('last_sync_at')}"
    )


def _totals_block(t):
    if not t:
        return "(no local totals)"
    return (
        f"- Local videos: {t.get('videos')}\n"
        f"- Stored comments: {t.get('total_comments')}\n"
        f"- Avg engagement: {round((t.get('avg_engagement') or 0) * 100, 2)}%"
    )


def build_system_prompt(slug, kind):
    report = store.get_latest_report(slug, kind)
    if not report:
        raise RuntimeError(f"No '{kind}' report stored for this channel yet. Generate one first.")
    ch = store.get_channel(slug) or {}
    totals = store.channel_totals(slug) or {}
    kind_label = "performance" if kind == "performance" else "comments"
    return SYSTEM_TEMPLATE.format(
        channel_block=_channel_block(ch),
        totals_block=_totals_block(totals),
        kind_label=kind_label,
        report_json=json.dumps(report.get("payload") or {}, ensure_ascii=False, indent=2)[:40000],
    )


CallAi = Callable[[str, str, list, dict, int], tuple]


def chat(
    slug,
    kind,
    history,
    user_message,
    call_ai: CallAi,
    provider="claude_cli",
    model="",
    api_keys=None,
):
    api_keys = api_keys or {}
    system = build_system_prompt(slug, kind)
    messages = [{"role": "system", "content": system}]
    for turn in (history or [])[-12:]:  # cap context
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": (user_message or "").strip()})

    reply, usage = call_ai(provider, model, messages, api_keys, 180)
    return {
        "reply": reply,
        "usage": usage or {},
        "provider": provider,
        "model": model,
    }
