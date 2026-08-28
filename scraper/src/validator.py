"""Validate and normalize raw records into clean BookRecords."""

from src.models import BookRecord, RawBookRecord
from src.extractor import normalize_price


def validate_and_normalize(raw: RawBookRecord) -> tuple[BookRecord | None, str | None]:
    """
    Attempt to convert a raw record into a validated BookRecord.
    Returns (book_record_or_none, error_reason_or_none).
    """
    try:
        price_gbp = normalize_price(raw.price_text)
    except (ValueError, TypeError) as e:
        return None, f"price parse error: {e}"

    try:
        record = BookRecord(
            title=raw.title,
            product_url=raw.product_url,
            price_text=raw.price_text,
            price_gbp=price_gbp,
            availability_text=raw.availability_text,
            rating_text=raw.rating_text,
            description=raw.description,
            source_page=raw.source_page,
            fetched_at=raw.fetched_at,
        )
        return record, None
    except Exception as e:
        return None, f"validation error: {e}"
