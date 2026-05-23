"""Apify actor registry + per-platform input/result mappers.

Each platform has:
  - a list of built-in actor IDs surfaced as dropdown choices in the admin UI
    (extensible: admins can add custom actor IDs through the same UI),
  - a `build_input_*` that turns a fetch's params into the actor's input JSON,
  - a `map_result_*` that turns the actor's dataset items into the canonical
    response shape the existing legacy path emits, so the frontend keeps
    rendering the same fields without changes.

Mappers are deliberately tolerant of field-name differences between actors
(e.g. `fullName` vs `full_name`, `playsCount` vs `views`) — Apify community
actors don't share a schema, so the mapper inspects several likely keys.
"""

from __future__ import annotations

from typing import Any

# ── Built-in actor registry ─────────────────────────────────────────────
# Each entry: {"id", "label", "default": bool}. The `default` flag picks the
# initial selection if the admin hasn't chosen one yet.

BUILTIN_ACTORS: dict[str, list[dict[str, Any]]] = {
    "instagram": [
        {"id": "apify/instagram-scraper", "label": "Apify · Instagram Scraper", "default": True},
        {"id": "apify/instagram-profile-scraper", "label": "Apify · Instagram Profile"},
        {"id": "apify/instagram-post-scraper", "label": "Apify · Instagram Posts"},
        {"id": "apify/instagram-reel-scraper", "label": "Apify · Instagram Reels"},
    ],
    "tiktok": [
        {"id": "clockworks/tiktok-scraper", "label": "Clockworks · TikTok Scraper", "default": True},
        {"id": "clockworks/free-tiktok-scraper", "label": "Clockworks · TikTok (free tier)"},
        {"id": "clockworks/tiktok-profile-scraper", "label": "Clockworks · TikTok Profile"},
        {"id": "novi/tiktok-scraper", "label": "Novi · TikTok Scraper"},
    ],
    "linkedin": [
        {"id": "bebity/linkedin-premium-actor", "label": "Bebity · LinkedIn Premium", "default": True},
        {"id": "harvestapi/linkedin-company", "label": "HarvestAPI · LinkedIn Company"},
        {"id": "curious_coder/linkedin-post-search-scraper", "label": "LinkedIn Post Search"},
        {"id": "supreme_coder/linkedin-profile-scraper", "label": "LinkedIn Profile Scraper"},
    ],
    "fbads": [
        {"id": "apify/facebook-ads-library-scraper", "label": "Apify · Facebook Ads Library", "default": True},
        {"id": "curious_coder/facebook-ads-library-scraper", "label": "Facebook Ads Library (alt)"},
    ],
    "facebook": [
        {"id": "apify/facebook-pages-scraper", "label": "Apify · Facebook Pages", "default": True},
        {"id": "apify/facebook-posts-scraper", "label": "Apify · Facebook Posts"},
        {"id": "axesso_data/facebook-posts-scraper", "label": "Axesso · Facebook Posts"},
    ],
    "twitter": [
        {"id": "apidojo/tweet-scraper", "label": "ApiDojo · Tweet Scraper", "default": True},
        {"id": "apify/tweet-scraper", "label": "Apify · Tweet Scraper"},
        {"id": "apidojo/twitter-scraper-lite", "label": "ApiDojo · Twitter Scraper Lite"},
    ],
}


def default_actor_for(platform: str) -> str:
    for entry in BUILTIN_ACTORS.get(platform, []):
        if entry.get("default"):
            return str(entry.get("id") or "")
    items = BUILTIN_ACTORS.get(platform) or []
    return str(items[0]["id"]) if items else ""


# ── Small helpers used by the mappers ───────────────────────────────────


def _first(d: dict, *keys: str, default: Any = "") -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _str(value: Any) -> str:
    return "" if value is None else str(value)


# ── Instagram ───────────────────────────────────────────────────────────


def build_input_instagram(username: str, max_posts: int = 50) -> dict:
    return {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "details",
        "resultsLimit": max_posts,
        "addParentData": False,
    }


def map_result_instagram(items: list[dict], username: str) -> dict:
    """Pick the profile entry, then collect its posts. Apify IG actors emit
    one item per profile (with nested posts) and/or one item per post — the
    mapper handles both shapes."""
    profile_item: dict = {}
    posts_items: list[dict] = []
    for it in items:
        t = (it.get("type") or it.get("resultType") or "").lower()
        if t in ("user", "profile") or it.get("biography") is not None or it.get("followersCount") is not None:
            profile_item = it
        else:
            posts_items.append(it)

    if not profile_item and items:
        profile_item = items[0]

    nested_posts = profile_item.get("latestPosts") or profile_item.get("posts") or []
    if nested_posts and not posts_items:
        posts_items = list(nested_posts)

    profile = {
        "username": _str(_first(profile_item, "username", "userName", default=username)),
        "full_name": _str(_first(profile_item, "fullName", "full_name", "displayName")),
        "biography": _str(_first(profile_item, "biography", "bio")),
        "profile_pic": _str(_first(profile_item, "profilePicUrlHD", "profilePicUrl", "profile_pic_url")),
        "followers": _int(_first(profile_item, "followersCount", "followers", "followers_count", default=0)),
        "following": _int(_first(profile_item, "followsCount", "followingCount", "following", default=0)),
        "posts_count": _int(_first(profile_item, "postsCount", "mediaCount", "posts_count", default=0)),
        "is_verified": bool(profile_item.get("verified") or profile_item.get("isVerified")),
        "is_business": bool(profile_item.get("isBusinessAccount") or profile_item.get("is_business")),
        "category": _str(_first(profile_item, "businessCategoryName", "category", "categoryName")),
    }

    posts = []
    for p in posts_items:
        posts.append({
            "id": _str(_first(p, "shortCode", "shortcode", "id")),
            "caption": _str(_first(p, "caption", "text"))[:200],
            "likes": _int(_first(p, "likesCount", "likes", default=0)),
            "comments": _int(_first(p, "commentsCount", "comments", default=0)),
            "thumbnail": _str(_first(p, "displayUrl", "thumbnailUrl", "imageUrl", "url")),
            "timestamp": _str(_first(p, "timestamp", "takenAtTimestamp", default="")),
            "is_video": bool(p.get("isVideo") or p.get("videoUrl") or p.get("type") == "Video"),
            "video_views": _int(_first(p, "videoViewCount", "videoPlayCount", default=0)),
            "permalink": _str(_first(p, "url", "permalink")),
        })

    return {
        "profile": profile,
        "posts": posts,
        "engagement_rate": 0,
        "has_more": False,
        "source": "apify",
    }


# ── TikTok ──────────────────────────────────────────────────────────────


def build_input_tiktok(username: str, max_videos: int = 30) -> dict:
    return {
        "profiles": [username],
        "resultsPerPage": max_videos,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
    }


def map_result_tiktok(items: list[dict], username: str) -> tuple[dict, list[dict]]:
    profile_item: dict = {}
    video_items: list[dict] = []
    for it in items:
        author = it.get("authorMeta") or it.get("author") or {}
        if isinstance(author, dict) and author.get("name"):
            video_items.append(it)
            if not profile_item:
                profile_item = author
        elif it.get("nickName") or it.get("nickname") or it.get("uniqueId"):
            profile_item = it
        else:
            video_items.append(it)

    if not profile_item and items:
        profile_item = items[0]

    profile = {
        "username": _str(_first(profile_item, "name", "uniqueId", "username", default=username)),
        "nickname": _str(_first(profile_item, "nickName", "nickname", "displayName")),
        "display_name": _str(_first(profile_item, "nickName", "nickname", "displayName")),
        "bio": _str(_first(profile_item, "signature", "bio", "bioDescription")),
        "avatar": _str(_first(profile_item, "avatar", "avatarLarger", "avatarMedium")),
        "followers": _int(_first(profile_item, "fans", "followerCount", "followers", default=0)),
        "follower_count": _int(_first(profile_item, "fans", "followerCount", "followers", default=0)),
        "following": _int(_first(profile_item, "following", "followingCount", default=0)),
        "following_count": _int(_first(profile_item, "following", "followingCount", default=0)),
        "likes": _int(_first(profile_item, "heart", "heartCount", "likesCount", default=0)),
        "likes_count": _int(_first(profile_item, "heart", "heartCount", "likesCount", default=0)),
        "videos": _int(_first(profile_item, "video", "videoCount", default=0)),
        "video_count": _int(_first(profile_item, "video", "videoCount", default=0)),
        "verified": bool(profile_item.get("verified") or profile_item.get("isVerified")),
        "is_verified": bool(profile_item.get("verified") or profile_item.get("isVerified")),
    }

    videos = []
    for v in video_items:
        videos.append({
            "id": _str(_first(v, "id", "videoId")),
            "desc": _str(_first(v, "text", "desc", "description"))[:200],
            "title": _str(_first(v, "text", "desc", "description"))[:200],
            "video_description": _str(_first(v, "text", "desc", "description"))[:200],
            "createTime": _int(_first(v, "createTime", "createTimeISO", default=0)),
            "create_time": _int(_first(v, "createTime", default=0)),
            "views": _int(_first(v, "playCount", "playsCount", "views", default=0)),
            "view_count": _int(_first(v, "playCount", "playsCount", "views", default=0)),
            "likes": _int(_first(v, "diggCount", "likesCount", "likes", default=0)),
            "like_count": _int(_first(v, "diggCount", "likesCount", default=0)),
            "comments": _int(_first(v, "commentCount", "commentsCount", default=0)),
            "comment_count": _int(_first(v, "commentCount", default=0)),
            "shares": _int(_first(v, "shareCount", "sharesCount", default=0)),
            "share_count": _int(_first(v, "shareCount", default=0)),
            "cover": _str(_first(v, "covers", "cover", "coverUrl")),
            "cover_image_url": _str(_first(v, "covers", "cover", "coverUrl")),
            "share_url": _str(_first(v, "webVideoUrl", "shareUrl", "url")),
        })
    return profile, videos


# ── LinkedIn (public company / profile pages) ───────────────────────────


def build_input_linkedin(url: str) -> dict:
    return {
        "urls": [url],
        "startUrls": [{"url": url}],
    }


def map_result_linkedin(items: list[dict], url: str) -> dict:
    if not items:
        return {"kind": "page", "name": "", "url": url, "description": "", "followers": 0}
    it = items[0]
    name = _str(_first(it, "name", "title", "fullName", "displayName"))
    description = _str(_first(it, "description", "about", "tagline"))[:600]
    followers = _int(_first(it, "followers", "followersCount", "followerCount", default=0))
    industry = _str(_first(it, "industry", "industryName"))
    employees = _int(_first(it, "employeeCount", "employees", default=0))
    headquarters = _str(_first(it, "headquarter", "headquarters", "location"))

    profile = {
        "kind": _str(_first(it, "type", "kind", default="page")),
        "name": name,
        "subtitle": industry,
        "description": description,
        "bio": description[:300],
        "image": _str(_first(it, "logoUrl", "imageUrl", "profilePictureUrl", "logo")),
        "logo": _str(_first(it, "logoUrl", "logo", "imageUrl")),
        "url": _str(_first(it, "url", "profileUrl", default=url)),
        "industry": industry,
        "headquarters": headquarters,
        "company_size": _str(_first(it, "companySize", "company_size")),
        "employees": employees,
        "founded": _str(_first(it, "founded", "foundedYear", default="")),
        "website": _str(_first(it, "website", "websiteUrl")),
        "socials": it.get("socials") or [],
        "specialties": it.get("specialties") or it.get("specialities") or [],
        "followers": followers,
        "followers_text": f"{followers:,} followers" if followers else "",
        "follower_text": f"{followers:,} followers" if followers else "",
    }
    return profile


# ── Meta Ad Library ─────────────────────────────────────────────────────


def build_input_fbads(query: str, country: str = "ALL") -> dict:
    return {
        "search": [query],
        "searchTerms": [query],
        "country": country,
        "active": "all",
        "adType": "all",
        "count": 30,
    }


def map_result_fbads(items: list[dict], query: str, country: str) -> dict:
    ads = []
    for a in items:
        snap = a.get("snapshot") or a.get("ad_snapshot") or {}
        body = _str(_first(a, "body", "ad_creative_body", default=""))
        if not body and snap:
            body = _str(((snap.get("body") or {}).get("text")) or snap.get("title"))
        images: list[str] = []
        for img in (a.get("images") or snap.get("images") or []):
            if isinstance(img, str):
                images.append(img)
            elif isinstance(img, dict):
                u = img.get("resized_image_url") or img.get("original_image_url") or img.get("url")
                if u:
                    images.append(u)
        ad_id = _str(_first(a, "adArchiveID", "ad_archive_id", "adId", "id"))
        ads.append({
            "ad_id": ad_id,
            "page_name": _str(_first(a, "pageName", "page_name", default=snap.get("page_name") or "")),
            "page_id": _str(_first(a, "pageID", "page_id", default="")),
            "page_profile_pic": _str(snap.get("page_profile_picture_url") or a.get("page_profile_picture_url") or ""),
            "start_date": _first(a, "startDate", "start_date", default=None),
            "end_date": _first(a, "endDate", "end_date", default=None),
            "is_active": bool(_first(a, "isActive", "is_active", default=False)),
            "cta": _str(snap.get("cta_text") or a.get("cta") or ""),
            "link_url": _str(snap.get("link_url") or a.get("link_url") or ""),
            "body": body[:500],
            "title": _str(snap.get("title") or a.get("title") or ""),
            "caption": _str(snap.get("caption") or a.get("caption") or ""),
            "image": images[0] if images else "",
            "images": images[:5],
            "platforms": a.get("publisherPlatform") or a.get("publisher_platform") or [],
            "impressions": a.get("impressionsWithIndex") or a.get("impressions") or {},
            "spend": a.get("spend") or {},
            "link": f"https://www.facebook.com/ads/library/?id={ad_id}" if ad_id else "",
        })
    return {
        "query": query,
        "country": country,
        "ads": ads,
        "has_more": False,
    }


# ── Facebook (public pages) ─────────────────────────────────────────────


def build_input_facebook(target: str, max_posts: int = 30) -> dict:
    url = target if target.startswith("http") else f"https://www.facebook.com/{target}"
    return {
        "startUrls": [{"url": url}],
        "resultsLimit": max_posts,
        "maxPosts": max_posts,
    }


def map_result_facebook(items: list[dict], target: str) -> dict:
    profile_item: dict = {}
    posts_items: list[dict] = []
    for it in items:
        if it.get("pageName") or it.get("page_name") or it.get("title") and it.get("likes") is not None:
            if not profile_item:
                profile_item = it
        if it.get("postId") or it.get("post_id") or it.get("text") or it.get("message"):
            posts_items.append(it)

    if not profile_item and items:
        profile_item = items[0]

    profile = {
        "name": _str(_first(profile_item, "pageName", "page_name", "title", "name")),
        "description": _str(_first(profile_item, "intro", "about", "description", "pageDescription"))[:600],
        "image": _str(_first(profile_item, "profilePictureUrl", "profile_picture_url", "image", "logo")),
        "url": _str(_first(profile_item, "pageUrl", "url", default=target if target.startswith("http") else f"https://www.facebook.com/{target}")),
        "followers": _int(_first(profile_item, "followers", "followersCount", "follower_count", default=0)),
        "likes": _int(_first(profile_item, "likes", "likesCount", "page_likes", default=0)),
        "category": _str(_first(profile_item, "category", "pageCategory")),
        "is_verified": bool(profile_item.get("verified") or profile_item.get("isVerified")),
    }

    posts = []
    for p in posts_items:
        posts.append({
            "id": _str(_first(p, "postId", "post_id", "id")),
            "text": _str(_first(p, "text", "message", "content"))[:500],
            "likes": _int(_first(p, "likes", "likesCount", "reactionCount", default=0)),
            "comments": _int(_first(p, "comments", "commentsCount", "commentCount", default=0)),
            "shares": _int(_first(p, "shares", "sharesCount", "shareCount", default=0)),
            "timestamp": _str(_first(p, "time", "timestamp", "publishedAt")),
            "permalink": _str(_first(p, "url", "postUrl", "permalink")),
            "image": _str(_first(p, "imageUrl", "image", "media")),
        })

    return {"profile": profile, "posts": posts, "source": "apify"}


# ── Twitter / X ─────────────────────────────────────────────────────────


def build_input_twitter(target: str, max_tweets: int = 30) -> dict:
    handle = target.lstrip("@")
    if target.startswith("http"):
        return {"startUrls": [target], "maxItems": max_tweets, "tweetsDesired": max_tweets}
    return {
        "twitterHandles": [handle],
        "handles": [handle],
        "searchTerms": [f"from:{handle}"],
        "maxItems": max_tweets,
        "tweetsDesired": max_tweets,
    }


def map_result_twitter(items: list[dict], target: str) -> dict:
    profile_item: dict = {}
    tweets_items: list[dict] = []
    for it in items:
        author = it.get("author") or it.get("user") or {}
        if isinstance(author, dict) and (author.get("userName") or author.get("screen_name") or author.get("name")):
            tweets_items.append(it)
            if not profile_item:
                profile_item = author
        elif it.get("userName") or it.get("screen_name"):
            if not profile_item:
                profile_item = it
        else:
            tweets_items.append(it)

    if not profile_item and items:
        profile_item = items[0]

    profile = {
        "name": _str(_first(profile_item, "name", "displayName", "fullName")),
        "username": _str(_first(profile_item, "userName", "screen_name", "username", default=target.lstrip("@"))),
        "description": _str(_first(profile_item, "description", "bio"))[:300],
        "image": _str(_first(profile_item, "profileImageUrl", "profile_image_url", "avatar")),
        "followers": _int(_first(profile_item, "followers", "followersCount", "followers_count", default=0)),
        "following": _int(_first(profile_item, "following", "followingCount", "friends_count", default=0)),
        "tweets_count": _int(_first(profile_item, "statusesCount", "tweetsCount", "statuses_count", default=0)),
        "is_verified": bool(profile_item.get("verified") or profile_item.get("isVerified")),
    }

    tweets = []
    for t in tweets_items:
        tweets.append({
            "id": _str(_first(t, "id", "tweetId", "id_str")),
            "text": _str(_first(t, "text", "fullText", "full_text"))[:500],
            "likes": _int(_first(t, "likeCount", "favoriteCount", "favorite_count", default=0)),
            "retweets": _int(_first(t, "retweetCount", "retweet_count", default=0)),
            "replies": _int(_first(t, "replyCount", "reply_count", default=0)),
            "views": _int(_first(t, "viewCount", "view_count", default=0)),
            "timestamp": _str(_first(t, "createdAt", "created_at", "date")),
            "permalink": _str(_first(t, "url", "tweetUrl", "permalink")),
        })

    return {"profile": profile, "tweets": tweets, "source": "apify"}
