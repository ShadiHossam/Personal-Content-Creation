"""Encrypted per-user OAuth *app* credentials (client_id / client_secret).

Mirrors :mod:`scraper_tool.token_store` but stores the developer-app
credentials a user pastes into the UI — separate from the per-user OAuth
*tokens* obtained by the handshake.

Falls back to env vars when no credential is stored, so existing deployments
that already export ``GOOGLE_OAUTH_CLIENT_ID`` etc. keep working.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from cryptography.fernet import InvalidToken

from backend.scraper_tool.token_store import _get_fernet  # reuse the same Fernet key

_lock = threading.Lock()

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CREDS_ROOT = os.path.join(_BASE_DIR, "data", "scraper_credentials")


# ── Per-platform schema ───────────────────────────────────────────────
# Drives the UI form + the env-var fallback in ``require_credential``.
# ``instagram`` is an alias of ``facebook`` because Meta exposes both
# surfaces through a single OAuth app.

PLATFORM_SCHEMA: dict[str, dict] = {
    "youtube": {
        "name": "YouTube (Google)",
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "docs_note": "Enable 'YouTube Data API v3' and 'YouTube Analytics API' on the project.",
        "fields": [
            {"key": "client_id", "label": "Client ID", "env": "GOOGLE_OAUTH_CLIENT_ID"},
            {"key": "client_secret", "label": "Client Secret", "env": "GOOGLE_OAUTH_CLIENT_SECRET", "secret": True},
        ],
    },
    "facebook": {
        "name": "Facebook + Instagram (Meta)",
        "setup_url": "https://developers.facebook.com/apps",
        "docs_note": "One Meta app covers both Facebook Pages and Instagram Business.",
        "fields": [
            {"key": "client_id", "label": "App ID", "env": "META_OAUTH_CLIENT_ID"},
            {"key": "client_secret", "label": "App Secret", "env": "META_OAUTH_CLIENT_SECRET", "secret": True},
        ],
    },
    "tiktok": {
        "name": "TikTok",
        "setup_url": "https://developers.tiktok.com/",
        "docs_note": "Add the 'Login Kit' and 'Display API' products to your app.",
        "fields": [
            {"key": "client_key", "label": "Client Key", "env": "TIKTOK_OAUTH_CLIENT_KEY"},
            {"key": "client_secret", "label": "Client Secret", "env": "TIKTOK_OAUTH_CLIENT_SECRET", "secret": True},
        ],
    },
    "linkedin": {
        "name": "LinkedIn",
        "setup_url": "https://www.linkedin.com/developers/apps",
        "docs_note": "Add 'Sign In with LinkedIn using OpenID Connect' to your app.",
        "fields": [
            {"key": "client_id", "label": "Client ID", "env": "LINKEDIN_OAUTH_CLIENT_ID"},
            {"key": "client_secret", "label": "Client Secret", "env": "LINKEDIN_OAUTH_CLIENT_SECRET", "secret": True},
        ],
    },
}

# Credentials are stored once for the underlying OAuth app, even if the UI
# exposes multiple platform slots tied to it (Meta → facebook + instagram).
ALIASES: dict[str, str] = {"instagram": "facebook"}


def canonical(platform: str) -> str:
    return ALIASES.get(platform, platform)


def schema_for(platform: str) -> dict | None:
    return PLATFORM_SCHEMA.get(canonical(platform))


# ── Storage ───────────────────────────────────────────────────────────


def _user_dir() -> str:
    path = os.path.join(_CREDS_ROOT, "default")
    os.makedirs(path, exist_ok=True)
    return path


def _path(platform: str) -> str:
    return os.path.join(_user_dir(), f"{canonical(platform)}.json.enc")


def save(platform: str, creds: dict[str, Any]) -> None:
    schema = schema_for(platform)
    if not schema:
        raise ValueError(f"unknown platform: {platform}")
    valid_keys = {f["key"] for f in schema["fields"]}
    cleaned = {k: str(v).strip() for k, v in creds.items() if k in valid_keys and str(v).strip()}
    if not cleaned:
        raise ValueError("no valid credential fields provided")
    payload = json.dumps(cleaned, ensure_ascii=False).encode("utf-8")
    encrypted = _get_fernet().encrypt(payload)
    with _lock, open(_path(platform), "wb") as f:
        f.write(encrypted)


def load(platform: str) -> dict | None:
    try:
        path = _path(platform)
    except RuntimeError:
        return None
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        encrypted = f.read()
    try:
        raw = _get_fernet().decrypt(encrypted)
    except InvalidToken:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def delete(platform: str) -> bool:
    try:
        path = _path(platform)
    except RuntimeError:
        return False
    with _lock:
        if not os.path.isfile(path):
            return False
        os.remove(path)
    return True


# ── Lookup used by OAuth provider modules ─────────────────────────────


def lookup(platform: str, key: str, env_var: str) -> str:
    """Per-user credential first, env var second. Returns '' if neither set."""
    creds = load(platform) or {}
    val = creds.get(key) or ""
    if val:
        return str(val).strip()
    return os.environ.get(env_var, "").strip()


def status(platform: str) -> dict:
    """Public summary — never returns secret values."""
    schema = schema_for(platform)
    if not schema:
        return {"platform": platform, "supported": False}
    creds = load(platform) or {}
    fields_out = []
    all_set = True
    for f in schema["fields"]:
        from_db = bool(creds.get(f["key"]))
        from_env = bool(os.environ.get(f["env"], "").strip())
        is_set = from_db or from_env
        all_set = all_set and is_set
        fields_out.append(
            {
                "key": f["key"],
                "label": f["label"],
                "secret": bool(f.get("secret")),
                "set": is_set,
                "source": "user" if from_db else ("env" if from_env else None),
            }
        )
    return {
        "platform": canonical(platform),
        "supported": True,
        "name": schema["name"],
        "setup_url": schema["setup_url"],
        "docs_note": schema.get("docs_note", ""),
        "fields": fields_out,
        "configured": all_set,
    }
