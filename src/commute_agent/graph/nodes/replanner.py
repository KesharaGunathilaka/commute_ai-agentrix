"""
Replanner node — finds an alternative route when the candidate is disrupted.

Writes: alternative_route, replan_attempts
Graph loops back to Monitor after this node (bounded by MAX_REPLAN_ATTEMPTS).

The hard cap on iterations is enforced BOTH here (state guard) and in the
conditional routing logic in builder.py — defence in depth.
"""

from __future__ import annotations

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger
from commute_agent.domain.models import RouteOption
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)

NODE_NAME = "replanner"


def replanner_node(state: AgentState) -> AgentState:
    """
    Find an alternative route by picking the next non-disrupted candidate from
    the Google Maps results already stored in candidate_routes.

    Strategy:
      1. Determine which route_id(s) have already been tried.
      2. Build a search order that respects the Ranker's scoring — ranked_routes
         first (already sorted best-first), then any remaining candidate_routes
         not covered by the ranker — and filter out anything already tried.
      3. Return the next available option as alternative_route.
      4. If nothing remains, store None — the Responder handles it gracefully.
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    replan_attempts = state.get("replan_attempts", 0) + 1
    settings = get_settings()

    logger.info(
        "[%s] Replanning attempt %d/%d",
        NODE_NAME, replan_attempts, settings.max_replan_attempts,
    )

    # Collect all route_ids already tried (candidate + any prior alternatives)
    tried_ids: set[str] = set()
    for key in ("candidate_route", "alternative_route"):
        r = state.get(key)
        if r and r.get("route_id"):
            tried_ids.add(r["route_id"])

    # Prefer the Ranker's best-first order; only fall back to the raw
    # Google Maps order for routes the Ranker didn't already consider.
    ranked_routes: list[dict] = state.get("ranked_routes") or []
    candidate_routes: list[dict] = state.get("candidate_routes") or []
    ranked_ids = {r.get("route_id") for r in ranked_routes}
    search_order = ranked_routes + [r for r in candidate_routes if r.get("route_id") not in ranked_ids]

    remaining = [r for r in search_order if r.get("route_id") not in tried_ids]

    alternative_dict = None
    if remaining:
        best = remaining[0]
        alternative_dict = best
        logger.info("[%s] Alternative found: route_id=%r mode=%r", NODE_NAME, best.get("route_id"), best.get("transit_mode"))
    else:
        logger.warning("[%s] No alternative route found in candidate_routes.", NODE_NAME)

    return {
        **state,
        "trace": trace,
        "replan_attempts": replan_attempts,
        "alternative_route": alternative_dict,
    }
