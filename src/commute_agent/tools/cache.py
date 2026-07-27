"""
Simple in-memory TTL cache shared across all tools.

Design goals:
- Avoid redundant Chroma / Gemini calls for the same query within a session.
- Thread-safe for Streamlit's rerun model (single-threaded per session).
- TTL configured from settings.yaml (default 5 min).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger

logger = get_logger(__name__)

_store: dict[str, tuple[Any, float]] = {}  # key → (value, expiry_timestamp)


def _ttl() -> int:
    return get_settings().cache_ttl_seconds


def _key(*args: Any) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(cache_key: str) -> Optional[Any]:
    """Return cached value if still within TTL, else None."""
    if not get_settings().cache_enabled:
        return None
    entry = _store.get(cache_key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() > expiry:
        del _store[cache_key]
        logger.debug("Cache expired for key=%s", cache_key[:16])
        return None
    logger.debug("Cache hit for key=%s", cache_key[:16])
    return value


def set(cache_key: str, value: Any) -> None:
    """Store value with TTL expiry."""
    if not get_settings().cache_enabled:
        return
    _store[cache_key] = (value, time.monotonic() + _ttl())
    logger.debug("Cache set for key=%s (ttl=%ds)", cache_key[:16], _ttl())


def make_key(*args: Any) -> str:
    return _key(*args)


def invalidate_all() -> None:
    """Clear the entire cache — useful in tests or after data reload."""
    _store.clear()
    logger.info("Cache cleared.")
