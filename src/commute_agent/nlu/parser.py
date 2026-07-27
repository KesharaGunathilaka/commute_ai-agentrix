"""
NLU query parser — parse_query(user_query) → ParsedIntent.

Uses Groq (llama-3.3-70b-versatile) with a strict JSON output schema.
Retries once on parse failure, then raises NLUParseError.
"""

from __future__ import annotations

import json

from langchain_groq import ChatGroq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from commute_agent.core.config import get_settings
from commute_agent.core.exceptions import NLUParseError
from commute_agent.core.guardrails import (
    check_off_topic,
    sanitise_query,
    validate_mode_change,
    validate_parsed_intent,
)
from commute_agent.core.logging import get_logger
from commute_agent.nlu.models import ParsedIntent

logger = get_logger(__name__)


def parse_update(message: str, current_intent: dict) -> ParsedIntent:
    """
    Parse a follow-up message against an existing accumulated intent.

    Merges new information with what is already known rather than starting
    from scratch. Falls back to the current intent unchanged if the message
    is off-topic or cannot be parsed.
    """
    cleaned = sanitise_query(message)
    settings = get_settings()
    prompt = settings.prompts_config["parse_update"].format(
        message=cleaned,
        origin=current_intent.get("origin") or "not specified",
        destination=current_intent.get("destination") or "not specified",
        requested_time=current_intent.get("requested_time") or "not specified",
        expected_arrival_time=current_intent.get("expected_arrival_time") or "not specified",
        preferred_mode=current_intent.get("preferred_mode") or "any",
        optimise_for=current_intent.get("optimise_for") or "not specified",
    )

    try:
        raw_json = _call_llm_with_raw_prompt(prompt)
    except NLUParseError:
        return ParsedIntent(
            language=current_intent.get("language", "en"),
            origin=current_intent.get("origin"),
            destination=current_intent.get("destination"),
            requested_time=current_intent.get("requested_time"),
            expected_arrival_time=current_intent.get("expected_arrival_time"),
            preferred_mode=current_intent.get("preferred_mode"),
            optimise_for=current_intent.get("optimise_for"),
            raw_intent="parse_error_fallback",
        )

    if raw_json.get("raw_intent") == "off_topic":
        return ParsedIntent(
            language=current_intent.get("language", "en"),
            origin=current_intent.get("origin"),
            destination=current_intent.get("destination"),
            requested_time=current_intent.get("requested_time"),
            expected_arrival_time=current_intent.get("expected_arrival_time"),
            preferred_mode=current_intent.get("preferred_mode"),
            optimise_for=current_intent.get("optimise_for"),
            raw_intent="no_change",
        )

    intent = ParsedIntent(**raw_json)
    intent.preferred_mode = validate_mode_change(
        cleaned, current_intent.get("preferred_mode"), intent.preferred_mode
    )
    return intent


def parse_query(user_query: str) -> ParsedIntent:
    """
    Parse a raw commuter query (any language) into a structured ParsedIntent.

    Applies input guardrails before calling the LLM, and validates output
    schema strictly — raises NLUParseError if the LLM response cannot be parsed
    after one retry.
    """
    cleaned = sanitise_query(user_query)
    check_off_topic(cleaned)

    try:
        raw_json = _call_llm_with_retry(cleaned)
    except NLUParseError:
        raise

    validate_parsed_intent(raw_json)
    intent = ParsedIntent(**raw_json)
    intent.preferred_mode = validate_mode_change(cleaned, None, intent.preferred_mode)
    return intent


@retry(
    retry=retry_if_exception_type(NLUParseError),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=True,
)
def _call_llm_with_raw_prompt(prompt: str) -> dict:
    """Call Groq with an already-formatted prompt and parse JSON. Retried once on failure."""
    settings = get_settings()
    logger.debug("Calling Groq (raw prompt, first 60 chars=%r)", prompt[:60])
    llm = ChatGroq(
        model=settings.groq_model,
        temperature=settings.gemini_temperature,
        groq_api_key=settings.groq_api_key,
    )
    response = llm.invoke(prompt)
    raw_text: str = response.content
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
    raw_text = stripped.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise NLUParseError(f"LLM returned invalid JSON: {raw_text[:200]}") from exc


def _call_llm_with_retry(query: str) -> dict:
    """Build parse_query prompt and delegate to the raw-prompt LLM helper."""
    settings = get_settings()
    prompt_template: str = settings.prompts_config["parse_query"]
    prompt = prompt_template.format(user_query=query)
    logger.debug("NLU parse query=%r", query[:60])
    return _call_llm_with_raw_prompt(prompt)
