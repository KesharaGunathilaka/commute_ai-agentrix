"""
LangGraph-compatible tool: route retrieval with caching and retry.

Wraps retrieval.retrieve_routes() with:
  - TTL cache (avoids repeat Chroma queries for the same input)
  - Tenacity retry (up to 2 attempts on transient errors)
  - Typed return value (List[RouteOption])
"""
 
from __future__ import annotations

from typing import Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from commute_agent.core.exceptions import EmbeddingError, RouteNotFoundError
from commute_agent.core.logging import get_logger
from commute_agent.domain.models import RouteOption
from commute_agent.rag.retrieval import retrieve_routes as _retrieve
from commute_agent.tools import cache

logger = get_logger(__name__)


@retry(
    retry=retry_if_exception_type(EmbeddingError),
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    reraise=True,
)
def get_routes(
    query_text: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    time: Optional[str] = None,
) -> list[RouteOption]:
    """
    Retrieve candidate routes, using the cache to avoid redundant Chroma calls.

    Raises RouteNotFoundError if no matching routes exist.
    Raises EmbeddingError (after retry) if the embedding backend is unavailable.
    """
    key = cache.make_key("routes", query_text, origin, destination, time)
    cached = cache.get(key)
    if cached is not None:
        return cached

    logger.info(
        "Fetching routes: origin=%r destination=%r time=%r", origin, destination, time
    )
    routes = _retrieve(query_text, origin=origin, destination=destination, time=time)
    cache.set(key, routes)
    return routes
