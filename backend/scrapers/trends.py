import json
import time
import xml.etree.ElementTree as ET
import httpx
from typing import Optional

_cache: dict = {}
CACHE_TTL = 3600  # 1 hour

_REGION_TO_PN = {
    "SA": "saudi_arabia",
    "AE": "united_arab_emirates",
    "EG": "egypt",
    "US": "united_states",
    "WW": "p1",
}

_TIMEFRAME_MAP = {
    "7d": "now 7-d",
    "30d": "today 1-m",
    "90d": "today 3-m",
    "12mo": "today 12-m",
}


def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


def _cache_age_seconds(key: str) -> Optional[float]:
    entry = _cache.get(key)
    if entry:
        return time.time() - entry["ts"]
    return None


def fetch_google_trending(region: str) -> dict:
    """Fetch today's trending searches via Google Trends RSS feed."""
    cache_key = f"google_trending_{region}"
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True, "cache_age_seconds": _cache_age_seconds(cache_key)}

    geo = "" if region == "WW" else region
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        url = "https://trends.google.com/trending/rss"
        params = {"geo": geo} if geo else {}
        with httpx.Client(timeout=20, headers=headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        keywords = []
        for item in root.findall(".//item"):
            title = item.find("title")
            if title is not None and title.text:
                keywords.append(title.text.strip())
    except Exception as e:
        raise RuntimeError(str(e))

    result = {"region": region, "keywords": keywords}
    _cache_set(cache_key, result)
    return {**result, "cached": False, "cache_age_seconds": None}


def fetch_keyword_interest(keywords: list, region: str, timeframe: str) -> dict:
    """Fetch interest over time + related topics for keywords. Sync — run via asyncio.to_thread."""
    cache_key = f"kw_interest_{'_'.join(sorted(keywords))}_{region}_{timeframe}"
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True, "cache_age_seconds": _cache_age_seconds(cache_key)}

    try:
        from pytrends_modern import TrendReq
        geo = "" if region == "WW" else region
        tf = _TIMEFRAME_MAP.get(timeframe, "today 1-m")
        pytrends = TrendReq(hl="en-US", tz=180, timeout=(10, 30))
        pytrends.build_payload(keywords, geo=geo, timeframe=tf)

        interest_over_time = []
        df = pytrends.interest_over_time()
        if not df.empty:
            df = df.drop(columns=["isPartial"], errors="ignore")
            # Resample to daily so 7d (hourly) and 30d/90d (daily) all produce daily points
            df = df.resample("D").mean().round().dropna(how="all")
            df.index = df.index.strftime("%Y-%m-%d")
            df.index.name = "date"
            interest_over_time = df.reset_index().to_dict("records")

        related_topics = {}
        try:
            rt = pytrends.related_topics()
            for kw in keywords:
                top_df = rt.get(kw, {}).get("top")
                if top_df is not None and not top_df.empty and "topic_title" in top_df.columns:
                    related_topics[kw] = top_df["topic_title"].head(5).tolist()
                else:
                    related_topics[kw] = []
        except Exception:
            related_topics = {kw: [] for kw in keywords}

    except Exception as e:
        raise RuntimeError(str(e))

    result = {
        "keywords": keywords,
        "region": region,
        "timeframe": timeframe,
        "interest_over_time": interest_over_time,
        "related_topics": related_topics,
    }
    _cache_set(cache_key, result)
    return {**result, "cached": False, "cache_age_seconds": None}


async def fetch_youtube_trending(
    api_key: str,
    region: str,
    category_id: str,
    max_results: int,
) -> dict:
    """Fetch trending YouTube videos for a region. Async."""
    cache_key = f"yt_trending_{region}_{category_id}_{max_results}"
    cached = _cache_get(cache_key)
    if cached:
        return {**cached, "cached": True, "cache_age_seconds": _cache_age_seconds(cache_key)}

    _REGION_LANG = {"AE": "ar", "SA": "ar", "EG": "ar", "US": "en", "WW": "en"}
    hl = _REGION_LANG.get(region, "ar")
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region if region != "WW" else "US",
        "hl": hl,
        "maxResults": max_results,
        "key": api_key,
    }
    if category_id:
        params["videoCategoryId"] = category_id

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos", params=params
        )
        resp.raise_for_status()
        data = resp.json()

    videos = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        thumb = (
            thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
            or ""
        )
        videos.append({
            "id": item.get("id", ""),
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "thumbnail": thumb,
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "published_at": snippet.get("publishedAt", ""),
            "url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
        })

    result = {"region": region, "videos": videos}
    _cache_set(cache_key, result)
    return {**result, "cached": False, "cache_age_seconds": None}
