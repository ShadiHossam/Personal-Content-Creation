"""
Twitter/X scraping via Playwright headless browser.
Does not require any API key or paid subscription.
"""
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional


async def fetch_twitter_playwright(
    handle: str,
    max_tweets: int = 20,
    include_replies: bool = False,
    include_retweets: bool = False,
    published_after: Optional[datetime] = None,
    auth_token: Optional[str] = None,
    ct0: Optional[str] = None,
) -> list[dict]:
    from playwright.async_api import async_playwright

    handle = handle.lstrip("@")
    # Go directly to the profile page — X shows posts newest-first here
    url = f"https://x.com/{handle}"
    results = []
    seen_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        # Inject session cookies so X shows chronological profile posts (not algorithmic feed)
        if auth_token and ct0:
            await context.add_cookies([
                {"name": "auth_token", "value": auth_token, "domain": ".x.com", "path": "/", "secure": True, "httpOnly": True},
                {"name": "ct0", "value": ct0, "domain": ".x.com", "path": "/", "secure": True},
            ])

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # If redirected to login page, bail early
            if "login" in page.url or "signin" in page.url:
                await browser.close()
                raise RuntimeError("X.com required login — profile may be private or restricted")

            await page.wait_for_selector('[data-testid="tweet"]', timeout=20000)

            # Scroll repeatedly to load more tweets
            scroll_rounds = max(4, max_tweets // 4)
            for _ in range(scroll_rounds):
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(1.2)

            tweet_els = await page.query_selector_all('[data-testid="tweet"]')

            for tweet_el in tweet_els:
                if len(results) >= max_tweets:
                    break
                try:
                    # Skip retweets
                    social_ctx = await tweet_el.query_selector('[data-testid="socialContext"]')
                    if social_ctx and not include_retweets:
                        ctx_text = await social_ctx.inner_text()
                        if "repost" in ctx_text.lower() or "retweet" in ctx_text.lower():
                            continue

                    text_el = await tweet_el.query_selector('[data-testid="tweetText"]')
                    body = (await text_el.inner_text() if text_el else "").strip()
                    if not body:
                        continue

                    # Skip replies
                    if body.startswith("@") and not include_replies:
                        continue

                    # Date + URL from timestamp anchor
                    time_el = await tweet_el.query_selector("time")
                    tweet_url = ""
                    pub_date = None
                    if time_el:
                        dt_str = await time_el.get_attribute("datetime")
                        if dt_str:
                            try:
                                pub_date = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            except Exception:
                                pass
                        link_el = await time_el.evaluate_handle("el => el.closest('a')")
                        href = await link_el.get_attribute("href") if link_el else None
                        if href:
                            tweet_url = f"https://x.com{href}" if href.startswith("/") else href

                    if not tweet_url or tweet_url in seen_urls:
                        continue
                    seen_urls.add(tweet_url)

                    # Skip if older than published_after
                    if published_after and pub_date and pub_date <= published_after:
                        continue

                    likes = _parse_stat(await _get_stat(tweet_el, "like"))
                    replies_count = _parse_stat(await _get_stat(tweet_el, "reply"))
                    retweets_count = _parse_stat(await _get_stat(tweet_el, "retweet"))

                    results.append({
                        "platform": "twitter",
                        "title": None,
                        "body": body[:1000],
                        "url": tweet_url,
                        "published_at": pub_date,
                        "format": "text",
                        "likes": likes,
                        "comments_count": replies_count,
                        "shares": retweets_count,
                    })
                except Exception:
                    continue

        except Exception as e:
            await browser.close()
            raise RuntimeError(f"Twitter scraping failed: {e}")

        await browser.close()

    return results


async def _get_stat(tweet_el, stat_name: str) -> str:
    try:
        el = await tweet_el.query_selector(f'[data-testid="{stat_name}"]')
        if el:
            return await el.inner_text()
    except Exception:
        pass
    return "0"


def _parse_stat(text: str) -> int:
    text = text.strip().replace(",", "")
    if not text or text == "0":
        return 0
    try:
        if text.endswith("K"):
            return int(float(text[:-1]) * 1000)
        if text.endswith("M"):
            return int(float(text[:-1]) * 1_000_000)
        return int(text)
    except Exception:
        return 0
