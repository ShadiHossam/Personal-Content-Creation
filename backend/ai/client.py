"""Centralized AI client: dispatches to Anthropic, free providers, or Claude CLI.

`call_claude` / `call_claude_messages` are kept as backward-compatible wrappers
around `call_ai`, which is the new unified dispatcher. Routes that need raw
Anthropic features (tool-use, vision) keep using `get_anthropic_client`.
"""
from __future__ import annotations

import shutil
from typing import Any

from sqlalchemy.orm import Session

from .providers import (
    get_provider,
    PROVIDER_CONFIG,
    TokenMissingError,
    TokenInvalidError,
    RateLimitError,
    ClaudeCLINotFoundError,
)

MODEL = "claude-sonnet-4-6"

# Per-feature override setting keys -> feature name used by `call_ai(feature=...)`
FEATURE_SETTING_KEYS = {
    "writing": "ai_provider_for_writing",
    "analysis": "ai_provider_for_analysis",
    "intelligence": "ai_provider_for_intelligence",
}


# ── settings helpers ─────────────────────────────────────────────────────────

def _get_setting(db: Session, key: str) -> str | None:
    from ..models import Setting
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row and row.value else None


def get_backend(db: Session) -> str:
    """Legacy: 'api' or 'cli'. Kept for the older write.py code path."""
    val = _get_setting(db, "claude_backend")
    return (val or "api").strip()


def get_api_key(db: Session) -> str | None:
    return _get_setting(db, "claude_api_key")


def get_provider_key(db: Session, provider_name: str) -> str | None:
    """Resolve the API key stored for a provider."""
    if provider_name == "anthropic":
        return get_api_key(db)
    if provider_name == "claude_cli":
        return None
    return _get_setting(db, f"ai_provider_{provider_name}_key")


def resolve_provider_name(db: Session, feature: str = "default") -> str:
    """Pick a provider name for a given feature, honoring per-feature overrides
    and the global default. Falls back to inferring from legacy `claude_backend`."""
    if feature in FEATURE_SETTING_KEYS:
        override = _get_setting(db, FEATURE_SETTING_KEYS[feature])
        if override and override in PROVIDER_CONFIG:
            return override

    default = _get_setting(db, "ai_provider_default")
    if default and default in PROVIDER_CONFIG:
        return default

    # Legacy fallback: derive from claude_backend
    legacy = get_backend(db)
    if legacy == "cli":
        return "claude_cli"
    return "anthropic"


def resolve_backend(db: Session) -> tuple[str, str | None]:
    """Legacy API kept for write.py. Returns ('api', key) or ('cli', None)."""
    provider = resolve_provider_name(db, "writing")
    if provider == "claude_cli":
        if not shutil.which("claude"):
            raise ValueError(
                "Claude CLI not found on PATH. "
                "Install Claude Code (claude.ai/code) or switch to API key mode in Settings."
            )
        return "cli", None
    if provider == "anthropic":
        key = get_api_key(db)
        if not key:
            raise ValueError(
                "Claude is not configured. Add an Anthropic API key in Settings → API Keys, "
                "or install the Claude CLI to use your subscription."
            )
        return "api", key
    # A free provider was selected — caller (write.py) treats this as 'cli'
    # which triggers the single-shot inline path.
    return "cli", None


# ── unified dispatcher ──────────────────────────────────────────────────────

def call_ai(
    user_prompt: str,
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
    feature: str = "default",
) -> str:
    """Single-turn AI call. Picks provider from settings (with per-feature override)."""
    return call_ai_messages(
        [{"role": "user", "content": user_prompt}],
        system=system, db=db, max_tokens=max_tokens, feature=feature,
    )


def call_ai_messages(
    messages: list[dict],
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
    feature: str = "default",
) -> str:
    """Multi-turn AI call."""
    provider_name = resolve_provider_name(db, feature)
    api_key = get_provider_key(db, provider_name)

    if provider_name == "claude_cli" and not shutil.which("claude"):
        raise ValueError(
            "Claude CLI not found on PATH. "
            "Install Claude Code or pick a different provider in Settings."
        )

    try:
        provider = get_provider(provider_name, api_key)
    except TokenMissingError:
        raise ValueError(
            f"Provider '{provider_name}' has no API key configured. "
            f"Add it in Settings → API Keys, or pick a different provider."
        )

    config = PROVIDER_CONFIG.get(provider_name, {})
    model = config.get("default_model", MODEL)

    try:
        return provider.complete(messages, model, system=system, max_tokens=max_tokens)
    except TokenInvalidError:
        raise ValueError(
            f"The API key saved for '{provider_name}' was rejected. "
            f"Check it in Settings → API Keys."
        )
    except RateLimitError:
        raise ValueError(
            f"Provider '{provider_name}' is rate-limited right now. Try again shortly, "
            f"or switch providers in Settings."
        )


# ── backward-compatible wrappers (do not remove — many routes import these) ──

def call_claude(
    user_prompt: str,
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
) -> str:
    """Legacy single-turn wrapper. Routes through the unified dispatcher."""
    return call_ai(user_prompt, system=system, db=db, max_tokens=max_tokens)


def call_claude_messages(
    messages: list[dict],
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
) -> str:
    """Legacy multi-turn wrapper."""
    return call_ai_messages(messages, system=system, db=db, max_tokens=max_tokens)


def get_anthropic_client(db: Session):
    """Raw anthropic.Anthropic client. Required for tool-use / vision flows."""
    api_key = get_api_key(db)
    if not api_key:
        raise ValueError(
            "This feature requires an Anthropic API key. Add it in Settings → API Keys."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)
