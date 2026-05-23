"""Transcript input handlers.

Each handler returns a dict with:
  {"text": str, "segments": [{"start": float, "end": float, "text": str}]}

`segments` is empty for plain-text input (no timestamps available).
"""

from __future__ import annotations

import os
import re


def _seconds_to_float(h: int, m: int, s: int, ms: int = 0) -> float:
    return h * 3600 + m * 60 + s + ms / 1000.0


def from_text(raw: str) -> dict:
    return {"text": (raw or "").strip(), "segments": []}


def from_srt_vtt(path: str) -> dict:
    """Parse .srt or .vtt files. Falls back to line-by-line text extraction."""
    with open(path, encoding="utf-8") as f:
        content = f.read()

    ext = os.path.splitext(path)[1].lower()
    segments: list[dict] = []

    if ext == ".srt":
        # Block format: index \n start --> end \n text lines \n (blank)
        blocks = re.split(r"\r?\n\r?\n+", content.strip())
        ts_re = re.compile(r"(\d{1,2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2}),(\d{3})")
        for block in blocks:
            m = ts_re.search(block)
            if not m:
                continue
            start = _seconds_to_float(int(m[1]), int(m[2]), int(m[3]), int(m[4]))
            end = _seconds_to_float(int(m[5]), int(m[6]), int(m[7]), int(m[8]))
            lines = block.split("\n")
            text_lines = [line for line in lines if not ts_re.search(line) and not line.strip().isdigit()]
            text = " ".join(line.strip() for line in text_lines if line.strip())
            if text:
                segments.append({"start": start, "end": end, "text": text})
    elif ext == ".vtt":
        ts_re = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})\.(\d{3})")
        blocks = re.split(r"\r?\n\r?\n+", content.strip())
        for block in blocks:
            m = ts_re.search(block)
            if not m:
                continue
            start = _seconds_to_float(int(m[1]), int(m[2]), int(m[3]), int(m[4]))
            end = _seconds_to_float(int(m[5]), int(m[6]), int(m[7]), int(m[8]))
            lines = block.split("\n")
            text_lines = [line for line in lines if not ts_re.search(line) and not line.startswith("WEBVTT")]
            text = " ".join(line.strip() for line in text_lines if line.strip())
            if text:
                segments.append({"start": start, "end": end, "text": text})
    else:
        raise ValueError(f"Unsupported caption file extension: {ext}. Use .srt or .vtt")

    full_text = " ".join(seg["text"] for seg in segments)
    return {"text": full_text, "segments": segments}


def _extract_youtube_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m[1]
    return None


def from_youtube_url(url: str, languages: list[str] | None = None) -> dict:
    """Fetch transcript from YouTube via youtube-transcript-api (no key required)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("youtube-transcript-api is not installed. Run: pip install youtube-transcript-api") from exc

    video_id = _extract_youtube_id(url)
    if not video_id:
        raise ValueError(f"Could not extract a YouTube video ID from: {url}")

    langs = languages or ["fr", "en", "ar", "es"]
    raw = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)

    segments = []
    for entry in raw:
        start = float(entry.get("start", 0))
        dur = float(entry.get("duration", 0))
        text = (entry.get("text") or "").replace("\n", " ").strip()
        if text:
            segments.append({"start": start, "end": start + dur, "text": text})

    full_text = " ".join(seg["text"] for seg in segments)
    return {"text": full_text, "segments": segments, "video_id": video_id}


def from_audio(path: str, model_size: str = "base") -> dict:
    """Transcribe a local audio/video file using faster-whisper (CPU, free)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper") from exc

    if not os.path.exists(path):
        raise FileNotFoundError(f"Audio/video file not found: {path}")

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    whisper_segments, _info = model.transcribe(path, beam_size=5)

    segments = []
    for seg in whisper_segments:
        text = (seg.text or "").strip()
        if text:
            segments.append({"start": float(seg.start), "end": float(seg.end), "text": text})

    full_text = " ".join(seg["text"] for seg in segments)
    return {"text": full_text, "segments": segments}


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS (drops hours if < 1 hour)."""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def serialize_segments(segments: list[dict]) -> str:
    """Render segments as '[MM:SS] text' lines, for prompt input."""
    return "\n".join(f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments)
