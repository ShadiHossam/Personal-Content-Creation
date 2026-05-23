"""Channel ownership registry — maps a channel's db_slug to a unified project slug.

The per-channel SQLite DB at ``data/youtube_channels/<slug>.db`` is keyed by a
stable ``db_slug``. Ownership (which unified project owns the channel) lives
separately in ``data/channel_ownership.json`` so reassignment is a pointer
update, not a file move.

Resolution order when the registry has no explicit entry:
  1. ``unassigned-*`` slug → None (the Unassigned pool).
  2. ``_adhoc_*`` slug → None (ad-hoc, no persisted ownership).
  3. Slug matches a unified project slug → that project owns it (implicit).
  4. Otherwise → None (orphan; surfaced by orphan-scan).
"""

from __future__ import annotations

import json
import os
import threading

_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "channel_ownership.json")
)
_LOCK = threading.Lock()


def _load() -> dict:
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, _PATH)


def get_owner(db_slug: str) -> str | None:
    """Return the explicit owner project_slug, or None if unassigned/not set."""
    if not db_slug:
        return None
    m = _load()
    v = m.get(db_slug)
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def set_owner(db_slug: str, project_slug: str | None) -> None:
    if not db_slug:
        return
    with _LOCK:
        m = _load()
        if project_slug and project_slug.strip():
            m[db_slug] = project_slug.strip()
        else:
            # Explicit None clears the entry so resolution falls back to implicit rules.
            m.pop(db_slug, None)
        _write(m)


def all_owners() -> dict:
    """Return a copy of the full ownership map."""
    return dict(_load())


def channels_for_project(project_slug: str) -> list[str]:
    """Return all db_slugs explicitly owned by the given project."""
    if not project_slug:
        return []
    return sorted(k for k, v in _load().items() if v == project_slug)


def remove_owner(db_slug: str) -> None:
    set_owner(db_slug, None)
