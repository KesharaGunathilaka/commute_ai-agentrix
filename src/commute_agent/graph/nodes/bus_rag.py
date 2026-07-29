"""
Bus RAG node — enriches bus routes in candidate_routes with real departure times.

For each bus route returned by Google Maps, looks up the matching timetable entry
in data/bus_timetables.json and annotates the route with the next scheduled
departure after requested_time.

Bus matching uses the route number extracted from the Google Maps description.
When the curated JSON has no match, falls back to semantic search over the
much larger (but lower-confidence) archived bus-timetable corpus ingested
into Chroma from data/processed/bus/**/*.md (see rag/ingest_bus_docs.py).
That fallback only ever adds metadata (route name / archived sample
schedule) — it never overwrites the Google-Maps-derived departure/arrival
times used for ranking and response generation, since the archived data is
best-effort (PDF-extracted, of unknown freshness).

Falls back gracefully when no match is found at all.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import TransitMode
from commute_agent.domain.provenance import (
    SOURCE_GOOGLE_MAPS,
    SOURCE_LOCAL_TIMETABLE,
    provenance,
)
from commute_agent.graph.state import AgentState
from commute_agent.rag.retrieval import retrieve_bus_timetable

logger = get_logger(__name__)

NODE_NAME = "bus_rag"

_TIMETABLES_PATH = Path(__file__).parents[4] / "data" / "bus_timetables.json"
_timetables: Optional[list[dict]] = None


def _load_timetables() -> list[dict]:
    global _timetables
    if _timetables is None:
        with open(_TIMETABLES_PATH, encoding="utf-8") as f:
            _timetables = json.load(f)
    return _timetables


def _extract_route_number(description: str) -> Optional[str]:
    """Pull the bus route number from a Google Maps leg description string."""
    # Matches patterns like "Bus No.EX1-18", "Bus No.346-1", "Bus No.01"
    m = re.search(r"Bus No\.([A-Z0-9]+(?:-\d+)?)", description or "")
    if m:
        return m.group(1)
    # Also check plain route number prefix without "Bus No."
    m2 = re.search(r"\b([A-Z]{2,}\d*(?:-\d+)?|\d{2,3}(?:-\d+)?)\b", description or "")
    if m2:
        return m2.group(1)
    return None


def _canonical_route_number(route_num: str) -> str:
    """Return just the prefix before '-' for matching (EX1-18 -> EX1, 346-1 -> 346)."""
    return route_num.split("-")[0].lstrip("0") or "0"


def _find_timetable(route_num: str, timetables: list[dict]) -> Optional[dict]:
    """Find the matching timetable entry for a given route number.

    Tries an exact match on the literal route number first — this correctly
    distinguishes real, distinct routes like "01" (Normal) from "001" (A/C
    Luxury), which a zero-stripped comparison would otherwise conflate.
    Falls back to a zero-stripped comparison only when it resolves to exactly
    one candidate; an ambiguous or loose (e.g. plain prefix) match returns
    None rather than silently attaching the wrong schedule — the caller
    already degrades gracefully by keeping the Google Maps times untouched.
    """
    for entry in timetables:
        if entry["route_number"] == route_num:
            return entry

    canon = _canonical_route_number(route_num)
    candidates = [e for e in timetables if _canonical_route_number(e["route_number"]) == canon]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _next_departure(departures: list[str], requested_time: Optional[str]) -> Optional[str]:
    """Return the first departure at or after requested_time, or the first of the day."""
    if not departures:
        return None
    if not requested_time:
        return departures[0]

    try:
        base = datetime.strptime(requested_time, "%H:%M")
    except ValueError:
        return departures[0]

    for dep in departures:
        try:
            t = datetime.strptime(dep, "%H:%M")
            if t >= base:
                return dep
        except ValueError:
            continue

    # All departures are before requested_time — wrap to tomorrow
    return departures[0] + " (next day)"


def _rag_fallback_lookup(route: dict) -> Optional[dict]:
    """
    Semantic-search the archived bus-timetable corpus when the curated JSON
    has no match for this route.

    Returns None (never raises) on no confident match, or if the corpus
    hasn't been ingested yet (`uv run ingest-bus`) — this is a best-effort
    enrichment on top of the Google Maps data, never a hard requirement.
    """
    stops = route.get("stops") or []
    if len(stops) < 2:
        return None
    query = f"bus from {stops[0]} to {stops[-1]}"
    try:
        matches = retrieve_bus_timetable(query, top_k=1)
    except Exception as exc:
        logger.debug("[%s] RAG fallback lookup failed: %s", NODE_NAME, exc)
        return None
    return matches[0] if matches else None


def _compute_arrival(departure: str, journey_minutes: int) -> str:
    """Calculate arrival time string given departure HH:MM and journey duration."""
    try:
        dep_clean = departure.replace(" (next day)", "")
        t = datetime.strptime(dep_clean, "%H:%M") + timedelta(minutes=journey_minutes)
        suffix = " (next day)" if "(next day)" in departure else ""
        return t.strftime("%H:%M") + suffix
    except ValueError:
        return "—"


def bus_rag_node(state: AgentState) -> AgentState:
    """
    Enrich bus routes in candidate_routes with scheduled departure/arrival times.

    Reads:  candidate_routes, requested_time
    Writes: candidate_routes (updated in-place with enriched bus routes)
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])
    requested_time = state.get("requested_time")

    if not candidate_routes:
        logger.info("[%s] No candidate routes to enrich.", NODE_NAME)
        return {**state, "trace": trace}

    timetables = _load_timetables()
    enriched = []

    for route in candidate_routes:
        if route.get("transit_mode") != TransitMode.BUS.value:
            enriched.append(route)
            continue

        description = route.get("description", "")
        route_num = _extract_route_number(description)

        if not route_num:
            logger.debug("[%s] Could not extract route number from: %r", NODE_NAME, description[:80])
            enriched.append(route)
            continue

        entry = _find_timetable(route_num, timetables)
        if not entry:
            logger.debug(
                "[%s] No curated timetable match for route number %r — trying RAG fallback",
                NODE_NAME, route_num,
            )
            rag_match = _rag_fallback_lookup(route)
            if rag_match:
                updated = dict(route)
                updated["_timetable_route_name"] = rag_match.get("route_name", "")
                updated["_rag_match"] = {
                    "route_name": rag_match.get("route_name", ""),
                    "category": rag_match.get("category", ""),
                    "subcategory": rag_match.get("subcategory", ""),
                    "similarity": rag_match.get("similarity"),
                    "sample_schedule": rag_match.get("sample_schedule", []),
                }
                logger.info(
                    "[%s] RAG fallback matched %r (similarity=%.2f) for route %r",
                    NODE_NAME, rag_match.get("route_name"), rag_match.get("similarity") or 0.0, route_num,
                )
                enriched.append(updated)
            else:
                logger.debug("[%s] No RAG match either for route number %r", NODE_NAME, route_num)
                enriched.append(route)
            continue

        next_dep = _next_departure(entry["departures"], requested_time)
        journey_mins = entry.get("journey_time_minutes", 60)
        arrival = _compute_arrival(next_dep, journey_mins) if next_dep else "—"

        updated = dict(route)
        updated["departure_times"] = [next_dep] if next_dep else route.get("departure_times", [])
        updated["arrival_times"] = [arrival] if arrival else route.get("arrival_times", [])
        updated["_timetable_route_name"] = entry.get("route_name", "")
        updated["_journey_time_minutes"] = journey_mins

        # This branch replaces Google Maps times with curated ones, so the
        # route's headline times are no longer Maps-sourced and must not keep
        # claiming to be. `legs` is deliberately left alone: those times were
        # not touched, and re-stamping them would attribute Maps data to a
        # source it didn't come from.
        #
        # The previous values are kept rather than discarded. R1 happened
        # because an override left nothing behind to compare against, so the
        # substitution was invisible and unrecoverable.
        updated.update(provenance(SOURCE_LOCAL_TIMETABLE))
        updated["_provenance_override"] = {
            "fields": ["departure_times", "arrival_times"],
            "replaced_source": route.get("source") or SOURCE_GOOGLE_MAPS,
            "new_source": SOURCE_LOCAL_TIMETABLE,
            "timetable_route_name": entry.get("route_name", ""),
            "previous_departure_times": route.get("departure_times", []),
            "previous_arrival_times": route.get("arrival_times", []),
        }

        logger.info(
            "[%s] Enriched bus route %r: dep=%s arr=%s (%d min)",
            NODE_NAME, route_num, next_dep, arrival, journey_mins,
        )
        enriched.append(updated)

    # Update candidate_route to reflect enriched version of current best
    candidate_route = state.get("candidate_route")
    if candidate_route:
        route_id = candidate_route.get("route_id")
        for r in enriched:
            if r.get("route_id") == route_id:
                candidate_route = r
                break

    return {
        **state,
        "trace": trace,
        "candidate_routes": enriched,
        "candidate_route": candidate_route,
    }
