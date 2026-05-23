"""Social media scraper for own accounts via official APIs + OAuth.

Unified tool that lets each user connect their own social accounts (Reddit,
YouTube, Meta/Facebook+Instagram, TikTok, LinkedIn) via OAuth and pull their
own profile/posts/insights data into their project.

No stealth, no proxies, no anti-detection — official APIs only.
"""

from backend.scraper_tool.routes import router as scraper_router

__all__ = ["scraper_router"]
