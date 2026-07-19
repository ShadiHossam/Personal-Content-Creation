"""Engagement feed routes — daily LinkedIn post suggestions + profile search."""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import ContentItem, Creator, EngageItem, Profile, Setting

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engage", tags=["engage"])

_executor = ThreadPoolExecutor(max_workers=2)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_setting(db: Session, key: str) -> Optional[str]:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class EngageItemOut(BaseModel):
    id: int
    source_type: Optional[str]
    source_label: Optional[str]
    author_name: Optional[str]
    author_url: Optional[str]
    post_text: Optional[str]
    post_url: Optional[str]
    likes: int
    comments_count: int
    posted_at: Optional[datetime]
    fetched_at: Optional[datetime]
    ai_score: Optional[float]
    ai_reason: Optional[str]
    status: str

    model_config = {"from_attributes": True}


class StatusUpdate(BaseModel):
    status: str  # engaged | skipped | pending


class SearchProfilesRequest(BaseModel):
    keywords: str
    location: str = ""
    max_results: int = 30


class AIRecommendationSuggestion(BaseModel):
    keywords: str
    location: str
    reason: str


class AIRecommendationsResponse(BaseModel):
    suggestions: list[AIRecommendationSuggestion]


# ─── GET /api/engage/items ────────────────────────────────────────────────────

@router.get("/items", response_model=List[EngageItemOut])
def list_items(
    status: Optional[str] = None,
    min_score: Optional[float] = None,
    source_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(EngageItem)
    if status:
        q = q.filter(EngageItem.status == status)
    if min_score is not None:
        q = q.filter(EngageItem.ai_score >= min_score)
    if source_type:
        q = q.filter(EngageItem.source_type == source_type)
    items = q.order_by(EngageItem.ai_score.desc().nullslast(), EngageItem.likes.desc()).limit(200).all()
    return items


# ─── PATCH /api/engage/items/{id} ────────────────────────────────────────────

@router.patch("/items/{item_id}")
def update_status(item_id: int, body: StatusUpdate, db: Session = Depends(get_db)):
    item = db.query(EngageItem).filter(EngageItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    if body.status not in ("engaged", "skipped", "pending"):
        raise HTTPException(400, "status must be engaged, skipped, or pending")
    item.status = body.status
    db.commit()
    return {"ok": True}


# ─── DELETE /api/engage/items ────────────────────────────────────────────────

@router.delete("/items")
def clear_old_items(days: int = 7, status: Optional[str] = None, db: Session = Depends(get_db)):
    """By default, clears items older than `days`. If `status` is given
    (comma-separated, e.g. "engaged,skipped"), deletes items matching those
    statuses instead, regardless of age."""
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        deleted = db.query(EngageItem).filter(EngageItem.status.in_(statuses)).delete(synchronize_session=False)
    else:
        cutoff = _now() - timedelta(days=days)
        deleted = db.query(EngageItem).filter(EngageItem.fetched_at < cutoff).delete()
    db.commit()
    return {"deleted": deleted}


# ─── POST /api/engage/fetch ───────────────────────────────────────────────────

@router.post("/fetch")
def trigger_fetch(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    li_at = _get_setting(db, "linkedin_li_at")
    if not li_at:
        raise HTTPException(400, "LinkedIn li_at cookie not configured. Add it in Settings → Scraping Options.")
    background_tasks.add_task(_run_fetch, li_at)
    return {"ok": True, "message": "Fetch started — refresh in ~60 seconds"}


def _run_fetch(li_at: str):
    """Background task: scrape LinkedIn, score posts, save to DB.

    Opens its own session since it keeps running after the request/response
    cycle ends, by which point the request-scoped session would be closed.
    """
    db = SessionLocal()
    try:
        _run_fetch_with_session(li_at, db)
    finally:
        db.close()


def _run_fetch_with_session(li_at: str, db: Session):
    hashtags_raw = _get_setting(db, "linkedin_hashtags") or ""
    hashtags = [h.strip().lstrip("#") for h in hashtags_raw.split(",") if h.strip()]

    all_posts: list[dict] = []

    # ── 1. Home feed (connections) ─────────────────────────────────────────
    try:
        from ..scraper_tool.clients.linkedin_feed import fetch_feed_posts
        feed_posts = _run_in_thread(fetch_feed_posts, li_at, 30)
        all_posts.extend(feed_posts)
        log.info("Engage fetch: %d posts from feed", len(feed_posts))
    except Exception as e:
        log.warning("Engage fetch: feed scrape failed — %s", e)

    # ── 2. Hashtag posts ───────────────────────────────────────────────────
    for tag in hashtags[:5]:  # limit to 5 hashtags to avoid long runtime
        try:
            from ..scraper_tool.clients.linkedin_feed import fetch_hashtag_posts
            tag_posts = _run_in_thread(fetch_hashtag_posts, li_at, tag, 20)
            all_posts.extend(tag_posts)
            log.info("Engage fetch: %d posts for #%s", len(tag_posts), tag)
        except Exception as e:
            log.warning("Engage fetch: hashtag #%s failed — %s", tag, e)

    # ── 3. Recent posts from tracked creators ──────────────────────────────
    cutoff_24h = _now() - timedelta(hours=48)
    creator_posts = (
        db.query(ContentItem)
        .filter(
            ContentItem.platform == "linkedin",
            or_(ContentItem.published_at >= cutoff_24h, ContentItem.fetched_at >= cutoff_24h),
        )
        .order_by(ContentItem.fetched_at.desc())
        .limit(50)
        .all()
    )
    for cp in creator_posts:
        creator = db.query(Creator).filter(Creator.id == cp.creator_id).first()
        all_posts.append({
            "author_name": creator.name if creator else "Creator",
            "author_url": creator.linkedin_url if creator else "",
            "post_text": cp.body or cp.title or "",
            "post_url": cp.url or "",
            "likes": cp.likes or 0,
            "comments_count": cp.comments_count or 0,
            "source_type": "specific_person",
            "source_label": creator.name if creator else "Creator",
            "posted_at": cp.published_at,
        })

    if not all_posts:
        log.warning("Engage fetch: no posts collected")
        return

    # ── 4. Deduplicate by URL ──────────────────────────────────────────────
    existing_urls = {
        row.post_url
        for row in db.query(EngageItem.post_url).all()
        if row.post_url
    }
    unique_posts = []
    seen = set()
    for p in all_posts:
        url = (p.get("post_url") or "").strip()
        text = (p.get("post_text") or "").strip()
        if not url or not text:
            continue
        if url in existing_urls or url in seen:
            continue
        seen.add(url)
        unique_posts.append(p)

    log.info("Engage fetch: %d unique new posts to score", len(unique_posts))

    if not unique_posts:
        return

    # ── 5. AI scoring ──────────────────────────────────────────────────────
    profile = db.query(Profile).first()
    profile_text = ""
    if profile:
        profile_text = f"Bio: {profile.bio or ''}\nAudience: {profile.audience or ''}"

    scored = _score_posts(unique_posts, profile_text, db)

    # ── 6. Insert into DB ──────────────────────────────────────────────────
    inserted = 0
    for post, score, reason in scored:
        try:
            item = EngageItem(
                source_type=post.get("source_type", "connection"),
                source_label=post.get("source_label", ""),
                author_name=post.get("author_name", ""),
                author_url=post.get("author_url", ""),
                post_text=post.get("post_text", ""),
                post_url=post.get("post_url", ""),
                likes=post.get("likes", 0),
                comments_count=post.get("comments_count", 0),
                posted_at=post.get("posted_at"),
                ai_score=score,
                ai_reason=reason,
                status="pending",
            )
            db.add(item)
            db.commit()
            inserted += 1
        except Exception as e:
            db.rollback()
            log.debug("Engage fetch: skip duplicate/error — %s", e)

    log.info("Engage fetch: inserted %d new engage items", inserted)


def _run_in_thread(fn, *args):
    """Run a sync Playwright function in the thread pool and return its result."""
    future = _executor.submit(fn, *args)
    return future.result(timeout=120)


def _score_posts(posts: list[dict], profile_text: str, db: Session) -> list[tuple[dict, float, str]]:
    """Call Claude to score posts 0–10 for engagement opportunity."""
    try:
        from ..ai.client import resolve_backend, get_api_key
        backend, api_key = resolve_backend(db)
    except ValueError:
        # No Claude configured — assign default score of 5 to all
        return [(p, 5.0, "No AI scoring configured") for p in posts]

    # Build the scoring prompt
    posts_text = "\n\n".join(
        f"[{i+1}] AUTHOR: {p.get('author_name', '')} | URL: {p.get('post_url', '')}\n"
        f"TEXT: {(p.get('post_text') or '')[:400]}\n"
        f"LIKES: {p.get('likes', 0)} | COMMENTS: {p.get('comments_count', 0)}"
        for i, p in enumerate(posts[:30])  # limit to 30 at once
    )

    system_prompt = f"""You are an engagement strategist for a personal branding consultant.
User profile:
{profile_text or 'Marketing consultant and AI advisor for Arab business owners.'}

Your job: score each LinkedIn post from 0 to 10 on how worthwhile it would be to leave a thoughtful comment on it.

High score (8-10): Post is in the user's niche, already has good engagement, and a comment would add real value and visibility.
Medium score (5-7): Post is somewhat relevant but less strategic.
Low score (0-4): Off-topic, too old, too low-engagement, or a comment would add no value.

Respond ONLY with a JSON array. No explanation outside the JSON.
Format: [{{"index": 1, "score": 8.5, "reason": "High-engagement marketing post, perfect niche fit"}}, ...]"""

    user_prompt = f"Score these {len(posts[:30])} LinkedIn posts:\n\n{posts_text}"

    try:
        if backend == "cli":
            import subprocess, json as _json
            result = subprocess.run(
                ["claude", "-p", user_prompt, "--system", system_prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=60
            )
            raw = result.stdout.strip()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = next((b.text for b in resp.content if hasattr(b, "text")), "").strip()

        # Parse JSON from response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array in response")
        scores_data = json.loads(match.group(0))
        score_map = {item["index"]: (float(item.get("score", 5)), item.get("reason", "")) for item in scores_data}

        result_list = []
        for i, post in enumerate(posts[:30]):
            score, reason = score_map.get(i + 1, (5.0, ""))
            result_list.append((post, score, reason))

        # Any posts beyond the first 30 get a default score
        for post in posts[30:]:
            result_list.append((post, 5.0, "Not scored (batch limit)"))

        return result_list

    except Exception as e:
        log.warning("Engage: AI scoring failed — %s", e)
        return [(p, 5.0, "") for p in posts]


# ─── POST /api/engage/search-profiles ────────────────────────────────────────

@router.post("/search-profiles")
def search_linkedin_profiles(body: SearchProfilesRequest, db: Session = Depends(get_db)):
    """Search LinkedIn for people by keyword. Uses Apify if configured, Playwright fallback."""
    keywords = body.keywords.strip()
    if not keywords:
        raise HTTPException(400, "keywords is required")

    apify_token = _get_setting(db, "apify_api_key")
    if apify_token:
        try:
            return _search_via_apify(keywords, body.location, body.max_results, apify_token)
        except Exception as e:
            log.warning("Engage search: Apify failed (%s) — trying Playwright", e)

    # Playwright fallback
    li_at = _get_setting(db, "linkedin_li_at")
    if li_at:
        try:
            return _search_via_playwright(keywords, body.location, body.max_results, li_at)
        except Exception as e:
            log.warning("Engage search: Playwright failed — %s", e)

    raise HTTPException(503, "No scraping method available. Add an Apify key or li_at cookie in Settings.")


def _search_via_apify(keywords: str, location: str, max_results: int, token: str) -> dict:
    from ..scraper_tool.clients.apify_client import run_actor_sync

    search_url = f"https://www.linkedin.com/search/results/people/?keywords={keywords}"
    if location:
        search_url += f"&geoUrn={location}"

    actor_id = "supreme_coder/linkedin-profile-scraper"
    run_input = {"searchUrl": search_url, "maxResults": max_results}
    items = run_actor_sync(actor_id, run_input, token)

    profiles = []
    for item in items:
        profiles.append({
            "name": item.get("fullName") or item.get("name") or "",
            "headline": item.get("headline") or item.get("title") or "",
            "location": item.get("location") or item.get("geo") or "",
            "linkedin_url": item.get("profileUrl") or item.get("url") or "",
            "followers": item.get("followersCount") or item.get("followers") or 0,
            "profile_image_url": item.get("profilePicture") or item.get("img") or "",
        })
    return {"profiles": profiles, "source": "apify", "count": len(profiles)}


def _search_via_playwright(keywords: str, location: str, max_results: int, li_at: str) -> dict:
    from urllib.parse import quote as _quote
    from ..scraper_tool.clients.linkedin_feed import _launch_browser_with_cookie, _text, _attr
    import time

    url = f"https://www.linkedin.com/search/results/people/?keywords={_quote(keywords)}"
    if location:
        url += f"&geoUrn={_quote(location)}"

    def _scrape():
        pw, browser, context = _launch_browser_with_cookie(li_at)
        profiles = []
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            if "login" in page.url or "checkpoint" in page.url:
                raise RuntimeError("LinkedIn session expired")

            for _ in range(4):
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                time.sleep(2)

            cards = page.query_selector_all(".reusable-search__result-container, .entity-result")
            for card in cards[:max_results]:
                try:
                    name_el = card.query_selector(".entity-result__title-text a span[aria-hidden='true']") or \
                              card.query_selector(".app-aware-link span[aria-hidden='true']")
                    name = _text(name_el) if name_el else ""

                    link_el = card.query_selector(".entity-result__title-text a, .app-aware-link")
                    profile_url = _attr(link_el, "href").split("?")[0] if link_el else ""

                    headline_el = card.query_selector(".entity-result__primary-subtitle, .t-14.t-black--light")
                    headline = _text(headline_el) if headline_el else ""

                    loc_el = card.query_selector(".entity-result__secondary-subtitle")
                    location_str = _text(loc_el) if loc_el else ""

                    img_el = card.query_selector("img.presence-entity__image, img.EntityPhoto-circle-4")
                    img_url = _attr(img_el, "src") if img_el else ""

                    if name and profile_url:
                        profiles.append({
                            "name": name,
                            "headline": headline,
                            "location": location_str,
                            "linkedin_url": profile_url,
                            "followers": 0,
                            "profile_image_url": img_url,
                        })
                except Exception:
                    pass
            page.close()
        finally:
            context.close()
            browser.close()
            pw.stop()
        return profiles

    profiles = _run_in_thread(_scrape)
    return {"profiles": profiles, "source": "playwright", "count": len(profiles)}


# ─── POST /api/engage/ai-recommendations ──────────────────────────────────────

@router.post("/ai-recommendations", response_model=AIRecommendationsResponse)
def get_ai_recommendations(db: Session = Depends(get_db)):
    """Use Claude to suggest LinkedIn search queries tailored to the user's niche."""
    profile = db.query(Profile).first()
    profile_text = ""
    if profile:
        parts = []
        if profile.bio:
            parts.append(f"Bio: {profile.bio}")
        if profile.audience:
            parts.append(f"Target audience: {profile.audience}")
        if hasattr(profile, 'niche') and profile.niche:
            parts.append(f"Niche: {profile.niche}")
        profile_text = "\n".join(parts)

    if not profile_text:
        profile_text = "Marketing consultant and AI advisor for Arab business owners in the Gulf region."

    system_prompt = (
        "You are a LinkedIn growth strategist. Based on the user's profile, "
        "generate exactly 5 LinkedIn people-search suggestions to help them find "
        "high-value connections. Each suggestion should have distinct keywords and location.\n\n"
        "Respond ONLY with a valid JSON array. No text before or after the JSON.\n"
        'Format: [{"keywords": "...", "location": "...", "reason": "..."}, ...]'
    )
    user_prompt = (
        f"User profile:\n{profile_text}\n\n"
        "Generate 5 LinkedIn search suggestions. "
        "keywords = job title / role / topic (e.g. 'CMO fintech startup'). "
        "location = city or country (e.g. 'Dubai, United Arab Emirates'). "
        "reason = one sentence why this persona is worth connecting with."
    )

    try:
        from ..ai.client import resolve_backend, get_api_key
        backend, api_key = resolve_backend(db)
    except ValueError:
        return AIRecommendationsResponse(suggestions=_default_suggestions())

    try:
        if backend == "cli":
            import subprocess
            result = subprocess.run(
                ["claude", "-p", user_prompt, "--system", system_prompt, "--output-format", "text"],
                capture_output=True, text=True, timeout=60,
            )
            raw = result.stdout.strip()
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = next((b.text for b in resp.content if hasattr(b, "text")), "").strip()

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array in response")
        data = json.loads(match.group(0))
        suggestions = [
            AIRecommendationSuggestion(
                keywords=str(item.get("keywords", "")),
                location=str(item.get("location", "")),
                reason=str(item.get("reason", "")),
            )
            for item in data[:5]
        ]
        return AIRecommendationsResponse(suggestions=suggestions)

    except Exception as e:
        log.warning("AI recommendations failed — %s", e)
        return AIRecommendationsResponse(suggestions=_default_suggestions())


def _default_suggestions() -> list[AIRecommendationSuggestion]:
    return [
        AIRecommendationSuggestion(keywords="CMO marketing director", location="United Arab Emirates", reason="Senior marketers who can refer clients or collaborate"),
        AIRecommendationSuggestion(keywords="founder CEO small business", location="Dubai, United Arab Emirates", reason="Business owners who need personal branding help"),
        AIRecommendationSuggestion(keywords="AI consultant digital transformation", location="Saudi Arabia", reason="Tech-forward professionals in Shadi's niche"),
        AIRecommendationSuggestion(keywords="marketing manager e-commerce", location="Egypt", reason="Growing market with strong demand for branding"),
        AIRecommendationSuggestion(keywords="entrepreneur startup personal brand", location="Qatar", reason="Startup founders often looking for LinkedIn presence help"),
    ]
