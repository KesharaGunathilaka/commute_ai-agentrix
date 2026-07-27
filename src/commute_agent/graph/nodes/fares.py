"""
Fare node — attaches a fare estimate to every candidate route.

Sits between train_rag and ranker. It has to run *before* ranking because
cheapest-first sorting depends on the numbers it produces, and it's a node of
its own rather than a few lines inside the ranker so the work is visible in
the agent trace — a commuter comparing options on price deserves to see that
the agent priced them.

Purely additive: a route the fare model can't price passes through untouched
with `fare_estimate` left as None, and the graph continues normally.
"""

from __future__ import annotations

from commute_agent.core.logging import get_logger
from commute_agent.graph.state import AgentState
from commute_agent.tools.fare_tool import estimate_fare

logger = get_logger(__name__)

NODE_NAME = "fares"


def fare_node(state: AgentState) -> AgentState:
    """
    Price every candidate route.

    Reads:  candidate_routes
    Writes: candidate_routes (each with fare_estimate), candidate_route
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])
    if not candidate_routes:
        logger.info("[%s] No routes to price.", NODE_NAME)
        return {**state, "trace": trace}

    priced: list[dict] = []
    priced_count = 0
    for route in candidate_routes:
        fare = estimate_fare(route)
        if fare is not None:
            priced_count += 1
        priced.append({**route, "fare_estimate": fare})

    # The ranker re-selects candidate_route straight after this, but keeping
    # it in step here means the state is never internally inconsistent — the
    # streaming API publishes state after every node, including this one.
    best = state.get("candidate_route")
    if best is not None:
        best_id = best.get("route_id")
        best = next(
            (r for r in priced if r.get("route_id") == best_id),
            {**best, "fare_estimate": estimate_fare(best)},
        )

    if priced_count == 0:
        logger.info(
            "[%s] Priced 0/%d route(s) — no leg distances available.",
            NODE_NAME, len(priced),
        )
    else:
        cheapest = min(
            (r["fare_estimate"]["amount"] for r in priced if r.get("fare_estimate")),
            default=None,
        )
        logger.info(
            "[%s] Priced %d/%d route(s); cheapest ≈ %s.",
            NODE_NAME, priced_count, len(priced), cheapest,
        )

    return {
        **state,
        "trace": trace,
        "candidate_routes": priced,
        "candidate_route": best,
    }
