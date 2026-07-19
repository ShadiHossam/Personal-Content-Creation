from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, String, or_, asc
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime

from ..database import get_db
from ..models import Source, SourceItem, Setting

router = APIRouter(prefix="/api/sources", tags=["sources"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class SourceIn(BaseModel):
    name: str
    url: str
    rss_url: Optional[str] = None
    notes: Optional[str] = None
    fetch_from_date: Optional[datetime] = None
    priority: int = 3
    category: Optional[str] = None
    tags: List[str] = []


class SourceOut(BaseModel):
    id: int
    name: str
    url: str
    rss_url: Optional[str]
    notes: Optional[str]
    fetch_from_date: Optional[datetime]
    last_fetched_at: Optional[datetime]
    created_at: datetime
    priority: int = 3
    category: Optional[str] = None
    tags: List[str] = []
    unread_count: Optional[int] = 0
    total_count: Optional[int] = 0
    oldest_post_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SourceItemOut(BaseModel):
    id: int
    source_id: int
    source_name: Optional[str] = None
    source_priority: Optional[int] = 3
    source_category: Optional[str] = None
    title: str
    body: Optional[str]
    url: Optional[str]
    published_at: Optional[datetime]
    topic_tags: Optional[list] = []
    user_tags: Optional[list] = []
    is_read: bool
    is_saved: bool

    model_config = {"from_attributes": True}


class BulkCreateIn(BaseModel):
    sources: List[SourceIn]


class BulkDeleteIn(BaseModel):
    ids: List[int]


class BulkUpdateIn(BaseModel):
    ids: List[int]
    priority: Optional[int] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None


class ItemTagsIn(BaseModel):
    tags: List[str]


class BulkTagsIn(BaseModel):
    ids: List[int]
    tags: List[str]
    mode: Literal["set", "add", "remove"] = "set"


class AIRecommendIn(BaseModel):
    provider: str
    model: str
    source_ids: List[int] = []
    num_topics: int = 5


# ─── Helper ──────────────────────────────────────────────────────────────────

def _source_out(s: Source, db: Session) -> SourceOut:
    unread = db.query(func.count(SourceItem.id)).filter(
        SourceItem.source_id == s.id,
        SourceItem.is_read == False
    ).scalar()
    total = db.query(func.count(SourceItem.id)).filter(
        SourceItem.source_id == s.id
    ).scalar()
    oldest = db.query(func.min(SourceItem.published_at)).filter(
        SourceItem.source_id == s.id
    ).scalar()
    out = SourceOut.model_validate(s)
    out.unread_count = unread
    out.total_count = total
    out.oldest_post_at = oldest
    out.tags = s.tags or []
    return out


# ─── Bulk Source Operations (must be before /{source_id} routes) ─────────────

@router.post("/bulk-create", response_model=List[SourceOut])
def bulk_create_sources(data: BulkCreateIn, db: Session = Depends(get_db)):
    existing_urls = {s.url for s in db.query(Source.url).all()}
    created = []
    for item in data.sources:
        if item.url in existing_urls:
            continue
        s = Source(**item.model_dump())
        db.add(s)
        db.flush()
        existing_urls.add(item.url)
        created.append(s)
    db.commit()
    return [_source_out(s, db) for s in created]


@router.delete("/bulk-delete")
def bulk_delete_sources(data: BulkDeleteIn, db: Session = Depends(get_db)):
    deleted = db.query(Source).filter(Source.id.in_(data.ids)).all()
    count = len(deleted)
    for s in deleted:
        db.delete(s)
    db.commit()
    return {"ok": True, "deleted_count": count}


@router.put("/bulk-update")
def bulk_update_sources(data: BulkUpdateIn, db: Session = Depends(get_db)):
    sources = db.query(Source).filter(Source.id.in_(data.ids)).all()
    for s in sources:
        if data.priority is not None:
            s.priority = data.priority
        if data.category is not None:
            s.category = data.category
        if data.tags is not None:
            s.tags = data.tags
    db.commit()
    return {"ok": True, "updated_count": len(sources)}


# ─── Source CRUD (after bulk routes to avoid /{source_id} shadowing) ──────────

@router.get("", response_model=List[SourceOut])
def list_sources(db: Session = Depends(get_db)):
    sources = db.query(Source).order_by(Source.priority.asc(), Source.name.asc()).all()
    source_ids = [s.id for s in sources]

    if source_ids:
        total_counts = dict(
            db.query(SourceItem.source_id, func.count(SourceItem.id))
            .filter(SourceItem.source_id.in_(source_ids))
            .group_by(SourceItem.source_id).all()
        )
        unread_counts = dict(
            db.query(SourceItem.source_id, func.count(SourceItem.id))
            .filter(SourceItem.source_id.in_(source_ids), SourceItem.is_read == False)
            .group_by(SourceItem.source_id).all()
        )
        oldest_dates = dict(
            db.query(SourceItem.source_id, func.min(SourceItem.published_at))
            .filter(SourceItem.source_id.in_(source_ids))
            .group_by(SourceItem.source_id).all()
        )
    else:
        total_counts, unread_counts, oldest_dates = {}, {}, {}

    result = []
    for s in sources:
        out = SourceOut.model_validate(s)
        out.unread_count = unread_counts.get(s.id, 0)
        out.total_count = total_counts.get(s.id, 0)
        out.oldest_post_at = oldest_dates.get(s.id)
        out.tags = s.tags or []
        result.append(out)
    return result


@router.post("", response_model=SourceOut)
def create_source(data: SourceIn, db: Session = Depends(get_db)):
    source = Source(**data.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_out(source, db)


@router.put("/{source_id}", response_model=SourceOut)
def update_source(source_id: int, data: SourceIn, db: Session = Depends(get_db)):
    s = db.query(Source).filter(Source.id == source_id).first()
    if not s:
        raise HTTPException(404, "Source not found")
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _source_out(s, db)


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    s = db.query(Source).filter(Source.id == source_id).first()
    if not s:
        raise HTTPException(404, "Source not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


# ─── Source Items ─────────────────────────────────────────────────────────────

@router.get("/items", response_model=List[SourceItemOut])
def list_source_items(
    source_ids: Optional[str] = None,
    source_id: Optional[int] = None,
    priorities: Optional[str] = None,
    tags: Optional[str] = None,
    categories: Optional[str] = None,
    saved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    q = db.query(SourceItem, Source.name.label("sname"), Source.priority.label("spriority"), Source.category.label("scategory")).join(Source)

    # source filter
    sid_list = []
    if source_ids:
        sid_list = [int(x) for x in source_ids.split(",") if x.strip().isdigit()]
    elif source_id:
        sid_list = [source_id]
    if sid_list:
        q = q.filter(SourceItem.source_id.in_(sid_list))

    # priority filter (filter sources by priority)
    if priorities:
        p_list = [int(x) for x in priorities.split(",") if x.strip().isdigit()]
        if p_list:
            q = q.filter(Source.priority.in_(p_list))

    # category filter
    if categories:
        cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        if cat_list:
            q = q.filter(Source.category.in_(cat_list))

    # tag filter (match either user_tags or topic_tags)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            conditions = []
            for t in tag_list:
                conditions.append(cast(SourceItem.user_tags, String).contains(f'"{t}"'))
                conditions.append(cast(SourceItem.topic_tags, String).contains(f'"{t}"'))
            q = q.filter(or_(*conditions))

    if saved is not None:
        q = q.filter(SourceItem.is_saved == saved)

    rows = q.order_by(SourceItem.published_at.desc()).offset(offset).limit(limit).all()

    result = []
    for item, src_name, src_priority, src_category in rows:
        out = SourceItemOut.model_validate(item)
        out.source_name = src_name
        out.source_priority = src_priority or 3
        out.source_category = src_category
        out.user_tags = item.user_tags or []
        out.topic_tags = item.topic_tags or []
        result.append(out)
    return result


@router.post("/items/{item_id}/save")
def save_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(SourceItem).filter(SourceItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    item.is_saved = True
    item.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/items/{item_id}/read")
def mark_read(item_id: int, db: Session = Depends(get_db)):
    item = db.query(SourceItem).filter(SourceItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    item.is_read = True
    db.commit()
    return {"ok": True}


@router.put("/items/{item_id}/tags")
def update_item_tags(item_id: int, data: ItemTagsIn, db: Session = Depends(get_db)):
    item = db.query(SourceItem).filter(SourceItem.id == item_id).first()
    if not item:
        raise HTTPException(404)
    item.user_tags = data.tags
    db.commit()
    return {"ok": True}


@router.put("/items/bulk-tags")
def bulk_update_item_tags(data: BulkTagsIn, db: Session = Depends(get_db)):
    items = db.query(SourceItem).filter(SourceItem.id.in_(data.ids)).all()
    for item in items:
        current = item.user_tags or []
        if data.mode == "set":
            item.user_tags = data.tags
        elif data.mode == "add":
            item.user_tags = list(set(current + data.tags))
        elif data.mode == "remove":
            item.user_tags = [t for t in current if t not in data.tags]
    db.commit()
    return {"ok": True, "updated_count": len(items)}


# ─── Meta: all known tags & categories ───────────────────────────────────────

@router.get("/meta")
def get_sources_meta(db: Session = Depends(get_db)):
    """Return all unique tags and categories across sources for filter/autocomplete."""
    sources = db.query(Source).all()
    all_tags = set()
    all_categories = set()
    for s in sources:
        if s.tags:
            all_tags.update(s.tags)
        if s.category:
            all_categories.add(s.category)
    # Also collect user_tags and topic_tags from items
    items = db.query(SourceItem.user_tags, SourceItem.topic_tags).all()
    for (utags, ttags) in items:
        if utags:
            all_tags.update(utags)
        if ttags:
            all_tags.update(ttags)
    return {
        "tags": sorted(all_tags),
        "categories": sorted(all_categories),
    }


# ─── AI Recommendations ───────────────────────────────────────────────────────

@router.post("/ai-recommend")
async def ai_recommend(data: AIRecommendIn, db: Session = Depends(get_db)):
    from ..ai.providers import get_provider, TokenMissingError, TokenInvalidError, RateLimitError, ClaudeCLINotFoundError

    # Get API key for provider
    key_map = {
        "groq": "ai_provider_groq_key",
        "openrouter": "ai_provider_openrouter_key",
        "gemini": "ai_provider_gemini_key",
        "together": "ai_provider_together_key",
        "claude_cli": None,
    }
    api_key = None
    if data.provider != "claude_cli":
        key_setting = key_map.get(data.provider)
        if key_setting:
            row = db.query(Setting).filter(Setting.key == key_setting).first()
            api_key = row.value if row else None

    try:
        provider = get_provider(data.provider, api_key)
    except TokenMissingError:
        raise HTTPException(422, detail={"error": "token_missing", "provider": data.provider})
    except ClaudeCLINotFoundError:
        raise HTTPException(422, detail={"error": "cli_not_found"})

    # Gather recent articles
    q = db.query(SourceItem, Source.name).join(Source)
    if data.source_ids:
        q = q.filter(SourceItem.source_id.in_(data.source_ids))
    articles = q.order_by(SourceItem.published_at.desc()).limit(30).all()

    if not articles:
        return {"topics": [], "tag_suggestions": []}

    # Build context
    article_summaries = []
    untagged_items = []
    for item, src_name in articles:
        excerpt = (item.body or "")[:200]
        article_summaries.append(f"- [{src_name}] {item.title}" + (f": {excerpt}" if excerpt else ""))
        if not (item.user_tags or item.topic_tags):
            untagged_items.append({"id": item.id, "title": item.title, "body": (item.body or "")[:300]})

    articles_text = "\n".join(article_summaries[:25])
    untagged_text = "\n".join([f"ID:{u['id']} - {u['title']}" for u in untagged_items[:15]])

    prompt = f"""You are a content strategy assistant. Based on these recent news articles, provide:

1. {data.num_topics} content topic ideas for a marketing/AI consultant who serves Arab business owners. Each topic should be actionable and relevant.

2. Tag suggestions for untagged articles (if any).

Recent articles:
{articles_text}

Untagged articles needing tags:
{untagged_text if untagged_text else "None"}

Respond in JSON format exactly like this:
{{
  "topics": [
    {{"title": "Topic title", "description": "1-2 sentence description", "angle": "Specific angle or hook"}}
  ],
  "tag_suggestions": [
    {{"item_id": 123, "suggested_tags": ["tag1", "tag2"]}}
  ]
}}"""

    try:
        raw = provider.complete([{"role": "user", "content": prompt}], data.model)
    except TokenInvalidError:
        raise HTTPException(422, detail={"error": "token_invalid", "provider": data.provider})
    except RateLimitError:
        raise HTTPException(429, detail={"error": "rate_limit"})
    except Exception as e:
        raise HTTPException(500, detail={"error": "provider_error", "message": str(e)})

    # Parse JSON from response
    import json, re
    try:
        # Extract JSON block if wrapped in markdown
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            result = json.loads(match.group())
        else:
            result = {"topics": [], "tag_suggestions": []}
    except Exception:
        result = {"topics": [], "tag_suggestions": []}

    return result
