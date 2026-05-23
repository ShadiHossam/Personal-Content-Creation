"""Meta OAuth (single flow covering Facebook Pages + Instagram Business).

One Meta app at https://developers.facebook.com unlocks both surfaces.  After
``exchange_code`` we fetch the user's Pages, pick the first Page (or the one
matching ``META_OAUTH_DEFAULT_PAGE_ID``), and derive the linked Instagram
Business Account if present. The returned mapping therefore populates both
``facebook`` and ``instagram`` token slots from a single OAuth handshake.

Env vars required:
    META_OAUTH_CLIENT_ID          (Meta App ID)
    META_OAUTH_CLIENT_SECRET      (Meta App Secret)
    META_OAUTH_DEFAULT_PAGE_ID    (optional — pick a specific Page)
    META_GRAPH_VERSION            (optional; defaults to v19.0)
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

import requests

from backend.scraper_tool.oauth.base import OAuthError, redirect_uri, require_credential, seconds_from_now

META = {
    "id": "facebook",
    "name": "Facebook / Instagram (Meta)",
    "scopes": [
        "pages_show_list",
        "pages_read_engagement",
        "pages_read_user_content",
        "read_insights",
        "instagram_basic",
        "instagram_manage_insights",
    ],
    "docs_url": "https://developers.facebook.com/docs/graph-api",
    "setup_url": "https://developers.facebook.com/apps",
}

# Instagram is exposed as a separate platform slot but shares this OAuth flow.
INSTAGRAM_META = {
    "id": "instagram",
    "name": "Instagram (via Meta)",
    "scopes": META["scopes"],
    "docs_url": "https://developers.facebook.com/docs/instagram-api",
    "setup_url": META["setup_url"],
}


def _graph_version() -> str:
    return os.environ.get("META_GRAPH_VERSION", "v19.0")


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{_graph_version()}{path}"


AUTH_URL_TEMPLATE = "https://www.facebook.com/{v}/dialog/oauth"


def authorize_url(state: str) -> str:
    client_id = require_credential("facebook", "client_id", "META_OAUTH_CLIENT_ID")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri("facebook"),
        "state": state,
        "scope": ",".join(META["scopes"]),
        "response_type": "code",
    }
    return f"{AUTH_URL_TEMPLATE.format(v=_graph_version())}?{urlencode(params)}"


def _exchange_short_lived(code: str) -> dict:
    client_id = require_credential("facebook", "client_id", "META_OAUTH_CLIENT_ID")
    client_secret = require_credential("facebook", "client_secret", "META_OAUTH_CLIENT_SECRET")
    resp = requests.get(
        _graph("/oauth/access_token"),
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri("facebook"),
            "code": code,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise OAuthError(f"meta token exchange {resp.status_code}: {resp.text[:300]}")
    return resp.json() or {}


def _extend_long_lived(short_token: str) -> dict:
    client_id = require_credential("facebook", "client_id", "META_OAUTH_CLIENT_ID")
    client_secret = require_credential("facebook", "client_secret", "META_OAUTH_CLIENT_SECRET")
    resp = requests.get(
        _graph("/oauth/access_token"),
        params={
            "grant_type": "fb_exchange_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "fb_exchange_token": short_token,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise OAuthError(f"meta long-lived exchange {resp.status_code}: {resp.text[:300]}")
    return resp.json() or {}


def _me(access_token: str) -> dict:
    resp = requests.get(
        _graph("/me"),
        params={"fields": "id,name", "access_token": access_token},
        timeout=15,
    )
    return resp.json() if resp.status_code == 200 else {}


def _list_pages(access_token: str) -> list[dict]:
    resp = requests.get(
        _graph("/me/accounts"),
        params={
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": access_token,
            "limit": 100,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return []
    return (resp.json() or {}).get("data") or []


def _pick_page(pages: list[dict]) -> dict | None:
    wanted = os.environ.get("META_OAUTH_DEFAULT_PAGE_ID", "").strip()
    if wanted:
        for p in pages:
            if str(p.get("id")) == wanted:
                return p
    return pages[0] if pages else None


def exchange_code(code: str) -> dict:
    """Return mapping {platform_id: token_dict} — both facebook and instagram."""
    short = _exchange_short_lived(code)
    short_token = short.get("access_token", "")
    if not short_token:
        raise OAuthError("meta: no access_token in exchange response")
    long_lived = _extend_long_lived(short_token)
    user_token = long_lived.get("access_token", short_token)
    expires_at = seconds_from_now(long_lived.get("expires_in", short.get("expires_in", 3600)))

    me = _me(user_token)
    pages = _list_pages(user_token)
    page = _pick_page(pages)

    result: dict[str, dict] = {}

    if page:
        fb_token = {
            "access_token": page.get("access_token") or user_token,  # Page access token
            "user_access_token": user_token,
            "expires_at": expires_at,  # Page tokens usually inherit long-lived 60d
            "account_handle": page.get("name", "") or me.get("name", ""),
            "account_id": str(page.get("id", "")),
            "page_id": str(page.get("id", "")),
            "scope": ",".join(META["scopes"]),
        }
        result["facebook"] = fb_token

        igba = page.get("instagram_business_account") or {}
        if igba.get("id"):
            ig_token = {
                "access_token": page.get("access_token") or user_token,
                "user_access_token": user_token,
                "expires_at": expires_at,
                "account_handle": igba.get("username", ""),
                "account_id": str(igba.get("id", "")),
                "page_id": str(page.get("id", "")),
                "ig_user_id": str(igba.get("id", "")),
                "scope": ",".join(META["scopes"]),
            }
            result["instagram"] = ig_token
    else:
        # No pages — store a user-level facebook token so at least profile works.
        result["facebook"] = {
            "access_token": user_token,
            "user_access_token": user_token,
            "expires_at": expires_at,
            "account_handle": me.get("name", ""),
            "account_id": str(me.get("id", "")),
            "scope": ",".join(META["scopes"]),
        }

    return result


def refresh(token: dict) -> dict:
    """Meta long-lived tokens are not refreshable via a refresh_token flow —
    the user can re-extend the token by re-authenticating. We try extending
    the stored user token in place; if that fails the caller surfaces a
    reconnect-required error.
    """
    user_token = token.get("user_access_token") or token.get("access_token")
    if not user_token:
        raise OAuthError("meta: no user_access_token stored; user must reconnect")
    try:
        ext = _extend_long_lived(user_token)
    except OAuthError:
        raise
    new_user_token = ext.get("access_token", user_token)
    expires_at = seconds_from_now(ext.get("expires_in", 3600))
    updated = dict(token)
    # Page tokens inherit user token longevity; refresh both.
    updated["user_access_token"] = new_user_token
    updated["access_token"] = new_user_token if token.get("access_token") == user_token else token["access_token"]
    updated["expires_at"] = expires_at
    return updated
