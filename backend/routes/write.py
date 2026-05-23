from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_db
from ..models import (
    AIFeedback, WritingSkill, WritingSample, Profile,
    ContentItem, SourceItem
)

router = APIRouter(prefix="/api/write", tags=["write"])


class GenerateRequest(BaseModel):
    idea: str
    angle: Optional[str] = None
    format: str = "linkedin_post"
    language: str = "ar"
    skill_id: Optional[int] = None
    reference_content_ids: Optional[List[int]] = None
    reference_source_ids: Optional[List[int]] = None


class FeedbackRequest(BaseModel):
    idea: str
    angle: Optional[str]
    format: str
    language: str
    skill_id: Optional[int]
    draft: str
    rating: str  # good | bad
    note: Optional[str] = None


@router.post("/generate")
async def generate_draft(data: GenerateRequest, db: Session = Depends(get_db)):
    from ..ai.client import resolve_backend, call_claude

    try:
        backend, api_key = resolve_backend(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # CLI mode: pre-gather all context and call once (no tool-use loop)
    if backend == "cli":
        return await _generate_via_cli(data, db, call_claude)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    # Tool definitions for agentic context gathering
    tools = [
        {
            "name": "get_writing_samples",
            "description": "Get sample posts in the active writing style",
            "input_schema": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "integer", "description": "The writing skill ID"}
                },
                "required": []
            }
        },
        {
            "name": "get_feedback_history",
            "description": "Get recent feedback on past drafts to know what to improve",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max number of feedback items", "default": 10}
                },
                "required": []
            }
        },
        {
            "name": "get_profile",
            "description": "Get user profile, audience description, and global writing rules",
            "input_schema": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "get_references",
            "description": "Get reference content items and source articles selected by user",
            "input_schema": {"type": "object", "properties": {}, "required": []}
        }
    ]

    def handle_tool(tool_name: str, tool_input: dict) -> str:
        if tool_name == "get_writing_samples":
            sid = tool_input.get("skill_id") or data.skill_id
            if sid:
                samples = db.query(WritingSample).filter(WritingSample.skill_id == sid).limit(5).all()
            else:
                samples = db.query(WritingSample).limit(5).all()
            if not samples:
                return "No writing samples available yet."
            return "\n\n---\n\n".join(s.text for s in samples)

        elif tool_name == "get_feedback_history":
            limit = tool_input.get("limit", 10)
            q = db.query(AIFeedback)
            if data.skill_id:
                q = q.filter(AIFeedback.skill_id == data.skill_id)
            items = q.order_by(AIFeedback.created_at.desc()).limit(limit).all()
            if not items:
                return "No feedback history yet."
            lines = []
            for fb in items:
                emoji = "👍" if fb.rating == "good" else "👎"
                lines.append(f"{emoji} {fb.note or 'No note'} | Draft snippet: {(fb.draft or '')[:100]}")
            return "\n".join(lines)

        elif tool_name == "get_profile":
            profile = db.query(Profile).first()
            if not profile:
                return "No profile configured yet."
            skill_info = ""
            if data.skill_id:
                skill = db.query(WritingSkill).filter(WritingSkill.id == data.skill_id).first()
                if skill:
                    skill_info = f"\n\nActive skill: {skill.name}\nStyle: {skill.style_description}\nSkill rules: {', '.join(skill.rules or [])}"
            return f"Bio: {profile.bio}\nAudience: {profile.audience}\nGlobal rules: {', '.join(profile.rules or [])}{skill_info}"

        elif tool_name == "get_references":
            parts = []
            if data.reference_content_ids:
                for cid in data.reference_content_ids:
                    item = db.query(ContentItem).filter(ContentItem.id == cid).first()
                    if item:
                        parts.append(f"[{item.platform} post by creator] {item.body or item.title or ''}")
            if data.reference_source_ids:
                for sid in data.reference_source_ids:
                    item = db.query(SourceItem).filter(SourceItem.id == sid).first()
                    if item:
                        parts.append(f"[Article: {item.title}] {item.body or ''}")
            return "\n\n".join(parts) if parts else "No references selected."

        return "Unknown tool"

    lang_label = "Arabic" if data.language == "ar" else "English"
    format_labels = {
        "linkedin_post": "LinkedIn post",
        "thread": "Twitter/X thread",
        "article": "article introduction",
        "caption": "short social caption"
    }
    format_label = format_labels.get(data.format, data.format)

    system = f"""You are an expert ghostwriter for Shadi, a marketing strategist and AI consultant for Arab and global business owners.
Use the available tools to gather: writing samples, feedback history, profile/rules, and any references before writing.
Then write a polished {format_label} in {lang_label}.
Write ONLY the final post — no meta-commentary, no explanations. Just the post content."""

    user_message = f"Idea: {data.idea}"
    if data.angle:
        user_message += f"\nAngle: {data.angle}"
    user_message += f"\nFormat: {format_label}\nLanguage: {lang_label}"
    user_message += "\n\nFirst use the tools to gather context, then write the post."

    messages = [{"role": "user", "content": user_message}]

    # Agentic tool-use loop
    max_iterations = 5
    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            draft = next((b.text for b in response.content if hasattr(b, "text")), "")
            return {"draft": draft}

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = handle_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    # Fallback: extract text from last response
    draft = next((b.text for b in response.content if hasattr(b, "text")), "")
    return {"draft": draft}


async def _generate_via_cli(data: GenerateRequest, db: Session, call_claude) -> dict:
    """CLI path: gather all context inline, then call Claude once."""
    context_parts = []

    profile = db.query(Profile).first()
    if profile:
        context_parts.append(
            f"PROFILE:\nBio: {profile.bio or ''}\nAudience: {profile.audience or ''}"
            f"\nGlobal rules: {', '.join(profile.rules or [])}"
        )

    if data.skill_id:
        skill = db.query(WritingSkill).filter(WritingSkill.id == data.skill_id).first()
        if skill:
            context_parts.append(
                f"ACTIVE SKILL: {skill.name}\nStyle: {skill.style_description or ''}"
                f"\nSkill rules: {', '.join(skill.rules or [])}"
            )
            samples = db.query(WritingSample).filter(WritingSample.skill_id == data.skill_id).limit(5).all()
            if samples:
                context_parts.append("WRITING SAMPLES:\n" + "\n\n---\n\n".join(s.text for s in samples))

    q = db.query(AIFeedback)
    if data.skill_id:
        q = q.filter(AIFeedback.skill_id == data.skill_id)
    feedback_items = q.order_by(AIFeedback.created_at.desc()).limit(10).all()
    if feedback_items:
        lines = []
        for fb in feedback_items:
            emoji = "👍" if fb.rating == "good" else "👎"
            lines.append(f"{emoji} {fb.note or 'No note'} | Draft: {(fb.draft or '')[:100]}")
        context_parts.append("FEEDBACK HISTORY:\n" + "\n".join(lines))

    ref_parts = []
    if data.reference_content_ids:
        for cid in data.reference_content_ids:
            item = db.query(ContentItem).filter(ContentItem.id == cid).first()
            if item:
                ref_parts.append(f"[{item.platform} post] {item.body or item.title or ''}")
    if data.reference_source_ids:
        for sid in data.reference_source_ids:
            item = db.query(SourceItem).filter(SourceItem.id == sid).first()
            if item:
                ref_parts.append(f"[Article: {item.title}] {item.body or ''}")
    if ref_parts:
        context_parts.append("REFERENCES:\n" + "\n\n".join(ref_parts))

    lang_label = "Arabic" if data.language == "ar" else "English"
    format_labels = {
        "linkedin_post": "LinkedIn post",
        "thread": "Twitter/X thread",
        "article": "article introduction",
        "caption": "short social caption",
    }
    format_label = format_labels.get(data.format, data.format)
    context_block = "\n\n".join(context_parts) if context_parts else "No context available yet."

    user_prompt = f"""{context_block}

---

TASK: Write a {format_label} in {lang_label}.
Idea: {data.idea}
{f"Angle: {data.angle}" if data.angle else ""}

Write ONLY the final post — no meta-commentary, no explanations. Just the post content."""

    system = (
        f"You are an expert ghostwriter for Shadi, a marketing strategist and AI consultant "
        f"for Arab and global business owners. Write a polished {format_label} in {lang_label}."
    )

    try:
        draft = call_claude(user_prompt, system=system, db=db, max_tokens=2000)
    except ValueError as exc:
        raise HTTPException(502, str(exc))
    return {"draft": draft}


@router.post("/feedback")
def save_feedback(data: FeedbackRequest, db: Session = Depends(get_db)):
    fb = AIFeedback(**data.model_dump())
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return {"id": fb.id}


@router.post("/generate-from-article")
async def generate_from_article(
    source_item_id: int,
    angle: Optional[str] = None,
    format: str = "linkedin_post",
    language: str = "ar",
    skill_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    item = db.query(SourceItem).filter(SourceItem.id == source_item_id).first()
    if not item:
        raise HTTPException(404)

    idea = f"React to / share insight from this article: '{item.title}'"
    req = GenerateRequest(
        idea=idea,
        angle=angle or "share insight",
        format=format,
        language=language,
        skill_id=skill_id,
        reference_source_ids=[source_item_id]
    )
    return await generate_draft(req, db)
