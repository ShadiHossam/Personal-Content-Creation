"""
LinkedIn feed scraper using Playwright + li_at session cookie.

No API key or Apify credits needed. Requires the user to paste their
li_at cookie (from linkedin.com DevTools → Application → Cookies).

Uses headless Chromium (not the persistent profile, no extension required).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

log = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _text(el) -> str:
    try:
        return el.inner_text().strip()
    except Exception:
        return ""


def _attr(el, attr: str) -> str:
    try:
        return el.get_attribute(attr) or ""
    except Exception:
        return ""


def _parse_count(raw: str) -> int:
    """Turn '1,234', '1.2K', '12K', '1M' etc. into an integer."""
    if not raw:
        return 0
    raw = raw.replace(",", "").replace(" ", "").lower()
    try:
        if raw.endswith("k"):
            return int(float(raw[:-1]) * 1000)
        if raw.endswith("m"):
            return int(float(raw[:-1]) * 1_000_000)
        # Strip non-numeric suffix (e.g. "12 reactions")
        num = re.sub(r"[^\d.]", "", raw.split()[0] if " " in raw else raw)
        return int(float(num)) if num else 0
    except Exception:
        return 0


def _make_post(author_name: str, author_url: str, text: str, url: str,
               likes: int, comments: int, source_type: str,
               source_label: str) -> dict:
    return {
        "author_name": author_name,
        "author_url": author_url,
        "post_text": text,
        "post_url": url,
        "likes": likes,
        "comments_count": comments,
        "source_type": source_type,
        "source_label": source_label,
        "posted_at": None,
    }


# ─── Selectors (tries multiple, LinkedIn changes them often) ──────────────────

_POST_CONTAINERS = [
    ".feed-shared-update-v2",
    "[data-urn*='activity']",
    ".occludable-update",
]
_AUTHOR_NAME_SELECTORS = [
    ".update-components-actor__name",
    ".feed-shared-actor__name",
    ".app-aware-link .actor-name",
    ".update-components-actor__title span[aria-hidden='true']",
]
_AUTHOR_LINK_SELECTORS = [
    ".update-components-actor__image",
    ".feed-shared-actor__container-link",
    ".update-components-actor__meta-link",
]
_TEXT_SELECTORS = [
    ".update-components-text .break-words",
    ".feed-shared-update-v2__description .break-words",
    ".update-components-text",
    ".feed-shared-text__text-view",
]
_LIKES_SELECTORS = [
    ".social-details-social-counts__reactions-count",
    "[aria-label*='reaction']",
    ".social-details-social-counts__count-value",
]
_COMMENTS_SELECTORS = [
    ".social-details-social-counts__comments",
    "[aria-label*='comment']",
]
_POST_LINK_SELECTORS = [
    ".update-components-actor__sub-description a",
    "time a",
    ".feed-shared-update-v2__update-content-wrapper a[href*='activity']",
    "a[href*='/posts/']",
    "a[href*='ugcPost']",
]


def _extract_posts_from_page(page, source_type: str, source_label: str,
                              max_posts: int) -> list[dict]:
    """Scroll and extract post cards from the currently loaded LinkedIn page."""
    posts: list[dict] = []
    seen_urls: set[str] = set()

    for _ in range(8):  # scroll rounds
        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        time.sleep(2.5)

        # Try each container selector
        containers = []
        for sel in _POST_CONTAINERS:
            try:
                containers = page.query_selector_all(sel)
                if containers:
                    break
            except Exception:
                pass

        for card in containers:
            if len(posts) >= max_posts:
                break

            # ── Author name ──────────────────────────────────────────────────
            author_name = ""
            for sel in _AUTHOR_NAME_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        author_name = _text(el)
                        break
                except Exception:
                    pass

            # ── Author URL ───────────────────────────────────────────────────
            author_url = ""
            for sel in _AUTHOR_LINK_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        href = _attr(el, "href")
                        if href and "linkedin.com/in/" in href:
                            author_url = href.split("?")[0]
                            break
                except Exception:
                    pass

            # ── Post text ────────────────────────────────────────────────────
            post_text = ""
            for sel in _TEXT_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        post_text = _text(el)
                        if post_text:
                            break
                except Exception:
                    pass
            if not post_text:
                continue  # skip empty posts

            # ── Post URL ─────────────────────────────────────────────────────
            post_url = ""
            for sel in _POST_LINK_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        href = _attr(el, "href")
                        if href and ("activity" in href or "/posts/" in href or "ugcPost" in href):
                            post_url = href.split("?")[0]
                            break
                except Exception:
                    pass
            if not post_url or post_url in seen_urls:
                continue
            seen_urls.add(post_url)

            # ── Likes ────────────────────────────────────────────────────────
            likes = 0
            for sel in _LIKES_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        likes = _parse_count(_text(el))
                        break
                except Exception:
                    pass

            # ── Comments ─────────────────────────────────────────────────────
            comments = 0
            for sel in _COMMENTS_SELECTORS:
                try:
                    el = card.query_selector(sel)
                    if el:
                        comments = _parse_count(_text(el))
                        break
                except Exception:
                    pass

            posts.append(_make_post(
                author_name=author_name or "Unknown",
                author_url=author_url,
                text=post_text,
                url=post_url,
                likes=likes,
                comments=comments,
                source_type=source_type,
                source_label=source_label,
            ))

        if len(posts) >= max_posts:
            break

    return posts


# ─── Public API ───────────────────────────────────────────────────────────────

def _launch_browser_with_cookie(li_at: str):
    """Launch headless Chromium and set the li_at session cookie."""
    from playwright.sync_api import sync_playwright  # type: ignore

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    context.add_cookies([{
        "name": "li_at",
        "value": li_at,
        "domain": ".linkedin.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "None",
    }])
    return pw, browser, context


def fetch_feed_posts(li_at: str, max_posts: int = 30) -> list[dict]:
    """Scrape the LinkedIn home feed (posts from connections)."""
    if not li_at:
        raise ValueError("li_at cookie is required")

    log.info("LinkedIn feed scraper: fetching home feed (max=%d)", max_posts)
    pw = browser = context = page = None
    try:
        pw, browser, context = _launch_browser_with_cookie(li_at)
        page = context.new_page()
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Detect if we were redirected to login
        if "login" in page.url or "checkpoint" in page.url:
            raise RuntimeError("LinkedIn session expired — please refresh your li_at cookie")

        posts = _extract_posts_from_page(page, "connection", "My Feed", max_posts)
        log.info("LinkedIn feed scraper: found %d posts from feed", len(posts))
        return posts
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass


def fetch_hashtag_posts(li_at: str, hashtag: str, max_posts: int = 20) -> list[dict]:
    """Scrape posts for a given hashtag (e.g. '#marketing' or 'marketing')."""
    if not li_at:
        raise ValueError("li_at cookie is required")

    tag = hashtag.lstrip("#").strip()
    label = f"#{tag}"
    url = f"https://www.linkedin.com/search/results/content/?keywords=%23{quote(tag)}&origin=HASH_TAG_FROM_FEED"

    log.info("LinkedIn feed scraper: fetching hashtag %s (max=%d)", label, max_posts)
    pw = browser = context = page = None
    try:
        pw, browser, context = _launch_browser_with_cookie(li_at)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if "login" in page.url or "checkpoint" in page.url:
            raise RuntimeError("LinkedIn session expired — please refresh your li_at cookie")

        posts = _extract_posts_from_page(page, "hashtag", label, max_posts)
        log.info("LinkedIn feed scraper: found %d posts for %s", len(posts), label)
        return posts
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
