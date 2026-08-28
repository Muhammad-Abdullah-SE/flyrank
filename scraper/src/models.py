"""Pydantic models for book record validation."""

from datetime import datetime
from pydantic import BaseModel, HttpUrl, field_validator


class RawBookRecord(BaseModel):
    """Raw record scraped from a book detail page."""
    title: str
    product_url: str
    price_text: str
    availability_text: str
    rating_text: str
    description: str | None
    source_page: str
    fetched_at: str


class BookRecord(BaseModel):
    """Cleaned and validated book record."""
    title: str
    product_url: str
    price_text: str
    price_gbp: float
    availability_text: str
    rating_text: str
    description: str | None
    source_page: str
    fetched_at: str

    @field_validator("product_url")
    @classmethod
    def must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError(f"product_url must start with https://, got: {v}")
        return v

    @field_validator("fetched_at")
    @classmethod
    def must_be_iso8601(cls, v: str) -> str:
        # Try to parse to confirm it's valid ISO 8601
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v
