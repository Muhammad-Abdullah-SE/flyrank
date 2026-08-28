"""Main scraper pipeline — fetch, extract, normalize, validate, store, report."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is on sys.path so src.X imports work
def _ensure_path():
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

_ensure_path()

from src.fetcher import check_robots_txt, fetch_url, CACHE_DIR
from src.extractor import extract_book_detail, extract_book_links, find_next_page
from src.validator import validate_and_normalize


BASE_URL = "https://books.toscrape.com"
CATALOGUE_URL = f"{BASE_URL}/catalogue/page-1.html"
MAX_CATALOGUE_PAGES = 3
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def main():
    start_time = datetime.now(timezone.utc)
    print("=" * 60)
    print("FLYRANK W5 — The Polite Scraper")
    print(f"Started: {start_time.isoformat()}")
    print("=" * 60)

    # ── Stage 0: Check robots.txt ──
    robots_result = check_robots_txt(BASE_URL)
    print(f"\n[Stage 0] robots.txt → {robots_result}")

    # ── Stage 1–2: Fetch catalogue pages and discover book URLs ──
    all_book_urls: list[str] = []
    book_source_pages: dict[str, str] = {}
    catalogue_pages_fetched = 0
    cache_hit_count = 0
    pages_fetched_count = 0
    current_url = CATALOGUE_URL

    for page_num in range(1, MAX_CATALOGUE_PAGES + 1):
        print(f"\n[Stage 2] Catalogue page {page_num}: {current_url}")
        html, status = fetch_url(current_url)

        if html is None or status != 200:
            print(f"  FAILED (status {status}), stopping catalogue crawl.")
            break

        catalogue_pages_fetched += 1

        links = extract_book_links(html, current_url)
        print(f"  Found {len(links)} book links on page {page_num}")
        for link in links:
            book_source_pages[link] = current_url
        all_book_urls.extend(links)

        next_url = find_next_page(html, current_url)
        if next_url:
            current_url = next_url
        else:
            print("  No next page — done with catalogue.")
            break

    # Deduplicate while preserving order
    seen = set()
    unique_urls: list[str] = []
    for u in all_book_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    # Stage 5 failure test: set FAIL_TEST_URL env var to inject one fake URL
    # (breaks things on our side only — never by hammering the real site)
    fail_test_url = os.environ.get("FAIL_TEST_URL")
    if fail_test_url:
        unique_urls.append(fail_test_url)
        print(f"\n[Stage 5] FAIL TEST: injected fake URL → {fail_test_url}")

    print(f"\n[Stage 2] Summary: catalogue_pages={catalogue_pages_fetched}, "
          f"discovered={len(all_book_urls)}, unique_urls={len(unique_urls)}")

    # ── Stage 3–5: Fetch book pages, extract, validate, survive failures ──
    valid_records: list[dict] = []
    invalid_records: list[dict] = []
    failed_pages: list[dict] = []

    existing_cache = set(f.name for f in CACHE_DIR.glob("*.html")) if CACHE_DIR.exists() else set()

    for i, book_url in enumerate(unique_urls):
        print(f"\n[Stage 3] Book {i + 1}/{len(unique_urls)}: {book_url}")

        cache_filename = book_url.replace("https://", "").replace("http://", "").replace("/", "_").replace("?", "_q_").replace("&", "_a_")[:200] + ".html"
        was_cached = cache_filename in existing_cache

        html, status = fetch_url(book_url)
        pages_fetched_count += 1

        if html is None or status != 200:
            failed_pages.append({"url": book_url, "status": status})
            print(f"  FAILED (status {status}) — skipping.")

            # Retry once for 5xx / timeout (Stage 5)
            if status in (408, 500, 502, 503, 504) or status >= 500:
                print("  Retrying after 1s...")
                time.sleep(1)
                html2, status2 = fetch_url(book_url)
                pages_fetched_count += 1
                if html2 is not None and status2 == 200:
                    print("  Retry succeeded!")
                    raw = extract_book_detail(html2, book_url,
                                              source_page=book_source_pages.get(book_url, ""))
                    if raw:
                        record, error = validate_and_normalize(raw)
                        if record:
                            valid_records.append(record.model_dump())
                        else:
                            invalid_records.append({"url": book_url, "reason": error})
                    else:
                        failed_pages.append({"url": book_url, "status": "parse_error"})
                else:
                    print(f"  Retry also failed (status {status2}).")
            continue

        if was_cached:
            cache_hit_count += 1

        raw = extract_book_detail(html, book_url, source_page=book_source_pages.get(book_url, ""))
        if raw is None:
            failed_pages.append({"url": book_url, "status": "parse_error"})
            print("  PARSE ERROR — could not extract data.")
            continue

        record, error = validate_and_normalize(raw)
        if record:
            valid_records.append(record.model_dump())
            print(f"  OK: {raw.title} — {raw.price_text}")
        else:
            invalid_records.append({"url": book_url, "reason": error})
            print(f"  INVALID: {error}")

    # ── Idempotency: deduplicate by product_url ──
    seen_urls = set()
    deduped: list[dict] = []
    for r in valid_records:
        if r["product_url"] not in seen_urls:
            seen_urls.add(r["product_url"])
            deduped.append(r)

    # ── Stage 4–6: Write outputs & report ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_DIR / "books.json", "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    with open(OUTPUT_DIR / "errors.json", "w", encoding="utf-8") as f:
        json.dump(invalid_records, f, indent=2, ensure_ascii=False)

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    report = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_seconds": round(duration, 2),
        "pages_fetched": pages_fetched_count,
        "cache_hits": cache_hit_count,
        "catalogue_pages": catalogue_pages_fetched,
        "unique_urls_discovered": len(unique_urls),
        "valid_records": len(deduped),
        "invalid_records": len(invalid_records),
        "failed_pages": len(failed_pages),
        "failed_page_details": failed_pages,
    }

    with open(OUTPUT_DIR / "run-report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # ── Print summary ──
    print("\n" + "=" * 60)
    print("RUN REPORT")
    print("=" * 60)
    for k, v in report.items():
        if k != "failed_page_details":
            print(f"  {k}: {v}")
    print(f"\nOutput:")
    print(f"  books.json   -> {len(deduped)} records")
    print(f"  errors.json  -> {len(invalid_records)} records")
    print(f"  run-report.json -> saved")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
