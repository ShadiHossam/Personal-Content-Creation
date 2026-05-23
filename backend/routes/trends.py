import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Setting
from ..scrapers.trends import (
    fetch_google_trending,
    fetch_keyword_interest,
    fetch_youtube_trending,
)

router = APIRouter(prefix="/api/trends", tags=["trends"])


def _get_setting(db: Session, key: str) -> Optional[str]:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


class KeywordInterestRequest(BaseModel):
    keywords: List[str]
    region: str = "SA"
    timeframe: str = "30d"


@router.post("/google/trending")
async def google_trending(
    region: str = Query(default="SA"),
    db: Session = Depends(get_db),
):
    try:
        result = await asyncio.to_thread(fetch_google_trending, region)
    except RuntimeError as e:
        msg = str(e).lower()
        if "429" in msg or "rate" in msg or "too many" in msg:
            raise HTTPException(429, "Rate limited by Google Trends. Try again in a few minutes.")
        raise HTTPException(502, f"Google Trends error: {e}")
    return result


@router.post("/google/keywords")
async def google_keywords(
    body: KeywordInterestRequest,
    db: Session = Depends(get_db),
):
    if not body.keywords or len(body.keywords) > 5:
        raise HTTPException(400, "Provide 1–5 keywords.")
    keywords = [k.strip() for k in body.keywords if k.strip()]
    if not keywords:
        raise HTTPException(400, "Keywords cannot be empty.")
    try:
        result = await asyncio.to_thread(
            fetch_keyword_interest, keywords, body.region, body.timeframe
        )
    except RuntimeError as e:
        msg = str(e).lower()
        if "429" in msg or "rate" in msg or "too many" in msg:
            raise HTTPException(429, "Rate limited by Google Trends. Try again in a few minutes.")
        raise HTTPException(502, f"Google Trends error: {e}")
    return result


@router.get("/youtube")
async def youtube_trending(
    region: str = Query(default="SA"),
    category_id: str = Query(default=""),
    max_results: int = Query(default=20),
    db: Session = Depends(get_db),
):
    api_key = _get_setting(db, "youtube_api_key")
    if not api_key:
        raise HTTPException(400, "YouTube API key not configured. Add it in Settings.")
    try:
        result = await fetch_youtube_trending(api_key, region, category_id, max_results)
    except Exception as e:
        raise HTTPException(502, f"YouTube API error: {e}")
    return result
