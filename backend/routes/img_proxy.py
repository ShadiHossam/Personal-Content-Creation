"""Image proxy for CDNs that send Cross-Origin-Resource-Policy: same-origin.

Instagram and Facebook CDNs (*.fbcdn.net, *.cdninstagram.com) set CORP headers
that make modern browsers refuse to use the image when embedded from a
different origin. We refetch the image server-side (where CORP doesn't apply)
and serve it from our own origin so the browser will display it.

Only a small allowlist of hosts is proxied to avoid turning this into an
open SSRF gateway.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api", tags=["img-proxy"])


_ALLOWED_HOST_SUFFIXES = (
    ".fbcdn.net",
    ".cdninstagram.com",
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".twimg.com",
)

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def _host_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)


@router.get("/img-proxy")
async def img_proxy(url: str = Query(..., description="Full https URL to proxy")):
    # Redirects are followed manually (not via httpx's follow_redirects) so every
    # hop — not just the initial URL — is checked against the host allowlist.
    # Otherwise an allow-listed CDN could redirect the request to an arbitrary
    # (including internal/private) host and turn this into an open SSRF gateway.
    max_redirects = 5
    current_url = url

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            for _ in range(max_redirects + 1):
                parsed = urlparse(current_url)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise HTTPException(400, "https url required")
                if not _host_allowed(parsed.netloc):
                    raise HTTPException(403, f"host not allowed: {parsed.netloc}")

                r = await client.get(
                    current_url, headers={"User-Agent": _BROWSER_UA, "Accept": "image/*,*/*"}
                )
                if r.status_code in (301, 302, 303, 307, 308):
                    location = r.headers.get("location")
                    if not location:
                        raise HTTPException(502, "redirect with no location")
                    current_url = urljoin(current_url, location)
                    continue
                break
            else:
                raise HTTPException(502, "too many redirects")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"upstream fetch failed: {type(e).__name__}")

    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"upstream {r.status_code}")

    content_type = r.headers.get("content-type", "image/jpeg")
    return Response(
        content=r.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
