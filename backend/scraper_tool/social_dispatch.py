"""Cascade orchestrator for the social-scrape tool.

The tool offers three methods to fetch a public profile:

    direct_cffi      — curl_cffi + chrome131 fingerprint (+ session cookies if saved)
    apify            — managed actor via apify_dispatch (already in this repo)
    extension_idsmcr — Playwright + Chrome with an unpacked Instant Data Scraper

`run_with_cascade(platform, target, primary)` runs `primary` first, then walks
the rest of `DEFAULT_LADDER[platform]` until one succeeds. It only catches
*expected* failures (HTTP 4xx/429, ApifyRunError, ExtensionNotConfigured,
Playwright timeout); programming errors propagate so we don't silently mask
bugs. Each attempt is recorded with status / error / elapsed-ms so the UI
can show what happened.

Each method returns the same shape:

    {"records": [...], "profile": {...}, "raw": <method-specific>}

so the front-end doesn't need to branch on which method won.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from backend.scraper_tool import apify_dispatch
from backend.scraper_tool.apify_dispatch import ApifyRunError, _read_setting

log = logging.getLogger(__name__)


SUPPORTED_PLATFORMS = ("linkedin", "twitter", "instagram", "facebook", "tiktok")


# ── Cookie loading from credentials store ─────────────────────────────


def _cookies_for(platform: str) -> dict:
    """Build the cookies dict to pass into curl_cffi for `platform`."""
    if platform == "linkedin":
        v = _read_setting("linkedin_li_at")
        return {"li_at": v} if v else {}
    if platform == "twitter":
        a = _read_setting("twitter_auth_token")
        c = _read_setting("twitter_ct0")
        out = {}
        if a:
            out["auth_token"] = a
        if c:
            out["ct0"] = c
        return out
    if platform == "instagram":
        v = _read_setting("instagram_sessionid")
        return {"sessionid": v} if v else {}
    if platform == "facebook":
        cu = _read_setting("facebook_c_user")
        xs = _read_setting("facebook_xs")
        out = {}
        if cu:
            out["c_user"] = cu
        if xs:
            out["xs"] = xs
        return out
    return {}


# ── Method handlers ───────────────────────────────────────────────────


def _normalize_direct_linkedin(record: dict) -> dict:
    return {
        "profile": {
            "name": record.get("jsonld_name") or record.get("og_title") or "",
            "description": record.get("jsonld_description") or record.get("og_description") or "",
            "image": record.get("og_image") or "",
            "auth_wall_hit": record.get("auth_wall_hit"),
        },
        "records": [],
        "raw": record,
    }


def _normalize_direct_twitter(record: dict) -> dict:
    tweets = record.get("tweets") or []
    return {
        "profile": {
            "name": record.get("x_og_title") or "",
            "description": record.get("x_og_description") or "",
        },
        "records": tweets,
        "raw": record,
    }


def _normalize_direct_instagram(record: dict) -> dict:
    user = record.get("api_user") or {}
    return {
        "profile": {
            "name": user.get("full_name") or record.get("og_title") or "",
            "biography": user.get("biography") or "",
            "image": (
                user.get("profile_pic_url_hd")
                or user.get("profile_pic_url")
                or record.get("og_image")
                or ""
            ),
            "followers": user.get("followers"),
            "following": user.get("following"),
            "is_verified": user.get("is_verified"),
            "is_private": user.get("is_private"),
            "media_count": user.get("media_count"),
            "counters_from_og": record.get("counters_from_og") or {},
        },
        "records": record.get("posts") or [],
        "raw": record,
    }


def _normalize_direct_tiktok(record: dict) -> dict:
    profile = record.get("profile") or {}
    return {
        "profile": {
            "name": profile.get("nickname") or record.get("og_title") or "",
            "description": profile.get("signature") or record.get("og_description") or "",
            "image": profile.get("avatar") or record.get("og_image") or "",
            "followers": profile.get("followers"),
            "following": profile.get("following"),
            "video_count": profile.get("video_count"),
            "heart_count": profile.get("heart_count"),
            "is_verified": profile.get("verified"),
        },
        "records": record.get("videos") or [],
        "raw": record,
    }


def _normalize_direct_facebook(record: dict) -> dict:
    variants = record.get("variants") or []
    pick = next((v for v in variants if v.get("og_title")), variants[0] if variants else {})
    return {
        "profile": {
            "name": pick.get("og_title") or "",
            "description": pick.get("og_description") or "",
            "image": pick.get("og_image") or "",
            "login_redirect": pick.get("login_redirect"),
        },
        "records": [],
        "raw": record,
    }


def run_direct_cffi(platform: str, target: str, max_records: int = 30) -> dict:
    """Method 1: curl_cffi with Chrome fingerprint + saved session cookies.

    Raises RuntimeError when the response came back but contains no
    useful data — that signals the cascade to try the next method instead
    of returning a falsely-successful empty result.

    The underlying scrape_demo helpers fetch whatever the public endpoint
    returns (typically ~12 for Instagram web_profile_info); we trim the
    record list to max_records so the cap is at least honored downstream.
    """
    from scrape_demo import run_demo

    cookies = _cookies_for(platform)
    if platform == "linkedin":
        rec = run_demo.scrape_linkedin(target, cookies=cookies)
        out = _normalize_direct_linkedin(rec)
        if rec.get("status", 0) >= 400 or (
            not out["profile"].get("name") and not out["profile"].get("description")
        ):
            raise RuntimeError(
                f"linkedin direct returned no data (status={rec.get('status')}, "
                f"authwall={rec.get('auth_wall_hit')})"
            )
        return out
    if platform == "twitter":
        rec = run_demo.scrape_twitter(target, cookies=cookies)
        out = _normalize_direct_twitter(rec)
        if not out["records"] and not out["profile"].get("name"):
            raise RuntimeError(
                f"twitter direct returned no data (x_status={rec.get('x_status')}, "
                f"syndication={rec.get('syndication_status')})"
            )
        out["records"] = out["records"][:max_records]
        return out
    if platform == "instagram":
        rec = run_demo.scrape_instagram(target, cookies=cookies)
        out = _normalize_direct_instagram(rec)
        api_status = rec.get("api_status") or 0
        if api_status >= 400 and not out["records"] and not out["profile"].get("followers"):
            raise RuntimeError(f"instagram web_profile_info HTTP {api_status}")
        out["records"] = out["records"][:max_records]
        return out
    if platform == "facebook":
        rec = run_demo.scrape_facebook(target, cookies=cookies)
        out = _normalize_direct_facebook(rec)
        if not out["profile"].get("name") and not out["profile"].get("description"):
            raise RuntimeError("facebook direct returned no profile data (login redirect?)")
        return out
    if platform == "tiktok":
        rec = run_demo.scrape_tiktok(target, cookies=cookies)
        out = _normalize_direct_tiktok(rec)
        if not out["records"] and not out["profile"].get("name") and not out["profile"].get("followers"):
            raise RuntimeError(
                f"tiktok direct returned no data (status={rec.get('status')})"
            )
        out["records"] = out["records"][:max_records]
        return out
    raise ValueError(f"unsupported platform for direct_cffi: {platform}")


def run_apify_method(platform: str, target: str, max_records: int = 30) -> dict:
    """Method 2: managed Apify actor via apify_dispatch."""
    if not apify_dispatch.get_token():
        raise ApifyRunError("apify_token not configured")
    if platform in ("linkedin", "instagram", "facebook", "tiktok", "twitter") and not apify_dispatch.is_enabled(platform):
        raise ApifyRunError(f"apify_{platform}_enabled is off")

    if platform == "tiktok":
        profile, posts = apify_dispatch.run_tiktok(target.lstrip("@"), max_videos=max_records)
        return {
            "profile": {
                "name": profile.get("nickname") or profile.get("uniqueId") or target,
                "description": profile.get("signature") or "",
                "image": profile.get("avatarLarger") or profile.get("avatarMedium") or "",
                "followers": profile.get("followers"),
                "following": profile.get("following"),
                "video_count": profile.get("video_count") or profile.get("videoCount"),
                "heart_count": profile.get("heart_count") or profile.get("heartCount"),
                "is_verified": profile.get("verified"),
            },
            "records": posts or [],
            "raw": {"profile": profile, "posts": posts},
        }
    if platform == "instagram":
        result = apify_dispatch.run_instagram(target, max_posts=max_records)
        prof = result.get("profile") or {}
        return {
            "profile": {
                "name": prof.get("full_name") or prof.get("username") or "",
                "biography": prof.get("biography") or "",
                "image": prof.get("profile_pic") or prof.get("profile_pic_url") or "",
                "followers": prof.get("followers"),
                "following": prof.get("following"),
                "is_verified": prof.get("is_verified"),
                "media_count": prof.get("posts_count"),
            },
            "records": result.get("posts") or [],
            "raw": result,
        }
    if platform == "linkedin":
        url = target if target.startswith("http") else f"https://www.linkedin.com/company/{target}/"
        result = apify_dispatch.run_linkedin(url)
        # map_result_linkedin returns the profile dict flat (no "posts" key).
        return {
            "profile": {
                "name": result.get("name") or "",
                "description": result.get("description") or "",
                "image": result.get("image") or result.get("logo") or "",
                "followers": result.get("followers"),
                "industry": result.get("industry") or "",
                "headquarters": result.get("headquarters") or "",
                "url": result.get("url") or url,
            },
            "records": [],
            "raw": result,
        }
    if platform == "facebook":
        result = apify_dispatch.run_facebook(target, max_posts=max_records)
        prof = result.get("profile") or {}
        return {
            "profile": {
                "name": prof.get("name") or "",
                "description": prof.get("description") or "",
                "image": prof.get("image") or "",
                "followers": prof.get("followers"),
                "likes": prof.get("likes"),
                "category": prof.get("category") or "",
                "url": prof.get("url") or "",
                "is_verified": prof.get("is_verified"),
            },
            "records": result.get("posts") or [],
            "raw": result,
        }
    if platform == "twitter":
        result = apify_dispatch.run_twitter(target, max_tweets=max_records)
        prof = result.get("profile") or {}
        return {
            "profile": {
                "name": prof.get("name") or "",
                "username": prof.get("username") or "",
                "description": prof.get("description") or "",
                "image": prof.get("image") or "",
                "followers": prof.get("followers"),
                "following": prof.get("following"),
                "tweets_count": prof.get("tweets_count"),
                "is_verified": prof.get("is_verified"),
            },
            "records": result.get("tweets") or [],
            "raw": result,
        }
    raise ApifyRunError(f"no apify path for platform: {platform}")


def run_extension_idsmcr(platform: str, target: str, max_records: int = 30) -> dict:
    """Method 3: Playwright + Instant Data Scraper extension."""
    # Lazy import so the module loads even when Playwright isn't installed.
    from backend.scraper_tool import extension_driver

    target_url = _target_to_url(platform, target)
    # Instagram's profile grid doesn't expose likes/comments/timestamps —
    # only the post page does. Enrich each post so we get real engagement
    # numbers instead of zeros.
    enrich_posts = platform == "instagram"
    return extension_driver.run_idsmcr(
        platform,
        target_url,
        max_records=max_records,
        enrich_posts=enrich_posts,
        max_posts_to_enrich=max_records,
    )


def _target_to_url(platform: str, target: str) -> str:
    if target.startswith("http"):
        return target
    if platform == "linkedin":
        return f"https://www.linkedin.com/company/{target}/"
    if platform == "twitter":
        return f"https://x.com/{target}"
    if platform == "instagram":
        return f"https://www.instagram.com/{target}/"
    if platform == "facebook":
        return f"https://www.facebook.com/{target}"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{target.lstrip('@')}"
    raise ValueError(f"unsupported platform: {platform}")


# ── Method registry + cascade ──────────────────────────────────────────


METHODS: dict[str, tuple[Callable[[str, str], dict], set[str]]] = {
    "direct_cffi": (run_direct_cffi, {"linkedin", "twitter", "instagram", "facebook", "tiktok"}),
    "apify": (run_apify_method, {"linkedin", "instagram", "tiktok", "facebook", "twitter"}),
    "extension_idsmcr": (run_extension_idsmcr, {"linkedin", "twitter", "instagram", "facebook", "tiktok"}),
}


DEFAULT_LADDER: dict[str, list[str]] = {
    "linkedin": ["extension_idsmcr", "direct_cffi", "apify"],
    "twitter": ["extension_idsmcr", "direct_cffi", "apify"],
    "instagram": ["extension_idsmcr", "direct_cffi", "apify"],
    "facebook": ["extension_idsmcr", "direct_cffi", "apify"],
    "tiktok": ["extension_idsmcr", "direct_cffi", "apify"],
}


# Only catch failures that mean "this method couldn't get the data" — not
# programmer bugs like AttributeError or KeyError.
# ImportError covers missing optional deps (e.g. scrape_demo not installed) —
# treat as "this method is unavailable" and fall through.
_EXPECTED_FAILURES = (ApifyRunError, RuntimeError, TimeoutError, OSError, ValueError, ImportError)


def run_with_cascade(
    platform: str,
    target: str,
    primary: str | None = None,
    max_records: int = 30,
) -> dict:
    if platform not in DEFAULT_LADDER:
        raise ValueError(f"unsupported platform: {platform}")

    ladder = list(DEFAULT_LADDER[platform])
    if primary and primary in METHODS and primary != ladder[0]:
        # Move user-chosen primary to the front, dedup the rest.
        ladder = [primary] + [m for m in ladder if m != primary]

    attempts: list[dict] = []
    for method_name in ladder:
        if method_name not in METHODS:
            continue
        fn, supported = METHODS[method_name]
        if platform not in supported:
            attempts.append(
                {"method": method_name, "ok": False, "skipped": True, "error": "platform not supported by method"}
            )
            continue

        t0 = time.monotonic()
        try:
            data = fn(platform, target, max_records=max_records)
            ms = int((time.monotonic() - t0) * 1000)
            attempts.append({"method": method_name, "ok": True, "ms": ms})
            return {
                "ok": True,
                "platform": platform,
                "target": target,
                "method": method_name,
                "data": data,
                "attempts": attempts,
            }
        except _EXPECTED_FAILURES as e:
            ms = int((time.monotonic() - t0) * 1000)
            attempts.append(
                {"method": method_name, "ok": False, "ms": ms, "error": f"{type(e).__name__}: {e}"}
            )
            log.info("social_dispatch %s/%s via %s failed: %s", platform, target, method_name, e)
            continue

    return {
        "ok": False,
        "platform": platform,
        "target": target,
        "method": None,
        "data": None,
        "attempts": attempts,
    }


__all__ = [
    "DEFAULT_LADDER",
    "METHODS",
    "SUPPORTED_PLATFORMS",
    "run_with_cascade",
]
