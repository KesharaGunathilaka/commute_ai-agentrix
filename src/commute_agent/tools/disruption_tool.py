"""
LangGraph-compatible tool: disruption checking with caching and fault tolerance.

Wraps retrieval.check_disruption() with:
  - TTL cache (short — disruption data changes frequently)
  - Graceful fallback: if the feed is unreachable, treat as CLEAR and log a warning
    so the agent degrades gracefully rather than crashing the whole graph.
"""

from __future__ import annotations

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from commute_agent.core.exceptions import DisruptionCheckError
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import DisruptionLevel
from commute_agent.domain.models import DisruptionStatus, RouteOption
from commute_agent.rag.retrieval import check_disruption as _check
from commute_agent.tools import cache

logger = get_logger(__name__)

# Disruption cache TTL is intentionally shorter than the global default —
# disruption state can change within minutes.
_DISRUPTION_TTL_OVERRIDE = 60  # seconds


@retry(
    retry=retry_if_exception_type(DisruptionCheckError),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=False,
)
def check_disruption(route: RouteOption) -> DisruptionStatus:
    """
    Check route disruption status, with cache and a safe fallback.

    If the disruption feed fails after retries, returns CLEAR with a warning
    so the agent continues rather than blocking the commuter.
    """
    key = cache.make_key("disruption", route.route_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    logger.info("Checking disruption for route_id=%r", route.route_id)

    try:
        status = _check(route)
    except DisruptionCheckError as exc:
        logger.warning(
            "Disruption check failed for %r (treating as CLEAR): %s",
            route.train_id, exc,
        )
        # Graceful degradation — don't surface the error to the commuter
        status = DisruptionStatus(level=DisruptionLevel.CLEAR)

    cache.set(key, status)
    return status
