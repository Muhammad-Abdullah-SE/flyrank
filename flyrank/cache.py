"""Caching logic (concept: CACHING).

Expensive results (ranked deal list, search queries) are stored in a TTL cache
and reused. Backed by both an in-memory dict and the SQLite kv_cache table, so
cache entries survive restarts. The API reports X-Cache: HIT / MISS headers.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from . import db

DEFAULT_TTL_SECONDS = 60
_pool: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def _normalize(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def get(key: str):
    now = time.time()
    with _lock:
        entry = _pool.get(key)
        if entry and entry[0] >= now:
            return json.loads(entry[1])
    # fall back to sqlite (survived a restart)
    row = db.query_one(
        "SELECT value, expires_at FROM kv_cache WHERE key = ? AND expires_at > ?",
        (key, datetime.now(timezone.utc).isoformat()),
    )
    if not row:
        return None
    value = json.loads(row["value"])
    # warm the memory pool so repeated calls are fast
    ttl = (datetime.fromisoformat(row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
    with _lock:
        _pool[key] = (time.time() + ttl, row["value"])
    return value


def set(key: str, value, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    payload = _normalize(value)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    with _lock:
        _pool[key] = (time.time() + ttl_seconds, payload)
    db.execute(
        """
        INSERT INTO kv_cache (key, value, expires_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires_at=excluded.expires_at
        """,
        (key, payload, expires),
    )


def delete(key: str) -> None:
    with _lock:
        _pool.pop(key, None)
    db.execute("DELETE FROM kv_cache WHERE key = ?", (key,))


def purge_expired() -> int:
    """Remove expired sqlite cache rows. Returns number removed."""
    with db.get_conn() as c:
        cur = c.execute(
            "DELETE FROM kv_cache WHERE expires_at <= ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        return cur.rowcount


def cached(key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS):
    """Decorator: cache the result of a function call under key."""

    def deco(fn):
        def wrapper(*args, **kwargs):
            k = f"{key}:{_normalize(args)}:{_normalize(kwargs)}"
            hit = get(k)
            if hit is not None:
                return hit, True
            result = fn(*args, **kwargs)
            set(k, result, ttl_seconds)
            return result, False

        return wrapper

    return deco