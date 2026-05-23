"""OAuth flow helpers per platform.

Each provider module exposes:
    - META: dict
    - authorize_url(state) -> str
    - exchange_code(code) -> dict
        Either a single token dict (single-platform providers like Reddit)
        or a mapping {platform_id: token_dict} (Meta returns both
        ``facebook`` and ``instagram``).
    - refresh(token) -> dict
"""

from backend.scraper_tool.oauth import google, linkedin, meta, reddit, tiktok

# Mapping platform_id -> provider module used for the OAuth handshake.
# Note: ``instagram`` shares the Meta provider, so /connect/instagram and
# /connect/facebook resolve to the same flow; the callback writes both
# token slots.
PROVIDERS = {
    "reddit": reddit,
    "youtube": google,
    "facebook": meta,
    "instagram": meta,
    "tiktok": tiktok,
    "linkedin": linkedin,
}

# Display metadata per platform for the providers list endpoint.
DISPLAY_META = {
    "reddit": reddit.META,
    "youtube": google.META,
    "facebook": meta.META,
    "instagram": meta.INSTAGRAM_META,
    "tiktok": tiktok.META,
    "linkedin": linkedin.META,
}

__all__ = ["PROVIDERS", "DISPLAY_META", "google", "linkedin", "meta", "reddit", "tiktok"]
