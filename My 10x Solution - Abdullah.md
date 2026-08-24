# FlyRank — "My 10x Solution"
### Abdullah — FlyRank Internship, Backend Track · Capstone

---

## 1. What problem am I solving?

Finding a good flight deal is a slow, manual ritual. Travelers open airline
sites and aggregators, compare dozens of tabs by hand, bookmark prices, and
then re-check them every few days hoping for a drop — and because nothing
watches the fares for them, they regularly miss the drop and overpay at the
moment of booking.

**Who has this problem:** anyone who books flights regularly on a budget —
students, remote workers hopping between cities, freelancers, and small teams
planning trips.

**My 10x claim:** the weekly ritual of hunting and tracking deals (1–2 hours
of tab-hopping per week) becomes one minute with FlyRank: a single ranked feed
of flight deals scored on a 0–100 "value score" (price vs route average, seat
urgency, freshness), automatic price watching in the background, and the
results packaged as an AI briefing and a weekly PDF report — roughly
**60–120× less effort**, and the price watching simply never sleeps.

**Non-goal (written down, on purpose):** FlyRank does *not* do live booking,
payments, or real airline aggregation. The flight feed is a simulated provider,
so the whole system runs on free tools with no credit card — the engineering
is real, the data source keeps the project finishable.

## 2. How did I implement it?

**Stack:** Python 3.9+ **standard library only** (http.server, sqlite3,
hashlib, urllib, json) — zero external dependencies, no pip install, no
credit card. The dashboard is a single HTML/JS page served by the app.

**How it works, in plain words:**

1. The server exposes a REST API (`flyrank/app.py`) with real status codes and
   validation. The dashboard and any script talk to it over HTTP.
2. Every record lives in a SQLite database (`flyrank/db.py`) — users, sessions,
   deals, price history, watchlists, job runs, AI cost logs, and the cache.
   It all survives restarts.
3. Users register/login (`flyrank/auth.py`): passwords are hashed with
   PBKDF2-SHA256 and sessions are opaque bearer tokens; protected routes
   (AI, reports, jobs, watchlist) reject missing/invalid tokens with 401.
4. A scheduler thread (`flyrank/scheduler.py`) runs a cron job
   (`daily_price_refresh`, `30 8 * * *`) off the request path: it polls the
   simulated live feed, stores every price snapshot, and logs each run in the
   `jobs` table. You can also trigger the same job manually — the API answers
   202 *accepted* and runs it in a background thread.
5. A weekly report endpoint (`flyrank/reporting.py`) generates a real PDF
   (stats + ranked deals table) with a dependency-free PDF writer.
6. Expensive results (ranked lists, search) are cached (`flyrank/cache.py`)
   with a TTL, backed by memory + SQLite, and the API reports
   `X-Cache: HIT/MISS`.
7. One narrow AI job sits behind an endpoint (`flyrank/llm.py`):
   `/api/deals/summarize` turns the top deals into a plain-language briefing.
   It validates input, has a timeout, and every call is written to the
   `ai_logs` table with model, tokens, and estimated cost. It uses an
   OpenAI-compatible API when `LLM_API_KEY` is set, otherwise a deterministic
   local summarizer — the feature works either way at $0.

### The 5+ concepts (7 core — no swaps needed)

| # | Concept                  | Where it lives in the code                              |
|---|--------------------------|---------------------------------------------------------|
| 1 | API endpoints            | `flyrank/app.py`                                        |
| 2 | Database                 | `flyrank/db.py` — SQLite, survives restarts             |
| 3 | Authentication           | `flyrank/auth.py` — PBKDF2 + bearer tokens, 401s        |
| 4 | Background / cron jobs   | `flyrank/scheduler.py` — cron refresh + 202 background  |
| 5 | Reporting (PDF)          | `flyrank/reporting.py` — weekly PDF via the API         |
| 6 | Caching                  | `flyrank/cache.py` — TTL cache, `X-Cache` headers       |
| 7 | LLM integration          | `flyrank/llm.py` — validated, timeout, cost log         |

*Swap note:* the brief allows up to two swaps; none were needed — all seven
core concepts fit the solution, so all seven are used.

### How to run it (two commands + one for tests)

```bash
python scripts/seed.py                 # demo database: user, deals, history
python -m flyrank.app                  # server -> http://127.0.0.1:8000
python -m unittest discover -s tests -v   # the scary-case test suite
```

Demo login: `demo@flyrank.dev` / `demo1234` · everything free, no credit card.

*See README.md for the full API reference, 5-minute demo path, and layout.*