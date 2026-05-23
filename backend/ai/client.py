"""Centralized Claude client: Anthropic SDK (API key) or claude CLI (subscription)."""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from sqlalchemy.orm import Session

MODEL = "claude-sonnet-4-6"


def get_backend(db: Session) -> str:
    from ..models import Setting
    row = db.query(Setting).filter(Setting.key == "claude_backend").first()
    return (row.value or "api").strip() if row else "api"


def get_api_key(db: Session) -> str | None:
    from ..models import Setting
    row = db.query(Setting).filter(Setting.key == "claude_api_key").first()
    return row.value if row and row.value else None


def resolve_backend(db: Session) -> tuple[str, str | None]:
    """Return (backend, api_key_or_None). Raises ValueError if nothing is available."""
    backend = get_backend(db)

    if backend == "cli":
        if not shutil.which("claude"):
            raise ValueError(
                "Claude CLI not found on PATH. "
                "Install Claude Code (claude.ai/code) or switch to API key mode in Settings."
            )
        return "cli", None

    api_key = get_api_key(db)
    if api_key:
        return "api", api_key

    # Auto-fallback to CLI when no API key is set
    if shutil.which("claude"):
        return "cli", None

    raise ValueError(
        "Claude is not configured. Add an Anthropic API key in Settings → API Keys, "
        "or install the Claude CLI (claude.ai/code) to use your subscription."
    )


def call_claude(
    user_prompt: str,
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
) -> str:
    """Single-turn Claude call. Returns the text response."""
    backend, api_key = resolve_backend(db)
    if backend == "api":
        return _api_call(
            [{"role": "user", "content": user_prompt}],
            api_key=api_key,
            system=system,
            max_tokens=max_tokens,
        )
    return _cli_call(user_prompt, system=system)


def call_claude_messages(
    messages: list[dict],
    *,
    system: str = "",
    db: Session,
    max_tokens: int = 2000,
) -> str:
    """Multi-turn Claude call. Returns the text response."""
    backend, api_key = resolve_backend(db)
    if backend == "api":
        return _api_call(messages, api_key=api_key, system=system, max_tokens=max_tokens)

    # CLI: flatten conversation history into a single prompt
    parts = []
    for m in messages:
        label = "Human" if m["role"] == "user" else "Assistant"
        parts.append(f"{label}: {m['content']}")
    return _cli_call("\n\n".join(parts), system=system)


def get_anthropic_client(db: Session):
    """Return a raw anthropic.Anthropic client (API-only, for tool-use loops etc.)."""
    api_key = get_api_key(db)
    if not api_key:
        raise ValueError(
            "This feature requires an Anthropic API key. Add it in Settings → API Keys."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


# ── private helpers ──────────────────────────────────────────────────────────

def _api_call(
    messages: list[dict],
    *,
    api_key: str,
    system: str,
    max_tokens: int,
) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return next((b.text for b in response.content if hasattr(b, "text")), "")


def _cli_call(user_prompt: str, *, system: str) -> str:
    cli = shutil.which("claude")
    if not cli:
        raise ValueError("Claude CLI not found on PATH.")
    cmd = [cli, "-p", "--output-format", "text"]
    if system:
        cmd += ["--append-system-prompt", system]
    proc = subprocess.run(
        cmd,
        input=user_prompt,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"Claude CLI error: {(proc.stderr or '').strip()[:300]}")
    return (proc.stdout or "").strip()
