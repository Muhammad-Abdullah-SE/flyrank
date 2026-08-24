"""Background & cron jobs (concept: BACKGROUND/CRON JOBS).

Two complementary mechanisms:

1. In-process scheduler thread (started with the server): matches a cron
   expression every tick and runs due jobs off the request path.
2. On-demand trigger API (POST /api/jobs/refresh -> 202) runs the same job in
   a background thread, so slow work never blocks a request.

The daily job: poll the (simulated) live provider for every deal, store the
snapshot in price_history, update the deal, and log the run in the jobs table.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from . import db, sources

POLL_INTERVAL_SECONDS = 15  # scheduler tick

JOB_DEFS = [
    {
        "name": "daily_price_refresh",
        "cron": "30 8 * * *",  # 08:30 every day, no request involved
        "func": "refresh_prices",
        "description": "Poll the live provider and refresh every deal price.",
    }
]


def _cron_matches(expr: str, now: datetime) -> bool:
    minute, hour, dom, month, dow = expr.split()

    def matches(field: str, value: int) -> bool:
        if field == "*":
            return True
        if field.startswith("*/"):
            step = int(field[2:])
            return value % step == 0
        if "," in field:
            return value in {int(x) for x in field.split(",")}
        return int(field) == value

    return (
        matches(minute, now.minute)
        and matches(hour, now.hour)
        and matches(dom, now.day)
        and matches(month, now.month)
        and matches(dow, now.weekday() + 1)  # cron: 0-6 (Sun=0); Python: Mon=0
    )


def refresh_prices() -> dict:
    """Refresh all deal prices from the live provider (one job run)."""
    job_id = db.execute(
        "INSERT INTO jobs (name, status) VALUES ('daily_price_refresh', 'running')"
    )
    provider = sources.LiveProvider(seed=int(time.time()) % 100000)
    deals = db.query("SELECT * FROM deals")
    try:
        updated = 0
        for deal in deals:
            snapshot = provider.poll(deal)
            db.execute(
                "UPDATE deals SET price = ?, seats_left = ?, last_seen = datetime('now') WHERE id = ?",
                (snapshot["price"], snapshot["seats_left"], deal["id"]),
            )
            db.execute(
                "INSERT INTO price_history (deal_id, price, seats_left) VALUES (?, ?, ?)",
                (deal["id"], snapshot["price"], snapshot["seats_left"]),
            )
            updated += 1
        detail = f"refreshed {updated} deals"
        db.execute(
            "UPDATE jobs SET status = 'ok', detail = ?, finished_at = datetime('now') WHERE id = ?",
            (detail, job_id),
        )
        return {"job_id": job_id, "detail": detail}
    except Exception as exc:  # keep the job table honest on failure
        db.execute(
            "UPDATE jobs SET status = 'error', detail = ?, finished_at = datetime('now') WHERE id = ?",
            (str(exc), job_id),
        )
        raise


def _run_scheduled_jobs() -> None:
    """Run any cron job that is due and has not already run today."""
    now = datetime.now(timezone.utc)
    for job in JOB_DEFS:
        already_ran_today = db.query_one(
            "SELECT id FROM jobs WHERE name = ? AND status = 'ok' AND date(started_at) = date('now')",
            (job["name"],),
        )
        if already_ran_today:
            continue
        if _cron_matches(job["cron"], now):
            threading.Thread(target=refresh_prices, daemon=True).start()


class SchedulerThread(threading.Thread):
    """Background thread that ticks every POLL_INTERVAL_SECONDS."""

    def __init__(self):
        super().__init__(daemon=True, name="flyrank-scheduler")
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                _run_scheduled_jobs()
            except Exception:
                pass  # never let the scheduler die
            self._stop.wait(POLL_INTERVAL_SECONDS)


def recent_jobs(limit: int = 10) -> list[dict]:
    return db.query(
        "SELECT id, name, status, detail, started_at, finished_at FROM jobs "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def run_forever() -> None:
    """CLI entry: python -m flyrank.scheduler (or scripts/run_cron.py)."""
    print("FlyRank scheduler started. Ctrl+C to stop.")
    sched = SchedulerThread()
    sched.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping scheduler.")
        sched.stop()


if __name__ == "__main__":
    run_forever()