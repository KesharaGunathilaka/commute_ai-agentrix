"""
Text embedder — local, offline, no API key required.

Uses ChromaDB's bundled ONNX MiniLM-L6-v2 embedding function (the same one
Chroma uses as its own default). The model file (~80MB) downloads once on
first use and is cached under the Chroma persist directory afterwards; every
call after that runs fully on-device.

Exposed as embed_texts() so any caller can get raw vectors, and as
get_embedding_function() for modules (chroma_client) that want to attach the
function directly to a Collection so Chroma can embed on add/upsert/query
without the caller ever handling vectors manually.
"""

from __future__ import annotations

from functools import lru_cache

from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from commute_agent.core.exceptions import EmbeddingError
from commute_agent.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_embedding_function() -> ONNXMiniLM_L6_V2:
    """Return the shared local embedding function (cached after first call)."""
    logger.debug("Loading local ONNX MiniLM-L6-v2 embedding function")
    return ONNXMiniLM_L6_V2()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts and return their float vectors.

    Raises EmbeddingError on failure so callers can handle gracefully.
    """
    if not texts:
        return []

    logger.debug("Embedding %d text(s) locally", len(texts))
    try:
        embed_fn = get_embedding_function()
        return list(embed_fn(texts))
    except Exception as exc:
        raise EmbeddingError(f"Embedding call failed: {exc}") from exc
