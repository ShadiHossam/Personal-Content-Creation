"""Shared helpers for OAuth2 flows (FastAPI / single-user adaptation)."""

from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime, timezone

_state_lock = threading.Lock()
_STATES: dict[str, str] = {}


def generate_state(platform: str) -> str:
    token = secrets.token_urlsafe(32)
    with _state_lock:
        _STATES[platform] = token
    return token


def verify_state(platform: str, provided: str) -> bool:
    if not provided:
        return False
    with _state_lock:
        expected = _STATES.pop(platform, None)
    return bool(expected) and secrets.compare_digest(expected, provided)


def redirect_uri(platform: str) -> str:
    base = os.environ.get("SCRAPER_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/scraper/callback/{platform}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seconds_from_now(seconds: int) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(seconds=max(0, int(seconds or 0)))).isoformat(timespec="seconds")


class OAuthError(RuntimeError):
    """Raised when an OAuth handshake fails or credentials are missing."""


def require_env(var: str, platform: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val:
        raise OAuthError(
            f"{platform}: environment variable {var} is not set. "
            f"Register a developer app and add the credential to your env."
        )
    return val


def require_credential(platform: str, key: str, env_var: str) -> str:
    from backend.scraper_tool import credentials_store

    val = credentials_store.lookup(platform, key, env_var)
    if not val:
        raise OAuthError(
            f"{platform}: missing {key}. Open My Accounts and click Connect on "
            f"{platform} to paste your developer-app credentials."
        )
    return val
