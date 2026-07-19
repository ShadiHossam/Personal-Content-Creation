"""Per-project dataset storage for scraper runs.

Mirrors the pattern in ``social_plan_tool/storage.py`` but scoped per-user:
results are written under ``projects/<user_id>/<slug>/scraper_datasets/``.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.Lock()

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BASE_PROJECTS_DIR = os.path.join(_BASE_DIR, "data", "scraper_datasets")


def _datasets_dir(slug: str) -> str:
    # Guard against path traversal — slug is caller-supplied (query param),
    # so reject anything that isn't a plain path segment.
    if not slug or "/" in slug or "\\" in slug or ".." in slug:
        raise ValueError(f"invalid project slug: {slug!r}")
    return os.path.join(_BASE_PROJECTS_DIR, slug)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_run_id(platform: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{platform}_{ts}_{uuid.uuid4().hex[:6]}"


def save_dataset(
    slug: str,
    platform: str,
    kind: str,
    records: list[dict],
    *,
    account_handle: str = "",
    meta: dict | None = None,
) -> dict:
    if not slug:
        raise ValueError("project slug is required")
    run_id = _new_run_id(platform)
    record = {
        "run_id": run_id,
        "project_slug": slug,
        "platform": platform,
        "kind": kind,
        "account_handle": account_handle,
        "count": len(records),
        "saved_at": _now_iso(),
        "meta": meta or {},
        "records": records,
    }
    with _lock:
        directory = _datasets_dir(slug)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
    return record


def list_datasets(slug: str) -> list[dict]:
    directory = _datasets_dir(slug)
    if not os.path.isdir(directory):
        return []
    out = []
    for fname in os.listdir(directory):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        try:
            with open(os.path.join(directory, fname), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        out.append(
            {
                "run_id": data.get("run_id", fname[:-5]),
                "platform": data.get("platform", ""),
                "kind": data.get("kind", ""),
                "account_handle": data.get("account_handle", ""),
                "count": data.get("count", 0),
                "saved_at": data.get("saved_at", ""),
            }
        )
    out.sort(key=lambda r: r["saved_at"], reverse=True)
    return out


def get_dataset(slug: str, run_id: str) -> dict | None:
    # Guard against path traversal — run_id is generated server-side so should
    # be a simple token, but validate defensively.
    if "/" in run_id or ".." in run_id or "\\" in run_id:
        return None
    path = os.path.join(_datasets_dir(slug), f"{run_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def delete_dataset(slug: str, run_id: str) -> bool:
    if "/" in run_id or ".." in run_id or "\\" in run_id:
        return False
    path = os.path.join(_datasets_dir(slug), f"{run_id}.json")
    with _lock:
        if not os.path.isfile(path):
            return False
        os.remove(path)
    return True
