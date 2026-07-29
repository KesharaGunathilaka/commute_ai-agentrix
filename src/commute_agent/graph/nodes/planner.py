"""
Planner node — first node in the graph.

Parses the user query via NLU (or uses pre-populated intent in conversational mode),
then discovers all available transit routes via the Google Maps Directions API.
"""

from __future__ import annotations

from commute_agent.core.exceptions import NLUParseError, OffTopicQueryError, RouteNotFoundError
from commute_agent.core.logging import get_logger
from commute_agent.graph.state import AgentState
from commute_agent.nlu.models import ParsedIntent
from commute_agent.nlu.parser import parse_query
from commute_agent.tools.google_maps_tool import get_transit_routes

logger = get_logger(__name__)

NODE_NAME = "planner"


def planner_node(state: AgentState) -> AgentState:
    """ 
    LangGraph node function — receives state, returns updated state dict.

    On NLU failure: stores error in state and returns early (graph routes to responder).
    On route not found: stores error and returns early.
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)
    logger.info("[%s] Processing query: %r", NODE_NAME, state.get("user_query", "")[:60])

    # ── Step 1: Parse the query (skip if intent already pre-populated) ───────
    if state.get("origin") is not None and state.get("destination") is not None:
        # Conversational mode — intent was resolved by the UI before invoking the graph
        intent = ParsedIntent(
            language=state.get("language", "en"),
            origin=state.get("origin"),
            destination=state.get("destination"),
            requested_time=state.get("requested_time"),
            expected_arrival_time=state.get("expected_arrival_time"),
            preferred_mode=state.get("preferred_mode"),
            # Carried through explicitly. state_update below writes
            # intent.optimise_for back to state, so omitting it here would
            # blank the value _state_from_intent already seeded.
            optimise_for=state.get("optimise_for"),
        )
        logger.info("[%s] Pre-populated intent: %r → %r", NODE_NAME, intent.origin, intent.destination)
    else:
        try:
            intent = parse_query(state["user_query"])
        except OffTopicQueryError as exc:
            logger.warning("[%s] Off-topic query: %s", NODE_NAME, exc)
            return {
                **state,
                "trace": trace,
                "language": "en",
                "error": "Your query doesn't seem to be about public transport. Please ask about a journey.",
                "final_response_native": "Your query doesn't seem to be about public transport.",
                "final_response_en": "Your query doesn't seem to be about public transport.",
            }
        except NLUParseError as exc:
            logger.error("[%s] NLU parse failed: %s", NODE_NAME, exc)
            return {
                **state,
                "trace": trace,
                "language": "en",
                "error": str(exc),
            }

    state_update: AgentState = {
        **state,
        "trace": trace,
        "language": intent.language,
        "origin": intent.origin,
        "destination": intent.destination,
        "requested_time": intent.requested_time,
        "expected_arrival_time": intent.expected_arrival_time,
        "preferred_mode": intent.preferred_mode,
        # The NLU extracts this ("the cheapest way to Kandy") and the ranker
        # reads it, but nothing used to carry it between them on the one-shot
        # path — so POST /query silently ranked balanced whatever was asked for.
        "optimise_for": intent.optimise_for,
        "replan_attempts": state.get("replan_attempts", 0),
    }

    # ── Step 2: Discover routes via Google Maps ────────────────────────────────
    try:
        routes = get_transit_routes(
            origin=intent.origin,
            destination=intent.destination,
            departure_time=intent.requested_time,
        )

        # Filter by user's preferred transit mode if specified
        preferred = intent.preferred_mode  # "train" | "bus" | None
        if preferred:
            mode_filtered = [r for r in routes if r.transit_mode.value == preferred]
            if mode_filtered:
                routes = mode_filtered
                logger.info("[%s] Filtered to %d %s route(s)", NODE_NAME, len(routes), preferred)
            else:
                logger.warning(
                    "[%s] No %s routes found — falling back to all %d route(s)",
                    NODE_NAME, preferred, len(routes),
                )
                state_update["error"] = (
                    f"No {preferred} routes found for this journey; "
                    f"showing best available alternative."
                )

        state_update["candidate_routes"] = [r.model_dump() for r in routes]
        state_update["candidate_route"] = routes[0].model_dump()
        logger.info(
            "[%s] Found %d route(s); candidate route_id=%r mode=%r",
            NODE_NAME, len(routes), routes[0].route_id, routes[0].transit_mode,
        )
    except RouteNotFoundError as exc:
        logger.warning("[%s] No route found: %s", NODE_NAME, exc)
        state_update["candidate_routes"] = []
        state_update["error"] = str(exc)

    return state_update
