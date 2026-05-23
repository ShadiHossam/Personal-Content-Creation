"""LinkedIn client.

Default scopes (openid profile email) give basic profile access only. Post
and company-page reads require Marketing Developer Platform approval — those
branches return an empty list rather than failing, so the UI stays usable.
"""

from __future__ import annotations

import requests

from backend.scraper_tool.schema import make_record


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def fetch_profile(access_token: str) -> list[dict]:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers=_headers(access_token),
        timeout=15,
    )
    if resp.status_code != 200:
        # Fall back to /v2/me for apps without OpenID scope.
        resp = requests.get(
            "https://api.linkedin.com/v2/me",
            headers=_headers(access_token),
            timeout=15,
        )
        if resp.status_code != 200:
            return []
    data = resp.json() or {}
    name = (
        data.get("name")
        or (data.get("given_name", "") + " " + data.get("family_name", "")).strip()
        or data.get("localizedFirstName", "")
    )
    ident = data.get("sub") or data.get("id", "")
    return [
        make_record(
            "linkedin",
            "profile",
            account_handle=name,
            account_id=str(ident),
            id=str(ident),
            url=f"https://www.linkedin.com/in/{ident}" if ident else "",
            text=data.get("email", ""),
            media=[data.get("picture", "")],
            metrics={
                "locale": data.get("locale", ""),
                "email_verified": bool(data.get("email_verified")),
            },
            raw=data,
        )
    ]


def fetch_posts(access_token: str, owner_id: str, max_items: int = 25) -> list[dict]:
    """Best-effort: requires Marketing Developer Platform approval + the
    ``r_member_social`` scope. Without approval LinkedIn returns 403 and we
    return an empty list rather than raising."""
    if not owner_id:
        return []
    resp = requests.get(
        "https://api.linkedin.com/v2/shares",
        headers=_headers(access_token),
        params={
            "q": "owners",
            "owners": f"urn:li:person:{owner_id}",
            "count": min(50, max_items),
        },
        timeout=20,
    )
    if resp.status_code != 200:
        return []
    items = (resp.json() or {}).get("elements") or []
    out: list[dict] = []
    for s in items[:max_items]:
        text = ((s.get("text") or {}).get("text")) or ""
        out.append(
            make_record(
                "linkedin",
                "post",
                account_handle="",
                account_id=str(owner_id),
                id=s.get("activity", "") or s.get("id", ""),
                url=f"https://www.linkedin.com/feed/update/{s.get('activity', '')}" if s.get("activity") else "",
                created_at=str(s.get("created", {}).get("time", "")),
                text=text,
                metrics={},
                raw=s,
            )
        )
    return out
