"""YouTube Content Pack route.

Mirrors the SASS project's `/api/youtube/generate` endpoint, simplified for the
branding project's stack:
  - FastAPI + SQLAlchemy `Depends(get_db)` (same pattern as write.py)
  - Centralized Claude client (`backend.ai.client`) — supports both Anthropic
    API key and the local `claude` CLI subscription, mirroring write.py.
  - Two transcript sources: pasted text and a YouTube URL (text + URL only —
    SRT/VTT/audio file uploads are out of scope for the branding port).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import json

from ..database import get_db

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


class Keyword(BaseModel):
    term: str
    priority: str = "medium"  # high | medium | low
    notes: Optional[str] = None


class GeneratePackRequest(BaseModel):
    transcript_text: Optional[str] = None
    transcript_url: Optional[str] = None
    project_name: str = "My Channel"
    project_description: Optional[str] = None
    project_language: str = "en"
    arabic_dialect: Optional[str] = None
    keywords: List[Keyword] = []


@router.post("/generate-pack")
def generate_pack(data: GeneratePackRequest, db: Session = Depends(get_db)):
    # 1. Resolve Claude backend (api key OR claude CLI), same flow as write.py
    from ..ai.client import resolve_backend, call_ai

    try:
        backend, api_key = resolve_backend(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # 2. Build the transcript dict {text, segments[]}
    from ..youtube_tool.transcript_sources import from_text, from_youtube_url

    if data.transcript_url and data.transcript_url.strip():
        try:
            transcript = from_youtube_url(data.transcript_url.strip())
        except Exception as e:
            raise HTTPException(400, f"Could not fetch transcript from URL: {e}")
    elif data.transcript_text and data.transcript_text.strip():
        transcript = from_text(data.transcript_text)
    else:
        raise HTTPException(400, "Provide either transcript_text or transcript_url")

    if not (transcript.get("text") or "").strip():
        raise HTTPException(400, "Transcript is empty after parsing")

    # 3. Build the project + keyword_list dicts the generator expects
    project = {
        "name": data.project_name,
        "description": data.project_description or "",
        "language": data.project_language,
        "arabic_dialect": data.arabic_dialect or "",
    }
    keyword_list = (
        {
            "name": "Keywords",
            "keywords": [kw.model_dump() for kw in data.keywords],
        }
        if data.keywords
        else None
    )

    # 4. Build the prompt and call Claude (api or cli)
    from ..youtube_tool.generator import build_prompt, SYSTEM_PROMPT, _safe_json_parse

    prompt = build_prompt(transcript, project, keyword_list)

    try:
        raw = call_ai(prompt, system=SYSTEM_PROMPT, db=db, max_tokens=4096)
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    # 5. Parse the JSON content pack
    try:
        pack = _safe_json_parse(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"AI returned invalid JSON: {exc}")

    return {
        "pack": pack,
        "segments_count": len(transcript.get("segments") or []),
        "backend": backend,
    }
