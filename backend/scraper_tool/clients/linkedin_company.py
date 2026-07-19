"""
LinkedIn company + people scraper using Playwright + li_at session cookie.

Scrapes company info from the About page and paginates through the
People tab to extract employee names, titles, locations, and profile URLs.

Anti-detection mirrors extension_driver.py: disables AutomationControlled,
overrides navigator.webdriver/plugins/languages, uses a realistic user-agent.
"""
from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import quote

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_ANTI_DETECTION_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    if (!window.chrome) window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _text(el) -> str:
    try:
        return el.inner_text().strip()
    except Exception:
        return ""


def _attr(el, attr: str) -> str:
    try:
        return el.get_attribute(attr) or ""
    except Exception:
        return ""


def _first(page_or_el, selectors: list[str]):
    """Return first matching element from a list of selector fallbacks."""
    for sel in selectors:
        try:
            el = page_or_el.query_selector(sel)
            if el:
                return el
        except Exception:
            pass
    return None


def _all(page_or_el, selectors: list[str]) -> list:
    """Return all elements matched by first working selector."""
    for sel in selectors:
        try:
            els = page_or_el.query_selector_all(sel)
            if els:
                return els
        except Exception:
            pass
    return []


def _slug_from_input(target: str) -> str:
    """Convert a LinkedIn company URL or plain slug to just the slug."""
    target = target.strip().rstrip("/")
    m = re.search(r"linkedin\.com/company/([^/?#]+)", target)
    if m:
        return m.group(1)
    if target.startswith("http"):
        parts = target.rstrip("/").split("/")
        return parts[-1]
    return target


# ─── Browser setup ────────────────────────────────────────────────────────────

def _launch(li_at: str):
    from playwright.sync_api import sync_playwright  # type: ignore

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    context = browser.new_context(
        user_agent=_USER_AGENT,
        viewport={"width": 1280, "height": 900},
    )
    context.add_init_script(_ANTI_DETECTION_SCRIPT)
    context.add_cookies([{
        "name": "li_at",
        "value": li_at,
        "domain": ".linkedin.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "None",
    }])
    return pw, browser, context


def _close(pw, browser, context, page):
    for obj in (page, context, browser, pw):
        if obj:
            try:
                obj.close() if hasattr(obj, "close") else obj.stop()
            except Exception:
                pass


_SESSION_ERROR = "LinkedIn session expired or CAPTCHA triggered — paste a fresh li_at cookie"


def _warmup(page):
    """Visit the feed briefly so the session looks human before hitting company pages."""
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(random.uniform(2.0, 3.5))
        if "login" in page.url or "checkpoint" in page.url or "authwall" in page.url:
            raise RuntimeError(_SESSION_ERROR)
    except RuntimeError:
        raise
    except Exception as e:
        err = str(e).lower()
        if "too_many_redirects" in err or "redirect" in err:
            raise RuntimeError(_SESSION_ERROR)
        pass  # other warmup failures are non-fatal


def _check_blocked(page):
    if "login" in page.url or "checkpoint" in page.url or "authwall" in page.url:
        raise RuntimeError(
            "LinkedIn session expired or CAPTCHA triggered — paste a fresh li_at cookie"
        )


# ─── Company search by name ───────────────────────────────────────────────────

def _resolve_slug(page, target: str) -> str:
    """If target looks like a company name (has spaces), search LinkedIn to find the slug."""
    slug = _slug_from_input(target)
    if " " not in slug:
        return slug

    log.info("LinkedIn company scraper: searching for company '%s'", target)
    url = f"https://www.linkedin.com/search/results/companies/?keywords={quote(target)}"
    page.goto(url, wait_until="domcontentloaded", timeout=25000)
    time.sleep(random.uniform(2.0, 3.0))
    _check_blocked(page)

    link = _first(page, [
        ".entity-result__title-text a[href*='/company/']",
        ".app-aware-link[href*='/company/']",
        "a[href*='linkedin.com/company/']",
    ])
    if link:
        href = _attr(link, "href")
        found = _slug_from_input(href)
        if found:
            log.info("LinkedIn company scraper: resolved '%s' → slug '%s'", target, found)
            return found

    raise RuntimeError(f"Could not find a LinkedIn company matching '{target}'")


# ─── Company info scraper ─────────────────────────────────────────────────────

_COMPANY_NAME_SELS = [
    "h1.org-top-card-summary__title",
    "h1[class*='top-card-summary__title']",
    "[class*='top-card'] h1",
    "h1",
]
_TAGLINE_SELS = [
    ".org-top-card-summary__tagline",
    "[class*='tagline']",
]
_ABOUT_SELS = [
    ".org-about-us-organization-description__text",
    "[class*='about-us__summary']",
    ".org-about-module__description",
    "[class*='organization-description']",
]
_WEBSITE_SELS = [
    "a[data-control-name='visit_company_website']",
    ".org-about-us-company-module__website a",
    "[class*='company-module__website'] a",
    "a[class*='website']",
]
_INFO_LIST_SELS = [
    "[class*='org-top-card-summary-info-list'] li",
    ".org-top-card-summary-info-list__info-item",
    "[class*='summary-info-list'] li",
]
_FOLLOWERS_SELS = [
    "[class*='followers']",
    "[class*='follower-count']",
]


def scrape_company(target: str, li_at: str) -> dict:
    """Scrape company info from the About page."""
    if not li_at:
        raise ValueError("li_at cookie is required")

    pw = browser = context = page = None
    try:
        pw, browser, context = _launch(li_at)
        page = context.new_page()
        _warmup(page)

        slug = _resolve_slug(page, target)
        url = f"https://www.linkedin.com/company/{slug}/about/"
        log.info("LinkedIn company scraper: fetching company info at %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            if "too_many_redirects" in str(e).lower() or "redirect" in str(e).lower():
                raise RuntimeError(_SESSION_ERROR)
            raise
        time.sleep(random.uniform(2.0, 3.5))
        _check_blocked(page)

        name_el = _first(page, _COMPANY_NAME_SELS)
        name = _text(name_el) if name_el else ""

        tagline_el = _first(page, _TAGLINE_SELS)
        tagline = _text(tagline_el) if tagline_el else ""

        about_el = _first(page, _ABOUT_SELS)
        about = _text(about_el) if about_el else ""

        website_el = _first(page, _WEBSITE_SELS)
        website = _attr(website_el, "href") if website_el else ""
        if website and website.startswith("/"):
            website = ""  # relative links are not the company website

        info_items = _all(page, _INFO_LIST_SELS)
        info_texts = [_text(el) for el in info_items if _text(el)]

        industry = ""
        employee_range = ""
        hq = ""
        for txt in info_texts:
            low = txt.lower()
            if "employee" in low or "+" in txt and any(c.isdigit() for c in txt):
                employee_range = txt
            elif any(word in low for word in ("industry", "information", "technology", "services",
                                               "financial", "healthcare", "education", "retail",
                                               "software", "internet", "consulting")):
                industry = txt
            elif not hq and "," in txt and not any(c.isdigit() for c in txt.replace(",", "")):
                hq = txt

        followers_el = _first(page, _FOLLOWERS_SELS)
        followers_text = _text(followers_el) if followers_el else ""
        followers_num = re.sub(r"[^\d,KkMm]", "", followers_text).strip()

        result = {
            "name": name,
            "tagline": tagline,
            "about": about,
            "website": website,
            "industry": industry,
            "employee_range": employee_range,
            "hq": hq,
            "followers": followers_num,
            "linkedin_url": f"https://www.linkedin.com/company/{slug}/",
        }
        log.info("LinkedIn company scraper: scraped info for '%s'", name or slug)
        return result

    finally:
        _close(pw, browser, context, page)


# ─── People scraper ───────────────────────────────────────────────────────────

_PEOPLE_CARD_SELS = [
    ".org-people-profile-card",
    "[class*='org-people-profile-card']",
    ".artdeco-list__item:has(a[href*='/in/'])",
    "li:has(a[href*='/in/'])",
]
_PERSON_NAME_SELS = [
    ".org-people-profile-card__profile-title",
    "[class*='profile-card__profile-title']",
    ".artdeco-entity-lockup__title span[aria-hidden='true']",
    ".artdeco-entity-lockup__title",
]
_PERSON_TITLE_SELS = [
    "[class*='member-title']",
    ".lt-line-clamp--multi-line",
    ".artdeco-entity-lockup__subtitle",
    "[class*='entity-lockup__subtitle']",
]
_PERSON_LOCATION_SELS = [
    ".artdeco-entity-lockup__metadata span",
    "[class*='entity-lockup__metadata']",
    "[class*='member-location']",
]
_PERSON_LINK_SELS = [
    "a.app-aware-link[href*='/in/']",
    "a[href*='linkedin.com/in/']",
    "a[href*='/in/']",
]
_LOAD_MORE_SELS = [
    "button.scaffold-finite-scroll__load-button",
    "button[aria-label*='more']",
    "button[class*='load-more']",
    "button[class*='show-more']",
]


def _extract_people(page, seen_urls: set, company_name: str) -> list[dict]:
    cards = _all(page, _PEOPLE_CARD_SELS)
    results = []
    for card in cards:
        link_el = _first(card, _PERSON_LINK_SELS)
        if not link_el:
            continue
        profile_url = _attr(link_el, "href").split("?")[0].rstrip("/")
        if not profile_url or profile_url in seen_urls:
            continue
        seen_urls.add(profile_url)

        name_el = _first(card, _PERSON_NAME_SELS)
        name = _text(name_el) if name_el else ""

        title_el = _first(card, _PERSON_TITLE_SELS)
        title = _text(title_el) if title_el else ""

        loc_el = _first(card, _PERSON_LOCATION_SELS)
        location = _text(loc_el) if loc_el else ""

        if name or title:
            results.append({
                "name": name,
                "title": title,
                "location": location,
                "profile_url": profile_url,
                "company": company_name,
            })
    return results


def scrape_company_people(
    target: str,
    li_at: str,
    keyword: str = "",
    max_people: int = 100,
    company_name: str = "",
) -> list[dict]:
    """Scrape employees from the company People tab, paginating via 'Show more'."""
    if not li_at:
        raise ValueError("li_at cookie is required")

    pw = browser = context = page = None
    try:
        pw, browser, context = _launch(li_at)
        page = context.new_page()
        _warmup(page)

        slug = _resolve_slug(page, target)
        people_url = f"https://www.linkedin.com/company/{slug}/people/"
        if keyword:
            people_url += f"?keywords={quote(keyword)}"

        log.info("LinkedIn company scraper: fetching people at %s (max=%d)", people_url, max_people)
        try:
            page.goto(people_url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            if "too_many_redirects" in str(e).lower() or "redirect" in str(e).lower():
                raise RuntimeError(_SESSION_ERROR)
            raise
        time.sleep(random.uniform(2.5, 4.0))
        _check_blocked(page)

        seen_urls: set[str] = set()
        people: list[dict] = []
        label = company_name or slug

        for round_num in range(50):  # hard cap: 50 pagination rounds
            new_batch = _extract_people(page, seen_urls, label)
            people.extend(new_batch)
            log.info("LinkedIn people scraper: round %d — %d total", round_num + 1, len(people))

            if len(people) >= max_people:
                break

            # Scroll down to reveal the load-more button
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1.5, 2.5))

            load_more = _first(page, _LOAD_MORE_SELS)
            if not load_more:
                break
            try:
                load_more.click()
            except Exception:
                break
            time.sleep(random.uniform(2.0, 4.0))

        people = people[:max_people]
        log.info("LinkedIn people scraper: done — %d employees from '%s'", len(people), label)
        return people

    finally:
        _close(pw, browser, context, page)


# ─── Company search ───────────────────────────────────────────────────────────

# LinkedIn headcount size codes (used in ?companySize URL param)
SIZE_CODES: dict[str, list[str]] = {
    "1-10":     ["B"],
    "11-50":    ["C"],
    "51-200":   ["D"],
    "201-500":  ["E"],
    "501-1000": ["F"],
    "1001-5000": ["G"],
    "5001-10000": ["H"],
    "10001+":   ["I"],
    "small":    ["B", "C"],           # 1-50
    "medium":   ["D", "E"],           # 51-500
    "large":    ["F", "G", "H", "I"], # 500+
}

_SEARCH_RESULT_SELS = [
    ".entity-result__item",
    ".reusable-search__result-container li",
    ".search-results-container li",
    "li.artdeco-list__item",
]
_SEARCH_NAME_SELS = [
    ".entity-result__title-text a span[aria-hidden='true']",
    ".entity-result__title-text a",
    ".app-aware-link .entity-result__title-text",
]
_SEARCH_LINK_SELS = [
    ".entity-result__title-text a[href*='/company/']",
    "a[href*='/company/']",
]
_SEARCH_PRIMARY_SELS = [
    ".entity-result__primary-subtitle",
    "[class*='primary-subtitle']",
]
_SEARCH_SECONDARY_SELS = [
    ".entity-result__secondary-subtitle",
    "[class*='secondary-subtitle']",
]
_SEARCH_SNIPPET_SELS = [
    ".entity-result__summary",
    "[class*='result__summary']",
]
_NEXT_BTN_SELS = [
    "button[aria-label='Next']",
    ".artdeco-pagination__button--next",
    "button[class*='pagination__button--next']",
]


def _build_search_url(keyword: str, location: str, size_key: str, page: int) -> str:
    import json as _json
    query = keyword.strip()
    if location.strip():
        query += f" {location.strip()}"
    url = f"https://www.linkedin.com/search/results/companies/?keywords={quote(query)}&origin=SWITCH_SEARCH_VERTICAL"
    codes = SIZE_CODES.get(size_key.strip().lower(), [])
    if codes:
        url += f"&companySize={quote(_json.dumps(codes))}"
    if page > 1:
        url += f"&page={page}"
    return url


def _extract_search_results(page_obj, seen_urls: set) -> list[dict]:
    cards = _all(page_obj, _SEARCH_RESULT_SELS)
    results = []
    for card in cards:
        link_el = _first(card, _SEARCH_LINK_SELS)
        if not link_el:
            continue
        href = _attr(link_el, "href").split("?")[0].rstrip("/")
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)

        name_el = _first(card, _SEARCH_NAME_SELS)
        name = _text(name_el) if name_el else ""
        if not name and link_el:
            name = _text(link_el)

        primary_el = _first(card, _SEARCH_PRIMARY_SELS)
        industry = _text(primary_el) if primary_el else ""

        secondary_el = _first(card, _SEARCH_SECONDARY_SELS)
        size_or_followers = _text(secondary_el) if secondary_el else ""

        snippet_el = _first(card, _SEARCH_SNIPPET_SELS)
        snippet = _text(snippet_el) if snippet_el else ""

        results.append({
            "name": name,
            "industry": industry,
            "size": size_or_followers,
            "description": snippet,
            "linkedin_url": href,
        })
    return results


def search_companies(
    keyword: str,
    li_at: str,
    location: str = "",
    size_filter: str = "",
    max_results: int = 100,
) -> list[dict]:
    """Search LinkedIn for companies matching keyword + optional location/size filters.

    Returns a list of company dicts: name, industry, size, description, linkedin_url.
    Paginates until max_results reached or no more pages.
    """
    if not li_at:
        raise ValueError("li_at cookie is required")
    if not keyword.strip():
        raise ValueError("keyword is required")

    pw = browser = context = page_obj = None
    try:
        pw, browser, context = _launch(li_at)
        page_obj = context.new_page()
        _warmup(page_obj)

        seen_urls: set[str] = set()
        companies: list[dict] = []
        page_num = 1

        log.info(
            "LinkedIn company search: keyword='%s' location='%s' size='%s' max=%d",
            keyword, location, size_filter, max_results,
        )

        while len(companies) < max_results:
            url = _build_search_url(keyword, location, size_filter, page_num)
            log.info("LinkedIn company search: page %d — %s", page_num, url)
            try:
                page_obj.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception as e:
                if "too_many_redirects" in str(e).lower() or "redirect" in str(e).lower():
                    raise RuntimeError(_SESSION_ERROR)
                raise
            time.sleep(random.uniform(2.5, 4.0))
            _check_blocked(page_obj)

            batch = _extract_search_results(page_obj, seen_urls)
            if not batch:
                log.info("LinkedIn company search: no results on page %d — stopping", page_num)
                break
            companies.extend(batch)
            log.info(
                "LinkedIn company search: page %d — +%d (total %d)",
                page_num, len(batch), len(companies),
            )

            if len(companies) >= max_results:
                break

            # Check for Next button
            next_btn = _first(page_obj, _NEXT_BTN_SELS)
            if not next_btn:
                log.info("LinkedIn company search: no Next button — done")
                break
            try:
                next_btn.click()
                time.sleep(random.uniform(2.0, 3.5))
                page_num += 1
            except Exception:
                break

        companies = companies[:max_results]
        log.info("LinkedIn company search: done — %d companies", len(companies))
        return companies

    finally:
        _close(pw, browser, context, page_obj)
