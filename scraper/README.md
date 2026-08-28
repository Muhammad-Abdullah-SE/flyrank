# W5 — The Polite Scraper

## Target Classification

- **Site:** [Books to Scrape](https://books.toscrape.com/) — a public practice sandbox built specifically for people to learn web scraping.
- **Scope:** First 3 catalogue pages only (60 books total).
- **Data collected:** title, product URL, price, availability, star rating, description, source page, and fetch timestamp.
- **Why it is appropriate:** The site explicitly states it exists for scraping practice. It is a sandbox, not a production service.

## Robots.txt Check

`https://books.toscrape.com/robots.txt` returned **404 — no robots file found.** A missing file is not permission; it is just a missing file. The site’s own homepage confirms it is a sandbox for practice, which is why scraping is appropriate here.

> I will not reuse this code on another site without checking its rules and terms first.

## Setup & Run

```bash
pip install requests beautifulsoup4 pydantic
python src/main.py
```

## Lane

Python 3.10+ with:
- **requests** — HTTP fetching
- **Beautiful Soup 4** — HTML parsing
- **Pydantic** — schema validation

## Record Schema

```json
{
  "title": "string (required)",
  "product_url": "string (required, https://, unique/canonical)",
  "price_text": "string (required)",
  "price_gbp": "float (required, derived from price_text)",
  "availability_text": "string (required)",
  "rating_text": "string (required)",
  "description": "string | null (optional)",
  "source_page": "string (required)",
  "fetched_at": "string (ISO 8601, required)"
}
```

## Politeness Rules

- **User-Agent:** `FlyRankInternship-A9/1.0 (+https://github.com/your-repo)` — identifies who we are and where to find us.
- **Delay:** At least 500 ms between every real (non-cached) request.
- **Timeout:** 10 seconds — a request gives up rather than hanging forever.
- **Cache:** Every fetched page is saved locally. During development, cached files are reused so the site is hit only once.

## Why No Browser?

The data is already in the HTML the server sends. A browser would add cost (memory, startup time, complexity) with no benefit — the server-rendered HTML contains every field we need.

## Ethics Note

Always use an official API when one exists. Never bypass logins, paywalls, or blocks. Collect only the data you need. A scraper is a guest — behave like one.

## Honest Limitation

This scraper assumes the catalogue page structure of Books to Scrape remains stable. If the site redesigns, selectors will need updating. It also does not handle JavaScript-rendered content — all data must be present in the initial HTML response.

## Failure Test (Stage 5)

To prove one broken page never kills the run, inject a fake URL via an environment variable (breaks things on our side only — never by hammering the real site):

```bash
# PowerShell
$env:FAIL_TEST_URL = 'https://books.toscrape.com/catalogue/this-book-does-not-exist_9999/index.html'
python src/main.py

# Bash
FAIL_TEST_URL='https://books.toscrape.com/catalogue/this-book-does-not-exist_9999/index.html' python src/main.py
```

Result with the fake URL injected: the run finishes, books.json still contains the 60 good records, and the report shows `failed_pages: 1` (status 404 — logged and skipped, never retried, since a 404 will not heal by asking again).

## Sample Run Report

Real clean run (first run, live fetches, 500 ms delay between requests):

```json
{
  "start_time": "2026-08-27T17:56:23.993014+00:00",
  "end_time": "2026-08-27T17:58:38.055689+00:00",
  "duration_seconds": 134.06,
  "pages_fetched": 60,
  "cache_hits": 0,
  "catalogue_pages": 3,
  "unique_urls_discovered": 60,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 0,
  "failed_page_details": []
}
```

Second run (idempotent, mostly from cache — 1.5 s instead of 134 s):

```json
{
  "start_time": "2026-08-27T18:13:04.641004+00:00",
  "end_time": "2026-08-27T18:13:09.173836+00:00",
  "duration_seconds": 4.53,
  "pages_fetched": 60,
  "cache_hits": 60,
  "catalogue_pages": 3,
  "unique_urls_discovered": 60,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 0,
  "failed_page_details": []
}
```

Failure-test run (fake URL injected → `failed_pages: 1`, 60 good records survive):

```json
{
  "start_time": "2026-08-27T18:12:17.276615+00:00",
  "end_time": "2026-08-27T18:12:20.406081+00:00",
  "duration_seconds": 3.13,
  "pages_fetched": 61,
  "cache_hits": 60,
  "catalogue_pages": 3,
  "unique_urls_discovered": 61,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 1,
  "failed_page_details": [
    {
      "url": "https://books.toscrape.com/catalogue/this-book-does-not-exist_9999/index.html",
      "status": 404
    }
  ]
}
```

## Tests

11 unit tests, no network required (parser fixtures, price normalization, relative→absolute URLs, missing description, duplicate URLs, schema validation):

```bash
pip install pytest
python -m pytest tests/ -v
```
