"""
Uber node — suggests ride-hailing options via RideService.

Triggers in three scenarios:
1. No transit routes found (candidate_routes is empty or all miss deadline) —
   full Uber journey from origin to destination.
2. Train/bus journey found but there is a walking last-mile gap > 1 km, per
   candidate_route.last_mile_distance_m (populated by google_maps_tool from
   the trailing WALKING leg Google Maps reports after the final transit step).
   No local transit exists for this segment, so only a ride is offered.
3. The route is multi-leg and its FINAL leg is itself a short local hop
   (< 20 km) — e.g. Google Maps auto-chaining "Train Colombo->Galle" with
   "Local bus Galle->Karapitiya" into one itinerary. Here BOTH the transit
   leg Maps already found AND a ride-hailing quote for the same segment are
   offered side by side, so the commuter can choose — Maps silently picking
   one specific local bus shouldn't be the only option for that last hop.

ride_service.py lives at the repo root, so we add the repo root to sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from commute_agent.core.logging import get_logger
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)

NODE_NAME = "uber"

# Below this walking distance, suggesting a ride is more hassle than it's worth.
_LAST_MILE_THRESHOLD_M = 1000

# A route's final leg under this distance is treated as a local connector hop
# (last-mile candidate); beyond it, it's its own intercity leg — offering a
# taxi for a 50km+ hop would be absurd, so no alternative is suggested.
_LOCAL_LEG_MAX_DISTANCE_M = 20000

# ride_service.py is at repo root (not installed as a package)
_REPO_ROOT = Path(__file__).parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _get_ride_quotes(pickup: str, dropoff: str) -> list[dict]:
    """Call RideService and return JSON-friendly quote dicts."""
    try:
        from ride_service import RideService, quote_to_dict  # noqa: PLC0415
        svc = RideService()
        quotes = svc.get_estimates(pickup, dropoff)
        return [quote_to_dict(q) for q in quotes if q.available]
    except Exception as exc:
        logger.warning("[%s] RideService failed: %s", NODE_NAME, exc)
        return []


def _all_miss_deadline(ranked_routes: list[dict], deadline: str | None) -> bool:
    """Return True if every ranked route arrives after the deadline."""
    if not deadline or not ranked_routes:
        return False
    try:
        from datetime import datetime
        dl = datetime.strptime(deadline, "%H:%M")
        for route in ranked_routes:
            arrs = route.get("arrival_times") or []
            if not arrs:
                return False
            try:
                arr = datetime.strptime(arrs[-1].replace(" (next day)", ""), "%H:%M")
                if arr <= dl:
                    return False
            except ValueError:
                return False
        return True
    except ValueError:
        return False


def _has_last_mile_gap(candidate_route: dict | None) -> bool:
    """True if the route ends with a walking gap longer than the threshold."""
    if not candidate_route:
        return False
    distance = candidate_route.get("last_mile_distance_m")
    return bool(distance and distance > _LAST_MILE_THRESHOLD_M)


def _final_local_leg(candidate_route: dict | None) -> Optional[dict]:
    """
    Return the route's final leg if it looks like a short local connector
    worth offering a ride-hailing alternative for — i.e. the route has 2+
    legs (so there IS a distinguishable "last hop") and that final leg is
    under the local-distance threshold. None otherwise.
    """
    if not candidate_route:
        return None
    legs: list[dict] = candidate_route.get("legs") or []
    if len(legs) < 2:
        return None
    final = legs[-1]
    if (final.get("distance_m") or 0) > _LOCAL_LEG_MAX_DISTANCE_M:
        return None
    return final


def uber_node(state: AgentState) -> AgentState:
    """
    Populate uber_options / uber_last_mile / last_mile_transit_leg in state
    when a transit gap or a last-mile choice exists.

    Reads:  candidate_routes, ranked_routes, candidate_route, origin, destination,
            expected_arrival_time
    Writes: uber_options (full-trip quotes when no transit fits),
            uber_last_mile (last-leg ride quotes — walking gap OR final-leg alternative),
            uber_last_mile_distance_m (that leg's distance, for the response text),
            last_mile_transit_leg (the local bus/train Maps found for the final leg,
                                    when one exists — None for the pure-walking-gap case)
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    origin = state.get("origin", "")
    destination = state.get("destination", "")
    candidate_routes: list[dict] = state.get("candidate_routes", [])
    ranked_routes: list[dict] = state.get("ranked_routes", [])
    candidate_route: dict | None = state.get("candidate_route")
    deadline = state.get("expected_arrival_time")

    updates: dict = {
        "trace": trace,
        "uber_options": None,
        "uber_last_mile": None,
        "uber_last_mile_distance_m": None,
        "last_mile_transit_leg": None,
    }

    no_transit = len(candidate_routes) == 0
    all_missed = _all_miss_deadline(ranked_routes, deadline)

    if no_transit or all_missed:
        reason = "no transit routes found" if no_transit else "all routes miss arrival deadline"
        logger.info("[%s] Getting full-trip Uber quotes (%s).", NODE_NAME, reason)
        quotes = _get_ride_quotes(origin, destination)
        if quotes:
            updates["uber_options"] = quotes
            logger.info("[%s] Got %d Uber quotes for %r -> %r", NODE_NAME, len(quotes), origin, destination)
        else:
            logger.warning("[%s] No Uber quotes returned.", NODE_NAME)
    elif _has_last_mile_gap(candidate_route):
        # Walking gap, no transit at all for this segment — ride is the only option
        last_stop = (candidate_route.get("stops") or [destination])[-1]
        gap_m = candidate_route.get("last_mile_distance_m")
        logger.info(
            "[%s] Last-mile walking gap detected (%sm) — getting ride quotes from %r to %r",
            NODE_NAME, gap_m, last_stop, destination,
        )
        quotes = _get_ride_quotes(last_stop, destination)
        if quotes:
            updates["uber_last_mile"] = quotes
            updates["uber_last_mile_distance_m"] = gap_m
    elif final_leg := _final_local_leg(candidate_route):
        # Multi-leg route whose final leg is a short local hop — offer the
        # transit leg Maps already found AND a ride quote for the same
        # segment, side by side, instead of silently locking in Maps' pick.
        # Pickup is the leg's BOARDING stop (where a rider would actually
        # start from) — not the route's overall final alighting stop, which
        # is where this leg ENDS, not begins.
        pickup = final_leg.get("board_stop", "")
        dropoff = destination or final_leg.get("alight_stop", "")
        logger.info(
            "[%s] Final leg is a local hop (%sm via transit, %s %r) — also getting ride quotes from %r to %r",
            NODE_NAME, final_leg.get("distance_m"), final_leg.get("mode"), final_leg.get("line"), pickup, dropoff,
        )
        quotes = _get_ride_quotes(pickup, dropoff)
        if quotes:
            updates["uber_last_mile"] = quotes
            # Use the ride's own distance (curated or estimated), not the
            # transit leg's road-route distance — they can legitimately
            # differ (e.g. a bus takes a longer path than a direct taxi
            # route), and this is the number the displayed price is based on.
            updates["uber_last_mile_distance_m"] = int(quotes[0]["distance_km"] * 1000)
            updates["last_mile_transit_leg"] = final_leg
    else:
        logger.info("[%s] Good transit routes found — no last-mile alternative needed.", NODE_NAME)

    return {**state, **updates}
