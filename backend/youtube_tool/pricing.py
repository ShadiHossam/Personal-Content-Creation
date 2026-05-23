"""Token cost estimation for the AI providers we call.

Prices are in USD per 1M tokens. They're approximate — model vendors change them
regularly, so the numbers here are a best-effort reference the UI can surface
instead of a guarantee. For the Claude CLI (subscription), cost is reported as
``0`` with a note that it's a flat subscription.
"""

from __future__ import annotations

# Prices in USD per 1,000,000 tokens.
# Entries are matched by `model.lower().startswith(key)` in order — longest keys first.
_PRICING = {
    # Anthropic — https://www.anthropic.com/pricing
    "claude-opus-4": {"in": 15.00, "out": 75.00},
    "claude-sonnet-4": {"in": 3.00, "out": 15.00},
    "claude-3-5-sonnet": {"in": 3.00, "out": 15.00},
    "claude-3-5-haiku": {"in": 0.80, "out": 4.00},
    "claude-haiku-4": {"in": 1.00, "out": 5.00},
    # OpenAI — https://openai.com/pricing
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gpt-4-turbo": {"in": 10.00, "out": 30.00},
    "o1-mini": {"in": 3.00, "out": 12.00},
    "o1": {"in": 15.00, "out": 60.00},
    # OpenRouter pass-through (examples; many models are free tier).
    "google/gemma-4-31b-it:free": {"in": 0, "out": 0},
    "meta-llama/llama-3.3-70b-instruct:free": {"in": 0, "out": 0},
    "meta-llama/": {"in": 0.20, "out": 0.20},
    "mistralai/": {"in": 0.20, "out": 0.60},
}


def _match(model):
    m = (model or "").strip().lower()
    if not m:
        return None
    # Prefer longest-prefix match.
    best = None
    for k, v in _PRICING.items():
        if m.startswith(k.lower()) and (best is None or len(k) > len(best[0])):
            best = (k, v)
    return best


def estimate(provider, model, usage):
    """Return {prompt_tokens, completion_tokens, total_tokens, usd, note}.

    `usage` is whatever the provider returned (we accept the standard OpenAI
    {prompt_tokens, completion_tokens, total_tokens} shape and gracefully fall
    back if fields are missing).
    """
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))

    if provider == "claude_cli":
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "usd": 0.0,
            "note": "Claude subscription — metered by your Claude Code plan, not per-call.",
        }

    match = _match(model)
    if not match:
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "usd": None,
            "note": f"No price table entry for '{model or 'default'}' — cost unknown.",
        }
    key, rates = match
    usd = (prompt / 1_000_000) * rates["in"] + (completion / 1_000_000) * rates["out"]
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "usd": round(usd, 6),
        "note": f"Estimated using public pricing for {key}.",
    }


def breakdown_many(provider, model, usages):
    """Sum `estimate()` across a list of usage dicts (useful for comment reports)."""
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "usd": 0.0}
    note = None
    usd_unknown = False
    for u in usages or []:
        est = estimate(provider, model, u)
        totals["prompt_tokens"] += est["prompt_tokens"]
        totals["completion_tokens"] += est["completion_tokens"]
        totals["total_tokens"] += est["total_tokens"]
        if est["usd"] is None:
            usd_unknown = True
        else:
            totals["usd"] += est["usd"]
        note = est.get("note")
    if usd_unknown:
        totals["usd"] = None
    else:
        totals["usd"] = round(totals["usd"], 6)
    totals["note"] = note
    return totals
