"""LinkedIn OAuth (OpenID Connect + optional Marketing Developer Platform scopes).

Register at https://www.linkedin.com/developers/apps. Add products: *Sign In
with LinkedIn using OpenID Connect* (works immediately) and — if you need
post/page reads — *Marketing Developer Platform* (requires approval).

Env vars required:
    LINKEDIN_OAUTH_CLIENT_ID
    LINKEDIN_OAUTH_CLIENT_SECRET
    LINKEDIN_OAUTH_SCOPES   (optional; space-separated; defaults to
                              "openid profile email")
"""

from __future__ import annotations

import os
from urllib.parse import urlencode

import requests

from backend.scraper_tool.oauth.base import OAuthError, redirect_uri, require_credential, seconds_from_now

_DEFAULT_SCOPES = "openid profile email"

META = {
    "id": "linkedin",
    "name": "LinkedIn",
    "scopes": os.environ.get("LINKEDIN_OAUTH_SCOPES", _DEFAULT_SCOPES).split(),
    "docs_url": "https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow",
    "setup_url": "https://www.linkedin.com/developers/apps",
}

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


def _scopes() -> str:
    return os.environ.get("LINKEDIN_OAUTH_SCOPES", _DEFAULT_SCOPES)


def authorize_url(state: str) -> str:
    client_id = require_credential("linkedin", "client_id", "LINKEDIN_OAUTH_CLIENT_ID")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri("linkedin"),
        "state": state,
        "scope": _scopes(),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict) -> dict:
    data = dict(data)
    data["client_id"] = require_credential("linkedin", "client_id", "LINKEDIN_OAUTH_CLIENT_ID")
    data["client_secret"] = require_credential("linkedin", "client_secret", "LINKEDIN_OAUTH_CLIENT_SECRET")
    resp = requests.post(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise OAuthError(f"linkedin token endpoint {resp.status_code}: {resp.text[:300]}")
    return resp.json() or {}


def _fetch_identity(access_token: str) -> dict:
    """Use the OpenID userinfo endpoint — works with the default scope set."""
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json() or {}
    # Fallback to legacy /v2/me if openid scope wasn't granted.
    resp2 = requests.get(
        "https://api.linkedin.com/v2/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    return resp2.json() if resp2.status_code == 200 else {}


def exchange_code(code: str) -> dict:
    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri("linkedin"),
        }
    )
    access = payload.get("access_token", "")
    identity = _fetch_identity(access) if access else {}
    # OIDC userinfo shape vs /v2/me shape — accommodate both.
    handle = (
        identity.get("name")
        or (identity.get("given_name", "") + " " + identity.get("family_name", "")).strip()
        or identity.get("localizedFirstName", "")
    )
    return {
        "access_token": access,
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", _scopes()),
        "expires_at": seconds_from_now(payload.get("expires_in", 60 * 86400)),
        "account_handle": handle,
        "account_id": identity.get("sub") or identity.get("id", ""),
    }


def refresh(token: dict) -> dict:
    rt = token.get("refresh_token", "")
    if not rt:
        # LinkedIn grants refresh_tokens only to approved Marketing Developer
        # Platform apps — most dev apps won't have one.
        raise OAuthError(
            "linkedin: no refresh_token available (requires Marketing Developer "
            "Platform approval). User must reconnect."
        )
    payload = _token_request({"grant_type": "refresh_token", "refresh_token": rt})
    updated = dict(token)
    updated["access_token"] = payload.get("access_token", "")
    updated["expires_at"] = seconds_from_now(payload.get("expires_in", 60 * 86400))
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    return updated
