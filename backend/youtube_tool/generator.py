"""Content pack generator.

Builds the prompt, calls the AI (via the shared ``_call_ai`` helper), and
returns the parsed JSON content pack. The AI is expected to return a single
JSON object — the parser is tolerant of markdown code fences.
"""

from __future__ import annotations

import json
import re

from .transcript_sources import format_timestamp, serialize_segments

SYSTEM_PROMPT = """You are a YouTube SEO strategist and video editor.

Given a video transcript, a YouTube project profile, and a keyword list,
produce a complete content pack for the video.

Output requirements:
- Respond with a SINGLE JSON object, nothing else. No prose, no markdown fences.
- The JSON must have these keys exactly: description, chapters,
  thumbnail_text_options, title_variants, tags, hashtags, shorts_clips.

Field definitions:
- description (string): 300-600 word YouTube description. First 120 characters
  must hook viewers and include a high-priority keyword. Include a clear CTA
  near the end. Weave high-priority keywords naturally. Add chapter timestamps
  at the bottom in "HH:MM - Title" format.
- chapters (array of {t, title}): 5-10 timestamped chapters. `t` is in
  "HH:MM:SS" or "MM:SS" format. First chapter MUST be "00:00". Use transcript
  timestamps when available; otherwise infer natural breakpoints from content.
- thumbnail_text_options (array of strings): 5 short, high-CTR thumbnail
  overlays. Each under 30 characters. Punchy, curiosity-driven or benefit-led.
- title_variants (array of strings): 8 title options, under 70 characters each,
  each using at least one keyword from the list. Mix styles: direct, question,
  list, emotional, contrarian.
- tags (array of strings): 12-15 YouTube tags ordered by relevance. Use all
  high-priority keywords first, then medium, then natural variations.
- hashtags (array of strings): exactly 3 hashtags, each starting with '#'.
- shorts_clips (array of {start, end, hook, caption}): 3-5 best 30-60 second
  clips for Shorts/Reels/TikTok. `start` and `end` in "HH:MM:SS" or "MM:SS".
  `hook` is the opening line (attention grabber). `caption` is a ready-to-post
  social caption under 220 characters.

Rules:
- Every priority=high keyword must appear at least once in description OR title_variants OR tags.
- Respect the project's brand voice, target audience, and language.
- If the transcript language differs from the project language, use the
  project language for output.
- Return valid JSON, properly escaped."""


def _safe_json_parse(raw: str) -> dict:
    """Extract a JSON object from an AI response that might be wrapped in fences."""
    s = raw.strip()
    # Strip ```json ... ``` fences
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n", "", s)
        s = re.sub(r"\n```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Last-ditch: find outermost {...} block
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            return json.loads(m[0])
        raise


def _project_block(project: dict | None) -> str:
    if not project:
        return ""
    parts = [f"## YouTube Project — {project.get('name', 'Unnamed')}"]
    if project.get("description"):
        parts.append(f"\n### About\n{project['description']}")
    if project.get("channel_url"):
        parts.append(f"\n### Channel URL\n{project['channel_url']}")
    lang_code = str(project.get("language") or "fr").strip().lower()
    dialect = str(project.get("arabic_dialect") or project.get("default_arabic_dialect") or "").strip().lower()
    dialect_labels = {
        "egyptian": "Egyptian Arabic (اللهجة المصرية) — Cairo/Alexandria colloquial, NOT MSA",
        "ksa": "Saudi Arabic (اللهجة السعودية) — Najdi/Hijazi colloquial, NOT MSA",
        "uae": "Emirati Arabic (اللهجة الإماراتية) — Khaleeji colloquial, NOT MSA",
        "kuwait": "Kuwaiti Arabic (اللهجة الكويتية) — Khaleeji colloquial, NOT MSA",
    }
    if lang_code in {"ar", "arabic"} and dialect in dialect_labels:
        parts.append(
            f"\n### Output language\n{dialect_labels[dialect]}\n"
            f"(arabic_dialect_code: {dialect}. Write ALL copy in this dialect, not MSA.)"
        )
    else:
        parts.append(f"\n### Output language\n{project.get('language', 'fr')}")
    return "\n".join(parts)


def _keyword_block(keyword_list: dict | None) -> str:
    if not keyword_list or not keyword_list.get("keywords"):
        return ""
    by_priority = {"high": [], "medium": [], "low": []}
    for kw in keyword_list["keywords"]:
        pr = kw.get("priority", "medium")
        if pr not in by_priority:
            pr = "medium"
        note = f" ({kw['notes']})" if kw.get("notes") else ""
        by_priority[pr].append(f'"{kw["term"]}"{note}')
    lines = [f"## Keyword List — {keyword_list.get('name', '')}"]
    if keyword_list.get("description"):
        lines.append(f"_{keyword_list['description']}_")
    if by_priority["high"]:
        lines.append("\n### PRIORITY = HIGH (must appear)")
        lines.extend(f"- {t}" for t in by_priority["high"])
    if by_priority["medium"]:
        lines.append("\n### PRIORITY = MEDIUM (use if natural)")
        lines.extend(f"- {t}" for t in by_priority["medium"])
    if by_priority["low"]:
        lines.append("\n### PRIORITY = LOW (optional)")
        lines.extend(f"- {t}" for t in by_priority["low"])
    return "\n".join(lines)


def _transcript_block(transcript: dict) -> str:
    segments = transcript.get("segments") or []
    if segments:
        total = segments[-1]["end"] if segments else 0
        header = f"## Transcript (with timestamps, total duration {format_timestamp(total)})"
        return f"{header}\n\n{serialize_segments(segments)}"
    return f"## Transcript (no timestamps available)\n\n{transcript.get('text', '')}"


def build_prompt(transcript: dict, project: dict | None, keyword_list: dict | None) -> str:
    parts = [
        _project_block(project),
        _keyword_block(keyword_list),
        _transcript_block(transcript),
        "\n---\n\nReturn the JSON content pack now.",
    ]
    return "\n\n".join(p for p in parts if p).strip()


def generate_content_pack(
    transcript: dict,
    project: dict | None,
    keyword_list: dict | None,
    call_ai,
    provider: str = "claude_cli",
    model: str = "",
    api_keys: dict | None = None,
) -> dict:
    """Run the generation. `call_ai` is an injected callable matching
    server._call_ai's signature: (provider, model, messages, api_keys) -> (content, usage).
    """
    api_keys = api_keys or {}
    prompt = build_prompt(transcript, project, keyword_list)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    content, usage = call_ai(provider, model, messages, api_keys)
    try:
        pack = _safe_json_parse(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI returned invalid JSON: {exc}\n\nRaw output:\n{content[:2000]}") from exc

    return {
        "pack": pack,
        "prompt_used": prompt,
        "usage": usage,
        "provider": provider,
        "model": model,
    }
