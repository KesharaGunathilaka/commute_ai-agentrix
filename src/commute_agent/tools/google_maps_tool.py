"""
Google Maps Directions API tool — transit route discovery for the Planner node.

Calls the Directions API with mode=transit and alternatives=True, then maps
each transit route to a RouteOption. Handles both train and bus legs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import googlemaps

from commute_agent.core.config import get_settings
from commute_agent.core.exceptions import RouteNotFoundError
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import TransitMode
from commute_agent.domain.models import RouteOption
from commute_agent.domain.provenance import SOURCE_GOOGLE_MAPS, provenance

logger = get_logger(__name__)

_RAIL_VEHICLE_TYPES = {
    "HEAVY_RAIL", "COMMUTER_TRAIN", "RAIL", "SUBWAY",
    "METRO_RAIL", "TRAM", "MONORAIL", "FUNICULAR",
}


def _client() -> googlemaps.Client:
    settings = get_settings()
    key = settings.google_maps_api_key or settings.google_api_key
    return googlemaps.Client(key=key)


def _parse_departure_time(time_str: Optional[str]) -> datetime:
    """Convert HH:MM string to today's datetime, or return now if absent."""
    if not time_str:
        return datetime.now()
    today = date.today()
    hour, minute = map(int, time_str.split(":"))
    return datetime(today.year, today.month, today.day, hour, minute)


def _unix_to_hhmm(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts).strftime("%H:%M")


def _stop_location(stop: Optional[dict]) -> dict:
    """Pull {"lat", "lng"} out of a transit stop, or {} when absent.

    Returns an empty dict rather than None so callers can splat it into a
    marker dict unconditionally — a stop with no coordinates simply yields a
    marker with no position, which the frontend skips.
    """
    location = (stop or {}).get("location") or {}
    lat, lng = location.get("lat"), location.get("lng")
    if lat is None or lng is None:
        return {}
    return {"lat": lat, "lng": lng}


def _extract_bounds(gmaps_route: dict) -> Optional[dict]:
    """Flatten Google's {northeast, southwest} viewport into N/S/E/W."""
    bounds = gmaps_route.get("bounds") or {}
    ne, sw = bounds.get("northeast"), bounds.get("southwest")
    if not ne or not sw:
        return None
    return {"north": ne["lat"], "south": sw["lat"], "east": ne["lng"], "west": sw["lng"]}


def _extract_route(gmaps_route: dict, route_idx: int) -> Optional[RouteOption]:
    """
    Convert one Google Maps route dict into a RouteOption.

    Each TRANSIT step becomes one leg. Per-leg route numbers, boarding stops,
    and alighting stops are captured and included in the description.
    WALKING steps don't become legs of their own, but a WALKING step that
    comes AFTER the last TRANSIT step is tracked as `last_mile_distance_m` —
    this is the gap between where transit drops the commuter off and their
    actual destination. A WALKING step between two TRANSIT steps (a transfer)
    is deliberately not counted — the running total resets every time another
    TRANSIT step is seen. Returns None if there are no transit steps.

    Each TRANSIT step is also captured as a structured dict in `legs` (mode,
    line, board/alight stop, times, distance) — this lets downstream nodes
    (e.g. the last-mile Uber alternative in uber.py) reason about the FINAL
    leg specifically without re-parsing the flattened description string.
    """
    stops: list[str] = []
    times: list[str] = []
    stop_coords: list[dict] = []
    leg_descriptions: list[str] = []
    legs_data: list[dict] = []
    primary_transit_mode = TransitMode.BUS
    primary_line = ""
    primary_vehicle = ""
    trailing_walk_distance_m = 0

    for leg in gmaps_route.get("legs", []):
        for step in leg.get("steps", []):
            if step.get("travel_mode") != "TRANSIT":
                if step.get("travel_mode") == "WALKING":
                    trailing_walk_distance_m += step.get("distance", {}).get("value", 0)
                continue

            # A TRANSIT step follows — any walking distance accumulated so
            # far was a transfer between legs, not a last-mile gap. Reset.
            trailing_walk_distance_m = 0

            details = step.get("transit_details", {})
            dep_stop = details.get("departure_stop", {}).get("name", "")
            arr_stop = details.get("arrival_stop", {}).get("name", "")
            dep_loc = _stop_location(details.get("departure_stop"))
            arr_loc = _stop_location(details.get("arrival_stop"))
            dep_unix = details.get("departure_time", {}).get("value", 0)
            arr_unix = details.get("arrival_time", {}).get("value", 0)
            dep_text = details.get("departure_time", {}).get("text", "")
            arr_text = details.get("arrival_time", {}).get("text", "")
            dep_hhmm = _unix_to_hhmm(dep_unix) if dep_unix else dep_text
            arr_hhmm = _unix_to_hhmm(arr_unix) if arr_unix else arr_text

            line = details.get("line", {})
            line_name = line.get("name", "")
            short_name = line.get("short_name", "")
            veh_type = line.get("vehicle", {}).get("type", "BUS")
            is_rail = veh_type in _RAIL_VEHICLE_TYPES

            if not primary_line:
                primary_line = line_name or short_name
                primary_vehicle = veh_type
            if is_rail:
                primary_transit_mode = TransitMode.TRAIN

            # Build the ordered stop list (deduped at transfer points).
            # stop_coords stays index-aligned with stops — every append here
            # pushes to both, so a map can label marker i with stops[i].
            if not stops or stops[-1] != dep_stop:
                stops.append(dep_stop)
                times.append(dep_hhmm)
                stop_coords.append({"name": dep_stop, **dep_loc})
            stops.append(arr_stop)
            times.append(arr_hhmm)
            stop_coords.append({"name": arr_stop, **arr_loc})

            # Per-leg boarding instruction
            mode_label = "Train" if is_rail else "Bus"
            route_ref = f"No.{short_name} ({line_name})" if short_name else f"({line_name})"
            leg_descriptions.append(
                f"{mode_label} {route_ref} — "
                f"Board at {dep_stop}, Alight at {arr_stop} "
                f"({dep_text} - {arr_text})"
            )
            legs_data.append({
                "mode": "train" if is_rail else "bus",
                "line": line_name,
                "route_ref": short_name,
                "board_stop": dep_stop,
                "alight_stop": arr_stop,
                "departure": dep_hhmm,
                "arrival": arr_hhmm,
                "distance_m": step.get("distance", {}).get("value", 0),
                # Stamped at the origin of the data, per leg, so that a later
                # node replacing one leg's times with local data leaves the
                # other legs still correctly attributed to Maps.
                **provenance(SOURCE_GOOGLE_MAPS),
                # Per-leg geometry, so the frontend can colour one leg
                # differently from the rest — that's how a disrupted segment
                # gets highlighted without redrawing the whole route.
                "polyline": step.get("polyline", {}).get("points"),
                "board_coord": dep_loc or None,
                "alight_coord": arr_loc or None,
            })

    if not stops or not leg_descriptions:
        return None

    if len(leg_descriptions) == 1:
        description = leg_descriptions[0]
    else:
        steps_str = "\n".join(
            f"  Step {i + 1}: {leg}" for i, leg in enumerate(leg_descriptions)
        )
        description = f"{len(leg_descriptions)}-leg journey:\n{steps_str}"

    return RouteOption(
        route_id=f"GMAPS-{route_idx}",
        line=primary_line,
        stops=stops,
        departure_times=times,
        arrival_times=times,
        days_of_operation=["daily"],
        transit_mode=primary_transit_mode,
        vehicle_type=primary_vehicle,
        description=description,
        last_mile_distance_m=trailing_walk_distance_m or None,
        legs=legs_data,
        polyline=gmaps_route.get("overview_polyline", {}).get("points"),
        stop_coords=stop_coords,
        bounds=_extract_bounds(gmaps_route),
        # Live routing, and the best times the system has — but nobody here
        # has checked them against a published SLR or NTC timetable, so this
        # is unverified. captured_date stays None: there is nothing to capture.
        **provenance(SOURCE_GOOGLE_MAPS),
    )


def get_transit_routes(
    origin: str,
    destination: str,
    departure_time: Optional[str] = None,
) -> list[RouteOption]:
    """
    Discover all transit routes from origin to destination via Google Maps.

    Raises RouteNotFoundError if the API call fails or returns no transit routes.
    """
    dep_dt = _parse_departure_time(departure_time)
    logger.info("Google Maps query: %r → %r at %s", origin, destination, dep_dt.strftime("%H:%M"))

    try:
        results = _client().directions(
            origin=origin,
            destination=destination,
            mode="transit",
            alternatives=True,
            departure_time=dep_dt,
        )
    except Exception as exc:
        logger.error("Google Maps API error: %s", exc)
        raise RouteNotFoundError(f"Google Maps API call failed: {exc}") from exc

    if not results:
        raise RouteNotFoundError(f"No transit routes found: {origin!r} → {destination!r}")

    routes: list[RouteOption] = []
    for idx, result in enumerate(results):
        route = _extract_route(result, idx)
        if route is not None:
            routes.append(route)

    if not routes:
        raise RouteNotFoundError(f"No transit legs found: {origin!r} → {destination!r}")

    logger.info("Found %d transit route(s) via Google Maps", len(routes))
    return routes
