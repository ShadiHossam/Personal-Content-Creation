"""FastAPI router exposing /api/scraper/* routes."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.scraper_tool import credentials_store, storage, token_store
from backend.scraper_tool.fetchers import run as run_fetch
from backend.scraper_tool.oauth import DISPLAY_META, PROVIDERS
from backend.scraper_tool.oauth.base import OAuthError, generate_state, redirect_uri, verify_state

router = APIRouter(prefix="/api/scraper")

_scraper_store: dict = {"latest": None}
_scraper_status: dict = {"running": False, "progress": "", "done": False}
_state_lock = threading.Lock()


def _try_acquire() -> bool:
    with _state_lock:
        if _scraper_status.get("running"):
            return False
        _scraper_status["running"] = True
        _scraper_status["done"] = False
        _scraper_status["progress"] = "Starting…"
    return True


def _release(progress: str):
    with _state_lock:
        _scraper_status["running"] = False
        _scraper_status["done"] = True
        _scraper_status["progress"] = progress


# ── Provider catalog ────────────────────────────────────────────────────


@router.get("/providers")
def list_providers():
    out = []
    for pid in ("reddit", "youtube", "facebook", "instagram", "tiktok", "linkedin"):
        meta = dict(DISPLAY_META.get(pid) or {})
        out.append(
            {
                "id": pid,
                "name": meta.get("name", pid.title()),
                "scopes": meta.get("scopes", []),
                "setup_url": meta.get("setup_url", ""),
                "docs_url": meta.get("docs_url", ""),
            }
        )
    return {"providers": out}


# ── Connections (token management) ──────────────────────────────────────


@router.get("/connections")
def list_connections():
    return {"connections": token_store.list_connections()}


@router.get("/connect/{platform}")
def start_connect(platform: str):
    provider = PROVIDERS.get(platform)
    if not provider:
        return {"error": f"unsupported platform: {platform}"}
    state_key = credentials_store.canonical(platform)
    try:
        state = generate_state(state_key)
        url = provider.authorize_url(state)
    except OAuthError as exc:
        return {"error": str(exc)}
    return {"auth_url": url}


@router.get("/callback/{platform}")
def oauth_callback(platform: str, code: str = "", state: str = "", error: str = ""):
    provider = PROVIDERS.get(platform)
    if not provider:
        return RedirectResponse(url="/?scraper_error=unsupported_platform")
    if error:
        return RedirectResponse(url=f"/?scraper_error={error}")
    if not verify_state(platform, state):
        return RedirectResponse(url="/?scraper_error=bad_state")
    try:
        result = provider.exchange_code(code)
    except OAuthError as exc:
        return RedirectResponse(url=f"/?scraper_error={exc}")

    if isinstance(result, dict) and "access_token" in result:
        token_store.save_token(platform, result)
        connected = [platform]
    elif isinstance(result, dict):
        connected = []
        for p, tok in result.items():
            token_store.save_token(p, tok)
            connected.append(p)
    else:
        return RedirectResponse(url="/?scraper_error=bad_exchange_response")

    return RedirectResponse(url=f"/?scraper_connected={','.join(connected)}")


@router.post("/disconnect/{platform}")
def disconnect(platform: str):
    ok = token_store.delete_token(platform)
    return {"ok": ok}


# ── Developer-app credentials ────────────────────────────────────────────


@router.get("/credentials/{platform}")
def get_credentials_status(platform: str):
    info = credentials_store.status(platform)
    if not info.get("supported"):
        return {"error": f"unsupported platform: {platform}"}
    info["redirect_uri"] = redirect_uri(credentials_store.canonical(platform))
    return info


class CredentialsBody(BaseModel):
    model_config = {"extra": "allow"}


@router.post("/credentials/{platform}")
def save_credentials(platform: str, body: CredentialsBody):
    if not credentials_store.schema_for(platform):
        return {"error": f"unsupported platform: {platform}"}
    try:
        credentials_store.save(platform, body.model_dump())
    except ValueError as exc:
        return {"error": str(exc)}
    return {"ok": True, "status": credentials_store.status(platform)}


@router.delete("/credentials/{platform}")
def delete_credentials(platform: str):
    if not credentials_store.schema_for(platform):
        return {"error": f"unsupported platform: {platform}"}
    ok = credentials_store.delete(platform)
    return {"ok": ok}


# ── Run a fetch ──────────────────────────────────────────────────────────


class FetchBody(BaseModel):
    platform: str = ""
    kind: str = ""
    project_slug: str = "default"
    options: dict[str, Any] = {}


@router.post("/fetch")
def start_fetch(body: FetchBody):
    platform = body.platform
    kind = body.kind
    slug = body.project_slug or "default"
    options = body.options or {}

    if platform not in PROVIDERS:
        return {"error": f"unsupported platform: {platform}"}
    if not token_store.load_token(platform):
        return {"error": f"{platform} not connected — connect first"}

    if not _try_acquire():
        return {"error": "A scraper run is already in progress"}

    def _work():
        try:
            _scraper_status["progress"] = f"{platform}: fetching…"
            handle, records = run_fetch(platform, kind, options)
            _scraper_status["progress"] = f"{platform}: saving {len(records)} records…"
            dataset = storage.save_dataset(
                slug,
                platform,
                kind,
                records,
                account_handle=handle,
                meta={"options": options},
            )
            _scraper_store["latest"] = {"run_id": dataset["run_id"], "count": dataset["count"]}
            _release(f"Done — {len(records)} records")
        except Exception as exc:
            _scraper_store["latest"] = {"error": str(exc)}
            _release(f"Error: {exc}")

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True}


class BrowserFetchBody(BaseModel):
    platform: str = ""
    target: str = ""
    max_records: int = 50
    fetch_comments: bool = False
    max_comments_per_post: int = 20
    enrich_posts: bool = False
    max_posts_to_enrich: int = 50
    project_slug: str = "default"


@router.post("/browser-fetch")
def start_browser_fetch(body: BrowserFetchBody):
    platform = body.platform.strip()
    target = body.target.strip()
    max_records = max(1, min(body.max_records, 500))
    slug = body.project_slug or "default"

    if not platform:
        return {"error": "platform is required"}
    if not target:
        return {"error": "target URL or handle is required"}

    if not _try_acquire():
        return {"error": "A scraper run is already in progress"}

    def _work():
        try:
            from backend.scraper_tool import extension_driver
            _scraper_status["progress"] = f"{platform}: opening browser…"
            result = extension_driver.run_idsmcr(
                platform=platform,
                target_url=target if target.startswith("http") else _handle_to_url(platform, target),
                max_records=max_records,
                max_scrolls=max(30, max_records * 2),
                fetch_comments=body.fetch_comments,
                max_comments_per_post=body.max_comments_per_post,
                enrich_posts=body.enrich_posts,
                max_posts_to_enrich=body.max_posts_to_enrich,
            )
            records = result.get("records", [])
            _scraper_status["progress"] = f"{platform}: saving {len(records)} records…"
            profile = result.get("profile", {})
            handle = profile.get("url", "").split("/in/")[-1].split("/")[0] if "/in/" in profile.get("url","") else target
            dataset = storage.save_dataset(
                slug,
                platform,
                "posts",
                records,
                account_handle=handle,
                meta={"target": target, "max_records": max_records},
            )
            _scraper_store["latest"] = {"run_id": dataset["run_id"], "count": dataset["count"]}
            _release(f"Done — {len(records)} records")
        except Exception as exc:
            _scraper_store["latest"] = {"error": str(exc)}
            _release(f"Error: {exc}")

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True}


def _handle_to_url(platform: str, target: str) -> str:
    if platform == "linkedin":
        return f"https://www.linkedin.com/in/{target}/"
    if platform == "twitter":
        return f"https://x.com/{target}"
    if platform == "instagram":
        return f"https://www.instagram.com/{target}/"
    if platform == "tiktok":
        return f"https://www.tiktok.com/@{target.lstrip('@')}"
    if platform == "facebook":
        return f"https://www.facebook.com/{target}"
    return target


class CompanyInfoBody(BaseModel):
    target: str = ""
    li_at: str = ""
    project_slug: str = "default"


class CompanyPeopleBody(BaseModel):
    target: str = ""
    li_at: str = ""
    keyword: str = ""
    max_people: int = 50
    project_slug: str = "default"


@router.post("/linkedin/company")
def scrape_linkedin_company(body: CompanyInfoBody):
    target = body.target.strip()
    li_at = body.li_at.strip()
    slug = body.project_slug or "default"

    if not target:
        return {"error": "target is required"}
    if not li_at:
        return {"error": "li_at cookie is required"}
    if not _try_acquire():
        return {"error": "A scraper run is already in progress"}

    def _work():
        try:
            from backend.scraper_tool.clients.linkedin_company import scrape_company
            _scraper_status["progress"] = "LinkedIn: fetching company info…"
            info = scrape_company(target, li_at)
            _scraper_status["progress"] = "LinkedIn: saving…"
            dataset = storage.save_dataset(
                slug, "linkedin", "company_info", [info],
                account_handle=info.get("name", target),
                meta={"target": target},
            )
            _scraper_store["latest"] = {"run_id": dataset["run_id"], "count": dataset["count"]}
            _release(f"Done — company info saved")
        except Exception as exc:
            _scraper_store["latest"] = {"error": str(exc)}
            _release(f"Error: {exc}")

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True}


@router.post("/linkedin/company/people")
def scrape_linkedin_company_people(body: CompanyPeopleBody):
    target = body.target.strip()
    li_at = body.li_at.strip()
    keyword = body.keyword.strip()
    max_people = max(1, min(body.max_people, 500))
    slug = body.project_slug or "default"

    if not target:
        return {"error": "target is required"}
    if not li_at:
        return {"error": "li_at cookie is required"}
    if not _try_acquire():
        return {"error": "A scraper run is already in progress"}

    def _work():
        try:
            from backend.scraper_tool.clients.linkedin_company import scrape_company_people
            _scraper_status["progress"] = f"LinkedIn: fetching employees (max {max_people})…"
            people = scrape_company_people(target, li_at, keyword=keyword, max_people=max_people)
            _scraper_status["progress"] = f"LinkedIn: saving {len(people)} employees…"
            dataset = storage.save_dataset(
                slug, "linkedin", "company_people", people,
                account_handle=target,
                meta={"target": target, "keyword": keyword, "max_people": max_people},
            )
            _scraper_store["latest"] = {"run_id": dataset["run_id"], "count": dataset["count"]}
            _release(f"Done — {len(people)} employees")
        except Exception as exc:
            _scraper_store["latest"] = {"error": str(exc)}
            _release(f"Error: {exc}")

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True}


class CompanySearchBody(BaseModel):
    keyword: str = ""
    location: str = ""
    size_filter: str = ""
    max_results: int = 100
    li_at: str = ""
    project_slug: str = "default"


@router.post("/linkedin/search-companies")
def search_linkedin_companies(body: CompanySearchBody):
    keyword = body.keyword.strip()
    slug = body.project_slug or "default"
    max_results = max(1, min(body.max_results, 500))

    if not keyword:
        return {"error": "keyword is required"}
    if not _try_acquire():
        return {"error": "A scraper run is already in progress"}

    def _work():
        try:
            from backend.scraper_tool import extension_driver
            _scraper_status["progress"] = f"LinkedIn: searching companies for '{keyword}'…"
            companies = extension_driver.search_companies(
                keyword=keyword,
                location=body.location.strip(),
                size_filter=body.size_filter.strip(),
                max_results=max_results,
                li_at=body.li_at.strip(),
            )
            _scraper_status["progress"] = f"LinkedIn: saving {len(companies)} companies…"
            dataset = storage.save_dataset(
                slug, "linkedin", "company_search", companies,
                account_handle=keyword,
                meta={"keyword": keyword, "location": body.location, "size_filter": body.size_filter},
            )
            _scraper_store["latest"] = {"run_id": dataset["run_id"], "count": dataset["count"]}
            _release(f"Done — {len(companies)} companies")
        except Exception as exc:
            _scraper_store["latest"] = {"error": str(exc)}
            _release(f"Error: {exc}")

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True}


@router.get("/status")
def status():
    return {**_scraper_status, "latest": _scraper_store.get("latest")}


# ── Datasets ─────────────────────────────────────────────────────────────


@router.get("/datasets")
def list_datasets(project_slug: str = "default"):
    try:
        return {"datasets": storage.list_datasets(project_slug)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/dataset/{run_id}")
def get_dataset(run_id: str, project_slug: str = "default", include_raw: str = "0"):
    try:
        dataset = storage.get_dataset(project_slug, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not dataset:
        return {"error": "not found"}
    if include_raw != "1":
        from backend.scraper_tool.schema import strip_raw
        dataset = {**dataset, "records": strip_raw(dataset["records"])}
    return dataset


@router.post("/dataset/{run_id}/delete")
def delete_dataset(run_id: str, project_slug: str = "default"):
    try:
        ok = storage.delete_dataset(project_slug, run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": ok}
