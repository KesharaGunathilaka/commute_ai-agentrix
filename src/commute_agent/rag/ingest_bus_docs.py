"""
One-off ingestion script — embeds the already-collected Sri Lanka bus
timetable markdown corpus (data/processed/bus/**/*.md) into Chroma.

These ~100 documents were extracted from PDF timetables and their narrative
Sinhala text is corrupted by a font-encoding issue in the original
PDF-to-markdown conversion (garbled "(cid:NN)" glyph codes). Rather than
embed that noise, this script embeds a clean text built from the YAML
frontmatter (route_name / category / subcategory), and separately extracts
real departure/arrival time samples straight from the "### Timetable"
pipe-table sections using position-based parsing (looking for HH:MM-shaped
tokens), which is immune to the header corruption since it never reads the
header text at all.

Usage:
  uv run python -m commute_agent.rag.ingest_bus_docs
  # or via project script:
  uv run ingest-bus
"""

from __future__ import annotations

import json
import re

import yaml

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger, setup_logging
from commute_agent.rag.chroma_client import COLLECTION_BUS_TIMETABLES, get_collection

logger = get_logger(__name__)

_TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
_MAX_SAMPLE_ROWS = 8


def _parse_frontmatter(text: str) -> dict:
    """Parse the leading YAML frontmatter block. Returns {} if absent/malformed."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _extract_schedule_samples(text: str, max_rows: int = _MAX_SAMPLE_ROWS) -> list[list[str]]:
    """
    Pull [departure, arrival] pairs straight from markdown table rows.

    Doesn't rely on header text at all (which is corrupted for these files).
    A "block" is a run of consecutive non-empty pipe-delimited cells within a
    row — these tables put one direction's data in one block and the return
    direction's data in a second block, separated by an empty cell. A block
    counts as a schedule row if it contains 2+ HH:MM-looking tokens; the
    first and last such tokens become that block's departure/arrival. This
    naturally skips header rows and "---" separator rows since neither
    contains time-like tokens.
    """
    samples: list[list[str]] = []
    seen: set[tuple[str, str]] = set()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]

        blocks: list[list[str]] = []
        block: list[str] = []
        for cell in cells:
            if cell == "":
                if block:
                    blocks.append(block)
                block = []
            else:
                block.append(cell)
        if block:
            blocks.append(block)

        for b in blocks:
            times = [c for c in b if _TIME_RE.match(c)]
            if len(times) < 2:
                continue
            pair = (times[0], times[-1])
            if pair not in seen:
                seen.add(pair)
                samples.append([times[0], times[-1]])
            if len(samples) >= max_rows:
                return samples

    return samples


def ingest_bus_docs() -> int:
    """
    Walk data/processed/bus/**/*.md, embed a clean per-route description, and
    upsert into the bus-timetables Chroma collection.

    Returns the number of documents ingested.
    """
    settings = get_settings()
    collection = get_collection(COLLECTION_BUS_TIMETABLES)

    bus_dir = settings.data_dir / "processed" / "bus"
    md_files = sorted(bus_dir.rglob("*.md"))
    if not md_files:
        logger.warning("No markdown files found under %s", bus_dir)
        return 0

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    for path in md_files:
        raw = path.read_text(encoding="utf-8")
        meta = _parse_frontmatter(raw)
        route_name = meta.get("route_name") or path.stem
        category = meta.get("category", "")
        subcategory = meta.get("subcategory", "")

        # Clean embedding text — deliberately built from frontmatter only,
        # NOT the corrupted body text (see module docstring).
        doc_text = f"{route_name} bus route ({category}, {subcategory})"
        schedule = _extract_schedule_samples(raw)

        ids.append(str(path.relative_to(settings.data_dir)))
        texts.append(doc_text)
        metadatas.append({
            "route_name": route_name,
            "category": category,
            "subcategory": subcategory,
            "source_file": meta.get("source_file", path.name),
            "sample_schedule": json.dumps(schedule, ensure_ascii=False),
        })

    logger.info("Upserting %d bus-timetable document(s) into Chroma…", len(ids))
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
    logger.info(
        "Upserted %d documents into Chroma collection %r", len(ids), COLLECTION_BUS_TIMETABLES
    )
    return len(ids)


def main() -> None:
    setup_logging()
    count = ingest_bus_docs()
    logger.info("Bus-timetable ingestion complete: %d documents indexed.", count)


if __name__ == "__main__":
    main()
