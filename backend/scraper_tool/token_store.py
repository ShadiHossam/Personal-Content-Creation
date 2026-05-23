"""Encrypted per-user per-platform OAuth token storage.

Tokens are encrypted at rest with Fernet. The key comes from the
``SCRAPER_TOKEN_KEY`` env var — on first run (if unset) a key is generated
and cached to ``data/scraper_tokens/.key`` so development keeps working, but
in production the operator should set it via the host's env (cPanel UI for
o2switch) and delete the cached file.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

_lock = threading.Lock()

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOKENS_ROOT = os.path.join(_BASE_DIR, "data", "scraper_tokens")
_KEY_FILE = os.path.join(_TOKENS_ROOT, ".key")


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("SCRAPER_TOKEN_KEY", "").strip()
    if env_key:
        try:
            # Validate it's a proper Fernet key (32 url-safe base64 bytes)
            raw = base64.urlsafe_b64decode(env_key.encode())
            if len(raw) != 32:
                raise ValueError
            return env_key.encode()
        except Exception as exc:
            raise RuntimeError("SCRAPER_TOKEN_KEY is set but not a valid Fernet key") from exc
    os.makedirs(_TOKENS_ROOT, exist_ok=True)
    if os.path.isfile(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def _user_dir() -> str:
    path = os.path.join(_TOKENS_ROOT, "default")
    os.makedirs(path, exist_ok=True)
    return path


def _token_path(platform: str) -> str:
    return os.path.join(_user_dir(), f"{platform}.json.enc")


def save_token(platform: str, token: dict[str, Any]) -> None:
    """Encrypt and persist a token record for the current user + platform."""
    record = dict(token)
    record.setdefault("saved_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    record["platform"] = platform
    payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
    encrypted = _get_fernet().encrypt(payload)
    with _lock, open(_token_path(platform), "wb") as f:
        f.write(encrypted)


def load_token(platform: str) -> dict | None:
    path = _token_path(platform)
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


def delete_token(platform: str) -> bool:
    path = _token_path(platform)
    with _lock:
        if not os.path.isfile(path):
            return False
        os.remove(path)
    return True


def list_connections() -> list[dict]:
    """Return a list of {platform, account_handle, saved_at, expires_at} for the user."""
    try:
        udir = _user_dir()
    except RuntimeError:
        return []
    out = []
    for fname in sorted(os.listdir(udir)):
        if not fname.endswith(".json.enc"):
            continue
        platform = fname[: -len(".json.enc")]
        tok = load_token(platform)
        if not tok:
            continue
        out.append(
            {
                "platform": platform,
                "account_handle": tok.get("account_handle", ""),
                "account_id": tok.get("account_id", ""),
                "saved_at": tok.get("saved_at", ""),
                "expires_at": tok.get("expires_at", ""),
            }
        )
    return out
