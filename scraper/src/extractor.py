"""HTML parsing and data extraction from Books to Scrape."""

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.models import RawBookRecord


RATING_MAP = {
    "One": "One",
    "Two": "Two",
    "Three": "Three",
    "Four": "Four",
    "Five": "Five",
}


def extract_book_links(catalogue_html: str, catalogue_url: str) -> list[str]:
    """Extract all book links from a catalogue page, return absolute URLs."""
    soup = BeautifulSoup(catalogue_html, "html.parser")
    articles = soup.select("article.product_pod")
    links = []
    for article in articles:
        a_tag = article.select_one("h3 a")
        if a_tag and a_tag.get("href"):
            absolute = urljoin(catalogue_url, a_tag["href"])
            links.append(absolute)
    return links


def find_next_page(catalogue_html: str, catalogue_url: str) -> str | None:
    """Find the 'next' page link. Returns absolute URL or None."""
    soup = BeautifulSoup(catalogue_html, "html.parser")
    next_link = soup.select_one("li.next a")
    if next_link and next_link.get("href"):
        return urljoin(catalogue_url, next_link["href"])
    return None


def extract_book_detail(html: str, product_url: str, source_page: str) -> RawBookRecord | None:
    """
    Extract raw fields from a book detail page.
    Returns None if the page cannot be parsed.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_el = soup.select_one("div.product_main h1")
    if not title_el:
        return None
    title = title_el.get_text(strip=True)

    # Price
    price_el = soup.select_one("div.product_main p.price_color")
    if not price_el:
        return None
    price_text = price_el.get_text(strip=True)

    # Availability
    avail_el = soup.select_one("div.product_main p.availability")
    availability_text = avail_el.get_text(strip=True) if avail_el else "unknown"

    # Rating — from class like "star-rating Three"
    rating_el = soup.select_one("p.star-rating")
    if rating_el:
        classes = rating_el.get("class", [])
        rating_text = ""
        for cls in classes:
            if cls in RATING_MAP:
                rating_text = cls
                break
        if not rating_text:
            rating_text = "unknown"
    else:
        rating_text = "unknown"

    # Description — in #product_description > p
    desc_el = soup.select_one("#product_description + p")
    if not desc_el:
        # Fallback: look for the paragraph after the product_description heading
        desc_el = soup.select_one("div#product_description ~ p")
    description = desc_el.get_text(strip=True) if desc_el else None

    fetched_at = datetime.now(timezone.utc).isoformat()

    return RawBookRecord(
        title=title,
        product_url=product_url,
        price_text=price_text,
        availability_text=availability_text,
        rating_text=rating_text,
        description=description,
        source_page=source_page,
        fetched_at=fetched_at,
    )


def normalize_price(price_text: str) -> float:
    """Turn '£51.77' into 51.77. Raises ValueError on bad input."""
    cleaned = price_text.replace("£", "").replace(",", "").strip()
    return float(cleaned)
