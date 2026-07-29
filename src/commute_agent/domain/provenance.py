"""
Where a value came from, and whether anyone checked it.

Three fields, carried on routes, on legs, and on fares:

    source          the dataset or API the value came from
    verified        has this source been checked against an authority?
    captured_date   ISO date the local data was captured, when it is local

`verified` is a claim about *this repository's* validation work, not about how
trustworthy the upstream feed is. Google Maps transit times are live and are
the best times the system has, but nobody here has checked them against a
published Sri Lanka Railways or NTC timetable, so they are `verified=False`.
Marking them True would make the badge decorative — which is the failure this
exists to prevent.

On the data present today every source is unverified: the audit found no
validation artefact anywhere in the repository, and `data/fares.json` says so
about itself. The mechanism is here so that the day a dataset *is* checked, the
badge changes on its own rather than needing new UI.

There is deliberately no registry and no lookup layer. Nodes stamp the constant
that describes what they did.
"""

from __future__ import annotations

from typing import Any, Optional

# Live transit routing. Accurate as feeds go; not independently checked here.
SOURCE_GOOGLE_MAPS = "google_maps"

# data/bus_timetables.json — hand-assembled, no source recorded, and at least
# 9 of its 20 records carry a journey time that contradicts their route name.
SOURCE_LOCAL_TIMETABLE = "local_timetable"

# Reserved for data actually transcribed from these authorities. Nothing in the
# repository qualifies yet; they exist so a future ingest has a name to use.
SOURCE_SRI_LANKA_RAILWAYS = "sri_lanka_railways"
SOURCE_NTC = "ntc"

# Randomly generated stand-ins: ride prices, ride availability, bookings.
SOURCE_SIMULATED = "simulated"

# Modelled from data/fares.json, whose own `verified` flag is false.
SOURCE_FARE_MODEL = "fare_model"

PROVENANCE_FIELDS = ("source", "verified", "captured_date")


def provenance(
    source: Optional[str],
    verified: bool = False,
    captured_date: Optional[str] = None,
) -> dict[str, Any]:
    """The three fields as a dict, ready to splat onto a route or leg."""
    return {"source": source, "verified": verified, "captured_date": captured_date}


def stamp_route_provenance(
    route: dict,
    source: Optional[str],
    verified: bool = False,
    captured_date: Optional[str] = None,
    stamp_legs: bool = True,
) -> dict:
    """Return a copy of `route` carrying provenance, legs included.

    Never mutates the input: nodes hand these dicts straight into LangGraph
    state, and in-place edits would reach state the node hasn't returned yet.
    """
    marks = provenance(source, verified, captured_date)
    stamped = {**route, **marks}
    if stamp_legs and route.get("legs"):
        stamped["legs"] = [{**leg, **marks} for leg in route["legs"]]
    return stamped


def is_verified(item: Optional[dict]) -> bool:
    """True only for an explicit verified flag. Absent means unverified."""
    return bool(item and item.get("verified") is True)


def summarise_provenance(items: list[dict]) -> str:
    """Collapse many legs' verification state into one word for a plan.

    'verified' requires every leg to be verified — one unchecked leg makes the
    whole itinerary unchecked, because acting on it means acting on that leg.
    """
    if not items:
        return "estimated"
    verified_count = sum(1 for item in items if is_verified(item))
    if verified_count == len(items):
        return "verified"
    if verified_count == 0:
        return "estimated"
    return "partially_verified"
