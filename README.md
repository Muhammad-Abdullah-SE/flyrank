# FlyRank — "Your 10x Solution" capstone

No external dependencies. Everything runs on the Python 3.9+ standard library
(HTTP server, SQLite, hashing, JSON, PDF generation). Nothing to install —
just 2 commands to start, 3 if you count the tests.

## Run in two commands

```bash
python scripts/seed.py       # 1. create the demo database (user + deals + history)
python -m flyrank.app        # 2. start the server -> http://127.0.0.1:8000

# optional third command — the test suite
python -m unittest discover -s tests -v
```

On Windows: `py scripts/seed.py` / `py -m flyrank.app` also work.

## 5-minute demo path (open X, click Y, see Z)

1. Open http://127.0.0.1:8000 — you land on the **Deals** board with ranked deals.
2. Click **Sign in** → use the demo account `demo@flyrank.dev` / `demo1234`.
3. In the search row, type `LHR` in *Origin*, click **Search deals** — the list
   filters and the header shows `cache: HIT/MISS`.
4. Click **☆ watch** on a deal, open **Watchlist** — it is there.
5. Open **AI Briefing**, click **Generate briefing** — you get a plain-language
   summary with token/cost meta (logged, even with the offline summarizer).
6. Open **Reports**, click **Download weekly PDF report** — a real PDF downloads.
7. Open **Jobs**, click **Trigger price refresh now** — a background job runs
   and the run (with status + detail) appears in the table.
8. Done. API-only users: `curl http://127.0.0.1:8000/api/health`.

## Problem

Travelers spend hours each week browsing airline sites and aggregators to find
a good fare, comparing dozens of tabs, re-checking prices, and still missing
drops because nothing watches the prices for them. FlyRank replaces that
manual ritual with a single ranked feed: it scores every deal
(price vs route average, seat urgency, freshness) on a 0–100 value score,
watches prices in the background, and packages the result as an AI briefing
and a weekly PDF report.

## 5+ concepts — implemented, all 7 core (no swaps needed)

| # | Concept              | Where it lives in the code                                                                |
|---|----------------------|------------------------------------------------------------------------------------------|
| 1 | API endpoints        | `flyrank/app.py` — REST API with 201/400/401/404/405/409/202 codes + validation          |
| 2 | Database             | `flyrank/db.py` — SQLite (users, sessions, deals, price_history, watchlist, jobs, ai_logs, kv_cache); data survives restarts |
| 3 | Authentication       | `flyrank/auth.py` — PBKDF2-SHA256 hashing, opaque bearer tokens, protected routes         |
| 4 | Background/cron jobs | `flyrank/scheduler.py` — cron `30 8 * * *` price refresh off the request path; on-demand trigger returns 202 |
| 5 | Reporting (PDF)      | `flyrank/reporting.py` — dependency-free PDF generator; `GET /api/reports/weekly`         |
| 6 | Caching              | `flyrank/cache.py` + `X-Cache: HIT/MISS` headers — TTL cache, memory + SQLite-backed      |
| 7 | LLM integration      | `flyrank/llm.py` — `POST /api/deals/summarize`: validated, timeouts, cost log (ai_logs)  |

Swap note: the brief allows replacing up to 2 concepts with swaps. FlyRank
does not need any — all 7 core concepts fit the solution, so no swaps are used.

## Project layout

```
flyrank/
  app.py        HTTP server + routes (the API)
  db.py         SQLite schema + connections
  auth.py       register/login, tokens, protected routes
  deals.py      ranking engine + search (cached)
  llm.py        AI briefing + cost log (OpenAI-compatible or local fallback)
  reporting.py  pure-Python PDF report writer
  scheduler.py  cron matching + background jobs
  cache.py      TTL cache (memory + SQLite)
  sources.py    simulated live flight feed (keeps the build $0)
  web/index.html  dashboard UI (served by the app)
scripts/
  seed.py       demo data: user, deals, price history, first job
  run_cron.py   run the scheduler as its own process (--once for one shot)
tests/
  test_app.py   scary cases: auth, validation, cache, PDF, jobs, LLM logging
```

## Concepts → assignments map

| Capstone need        | Assignment it reuses            |
|----------------------|---------------------------------|
| Login + protected routes | A4 Auth: login & protect     |
| Database with real data  | A2/A3 CRUD to database       |
| Slow work in background  | A7 first background job      |
| PDF report              | A8 PDF report generator      |
| AI feature behind API   | A17 LLM behind your API      |
| External data           | A9/A16 scraping assignments  (replaced here by a simulated feed so the project stays $0 and self-contained) |

## API reference

| Method | Path                       | Auth | Description                          |
|--------|----------------------------|------|--------------------------------------|
| POST   | /api/auth/register         | –    | Create account → 201 {user, token}   |
| POST   | /api/auth/login            | –    | Login → 200 {user, token}            |
| POST   | /api/auth/logout           | ✔    | Revoke token → 204                   |
| GET    | /api/me                    | ✔    | Current user                         |
| GET    | /api/deals                 | –    | Ranked deals (filters: origin, destination, airline, max_price; sort: value/price/departure; limit) |
| GET    | /api/deals/search?q=       | –    | Free-text search (cached)            |
| POST   | /api/deals/<id>/watch      | ✔    | Add to watchlist → 201               |
| DELETE | /api/deals/<id>/watch      | ✔    | Remove from watchlist → 204          |
| GET    | /api/watchlist             | ✔    | Your watched deals                   |
| POST   | /api/deals/summarize       | ✔    | AI briefing + cost log               |
| GET    | /api/reports/weekly        | ✔    | Weekly PDF report                    |
| GET    | /api/jobs                  | ✔    | Recent background job runs           |
| POST   | /api/jobs/refresh          | ✔    | Trigger price refresh → 202 (background) |
| GET    | /api/health                | –    | Liveness + implemented concepts      |

Example:

```bash
curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@flyrank.dev","password":"demo1234"}'
```

## Configuration

All settings are environment variables; nothing is committed. See `.env.example`.
The only one that changes behavior is `LLM_API_KEY`: with it, `/api/deals/summarize`
calls an OpenAI-compatible chat completions endpoint; without it, a deterministic
local summarizer answers (both are logged with token usage + estimated cost).

- `FLYRANK_HOST` (default 127.0.0.1), `FLYRANK_PORT` (default 8000)
- `FLYRANK_DB` (default `data/flyrank.db`)
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`

## Non-goal (scope guard)

FlyRank does NOT do live booking, payments, real airline aggregation, or a
mobile app. The flight feed is a simulated provider so the whole system runs
on free tools with no credit card — the engineering (API, database, auth,
jobs, PDF, cache, LLM) is real.

## Future ideas

- Real provider connectors (Amadeus / Google Flights scraping pipeline — swap-in)
- Email alert delivery for watched deals (reporting by email, per-downgrade rules)
- RAG over price history ("why is this deal cheap?")
- Deploy to a free tier (Render/Railway) with a live URL
- 2-minute demo video linked from this README

## The 10x claim

Finding and tracking a good flight deal used to mean 1–2 hours of tab-hopping
per week; with FlyRank the same outcome — ranked best-value flight + price
watch + weekly digest — takes under a minute, roughly **60–120× less time**
for the daily watch ritual and zero manual price re-checking.

## License

MIT — yours to own, fork, and put in your portfolio.