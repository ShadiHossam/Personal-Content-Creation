import feedparser
from datetime import datetime, timezone
from typing import Optional
import httpx
import re


TOPIC_KEYWORDS = {
    "AI": ["ai", "artificial intelligence", "machine learning", "gpt", "llm", "chatgpt", "automation"],
    "Marketing": ["marketing", "brand", "content", "social media", "campaign", "strategy", "seo", "advertising"],
    "SME": ["sme", "small business", "startup", "entrepreneur", "founder", "small company"],
    "Branding": ["brand", "branding", "identity", "positioning", "reputation"],
    "Business": ["business", "revenue", "growth", "profit", "enterprise", "company", "corporate"],
    "Economy": ["economy", "economic", "gdp", "inflation", "market", "trade", "investment"],
    "Leadership": ["leadership", "management", "ceo", "executive", "team", "culture"],
    "MENA": ["mena", "arab", "gulf", "saudi", "uae", "egypt", "middle east"],
}


def extract_tags(text: str) -> list[str]:
    text_lower = text.lower()
    tags = []
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)
    return tags[:4]


def parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                import calendar
                ts = calendar.timegm(val)  # val is UTC struct_time; timegm preserves UTC
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass
    return None


async def detect_rss_url(site_url: str) -> Optional[str]:
    candidates = [
        site_url.rstrip("/") + "/feed",
        site_url.rstrip("/") + "/feed/",
        site_url.rstrip("/") + "/rss",
        site_url.rstrip("/") + "/rss.xml",
        site_url.rstrip("/") + "/atom.xml",
    ]
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        # Try to detect from HTML
        try:
            r = await client.get(site_url, timeout=10)
            html = r.text
            match = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']', html)
            if match:
                href = match.group(1)
                if href.startswith("http"):
                    return href
                return site_url.rstrip("/") + "/" + href.lstrip("/")
        except Exception:
            pass

        for url in candidates:
            try:
                r = await client.get(url, timeout=8)
                if r.status_code == 200 and ("rss" in r.text[:500].lower() or "feed" in r.text[:500].lower() or "<item" in r.text[:2000] or "<entry" in r.text[:2000]):
                    return url
            except Exception:
                continue
    return None


def parse_feed(rss_url: str, since: Optional[datetime] = None, until: Optional[datetime] = None) -> list[dict]:
    feed = feedparser.parse(rss_url)
    results = []

    if since and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)

    for entry in feed.entries:
        pub_date = parse_date(entry)

        if since and pub_date and pub_date < since:
            continue
        if until and pub_date and pub_date > until:
            continue

        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        body = re.sub(r"<[^>]+>", "", summary)[:1000]

        tags = extract_tags(title + " " + body)

        results.append({
            "title": title,
            "body": body,
            "url": getattr(entry, "link", ""),
            "published_at": pub_date,
            "topic_tags": tags,
        })

    return results
