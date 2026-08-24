"""Authentication (concept: AUTHENTICATION).

- Register / login with PBKDF2-SHA256 password hashing (never stored plaintext).
- Opaque bearer tokens (256-bit random) stored hashed server-side; revocable.
- Protected routes reject missing / invalid / expired tokens with 401.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import db

SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected_hex = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), expected_hex)


def register(email: str, password: str, name: str) -> dict:
    """Create user + session. Returns {"user": ..., "token": ...}."""
    normalized = email.strip().lower()
    if db.query_one("SELECT id FROM users WHERE email = ?", (normalized,)):
        raise ValueError("email already registered")
    stored = hash_password(password)
    salt, pwhash = stored.split("$", 1)
    db.execute(
        "INSERT INTO users (email, name, salt, pwhash) VALUES (?, ?, ?, ?)",
        (normalized, name.strip(), salt, pwhash),
    )
    user = db.query_one(
        "SELECT id, email, name, created_at FROM users WHERE email = ?", (normalized,)
    )
    token = create_session(user["id"])
    return {"user": user, "token": token}


def login(email: str, password: str) -> dict | None:
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    if not row:
        return None
    stored = f"{row['salt']}${row['pwhash']}"
    if not verify_password(password, stored):
        return None
    user = {k: row[k] for k in ("id", "email", "name", "created_at")}
    return {"user": user, "token": create_session(user["id"])}


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_hash(token), user_id, expires),
    )
    return token


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    row = db.query_one(
        """
        SELECT u.id, u.email, u.name, u.created_at, s.expires_at
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """,
        (_hash(token),),
    )
    if not row:
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        return None
    if expires < datetime.now(timezone.utc):
        return None
    return {k: row[k] for k in ("id", "email", "name", "created_at")}


def revoke_session(token: str) -> None:
    db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()