"""Database layer - SQLite persistence (concept: DATABASE).

Real persistence: every table survives a restart. Uses one SQLite file
(default: <project>/data/flyrank.db), WAL mode, per-thread connections.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DB_ENV = "FLYRANK_DB"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    salt        TEXT NOT NULL,
    pwhash      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    airline         TEXT NOT NULL,
    origin          TEXT NOT NULL,
    destination     TEXT NOT NULL,
    departure_date  TEXT NOT NULL,
    price           REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    seats_left      INTEGER NOT NULL DEFAULT 0,
    first_seen      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id),
    price       REAL NOT NULL,
    seats_left  INTEGER,
    checked_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlist (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    deal_id     INTEGER NOT NULL REFERENCES deals(id),
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, deal_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_logs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER,
    model              TEXT,
    endpoint           TEXT,
    prompt_tokens      INTEGER DEFAULT 0,
    completion_tokens  INTEGER DEFAULT 0,
    cost_usd           REAL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kv_cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);
"""

_local = threading.local()
_all_conns: set = set()
_registry_lock = threading.Lock()


def db_path() -> str:
    """Resolve the database file path (env override allowed for tests)."""
    env = os.environ.get(DB_ENV)
    if env:
        return env
    root = Path(__file__).resolve().parent.parent
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "flyrank.db")


def get_conn() -> sqlite3.Connection:
    """Thread-local SQLite connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(db_path(), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
        with _registry_lock:
            _all_conns.add(conn)
    return conn


def init_db() -> None:
    with get_conn() as c:
        c.executescript(SCHEMA)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    with get_conn() as c:
        row = c.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> int:
    """Execute a write statement, return lastrowid."""
    with get_conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def close_all() -> None:
    """Close every registered connection (all threads)."""
    with _registry_lock:
        conns = list(_all_conns)
        _all_conns.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None