from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_db
from ..models import Profile, WritingSkill, WritingSample, AIFeedback

router = APIRouter(prefix="/api/style", tags=["style"])


# --- Profile ---

class ProfileIn(BaseModel):
    bio: Optional[str] = None
    audience: Optional[str] = None
    rules: Optional[List[str]] = None


class ProfileOut(BaseModel):
    id: Optional[int]
    bio: Optional[str]
    audience: Optional[str]
    rules: Optional[List[str]]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.get("/profile", response_model=ProfileOut)
def get_profile(db: Session = Depends(get_db)):
    p = db.query(Profile).first()
    if not p:
        return ProfileOut(id=None, bio=None, audience=None, rules=[], updated_at=None)
    return p


@router.post("/profile", response_model=ProfileOut)
def save_profile(data: ProfileIn, db: Session = Depends(get_db)):
    p = db.query(Profile).first()
    if not p:
        p = Profile()
        db.add(p)
    if data.bio is not None:
        p.bio = data.bio
    if data.audience is not None:
        p.audience = data.audience
    if data.rules is not None:
        p.rules = data.rules
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)
    return p


# --- Writing Skills ---

class SkillIn(BaseModel):
    name: str
    style_description: Optional[str] = None
    rules: Optional[List[str]] = None


class SampleIn(BaseModel):
    text: str
    language: str = "ar"


class SkillOut(BaseModel):
    id: int
    name: str
    style_description: Optional[str]
    rules: Optional[List[str]]
    is_active: bool
    created_at: datetime
    sample_count: Optional[int] = 0
    feedback_count: Optional[int] = 0

    model_config = {"from_attributes": True}


class SampleOut(BaseModel):
    id: int
    skill_id: Optional[int]
    text: str
    language: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/skills", response_model=List[SkillOut])
def list_skills(db: Session = Depends(get_db)):
    skills = db.query(WritingSkill).order_by(WritingSkill.is_active.desc(), WritingSkill.created_at).all()
    result = []
    for s in skills:
        out = SkillOut.model_validate(s)
        out.sample_count = len(s.samples)
        out.feedback_count = len(s.feedback)
        result.append(out)
    return result


@router.post("/skills", response_model=SkillOut)
def create_skill(data: SkillIn, db: Session = Depends(get_db)):
    skill = WritingSkill(**data.model_dump())
    db.add(skill)
    db.commit()
    db.refresh(skill)
    out = SkillOut.model_validate(skill)
    out.sample_count = 0
    out.feedback_count = 0
    return out


@router.put("/skills/{skill_id}", response_model=SkillOut)
def update_skill(skill_id: int, data: SkillIn, db: Session = Depends(get_db)):
    skill = db.query(WritingSkill).filter(WritingSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(404)
    for k, v in data.model_dump().items():
        setattr(skill, k, v)
    db.commit()
    db.refresh(skill)
    out = SkillOut.model_validate(skill)
    out.sample_count = len(skill.samples)
    out.feedback_count = len(skill.feedback)
    return out


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db)):
    skill = db.query(WritingSkill).filter(WritingSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(404)
    db.delete(skill)
    db.commit()
    return {"ok": True}


@router.post("/skills/{skill_id}/activate")
def activate_skill(skill_id: int, db: Session = Depends(get_db)):
    skill = db.query(WritingSkill).filter(WritingSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(404)
    db.query(WritingSkill).update({"is_active": False})
    skill.is_active = True
    db.commit()
    return {"ok": True}


@router.get("/skills/{skill_id}/samples", response_model=List[SampleOut])
def list_samples(skill_id: int, db: Session = Depends(get_db)):
    return db.query(WritingSample).filter(WritingSample.skill_id == skill_id).all()


@router.post("/skills/{skill_id}/samples", response_model=SampleOut)
def add_sample(skill_id: int, data: SampleIn, db: Session = Depends(get_db)):
    sample = WritingSample(skill_id=skill_id, **data.model_dump())
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


@router.delete("/samples/{sample_id}")
def delete_sample(sample_id: int, db: Session = Depends(get_db)):
    s = db.query(WritingSample).filter(WritingSample.id == sample_id).first()
    if not s:
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    return {"ok": True}


# --- Feedback Memory ---

class FeedbackOut(BaseModel):
    id: int
    idea: Optional[str]
    angle: Optional[str]
    format: Optional[str]
    language: Optional[str]
    skill_id: Optional[int]
    skill_name: Optional[str] = None
    draft: Optional[str]
    rating: Optional[str]
    note: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/feedback", response_model=List[FeedbackOut])
def list_feedback(skill_id: Optional[int] = None, rating: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(AIFeedback)
    if skill_id:
        q = q.filter(AIFeedback.skill_id == skill_id)
    if rating:
        q = q.filter(AIFeedback.rating == rating)
    items = q.order_by(AIFeedback.created_at.desc()).limit(limit).all()
    result = []
    for fb in items:
        out = FeedbackOut.model_validate(fb)
        if fb.skill_id and fb.skill:
            out.skill_name = fb.skill.name
        result.append(out)
    return result


@router.put("/feedback/{fb_id}")
def update_feedback(fb_id: int, note: str, db: Session = Depends(get_db)):
    fb = db.query(AIFeedback).filter(AIFeedback.id == fb_id).first()
    if not fb:
        raise HTTPException(404)
    fb.note = note
    db.commit()
    return {"ok": True}


@router.delete("/feedback/{fb_id}")
def delete_feedback(fb_id: int, db: Session = Depends(get_db)):
    fb = db.query(AIFeedback).filter(AIFeedback.id == fb_id).first()
    if not fb:
        raise HTTPException(404)
    db.delete(fb)
    db.commit()
    return {"ok": True}
