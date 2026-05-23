"""
Apify scraper for LinkedIn and Twitter.
Actor IDs and options are read from Settings and can be overridden per-creator.
"""
import httpx
import asyncio
from datetime import datetime, timezone
from typing import Optional


APIFY_BASE = "https://api.apify.com/v2"

# Defaults — user can override these in Settings
DEFAULT_LINKEDIN_ACTOR = "bebity/linkedin-profile-scraper"
DEFAULT_TWITTER_ACTOR = "apidojo/tweet-scraper"
DEFAULT_MAX_POSTS = 20


async def run_actor(api_key: str, actor_id: str, run_input: dict, timeout: int = 180) -> list[dict]:
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        actor_slug = actor_id.replace("/", "~")
        r = await client.post(
            f"{APIFY_BASE}/acts/{actor_slug}/runs",
            json=run_input,
            headers=headers,
        )
        r.raise_for_status()
        run_id = r.json()["data"]["id"]

        for _ in range(60):
            await asyncio.sleep(3)
            status_r = await client.get(f"{APIFY_BASE}/actor-runs/{run_id}", headers=headers)
            status = status_r.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED"):
                break

        if status != "SUCCEEDED":
            raise RuntimeError(f"Apify actor run ended with status: {status}")

        dataset_id = status_r.json()["data"]["defaultDatasetId"]
        data_r = await client.get(
            f"{APIFY_BASE}/datasets/{dataset_id}/items",
            headers=headers,
            params={"format": "json"},
        )
        return data_r.json()


async def fetch_linkedin_apify(
    profile_url: str,
    api_key: str,
    max_posts: int = DEFAULT_MAX_POSTS,
    actor_id: str = DEFAULT_LINKEDIN_ACTOR,
    use_proxy: bool = False,
) -> list[dict]:
    run_input: dict = {
        "profileUrls": [profile_url],
        "maxPosts": max_posts,
    }
    if use_proxy:
        run_input["proxyConfiguration"] = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}

    raw = await run_actor(api_key=api_key, actor_id=actor_id, run_input=run_input)
    results = []
    for item in raw:
        for post in item.get("posts", [])[:max_posts]:
            pub = post.get("postedAt")
            pub_date = None
            if pub:
                try:
                    pub_date = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except Exception:
                    pass
            results.append({
                "platform": "linkedin",
                "title": None,
                "body": post.get("text", "")[:2000],
                "url": post.get("url", ""),
                "published_at": pub_date,
                "format": "text",
                "likes": post.get("numLikes", 0),
                "comments_count": post.get("numComments", 0),
                "shares": post.get("numShares", 0),
                "image_url": (
                    post.get("imgUrl") or post.get("imageUrl") or
                    ((post.get("images") or [{}])[0].get("url") if post.get("images") else None)
                ),
            })
    return results


async def fetch_twitter_apify(
    handle: str,
    api_key: str,
    max_tweets: int = DEFAULT_MAX_POSTS,
    actor_id: str = DEFAULT_TWITTER_ACTOR,
    include_replies: bool = False,
    include_retweets: bool = False,
    use_proxy: bool = False,
) -> list[dict]:
    handle = handle.lstrip("@")
    # Build search query — "from:handle" gets the user's own tweets
    search = f"from:{handle}"
    if not include_replies:
        search += " -filter:replies"
    if not include_retweets:
        search += " -filter:retweets"

    run_input: dict = {
        "searchTerms": [search],
        "maxItems": max_tweets,
        "sort": "Latest",
    }
    if use_proxy:
        run_input["proxyConfiguration"] = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}

    raw = await run_actor(api_key=api_key, actor_id=actor_id, run_input=run_input)
    results = []
    for item in raw[:max_tweets]:
        # Skip demo placeholders
        if item.get("demo"):
            continue
        created = item.get("createdAt")
        pub_date = None
        if created:
            try:
                pub_date = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                pass
        # tweet-scraper puts the URL in "url" or builds it from author + id
        url = item.get("url") or item.get("tweetUrl") or ""
        if not url:
            author = (item.get("author") or {}).get("userName", handle)
            tweet_id = item.get("id", "")
            if tweet_id:
                url = f"https://x.com/{author}/status/{tweet_id}"
        results.append({
            "platform": "twitter",
            "title": None,
            "body": (item.get("text") or item.get("full_text") or "")[:1000],
            "url": url,
            "published_at": pub_date,
            "format": "text",
            "likes": item.get("likeCount", 0),
            "comments_count": item.get("replyCount", 0),
            "shares": item.get("retweetCount", 0),
            "image_url": (
                ((item.get("media") or [{}])[0].get("url") if item.get("media") else None) or
                ((item.get("photos") or [{}])[0].get("url") if item.get("photos") else None)
            ),
        })
    return results
