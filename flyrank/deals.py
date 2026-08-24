"""Deal ranking engine + search.

FlyRank's core value: instead of a flat list of flights, every deal gets a
0-100 VALUE SCORE that blends price competitiveness (vs route average),
urgency (seats left) and freshness. Search is a small, validated query layer
on top - this is what the cache protects.
"""

from __future__ import annotations

from . import cache, db

SORTS = {"value": "value", "price": "price", "departure": "departure_date"}


def _route_averages():
    rows = db.query(
        """
        SELECT origin, destination, AVG(price) AS avg_price, COUNT(*) AS n
        FROM deals GROUP BY origin, destination
        """
    )
    return {(r["origin"], r["destination"]): r for r in rows}


def score_deal(deal: dict, avgs: dict) -> dict:
    key = (deal["origin"], deal["destination"])
    avg = avgs.get(key, {})
    avg_price = avg.get("avg_price") or deal["price"]
    ratio = deal["price"] / avg_price  # < 1 means below route average
    # 60% of the score comes from price competitiveness
    price_score = max(0.0, min(1.0, 1.15 - ratio)) * 60
    # 25% urgency: fewer seats left = hotter deal
    urgency = max(0.0, min(1.0, 1.0 - deal["seats_left"] / 20.0)) * 25
    # 15% freshness bonus (recently seen deals ranked slightly higher)
    detail = db.query_one(
        "SELECT (julianday('now') - julianday(last_seen)) AS days FROM deals WHERE id = ?",
        (deal["id"],),
    )
    days = detail["days"] if detail else 0.0
    freshness = max(0.0, min(1.0, 1.0 - days / 7.0)) * 15
    value = round(price_score + urgency + freshness, 1)
    out = dict(deal)
    out["value_score"] = value
    out["vs_route_avg"] = round((1 - ratio) * 100, 1)
    return out


def rank_deals(rows: list[dict]) -> list[dict]:
    avgs = _route_averages()
    scored = [score_deal(r, avgs) for r in rows]
    scored.sort(key=lambda d: d["value_score"], reverse=True)
    for i, d in enumerate(scored, start=1):
        d["rank"] = i
    return scored


def _deal_rows(filters: dict | None = None) -> list[dict]:
    sql = "SELECT * FROM deals WHERE 1=1"
    params: list = []
    f = filters or {}
    if f.get("origin"):
        sql += " AND UPPER(origin) = UPPER(?)"
        params.append(f["origin"])
    if f.get("destination"):
        sql += " AND UPPER(destination) = UPPER(?)"
        params.append(f["destination"])
    if f.get("max_price") is not None:
        sql += " AND price <= ?"
        params.append(f["max_price"])
    if f.get("airline"):
        sql += " AND UPPER(airline) LIKE UPPER(?)"
        params.append(f"%{f['airline']}%")
    return db.query(sql, tuple(params))


def list_deals(filters: dict | None = None, sort: str = "value", limit: int = 50) -> tuple[list[dict], bool]:
    """Cached ranked deal list. Returns (deals, cache_hit)."""
    filters = filters or {}

    def _ranked(f):
        return rank_deals(_deal_rows(f))

    result, hit = cache.cached("deals_list")(_ranked)(filters)
    return _sort_and_limit(result, sort, limit), hit


def search_deals(query: str, limit: int = 20) -> tuple[list[dict], bool]:
    """Free-text search over origin/destination/airline. Cached."""
    q = query.strip().upper()
    if not q:
        return [], False
    rows = db.query(
        """
        SELECT * FROM deals
        WHERE UPPER(origin) LIKE ? OR UPPER(destination) LIKE ? OR UPPER(airline) LIKE ?
        """,
        (f"%{q}%", f"%{q}%", f"%{q}%"),
    )

    def _ranked(r):
        return rank_deals(r)

    result, hit = cache.cached("deals_search")(_ranked)(rows)
    return _sort_and_limit(result, "value", limit), hit


def _sort_and_limit(scored: list[dict], sort: str, limit: int) -> list[dict]:
    key = SORTS.get(sort, "value")
    if sort == "price":
        scored = sorted(scored, key=lambda d: d["price"])
    elif sort == "departure":
        scored = sorted(scored, key=lambda d: d["departure_date"])
    return scored[: int(limit)]


def get_deal(deal_id: int) -> dict | None:
    return db.query_one("SELECT * FROM deals WHERE id = ?", (deal_id,))


def watch_deal(user_id: int, deal_id: int) -> None:
    if not get_deal(deal_id):
        raise ValueError("deal not found")
    db.execute(
        "INSERT OR IGNORE INTO watchlist (user_id, deal_id) VALUES (?, ?)",
        (user_id, deal_id),
    )


def unwatch_deal(user_id: int, deal_id: int) -> None:
    db.execute("DELETE FROM watchlist WHERE user_id = ? AND deal_id = ?", (user_id, deal_id))


def watchlist(user_id: int) -> list[dict]:
    rows = db.query(
        """
        SELECT d.* FROM watchlist w JOIN deals d ON d.id = w.deal_id
        WHERE w.user_id = ? ORDER BY w.added_at DESC
        """,
        (user_id,),
    )
    return rank_deals(rows)