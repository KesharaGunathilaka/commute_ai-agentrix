"""
Simulated ride booking.

**Nothing here books anything.** `ride_service.py` is a dummy: distance for an
uncurated route is `rng.uniform(1.5, 24.0)`, availability is a coin flip, and
surge is drawn from a list. A real booking needs a PickMe or Uber partner API
and a commercial agreement, neither of which exists.

Every object this module produces therefore carries `simulated=True` and a
`disclaimer` string, and both travel over the wire. The flag originates here,
at the point the fabricated numbers are made, rather than being added by the
frontend — a client that forgets to render the badge should still be handed
data that says plainly what it is.

Driver names and vehicle plates are deliberately *not* included even though
`RideService.book()` offers them. A price with a caveat is a minor liability;
a confirmation naming a driver and a number plate reads as a completed
commercial transaction, and no badge makes that a good idea.

The one figure here that is not fabricated is the arithmetic:
`now + eta_min + ride_duration_min` is computed in Python and is what the
onward journey is planned from.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from commute_agent.core.logging import get_logger
from commute_agent.domain.provenance import SOURCE_SIMULATED

logger = get_logger(__name__)

# ride_service.py lives at the repo root, not in the package — same import
# dance uber.py does.
_REPO_ROOT = Path(__file__).parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DISCLAIMER = "Simulated booking · production requires PickMe/Uber partner API."

# Used only when a route has no curated duration. Roughly Colombo arterial
# traffic. Stated as a constant so the derived minutes are traceable to an
# assumption rather than appearing from nowhere.
_ASSUMED_AVG_SPEED_KMH = 24.0


class RideUnavailableError(Exception):
    """The requested class isn't available. Carries what is."""

    def __init__(self, message: str, available_classes: list[str]) -> None:
        super().__init__(message)
        self.available_classes = available_classes


class UnknownRideClassError(Exception):
    """Free text that matched no vehicle type."""


@dataclass(frozen=True)
class SimulatedBooking:
    booking_ref: str
    pickup: str
    dropoff: str
    ride_class: str
    ride_class_label: str

    eta_min: int
    """Minutes until pickup — time until the ride arrives, not trip length."""

    ride_duration_min: int
    """Minutes in the vehicle. Curated where a real distance is known,
    otherwise derived from distance at _ASSUMED_AVG_SPEED_KMH."""

    price: int
    currency: str
    distance_km: float
    booked_at: str
    """ISO timestamp the booking was made — the anchor for the time offset."""

    simulated: bool = True
    disclaimer: str = DISCLAIMER
    source: str = SOURCE_SIMULATED
    verified: bool = False

    def arrival_offset_min(self) -> int:
        """Minutes from booking until the ride reaches the drop-off.

        The single most important number in this feature. An onward journey
        planned from `now` rather than from here will happily recommend a
        connecting service that leaves before the ride has arrived.
        """
        return self.eta_min + self.ride_duration_min

    def replan_departure_at(self) -> datetime:
        return datetime.fromisoformat(self.booked_at) + timedelta(
            minutes=self.arrival_offset_min()
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ride_class_options(pickup: str, dropoff: str) -> list[dict[str, Any]]:
    """Every vehicle class for a segment, with availability and price.

    Lets the UI offer only what will succeed, so booking stays a single tap
    instead of a pick-then-fail. Deterministic for a given segment: the dummy
    seeds its RNG from the pickup and drop-off strings, so the same leg always
    reports the same availability within a run.
    """
    from ride_service import RideService, VEHICLES  # noqa: PLC0415

    quotes = {q.vehicle_type: q for q in RideService().get_estimates(pickup, dropoff)}
    return [
        {
            "ride_class": key,
            "label": config["label"],
            "available": bool(quotes[key].available) if key in quotes else False,
            "price": quotes[key].price if key in quotes and quotes[key].available else None,
            "eta_min": quotes[key].eta_min if key in quotes and quotes[key].available else None,
            "distance_km": quotes[key].distance_km if key in quotes else None,
            "currency": quotes[key].currency if key in quotes else "LKR",
            "simulated": True,
            "disclaimer": DISCLAIMER,
        }
        for key, config in VEHICLES.items()
    ]


def _ride_duration_min(distance_km: float, curated_duration: Optional[int]) -> int:
    """Trip length: curated where known, else distance over an assumed speed."""
    if curated_duration:
        return int(curated_duration)
    return max(1, round(distance_km / _ASSUMED_AVG_SPEED_KMH * 60))


def _booking_ref(pickup: str, dropoff: str, ride_class: str, booked_at: str) -> str:
    """Stable for a given booking, distinct between two bookings of one leg.

    Prefixed SIM- so the reference itself says what it is, even pasted out of
    context into a bug report or a screenshot.
    """
    raw = f"{pickup}|{dropoff}|{ride_class}|{booked_at}".lower()
    return f"SIM-{hashlib.sha256(raw.encode()).hexdigest()[:6].upper()}"


def simulate_booking(
    pickup: str,
    dropoff: str,
    ride_class: str,
    now: Optional[datetime] = None,
) -> SimulatedBooking:
    """
    Produce a simulated booking for one segment.

    Raises UnknownRideClassError for an unrecognised class, and
    RideUnavailableError — naming the classes that *are* available — when the
    dummy backend's availability flip comes up short for this one.

    `now` is injectable so the time arithmetic can be tested against a fixed
    clock rather than the wall clock.
    """
    from ride_service import RideService, normalize_vehicle  # noqa: PLC0415

    canonical = normalize_vehicle(ride_class)
    if canonical is None:
        raise UnknownRideClassError(
            f"Unknown ride class {ride_class!r}. Supported: bike, tuk, car."
        )

    service = RideService()
    all_quotes = service.get_estimates(pickup, dropoff)
    quote = next((q for q in all_quotes if q.vehicle_type == canonical), None)

    if quote is None or not quote.available:
        available = [q.vehicle_type for q in all_quotes if q.available]
        raise RideUnavailableError(
            f"No {canonical} available for this segment right now.", available
        )

    booked_at = (now or datetime.now()).replace(microsecond=0)
    booking = SimulatedBooking(
        booking_ref=_booking_ref(pickup, dropoff, canonical, booked_at.isoformat()),
        pickup=pickup,
        dropoff=dropoff,
        ride_class=canonical,
        ride_class_label=quote.label,
        eta_min=quote.eta_min,
        ride_duration_min=_ride_duration_min(quote.distance_km, quote.trip_duration_min),
        price=quote.price,
        currency=quote.currency,
        distance_km=quote.distance_km,
        booked_at=booked_at.isoformat(),
    )

    logger.info(
        "Simulated booking %s: %r -> %r by %s, pickup in %d min, ride %d min, "
        "onward planning from %s",
        booking.booking_ref, pickup, dropoff, canonical,
        booking.eta_min, booking.ride_duration_min,
        booking.replan_departure_at().strftime("%H:%M"),
    )
    return booking


# ── Place matching ────────────────────────────────────────────────────────────

# Stripped before comparing, so "Kandy" and "Kandy Railway Station" are one
# place. Longest first: "railway station" must go before "station".
_PLACE_NOISE = (
    "railway station", "train station", "bus stand", "bus stop", "bus station",
    "railway", "station", "junction",
)


def normalise_place(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in (name or "").lower())
    cleaned = " ".join(cleaned.split())
    for noise in _PLACE_NOISE:
        cleaned = cleaned.replace(noise, " ")
    return " ".join(cleaned.split())


def same_place(left: str, right: str) -> bool:
    """Whether two stop names denote the same place.

    Google Maps returns "Fort Railway station" where the commuter typed
    "Colombo Fort", so an exact match would miss constantly. Containment is
    gated on three characters to stop a stray token making two unrelated
    places equal.

    Used to decide the terminal case — drop-off *is* the destination, so there
    is nothing left to plan. Getting this wrong in the permissive direction
    skips a replan the commuter wanted; wrong in the strict direction plans a
    journey from a place to itself. Neither is silent: the response says
    whether a replan ran.
    """
    a, b = normalise_place(left), normalise_place(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) >= 3 and len(b) >= 3 and (a in b or b in a)


def segment_key(pickup: str, dropoff: str) -> str:
    """Identity of a bookable segment, for the already-booked guard."""
    return f"{normalise_place(pickup)}->{normalise_place(dropoff)}"
