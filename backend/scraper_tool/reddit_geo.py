"""Curated geo subreddits for the Trend Research → Reddit source.

Maps a location id (country/city slug) to a list of subreddits worth
searching for that locale. Kept deliberately small and editable — extend the
map as you discover useful subs for new markets.

Used only when the user picks a country in the Reddit source's "Location"
dropdown. Without a location pick, Reddit search runs against r/all.
"""

from __future__ import annotations

# Order matters for UI display: most-relevant subreddit first.
GEO_SUBREDDITS: dict[str, dict] = {
    "uae":         {"label": "UAE / Dubai",    "subs": ["dubai", "UAE", "abudhabi"]},
    "saudi":       {"label": "Saudi Arabia",   "subs": ["saudiarabia", "Riyadh", "jeddah"]},
    "qatar":       {"label": "Qatar",          "subs": ["qatar", "doha"]},
    "france":      {"label": "France",         "subs": ["france", "paris", "AskFrance"]},
    "uk":          {"label": "United Kingdom", "subs": ["unitedkingdom", "AskUK", "london"]},
    "usa":         {"label": "United States",  "subs": ["AskAnAmerican", "Entrepreneur", "smallbusiness"]},
    "india":       {"label": "India",          "subs": ["india", "mumbai", "bangalore", "delhi"]},
    "singapore":   {"label": "Singapore",      "subs": ["singapore", "askSingapore"]},
    "canada":      {"label": "Canada",         "subs": ["canada", "toronto", "vancouver", "PersonalFinanceCanada"]},
    "germany":     {"label": "Germany",        "subs": ["germany", "berlin", "AskAGerman"]},
    "australia":   {"label": "Australia",      "subs": ["australia", "sydney", "melbourne", "AusFinance"]},
    "ireland":     {"label": "Ireland",        "subs": ["ireland", "dublin"]},
    "netherlands": {"label": "Netherlands",    "subs": ["Netherlands", "Amsterdam"]},
    "spain":       {"label": "Spain",          "subs": ["spain", "askspain", "Madrid"]},
    "italy":       {"label": "Italy",          "subs": ["italy", "AskItaly"]},
    "japan":       {"label": "Japan",          "subs": ["japan", "japanlife", "tokyo"]},
}


# Popular non-geo subreddits the chip picker offers as autocomplete suggestions.
# Pulled from the categories most relevant to this user's content/SEO/business
# work. Free-typed subs still work — this list is just suggestions.
SUGGESTED_SUBS: list[str] = [
    # Business / entrepreneurship
    "Entrepreneur", "smallbusiness", "startups", "EntrepreneurRideAlong",
    "sweatystartup", "kickstarter", "freelance", "consulting",
    # Marketing / SEO / content
    "marketing", "SEO", "bigseo", "content_marketing", "PPC", "DigitalMarketing",
    "copywriting", "socialmedia", "Emailmarketing", "Affiliatemarketing",
    # Tech / AI / dev
    "ArtificialIntelligence", "ChatGPT", "OpenAI", "ClaudeAI", "LocalLLaMA",
    "MachineLearning", "programming", "webdev", "javascript", "Python",
    "selfhosted", "technology",
    # Finance / personal finance
    "personalfinance", "financialindependence", "investing", "Fire",
    # Productivity / career
    "productivity", "cscareerquestions", "remotework", "digitalnomad",
    # Misc useful
    "AskReddit", "explainlikeimfive", "OutOfTheLoop", "todayilearned",
]


def options() -> list[dict]:
    """UI catalog: [{id, label}, ...] sorted alphabetically by label."""
    return sorted(
        [{"id": k, "label": v["label"]} for k, v in GEO_SUBREDDITS.items()],
        key=lambda x: x["label"],
    )


def subs_for(location_id: str) -> list[str]:
    if not location_id:
        return []
    return list(GEO_SUBREDDITS.get(location_id, {}).get("subs") or [])


def all_suggested_subs() -> list[str]:
    """Suggestions for the chip picker: curated business/tech subs + every
    geo subreddit (deduped, sorted, case-insensitive)."""
    seen: set[str] = set()
    out: list[str] = []
    for sub in SUGGESTED_SUBS:
        key = sub.lower()
        if key not in seen:
            seen.add(key)
            out.append(sub)
    for entry in GEO_SUBREDDITS.values():
        for sub in entry.get("subs") or []:
            key = sub.lower()
            if key not in seen:
                seen.add(key)
                out.append(sub)
    return sorted(out, key=str.lower)
