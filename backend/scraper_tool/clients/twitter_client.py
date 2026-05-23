"""X / Twitter search via cookie-based auth.

Reads two cookies from the user's logged-in browser session:
  - auth_token : session token
  - ct0        : CSRF token (sent as both cookie and x-csrf-token header)

These are pasted into Settings → API Keys. Without them, this client returns
an empty list and the rest of the trend-research run continues unaffected.

Calls X's internal GraphQL SearchTimeline endpoint with a known query ID.
The query ID changes occasionally (a few times a year); when it does, the
endpoint returns 404 and the client returns []. Treat this as best-effort.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

# Public Bearer token X uses for unauthenticated web traffic. Pinned here
# because every request needs it — it's not a secret.
_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
_QUERY_ID = "nK1dw4oV3k4w5TdtcAdSww"  # SearchTimeline GraphQL query id (web client)
_URL = f"https://x.com/i/api/graphql/{_QUERY_ID}/SearchTimeline"


def _build_features() -> dict[str, bool]:
    # X requires a feature-flag bag on every request; the web client computes
    # this dynamically. Hardcoding the most-recent stable set is the standard
    # approach for cookie-auth scrapers.
    return {
        "rweb_video_screen_enabled": False,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "premium_content_api_read_enabled": False,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
        "responsive_web_grok_analyze_post_followups_enabled": True,
        "responsive_web_jetfuel_frame": False,
        "responsive_web_grok_share_attachment_enabled": True,
        "articles_preview_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "responsive_web_grok_show_grok_translated_post": False,
        "responsive_web_grok_analysis_button_from_backend": True,
        "creator_subscriptions_quote_tweet_preview_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_grok_image_annotation_enabled": True,
        "responsive_web_grok_imagine_annotation_enabled": True,
        "responsive_web_grok_community_note_auto_translation_is_enabled": False,
        "responsive_web_enhance_cards_enabled": False,
    }


def search(query: str, auth_token: str, ct0: str, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
    """Return up to `limit` X posts matching `query`, restricted to last `days`.

    Returns [] silently on any error (missing cookies, expired session, X
    changed the query id, network failure) — trend-research treats it as a
    soft per-source failure.
    """
    if not query:
        return []
    if not auth_token or not ct0:
        raise RuntimeError(
            "missing X cookies (Settings → API Keys → 'X / Twitter — auth_token' and 'ct0')"
        )

    cutoff = int(time.time() - max(1, days) * 86400)
    # `since:<unix>` operator scopes the search to recent posts.
    full_q = f"{query} since:{cutoff}"

    variables = {
        "rawQuery": full_q,
        "count": min(max(1, limit), 50),
        "querySource": "typed_query",
        "product": "Top",
    }
    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(_build_features(), separators=(",", ":")),
    }

    headers = {
        "Authorization": f"Bearer {_BEARER}",
        "x-csrf-token": ct0,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://x.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
        ),
    }
    cookies = {"auth_token": auth_token, "ct0": ct0}

    try:
        resp = requests.get(_URL, params=params, headers=headers, cookies=cookies, timeout=20)
    except requests.RequestException as exc:
        raise RuntimeError(f"network error: {exc}") from exc
    if resp.status_code == 401 or resp.status_code == 403:
        raise RuntimeError(
            f"X auth failed ({resp.status_code}) — cookies expired or wrong. "
            "Re-copy auth_token + ct0 from a fresh logged-in x.com session."
        )
    if resp.status_code == 404:
        raise RuntimeError(
            f"X SearchTimeline {resp.status_code} — likely the GraphQL query id rotated. "
            f"Update _QUERY_ID in twitter_client.py (current: {_QUERY_ID})."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"X API {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("X returned non-JSON response")

    return _extract_tweets(data, limit)


def _extract_tweets(data: dict, limit: int) -> list[dict[str, Any]]:
    """Walk the deeply-nested SearchTimeline response and pull tweet entries."""
    out: list[dict[str, Any]] = []
    try:
        instructions = (
            data["data"]["search_by_raw_query"]["search_timeline"]["timeline"]["instructions"]
        )
    except (KeyError, TypeError):
        return out

    for inst in instructions:
        if inst.get("type") != "TimelineAddEntries":
            continue
        for entry in inst.get("entries", []) or []:
            content = entry.get("content") or {}
            item_content = content.get("itemContent") or {}
            if item_content.get("itemType") != "TimelineTweet":
                continue
            tweet_result = (item_content.get("tweet_results") or {}).get("result") or {}
            # When a tweet is wrapped in TweetWithVisibilityResults, the actual
            # tweet sits under .tweet
            if tweet_result.get("__typename") == "TweetWithVisibilityResults":
                tweet_result = tweet_result.get("tweet") or {}
            legacy = tweet_result.get("legacy") or {}
            user = (
                ((tweet_result.get("core") or {}).get("user_results") or {}).get("result") or {}
            ).get("legacy") or {}

            tid = tweet_result.get("rest_id") or legacy.get("id_str") or ""
            if not tid:
                continue
            screen_name = user.get("screen_name", "")
            text = legacy.get("full_text") or ""
            out.append(
                {
                    "source": "twitter",
                    "id": tid,
                    "title": text[:140],
                    "url": f"https://x.com/{screen_name}/status/{tid}" if screen_name else f"https://x.com/i/status/{tid}",
                    "snippet": text[:400],
                    "author": screen_name,
                    "created_at": legacy.get("created_at", ""),
                    "score": int(legacy.get("favorite_count") or 0),
                    "comments": int(legacy.get("reply_count") or 0),
                    "retweets": int(legacy.get("retweet_count") or 0),
                    "views": int((tweet_result.get("views") or {}).get("count") or 0),
                    "permalink": f"https://x.com/{screen_name}/status/{tid}" if screen_name else "",
                }
            )
            if len(out) >= limit:
                return out
    return out
