from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean,
    DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Creator(Base):
    __tablename__ = "creators"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    country = Column(String(100))
    category = Column(String(50), nullable=False)  # competitor | inspiration
    rank = Column(Integer, default=999)
    priority = Column(Integer, nullable=True)
    profile_image_url = Column(String(500))
    profile_image_local = Column(String(500))
    linkedin_url = Column(String(500))
    twitter_handle = Column(String(100))
    instagram_handle = Column(String(100))
    youtube_channel_id = Column(String(100))
    tiktok_handle = Column(String(100))
    notes = Column(Text)
    scrape_max_posts = Column(Integer, nullable=True)
    scrape_linkedin_actor = Column(String(200), nullable=True)
    scrape_twitter_actor = Column(String(200), nullable=True)
    scrape_include_replies = Column(Boolean, nullable=True)
    scrape_include_retweets = Column(Boolean, nullable=True)
    last_fetched_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now_utc)

    content_items = relationship("ContentItem", back_populates="creator", cascade="all, delete-orphan")
    insights = relationship("CreatorInsight", back_populates="creator", cascade="all, delete-orphan")
    topics = relationship("CreatorTopic", back_populates="creator", cascade="all, delete-orphan")
    creator_notes = relationship("CreatorNote", back_populates="creator", cascade="all, delete-orphan")
    tags = relationship("CreatorTag", back_populates="creator", cascade="all, delete-orphan")


class CreatorTag(Base):
    __tablename__ = "creator_tags"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    tag_name = Column(String(100), nullable=False)

    creator = relationship("Creator", back_populates="tags")


class ContentItem(Base):
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # linkedin | twitter | youtube
    title = Column(String(500))
    body = Column(Text)
    url = Column(String(1000))
    published_at = Column(DateTime(timezone=True))
    format = Column(String(50))  # text | image | carousel | video | article
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    image_url = Column(String(1000))
    is_read = Column(Boolean, default=False)
    is_saved = Column(Boolean, default=False)
    transcript = Column(Text)
    fetched_at = Column(DateTime(timezone=True), default=now_utc)

    creator = relationship("Creator", back_populates="content_items")
    comments = relationship("Comment", back_populates="content_item", cascade="all, delete-orphan")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    content_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=False)
    author = Column(String(200))
    text = Column(Text)
    likes = Column(Integer, default=0)
    published_at = Column(DateTime(timezone=True))

    content_item = relationship("ContentItem", back_populates="comments")


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    url = Column(String(1000), nullable=False)
    rss_url = Column(String(1000))
    notes = Column(Text)
    fetch_from_date = Column(DateTime(timezone=True))
    last_fetched_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now_utc)
    priority = Column(Integer, default=3)
    category = Column(String(200), nullable=True)
    tags = Column(JSON, default=list)

    items = relationship("SourceItem", back_populates="source", cascade="all, delete-orphan")


class SourceItem(Base):
    __tablename__ = "source_items"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String(500), nullable=False)
    body = Column(Text)
    url = Column(String(1000))
    published_at = Column(DateTime(timezone=True))
    topic_tags = Column(JSON, default=list)
    user_tags = Column(JSON, default=list)
    is_read = Column(Boolean, default=False)
    is_saved = Column(Boolean, default=False)
    fetched_at = Column(DateTime(timezone=True), default=now_utc)

    source = relationship("Source", back_populates="items")


class CreatorNote(Base):
    __tablename__ = "creator_notes"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    creator = relationship("Creator", back_populates="creator_notes")


class CreatorInsight(Base):
    __tablename__ = "creator_insights"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    title = Column(String(300))
    question = Column(Text)
    answer = Column(Text)
    posts_analyzed = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    creator = relationship("Creator", back_populates="insights")


class CreatorTopic(Base):
    __tablename__ = "creator_topics"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    topic = Column(String(200), nullable=False)
    count = Column(Integer, default=0)
    last_updated = Column(DateTime(timezone=True), default=now_utc)

    creator = relationship("Creator", back_populates="topics")


class Profile(Base):
    __tablename__ = "profile"
    id = Column(Integer, primary_key=True)
    bio = Column(Text)
    audience = Column(Text)
    rules = Column(JSON, default=list)
    updated_at = Column(DateTime(timezone=True), default=now_utc)


class WritingSkill(Base):
    __tablename__ = "writing_skills"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    style_description = Column(Text)
    rules = Column(JSON, default=list)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    samples = relationship("WritingSample", back_populates="skill", cascade="all, delete-orphan")
    feedback = relationship("AIFeedback", back_populates="skill")


class WritingSample(Base):
    __tablename__ = "writing_samples"
    id = Column(Integer, primary_key=True)
    skill_id = Column(Integer, ForeignKey("writing_skills.id"), nullable=True)
    text = Column(Text, nullable=False)
    language = Column(String(10), default="ar")
    created_at = Column(DateTime(timezone=True), default=now_utc)

    skill = relationship("WritingSkill", back_populates="samples")


class AIFeedback(Base):
    __tablename__ = "ai_feedback"
    id = Column(Integer, primary_key=True)
    idea = Column(Text)
    angle = Column(String(200))
    format = Column(String(100))
    language = Column(String(10))
    skill_id = Column(Integer, ForeignKey("writing_skills.id"), nullable=True)
    draft = Column(Text)
    rating = Column(String(10))  # good | bad
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    skill = relationship("WritingSkill", back_populates="feedback")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True)
    title = Column(String(300))
    created_at = Column(DateTime(timezone=True), default=now_utc)

    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    session = relationship("ChatSession", back_populates="messages")


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime(timezone=True), default=now_utc)


class BulkAnalysis(Base):
    __tablename__ = "bulk_analyses"
    id = Column(Integer, primary_key=True)
    title = Column(String(300))
    creator_ids = Column(JSON, default=list)
    creator_names = Column(JSON, default=list)
    question = Column(Text)
    analysis_text = Column(Text, nullable=False)
    posts_per_creator = Column(Integer, default=20)
    created_at = Column(DateTime(timezone=True), default=now_utc)


class HookLibrary(Base):
    __tablename__ = "hook_library"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=True)
    content_item_id = Column(Integer, ForeignKey("content_items.id"), nullable=True)
    hook_text = Column(Text, nullable=False)
    hook_type = Column(String(50))  # question | stat | story | bold_claim | pain_point | curiosity_gap | other
    platform = Column(String(50))
    likes = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    engagement_score = Column(Float, default=0.0)
    extracted_at = Column(DateTime(timezone=True), default=now_utc)
    source = Column(String(50), default='extracted')   # extracted | manual | document
    source_label = Column(String(200), nullable=True)  # document filename or "Manual"

    creator = relationship("Creator")


class StyleExtract(Base):
    __tablename__ = "style_extracts"
    id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=False)
    tone = Column(JSON, default=list)           # list of adjectives e.g. ["bold", "direct", "warm"]
    vocabulary_level = Column(String(50))       # simple | conversational | professional | academic
    avg_sentence_length = Column(String(50))    # short | medium | long
    formats_used = Column(JSON, default=list)   # ["list", "story", "how-to", "question-answer"]
    cta_patterns = Column(JSON, default=list)   # recurring call-to-action phrases
    posting_rhythm = Column(String(200))        # e.g. "3-4x/week, mostly mornings"
    key_phrases = Column(JSON, default=list)    # power words / recurring expressions
    analysis_text = Column(Text)                # full Claude narrative
    posts_analyzed = Column(Integer, default=0)
    extracted_at = Column(DateTime(timezone=True), default=now_utc)


class LinkedInSkillResult(Base):
    __tablename__ = "linkedin_skill_results"
    id = Column(Integer, primary_key=True)
    skill = Column(String(50), nullable=False)  # content_analyzer | profile_optimizer | content_writer | dm_writer
    creator_id = Column(Integer, ForeignKey("creators.id"), nullable=True)
    creator_name = Column(String(200), nullable=True)
    user_context = Column(Text, nullable=True)
    result_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    creator = relationship("Creator")


class EngageItem(Base):
    __tablename__ = "engage_items"
    id             = Column(Integer, primary_key=True)
    source_type    = Column(String(50))   # connection | hashtag | specific_person | search_result
    source_label   = Column(String(200))  # e.g. "#leadership" or "My Feed"
    author_name    = Column(String(300))
    author_url     = Column(String(1000))
    post_text      = Column(Text)
    post_url       = Column(String(1000), unique=True)
    likes          = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    posted_at      = Column(DateTime(timezone=True))
    fetched_at     = Column(DateTime(timezone=True), default=now_utc)
    ai_score       = Column(Float, nullable=True)
    ai_reason      = Column(Text, nullable=True)
    status         = Column(String(20), default="pending")  # pending | engaged | skipped
