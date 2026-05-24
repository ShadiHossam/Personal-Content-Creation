from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import json
import re

from ..database import get_db
from ..models import Creator, ContentItem, Comment, CreatorInsight, HookLibrary, StyleExtract, BulkAnalysis

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class InsightOut(BaseModel):
    id: int
    creator_id: int
    title: Optional[str]
    question: Optional[str]
    answer: Optional[str]
    posts_analyzed: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class AskRequest(BaseModel):
    creator_id: int
    question: str
    limit: int = 20
    platform: Optional[str] = None


class SaveInsightRequest(BaseModel):
    creator_id: int
    title: str
    question: str
    answer: str
    posts_analyzed: int


@router.get("/insights/{creator_id}", response_model=List[InsightOut])
def list_insights(creator_id: int, db: Session = Depends(get_db)):
    return db.query(CreatorInsight).filter(
        CreatorInsight.creator_id == creator_id
    ).order_by(CreatorInsight.created_at.desc()).all()


@router.post("/insights", response_model=InsightOut)
def save_insight(data: SaveInsightRequest, db: Session = Depends(get_db)):
    insight = CreatorInsight(**data.model_dump())
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


@router.delete("/insights/{insight_id}")
def delete_insight(insight_id: int, db: Session = Depends(get_db)):
    ins = db.query(CreatorInsight).filter(CreatorInsight.id == insight_id).first()
    if not ins:
        raise HTTPException(404)
    db.delete(ins)
    db.commit()
    return {"ok": True}


@router.post("/ask")
async def ask_about_creator(data: AskRequest, db: Session = Depends(get_db)):
    creator = db.query(Creator).filter(Creator.id == data.creator_id).first()
    if not creator:
        raise HTTPException(404, "Creator not found")

    from ..ai.client import call_claude

    q = db.query(ContentItem).filter(ContentItem.creator_id == data.creator_id)
    if data.platform:
        q = q.filter(ContentItem.platform == data.platform)
    items = q.order_by(ContentItem.published_at.desc()).limit(data.limit).all()

    posts_text = []
    for item in items:
        entry = f"[{item.platform.upper()} | {item.published_at.strftime('%Y-%m-%d') if item.published_at else 'unknown'}] "
        entry += f"Likes: {item.likes}, Comments: {item.comments_count}, Shares: {item.shares}\n"
        if item.title:
            entry += f"Title: {item.title}\n"
        if item.body:
            entry += f"Content: {item.body[:500]}\n"
        comments = db.query(Comment).filter(Comment.content_item_id == item.id).limit(5).all()
        if comments:
            entry += "Comments: " + " | ".join(c.text[:100] for c in comments if c.text) + "\n"
        posts_text.append(entry)

    context = f"""Creator: {creator.name} ({creator.category})
Country: {creator.country or 'unknown'}
Platforms tracked: {', '.join(filter(None, [creator.linkedin_url and 'LinkedIn', creator.twitter_handle and 'Twitter', creator.youtube_channel_id and 'YouTube']))}
Total posts analyzed: {len(items)}

--- POSTS ---
{chr(10).join(posts_text)}
"""

    try:
        answer = call_claude(
            f"{context}\n\nQuestion: {data.question}",
            system="You are a content strategy analyst. Analyze the provided social media posts and answer the user's question with specific, actionable insights. Be concise and data-driven.",
            db=db,
            max_tokens=1500,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    return {"answer": answer, "posts_analyzed": len(items)}


@router.post("/full-analysis")
async def full_analysis(creator_id: int, limit: int = 30, db: Session = Depends(get_db)):
    creator = db.query(Creator).filter(Creator.id == creator_id).first()
    if not creator:
        raise HTTPException(404)

    from ..ai.client import call_claude

    items = db.query(ContentItem).filter(
        ContentItem.creator_id == creator_id
    ).order_by(ContentItem.published_at.desc()).limit(limit).all()

    posts_text = []
    for item in items:
        entry = f"[{item.platform.upper()} | {item.published_at.strftime('%Y-%m-%d') if item.published_at else 'unknown'}] "
        entry += f"Likes: {item.likes or 0}, Comments: {item.comments_count or 0}, Shares: {item.shares or 0}\n"
        if item.title:
            entry += f"Title: {item.title}\n"
        if item.body:
            entry += f"Content: {item.body[:400]}\n"
        posts_text.append(entry)

    context = "\n\n".join(posts_text)

    prompt = f"""You are analyzing {creator.name}'s content strategy.

Here are their last {len(items)} posts:

{context}

Analyze across exactly these 7 dimensions and return ONLY a valid JSON object (no prose outside the JSON):

{{
  "pillars": [
    {{"topic": "topic name", "emotion": "pain/desire this topic targets", "share": "approximate % of posts"}}
  ],
  "formats": [
    {{"type": "format name", "description": "how they structure this format", "example": "first line of a post using this format"}}
  ],
  "hooks": [
    {{"type": "question|stat|story|bold_claim|pain_point|curiosity_gap", "example": "exact opening line", "why_it_works": "one sentence"}}
  ],
  "ctas": [
    {{"pattern": "exact CTA phrase or pattern", "frequency": "how often used"}}
  ],
  "engagement": {{
    "best_posts": [{{"summary": "what the post was about", "why": "why it performed well"}}],
    "worst_posts": [{{"summary": "what the post was about", "why": "why it underperformed"}}],
    "key_insight": "one sentence about what drives their engagement"
  }},
  "tone": [{{"adjective": "word", "evidence": "one example from the posts"}}],
  "positioning": {{
    "unique_angle": "what makes them different from others in their space",
    "gap_for_shadi": "one specific topic or format gap Shadi could fill for the Arab market",
    "key_lesson": "the single most important thing to learn from this creator"
  }}
}}

Rules:
- pillars: 3–5 items
- formats: 2–4 items
- hooks: 3–5 strongest examples from actual posts
- ctas: 2–4 patterns
- engagement.best_posts: top 2–3 performing posts
- engagement.worst_posts: bottom 1–2 performing posts
- tone: 3 adjectives with evidence
- Return ONLY valid JSON, nothing else"""

    try:
        raw = call_claude(
            prompt,
            system="You are a content strategy analyst. Return only valid JSON as instructed. No prose, no markdown fences.",
            db=db,
            max_tokens=2500,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    # Parse JSON — try full parse first, then extract from response
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {}
    except json.JSONDecodeError:
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group(0)) if match else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

    if not data:
        # Fallback: return raw text so the UI can still display something
        return {"analysis_text": raw, "posts_analyzed": len(items), "structured": False}

    return {"dimensions": data, "posts_analyzed": len(items), "structured": True}


@router.get("/landscape")
def competitive_landscape(category: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Creator)
    if category and category != "all":
        q = q.filter(Creator.category == category)
    creators = q.all()
    result = []
    for c in creators:
        items = db.query(ContentItem).filter(ContentItem.creator_id == c.id).all()
        n = len(items)
        total_eng = sum((i.likes or 0) + (i.comments_count or 0) + (i.shares or 0) for i in items)
        result.append({
            "id": c.id,
            "name": c.name,
            "category": c.category,
            "post_count": n,
            "avg_engagement": round(total_eng / n, 1) if n else 0,
            "platforms": list({i.platform for i in items}),
            "profile_image_url": c.profile_image_url,
            "instagram_handle": c.instagram_handle,
            "twitter_handle": c.twitter_handle,
        })
    result.sort(key=lambda x: x["avg_engagement"], reverse=True)
    return result


# ─── Hook extraction ──────────────────────────────────────────────────────────

class ExtractHooksRequest(BaseModel):
    creator_ids: List[int]
    limit: int = 30
    platform: Optional[str] = None


def _engagement_score(item: ContentItem) -> float:
    return float((item.likes or 0) + (item.comments_count or 0) * 2 + (item.shares or 0) * 3)


@router.post("/extract-hooks")
async def extract_hooks(data: ExtractHooksRequest, db: Session = Depends(get_db)):
    from ..ai.client import call_claude

    creators = db.query(Creator).filter(Creator.id.in_(data.creator_ids)).all()
    if not creators:
        raise HTTPException(404, "No creators found")

    creator_map = {c.id: c for c in creators}
    all_hooks = []

    for creator_id in data.creator_ids:
        creator = creator_map.get(creator_id)
        if not creator:
            continue

        q = db.query(ContentItem).filter(ContentItem.creator_id == creator_id)
        if data.platform:
            q = q.filter(ContentItem.platform == data.platform)
        items = q.order_by(ContentItem.published_at.desc()).limit(data.limit).all()
        if not items:
            continue

        posts_for_prompt = []
        for item in items:
            text = item.title or item.body or ""
            if not text.strip():
                continue
            eng = _engagement_score(item)
            posts_for_prompt.append({
                "id": item.id,
                "platform": item.platform,
                "text": text[:600],
                "likes": item.likes or 0,
                "comments": item.comments_count or 0,
                "shares": item.shares or 0,
                "engagement": eng,
                "published_at": item.published_at.strftime("%Y-%m-%d") if item.published_at else "unknown",
            })

        if not posts_for_prompt:
            continue

        numbered = "\n\n".join(
            f"POST {i+1} [id:{p['id']}] [{p['platform'].upper()}] Eng:{p['engagement']:.0f}\n{p['text']}"
            for i, p in enumerate(posts_for_prompt)
        )

        prompt = f"""Creator: {creator.name}

{numbered}

For each post above, extract the opening hook (first 1-2 sentences only).
Classify each hook as one of: question | stat | story | bold_claim | pain_point | curiosity_gap | other
Rate its hook strength from 1-10.

Reply ONLY with a JSON array, no prose:
[
  {{"post_id": <number from [id:X]>, "hook_text": "...", "hook_type": "...", "strength": <1-10>}},
  ...
]"""

        try:
            raw = call_claude(prompt, system="You are a content hook analyst. Extract and classify opening hooks. Return only valid JSON.", db=db, max_tokens=3000)
        except ValueError as exc:
            raise HTTPException(502, str(exc))

        # parse JSON from response — try full parse first, then regex extraction
        try:
            hooks_data = json.loads(raw)
            if not isinstance(hooks_data, list):
                hooks_data = []
        except json.JSONDecodeError:
            try:
                match = re.search(r'\[.*\]', raw, re.DOTALL)
                hooks_data = json.loads(match.group(0)) if match else []
                if not isinstance(hooks_data, list):
                    hooks_data = []
            except Exception:
                hooks_data = []

        item_map = {p["id"]: p for p in posts_for_prompt}

        for h in hooks_data:
            post_id = h.get("post_id")
            hook_text = h.get("hook_text", "").strip()
            if not hook_text or not post_id:
                continue

            post = item_map.get(post_id)
            if not post:
                continue

            eng_score = round(h.get("strength", 5) * (post["engagement"] / max(1, max(p["engagement"] for p in posts_for_prompt)) * 10), 2)

            # upsert: delete old hook for same content_item then insert fresh
            db.query(HookLibrary).filter(
                HookLibrary.content_item_id == post_id,
                HookLibrary.creator_id == creator_id
            ).delete()

            hook_row = HookLibrary(
                creator_id=creator_id,
                content_item_id=post_id,
                hook_text=hook_text,
                hook_type=h.get("hook_type", "other"),
                platform=post["platform"],
                likes=post["likes"],
                comments_count=post["comments"],
                shares=post["shares"],
                engagement_score=eng_score,
            )
            db.add(hook_row)
            all_hooks.append({
                "creator_id": creator_id,
                "creator_name": creator.name,
                "hook_text": hook_text,
                "hook_type": h.get("hook_type", "other"),
                "platform": post["platform"],
                "likes": post["likes"],
                "comments_count": post["comments"],
                "shares": post["shares"],
                "engagement_score": eng_score,
            })

    db.commit()
    all_hooks.sort(key=lambda x: x["engagement_score"], reverse=True)
    return {"hooks": all_hooks, "total": len(all_hooks)}


# ─── Style extraction ─────────────────────────────────────────────────────────

class ExtractStyleRequest(BaseModel):
    creator_ids: List[int]
    limit: int = 40


@router.post("/extract-style")
async def extract_style(data: ExtractStyleRequest, db: Session = Depends(get_db)):
    from ..ai.client import call_claude

    creators = db.query(Creator).filter(Creator.id.in_(data.creator_ids)).all()
    if not creators:
        raise HTTPException(404, "No creators found")

    results = []

    for creator in creators:
        items = db.query(ContentItem).filter(
            ContentItem.creator_id == creator.id
        ).order_by(ContentItem.published_at.desc()).limit(data.limit).all()

        if not items:
            results.append({"creator_id": creator.id, "creator_name": creator.name, "error": "No posts found"})
            continue

        posts_text = "\n\n---\n\n".join(
            (item.title or "") + ("\n" + item.body[:800] if item.body else "")
            for item in items if (item.title or item.body)
        )

        prompt = f"""Analyze the writing style of {creator.name} based on these {len(items)} posts:

{posts_text[:6000]}

Return a JSON object with exactly these fields:
{{
  "tone": ["adjective1", "adjective2", "adjective3", "adjective4", "adjective5"],
  "vocabulary_level": "simple|conversational|professional|academic",
  "avg_sentence_length": "short|medium|long",
  "formats_used": ["format1", "format2", ...],
  "cta_patterns": ["cta phrase 1", "cta phrase 2", ...],
  "posting_rhythm": "brief observation about posting frequency/timing",
  "key_phrases": ["phrase1", "phrase2", ...],
  "analysis_text": "2-3 paragraph narrative describing this creator's unique voice and style"
}}

Return ONLY valid JSON, no prose outside it."""

        try:
            raw = call_claude(prompt, system="You are a writing style analyst. Return only valid JSON.", db=db, max_tokens=2000)
        except ValueError as exc:
            raise HTTPException(502, str(exc))

        try:
            style_data = json.loads(raw)
            if not isinstance(style_data, dict):
                style_data = {}
        except json.JSONDecodeError:
            try:
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                style_data = json.loads(match.group(0)) if match else {}
                if not isinstance(style_data, dict):
                    style_data = {}
            except Exception:
                style_data = {}

        # upsert style extract
        existing = db.query(StyleExtract).filter(StyleExtract.creator_id == creator.id).first()
        if existing:
            db.delete(existing)
            db.flush()

        extract = StyleExtract(
            creator_id=creator.id,
            tone=style_data.get("tone", []),
            vocabulary_level=style_data.get("vocabulary_level", ""),
            avg_sentence_length=style_data.get("avg_sentence_length", ""),
            formats_used=style_data.get("formats_used", []),
            cta_patterns=style_data.get("cta_patterns", []),
            posting_rhythm=style_data.get("posting_rhythm", ""),
            key_phrases=style_data.get("key_phrases", []),
            analysis_text=style_data.get("analysis_text", raw[:1000]),
            posts_analyzed=len(items),
        )
        db.add(extract)
        db.flush()

        results.append({
            "creator_id": creator.id,
            "creator_name": creator.name,
            **style_data,
            "posts_analyzed": len(items),
        })

    db.commit()
    return {"styles": results}


# ─── Multi-account analysis ───────────────────────────────────────────────────

class MultiAnalysisRequest(BaseModel):
    creator_ids: List[int]
    question: Optional[str] = None
    limit: int = 20


@router.post("/multi-analysis")
async def multi_analysis(data: MultiAnalysisRequest, db: Session = Depends(get_db)):
    from ..ai.client import call_claude

    if len(data.creator_ids) < 2:
        raise HTTPException(400, "Provide at least 2 creator_ids for multi-analysis")

    creators = db.query(Creator).filter(Creator.id.in_(data.creator_ids)).all()
    if len(creators) < 2:
        raise HTTPException(404, "Creators not found")

    sections = []
    for creator in creators:
        items = db.query(ContentItem).filter(
            ContentItem.creator_id == creator.id
        ).order_by(ContentItem.published_at.desc()).limit(data.limit).all()

        posts = []
        for item in items:
            eng = _engagement_score(item)
            text = (item.title or "") + ("\n" + item.body[:400] if item.body else "")
            posts.append(f"  [Eng:{eng:.0f}] {text[:450]}")

        sections.append(
            f"=== {creator.name.upper()} ({creator.category}) ===\n" + "\n".join(posts[:data.limit])
        )

    all_content = "\n\n".join(sections)
    custom_q = f"\n\nAlso answer this specific question: {data.question}" if data.question else ""

    prompt = f"""You are analyzing {len(creators)} content creators together. Here is their recent content:

{all_content[:8000]}

Produce a cross-account analysis with these sections:

1. SHARED TOPICS — what ALL creators cover (ranked by how many cover it)
2. UNIQUE ANGLES — what each creator covers that others don't (one insight per creator)
3. ENGAGEMENT WINNERS — which creator's approach drives the most interaction and specifically WHY
4. CONTENT GAPS — topics or formats none of them cover that represent an opportunity
5. STEAL THESE — the single best tactic or pattern from each creator that Shadi should adopt{custom_q}

Be specific, use creator names, cite examples from the posts above."""

    try:
        analysis = call_claude(prompt, system="You are a competitive content intelligence analyst. Be specific and name the creators in your analysis.", db=db, max_tokens=2500)
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    return {
        "analysis": analysis,
        "creators_analyzed": [{"id": c.id, "name": c.name} for c in creators],
        "posts_per_creator": data.limit,
    }


# ─── Hook library read ────────────────────────────────────────────────────────

@router.get("/hooks")
def get_hooks(
    creator_ids: Optional[List[int]] = Query(default=None),
    hook_type: Optional[str] = None,
    min_score: float = 0.0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = (
        db.query(HookLibrary, Creator.name)
        .outerjoin(Creator, HookLibrary.creator_id == Creator.id)
    )
    if creator_ids:
        q = q.filter(HookLibrary.creator_id.in_(creator_ids))
    if hook_type:
        q = q.filter(HookLibrary.hook_type == hook_type)
    if min_score > 0:
        q = q.filter(HookLibrary.engagement_score >= min_score)
    rows = q.order_by(HookLibrary.engagement_score.desc()).limit(limit).all()

    return [
        {
            "id": hook.id,
            "creator_id": hook.creator_id,
            "creator_name": name or "—",
            "hook_text": hook.hook_text,
            "hook_type": hook.hook_type,
            "platform": hook.platform,
            "likes": hook.likes,
            "comments_count": hook.comments_count,
            "shares": hook.shares,
            "engagement_score": hook.engagement_score,
            "extracted_at": hook.extracted_at.isoformat() if hook.extracted_at else None,
            "source": hook.source or "extracted",
            "source_label": hook.source_label,
        }
        for hook, name in rows
    ]


# ─── Hook CRUD ────────────────────────────────────────────────────────────────

class CreateHookRequest(BaseModel):
    hook_text: str
    hook_type: str = "other"
    creator_id: Optional[int] = None
    source_label: Optional[str] = None


class UpdateHookRequest(BaseModel):
    hook_text: str
    hook_type: str


@router.post("/hooks")
def create_hook(data: CreateHookRequest, db: Session = Depends(get_db)):
    if data.creator_id:
        creator = db.query(Creator).filter(Creator.id == data.creator_id).first()
        if not creator:
            raise HTTPException(404, "Creator not found")
    hook = HookLibrary(
        creator_id=data.creator_id,
        hook_text=data.hook_text.strip(),
        hook_type=data.hook_type,
        source="manual",
        source_label=data.source_label or "Manual",
        engagement_score=0.0,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)
    creator_name = None
    if data.creator_id:
        c = db.query(Creator).filter(Creator.id == data.creator_id).first()
        creator_name = c.name if c else None
    return {
        "id": hook.id,
        "creator_id": hook.creator_id,
        "creator_name": creator_name or "—",
        "hook_text": hook.hook_text,
        "hook_type": hook.hook_type,
        "platform": hook.platform,
        "likes": hook.likes,
        "comments_count": hook.comments_count,
        "shares": hook.shares,
        "engagement_score": hook.engagement_score,
        "source": hook.source,
        "source_label": hook.source_label,
        "extracted_at": hook.extracted_at.isoformat() if hook.extracted_at else None,
    }


@router.put("/hooks/{hook_id}")
def update_hook(hook_id: int, data: UpdateHookRequest, db: Session = Depends(get_db)):
    hook = db.query(HookLibrary).filter(HookLibrary.id == hook_id).first()
    if not hook:
        raise HTTPException(404, "Hook not found")
    hook.hook_text = data.hook_text.strip()
    hook.hook_type = data.hook_type
    db.commit()
    return {"ok": True}


@router.delete("/hooks/{hook_id}")
def delete_hook(hook_id: int, db: Session = Depends(get_db)):
    hook = db.query(HookLibrary).filter(HookLibrary.id == hook_id).first()
    if not hook:
        raise HTTPException(404, "Hook not found")
    db.delete(hook)
    db.commit()
    return {"ok": True}


class BulkDeleteHooksRequest(BaseModel):
    ids: List[int]


@router.post("/hooks/bulk-delete")
def bulk_delete_hooks(data: BulkDeleteHooksRequest, db: Session = Depends(get_db)):
    deleted = db.query(HookLibrary).filter(HookLibrary.id.in_(data.ids)).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


# ─── Document upload → extract hooks ─────────────────────────────────────────

@router.post("/hooks/upload-document")
async def upload_document_hooks(
    file: UploadFile,
    creator_id: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
):
    from ..ai.client import call_claude

    filename = file.filename or "document"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    raw_bytes = await file.read()

    # Extract text based on file type
    text_content = ""
    if ext == "txt":
        text_content = raw_bytes.decode("utf-8", errors="replace")
    elif ext == "pdf":
        try:
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                text_content = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            raise HTTPException(400, "PDF support requires pdfplumber — install it with: pip install pdfplumber")
    elif ext in ("docx", "doc"):
        try:
            import docx, io
            doc = docx.Document(io.BytesIO(raw_bytes))
            text_content = "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise HTTPException(400, "DOCX support requires python-docx — install it with: pip install python-docx")
    else:
        raise HTTPException(400, f"Unsupported file type: .{ext}. Use .txt, .pdf, or .docx")

    text_content = text_content.strip()
    if not text_content:
        raise HTTPException(400, "Could not extract any text from the document")

    # Truncate if too long
    if len(text_content) > 12000:
        text_content = text_content[:12000]

    prompt = f"""Below is text from a document called "{filename}".

{text_content}

Extract all opening hooks you can find (first 1-2 sentences of posts or sections).
Classify each as: question | stat | story | bold_claim | pain_point | curiosity_gap | other
Rate hook strength 1-10.

Reply ONLY with a JSON array, no prose:
[
  {{"hook_text": "...", "hook_type": "...", "strength": <1-10>}},
  ...
]"""

    try:
        raw = call_claude(
            prompt,
            system="You are a content hook analyst. Extract and classify opening hooks from text. Return only valid JSON.",
            db=db,
            max_tokens=3000,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    try:
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        hooks_data = json.loads(match.group(0)) if match else []
    except Exception:
        hooks_data = []

    if not hooks_data:
        raise HTTPException(422, "Claude could not extract hooks from this document")

    inserted = []
    for h in hooks_data:
        hook_text = (h.get("hook_text") or "").strip()
        if not hook_text:
            continue
        hook = HookLibrary(
            creator_id=creator_id,
            hook_text=hook_text,
            hook_type=h.get("hook_type", "other"),
            source="document",
            source_label=filename,
            engagement_score=float(h.get("strength", 5)),
        )
        db.add(hook)
        inserted.append(hook_text)

    db.commit()
    return {"total": len(inserted), "filename": filename}


# ─── Bulk analysis save/list/delete ──────────────────────────────────────────

class SaveBulkAnalysisRequest(BaseModel):
    title: str
    creator_ids: List[int]
    creator_names: List[str]
    question: Optional[str] = None
    analysis_text: str
    posts_per_creator: int = 20


class BulkAnalysisOut(BaseModel):
    id: int
    title: str
    creator_ids: List[int]
    creator_names: List[str]
    question: Optional[str]
    analysis_text: str
    posts_per_creator: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/bulk-analyses", response_model=BulkAnalysisOut)
def save_bulk_analysis(data: SaveBulkAnalysisRequest, db: Session = Depends(get_db)):
    row = BulkAnalysis(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/bulk-analyses", response_model=List[BulkAnalysisOut])
def list_bulk_analyses(db: Session = Depends(get_db)):
    return db.query(BulkAnalysis).order_by(BulkAnalysis.created_at.desc()).all()


@router.delete("/bulk-analyses/{analysis_id}")
def delete_bulk_analysis(analysis_id: int, db: Session = Depends(get_db)):
    row = db.query(BulkAnalysis).filter(BulkAnalysis.id == analysis_id).first()
    if not row:
        raise HTTPException(404)
    db.delete(row)
    db.commit()
    return {"ok": True}


# ─── Style library read ───────────────────────────────────────────────────────

@router.get("/styles")
def get_styles(
    creator_ids: Optional[List[int]] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(StyleExtract, Creator.name).join(Creator, StyleExtract.creator_id == Creator.id)
    if creator_ids:
        q = q.filter(StyleExtract.creator_id.in_(creator_ids))
    rows = q.order_by(StyleExtract.extracted_at.desc()).all()

    return [
        {
            "id": extract.id,
            "creator_id": extract.creator_id,
            "creator_name": name,
            "tone": extract.tone,
            "vocabulary_level": extract.vocabulary_level,
            "avg_sentence_length": extract.avg_sentence_length,
            "formats_used": extract.formats_used,
            "cta_patterns": extract.cta_patterns,
            "posting_rhythm": extract.posting_rhythm,
            "key_phrases": extract.key_phrases,
            "analysis_text": extract.analysis_text,
            "posts_analyzed": extract.posts_analyzed,
            "extracted_at": extract.extracted_at.isoformat() if extract.extracted_at else None,
        }
        for extract, name in rows
    ]


# ─── LinkedIn AI Skills ──────────────────────────────────────────────────────

_SKILL_PROMPTS = {
    "content_analyzer": """You are a content strategist who specializes in finding competitive gaps on LinkedIn — the specific territory that's high demand but low supply. Your job is not to describe what someone is posting. Your job is to find what's working, what's not, why, and where the white space is that nobody else is claiming.

Analyze the provided LinkedIn post data and deliver:
1. **Engagement ranking** — posts ranked from highest to lowest with reaction/comment counts
2. **3 key patterns** — what the data is actually telling you (hook types, formats, topics)
3. **Format breakdown** — which format performs best and why
4. **Hook analysis** — what types of hooks appear on the highest-performing posts
5. **Gap identification** — specific topics, angles, or formats nobody else is covering well
6. **10 content ideas** — ranked by priority, each with: concept, why it's high demand/low supply, suggested hook (first line), expected engagement type (reactions/comments/saves/DMs), and priority: 🔥 High / ✦ Strong / ◆ Solid
7. **3 format changes** — specific tactical improvements to make immediately

The goal is to find the specific territory where this creator can be the only logical choice for their ideal customer. Differentiation beats optimization every time.""",

    "profile_optimizer": """You are a LinkedIn profile strategist who builds client attraction engines using authentic personal branding frameworks.

Your job: audit and rewrite a LinkedIn profile so it deeply resonates with the exact right person — not impress everyone.

Deliver in this order:
1. **Character Identification** — which archetype fits: Low-Ego Operator, Visionary Disruptor, Journey Builder, Skilled Specialist, or Lifestyle Proof — and why
2. **Quick Audit** — 3 bullets: what's working / what's missing / what's actively hurting
3. **Headline Options** — 2-3 versions (max 220 chars each), no job titles, no buzzwords, speak directly to the person not about yourself
4. **About Section rewrite** — full rewrite using: Hook (tension/transformation, not "I am a...") → Origin Story Bridge (real journey, specific failure/turning point) → What You Do + Who You Help → Proof (specific numbers/outcomes) → CTA (one action, one link). Short paragraphs, no bullets, reads like a human talking.
5. **Featured Section** — specific recommendation based on CTA goal
6. **Perception Summary** — what the rewritten profile makes people feel and do

Rules: No "leverage", "synergy", "passionate about", "results-driven". Short paragraphs. Read it out loud — if it sounds weird, rewrite it. Specific beats vague every time.""",

    "content_writer": """You write LinkedIn posts that sound like a real person with a real story. Not AI-generated content. Every post must pass one test: could only THIS person have written this?

From the raw idea provided, write a complete LinkedIn post following these rules:

**Hook (Line 1):** Max 12-15 words. Never start with "I". Never start with a question. Must create curiosity, tension, or recognition. Use: specific story opener, contrarian statement, specific number, or curiosity gap.

**Body:** Use one of three structures:
- Story Arc: Setup → Conflict → Resolution → Insight
- Contrarian Take: Bold statement → conventional wisdom → why it's wrong → what to do instead → challenge
- Tactical List: Specific promise → numbered specific/non-obvious points → most surprising last

**Ending:** Either a direct question (drives comments) OR soft CTA with specific resource (drives DMs). Never "Follow me for more."

**Rules:** 150-300 words. Single line breaks between every 1-2 sentences. Specific numbers beat vague claims. NEVER use em dashes (—). No buzzwords. No "passionate about", "in today's world", "let's unpack this", "game-changer".

**Deliver:**
1. The post, ready to copy-paste with correct line breaks
2. Strategy note (2-3 lines): hook type used, which pillar it hits, expected engagement
3. One shorter variation with a different hook""",

    "dm_writer": """You write LinkedIn outbound DM sequences that don't feel like outbound. The real work is finding the one truth that applies to everyone on a target list and writing it so specifically that every person thinks you were talking to them.

From the segment description provided, write a complete 4-message sequence:

**Message 1 — Connection Request:** Always blank. No message. (Just note: "Send blank — no message text")

**Message 2 — Opening DM** (send 24-48 hours after accepted):
- Line 1: State the pain that applies to everyone on this list. Plain. No build-up.
- Lines 2-3: Why this matters specifically for someone in their position.
- Line 4: One open question (easy to answer yes/no or one sentence).
- NO links, NO offers, NO CTAs beyond the question. Max 6 lines.

**Message 3 — Follow-up 1** (5-7 days if no reply):
- Give value immediately — an insight, framework, or result connected to the pain.
- One sentence on why it's relevant to their situation.
- Optional soft reopen question.
- No "just following up." Not apologetic.

**Message 4 — Follow-up 2** (7-10 days if still no reply):
- Acknowledge it's the last message.
- One clear sentence: what you do + who it's for.
- The specific result, concrete.
- "Worth a quick call or not the right time?" framing.

**Rules:** Short sentences (15 words max). No corporate language. No flattery. No desperation. One ask per message. Peer tone — not vendor pitching down.

After each message, one line on what job it's doing.""",
}


class LinkedInSkillRequest(BaseModel):
    skill: str
    creator_id: Optional[int] = None
    user_context: Optional[str] = None


class LinkedInResultSaveRequest(BaseModel):
    skill: str
    creator_id: Optional[int] = None
    creator_name: Optional[str] = None
    user_context: Optional[str] = None
    result_text: str


@router.post("/linkedin-skill")
async def run_linkedin_skill(data: LinkedInSkillRequest, db: Session = Depends(get_db)):
    from ..ai.client import call_claude
    from ..models import LinkedInSkillResult

    if data.skill not in _SKILL_PROMPTS:
        raise HTTPException(400, f"Unknown skill: {data.skill}")

    system_prompt = _SKILL_PROMPTS[data.skill]
    creator_name = None

    if data.skill in ("content_analyzer", "profile_optimizer") and data.creator_id:
        creator = db.query(Creator).filter(Creator.id == data.creator_id).first()
        if not creator:
            raise HTTPException(404, "Creator not found")
        creator_name = creator.name

        items = (
            db.query(ContentItem)
            .filter(ContentItem.creator_id == data.creator_id, ContentItem.platform == "linkedin")
            .order_by(ContentItem.published_at.desc())
            .limit(30)
            .all()
        )

        posts_text = []
        for item in items:
            line = f"[{item.published_at.strftime('%Y-%m-%d') if item.published_at else 'unknown'}] "
            line += f"Likes: {item.likes or 0}  Comments: {item.comments_count or 0}  Shares: {item.shares or 0}\n"
            if item.format:
                line += f"Format: {item.format}\n"
            if item.body:
                line += f"Content: {item.body[:600]}\n"
            posts_text.append(line)

        platforms = ", ".join(filter(None, [
            creator.linkedin_url and "LinkedIn",
            creator.twitter_handle and "Twitter",
            creator.youtube_channel_id and "YouTube",
        ]))
        user_message = f"""Creator: {creator.name}
Category: {creator.category}
Country: {creator.country or 'unknown'}
LinkedIn URL: {creator.linkedin_url or 'not set'}
Platforms: {platforms or 'unknown'}
Notes/Bio: {creator.notes or 'none'}
LinkedIn posts analyzed: {len(items)}

--- POSTS (most recent first) ---
{chr(10).join(posts_text) if posts_text else 'No LinkedIn posts found for this creator.'}
"""
        if data.user_context:
            user_message += f"\nAdditional context from user: {data.user_context}"

    else:
        if not data.user_context:
            raise HTTPException(400, "user_context is required for this skill")
        user_message = data.user_context

    try:
        result = call_claude(user_message, system=system_prompt, db=db, max_tokens=3000)
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    return {"result": result, "skill": data.skill, "creator_name": creator_name}


@router.get("/linkedin-results")
def list_linkedin_results(db: Session = Depends(get_db)):
    from ..models import LinkedInSkillResult
    rows = db.query(LinkedInSkillResult).order_by(LinkedInSkillResult.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "skill": r.skill,
            "creator_id": r.creator_id,
            "creator_name": r.creator_name,
            "user_context": r.user_context,
            "result_text": r.result_text,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/linkedin-results")
def save_linkedin_result(data: LinkedInResultSaveRequest, db: Session = Depends(get_db)):
    from ..models import LinkedInSkillResult
    row = LinkedInSkillResult(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "skill": row.skill,
        "creator_id": row.creator_id,
        "creator_name": row.creator_name,
        "user_context": row.user_context,
        "result_text": row.result_text,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.delete("/linkedin-results/{result_id}")
def delete_linkedin_result(result_id: int, db: Session = Depends(get_db)):
    from ..models import LinkedInSkillResult
    row = db.query(LinkedInSkillResult).filter(LinkedInSkillResult.id == result_id).first()
    if not row:
        raise HTTPException(404)
    db.delete(row)
    db.commit()
    return {"ok": True}
