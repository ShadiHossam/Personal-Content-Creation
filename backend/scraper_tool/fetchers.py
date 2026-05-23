"""Dispatch fetch requests to the right platform client, refreshing tokens as needed."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.scraper_tool import token_store
from backend.scraper_tool.clients import (
    facebook_client,
    instagram_client,
    linkedin_client,
    reddit_client,
    tiktok_client,
    youtube_client,
)
from backend.scraper_tool.oauth import PROVIDERS


def _expired(token: dict) -> bool:
    exp = token.get("expires_at", "")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(exp)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Refresh 60s early to avoid races.
    return dt.timestamp() <= datetime.now(timezone.utc).timestamp() + 60


def _get_fresh_token(platform: str) -> dict:
    token = token_store.load_token(platform)
    if not token:
        raise RuntimeError(f"not connected: {platform}")
    if not _expired(token):
        return token
    provider = PROVIDERS.get(platform)
    if not provider:
        return token
    refreshed = provider.refresh(token)
    for k in ("account_handle", "account_id", "page_id", "ig_user_id", "user_access_token"):
        if k in token and k not in refreshed:
            refreshed[k] = token[k]
    token_store.save_token(platform, refreshed)
    return refreshed


def run(platform: str, kind: str, options: dict) -> tuple[str, list[dict]]:
    """Run a fetch and return (account_handle, records)."""
    options = dict(options or {})
    max_items = int(options.get("max_items") or 100)
    token = _get_fresh_token(platform)
    handle = token.get("account_handle", "")
    access = token.get("access_token", "")

    if platform == "reddit":
        if kind == "profile":
            return handle, reddit_client.fetch_profile(access)
        if kind == "post":
            return handle, reddit_client.fetch_posts(access, handle, max_items=max_items)
        if kind == "comment":
            return handle, reddit_client.fetch_comments(access, handle, max_items=max_items)

    elif platform == "youtube":
        if kind == "profile":
            return handle, youtube_client.fetch_profile(access)
        if kind == "post":
            return handle, youtube_client.fetch_posts(access, max_items=max_items)
        if kind == "comment":
            return handle, youtube_client.fetch_comments(access, max_items=max_items)

    elif platform == "facebook":
        if kind == "profile":
            return handle, facebook_client.fetch_profile(token)
        if kind == "post":
            return handle, facebook_client.fetch_posts(token, max_items=max_items)
        if kind == "insight":
            return handle, facebook_client.fetch_insights(token, max_items=max_items)

    elif platform == "instagram":
        if kind == "profile":
            return handle, instagram_client.fetch_profile(token)
        if kind == "post":
            return handle, instagram_client.fetch_posts(token, max_items=max_items)
        if kind == "insight":
            return handle, instagram_client.fetch_insights(token, max_items=max_items)

    elif platform == "tiktok":
        if kind == "profile":
            return handle, tiktok_client.fetch_profile(access)
        if kind == "post":
            return handle, tiktok_client.fetch_posts(access, max_items=max_items)

    elif platform == "linkedin":
        if kind == "profile":
            return handle, linkedin_client.fetch_profile(access)
        if kind == "post":
            return handle, linkedin_client.fetch_posts(access, token.get("account_id", ""), max_items=max_items)

    raise RuntimeError(f"({platform}, {kind}) is not supported")
