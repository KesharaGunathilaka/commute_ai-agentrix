"""
Guardrails applied before and after LLM calls.

Keeps the agent's behaviour predictable and safe:
- Input sanitisation (strip PII-like patterns, enforce length limits)
- Output validation (confirm required JSON keys are present)
- Off-topic detection (reject non-transport queries early)
- Mode-preference validation (an LLM claim of "user asked for train/bus" must
  be backed by that keyword actually appearing in the message)
"""

from __future__ import annotations

import re
from typing import Optional

from commute_agent.core.exceptions import NLUParseError, OffTopicQueryError
from commute_agent.core.logging import get_logger

logger = get_logger(__name__)

_MAX_QUERY_LENGTH = 500

_OFF_TOPIC_PATTERNS = [
    # NOTE: deliberately excludes "price"/"fare" — ticket-price questions are
    # a normal, on-topic thing for commuters to ask a transit assistant.
    r"\b(weather|stock|cricket|football|politics|recipe)\b",
]

_REQUIRED_PARSED_KEYS = {"language", "origin", "destination", "requested_time", "preferred_mode", "raw_intent"}
_REQUIRED_RESPONSE_KEYS = {"final_response_native", "final_response_en"}

_MODE_KEYWORDS = {
    "train": ("train", "ට්‍රේන්", "ரயில்"),
    "bus": ("bus", "බස්", "பஸ்"),
}


def sanitise_query(raw: str) -> str:
    """Strip excessive whitespace and enforce length cap."""
    cleaned = " ".join(raw.split())
    if len(cleaned) > _MAX_QUERY_LENGTH:
        logger.warning("Query truncated from %d to %d chars", len(cleaned), _MAX_QUERY_LENGTH)
        cleaned = cleaned[:_MAX_QUERY_LENGTH]
    return cleaned


def check_off_topic(query: str) -> None:
    """Raise OffTopicQueryError if the query is clearly not transport-related."""
    lower = query.lower()
    for pattern in _OFF_TOPIC_PATTERNS:
        if re.search(pattern, lower):
            raise OffTopicQueryError(f"Query appears off-topic: {query!r}")


def validate_parsed_intent(data: dict) -> None:
    """Raise NLUParseError if required keys are missing from parsed LLM output."""
    missing = _REQUIRED_PARSED_KEYS - data.keys()
    if missing:
        raise NLUParseError(f"Parsed intent missing keys: {missing}")
    if data.get("raw_intent") == "off_topic":
        raise OffTopicQueryError("LLM classified query as off-topic.")


def validate_mode_change(
    raw_message: str, previous_mode: Optional[str], new_mode: Optional[str]
) -> Optional[str]:
    """
    Only accept a preferred_mode CHANGE if the corresponding keyword actually
    appears in the commuter's raw message.

    The parse_query / parse_update prompts ask the LLM to only set "train" or
    "bus" when the commuter says so — but that's a prompt-level instruction,
    not an enforced guarantee, and the LLM can misclassify or re-derive a
    mode preference on a later turn that never mentioned mode at all (e.g.
    while answering "what time are you leaving?"). Since the Responder later
    tells the commuter "you specifically requested train/bus", a false
    positive here is directly user-visible and misleading, so it's enforced
    here rather than trusted from the LLM.

    A value that hasn't changed from before (carried forward from an earlier,
    already-validated turn) is left untouched — this only gates NEW claims.
    """
    if new_mode == previous_mode:
        return new_mode
    if new_mode not in _MODE_KEYWORDS:
        return new_mode

    lower = raw_message.lower()
    if any(kw.lower() in lower for kw in _MODE_KEYWORDS[new_mode]):
        return new_mode

    logger.warning(
        "Rejected preferred_mode change %r -> %r: no matching keyword in message %r",
        previous_mode, new_mode, raw_message[:80],
    )
    return previous_mode


def validate_response_output(data: dict) -> None:
    """Raise NLUParseError if the response dict is missing required language fields."""
    missing = _REQUIRED_RESPONSE_KEYS - data.keys()
    if missing:
        raise NLUParseError(f"Generated response missing keys: {missing}")
    for key in _REQUIRED_RESPONSE_KEYS:
        if not data.get(key):
            raise NLUParseError(f"Generated response has empty value for '{key}'")
