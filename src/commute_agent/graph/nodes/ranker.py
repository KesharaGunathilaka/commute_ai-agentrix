"""
Ranker node — selects the top-5 routes after bus_rag and train_rag enrichment.

Hard constraints always come first, whatever the commuter is optimising for:

1. Routes arriving before expected_arrival_time rank above those that miss it.
2. Routes departing at or after requested_time rank above earlier ones.

A route that misses the deadline is not a useful answer at any price, so
`optimise_for` only ever reorders within those two constraints:

  fastest         earliest arrival, then fewest legs
  cheapest        lowest estimated fare, then earliest arrival
  fewest_changes  fewest legs, then earliest arrival
  None (balanced) fewest legs, then train-over-bus, then earliest arrival
                  — the original behaviour, unchanged

Routes with no fare estimate sort last under `cheapest` rather than first:
unknown cost must not masquerade as zero cost.

Writes:
  candidate_route  — the single best route
  candidate_routes — full enriched list (for UI "all options" expander)
  ranked_routes    — top-5 after applying criteria (subset of candidate_routes)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import TransitMode
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)

NODE_NAME = "ranker"

_MAX_RANKED = 5

OPTIMISE_FASTEST = "fastest"
OPTIMISE_CHEAPEST = "cheapest"
OPTIMISE_FEWEST_CHANGES = "fewest_changes"

VALID_OPTIMISATIONS = {OPTIMISE_FASTEST, OPTIMISE_CHEAPEST, OPTIMISE_FEWEST_CHANGES}


def normalise_optimisation(value: Optional[str]) -> Optional[str]:
    """Map free-form input to a supported strategy, or None for balanced.

    Anything unrecognised falls back to balanced rather than raising — the
    value can originate from an LLM parse, and an odd string is not a reason
    to fail a journey.
    """
    if not value:
        return None
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "cheap": OPTIMISE_CHEAPEST,
        "cheapest": OPTIMISE_CHEAPEST,
        "lowest_cost": OPTIMISE_CHEAPEST,
        "price": OPTIMISE_CHEAPEST,
        "fast": OPTIMISE_FASTEST,
        "fastest": OPTIMISE_FASTEST,
        "quickest": OPTIMISE_FASTEST,
        "soonest": OPTIMISE_FASTEST,
        "fewest_changes": OPTIMISE_FEWEST_CHANGES,
        "fewest_transfers": OPTIMISE_FEWEST_CHANGES,
        "direct": OPTIMISE_FEWEST_CHANGES,
    }
    return aliases.get(key)


def _parse_time(t: Optional[str]) -> Optional[datetime]:
    """Parse HH:MM string to datetime (using today's date as anchor)."""
    if not t:
        return None
    clean = t.replace(" (next day)", "").strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            continue
    return None


def _departure_dt(route: dict) -> Optional[datetime]:
    deps = route.get("departure_times") or []
    return _parse_time(deps[0]) if deps else None


def _arrival_dt(route: dict) -> Optional[datetime]:
    arrs = route.get("arrival_times") or []
    return _parse_time(arrs[-1]) if arrs else None


def _leg_count(route: dict) -> int:
    """Number of transit legs; 1 for a direct route.

    Reads the structured `legs` list that google_maps_tool records. Falls back
    to counting "Step N:" markers in the description only for routes that
    predate that field — the description is a display string, not a contract,
    and parsing it is a last resort.
    """
    legs = route.get("legs")
    if legs:
        return len(legs)

    desc = route.get("description", "")
    if "Step" in desc:
        steps = re.findall(r"Step \d+:", desc)
        return len(steps) if steps else 1
    return 1


# Sorts after every priced route, so an unpriced one never wins on cost.
_UNKNOWN_FARE = float("inf")


def _fare_amount(route: dict) -> float:
    fare = route.get("fare_estimate") or {}
    amount = fare.get("amount")
    return float(amount) if isinstance(amount, (int, float)) else _UNKNOWN_FARE


def _score(
    route: dict,
    requested_dt: Optional[datetime],
    deadline_dt: Optional[datetime],
    optimise_for: Optional[str] = None,
) -> tuple:
    """
    Return a sort key tuple (lower = better).

    The first two elements are the hard constraints and never vary; the rest
    depend on `optimise_for`. Every branch returns a tuple of the same length
    so the keys stay mutually comparable.
    """
    dep = _departure_dt(route)
    arr = _arrival_dt(route)

    # Hard constraint 1: arrives after the commuter's deadline.
    missed_deadline = 1 if (deadline_dt and arr and arr > deadline_dt) else 0

    # Hard constraint 2: departs before the commuter can actually leave.
    before_requested = 1 if (requested_dt and dep and dep < requested_dt) else 0

    legs = _leg_count(route)
    arrival_minutes = arr.hour * 60 + arr.minute if arr else 9999
    fare = _fare_amount(route)
    # Tiebreaker only: train schedules are more reliable than bus ones.
    mode_penalty = 0 if route.get("transit_mode") == TransitMode.TRAIN.value else 1

    head = (missed_deadline, before_requested)

    if optimise_for == OPTIMISE_CHEAPEST:
        return (*head, fare, arrival_minutes, legs)
    if optimise_for == OPTIMISE_FASTEST:
        return (*head, arrival_minutes, legs, fare)
    if optimise_for == OPTIMISE_FEWEST_CHANGES:
        return (*head, legs, arrival_minutes, fare)

    # Balanced (default): a direct route beats a multi-leg one regardless of
    # mode, and mode only breaks ties between equal leg counts.
    return (*head, legs, mode_penalty, arrival_minutes)


def ranker_node(state: AgentState) -> AgentState:
    """
    Rank candidate_routes and select the top-5 best options.

    Reads:  candidate_routes, requested_time, expected_arrival_time
    Writes: ranked_routes, candidate_route (best single route)
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])
    requested_time = state.get("requested_time")
    expected_arrival_time = state.get("expected_arrival_time")
    optimise_for = normalise_optimisation(state.get("optimise_for"))

    if not candidate_routes:
        logger.info("[%s] No routes to rank.", NODE_NAME)
        return {**state, "trace": trace, "ranked_routes": []}

    requested_dt = _parse_time(requested_time)
    deadline_dt = _parse_time(expected_arrival_time)

    scored = sorted(
        candidate_routes,
        key=lambda r: _score(r, requested_dt, deadline_dt, optimise_for),
    )

    ranked = scored[:_MAX_RANKED]
    best = ranked[0]

    fare = best.get("fare_estimate") or {}
    logger.info(
        "[%s] Ranked %d route(s) by %s -> top route_id=%r mode=%r dep=%s arr=%s fare=%s",
        NODE_NAME,
        len(ranked),
        optimise_for or "balanced",
        best.get("route_id"),
        best.get("transit_mode"),
        (best.get("departure_times") or ["—"])[0],
        (best.get("arrival_times") or ["—"])[-1],
        fare.get("amount", "—"),
    )

    return {
        **state,
        "trace": trace,
        "ranked_routes": ranked,
        "candidate_route": best,
        # Echo the normalised value so downstream nodes and the UI agree on
        # which strategy actually ran, not merely what was requested.
        "optimise_for": optimise_for,
    }
