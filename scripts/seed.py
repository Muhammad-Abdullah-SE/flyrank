"""Seed the demo database: user, deal catalog, price history, first job run.

Usage:  python scripts/seed.py
        python -m scripts.seed
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flyrank import auth, db, sources  # noqa: E402

SEED = 42
DEMO_EMAIL = "demo@flyrank.dev"
DEMO_PASSWORD = "demo1234"


def seed() -> None:
    db.init_db()
    rng = random.Random(SEED)

    # 1. demo user
    existing = db.query_one("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,))
    if not existing:
        auth.register(DEMO_EMAIL, DEMO_PASSWORD, "Demo Intern")
        print(f"[seed] created demo user {DEMO_EMAIL} / {DEMO_PASSWORD}")
    else:
        print("[seed] demo user already exists")

    # 2. deal catalog
    count = db.query_one("SELECT COUNT(*) AS n FROM deals")["n"]
    if count == 0:
        catalog = sources.generate_catalog(rng)
        for deal in catalog:
            db.execute(
                """
                INSERT INTO deals (airline, origin, destination, departure_date,
                                    price, currency, seats_left)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (deal["airline"], deal["origin"], deal["destination"],
                 deal["departure_date"], deal["price"], deal["currency"], deal["seats_left"]),
            )
        print(f"[seed] inserted {len(catalog)} deals")
    else:
        print(f"[seed] {count} deals already present, skipping catalog insert")

    # 3. price history (one week of snapshots so the report has context)
    hist = db.query_one("SELECT COUNT(*) AS n FROM price_history")["n"]
    if hist == 0:
        deals = db.query("SELECT id, price FROM deals")
        provider = sources.LiveProvider(seed=SEED)
        for deal in deals:
            price = deal["price"]
            for _ in range(7):
                snap = provider.fetch_price({"price": price})
                price = snap["price"]
                db.execute(
                    "INSERT INTO price_history (deal_id, price, seats_left) VALUES (?, ?, ?)",
                    (deal["id"], price, snap["seats_left"]),
                )
        print("[seed] inserted price history snapshots")
    else:
        print(f"[seed] {hist} price snapshots already present, skipping")

    # 4. one recorded job run so the Jobs screen is not empty
    job = db.query_one("SELECT id FROM jobs LIMIT 1")
    if not job:
        db.execute(
            "INSERT INTO jobs (name, status, detail) VALUES ('seed', 'ok', 'demo data seeded')"
        )
        print("[seed] recorded seed job entry")

    print("\nFlyRank ready.")
    print(f"  Start the server:  python -m flyrank.app")
    print(f"  Open:              http://127.0.0.1:8000")
    print(f"  Login:             {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()