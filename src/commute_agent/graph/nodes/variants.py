"""
Plan-variants node — builds the fastest / cheapest / balanced cards.

Sits between `ranker` and `uber`. Purely additive: it reads `candidate_routes`
and writes `plan_variants`, and touches nothing else. `candidate_routes`,
`ranked_routes` and `candidate_route` come out exactly as they went in, because
the responder, the monitor, the replanner and the existing frontend all read
them and none of them may change behaviour.

It scores the **full candidate set** rather than `ranked_routes`. `ranked_routes`
is already the top five under whatever the commuter asked for, so the cheapest
option can have been cut from it by a speed-ranked truncation — which is
exactly the route the "cheapest" card exists to surface.

No LLM call and no network call: the whole node is arithmetic over data the
pipeline has already fetched, which is why it can be added to the per-turn path
without moving the latency budget. Measured cost is under a millisecond.
"""

from __future__ import annotations

from commute_agent.core.logging import get_logger
from commute_agent.graph.plan_variants import PlanConstraints, build_plan_variant_dicts
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)

NODE_NAME = "plan_variants"


def plan_variants_node(state: AgentState) -> AgentState:
    """
    Build up to three named plans from the candidate routes.

    Reads:  candidate_routes, requested_time, expected_arrival_time
    Writes: plan_variants
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])
    if not candidate_routes:
        logger.info("[%s] No routes to build variants from.", NODE_NAME)
        return {**state, "trace": trace, "plan_variants": []}

    variants = build_plan_variant_dicts(
        candidate_routes,
        PlanConstraints(
            requested_time=state.get("requested_time"),
            expected_arrival_time=state.get("expected_arrival_time"),
        ),
    )

    logger.info(
        "[%s] Built %d variant(s) from %d candidate(s): %s",
        NODE_NAME,
        len(variants),
        len(candidate_routes),
        ", ".join(f"{v['label']}={v['route_id']}" for v in variants) or "—",
    )

    return {**state, "trace": trace, "plan_variants": variants}
