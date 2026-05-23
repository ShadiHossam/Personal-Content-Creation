"""Chrome-extension driver for the social-scrape tool.

Launches a persistent-profile Chromium with one of the configured Chrome
extensions loaded (Instant Data Scraper for v1) and drives it programmatically
via Playwright. The persistent profile means logged-in extensions
(Chat4Data etc., when added later) only need to be set up once.

Why persistent context? Headless mode disables extensions entirely, and a
non-persistent context drops cookies between runs, forcing the user to log
into the extension every time. `launch_persistent_context` solves both.

The extension itself is **not bundled** with this app — Chrome Web Store
licensing forbids redistribution. The setup instruction is:

  1. Install the extension manually in your normal Chrome profile.
  2. Copy the unpacked extension folder from
     ~/Library/Application Support/Google/Chrome/Default/Extensions/<id>/<ver>/
     into <repo>/scraper_tool/extensions/instant-data-scraper/

If the extension folder is missing, `run_idsmcr` raises
`ExtensionNotConfigured`, which the cascade catches and falls through.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


# Defaults — overridable via env. The extensions ship with the package, the
# Chrome profile is created lazily under the project's data dir.
_PKG_DIR = Path(__file__).resolve().parent
_DEFAULT_EXTENSION_DIR = _PKG_DIR / "extensions"
_DATA_DIR = _PKG_DIR.parent.parent / "data"
_DEFAULT_PROFILE_DIR = _DATA_DIR / "scraper_chrome_profile"


class _Settings:
    """Tiny shim replacing the original Flask-style ``app.config.settings``."""

    @property
    def extension_dir(self) -> str:
        return os.environ.get("SCRAPER_EXTENSION_DIR", str(_DEFAULT_EXTENSION_DIR))

    @property
    def chrome_profile_dir(self) -> str:
        return os.environ.get("SCRAPER_CHROME_PROFILE_DIR", str(_DEFAULT_PROFILE_DIR))

    @property
    def chromium_executable_path(self) -> str:
        return os.environ.get("SCRAPER_CHROMIUM_EXECUTABLE_PATH", "")


settings = _Settings()


class ExtensionNotConfigured(RuntimeError):
    """Raised when an extension is selected but not installed locally.

    The cascade orchestrator catches this and tries the next method.
    """


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        # Resolve relative to the repo root (the cwd of the running server).
        p = Path.cwd() / p
    return p


def _ensure_extension(name: str) -> Path:
    base = _resolve_path(settings.extension_dir)
    ext = base / name
    if not ext.exists() or not ext.is_dir():
        raise ExtensionNotConfigured(
            f"extension not found at {ext}. See scraper_tool/extension_driver.py docstring "
            f"for setup instructions."
        )
    # Sanity-check that the folder looks like an unpacked extension.
    if not (ext / "manifest.json").exists():
        raise ExtensionNotConfigured(f"manifest.json missing in {ext}")
    return ext


def _ensure_profile() -> Path:
    profile = _resolve_path(settings.chrome_profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def run_idsmcr(
    platform: str,
    target_url: str,
    max_seconds: int = 90,
    max_records: int = 30,
    max_scrolls: int = 30,
    fetch_comments: bool = False,
    max_comments_per_post: int = 20,
    enrich_posts: bool = False,
    max_posts_to_enrich: int = 50,
) -> dict:
    """Drive Instant Data Scraper against `target_url`.

    The extension auto-detects table-like data on the page. We:
      1. Launch persistent Chromium with the extension loaded.
      2. Navigate to the target URL.
      3. Wait for the page to settle.
      4. Read whatever structured data the page exposes via the extension's
         injected helpers (or, fallback, via DOM scraping).

    Returns the same shape as the other methods: {profile, records, raw}.
    Raises ExtensionNotConfigured / TimeoutError when the run fails — both
    are caught by the cascade.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ExtensionNotConfigured(f"playwright not installed: {e}") from e

    ext_path = _ensure_extension("instant-data-scraper")
    profile_dir = _ensure_profile()

    records: list[dict] = []
    page_title = ""
    final_url = target_url
    profile_image = ""

    exe = settings.chromium_executable_path or None
    if exe and not Path(exe).exists():
        log.warning("chromium_executable_path %s not found; falling back to Playwright Chromium", exe)
        exe = None

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=exe,
            headless=False,  # extensions don't run headless
            args=[
                f"--disable-extensions-except={ext_path}",
                f"--load-extension={ext_path}",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        # Hide automation signals so Google OAuth ("Sign in with Google") works.
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            if (!window.chrome) window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # LinkedIn person profile pages only render ~5-10 activity items
            # as a preview. The dedicated /recent-activity/all/ page lists
            # the entire activity feed. Auto-redirect for /in/<slug>/ URLs.
            nav_url = target_url
            if platform == "linkedin" and "/in/" in target_url and "/recent-activity" not in target_url:
                nav_url = target_url.rstrip("/") + "/recent-activity/all/"

            page.goto(nav_url, wait_until="domcontentloaded", timeout=max_seconds * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                # Some social pages never go fully idle; that's OK, we still
                # have the DOM.
                pass

            page_title = page.title()
            final_url = page.url

            # Derive the target username from the URL for own-post filtering.
            _username = _username_from_url(platform, nav_url)

            # X (and to a lesser extent IG/LinkedIn) virtualize the post
            # list — items leave the DOM once scrolled past — so a final
            # one-shot extract only sees the current viewport. We instead
            # extract on every scroll and merge cumulatively, deduping by URL.
            collected: dict[str, dict] = {}

            # Initial settle so the first paint completes before extracting.
            page.wait_for_timeout(1500)

            stale_scrolls = 0
            for scroll_i in range(max_scrolls):
                # Detect if we've been bounced to an auth wall mid-scroll
                # (LinkedIn does this aggressively). If so, stop trying.
                try:
                    cur_url = page.url
                    if any(s in cur_url for s in ("/login", "/authwall", "/checkpoint")):
                        log.info("Hit auth wall at %s, stopping scroll loop", cur_url)
                        break
                except Exception:
                    pass

                # The page can navigate during eval_on_selector_all, raising
                # "Execution context was destroyed". Treat that as a stale
                # scroll rather than a hard error.
                try:
                    batch = _extract_records(page, platform, limit=max_records, username=_username)
                except Exception as e:
                    log.info("Extract failed during scroll loop (%s); treating as stale", e)
                    batch = []

                added = 0
                for r in batch:
                    # Dedup by URL when available, otherwise by text content.
                    # Avoid including position in the key — LinkedIn's virtualised
                    # feed re-renders the same posts at different scroll positions.
                    key = r.get("url") or r.get("text", "")[:120] or f"_idx_{len(collected)}"
                    if key not in collected:
                        collected[key] = r
                        added += 1

                if len(collected) >= max_records:
                    break

                try:
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(1100)
                except Exception:
                    break

                if added == 0:
                    stale_scrolls += 1
                    if stale_scrolls >= 3:
                        break
                else:
                    stale_scrolls = 0

            records = list(collected.values())

            # Optional second pass: enrich each post with comments / full details.
            do_enrich = fetch_comments or enrich_posts
            if do_enrich and records:
                to_enrich = [r for r in records if r.get("url")][:max_posts_to_enrich]
                log.info("Enriching %d posts (comments=%s enrich=%s)", len(to_enrich), fetch_comments, enrich_posts)
                for rec in to_enrich:
                    post_url = rec["url"]
                    try:
                        if platform == "instagram" and enrich_posts:
                            details = _enrich_ig_post(page, post_url, max_comments_per_post if fetch_comments else 0)
                            rec.update({k: v for k, v in details.items() if v})
                        elif fetch_comments:
                            comments = _fetch_post_comments(page, platform, post_url, max_comments_per_post)
                            if comments:
                                rec["comments_data"] = comments
                    except Exception as e:
                        log.info("Enrich failed for %s: %s", post_url, e)

            # X profile pages put a pinned tweet on top regardless of date.
            # Sort by timestamp descending so "latest" really is latest;
            # records without timestamps fall to the bottom but keep their
            # relative order.
            if platform == "twitter":
                def _ts(r):
                    return r.get("timestamp") or ""
                records.sort(key=_ts, reverse=True)

            records = records[:max_records]
            if not records:
                # Fallback: anchor permalinks only.
                fallback_sel = {
                    "instagram": "a[href*='/p/'], a[href*='/reel/']",
                    "twitter": "article a[href*='/status/']",
                    "linkedin": "a[href*='/posts/'], a[href*='/feed/update/']",
                    "facebook": "a[href*='/posts/'], a[href*='/photo/'], a[href*='/videos/']",
                }.get(platform)
                if fallback_sel:
                    links = page.eval_on_selector_all(
                        fallback_sel,
                        "els => els.map(e => ({href: e.href, text: (e.innerText || '').trim().slice(0,200)}))",
                    )
                    seen: set[str] = set()
                    for link in links:
                        href = link.get("href") or ""
                        if not href or href in seen:
                            continue
                        seen.add(href)
                        records.append({"url": href, "text": link.get("text") or ""})

            # Extract profile image from the loaded page DOM
            profile_image = _extract_profile_image(page, platform)

        finally:
            ctx.close()

    return {
        "profile": {"name": page_title, "url": final_url, "image": profile_image},
        "records": records,
        "raw": {"title": page_title, "final_url": final_url, "extension": "instant-data-scraper"},
    }


def _extract_profile_image(page, platform: str) -> str:
    """Extract the profile owner's avatar URL from the currently loaded page."""
    try:
        if platform == "linkedin":
            return page.evaluate(r"""() => {
                // On /recent-activity/all/ the first post actor is the profile owner.
                const imgs = [
                    '.update-components-actor__avatar-image',
                    '.feed-shared-actor__avatar-image',
                    '.presence-entity__image',
                    '.pv-top-card-profile-picture__image',
                    'img.evi-image.lazy-image',
                ];
                for (const sel of imgs) {
                    const el = document.querySelector(sel);
                    if (el && el.src && !el.src.startsWith('data:')) return el.src;
                }
                return '';
            }""") or ""
        if platform == "twitter":
            return page.evaluate(r"""() => {
                const el = document.querySelector('a[data-testid="UserAvatar-Container-unknown"] img, [data-testid="UserAvatar-Container"] img');
                return (el && el.src && !el.src.startsWith('data:')) ? el.src : '';
            }""") or ""
        if platform == "instagram":
            return page.evaluate(r"""() => {
                // Profile page header avatar
                const el = document.querySelector('header img, img[alt*="profile picture"], section img');
                return (el && el.src && !el.src.startsWith('data:')) ? el.src : '';
            }""") or ""
        if platform == "tiktok":
            return page.evaluate(r"""() => {
                const el = document.querySelector('[data-e2e="user-avatar"] img, .tiktok-avatar img');
                return (el && el.src && !el.src.startsWith('data:')) ? el.src : '';
            }""") or ""
    except Exception as e:
        log.debug("profile image extraction failed for %s: %s", platform, e)
    return ""


def _extract_records(page, platform: str, limit: int = 30, username: str = "") -> list[dict]:
    """Per-platform DOM walks that pull text + images + engagement from each
    post element. `limit` caps the slice so a fully-loaded long feed doesn't
    serialize a megabyte of DOM back over CDP. Returns [] when the page
    didn't render any structured posts (e.g. logged-out IG, LinkedIn auth
    wall) so the caller falls back to the anchor-only extractor."""
    if platform == "twitter":
        return page.eval_on_selector_all(
            'article[data-testid="tweet"]',
            r"""(articles) => articles.slice(0, """ + str(limit) + r""").map(art => {
                const linkEl = art.querySelector('a[href*="/status/"][role="link"] time')
                              ? art.querySelector('a[href*="/status/"][role="link"]')
                              : art.querySelector('a[href*="/status/"]');
                const textEl = art.querySelector('[data-testid="tweetText"]');
                const timeEl = art.querySelector('time');
                const imgs = Array.from(art.querySelectorAll('img[src*="pbs.twimg.com/media"], div[data-testid="tweetPhoto"] img'))
                              .map(i => i.src);
                // Videos — Twitter may use blob: for DRM content; capture non-blob sources + poster.
                const videoEls = Array.from(art.querySelectorAll('video'));
                const videos = videoEls.flatMap(v => {
                    const srcs = Array.from(v.querySelectorAll('source'))
                        .map(s => s.src || s.getAttribute('src'))
                        .filter(s => s && !s.startsWith('blob:'));
                    if (!v.src.startsWith('blob:') && v.src) srcs.push(v.src);
                    return srcs;
                });
                const videoPosters = videoEls.map(v => v.poster).filter(Boolean);
                const hasVideo = videoEls.length > 0;
                // Parse the leading number out of aria-label strings like "12 Likes. Like"
                const grabNum = sel => {
                    const el = art.querySelector(sel);
                    if (!el) return '';
                    const raw = (el.getAttribute('aria-label') || el.innerText || '').trim();
                    const m = raw.match(/^([\d,]+)/);
                    return m ? m[1].replace(/,/g, '') : raw;
                };
                // Detect pinned tweets — X marks them with a "Pinned" label.
                const pinnedEl = art.querySelector('[data-testid="socialContext"]');
                const pinnedText = pinnedEl ? pinnedEl.innerText.trim() : '';
                const isPinned = /pinned/i.test(pinnedText);
                return {
                    url: linkEl ? linkEl.href : '',
                    text: textEl ? textEl.innerText.trim() : '',
                    timestamp: timeEl ? timeEl.getAttribute('datetime') : '',
                    images: imgs,
                    videos,
                    video_posters: videoPosters,
                    has_video: hasVideo,
                    replies: grabNum('[data-testid="reply"]'),
                    retweets: grabNum('[data-testid="retweet"]'),
                    likes: grabNum('[data-testid="like"]'),
                    views: grabNum('a[href$="/analytics"]'),
                    pinned: isPinned,
                    social_context: pinnedText,
                };
            }).filter(r => r.url)"""
        )
    if platform == "instagram":
        # Filter to only the profile owner's posts — exclude tagged posts from
        # other accounts that also appear on the /tagged/ tab or sidebar.
        user_filter = f"/{username}/" if username else ""
        return page.eval_on_selector_all(
            'a[href*="/p/"], a[href*="/reel/"]',
            r"""(anchors, userFilter) => {
                const seen = new Set();
                const out = [];
                anchors.forEach(a => {
                    const href = a.href.split('?')[0];
                    if (!href || seen.has(href)) return;
                    // If we know the username, skip posts not owned by this user.
                    if (userFilter && !href.includes(userFilter)) return;
                    seen.add(href);
                    const img = a.querySelector('img');
                    // Try to get like/comment counts from overlay (visible on hover in grid)
                    const countEls = a.querySelectorAll('li');
                    let likes = '', comments = '';
                    countEls.forEach(li => {
                        const txt = li.innerText.trim();
                        if (/like/i.test(li.innerHTML)) likes = txt.replace(/[^\d,]/g,'');
                        else if (/comment/i.test(li.innerHTML)) comments = txt.replace(/[^\d,]/g,'');
                    });
                    out.push({
                        url: href,
                        text: img ? (img.alt || '') : '',
                        images: img ? [img.src] : [],
                        likes,
                        comments,
                    });
                });
                return out.slice(0, """ + str(limit) + r""");
            }""",
            user_filter,
        )
    if platform == "linkedin":
        return page.eval_on_selector_all(
            '.feed-shared-update-v2, .update-components-update-v2, article.feed-shared-update-v2',
            r"""posts => posts.slice(0, """ + str(limit) + r""").map(p => {
                const textEl = p.querySelector('.feed-shared-update-v2__commentary, .update-components-text, .feed-shared-text');
                // Prefer explicit post link; fall back to constructing from data-urn.
                const linkEl = p.querySelector('a[href*="/posts/"], a[href*="/feed/update/"]');
                const urn = p.getAttribute('data-urn') || '';
                const postUrl = linkEl ? linkEl.href
                    : (urn ? 'https://www.linkedin.com/feed/update/' + urn : '');
                // Post media only — exclude author avatars / headshots.
                const imgs = Array.from(p.querySelectorAll('.update-components-image img, .feed-shared-image img'))
                              .filter(i => !i.closest('.update-components-actor, .feed-shared-actor, .update-components-mini-update-v2'))
                              .map(i => i.src)
                              .filter(s => s && !s.startsWith('data:'));
                // Video sources — LinkedIn serves MP4s from their CDN; blob: URLs are unusable.
                const videoSrcs = Array.from(p.querySelectorAll(
                    '.update-components-video source, .update-components-video video, '
                    + '.feed-shared-update-v2__content video source, video source'
                )).map(s => s.src || s.getAttribute('src'))
                  .filter(s => s && !s.startsWith('blob:') && !s.startsWith('data:'));
                const videoPosters = Array.from(p.querySelectorAll('video[poster]')).map(v => v.poster).filter(Boolean);
                const hasVideo = p.querySelector('.update-components-video, video') !== null;
                // Engagement stats — extract leading number from aria-label/innerText.
                const grabNum = sel => {
                    const el = p.querySelector(sel);
                    if (!el) return '';
                    const raw = (el.getAttribute('aria-label') || el.innerText || '').trim();
                    const m = raw.match(/^([\d,]+)/);
                    return m ? m[1].replace(/,/g,'') : raw.replace(/[^\d]/g,'');
                };
                const likes    = grabNum('.social-details-social-counts__reactions-count, [data-test-id="social-actions__reactions"]');
                const comments = grabNum('.social-details-social-counts__comments, button[aria-label*="comment" i], li.social-details-social-counts__comments');
                const reposts  = grabNum('.social-details-social-counts__shares, button[aria-label*="repost" i]');
                const counts_label = (() => {
                    const el = p.querySelector('.social-details-social-counts, [aria-label*="reaction" i]');
                    return el ? (el.getAttribute('aria-label') || el.innerText || '').trim() : '';
                })();
                return {
                    url: postUrl,
                    text: textEl ? textEl.innerText.trim() : '',
                    images: imgs,
                    videos: videoSrcs,
                    video_posters: videoPosters,
                    has_video: hasVideo,
                    likes,
                    comments,
                    reposts,
                    counts_label,
                };
            }).filter(r => r.url || r.text)"""
        )
    if platform == "facebook":
        return page.eval_on_selector_all(
            'div[role="article"]',
            r"""posts => posts.slice(0, 30).map(p => {
                const textEl = p.querySelector('[data-ad-preview="message"], [data-ad-comet-preview="message"]');
                const linkEl = p.querySelector('a[href*="/posts/"], a[href*="/photo/"], a[href*="/videos/"]');
                const imgs = Array.from(p.querySelectorAll('img[src*="scontent"]'))
                              .map(i => i.src).filter(s => s && !s.startsWith('data:'));
                return {
                    url: linkEl ? linkEl.href : '',
                    text: textEl ? textEl.innerText.trim() : '',
                    images: imgs,
                };
            }).filter(r => r.url || r.text)"""
        )
    if platform == "tiktok":
        # TikTok uses data-e2e attributes for stable selectors. Each post tile
        # is `div[data-e2e="user-post-item"]`. The play count (only number
        # rendered inline) lives on `strong[data-e2e="video-views"]`.
        return page.eval_on_selector_all(
            'div[data-e2e="user-post-item"]',
            r"""items => items.slice(0, 60).map(it => {
                const linkEl = it.querySelector('a[href*="/video/"]');
                const img = it.querySelector('img');
                const viewsEl = it.querySelector('strong[data-e2e="video-views"]');
                // Caption is usually the link's `aria-label` or a sibling.
                const caption = (linkEl && linkEl.getAttribute('aria-label')) || '';
                return {
                    url: linkEl ? linkEl.href : '',
                    text: caption,
                    cover: img ? img.src : '',
                    play_count_text: viewsEl ? viewsEl.innerText.trim() : '',
                };
            }).filter(r => r.url)"""
        )
    return []


def _username_from_url(platform: str, url: str) -> str:
    """Extract the profile username/slug from a profile URL."""
    try:
        from urllib.parse import urlparse
        parts = urlparse(url).path.strip("/").split("/")
        if platform == "linkedin" and len(parts) >= 2 and parts[0] == "in":
            return parts[1]
        if platform in ("twitter", "instagram", "tiktok", "facebook") and parts:
            return parts[0].lstrip("@")
    except Exception:
        pass
    return ""


def _fetch_post_comments(page, platform: str, post_url: str, max_comments: int = 20) -> list[dict]:
    """Navigate to a single post and extract its comments/replies."""
    page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1800)

    if platform == "linkedin":
        # Scroll once to trigger lazy-load of comments.
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1500)
        # LinkedIn 2024+ uses obfuscated class names on the post permalink page.
        # We find comment items structurally: <li> elements that contain a
        # profile link (/in/ URL) AND have non-trivial text content.
        return page.evaluate(
            r"""(max) => {
                const seen = new Set();
                const out = [];
                document.querySelectorAll('li').forEach(li => {
                    if (out.length >= max) return;
                    // Must have a profile link inside
                    const profileLink = li.querySelector('a[href*="/in/"]');
                    if (!profileLink) return;
                    // Must have meaningful text (more than just the author name)
                    const allText = li.innerText.trim();
                    if (allText.length < 10) return;
                    // Skip nav/sidebar items by checking depth (comment li are deep)
                    // and ensuring there's a block of paragraph-length text.
                    const textNodes = [...li.querySelectorAll('span, p, div')]
                        .filter(el => !el.querySelector('a') && el.innerText.trim().length > 10)
                        .map(el => el.innerText.trim());
                    const commentText = textNodes.find(t => t.length > 15) || '';
                    if (!commentText || seen.has(commentText)) return;
                    seen.add(commentText);
                    const authorName = profileLink.innerText.trim() ||
                        profileLink.getAttribute('aria-label') || '';
                    const timeEl = li.querySelector('time');
                    // Reaction count — a number-only span/button near the bottom of the li
                    const likeEl = [...li.querySelectorAll('span, button')]
                        .find(el => /^\d+$/.test(el.innerText.trim()));
                    out.push({
                        author: authorName,
                        text: commentText,
                        timestamp: timeEl ? (timeEl.getAttribute('datetime') || timeEl.innerText.trim()) : '',
                        likes: likeEl ? likeEl.innerText.trim() : '',
                    });
                });
                return out;
            }""",
            max_comments,
        )

    if platform == "twitter":
        # Replies appear as tweet articles after the first (the original tweet).
        return page.eval_on_selector_all(
            'article[data-testid="tweet"]',
            r"""(articles, max) => articles.slice(1, max + 1).map(art => {
                const nameEl = art.querySelector('[data-testid="User-Name"]');
                const textEl = art.querySelector('[data-testid="tweetText"]');
                const timeEl = art.querySelector('time');
                const grabNum = sel => {
                    const el = art.querySelector(sel);
                    if (!el) return '';
                    const raw = (el.getAttribute('aria-label') || el.innerText || '').trim();
                    const m = raw.match(/^([\d,]+)/);
                    return m ? m[1].replace(/,/g,'') : raw;
                };
                return {
                    author: nameEl ? nameEl.innerText.trim() : '',
                    text: textEl ? textEl.innerText.trim() : '',
                    timestamp: timeEl ? timeEl.getAttribute('datetime') : '',
                    likes: grabNum('[data-testid="like"]'),
                };
            }).filter(c => c.text)""",
            max_comments,
        )

    if platform == "instagram":
        return page.eval_on_selector_all(
            'ul._a9z6 li, ul.x78zum5 li',
            r"""(items, max) => items.slice(0, max).map(li => {
                const spans = li.querySelectorAll('span');
                let author = '', text = '';
                spans.forEach(s => {
                    if (s.closest('a') && !author) author = s.innerText.trim();
                    else if (s.innerText.length > author.length && !s.closest('a')) text = s.innerText.trim();
                });
                return { author, text };
            }).filter(c => c.text)""",
            max_comments,
        )

    return []


def _enrich_ig_post(page, post_url: str, max_comments: int = 0) -> dict:
    """Visit a single Instagram post and return real caption, engagement, video, comments."""
    import re as _re
    page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    # Scroll to load comments (they're lazy-loaded below the fold)
    if max_comments > 0:
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(1200)

    raw = page.evaluate(
        r"""(maxComments) => {
            // ── og:description — most reliable source ─────────────────────
            // Format: "N likes, M comments - user on Date: \"caption\""
            const ogEl = document.querySelector('meta[property="og:description"]');
            const ogDesc = ogEl ? ogEl.getAttribute('content') || '' : '';

            // ── Video ─────────────────────────────────────────────────────
            const videoEl = document.querySelector('video');
            let videoUrl = '', videoPoster = '';
            if (videoEl) {
                const srcEl = videoEl.querySelector('source');
                const raw = (srcEl && srcEl.src) || videoEl.src || '';
                videoUrl = raw.startsWith('blob:') ? '' : raw;
                videoPoster = videoEl.poster || '';
            }

            // ── Comments ──────────────────────────────────────────────────
            // Each comment is a sibling <div> with innerText structured as:
            //   "[username]\n \n[timestamp]\n[comment text]\nReply\n..."
            // Find the container whose children ALL contain "Reply" text.
            const comments = [];
            if (maxComments > 0) {
                const skipLine = /^(reply|see translation|view all|like|follow|following|\s*)$/i;
                const isTimestamp = /^\d+[wdhms]$/i;

                // Find the comment container — a div where every direct child div
                // contains "Reply" (all comments have a Reply button).
                const containers = [...document.querySelectorAll('div')]
                    .filter(d => {
                        const kids = [...d.children];
                        return kids.length >= 2 &&
                            kids.every(k => k.tagName === 'DIV' && k.innerText.includes('Reply'));
                    })
                    .sort((a, b) => b.children.length - a.children.length);

                if (containers.length > 0) {
                    [...containers[0].children].slice(0, maxComments).forEach(div => {
                        const lines = div.innerText.split('\n')
                            .map(l => l.trim()).filter(l => l.length > 0);
                        const author = lines[0] || '';
                        let commentText = '';
                        for (let i = 1; i < lines.length; i++) {
                            const l = lines[i];
                            if (isTimestamp.test(l)) continue;
                            if (skipLine.test(l)) continue;
                            if (/^\d+ like/.test(l)) continue;
                            commentText = l;
                            break;
                        }
                        if (author && commentText) comments.push({ author, text: commentText });
                    });
                }
            }

            return { ogDesc, videoUrl, videoPoster, comments };
        }""",
        max_comments,
    )
    if not raw:
        return {}

    result: dict = {}

    # Parse og:description: "N likes, M comments - user on Date: \"caption\""
    og = raw.get("ogDesc", "")
    if og:
        m_likes = _re.search(r"([\d,]+)\s+like", og, _re.IGNORECASE)
        m_comments = _re.search(r"([\d,]+)\s+comment", og, _re.IGNORECASE)
        m_caption = _re.search(r':\s+"(.+)"', og, _re.DOTALL)
        if m_likes:
            result["likes"] = m_likes.group(1).replace(",", "")
        if m_comments:
            result["comments_count"] = m_comments.group(1).replace(",", "")
        if m_caption:
            result["caption"] = m_caption.group(1).strip()

    if raw.get("videoUrl"):
        result["video_url"] = raw["videoUrl"]
    if raw.get("videoPoster"):
        result["video_poster"] = raw["videoPoster"]
        result["has_video"] = True
    if raw.get("comments"):
        result["comments_data"] = raw["comments"]

    return result


__all__ = ["ExtensionNotConfigured", "run_idsmcr"]
