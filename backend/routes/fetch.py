from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional
import asyncio
import httpx

from ..database import get_db
from ..models import Creator, ContentItem, Comment, Source, SourceItem, Setting


class FetchParams(BaseModel):
    max_posts: Optional[int] = None
    from_date: Optional[str] = None       # "YYYY-MM-DD", inclusive lower bound
    to_date: Optional[str] = None         # "YYYY-MM-DD", inclusive upper bound
    platforms: Optional[list] = None      # e.g. ["youtube","twitter"] — omit = all
    ignore_last_fetched: bool = False     # bypass last_fetched_at floor (backfill mode)


def _parse_int(val) -> int:
    try:
        return int(str(val).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _before_since(pub: Optional[datetime], since: Optional[datetime]) -> bool:
    if not since or not pub:
        return False
    p = pub.replace(tzinfo=None) if pub.tzinfo else pub
    s = since.replace(tzinfo=None) if since.tzinfo else since
    return p < s


def _after_until(pub: Optional[datetime], until: Optional[datetime]) -> bool:
    if not until or not pub:
        return False
    p = pub.replace(tzinfo=None) if pub.tzinfo else pub
    u = until.replace(tzinfo=None) if until.tzinfo else until
    return p > u

router = APIRouter(prefix="/api/fetch", tags=["fetch"])


def _get_setting(db: Session, key: str) -> Optional[str]:
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row else None


def _friendly_apify_error(e: Exception, actor_id: str) -> str:
    """Turn long httpx/Apify exception messages into short user-friendly text."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 404:
            return f"Actor '{actor_id}' not found on Apify. Update the actor name in Settings."
        if status in (401, 403):
            return "Apify authentication failed. Check your API key in Settings."
    msg = str(e)
    # Try to detect a status code embedded in the message as a fallback
    import re as _re
    m = _re.search(r"\b(401|403|404)\b", msg)
    if m:
        code = m.group(1)
        if code == "404":
            return f"Actor '{actor_id}' not found on Apify. Update the actor name in Settings."
        if code in ("401", "403"):
            return "Apify authentication failed. Check your API key in Settings."
    # Generic: first 80 chars, no newlines
    cleaned = msg.replace("\n", " ").replace("\r", " ").strip()
    return cleaned[:80]


@router.post("/creator/{creator_id}")
async def fetch_creator(
    creator_id: int,
    params: FetchParams = Body(default_factory=FetchParams),
    db: Session = Depends(get_db),
):
    creator = db.query(Creator).filter(Creator.id == creator_id).first()
    if not creator:
        raise HTTPException(404)

    youtube_key = _get_setting(db, "youtube_api_key")

    new_count = 0
    errors = []

    # Parse date range bounds — used by all platform blocks below
    since: Optional[datetime] = None
    if params.from_date:
        try:
            since = datetime.strptime(params.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    until: Optional[datetime] = None
    if params.to_date:
        try:
            until = datetime.strptime(params.to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # YouTube
    if creator.youtube_channel_id and youtube_key and (not params.platforms or "youtube" in params.platforms):
        try:
            from ..scrapers.youtube import fetch_videos, fetch_video_comments
            # In backfill/date-range mode, ignore last_fetched_at and use explicit dates
            if params.ignore_last_fetched or params.from_date:
                yt_after = since  # None if no from_date — go as far back as possible
            else:
                yt_after = creator.last_fetched_at
            yt_before = until
            videos = await fetch_videos(
                creator.youtube_channel_id,
                youtube_key,
                published_after=yt_after,
                published_before=yt_before,
                paginate_all=(yt_after is None or params.ignore_last_fetched),
            )
            for v in videos:
                existing = db.query(ContentItem).filter(ContentItem.url == v["url"]).first()
                if existing:
                    if not existing.image_url and v.get("image_url"):
                        existing.image_url = v["image_url"]
                    continue
                item = ContentItem(creator_id=creator_id, **v)
                db.add(item)
                db.flush()
                video_id = v["url"].split("v=")[-1] if "v=" in v["url"] else ""
                if video_id:
                    comments = await fetch_video_comments(video_id, youtube_key)
                    for c in comments:
                        db.add(Comment(content_item_id=item.id, **c))
                new_count += 1
        except Exception as e:
            msg = str(e).replace("\n", " ").replace("\r", " ").strip()
            errors.append(f"YouTube: {msg[:80]}")

    # Read global scrape settings, with per-creator override for max posts
    def _int_setting(key, default):
        v = _get_setting(db, key)
        try:
            return int(v) if v else default
        except ValueError:
            return default

    global_max = _int_setting("scrape_max_posts", 20)
    effective_max = creator.scrape_max_posts if creator.scrape_max_posts else global_max
    if params.max_posts:
        effective_max = params.max_posts

    # Twitter via cascade scraper (direct_cffi → apify → extension_idsmcr)
    if creator.twitter_handle and (not params.platforms or "twitter" in params.platforms):
        try:
            from ..scraper_tool.social_dispatch import run_with_cascade
            handle_url = f"https://x.com/{creator.twitter_handle}"
            result = await asyncio.to_thread(
                run_with_cascade, "twitter", handle_url, None, effective_max
            )
            tw_data = result.get("data") or {}
            tw_records = tw_data.get("records", [])
            tw_profile = tw_data.get("profile") or {}
            img = tw_profile.get("image") or tw_profile.get("avatar") or tw_profile.get("profile_image_url")
            if img:
                creator.profile_image_url = img
            for rec in tw_records:
                url = rec.get("url", "")
                if not url:
                    continue
                pub = _parse_ts(rec.get("timestamp", ""))
                if _before_since(pub, since):
                    continue
                if _after_until(pub, until):
                    continue
                if db.query(ContentItem).filter(ContentItem.url == url).first():
                    continue
                db.add(ContentItem(
                    creator_id=creator_id,
                    platform="twitter",
                    url=url,
                    body=rec.get("text", "")[:2000],
                    published_at=pub,
                    likes=_parse_int(rec.get("likes")),
                    comments_count=_parse_int(rec.get("replies")),
                    shares=_parse_int(rec.get("retweets")),
                    image_url=rec["images"][0] if rec.get("images") else None,
                    format="video" if rec.get("has_video") else ("image" if rec.get("images") else "text"),
                ))
                new_count += 1
        except Exception as e:
            msg = str(e).replace("\n", " ").strip()
            errors.append(f"Twitter: {msg[:120]}")

    # Instagram via cascade scraper
    if creator.instagram_handle and (not params.platforms or "instagram" in params.platforms):
        try:
            from ..scraper_tool.social_dispatch import run_with_cascade
            ig_url = f"https://www.instagram.com/{creator.instagram_handle}/"
            result = await asyncio.to_thread(
                run_with_cascade, "instagram", ig_url, None, effective_max
            )
            ig_data = result.get("data") or {}
            ig_records = ig_data.get("records", [])
            ig_profile = ig_data.get("profile") or {}
            img = ig_profile.get("image") or ig_profile.get("avatar") or ig_profile.get("profile_pic_url")
            if img:
                creator.profile_image_url = img
            for rec in ig_records:
                url = rec.get("url", "")
                if not url:
                    continue
                pub = _parse_ts(rec.get("timestamp") or rec.get("taken_at") or "")
                if _before_since(pub, since):
                    continue
                if _after_until(pub, until):
                    continue
                if db.query(ContentItem).filter(ContentItem.url == url).first():
                    continue
                db.add(ContentItem(
                    creator_id=creator_id,
                    platform="instagram",
                    url=url,
                    body=(rec.get("caption") or rec.get("text", ""))[:2000],
                    published_at=pub,
                    likes=_parse_int(rec.get("likes")),
                    comments_count=_parse_int(rec.get("comments")),
                    shares=0,
                    image_url=rec["images"][0] if rec.get("images") else rec.get("image_url") or None,
                    format="video" if rec.get("has_video") or rec.get("is_video") else ("image" if rec.get("images") or rec.get("image_url") else "text"),
                ))
                new_count += 1
        except Exception as e:
            msg = str(e).replace("\n", " ").strip()
            errors.append(f"Instagram: {msg[:120]}")

    # TikTok via cascade scraper
    if creator.tiktok_handle and (not params.platforms or "tiktok" in params.platforms):
        try:
            from ..scraper_tool.social_dispatch import run_with_cascade
            tt_url = f"https://www.tiktok.com/@{creator.tiktok_handle}"
            result = await asyncio.to_thread(
                run_with_cascade, "tiktok", tt_url, None, effective_max
            )
            tt_data = result.get("data") or {}
            tt_records = tt_data.get("records", [])
            tt_profile = tt_data.get("profile") or {}
            img = tt_profile.get("image") or tt_profile.get("avatar")
            if img:
                creator.profile_image_url = img
            for rec in tt_records:
                url = rec.get("url", "")
                if not url:
                    continue
                pub = _parse_ts(rec.get("timestamp") or rec.get("created_at") or "")
                if _before_since(pub, since):
                    continue
                if _after_until(pub, until):
                    continue
                if db.query(ContentItem).filter(ContentItem.url == url).first():
                    continue
                db.add(ContentItem(
                    creator_id=creator_id,
                    platform="tiktok",
                    url=url,
                    body=(rec.get("text") or rec.get("caption", ""))[:2000],
                    published_at=pub,
                    likes=_parse_int(rec.get("likes")),
                    comments_count=_parse_int(rec.get("comments")),
                    shares=_parse_int(rec.get("shares")),
                    image_url=rec.get("cover") or (rec["images"][0] if rec.get("images") else None),
                    format="video",
                ))
                new_count += 1
        except Exception as e:
            msg = str(e).replace("\n", " ").strip()
            errors.append(f"TikTok: {msg[:120]}")

    # LinkedIn via cascade scraper (direct_cffi → apify → extension_idsmcr)
    if creator.linkedin_url and (not params.platforms or "linkedin" in params.platforms):
        try:
            from ..scraper_tool.social_dispatch import run_with_cascade
            result = await asyncio.to_thread(
                run_with_cascade, "linkedin", creator.linkedin_url, None, effective_max
            )
            li_data = result.get("data") or {}
            li_records = li_data.get("records", [])
            li_profile = li_data.get("profile") or {}
            img = li_profile.get("image") or li_profile.get("logo") or li_profile.get("avatar")
            if img:
                creator.profile_image_url = img
            for rec in li_records:
                url = rec.get("url", "")
                if not url:
                    continue
                pub = _parse_ts(rec.get("timestamp") or rec.get("published_at") or "")
                if _before_since(pub, since):
                    continue
                if _after_until(pub, until):
                    continue
                if db.query(ContentItem).filter(ContentItem.url == url).first():
                    continue
                db.add(ContentItem(
                    creator_id=creator_id,
                    platform="linkedin",
                    url=url,
                    body=rec.get("text", "")[:2000],
                    published_at=pub,
                    likes=_parse_int(rec.get("likes")),
                    comments_count=_parse_int(rec.get("comments")),
                    shares=_parse_int(rec.get("reposts")),
                    image_url=rec["images"][0] if rec.get("images") else None,
                    format="video" if rec.get("has_video") else ("image" if rec.get("images") else "text"),
                ))
                new_count += 1
        except Exception as e:
            msg = str(e).replace("\n", " ").strip()
            errors.append(f"LinkedIn: {msg[:120]}")

    # Refresh creator profile image from YouTube API when available
    if creator.youtube_channel_id and youtube_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet", "id": creator.youtube_channel_id, "key": youtube_key},
                )
                data = r.json()
                if data.get("items"):
                    thumbs = data["items"][0]["snippet"].get("thumbnails", {})
                    img = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
                    if img:
                        creator.profile_image_url = img
        except Exception:
            pass

    # Only advance last_fetched_at on normal incremental fetches, not backfills
    if not params.ignore_last_fetched:
        creator.last_fetched_at = datetime.now(timezone.utc)
    db.commit()

    return {"new_items": new_count, "errors": errors}


_BULK_FETCH_DELAY = 20  # seconds between each creator fetch to avoid platform rate-limiting
_bulk_stop_flag = False
_bulk_progress = {"current": 0, "total": 0, "creator_name": "", "running": False}


@router.get("/bulk/progress")
async def bulk_fetch_progress():
    return _bulk_progress


@router.post("/bulk/stop")
async def stop_bulk_fetch():
    global _bulk_stop_flag
    _bulk_stop_flag = True
    return {"ok": True}


@router.post("/bulk")
async def fetch_bulk(payload: dict, db: Session = Depends(get_db)):
    """Sequential fetch for a list of creator IDs — avoids concurrent scraping."""
    global _bulk_stop_flag, _bulk_progress
    _bulk_stop_flag = False

    creator_ids = [int(cid) for cid in (payload.get("creator_ids") or [])]
    params = FetchParams(
        max_posts=payload.get("max_posts"),
        from_date=payload.get("from_date"),
        to_date=payload.get("to_date"),
        ignore_last_fetched=bool(payload.get("ignore_last_fetched", False)),
    )
    total_new = 0
    results = []
    stopped = False

    _bulk_progress.update({"current": 0, "total": len(creator_ids), "creator_name": "", "running": True})

    for i, cid in enumerate(creator_ids):
        if _bulk_stop_flag:
            stopped = True
            break
        if i > 0:
            # Check stop flag during the delay in 1s increments
            for _ in range(_BULK_FETCH_DELAY):
                if _bulk_stop_flag:
                    break
                await asyncio.sleep(1)
            if _bulk_stop_flag:
                stopped = True
                break

        creator = db.query(Creator).filter(Creator.id == cid).first()
        _bulk_progress.update({"current": i + 1, "creator_name": creator.name if creator else str(cid)})

        try:
            result = await fetch_creator(cid, params, db)
            total_new += result["new_items"]
            results.append({"id": cid, "new_items": result["new_items"], "errors": result["errors"]})
        except Exception as e:
            results.append({"id": cid, "new_items": 0, "errors": [str(e)[:80]]})

    _bulk_progress.update({"running": False})
    return {"total_new": total_new, "results": results, "stopped": stopped}


@router.post("/all")
async def fetch_all(db: Session = Depends(get_db)):
    creators = db.query(Creator).all()
    total_new = 0
    all_errors = []
    for creator in creators:
        result = await fetch_creator(creator.id, FetchParams(), db)
        total_new += result["new_items"]
        if result["errors"]:
            all_errors.extend([f"{creator.name}: {e}" for e in result["errors"]])

    sources = db.query(Source).all()
    for source in sources:
        src_result = await fetch_source(source.id, FetchSourceParams(), db)
        total_new += src_result.get("new_items", 0)
        if src_result.get("errors"):
            all_errors.extend([f"{source.name}: {e}" for e in src_result["errors"]])

    return {"new_items": total_new, "errors": all_errors}


class FetchSourceParams(BaseModel):
    from_date: Optional[str] = None
    ignore_last_fetched: bool = False


@router.post("/source/{source_id}")
async def fetch_source(
    source_id: int,
    params: FetchSourceParams = Body(default_factory=FetchSourceParams),
    db: Session = Depends(get_db),
):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(404)

    if not source.rss_url:
        from ..scrapers.rss import detect_rss_url
        detected = await detect_rss_url(source.url)
        if detected:
            source.rss_url = detected
            db.commit()
        else:
            return {"new_items": 0, "errors": ["Could not detect RSS feed"]}

    from ..scrapers.rss import parse_feed
    def _to_naive(dt):
        return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

    if params.ignore_last_fetched:
        since = _to_naive(source.fetch_from_date)
    elif params.from_date:
        try:
            since = datetime.strptime(params.from_date, "%Y-%m-%d")
        except ValueError:
            since = None
    else:
        lfa = _to_naive(source.last_fetched_at)
        ffd = _to_naive(source.fetch_from_date)
        since = max(lfa, ffd) if lfa and ffd else (lfa or ffd)

    try:
        items = parse_feed(source.rss_url, since=since)
    except Exception as e:
        return {"new_items": 0, "errors": [str(e)]}

    new_count = 0
    for item in items:
        existing = db.query(SourceItem).filter(SourceItem.url == item.get("url")).first()
        if existing or not item.get("url"):
            continue
        db.add(SourceItem(source_id=source_id, **item))
        new_count += 1

    if not params.ignore_last_fetched:
        source.last_fetched_at = datetime.now(timezone.utc)
    db.commit()
    return {"new_items": new_count, "errors": []}
