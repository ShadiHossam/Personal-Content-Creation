from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, or_
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import httpx
import re

from fastapi.responses import Response
import csv
import io
import json as json_lib

from ..database import get_db
from ..models import Creator, ContentItem, Comment, Setting, CreatorNote, CreatorTag

router = APIRouter(prefix="/api/creators", tags=["creators"])


def _get_setting(db: Session, key: str) -> Optional[str]:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


class CreatorIn(BaseModel):
    name: str
    country: Optional[str] = None
    category: str  # competitor | inspiration
    rank: Optional[int] = 999
    priority: Optional[int] = None
    linkedin_url: Optional[str] = None
    twitter_handle: Optional[str] = None
    instagram_handle: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    tiktok_handle: Optional[str] = None
    notes: Optional[str] = None
    scrape_max_posts: Optional[int] = None
    scrape_linkedin_actor: Optional[str] = None
    scrape_twitter_actor: Optional[str] = None
    scrape_include_replies: Optional[bool] = None
    scrape_include_retweets: Optional[bool] = None


class CreatorOut(BaseModel):
    id: int
    name: str
    country: Optional[str]
    category: str
    rank: int
    priority: Optional[int] = None
    tags: List[str] = []
    profile_image_url: Optional[str]
    profile_image_local: Optional[str]
    linkedin_url: Optional[str]
    twitter_handle: Optional[str]
    instagram_handle: Optional[str] = None
    youtube_channel_id: Optional[str]
    tiktok_handle: Optional[str] = None
    notes: Optional[str]
    scrape_max_posts: Optional[int]
    scrape_linkedin_actor: Optional[str]
    scrape_twitter_actor: Optional[str]
    scrape_include_replies: Optional[bool]
    scrape_include_retweets: Optional[bool]
    last_fetched_at: Optional[datetime]
    created_at: datetime
    new_items_count: Optional[int] = 0
    total_items_count: Optional[int] = 0
    oldest_post_date: Optional[datetime] = None
    newest_post_date: Optional[datetime] = None

    model_config = {"from_attributes": True}


@router.get("", response_model=List[CreatorOut])
def list_creators(category: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Creator)
    if category:
        q = q.filter(Creator.category == category)
    creators = q.order_by(Creator.rank).all()

    result = []
    for c in creators:
        new_count = db.query(func.count(ContentItem.id)).filter(
            ContentItem.creator_id == c.id,
            ContentItem.is_read == False
        ).scalar()
        total_count = db.query(func.count(ContentItem.id)).filter(
            ContentItem.creator_id == c.id
        ).scalar()
        out = CreatorOut.model_validate(c)
        out.new_items_count = new_count
        out.total_items_count = total_count
        out.tags = [t.tag_name for t in c.tags]
        result.append(out)
    return result


@router.post("", response_model=CreatorOut)
def create_creator(data: CreatorIn, db: Session = Depends(get_db)):
    creator = Creator(**data.model_dump())
    db.add(creator)
    db.commit()
    db.refresh(creator)
    out = CreatorOut.model_validate(creator)
    out.new_items_count = 0
    out.total_items_count = 0
    out.tags = []
    return out


@router.post("/lookup")
async def lookup_creator_url(payload: dict, db: Session = Depends(get_db)):
    """Detect platform and extract creator info from a pasted URL."""
    url = (payload.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "URL required")

    result = {
        "platform": None,
        "name": None,
        "country": None,
        "profile_image_url": None,
        "linkedin_url": None,
        "twitter_handle": None,
        "instagram_handle": None,
        "youtube_channel_id": None,
        "tiktok_handle": None,
    }

    # YouTube — try channel ID, @handle, /c/, /user/
    yt_channel_id_match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]+)", url)
    yt_handle_match = re.search(r"youtube\.com/@([a-zA-Z0-9_.\-]+)", url)
    yt_custom_match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.\-]+)", url)

    yt_identifier = None
    yt_id_mode = None
    if yt_channel_id_match:
        yt_identifier = yt_channel_id_match.group(1)
        yt_id_mode = "id"
    elif yt_handle_match:
        yt_identifier = yt_handle_match.group(1)
        yt_id_mode = "handle"
    elif yt_custom_match:
        yt_identifier = yt_custom_match.group(1)
        yt_id_mode = "handle"

    if yt_identifier:
        result["platform"] = "youtube"
        youtube_key = _get_setting(db, "youtube_api_key")
        if youtube_key:
            if yt_id_mode == "id":
                api_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet&id={yt_identifier}&key={youtube_key}"
            else:
                api_url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet&forHandle={yt_identifier}&key={youtube_key}"
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(api_url)
                    data = resp.json()
                    if data.get("items"):
                        ch = data["items"][0]
                        snippet = ch["snippet"]
                        result["youtube_channel_id"] = ch["id"]
                        result["name"] = snippet.get("title")
                        result["country"] = snippet.get("country")
                        thumbs = snippet.get("thumbnails", {})
                        result["profile_image_url"] = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            except Exception:
                pass
        if not result["youtube_channel_id"] and yt_id_mode == "id":
            result["youtube_channel_id"] = yt_identifier
        # Fallback: scrape the YouTube page for channelId when API didn't resolve it
        # (e.g. no API key, API failure, or quota exhausted on @handle/custom URL).
        if not result["youtube_channel_id"] and yt_id_mode == "handle":
            try:
                page_url = f"https://www.youtube.com/@{yt_identifier}"
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                }
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(page_url, headers=headers)
                    html = resp.text
                ch_match = (
                    re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]+)"', html)
                    or re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]+)"', html)
                    or re.search(r'youtube\.com/channel/(UC[a-zA-Z0-9_-]+)', html)
                )
                if ch_match:
                    result["youtube_channel_id"] = ch_match.group(1)
                    if not result.get("name"):
                        og_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                        title_match = re.search(r"<title>([^<]+)</title>", html)
                        title = None
                        if og_match:
                            title = og_match.group(1)
                        elif title_match:
                            title = title_match.group(1)
                            # YouTube titles end with " - YouTube"
                            title = re.sub(r"\s*-\s*YouTube\s*$", "", title).strip()
                        if title:
                            result["name"] = title
                    if not result.get("profile_image_url"):
                        og_img = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                        if og_img:
                            result["profile_image_url"] = og_img.group(1)
            except Exception:
                pass
        return result

    # Twitter / X
    tw_match = re.search(r"(?:twitter|x)\.com/([a-zA-Z0-9_]{1,50})(?:/|$|\?)", url)
    if tw_match:
        handle = tw_match.group(1)
        if handle.lower() not in ("home", "explore", "notifications", "messages", "i", "search", "settings"):
            result["platform"] = "twitter"
            result["twitter_handle"] = handle
            result["name"] = "@" + handle
            return result

    # LinkedIn
    li_match = re.search(r"linkedin\.com/(in|company)/([a-zA-Z0-9_\-]+)", url)
    if li_match:
        slug = li_match.group(2)
        result["platform"] = "linkedin"
        result["linkedin_url"] = f"https://www.linkedin.com/{li_match.group(1)}/{slug}/"
        result["name"] = slug.replace("-", " ").title()
        return result

    # Instagram
    ig_match = re.search(r"instagram\.com/([a-zA-Z0-9_.]{1,50})(?:/|$|\?)", url)
    if ig_match:
        handle = ig_match.group(1)
        if handle.lower() not in ("p", "reel", "explore", "accounts", "stories"):
            result["platform"] = "instagram"
            result["instagram_handle"] = handle
            result["name"] = "@" + handle
            return result

    # TikTok
    tt_match = re.search(r"tiktok\.com/@([a-zA-Z0-9_.]{1,50})(?:/|$|\?)", url)
    if tt_match:
        handle = tt_match.group(1)
        result["platform"] = "tiktok"
        result["tiktok_handle"] = handle
        result["name"] = "@" + handle
        return result

    raise HTTPException(400, "Could not detect platform. Paste a YouTube, Twitter/X, LinkedIn, Instagram, or TikTok URL.")


@router.post("/{creator_id}/import-posts")
def import_posts(creator_id: int, payload: dict, db: Session = Depends(get_db)):
    """Import LinkedIn posts from BeReach, Synscribe, or generic JSON export."""
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")

    raw_posts = payload.get("posts", [])
    if not isinstance(raw_posts, list):
        raise HTTPException(400, "Expected {\"posts\": [...]} with an array of post objects")

    imported = 0
    skipped = 0

    for post in raw_posts:
        # Flexible field mapping: support BeReach, Synscribe, and generic formats
        body = (
            post.get("text") or post.get("content") or post.get("body") or
            post.get("postContent") or post.get("post_content") or
            post.get("message") or post.get("description") or ""
        )
        url = (
            post.get("url") or post.get("postUrl") or post.get("post_url") or
            post.get("link") or post.get("shareUrl") or post.get("share_url") or ""
        )
        pub_raw = (
            post.get("date") or post.get("publishedAt") or post.get("published_at") or
            post.get("postedAt") or post.get("posted_at") or post.get("createdAt") or
            post.get("created_at") or post.get("timestamp") or ""
        )
        pub_date = None
        if pub_raw:
            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(str(pub_raw)[:26], fmt)
                    pub_date = dt.replace(tzinfo=timezone.utc) if not dt.tzinfo else dt
                    break
                except ValueError:
                    continue

        likes = int(post.get("likes") or post.get("numLikes") or post.get("reactions") or 0)
        comments = int(post.get("comments") or post.get("numComments") or post.get("comments_count") or 0)
        shares = int(post.get("shares") or post.get("numShares") or post.get("reposts") or 0)

        if not body:
            skipped += 1
            continue

        # Deduplicate by URL if present, otherwise by body prefix
        if url:
            existing = db.query(ContentItem).filter(ContentItem.url == url).first()
        else:
            prefix = body[:200]
            existing = db.query(ContentItem).filter(
                ContentItem.creator_id == creator_id,
                ContentItem.body.like(prefix[:50] + "%"),
            ).first()

        if existing:
            skipped += 1
            continue

        db.add(ContentItem(
            creator_id=creator_id,
            platform="linkedin",
            title=None,
            body=body[:2000],
            url=url or None,
            published_at=pub_date,
            format="text",
            likes=likes,
            comments_count=comments,
            shares=shares,
        ))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped}


@router.get("/{creator_id}/posts")
def creator_posts(
    creator_id: int,
    limit: int = 30,
    offset: int = 0,
    platform: Optional[str] = None,
    sort_by: str = "published_at",
    sort_dir: str = "desc",
    search: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    format: Optional[str] = None,
    min_likes: Optional[int] = None,
    has_media: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")

    q = db.query(ContentItem).filter(ContentItem.creator_id == creator_id)

    if platform:
        q = q.filter(ContentItem.platform == platform)

    if format:
        q = q.filter(ContentItem.format == format)

    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(or_(ContentItem.body.ilike(term), ContentItem.title.ilike(term)))

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

    if min_likes is not None and min_likes > 0:
        q = q.filter(ContentItem.likes >= min_likes)

    if has_media:
        q = q.filter(ContentItem.image_url.isnot(None))

    sort_col_map = {
        "published_at": ContentItem.published_at,
        "likes": ContentItem.likes,
        "comments_count": ContentItem.comments_count,
        "shares": ContentItem.shares,
    }
    col = sort_col_map.get(sort_by, ContentItem.published_at)
    order_fn = desc if sort_dir == "desc" else asc
    q = q.order_by(order_fn(col))

    total = q.with_entities(func.count(ContentItem.id)).scalar()
    items = q.limit(limit).offset(offset).all()

    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "platform": item.platform,
                "url": item.url,
                "title": item.title,
                "body": item.body,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "likes": item.likes,
                "comments_count": item.comments_count,
                "shares": item.shares,
                "format": item.format,
                "is_saved": item.is_saved,
                "image_url": item.image_url,
                "transcript": item.transcript,
            }
            for item in items
        ],
    }


@router.get("/tags", response_model=List[str])
def list_all_tags(db: Session = Depends(get_db)):
    rows = db.query(CreatorTag.tag_name).distinct().order_by(CreatorTag.tag_name).all()
    return [r[0] for r in rows]


@router.get("/{creator_id}", response_model=CreatorOut)
def get_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    new_count = db.query(func.count(ContentItem.id)).filter(
        ContentItem.creator_id == c.id,
        ContentItem.is_read == False
    ).scalar()
    total_count = db.query(func.count(ContentItem.id)).filter(
        ContentItem.creator_id == c.id
    ).scalar()
    oldest = db.query(func.min(ContentItem.published_at)).filter(
        ContentItem.creator_id == c.id
    ).scalar()
    newest = db.query(func.max(ContentItem.published_at)).filter(
        ContentItem.creator_id == c.id
    ).scalar()
    out = CreatorOut.model_validate(c)
    out.new_items_count = new_count
    out.total_items_count = total_count
    out.oldest_post_date = oldest
    out.newest_post_date = newest
    out.tags = [t.tag_name for t in c.tags]
    return out


@router.put("/{creator_id}", response_model=CreatorOut)
def update_creator(creator_id: int, data: CreatorIn, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    for k, v in data.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    out = CreatorOut.model_validate(c)
    out.new_items_count = 0
    out.total_items_count = 0
    out.tags = [t.tag_name for t in c.tags]
    return out


@router.delete("/{creator_id}")
def delete_creator(creator_id: int, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/reorder")
def reorder_creators(order: List[int], db: Session = Depends(get_db)):
    for rank, creator_id in enumerate(order, 1):
        db.query(Creator).filter(Creator.id == creator_id).update({"rank": rank})
    db.commit()
    return {"ok": True}


# ── Bulk actions ──

class BulkPriorityIn(BaseModel):
    ids: List[int]
    priority: Optional[int] = None

class BulkCategoryIn(BaseModel):
    ids: List[int]
    category: str

class BulkTagIn(BaseModel):
    ids: List[int]
    tag_name: str


@router.post("/bulk-set-priority")
def bulk_set_priority(data: BulkPriorityIn, db: Session = Depends(get_db)):
    db.query(Creator).filter(Creator.id.in_(data.ids)).update(
        {"priority": data.priority}, synchronize_session=False
    )
    db.commit()
    return {"ok": True, "updated": len(data.ids)}


@router.post("/bulk-set-category")
def bulk_set_category(data: BulkCategoryIn, db: Session = Depends(get_db)):
    db.query(Creator).filter(Creator.id.in_(data.ids)).update(
        {"category": data.category}, synchronize_session=False
    )
    db.commit()
    return {"ok": True, "updated": len(data.ids)}


@router.post("/bulk-add-tag")
def bulk_add_tag(data: BulkTagIn, db: Session = Depends(get_db)):
    tag_name = data.tag_name.strip()
    if not tag_name:
        raise HTTPException(400, "tag_name required")
    for cid in data.ids:
        exists = db.query(CreatorTag).filter(
            CreatorTag.creator_id == cid,
            CreatorTag.tag_name == tag_name
        ).first()
        if not exists:
            db.add(CreatorTag(creator_id=cid, tag_name=tag_name))
    db.commit()
    return {"ok": True}


@router.post("/bulk-remove-tag")
def bulk_remove_tag(data: BulkTagIn, db: Session = Depends(get_db)):
    db.query(CreatorTag).filter(
        CreatorTag.creator_id.in_(data.ids),
        CreatorTag.tag_name == data.tag_name
    ).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


@router.get("/export")
def export_creators(ids: List[int] = [], format: str = "json", db: Session = Depends(get_db)):
    creators = db.query(Creator).filter(Creator.id.in_(ids)).order_by(Creator.rank).all() if ids else []
    rows = []
    for c in creators:
        rows.append({
            "id": c.id,
            "name": c.name,
            "country": c.country,
            "category": c.category,
            "priority": c.priority,
            "tags": [t.tag_name for t in c.tags],
            "linkedin_url": c.linkedin_url,
            "twitter_handle": c.twitter_handle,
            "instagram_handle": c.instagram_handle,
            "youtube_channel_id": c.youtube_channel_id,
            "tiktok_handle": c.tiktok_handle,
            "notes": c.notes,
        })

    if format == "csv":
        output = io.StringIO()
        fields = ["id", "name", "country", "category", "priority", "tags",
                  "linkedin_url", "twitter_handle", "instagram_handle",
                  "youtube_channel_id", "tiktok_handle", "notes"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            row["tags"] = ",".join(row["tags"])
            writer.writerow(row)
        content = output.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=creators.csv"}
        )

    content = json_lib.dumps(rows, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=creators.json"}
    )


@router.get("/{creator_id}/notes")
def list_creator_notes(creator_id: int, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    notes = db.query(CreatorNote).filter(CreatorNote.creator_id == creator_id).order_by(CreatorNote.created_at.desc()).all()
    return [{"id": n.id, "content": n.content, "created_at": n.created_at.isoformat()} for n in notes]


@router.post("/{creator_id}/notes")
def add_creator_note(creator_id: int, payload: dict, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "Note content required")
    note = CreatorNote(creator_id=creator_id, content=content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"id": note.id, "content": note.content, "created_at": note.created_at.isoformat()}


@router.delete("/{creator_id}/notes/{note_id}")
def delete_creator_note(creator_id: int, note_id: int, db: Session = Depends(get_db)):
    note = db.query(CreatorNote).filter(CreatorNote.id == note_id, CreatorNote.creator_id == creator_id).first()
    if not note:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
    return {"ok": True}


@router.post("/{creator_id}/tags")
def add_creator_tag(creator_id: int, payload: dict, db: Session = Depends(get_db)):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")
    tag_name = (payload.get("tag_name") or "").strip()
    if not tag_name:
        raise HTTPException(400, "tag_name required")
    existing = db.query(CreatorTag).filter(
        CreatorTag.creator_id == creator_id,
        CreatorTag.tag_name == tag_name
    ).first()
    if not existing:
        db.add(CreatorTag(creator_id=creator_id, tag_name=tag_name))
        db.commit()
    return {"ok": True, "tag_name": tag_name}


@router.delete("/{creator_id}/tags/{tag_name}")
def delete_creator_tag(creator_id: int, tag_name: str, db: Session = Depends(get_db)):
    tag = db.query(CreatorTag).filter(
        CreatorTag.creator_id == creator_id,
        CreatorTag.tag_name == tag_name
    ).first()
    if not tag:
        raise HTTPException(404, "Tag not found")
    db.delete(tag)
    db.commit()
    return {"ok": True}


@router.get("/{creator_id}/stats")
def creator_stats(
    creator_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
):
    c = db.query(Creator).filter(Creator.id == creator_id).first()
    if not c:
        raise HTTPException(404, "Creator not found")

    query = db.query(ContentItem).filter(ContentItem.creator_id == creator_id)
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            query = query.filter(
                func.coalesce(ContentItem.published_at, ContentItem.fetched_at) >= sd
            )
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
            query = query.filter(
                func.coalesce(ContentItem.published_at, ContentItem.fetched_at) <= ed
            )
        except ValueError:
            pass

    items = query.all()
    if not items:
        return {"total": 0, "platforms": {}, "formats": {}, "engagement": {}, "frequency": "unknown", "best_day": "unknown"}

    platforms = {}
    formats = {}
    total_likes = total_comments = total_shares = 0

    for item in items:
        platforms[item.platform] = platforms.get(item.platform, 0) + 1
        fmt = item.format or "text"
        formats[fmt] = formats.get(fmt, 0) + 1
        total_likes += item.likes or 0
        total_comments += item.comments_count or 0
        total_shares += item.shares or 0

    n = len(items)
    avg_engagement = round((total_likes + total_comments + total_shares) / n, 1) if n else 0

    # posting frequency — use published_at, fall back to fetched_at
    from collections import Counter

    def _item_date(item):
        d = item.published_at or item.fetched_at
        if d and d.tzinfo:
            from datetime import timezone as _tz
            d = d.astimezone(_tz.utc).replace(tzinfo=None)
        return d

    using_fallback = not any(i.published_at for i in items)
    dates = sorted([_item_date(i) for i in items if _item_date(i)])
    freq_label = "unknown"
    if len(dates) >= 2:
        span_days = (dates[-1] - dates[0]).days or 1
        ppw = n / (span_days / 7)
        if ppw >= 7:
            freq_label = "Daily"
        elif ppw >= 4:
            freq_label = f"{round(ppw, 1)}x/week"
        elif ppw >= 2:
            freq_label = f"{round(ppw, 1)}x/week"
        elif ppw >= 0.75:
            freq_label = "Weekly"
        else:
            freq_label = "Sporadic"
        if using_fallback:
            freq_label = f"~{freq_label}"

    # best posting day
    day_counts = Counter(
        _item_date(i).strftime("%A") for i in items if _item_date(i)
    )
    best_day = day_counts.most_common(1)[0][0] if day_counts else "unknown"

    return {
        "total": n,
        "platforms": platforms,
        "formats": formats,
        "engagement": {
            "avg_likes": round(total_likes / n, 1),
            "avg_comments": round(total_comments / n, 1),
            "avg_shares": round(total_shares / n, 1),
            "avg_total": avg_engagement,
        },
        "frequency": freq_label,
        "best_day": best_day,
    }
