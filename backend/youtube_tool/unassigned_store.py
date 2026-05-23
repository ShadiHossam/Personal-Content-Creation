"""Persistence for 'unassigned' YouTube channels.

These are channels you've started tracking without tying them to an admin project
yet. Stored locally in ``data/unassigned_channels.json`` with the same slug
that indexes their SQLite DB. Can be promoted to an admin project later.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone

_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "unassigned_channels.json")
)
_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load():
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(items):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return f"unassigned-{s or 'channel'}"


def _ensure_unique_slug(base, existing):
    used = {e.get("slug") for e in existing}
    if base not in used:
        return base
    i = 2
    while f"{base}-{i}" in used:
        i += 1
    return f"{base}-{i}"


def list_all():
    return _load()


def get(slug):
    for item in _load():
        if item.get("slug") == slug:
            return item
    return None


def create(name, channel_url, language="en", description=""):
    with _LOCK:
        items = _load()
        slug = _ensure_unique_slug(_slugify(name), items)
        rec = {
            "slug": slug,
            "name": (name or "Unassigned channel").strip(),
            "channel_url": (channel_url or "").strip(),
            "language": (language or "en").strip(),
            "description": (description or "").strip(),
            "created_at": _now(),
            "updated_at": _now(),
        }
        items.append(rec)
        _write(items)
    return rec


def update(slug, patch):
    with _LOCK:
        items = _load()
        for i, item in enumerate(items):
            if item.get("slug") == slug:
                for k in ("name", "channel_url", "language", "description"):
                    if k in patch and patch[k] is not None:
                        item[k] = patch[k].strip() if isinstance(patch[k], str) else patch[k]
                item["updated_at"] = _now()
                items[i] = item
                _write(items)
                return item
    return None


def delete(slug):
    with _LOCK:
        items = _load()
        new_items = [x for x in items if x.get("slug") != slug]
        if len(new_items) == len(items):
            return False
        _write(new_items)
    return True
