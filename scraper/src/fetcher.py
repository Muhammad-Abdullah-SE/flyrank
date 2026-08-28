"""Polite HTTP fetcher with caching, user-agent, timeout, and delay."""

import os
import time
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent.parent / "cache"
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/flyrank/w5-scraper)"
TIMEOUT_SECONDS = 10
DELAY_BETWEEN_REQUESTS = 0.5  # seconds


def _make_cache_filename(url: str) -> str:
    """Turn a URL into a safe filename for the cache."""
    safe = url.replace("https://", "").replace("http://", "")
    safe = safe.replace("/", "_").replace("?", "_q_").replace("&", "_a_")
    return safe[:200] + ".html"


def fetch_url(url: str) -> tuple[str | None, int]:
    """
    Fetch a URL with politeness rules.
    
    Returns (html_content, status_code).
    On failure, returns (None, status_code).
    """
    cache_path = CACHE_DIR / _make_cache_filename(url)

    # Check cache first
    if cache_path.exists():
        print(f"  CACHE HIT: {url}")
        content = cache_path.read_text(encoding="utf-8")
        return content, 200

    print(f"  FETCH: {url}")

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
        )
        # The site sends UTF-8 but doesn't declare it — fix encoding
        if resp.apparent_encoding == 'utf-8':
            resp.encoding = 'utf-8'

        time.sleep(DELAY_BETWEEN_REQUESTS)

        if resp.status_code == 200:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(resp.text, encoding="utf-8")

        return resp.text, resp.status_code

    except requests.exceptions.Timeout:
        print(f"  TIMEOUT: {url}")
        return None, 408
    except requests.exceptions.RequestException as e:
        print(f"  ERROR ({type(e).__name__}): {url}")
        return None, 503


def check_robots_txt(base_url: str) -> str:
    """
    Check robots.txt and return what happened.
    Returns a human-readable description.
    """
    robots_url = base_url.rstrip("/") + "/robots.txt"
    try:
        resp = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code == 404:
            return "no robots file found (404)"
        elif resp.status_code == 200:
            lines = resp.text.strip().split("\n")[:10]
            preview = "\n".join(lines)
            return f"robots.txt found (200):\n{preview}"
        else:
            return f"robots.txt returned {resp.status_code}"
    except Exception as e:
        return f"error checking robots.txt: {e}"
