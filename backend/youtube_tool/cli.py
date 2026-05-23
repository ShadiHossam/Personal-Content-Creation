"""CLI entry point.

Usage:
  python -m youtube_tool.cli --source text --input transcript.txt \\
      --project dubai-company-setup --list 1 -o pack.json

  python -m youtube_tool.cli --source url \\
      --input "https://www.youtube.com/watch?v=XYZ" \\
      --project 1 --list 1

  python -m youtube_tool.cli --source srt --input captions.srt \\
      --project 1 --list 2

  python -m youtube_tool.cli --source audio --input video.mp4 \\
      --project 1 --list 1 --whisper-model small
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import admin_bridge, transcript_sources
from .generator import generate_content_pack


def _load_transcript(source: str, raw_input: str, whisper_model: str) -> dict:
    if source == "text":
        if os.path.isfile(raw_input):
            with open(raw_input, encoding="utf-8") as f:
                return transcript_sources.from_text(f.read())
        return transcript_sources.from_text(raw_input)
    if source == "srt" or source == "vtt":
        return transcript_sources.from_srt_vtt(raw_input)
    if source == "url":
        return transcript_sources.from_youtube_url(raw_input)
    if source == "audio":
        return transcript_sources.from_audio(raw_input, model_size=whisper_model)
    raise ValueError(f"Unknown source type: {source}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a YouTube content pack from a video transcript.")
    parser.add_argument(
        "--source", required=True, choices=["text", "srt", "vtt", "url", "audio"], help="Transcript source type."
    )
    parser.add_argument("--input", required=True, help="Path or URL or raw text (depends on --source).")
    parser.add_argument("--project", required=True, help="YouTube project ID or slug.")
    parser.add_argument("--list", dest="list_id", required=True, help="Keyword list ID.")
    parser.add_argument("--output", "-o", help="Write JSON output to this path (default: stdout).")
    parser.add_argument(
        "--provider",
        default="claude_cli",
        help="AI provider (default: claude_cli — uses local Claude CLI subscription).",
    )
    parser.add_argument("--model", default="", help="Model override (optional).")
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="faster-whisper model size (only used with --source audio).",
    )
    args = parser.parse_args(argv)

    project = admin_bridge.get_project(args.project)
    if not project:
        print(f"ERROR: Project not found: {args.project}", file=sys.stderr)
        print("Available projects:", file=sys.stderr)
        for p in admin_bridge.list_projects():
            print(f"  id={p.get('id')} slug={p.get('slug')} name={p.get('name')}", file=sys.stderr)
        return 2

    keyword_list = admin_bridge.get_keyword_list(args.list_id)
    if not keyword_list:
        print(f"ERROR: Keyword list not found: {args.list_id}", file=sys.stderr)
        print(f"Available lists for project {project.get('name')}:", file=sys.stderr)
        for lst in admin_bridge.list_keyword_lists(project["id"]):
            print(f"  id={lst.get('id')} name={lst.get('name')}", file=sys.stderr)
        return 2

    print(f"Loading transcript via '{args.source}'...", file=sys.stderr)
    transcript = _load_transcript(args.source, args.input, args.whisper_model)
    n_segs = len(transcript.get("segments") or [])
    n_chars = len(transcript.get("text") or "")
    print(f"  {n_segs} segments, {n_chars} characters.", file=sys.stderr)

    # Lazy-import the shared AI caller to avoid importing Flask/server when not needed.
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from server import _call_ai

    print(f"Calling AI provider={args.provider}...", file=sys.stderr)
    result = generate_content_pack(
        transcript=transcript,
        project=project,
        keyword_list=keyword_list,
        call_ai=_call_ai,
        provider=args.provider,
        model=args.model,
        api_keys={},
    )
    print(f"  usage: {result.get('usage', {}).get('total_tokens', '?')} tokens", file=sys.stderr)

    output_json = json.dumps(result["pack"], indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Wrote: {args.output}", file=sys.stderr)
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
