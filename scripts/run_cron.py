"""Run the cron scheduler as its own process (background jobs concept).

Usage:
    python scripts/run_cron.py          # run forever (daily 08:30 refresh)
    python scripts/run_cron.py --once   # run the refresh once, then exit

Same code path as the in-process scheduler thread started with the server.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flyrank import db, scheduler  # noqa: E402


def main() -> None:
    if "--once" in sys.argv:
        db.init_db()
        result = scheduler.refresh_prices()
        print(f"[cron] one-shot run finished: {result}")
        return
    scheduler.run_forever()


if __name__ == "__main__":
    main()