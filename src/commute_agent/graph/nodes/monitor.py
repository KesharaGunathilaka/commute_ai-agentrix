"""
Monitor node — checks the candidate (or alternative) route for live disruptions.

Reads:  candidate_route (or alternative_route on replan iterations)
Writes: disruption_status
"""

from __future__ import annotations

from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import DisruptionLevel, TransitMode
from commute_agent.domain.models import DisruptionStatus, RouteOption
from commute_agent.graph.state import AgentState
from commute_agent.tools.disruption_tool import check_disruption

logger = get_logger(__name__)

NODE_NAME = "monitor"


def monitor_node(state: AgentState) -> AgentState:
    """
    Check disruption status for the current candidate_route.

    If we're in a replan iteration, check alternative_route instead.
    Writes disruption_status to state and appends 'monitor' to trace.
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    # On replan iterations the candidate has been replaced by alternative_route
    replan_attempts = state.get("replan_attempts", 0)
    route_dict = (
        state.get("alternative_route") if replan_attempts > 0
        else state.get("candidate_route")
    )

    if not route_dict:
        logger.warning("[%s] No route in state to check — marking CLEAR.", NODE_NAME)
        return {
            **state,
            "trace": trace,
            "disruption_status": {"level": DisruptionLevel.CLEAR, "disruption": None},
        }

    route = RouteOption(**route_dict)
    logger.info("[%s] Checking route_id=%r mode=%r (replan_attempt=%d)", NODE_NAME, route.route_id, route.transit_mode, replan_attempts)

    # Bus routes have no disruption feed — treat as clear
    if route.transit_mode == TransitMode.BUS:
        logger.info("[%s] Bus route — skipping disruption check (no feed available)", NODE_NAME)
        return {
            **state,
            "trace": trace,
            "disruption_status": {"level": DisruptionLevel.CLEAR, "disruption": None},
        }

    status: DisruptionStatus = check_disruption(route)
    logger.info("[%s] Disruption level: %s", NODE_NAME, status.level)

    disruption_dict = None
    if status.disruption:
        disruption_dict = status.disruption.model_dump()

    disruption_status = {"level": status.level, "disruption": disruption_dict}

    update: AgentState = {
        **state,
        "trace": trace,
        "disruption_status": disruption_status,
    }

    # Preserve the ORIGINAL disruption details the first time we see one, so the
    # Responder can still explain what went wrong even after a later check (on
    # the replanned alternative) comes back clear and overwrites disruption_status.
    if (
        replan_attempts == 0
        and status.level != DisruptionLevel.CLEAR
        and not state.get("original_disruption")
    ):
        update["original_disruption"] = disruption_status

    return update
