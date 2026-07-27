"""
PDF timetable extraction — attempts pdfplumber parsing, falls back to routes.json.

Usage:
  uv run python -m commute_agent.scripts.ingest_timetables
"""

from __future__ import annotations

import json
from pathlib import Path

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


def extract_from_pdfs() -> list[dict]:
    """
    Attempt to extract timetable data from PDFs in data/raw/ using pdfplumber.

    Returns list of raw route dicts if successful; empty list on failure.
    If extraction fails or yields messy data, routes.json is used as-is.
    """
    settings = get_settings()
    raw_dir = settings.data_dir / "raw"
    pdf_files = list(raw_dir.glob("*.pdf"))

    if not pdf_files:
        logger.warning("No PDFs found in %s — using existing routes.json", raw_dir)
        return []

    routes = []

    for pdf_path in pdf_files:
        logger.info("Attempting extraction from %s", pdf_path.name)

        logger.warning(
            "PDF extraction not yet implemented for %s — falling back to routes.json.",
            pdf_path.name,
        )

    return routes


def _parse_table(table: list[list]) -> list[dict]:
    """Convert a pdfplumber table (list of rows) into route dicts."""
    return []


def main() -> None:
    setup_logging()

    extracted = extract_from_pdfs()
    if extracted:
        settings = get_settings()
        out_path = settings.routes_path
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(extracted, f, indent=2, ensure_ascii=False)
        logger.info("Wrote %d routes to %s", len(extracted), out_path)
    else:
        logger.info("Using existing routes.json (no PDF extraction).")

    # Always run Chroma ingestion after (creates/updates the vector store)
    from commute_agent.rag.ingest import ingest_routes
    count = ingest_routes()
    logger.info("Ingestion complete: %d routes in Chroma.", count)


if __name__ == "__main__":
    main()
