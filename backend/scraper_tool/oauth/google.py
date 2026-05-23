"""Google OAuth2 for YouTube Data API v3 + YouTube Analytics API.

Register an OAuth client at https://console.cloud.google.com/apis/credentials
(type: "Web application"). Enable *YouTube Data API v3* and *YouTube Analytics
API* on the same project. Add redirect URI
``<host>/api/scraper/callback/youtube``.

Env vars required:
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests

from backend.scraper_tool.oauth.base import OAuthError, redirect_uri, require_credential, seconds_from_now

META = {
    "id": "youtube",
    "name": "YouTube",
    "scopes": [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
    "docs_url": "https://developers.google.com/youtube/v3/getting-started",
    "setup_url": "https://console.cloud.google.com/apis/credentials",
}

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def authorize_url(state: str) -> str:
    client_id = require_credential("youtube", "client_id", "GOOGLE_OAUTH_CLIENT_ID")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri("youtube"),
        "response_type": "code",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "scope": " ".join(META["scopes"]),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    data = dict(data)
    data["client_id"] = require_credential("youtube", "client_id", "GOOGLE_OAUTH_CLIENT_ID")
    data["client_secret"] = require_credential("youtube", "client_secret", "GOOGLE_OAUTH_CLIENT_SECRET")
    resp = requests.post(TOKEN_URL, data=data, timeout=15)
    if resp.status_code != 200:
        raise OAuthError(f"google token endpoint {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _fetch_channel(access_token: str) -> dict:
    resp = requests.get(
        "https://youtube.googleapis.com/youtube/v3/channels",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "snippet,statistics", "mine": "true"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    items = (resp.json() or {}).get("items") or []
    return items[0] if items else {}


def exchange_code(code: str) -> dict:
    payload = _token_request(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri("youtube"),
        }
    )
    access = payload.get("access_token", "")
    channel = _fetch_channel(access) if access else {}
    snip = channel.get("snippet") or {}
    return {
        "access_token": access,
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", ""),
        "expires_at": seconds_from_now(payload.get("expires_in", 3600)),
        "account_handle": snip.get("customUrl") or snip.get("title") or "",
        "account_id": channel.get("id", ""),
    }


def refresh(token: dict) -> dict:
    rt = token.get("refresh_token", "")
    if not rt:
        raise OAuthError("youtube: no refresh_token stored; user must reconnect")
    payload = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    updated = dict(token)
    updated["access_token"] = payload.get("access_token", "")
    updated["expires_at"] = seconds_from_now(payload.get("expires_in", 3600))
    # Google may rotate the refresh_token; preserve it if it did not.
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    return updated
