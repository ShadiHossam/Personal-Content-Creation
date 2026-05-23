from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_db
from ..models import (
    ChatSession, ChatMessage, ContentItem, SourceItem,
    Creator, Source, AIFeedback, CreatorInsight
)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class MessageIn(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: int
    title: Optional[str]
    created_at: datetime
    message_count: Optional[int] = 0

    model_config = {"from_attributes": True}


@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).limit(20).all()
    result = []
    for s in sessions:
        out = SessionOut.model_validate(s)
        out.message_count = len(s.messages)
        result.append(out)
    return result


@router.post("/sessions", response_model=SessionOut)
def create_session(db: Session = Depends(get_db)):
    session = ChatSession(title="New Chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    out = SessionOut.model_validate(session)
    out.message_count = 0
    return out


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
def get_messages(session_id: int, db: Session = Depends(get_db)):
    return db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).all()


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: int, data: MessageIn, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(404)

    from ..ai.client import call_claude_messages

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=data.content)
    db.add(user_msg)

    # Auto-title after first message
    if not session.messages and session.title == "New Chat":
        session.title = data.content[:60] + ("..." if len(data.content) > 60 else "")

    db.commit()

    # Build data context summary
    creators = db.query(Creator).order_by(Creator.rank).all()
    creator_summary = []
    for c in creators:
        items = db.query(ContentItem).filter(ContentItem.creator_id == c.id).limit(50).all()
        n = len(items)
        if n:
            avg_eng = round(sum((i.likes or 0) + (i.comments_count or 0) + (i.shares or 0) for i in items) / n, 1)
            creator_summary.append(f"- {c.name} ({c.category}): {n} posts sampled, avg engagement {avg_eng}")
        else:
            creator_summary.append(f"- {c.name} ({c.category}): no posts yet")

    recent_news = db.query(SourceItem).order_by(SourceItem.published_at.desc()).limit(10).all()
    news_summary = [f"- {i.title} ({', '.join(i.topic_tags or [])})" for i in recent_news]

    saved_insights = db.query(CreatorInsight).order_by(CreatorInsight.created_at.desc()).limit(5).all()
    insights_summary = [f"- {ins.title}: {ins.answer[:200]}" for ins in saved_insights]

    system_context = f"""You are an AI assistant helping Shadi, a marketing strategist and AI consultant for Arab and global business owners.
You have access to Shadi's personal branding intelligence system with the following data:

CREATORS IN DATABASE ({len(creators)} total):
{chr(10).join(creator_summary) or 'None yet'}

RECENT NEWS ({len(recent_news)} articles):
{chr(10).join(news_summary) or 'None yet'}

SAVED INSIGHTS:
{chr(10).join(insights_summary) or 'None yet'}

Answer questions about content strategy, competitors, trends, and what Shadi should focus on. Be specific and actionable. Reference actual data from the system when available."""

    # Build message history — keep last 20 messages to avoid context overflow
    history = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).all()

    messages = [{"role": m.role, "content": m.content} for m in history[-20:]]

    try:
        answer = call_claude_messages(
            messages,
            system=system_context,
            db=db,
            max_tokens=1500,
        )
    except ValueError as exc:
        raise HTTPException(502, str(exc))

    assistant_msg = ChatMessage(session_id=session_id, role="assistant", content=answer)
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return {"answer": answer, "message_id": assistant_msg.id}
