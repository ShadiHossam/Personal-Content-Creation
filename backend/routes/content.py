from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_db
from ..models import ContentItem, Comment, Creator, Setting

router = APIRouter(prefix="/api/content", tags=["content"])


class ContentItemOut(BaseModel):
    id: int
    creator_id: int
    creator_name: Optional[str] = None
    creator_category: Optional[str] = None
    creator_image_url: Optional[str] = None
    platform: str
    title: Optional[str]
    body: Optional[str]
    url: Optional[str]
    published_at: Optional[datetime]
    format: Optional[str]
    likes: int
    comments_count: int
    shares: int
    is_read: bool
    is_saved: bool
    transcript: Optional[str] = None
    image_url: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("", response_model=List[ContentItemOut])
def list_content(
    platform: Optional[str] = None,
    category: Optional[str] = None,
    creator_id: Optional[int] = None,
    saved: Optional[bool] = None,
    unread_only: bool = False,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    q = db.query(ContentItem, Creator.name.label("cname"), Creator.category.label("ccat"), Creator.profile_image_url.label("cimg")).join(Creator)
    if platform:
        q = q.filter(ContentItem.platform == platform)
    if creator_id:
        q = q.filter(ContentItem.creator_id == creator_id)
    if category:
        q = q.filter(Creator.category == category)
    if saved is not None:
        q = q.filter(ContentItem.is_saved == saved)
    if unread_only:
        q = q.filter(ContentItem.is_read == False)
    if from_date:
        try:
            dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q = q.filter(ContentItem.published_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q = q.filter(ContentItem.published_at <= dt)
        except ValueError:
            pass

    rows = q.order_by(ContentItem.published_at.desc()).offset(offset).limit(limit).all()

    result = []
    for item, cname, ccat, cimg in rows:
        out = ContentItemOut.model_validate(item)
        out.creator_name = cname
        out.creator_category = ccat
        out.creator_image_url = cimg
        result.append(out)
    return result


@router.post("/{item_id}/save")
def save_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    item.is_saved = True
    item.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/{item_id}/skip")
def skip_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    item.is_read = True
    db.commit()
    return {"ok": True}


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db)):
    count = db.query(func.count(ContentItem.id)).filter(ContentItem.is_read == False).scalar()
    return {"count": count}


@router.post("/{item_id}/fetch-details", response_model=ContentItemOut)
async def fetch_item_details(item_id: int, db: Session = Depends(get_db)):
    item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    if item.platform != "youtube":
        raise HTTPException(400, "fetch-details is only supported for YouTube videos")

    video_id = item.url.split("v=")[-1].split("&")[0] if item.url and "v=" in item.url else ""
    if not video_id:
        raise HTTPException(400, "Could not extract video ID from URL")

    api_key_row = db.query(Setting).filter(Setting.key == "youtube_api_key").first()
    api_key = api_key_row.value if api_key_row else None
    if not api_key:
        raise HTTPException(400, "YouTube API key not set — add it in Settings")

    from ..scrapers.youtube import (
        fetch_video_full_description,
        fetch_all_video_comments,
        fetch_video_transcript,
    )

    # Full description (no truncation)
    description = await fetch_video_full_description(video_id, api_key)
    if description:
        item.body = description

    # All comments (paginated, up to 200)
    db.query(Comment).filter(Comment.content_item_id == item.id).delete()
    comments = await fetch_all_video_comments(video_id, api_key, max_results=200)
    for c in comments:
        db.add(Comment(content_item_id=item.id, **c))
    item.comments_count = len(comments)

    # Transcript — no error if unavailable
    item.transcript = await fetch_video_transcript(video_id)

    db.commit()
    db.refresh(item)
    return item
