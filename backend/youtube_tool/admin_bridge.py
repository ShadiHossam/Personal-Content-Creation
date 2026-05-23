"""Reads YouTube projects + keyword lists from the admin dashboard data files.

Default path points to the sibling admin project. Override with
``YT_ADMIN_DATA_DIR`` env var to point elsewhere (e.g. a copy of the data).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

_DEFAULT_ADMIN_DATA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "creer soceite new website",
        "admin",
        "data",
    )
)


def _data_dir() -> str:
    return os.environ.get("YT_ADMIN_DATA_DIR", _DEFAULT_ADMIN_DATA_DIR)


def _read(filename: str) -> list:
    path = os.path.join(_data_dir(), filename)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def list_projects() -> list[dict]:
    return _read("youtube-projects.json")


def get_project(project_id: int | str) -> dict | None:
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        # Try matching by slug
        for p in list_projects():
            if p.get("slug") == project_id:
                return p
        return None
    for p in list_projects():
        if p.get("id") == pid:
            return p
    return None


def _atomic_write(filename: str, data) -> None:
    path = os.path.join(_data_dir(), filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def create_project(
    name: str,
    channel_url: str,
    language: str = "en",
    description: str = "",
    slug: str | None = None,
    youtube_api_key: str | None = None,
) -> dict:
    """Append a new YouTube project to the admin's youtube-projects.json.

    If `slug` is provided, it is kept (so SQLite data indexed by that slug
    survives a promote-to-project flow). A numeric suffix is added only if
    the requested slug already exists.
    """
    projects = list_projects()
    next_id = max((int(p.get("id") or 0) for p in projects), default=0) + 1
    base_slug = slug or re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or f"project-{next_id}"
    used = {p.get("slug") for p in projects}
    final_slug = base_slug
    i = 2
    while final_slug in used:
        final_slug = f"{base_slug}-{i}"
        i += 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    rec = {
        "id": next_id,
        "slug": final_slug,
        "name": name,
        "description": description,
        "channel_url": channel_url,
        "language": language,
        "created_at": now,
        "updated_at": now,
    }
    if youtube_api_key:
        rec["youtube_api_key"] = youtube_api_key
    projects.append(rec)
    _atomic_write("youtube-projects.json", projects)
    return rec


def get_api_key(project_id: int | str) -> str | None:
    """Return the stored ``youtube_api_key`` for a project, or None if unset."""
    proj = get_project(project_id)
    if not proj:
        return None
    key = proj.get("youtube_api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def list_keyword_lists(project_id: int | str | None = None) -> list[dict]:
    lists = _read("keyword-lists.json")
    if project_id is None:
        return lists
    try:
        pid = int(project_id)
    except (TypeError, ValueError):
        proj = get_project(project_id)
        if not proj:
            return []
        pid = proj["id"]
    return [lst for lst in lists if lst.get("project_id") == pid]


def get_keyword_list(list_id: int | str) -> dict | None:
    try:
        lid = int(list_id)
    except (TypeError, ValueError):
        return None
    for lst in _read("keyword-lists.json"):
        if lst.get("id") == lid:
            return lst
    return None
