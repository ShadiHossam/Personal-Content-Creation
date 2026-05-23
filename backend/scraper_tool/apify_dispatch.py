"""Apify dispatch shim used by the social-fetch handlers.

For each platform (Instagram, TikTok, LinkedIn, Meta Ads) the corresponding
fetch handler calls into here first; if Apify is enabled for that platform
and an API token is configured, we run the configured Apify actor and return
a result dict shaped like the legacy path's output.

Single-user adaptation: settings are read from environment variables only
(no DB-backed integration credentials store). Set e.g. ``APIFY_TOKEN`` and
``APIFY_INSTAGRAM_ENABLED=1`` in the environment to enable Apify for a
platform; per-platform actor overrides via ``APIFY_<PLATFORM>_ACTOR``.
"""

from __future__ import annotations

import logging
import os

from backend.scraper_tool.clients import apify_actors
from backend.scraper_tool.clients.apify_client import ApifyRunError, run_actor_sync

log = logging.getLogger(__name__)

PLATFORMS = ("instagram", "tiktok", "linkedin", "fbads", "facebook", "twitter")


# ── Settings access ────────────────────────────────────────────────────


def _read_setting(key: str) -> str:
    """Read an integration setting from the environment.

    Looks up the upper-cased env var (``apify_token`` -> ``APIFY_TOKEN``).
    Returns "" when unset.
    """
    return os.environ.get(key.upper(), "").strip()


def _truthy(s: str) -> bool:
    return s.strip().lower() in ("1", "true", "yes", "on")


def is_enabled(platform: str) -> bool:
    if platform not in PLATFORMS:
        return False
    return _truthy(_read_setting(f"apify_{platform}_enabled"))


def get_token() -> str:
    return _read_setting("apify_token")


def get_actor(platform: str) -> str:
    selected = _read_setting(f"apify_{platform}_actor")
    if selected:
        return selected
    return apify_actors.default_actor_for(platform)


# ── Per-platform run helpers ───────────────────────────────────────────
#
# Each helper either returns the canonical result dict (or tuple, for
# tiktok) or raises ApifyRunError, which the calling fetch handler swallows
# to fall back to the legacy path.


def run_instagram(username: str, max_posts: int = 50) -> dict:
    token = get_token()
    actor = get_actor("instagram")
    run_input = apify_actors.build_input_instagram(username, max_posts=max_posts)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_instagram(items, username)


def run_tiktok(username: str, max_videos: int = 30) -> tuple[dict, list[dict]]:
    token = get_token()
    actor = get_actor("tiktok")
    run_input = apify_actors.build_input_tiktok(username, max_videos=max_videos)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_tiktok(items, username)


def run_linkedin(url: str) -> dict:
    token = get_token()
    actor = get_actor("linkedin")
    run_input = apify_actors.build_input_linkedin(url)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_linkedin(items, url)


def run_fbads(query: str, country: str = "ALL") -> dict:
    token = get_token()
    actor = get_actor("fbads")
    run_input = apify_actors.build_input_fbads(query, country=country)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_fbads(items, query, country)


def run_facebook(target: str, max_posts: int = 30) -> dict:
    token = get_token()
    actor = get_actor("facebook")
    run_input = apify_actors.build_input_facebook(target, max_posts=max_posts)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_facebook(items, target)


def run_twitter(target: str, max_tweets: int = 30) -> dict:
    token = get_token()
    actor = get_actor("twitter")
    run_input = apify_actors.build_input_twitter(target, max_tweets=max_tweets)
    items = run_actor_sync(actor, run_input, token)
    return apify_actors.map_result_twitter(items, target)


__all__ = [
    "ApifyRunError",
    "PLATFORMS",
    "get_actor",
    "get_token",
    "is_enabled",
    "run_facebook",
    "run_fbads",
    "run_instagram",
    "run_linkedin",
    "run_tiktok",
    "run_twitter",
]
