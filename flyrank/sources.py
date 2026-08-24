"""External data access layer.

FlyRank is a *backend* capstone, so the live-airline feed is simulated: this
module stands in for a flight API / scraping pipeline and returns small,
realistic price movements. All data used is seeded/public demo data.

Swap note: the program allows replacing 2 concepts with swaps; FlyRank does
NOT need swaps - it implements all 7 core concepts, so the simulated feed
keeps the build self-contained at $0 rather than depending on a paid API.
"""

from __future__ import annotations

import math
import random
import time

_ROUTES = [
    # (origin, destination, base_price, airlines)
    ("LHR", "JFK", 420, ["British Airways", "Delta", "American", "Virgin"]),
    ("JFK", "LHR", 430, ["British Airways", "Delta", "American", "Virgin"]),
    ("JFK", "LAX", 240, ["Delta", "United", "American", "JetBlue"]),
    ("LAX", "JFK", 245, ["Delta", "United", "American", "JetBlue"]),
    ("DXB", "LHR", 490, ["Emirates", "British Airways", "Qatar"]),
    ("LHR", "DXB", 495, ["Emirates", "British Airways", "Qatar"]),
    ("SIN", "SYD", 520, ["Singapore Airlines", "Qantas", "Jetstar"]),
    ("CDG", "NRT", 690, ["Air France", "JAL", "ANA"]),
    ("NRT", "CDG", 700, ["Air France", "JAL", "ANA"]),
    ("IST", "BKK", 430, ["Turkish", "Thai Airways", "Qatar"]),
    ("BKK", "SIN", 120, ["Thai Airways", "Singapore Airlines", "AirAsia"]),
    ("FRA", "ORD", 610, ["Lufthansa", "United", "American"]),
]


def _price_for(route_idx: int, airline_idx: int) -> float:
    """Deterministic-ish base price with a little per-airline spread."""
    base, airlines = _ROUTES[route_idx][2], _ROUTES[route_idx][3]
    spread = (airline_idx / max(len(airlines) - 1, 1) - 0.5) * 0.12
    jitter = math.sin((route_idx + 1) * (airline_idx + 3)) * 0.03
    return round(base * (1 + spread + jitter), 2)


def generate_catalog(rng: random.Random) -> list[dict]:
    """Generate the full demo deal catalog (used by the seed script)."""
    deals = []
    deal_id = 1
    for ri, (origin, dest, _, airlines) in enumerate(_ROUTES):
        for ai, airline in enumerate(airlines):
            price = _price_for(ri, ai)
            # 45-90 days out
            day = rng.randint(45, 90)
            deals.append(
                {
                    "id": deal_id,
                    "airline": airline,
                    "origin": origin,
                    "destination": dest,
                    "departure_date": f"2026-{10 + day // 30:02d}-{day % 30 + 1:02d}",
                    "price": price,
                    "currency": "USD",
                    "seats_left": rng.randint(0, 9) * 2 + rng.choice([2, 4, 6, 9]),
                }
            )
            deal_id += 1
    return deals


class LiveProvider:
    """Simulates polling a live flight feed for price updates."""

    def __init__(self, seed: int | None = None, volatility: float = 0.12):
        self.rng = random.Random(seed)
        self.volatility = volatility

    def fetch_price(self, deal: dict) -> dict:
        """Return an updated snapshot for one deal."""
        # occasional sharper drops (that's what makes it a "deal")
        if self.rng.random() < 0.18:
            change = -self.rng.uniform(0.15, 0.28)
        else:
            change = self.rng.gauss(0.0, self.volatility / 2)
        new_price = max(25.0, round(deal["price"] * (1 + change), 2))
        seats = max(0, deal.get("seats_left", 9) + self.rng.choice([-1, 0, 0, 1, 2]))
        return {"price": new_price, "seats_left": seats}

    def poll(self, deal: dict) -> dict:
        time.sleep(0.002)  # simulates network latency in a polite, fake way
        return self.fetch_price(deal)