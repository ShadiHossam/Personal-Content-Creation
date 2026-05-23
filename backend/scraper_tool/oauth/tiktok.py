"""TikTok Login Kit + Display API OAuth.

Register at https://developers.tiktok.com/ and add Login Kit + Display API
products. Redirect URI must be HTTPS (or ``http://localhost`` for dev).

Env vars required:
    TIKTOK_OAUTH_CLIENT_KEY     (TikTok calls this "client key", not "client id")
    TIKTOK_OAUTH_CLIENT_SECRET
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests

from backend.scraper_tool.oauth.base import OAuthError, redirect_uri, require_credential, seconds_from_now

META = {
    "id": "tiktok",
    "name": "TikTok",
    "scopes": ["user.info.basic", "user.info.profile", "user.info.stats", "video.list"],
    "docs_url": "https://developers.tiktok.com/doc/login-kit-web",
    "setup_url": "https://developers.tiktok.com/",
}

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def authorize_url(state: str) -> str:
    client_key = require_credential("tiktok", "client_key", "TIKTOK_OAUTH_CLIENT_KEY")
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": ",".join(META["scopes"]),
        "redirect_uri": redirect_uri("tiktok"),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    data = dict(data)
    data["client_key"] = require_credential("tiktok", "client_key", "TIKTOK_OAUTH_CLIENT_KEY")
    data["client_secret"] = require_credential("tiktok", "client_secret", "TIKTOK_OAUTH_CLIENT_SECRET")
    resp = requests.post(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise OAuthError(f"tiktok token endpoint {resp.status_code}: {resp.text[:300]}")
    payload = resp.json() or {}
    if payload.get("error"):
        raise OAuthError(f"tiktok token error: {payload.get('error')} {payload.get('error_description', '')}")
    return payload


def _fetch_identity(access_token: str) -> dict:
    resp = requests.get(
        "https://open.tiktokapis.com/v2/user/info/",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "open_id,union_id,avatar_url,display_name,username"},
        timeout=15,
    )
    if resp.status_code != 200:
        return {}
    return (resp.json() or {}).get("data", {}).get("user", {}) or {}


def exchange_code(code: str) -> dict:
    payload = _token_request(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri("tiktok"),
        }
    )
    access = payload.get("access_token", "")
    identity = _fetch_identity(access) if access else {}
    return {
        "access_token": access,
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", ""),
        "expires_at": seconds_from_now(payload.get("expires_in", 3600)),
        "refresh_expires_at": seconds_from_now(payload.get("refresh_expires_in", 30 * 86400)),
        "account_handle": identity.get("username") or identity.get("display_name") or "",
        "account_id": identity.get("open_id", "") or identity.get("union_id", ""),
    }


def refresh(token: dict) -> dict:
    rt = token.get("refresh_token", "")
    if not rt:
        raise OAuthError("tiktok: no refresh_token stored; user must reconnect")
    payload = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    updated = dict(token)
    updated["access_token"] = payload.get("access_token", "")
    updated["expires_at"] = seconds_from_now(payload.get("expires_in", 3600))
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    if payload.get("refresh_expires_in"):
        updated["refresh_expires_at"] = seconds_from_now(payload["refresh_expires_in"])
    return updated
