"""Unit tests for the scraper — no network required."""

import os
import sys

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.extractor import extract_book_links, extract_book_detail, normalize_price, find_next_page
from src.validator import validate_and_normalize
from src.models import RawBookRecord


# ── Fixtures ──

CATALOGUE_HTML = """<!DOCTYPE html>
<html><body>
<div class="container-fluid">
  <div class="row">
    <article class="product_pod">
      <h3><a href="../a-light-in-the-attic_1000/index.html">A Light in the Attic</a></h3>
    </article>
    <article class="product_pod">
      <h3><a href="../tipping-the-velvet_999/index.html">Tipping the Velvet</a></h3>
    </article>
    <article class="product_pod">
      <h3><a href="../soumission_998/index.html">Soumission</a></h3>
    </article>
  </div>
  <ul class="pager">
    <li class="next"><a href="page-2.html">next</a></li>
  </ul>
</div>
</body></html>"""

BOOK_HTML = """<!DOCTYPE html>
<html><body>
<div class="product_main">
  <h1>A Light in the Attic</h1>
  <p class="price_color">£51.77</p>
  <p class="instock availability"><i class="icon-ok"></i> In stock (22 available)</p>
  <p class="star-rating Three"></p>
</div>
<div id="product_description">
  <h2>Product Description</h2>
</div>
<p>It's a dark and stormy night and something wonderful is about to happen.</p>
</body></html>"""

BOOK_HTML_NO_DESC = """<!DOCTYPE html>
<html><body>
<div class="product_main">
  <h1>No Description Book</h1>
  <p class="price_color">£12.50</p>
  <p class="instock availability"><i class="icon-ok"></i> In stock</p>
  <p class="star-rating Five"></p>
</div>
</body></html>"""

BOOK_HTML_EXTRA_WHITESPACE = """<!DOCTYPE html>
<html><body>
<div class="product_main">
  <h1>  Whitespace   Everywhere   Book  </h1>
  <p class="price_color">  £99.99  </p>
  <p class="instock availability"><i class="icon-ok"></i>   In stock   (3  available)  </p>
  <p class="star-rating One"></p>
</div>
<div id="product_description">
  <h2>Product Description</h2>
</div>
<p>  Lots   of   spaces   here.  </p>
</body></html>"""

CATALOGUE_BASE = "https://books.toscrape.com/catalogue/page-1.html"


def test_extract_book_links():
    links = extract_book_links(CATALOGUE_HTML, CATALOGUE_BASE)
    assert len(links) == 3
    # urljoin resolves ../ relative to the base URL
    assert "a-light-in-the-attic_1000/index.html" in links[0]
    assert "tipping-the-velvet_999/index.html" in links[1]
    assert "soumission_998/index.html" in links[2]
    # All must be absolute
    for link in links:
        assert link.startswith("https://")


def test_extract_book_links_dedup():
    # Add a duplicate book to the HTML
    html_dup = CATALOGUE_HTML.replace(
        '</article>',
        '</article><article class="product_pod"><h3><a href="../tipping-the-velvet_999/index.html">Dup</a></h3></article>',
        1  # only replace the first occurrence
    )
    links = extract_book_links(html_dup, CATALOGUE_BASE)
    assert len(links) == 4
    # Dedup is handled in main.py, not in extractor


def test_extract_book_detail():
    raw = extract_book_detail(BOOK_HTML, "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html", CATALOGUE_BASE)
    assert raw is not None
    assert raw.title == "A Light in the Attic"
    assert raw.price_text == "£51.77"
    assert "In stock" in raw.availability_text
    assert raw.rating_text == "Three"
    assert raw.description is not None


def test_missing_description():
    raw = extract_book_detail(BOOK_HTML_NO_DESC, "https://example.com/book", CATALOGUE_BASE)
    assert raw is not None
    assert raw.description is None


def test_extra_whitespace():
    raw = extract_book_detail(BOOK_HTML_EXTRA_WHITESPACE, "https://example.com/book", CATALOGUE_BASE)
    assert raw is not None
    assert raw.title == "Whitespace   Everywhere   Book"
    assert "In stock" in raw.availability_text


def test_normalize_price():
    assert normalize_price("£51.77") == 51.77
    assert normalize_price("  £12.50  ") == 12.50
    assert normalize_price("£1,234.56") == 1234.56


def test_normalize_price_bad():
    with pytest.raises(ValueError):
        normalize_price("free")


def test_validate_good_record():
    raw = RawBookRecord(
        title="Test Book",
        product_url="https://books.toscrape.com/catalogue/test_1/index.html",
        price_text="£25.00",
        availability_text="In stock (5 available)",
        rating_text="Three",
        description="A test book.",
        source_page=CATALOGUE_BASE,
        fetched_at="2026-08-27T17:00:00+00:00",
    )
    record, error = validate_and_normalize(raw)
    assert record is not None
    assert error is None
    assert record.price_gbp == 25.0


def test_validate_rejects_http():
    raw = RawBookRecord(
        title="Bad URL Book",
        product_url="http://books.toscrape.com/book",
        price_text="£10.00",
        availability_text="In stock",
        rating_text="One",
        description=None,
        source_page=CATALOGUE_BASE,
        fetched_at="2026-08-27T17:00:00+00:00",
    )
    record, error = validate_and_normalize(raw)
    assert record is None
    assert "https" in error.lower()


def test_find_next_page():
    next_url = find_next_page(CATALOGUE_HTML, CATALOGUE_BASE)
    assert next_url == "https://books.toscrape.com/catalogue/page-2.html"


def test_find_next_page_none():
    html_no_next = CATALOGUE_HTML.replace('<li class="next">', '<li class="">')
    assert find_next_page(html_no_next, CATALOGUE_BASE) is None
