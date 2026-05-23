"""Reddit OAuth2 (code flow, permanent refresh tokens).

Register an app at https://www.reddit.com/prefs/apps (type: "web app").
Set redirect URI to ``<host>/api/scraper/callback/reddit``.

Env vars required:
    REDDIT_OAUTH_CLIENT_ID
    REDDIT_OAUTH_CLIENT_SECRET
    REDDIT_OAUTH_USER_AGENT   (any descriptive UA; Reddit enforces it)
"""

from __future__ import annotations

import requests

from backend.scraper_tool.oauth.base import OAuthError, redirect_uri, require_env, seconds_from_now

META = {
    "id": "reddit",
    "name": "Reddit",
    "scopes": ["identity", "history", "read", "mysubreddits"],
    "docs_url": "https://github.com/reddit-archive/reddit/wiki/OAuth2",
    "setup_url": "https://www.reddit.com/prefs/apps",
}

AUTH_URL = "https://www.reddit.com/api/v1/authorize"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


def _user_agent() -> str:
    return require_env("REDDIT_OAUTH_USER_AGENT", "reddit")


def authorize_url(state: str) -> str:
    client_id = require_env("REDDIT_OAUTH_CLIENT_ID", "reddit")
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri("reddit"),
        "duration": "permanent",
        "scope": " ".join(META["scopes"]),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    client_id = require_env("REDDIT_OAUTH_CLIENT_ID", "reddit")
    client_secret = require_env("REDDIT_OAUTH_CLIENT_SECRET", "reddit")
    resp = requests.post(
        TOKEN_URL,
        data=data,
        auth=(client_id, client_secret),
        headers={"User-Agent": _user_agent()},
        timeout=15,
    )
    if resp.status_code != 200:
        raise OAuthError(f"reddit token endpoint returned {resp.status_code}: {resp.text[:300]}")
    payload = resp.json()
    if "error" in payload:
        raise OAuthError(f"reddit token error: {payload.get('error')}")
    return payload


def _fetch_identity(access_token: str) -> dict:
    resp = requests.get(
        "https://oauth.reddit.com/api/v1/me",
        headers={
            "Authorization": f"bearer {access_token}",
            "User-Agent": _user_agent(),
        },
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    return resp.json() or {}


def exchange_code(code: str) -> dict:
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri("reddit"),
        }
    )
    access_token = payload.get("access_token", "")
    identity = _fetch_identity(access_token) if access_token else {}
    return {
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "bearer"),
        "scope": payload.get("scope", ""),
        "expires_at": seconds_from_now(payload.get("expires_in", 3600)),
        "account_handle": identity.get("name", ""),
        "account_id": identity.get("id", ""),
    }


def refresh(token: dict) -> dict:
    rt = token.get("refresh_token", "")
    if not rt:
        raise OAuthError("reddit: no refresh_token stored; user must reconnect")
    payload = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    updated = dict(token)
    updated["access_token"] = payload.get("access_token", "")
    updated["expires_at"] = seconds_from_now(payload.get("expires_in", 3600))
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    return updated
