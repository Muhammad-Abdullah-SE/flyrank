"""LLM integration (concept: LLM INTEGRATION).

One narrow AI job behind an endpoint: /api/deals/summarize turns the ranked
deal list into a plain-language briefing. The call is validated, runs behind
an auth-protected route, has a timeout, and every request is written to the
ai_logs table (model, tokens, estimated cost) - a "cost log", as required.

Design decision: FlyRank is a $0 no-credit-card project. If LLM_API_KEY is
set, it calls an OpenAI-compatible chat completions endpoint. If the key is
absent (default for the demo), it uses a deterministic local summarizer, so
the feature is fully functional out of the box either way.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import db

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
# USD per 1k tokens for cost logging (gpt-4o-mini pricing)
PRICE_IN = 0.00015
PRICE_OUT = 0.00060
MAX_DEALS = 25


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _local_summary(deals: list[dict]) -> str:
    """Deterministic rule-based briefing (offline LLM fallback)."""
    if not deals:
        return "No deals found for the selected filters."
    prices = [d["price"] for d in deals]
    best = deals[0]
    cheapest = min(deals, key=lambda d: d["price"])
    below500 = [d for d in deals if d["price"] < 500]
    airlines = sorted({d["airline"] for d in deals})
    routes = sorted({f"{d['origin']}→{d['destination']}" for d in deals})
    lines = [
        f"Flight briefing for the top {len(deals)} ranked deals.",
        f"Best value right now: {best['airline']} {best['origin']}→{best['destination']} "
        f"on {best['departure_date']} for ${best['price']:.0f} "
        f"(value score {best['value_score']:.0f}/100, {best['vs_route_avg']:.0f}% below route average).",
        f"Cheapest option: {cheapest['airline']} {cheapest['origin']}→{cheapest['destination']} "
        f"at ${cheapest['price']:.0f}.",
        f"Price range across the batch: ${min(prices):.0f} - ${max(prices):.0f}.",
        f"{len(below500)} of {len(deals)} deals are under $500.",
        f"Airlines in the mix: {', '.join(airlines[:6])}{'…' if len(airlines) > 6 else ''}.",
        f"Routes covered: {', '.join(routes[:6])}.",
        "Tip: deals with high value scores and few seats left tend to move fast - watch them.",
    ]
    return "\n".join(lines)


def _call_openai_compatible(deals: list[dict]) -> dict:
    model = _env("LLM_MODEL", DEFAULT_MODEL)
    base = _env("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    key = _env("LLM_API_KEY")
    system = (
        "You are the FlyRank flight-deal analyst. Summarize the ranked flight "
        "deals into a short, practical briefing (max 6 bullet lines, plain text). "
        "Mention concrete prices, routes and the top pick."
    )
    user = "Ranked deals:\n" + json.dumps(deals[:MAX_DEALS], indent=1)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"].strip()
    usage = body.get("usage", {})
    return {
        "summary": content,
        "model": model,
        "prompt_tokens": int(usage.get("prompt_tokens", _estimate_tokens(user))),
        "completion_tokens": int(usage.get("completion_tokens", _estimate_tokens(content))),
    }


def summarize_deals(deals: list[dict], user: dict | None) -> dict:
    """Validate + summarize deals behind a protected endpoint, log the cost."""
    # --- validation ---
    if not isinstance(deals, list):
        raise ValueError("deals must be a list")
    if len(deals) > MAX_DEALS:
        raise ValueError(f"too many deals (max {MAX_DEALS})")
    cleaned: list[dict] = []
    for d in deals[:MAX_DEALS]:
        if not isinstance(d, dict) or not all(k in d for k in ("airline", "origin", "destination", "price")):
            raise ValueError("each deal needs airline, origin, destination, price")
        price = float(d["price"])
        if price <= 0 or price > 100_000:
            raise ValueError("price out of range")
        cleaned.append(
            {
                "airline": str(d["airline"])[:40],
                "origin": str(d["origin"])[:3].upper(),
                "destination": str(d["destination"])[:3].upper(),
                "departure_date": str(d.get("departure_date", ""))[:10],
                "price": round(price, 2),
                "value_score": round(float(d.get("value_score", 0)), 1),
                "vs_route_avg": round(float(d.get("vs_route_avg", 0)), 1),
            }
        )
    if not cleaned:
        raise ValueError("deals list is empty")

    source = "llm"
    model = _env("LLM_MODEL", DEFAULT_MODEL)
    prompt_tokens = completion_tokens = 0
    error_note = ""
    if _env("LLM_API_KEY"):
        try:
            result = _call_openai_compatible(cleaned)
            summary = result["summary"]
            model = result["model"]
            prompt_tokens = result["prompt_tokens"]
            completion_tokens = result["completion_tokens"]
        except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
            source = "local"
            error_note = f" (llm unavailable: {exc})"
            summary = _local_summary(cleaned)
            model = f"local-fallback{error_note}"
    else:
        source = "local"
        summary = _local_summary(cleaned)

    cost_usd = round(prompt_tokens * PRICE_IN + completion_tokens * PRICE_OUT, 6)
    db.execute(
        """
        INSERT INTO ai_logs (user_id, model, endpoint, prompt_tokens, completion_tokens, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user["id"] if user else None,
            model,
            "/api/deals/summarize",
            prompt_tokens,
            completion_tokens,
            cost_usd,
        ),
    )
    return {
        "summary": summary,
        "source": source,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost_usd,
    }


def usage_stats() -> dict:
    row = db.query_one(
        """
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens),0) AS completion_tokens,
               COALESCE(SUM(cost_usd),0) AS cost_usd
        FROM ai_logs
        """
    )
    return row or {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0}