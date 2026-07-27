"""
Fare estimation for transit routes.

Sri Lanka publishes no machine-readable fare feed: bus fares come from the
NTC's stage-based schedule, rail fares from SLR's distance-and-class tariff.
Both are modelled here as a minimum fare covering an initial distance band
plus a per-km rate, with a multiplier per comfort class. The rates live in
`data/fares.json` so they can be corrected without touching this code.

Every figure this module produces is an ESTIMATE and is labelled as such all
the way to the UI. `data/fares.json` carries a `verified` flag; while it is
false the reported range is deliberately widened, so an unverified estimate
never presents itself with more precision than it has earned.

Distance comes from the per-leg `distance_m` that google_maps_tool records.
A route with no leg distances (one sourced from the curated timetable JSON
rather than live routing) gets no estimate at all rather than a guessed one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import TransitMode

logger = get_logger(__name__)

# Below this, a "route" is a rounding artefact rather than a journey — Maps
# occasionally emits a sub-100m transit hop at a transfer point.
_MIN_CHARGEABLE_KM = 0.1


@lru_cache(maxsize=1)
def _load_fare_config() -> Optional[dict]:
    """Read data/fares.json once, or None if it's missing or malformed.

    Returning None (rather than raising) keeps fares strictly additive: the
    graph still plans journeys perfectly well without them.
    """
    path = get_settings().fares_path
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.warning("Fare config not found at %s — fares disabled.", path)
        return None
    except json.JSONDecodeError as exc:
        logger.error("Fare config at %s is not valid JSON: %s — fares disabled.", path, exc)
        return None

    if "bus" not in config or "train" not in config:
        logger.error("Fare config missing 'bus'/'train' sections — fares disabled.")
        return None
    return config


def route_distance_km(route: dict) -> Optional[float]:
    """Total chargeable transit distance, or None when it can't be determined.

    Sums the transit legs only. A trailing walk to the destination isn't
    chargeable, and `last_mile_distance_m` is tracked separately for the
    ride-hailing fallback.
    """
    legs = route.get("legs") or []
    metres = sum(leg.get("distance_m") or 0 for leg in legs)
    if metres <= 0:
        return None
    return metres / 1000


def _fare_for_class(
    distance_km: float,
    scheme: dict,
    multiplier: float,
) -> int:
    """Fare for one comfort class, rounded to the nearest rupee."""
    covered = scheme.get("minimum_covers_km", 0)
    minimum = scheme.get("minimum_fare", 0)
    per_km = scheme.get("per_km", 0)

    chargeable_beyond = max(0.0, distance_km - covered)
    base = minimum + per_km * chargeable_beyond
    return int(round(base * multiplier))


def estimate_fare(route: dict) -> Optional[dict]:
    """
    Estimate the fare for one route.

    Returns None when no estimate is defensible — no fare config, or a route
    with no usable distance. Callers treat that as "no fare shown", never as
    "free".

    The returned dict is what reaches the UI:

        amount          cheapest class — the headline figure, and what
                        cost-based ranking sorts on
        classes         per-class breakdown, cheapest first. The spread here
                        is real price variation ("3rd class vs 1st"), not
                        uncertainty.
        uncertainty_pct how far the rates themselves might be off, kept
                        separate from the class spread so the UI can say
                        "roughly LKR 163, ±25%" rather than quoting one
                        blurred band that conflates the two.
        estimated       always True; never present these as published tariffs
        verified        whether the underlying rates have been checked
    """
    config = _load_fare_config()
    if config is None:
        return None

    distance_km = route_distance_km(route)
    if distance_km is None or distance_km < _MIN_CHARGEABLE_KM:
        return None

    is_train = route.get("transit_mode") == TransitMode.TRAIN.value
    scheme = config["train"] if is_train else config["bus"]

    classes: list[dict[str, Any]] = []
    for entry in scheme.get("classes", []):
        classes.append({
            "id": entry.get("id", ""),
            "label": entry.get("label", ""),
            "amount": _fare_for_class(distance_km, scheme, entry.get("multiplier", 1.0)),
        })

    if not classes:
        return None

    classes.sort(key=lambda c: c["amount"])

    # Two distinct things, deliberately not merged:
    #   the class spread is real ("3rd class costs less than 1st"),
    #   the uncertainty is how wrong the rate table itself might be.
    # Blending them into one low–high band would report a confident price
    # range and a shrug as if they were the same quantity.
    verified = bool(config.get("verified", False))
    uncertainty = 0.0 if verified else float(config.get("unverified_range_pct", 0.25))

    return {
        "currency": config.get("currency", "LKR"),
        "amount": classes[0]["amount"],
        "max_amount": classes[-1]["amount"],
        "distance_km": round(distance_km, 1),
        "classes": classes,
        "uncertainty_pct": uncertainty,
        "mode": "train" if is_train else "bus",
        "estimated": True,
        "verified": verified,
        "source": config.get("source", ""),
    }


def cheapest_fare(route: dict) -> Optional[int]:
    """The figure cost-based ranking sorts on, or None if unknown."""
    fare = route.get("fare_estimate")
    if not fare:
        return None
    amount = fare.get("amount")
    return amount if isinstance(amount, int) else None
