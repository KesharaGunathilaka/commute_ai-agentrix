"""Dummy ride backend — a deterministic stand-in for a real ride-hailing API.

Distance (and hence price) is random-but-deterministic by default, seeded
from the pickup/dropoff strings. For known real-world routes listed in
data/ride_distances.json, the curated distance is used instead — this keeps
demo-relevant journeys (e.g. a hospital last-mile hop) realistic instead of
an arbitrary 1.5-24km random distance.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

CURRENCY = "LKR"

_CURATED_DISTANCES_PATH = Path(__file__).parent / "data" / "ride_distances.json"


@lru_cache(maxsize=1)
def _load_curated_distances() -> list[dict]:
    try:
        with open(_CURATED_DISTANCES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _match_curated_route(pickup: str, dropoff: str) -> Optional[dict]:
    """Return the curated entry for (pickup, dropoff) if either name loosely
    matches one of its aliases in each direction, else None."""
    pickup_l = pickup.strip().lower()
    dropoff_l = dropoff.strip().lower()
    for entry in _load_curated_distances():
        from_hit = any(a.lower() in pickup_l or pickup_l in a.lower() for a in entry["from_aliases"])
        to_hit = any(a.lower() in dropoff_l or dropoff_l in a.lower() for a in entry["to_aliases"])
        if from_hit and to_hit:
            return entry
    return None

# vehicle_type -> pricing config
VEHICLES: dict[str, dict] = {
    "bike": {"label": "Bike", "base_fare": 60, "per_km": 45, "base_eta": 3},
    "tuk": {"label": "Tuk-tuk", "base_fare": 100, "per_km": 75, "base_eta": 5},
    "car": {"label": "Car", "base_fare": 220, "per_km": 120, "base_eta": 7},
}

# Free-text the user might type -> canonical vehicle key.
_SYNONYMS: dict[str, str] = {
    "bike": "bike", "motorbike": "bike", "motorcycle": "bike", "scooter": "bike",
    "tuk": "tuk", "tuktuk": "tuk", "trishaw": "tuk", "threewheeler": "tuk",
    "auto": "tuk", "rickshaw": "tuk",
    "car": "car", "cab": "car", "taxi": "car", "sedan": "car",
}

_DRIVERS = ["Nimal", "Kasun", "Saman", "Ruwan", "Tharindu", "Dilshan", "Pradeep", "Chamara"]


def normalize_vehicle(text: str) -> Optional[str]:
    """Map free text to a canonical vehicle key, or None if unrecognised."""
    key = "".join(ch for ch in text.lower() if ch.isalnum())
    return _SYNONYMS.get(key)


@dataclass(frozen=True)
class Quote:
    quote_id: str
    vehicle_type: str  # canonical key
    label: str
    available: bool
    distance_km: float
    price: int
    currency: str
    eta_min: int
    surge: float
    trip_duration_min: Optional[int] = None
    """Estimated ride duration for this trip, when known from curated route
    data. None for routes without a curated match (eta_min, by contrast, is
    always populated — it's "time until pickup", not trip length)."""


def quote_to_dict(q: Quote) -> dict:
    """JSON-friendly view handed to the LLM as a tool result."""
    return {
        "quote_id": q.quote_id,
        "vehicle_type": q.label,
        "available": q.available,
        "distance_km": q.distance_km,
        "price": q.price if q.available else None,
        "currency": q.currency,
        "eta_min": q.eta_min if q.available else None,
        "trip_duration_min": q.trip_duration_min if q.available else None,
        "surge_multiplier": q.surge,
    }


class RideService:
    """In-memory dummy ride service. One instance per process is fine."""

    def __init__(self, seed_salt: str = "") -> None:
        self._salt = seed_salt
        self._quotes: dict[str, Quote] = {}

    # deterministic seeding

    def _seed(self, pickup: str, dropoff: str, tag: str) -> tuple[random.Random, str]:
        raw = f"{self._salt}|{pickup.strip().lower()}|{dropoff.strip().lower()}|{tag}"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return random.Random(int(digest[:12], 16)), digest[:8]

    def _distance_km(self, pickup: str, dropoff: str) -> float:
        curated = _match_curated_route(pickup, dropoff)
        if curated:
            return curated["distance_km"]
        rng, _ = self._seed(pickup, dropoff, "__distance__")
        return round(rng.uniform(1.5, 24.0), 1)

    # public surface 

    def get_estimates(
        self, pickup: str, dropoff: str, vehicle_type: Optional[str] = None
    ) -> list[Quote]:
        """Return quotes for the requested vehicle type, or all types if omitted.

        Raises ValueError if a vehicle_type is given but not recognised.
        """
        if vehicle_type:
            canonical = normalize_vehicle(vehicle_type)
            if canonical is None:
                raise ValueError(
                    f"unknown vehicle type {vehicle_type!r}; supported: bike, tuk, car"
                )
            types = [canonical]
        else:
            types = list(VEHICLES)

        curated = _match_curated_route(pickup, dropoff)
        distance = curated["distance_km"] if curated else self._distance_km(pickup, dropoff)
        trip_duration = curated.get("typical_duration_min") if curated else None

        quotes: list[Quote] = []
        for vt in types:
            cfg = VEHICLES[vt]
            rng, h = self._seed(pickup, dropoff, vt)
            available = rng.random() > 0.25  # ~75% chance available
            surge = rng.choice([1.0, 1.0, 1.0, 1.2, 1.5])
            price = int(round((cfg["base_fare"] + cfg["per_km"] * distance) * surge))
            eta = cfg["base_eta"] + rng.randint(0, 8)
            quote = Quote(
                quote_id=f"{vt}-{h}",
                vehicle_type=vt,
                label=cfg["label"],
                available=available,
                distance_km=distance,
                price=price,
                currency=CURRENCY,
                eta_min=eta,
                surge=surge,
                trip_duration_min=trip_duration,
            )
            self._quotes[quote.quote_id] = quote
            quotes.append(quote)
        return quotes

    def get_quote(self, quote_id: str) -> Optional[Quote]:
        return self._quotes.get(quote_id)

    def book(self, quote_id: str) -> dict:
        """Confirm a booking for a previously issued quote.

        Raises ValueError if the quote is unknown or unavailable.
        """
        quote = self._quotes.get(quote_id)
        if quote is None:
            raise ValueError(f"unknown quote_id {quote_id!r}; request an estimate first")
        if not quote.available:
            raise ValueError(f"{quote.label} is not available for this route right now")

        rng = random.Random(f"{quote_id}|booking")
        return {
            "booking_id": f"BK{rng.randint(100000, 999999)}",
            "status": "confirmed",
            "vehicle_type": quote.label,
            "price": quote.price,
            "currency": quote.currency,
            "driver_name": rng.choice(_DRIVERS),
            "vehicle_plate": f"{rng.choice(['CAB', 'CAA', 'WP', 'NB'])}-{rng.randint(1000, 9999)}",
            "eta_min": quote.eta_min,
        }
