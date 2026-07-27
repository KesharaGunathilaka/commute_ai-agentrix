"""
Singleton Chroma client — creates or opens the persisted collections.

All RAG modules import `get_collection(name)` instead of constructing their
own client, so the persist directory is only opened once per process. Every
collection gets the shared local embedding function (see embedder.py)
attached, so callers can `.add()`/`.upsert()`/`.query()` with raw text
(`documents=`, `query_texts=`) and never have to handle vectors by hand.
"""

from __future__ import annotations

from functools import lru_cache

import chromadb
from chromadb import Collection

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger
from commute_agent.rag.embedder import get_embedding_function

logger = get_logger(__name__)

COLLECTION_ROUTES = "sri_lanka_railways_routes"
COLLECTION_BUS_TIMETABLES = "sri_lanka_bus_timetables_docs"


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.PersistentClient:
    settings = get_settings()
    path = str(settings.chroma_persist_dir)
    logger.info("Opening Chroma at %s", path)

    return chromadb.PersistentClient(path=path)


@lru_cache(maxsize=None)
def get_collection(name: str = COLLECTION_ROUTES) -> Collection:
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=name,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
