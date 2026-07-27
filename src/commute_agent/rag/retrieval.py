"""
Data access layer — route retrieval and disruption checking.

Public API (called by the graph nodes via tools):
  retrieve_routes(query_text, origin, destination, time) -> List[RouteOption]
  retrieve_bus_timetable(query_text, top_k)              -> list[dict]
  check_disruption(route)                                -> DisruptionStatus

Both functions are fault-tolerant: they log and raise typed exceptions rather
than returning None or empty lists silently.
"""

from __future__ import annotations

import json
from typing import Optional

from commute_agent.core.config import get_settings
from commute_agent.core.exceptions import DisruptionCheckError, RouteNotFoundError
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import DisruptionLevel
from commute_agent.domain.models import DisruptionRecord, DisruptionStatus, RouteOption
from commute_agent.rag.chroma_client import COLLECTION_BUS_TIMETABLES, COLLECTION_ROUTES, get_collection

logger = get_logger(__name__)


def retrieve_routes(
    query_text: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    time: Optional[str] = None,
) -> list[RouteOption]:
    """
    Semantic search over the Chroma vector store for matching train routes.

    Falls back to keyword/filter matching on routes.json when Chroma hasn't
    been populated yet (run `uv run ingest`) or returns nothing above the
    similarity threshold. Raises RouteNotFoundError if no routes match after
    both strategies.
    """
    settings = get_settings()
    top_k: int = settings.app_settings["retrieval"]["top_k"]
    threshold: float = settings.app_settings["retrieval"]["similarity_threshold"]

    logger.debug(
        "retrieve_routes: query=%r origin=%r destination=%r time=%r",
        query_text[:60], origin, destination, time,
    )

    semantic_matches = _semantic_search_routes(query_text, origin, destination, top_k, threshold)
    if semantic_matches:
        return semantic_matches

    logger.debug("retrieve_routes: keyword fallback on routes.json")
    all_routes = _load_all_routes()
    if not all_routes:
        raise RouteNotFoundError("No routes loaded from routes.json")

    # Simple filter by destination station name (case-insensitive) as minimal logic
    filtered = all_routes
    if destination:
        filtered = [r for r in all_routes if destination.lower() in r.destination.lower()]
    if origin:
        filtered = [r for r in filtered if origin.lower() in r.origin.lower()]

    if not filtered:
        raise RouteNotFoundError(
            f"No routes found for origin={origin!r}, destination={destination!r}"
        )

    return filtered[:top_k]


def retrieve_bus_timetable(query_text: str, top_k: int = 3) -> list[dict]:
    """
    Semantic search over the ingested bus-timetable document corpus
    (data/processed/bus/**/*.md, ingested via `uv run ingest-bus`).

    Returns a list of dicts: {route_name, category, subcategory, source_file,
    similarity, sample_schedule}, where sample_schedule is a list of
    [departure, arrival] HH:MM pairs pulled directly from the archived
    timetable (best-effort — treat as a "we found this in the archive"
    signal, not a live/authoritative schedule).

    Returns an empty list — never raises — if the collection hasn't been
    ingested yet or nothing clears the similarity threshold; callers must
    treat that as "no extra data available", the same graceful-degradation
    contract as the rest of the RAG layer.
    """
    settings = get_settings()
    threshold: float = settings.app_settings["retrieval"]["similarity_threshold"]

    try:
        collection = get_collection(COLLECTION_BUS_TIMETABLES)
        result = collection.query(query_texts=[query_text], n_results=top_k)
    except Exception as exc:
        logger.debug("Bus timetable semantic search unavailable: %s", exc)
        return []

    ids = result.get("ids") or [[]]
    distances = result.get("distances") or [[]]
    metadatas = result.get("metadatas") or [[]]

    matches: list[dict] = []
    for doc_id, meta, distance in zip(ids[0], metadatas[0], distances[0]):
        similarity = 1 - distance
        if similarity < threshold:
            continue
        entry = dict(meta)
        entry["doc_id"] = doc_id
        entry["similarity"] = round(similarity, 3)
        raw_schedule = entry.get("sample_schedule")
        if isinstance(raw_schedule, str):
            try:
                entry["sample_schedule"] = json.loads(raw_schedule)
            except json.JSONDecodeError:
                entry["sample_schedule"] = []
        matches.append(entry)

    logger.info("retrieve_bus_timetable: %d match(es) for %r", len(matches), query_text[:60])
    return matches


def check_disruption(route: RouteOption) -> DisruptionStatus:
    """
    Check whether a given route is currently disrupted.

    Reads from disruptions.json (simulating a live feed).
    Matches by checking whether the route's origin or destination appears in
    the disruption's affected_segment — works for both timetable and Google Maps routes.
    Raises DisruptionCheckError on read/parse failure.
    """
    logger.debug("check_disruption: route_id=%r", route.route_id)

    try:
        disruptions = _load_active_disruptions()
    except Exception as exc:
        raise DisruptionCheckError(f"Failed to load disruption feed: {exc}") from exc

    route_origin = route.origin.lower()
    route_dest = route.destination.lower()

    for d in disruptions:
        if not d.active:
            continue
        segment = d.affected_segment.lower()
        if route_origin in segment or route_dest in segment:
            level = (
                DisruptionLevel.CANCELLED
                if d.type.value == "cancellation"
                else DisruptionLevel.DELAYED
            )
            logger.info("Disruption found for route %s: %s", route.route_id, level)
            return DisruptionStatus(level=level, disruption=d)

    return DisruptionStatus(level=DisruptionLevel.CLEAR)


# ── Private helpers ────────────────────────────────────────────────────────────

def _semantic_search_routes(
    query_text: str,
    origin: Optional[str],
    destination: Optional[str],
    top_k: int,
    threshold: float,
) -> list[RouteOption]:
    """Query the Chroma routes collection; returns [] on any failure or no confident match."""
    try:
        collection = get_collection(COLLECTION_ROUTES)
        where = _build_filter(origin, destination)
        result = collection.query(query_texts=[query_text], n_results=top_k, where=where)
    except Exception as exc:
        logger.debug("Semantic route search unavailable (%s) — falling back to keyword filter.", exc)
        return []

    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    if not ids:
        return []

    routes_by_id = {r.route_id: r for r in _load_all_routes()}
    matches: list[RouteOption] = []
    for route_id, distance in zip(ids, distances):
        if (1 - distance) < threshold:
            continue
        route = routes_by_id.get(route_id)
        if route:
            matches.append(route)

    if matches:
        logger.info("Semantic search matched %d route(s) for %r", len(matches), query_text[:60])
    return matches


def _load_all_routes() -> list[RouteOption]:
    """Load all routes from the JSON file. Cached by the tool layer."""
    settings = get_settings()
    with open(settings.routes_path, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return [RouteOption(**r) for r in data]


def _load_active_disruptions() -> list[DisruptionRecord]:
    """Load disruption records. Only active=true entries count as live."""
    settings = get_settings()
    with open(settings.disruptions_path, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return [DisruptionRecord(**d) for d in data]


def _build_filter(origin: Optional[str], destination: Optional[str]) -> Optional[dict]:
    """Build a Chroma where-clause from optional station filters."""
    conditions = []
    if origin:
        conditions.append({"origin": {"$eq": origin}})
    if destination:
        conditions.append({"destination": {"$eq": destination}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
