"""
Multilingual response generator.

generate_response(state) → dict with keys:
  final_response_native  — answer in the commuter's detected language
  final_response_en      — English gloss (always present, never behind a toggle)

Produces distinct templates for clear vs disrupted routes.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from langchain_groq import ChatGroq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from commute_agent.core.config import get_settings
from commute_agent.core.exceptions import NLUParseError
from commute_agent.core.guardrails import validate_response_output
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import DisruptionLevel, Language

logger = get_logger(__name__)


def _invoke_llm(prompt: str) -> dict:
    """Call Groq with `prompt`, parse the JSON response, return the dict."""
    settings = get_settings()
    llm = ChatGroq(
        model=settings.groq_model,
        temperature=settings.gemini_temperature,
        groq_api_key=settings.groq_api_key,
    )
    raw_text: str = llm.invoke(prompt).content

    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
    raw_text = stripped.strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise NLUParseError(f"LLM returned invalid JSON: {raw_text[:200]}") from exc


def _calc_duration(dep: str, arr: str) -> str:
    """Return a human-readable duration string from two HH:MM strings."""
    try:
        d = datetime.strptime(dep, "%H:%M")
        a = datetime.strptime(arr, "%H:%M")
        minutes = int((a - d).total_seconds() // 60)
        if minutes < 0:
            minutes += 24 * 60  # overnight journey
        hrs, mins = divmod(minutes, 60)
        if hrs and mins:
            return f"{hrs}h {mins}min"
        if hrs:
            return f"{hrs}h"
        return f"{mins}min"
    except Exception:
        return "unknown"


def _journey_type(route: dict) -> str:
    description = route.get("description", "")
    if "\nStep" in description or "leg journey" in description:
        return "multi-leg journey (transfer required)"
    mode = route.get("transit_mode", "")
    vehicle = route.get("vehicle_type", "").replace("_", " ").title()
    return f"direct {mode} service ({vehicle})" if vehicle else f"direct {mode} service"


def _preferred_mode_note(preferred_mode: Optional[str]) -> str:
    if preferred_mode == "train":
        return "a train journey (user specifically requested train)"
    if preferred_mode == "bus":
        return "a bus journey (user specifically requested bus)"
    return "the fastest available transit option"


# Fallback clarification messages — used when LLM parsing fails
_CLARIFY = {
    Language.SINHALA: "කරුණාකර ඔබගේ ගමනාන්තය සහ ගමන් කරන වේලාව නැවත සඳහන් කරන්න.",
    Language.TAMIL: "தயவுசெய்து உங்கள் பயணத்தின் இலக்கு மற்றும் நேரத்தை மீண்டும் தெரிவிக்கவும்.",
    Language.ENGLISH: "Could you please clarify your destination and preferred travel time?",
}


def generate_response(state: dict) -> dict:
    """
    Build bilingual response text based on current AgentState.

    Always returns both final_response_native and final_response_en.
    Delegates to a distinct prompt template depending on whether replanning
    was ever attempted — NOT just the latest disruption_status level. If a
    replan happened, disruption_status now reflects a check of the
    *alternative* route (which may well be clear); that must still be reported
    as "your original service was disrupted, here's the confirmed alternative"
    rather than as a plain clear-route response.
    """
    language = state.get("language", "en")
    disruption = state.get("disruption_status") or {}
    level = disruption.get("level", DisruptionLevel.CLEAR)
    replanned = state.get("replan_attempts", 0) > 0

    if not replanned and level == DisruptionLevel.CLEAR:
        return _generate_clear_response(state, language)
    elif state.get("alternative_route"):
        return _generate_disrupted_response(state, language)
    else:
        return _generate_no_alternative_response(state, language)


@retry(
    retry=retry_if_exception_type(NLUParseError),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=False,
)
def _generate_clear_response(state: dict, language: str) -> dict:
    """Generate response for a clear, undisrupted route."""
    settings = get_settings()
    route = state.get("candidate_route", {})

    if not route:
        return _clarification_response(language)

    stops: list[str] = route.get("stops", [])
    departure_times: list[str] = route.get("departure_times", [])
    arrival_times: list[str] = route.get("arrival_times", [])
    dep = departure_times[0] if departure_times else ""
    arr = arrival_times[-1] if arrival_times else ""

    prompt_template: str = settings.prompts_config["respond_clear"]
    prompt = prompt_template.format(
        language=language,
        preferred_mode_note=_preferred_mode_note(state.get("preferred_mode")),
        train_id=route.get("line") or route.get("route_id", ""),
        origin=stops[0] if stops else state.get("origin", ""),
        departure_time=dep,
        destination=stops[-1] if stops else state.get("destination", ""),
        arrival_time=arr,
        duration=_calc_duration(dep, arr) if dep and arr else "unknown",
        journey_type=_journey_type(route),
        description=route.get("description", ""),
        stops=", ".join(stops) if stops else "",
    )

    logger.debug("Generating clear-route response in language=%r", language)

    result = _invoke_llm(prompt)
    validate_response_output(result)
    return result


@retry(
    retry=retry_if_exception_type(NLUParseError),
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    reraise=False,
)
def _generate_disrupted_response(state: dict, language: str) -> dict:
    """Generate response for a disrupted route that has a valid alternative."""
    settings = get_settings()
    # Prefer the ORIGINAL disruption (captured before replanning) so the
    # disruption reason/delay is still reported even if the alternative's
    # own disruption_status has since come back clear.
    original_status = state.get("original_disruption") or state.get("disruption_status") or {}
    disruption = original_status.get("disruption") or {}
    original = state.get("candidate_route", {})
    alternative = state.get("alternative_route", {})

    orig_dep_times: list[str] = original.get("departure_times", [])
    alt_dep_times: list[str] = alternative.get("departure_times", [])
    alt_arr_times: list[str] = alternative.get("arrival_times", [])
    alt_dep = alt_dep_times[0] if alt_dep_times else ""
    alt_arr = alt_arr_times[-1] if alt_arr_times else ""

    prompt_template: str = settings.prompts_config["respond_disrupted"]
    prompt = prompt_template.format(
        language=language,
        disruption_type=disruption.get("type", "delay"),
        delay_minutes=disruption.get("delay_minutes", "unknown"),
        original_train_id=original.get("line") or original.get("route_id", ""),
        origin=state.get("origin", ""),
        original_departure=orig_dep_times[0] if orig_dep_times else "",
        alt_train_id=alternative.get("line") or alternative.get("route_id", ""),
        alt_departure=alt_dep,
        destination=state.get("destination", ""),
        alt_arrival=alt_arr,
        alt_duration=_calc_duration(alt_dep, alt_arr) if alt_dep and alt_arr else "unknown",
        alt_description=alternative.get("description", ""),
    )

    logger.debug("Generating disrupted-route response in language=%r", language)

    result = _invoke_llm(prompt)
    validate_response_output(result)
    return result


def _generate_no_alternative_response(state: dict, language: str) -> dict:
    """Generate response when no alternative route is available."""
    settings = get_settings()
    original_status = state.get("original_disruption") or state.get("disruption_status") or {}
    disruption = original_status.get("disruption") or {}

    prompt_template: str = settings.prompts_config["respond_no_alternative"]
    prompt = prompt_template.format(
        language=language,
        disruption_message=disruption.get("message", "Service disrupted."),
    )

    logger.debug("Generating no-alternative response in language=%r", language)

    result = _invoke_llm(prompt)
    validate_response_output(result)
    return result


def _clarification_response(language: str) -> dict:
    """Fallback when the agent lacks enough info to build a real response."""
    msg = _CLARIFY.get(language, _CLARIFY[Language.ENGLISH])
    return {
        "final_response_native": msg,
        "final_response_en": _CLARIFY[Language.ENGLISH],
    }
