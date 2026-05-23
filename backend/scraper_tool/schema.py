"""Unified output schema for every scraper adapter.

Every fetcher returns dicts shaped like ``make_record(...)`` so the UI and
downstream tools don't need to know which platform produced the data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PLATFORMS = ("reddit", "youtube", "instagram", "facebook", "tiktok", "linkedin")
KINDS = ("profile", "post", "insight", "comment")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_record(
    platform: str,
    kind: str,
    *,
    account_handle: str = "",
    account_id: str = "",
    id: str = "",
    url: str = "",
    created_at: str = "",
    text: str = "",
    media: list | None = None,
    metrics: dict[str, Any] | None = None,
    raw: dict | None = None,
) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform: {platform}")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    return {
        "platform": platform,
        "kind": kind,
        "account_handle": account_handle,
        "account_id": str(account_id or ""),
        "id": str(id or ""),
        "url": url,
        "created_at": created_at,
        "text": text,
        "media": list(media or []),
        "metrics": dict(metrics or {}),
        "raw": raw or {},
        "scraped_at": now_iso(),
    }


def strip_raw(records: list[dict]) -> list[dict]:
    """Return copies without the `raw` field for UI/export contexts."""
    return [{k: v for k, v in r.items() if k != "raw"} for r in records]
