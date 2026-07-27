"""
One-off ingestion script — run once (or whenever timetable data changes).

Pipeline:
  routes.json → descriptions → local embeddings → Chroma

Usage:
  uv run python -m commute_agent.rag.ingest
  # or via project script:
  uv run ingest
"""

from __future__ import annotations

import json

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger, setup_logging
from commute_agent.domain.models import RouteOption
from commute_agent.rag.chroma_client import COLLECTION_ROUTES, get_collection

logger = get_logger(__name__)


def ingest_routes() -> int:
    """
    Load routes.json and upsert each route's description into Chroma.

    Documents are embedded automatically by the collection's attached local
    embedding function — no separate embed step needed.

    Returns the number of documents ingested.
    """
    settings = get_settings()
    collection = get_collection(COLLECTION_ROUTES)

    with open(settings.routes_path, encoding="utf-8") as f:
        raw_routes: list[dict] = json.load(f)

    routes = [RouteOption(**r) for r in raw_routes]
    logger.info("Loaded %d routes from %s", len(routes), settings.routes_path)

    ids = [r.route_id for r in routes]
    texts = [r.description for r in routes]
    metadatas = [
        {
            "route_id": r.route_id,
            "line": r.line,
            "origin": r.origin,
            "destination": r.destination,
            "departure_time": r.departure_time,
            "arrival_time": r.arrival_time,
            "transit_mode": r.transit_mode.value,
        }
        for r in routes
    ]

    logger.info("Upserting %d route descriptions into Chroma…", len(texts))
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
    logger.info("Upserted %d documents into Chroma collection %r", len(ids), COLLECTION_ROUTES)
    return len(ids)


def main() -> None:
    setup_logging()

    count = ingest_routes()
    logger.info("Ingestion complete: %d routes indexed.", count)


if __name__ == "__main__":
    main()
