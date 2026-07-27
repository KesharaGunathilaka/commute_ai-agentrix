"""Multi-turn journey intake state machine.

Collects the four journey fields over as many turns as it takes:

    origin -> destination -> departure time -> arrival deadline

The caller owns storage. `advance()` is a pure function: it takes the intent
so far plus the commuter's latest message and returns a new intent alongside
whatever should happen next. That keeps the machine testable and lets the
Streamlit session_state and the API's session store share one implementation.

`_awaiting` records which question was actually just asked, so the reply is
always attributed to the right field. The earlier Streamlit version inferred
this from a combination of `_time_asked` / `_arrival_asked` booleans, which
misfiled every departure-time answer as the arrival deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from commute_agent.core.exceptions import NLUParseError, OffTopicQueryError
from commute_agent.core.logging import get_logger
from commute_agent.nlu.parser import parse_query, parse_update

logger = get_logger(__name__)

# Journey fields that actually affect planning. Bookkeeping keys (prefixed with
# an underscore) are deliberately excluded — they track the conversation, not
# the journey, and must never trigger a replan.
PLANNING_FIELDS = (
    "origin",
    "destination",
    "requested_time",
    "preferred_mode",
    "expected_arrival_time",
    "optimise_for",
)

# Answers that explicitly decline to give a departure time / arrival deadline.
_SKIP_DEPARTURE = {"now", "skip", "asap", "any", "anytime", "whenever"}
_SKIP_ARRIVAL = {"no", "none", "skip", "n", "no deadline", "nope", "not really"}

JourneyIntent = dict[str, Any]


class ClarificationKind(str, Enum):
    """Which field the pending question is trying to fill."""

    BOTH = "both"
    ORIGIN = "origin"
    DESTINATION = "destination"
    TIME = "time"
    ARRIVAL = "arrival"


class TurnOutcome(str, Enum):
    """What the caller should do with the result of `advance()`."""

    CLARIFY = "clarify"
    """Ask `message` and wait — more journey detail is still needed."""

    PLAN = "plan"
    """Every field is collected and something changed: run the graph."""

    UNCHANGED = "unchanged"
    """Fields are complete but identical to the last plan: re-offer the result."""

    RESTART = "restart"
    """Commuter asked to start over; the intent has been cleared."""

    OFF_TOPIC = "off_topic"
    """Query isn't about Sri Lanka public transport."""

    PARSE_ERROR = "parse_error"
    """NLU could not understand the message."""


# ── Question templates ────────────────────────────────────────────────────────
# Keyed by language code, with English as the fallback for anything unmapped.

_ASK_BOTH = {
    "en": "Sure! Where would you like to travel? Tell me your **departure station** and **destination**. 🚉",
    "si": "ඔබ ගමන් යන ආරම්භ ස්ථානය සහ ගමනාන්තය කරුණාකර සඳහන් කරන්න. 🚉",
    "ta": "நீங்கள் எங்கிருந்து எங்கே பயணிக்க விரும்புகிறீர்கள் என்று சொல்லுங்கள். 🚉",
}
_ASK_ORIGIN = {
    "en": "Got it — heading to **{destination}**. Where will you be **departing from**?",
    "si": "**{destination}** ගමනාන්තය හොඳයි. ඔබ ගමන් ආරම්භ කරන **ස්ථානය** කුමක්ද?",
    "ta": "**{destination}** க்கு செல்கிறீர்கள். நீங்கள் **எங்கிருந்து** புறப்படுவீர்கள்?",
}
_ASK_DESTINATION = {
    "en": "Departing from **{origin}**. Where would you like to **go**?",
    "si": "**{origin}** සිට ගමන් ආරම්භ. ඔබ **ගමන් යන ස්ථානය** කුමක්ද?",
    "ta": "**{origin}** இலிருந்து புறப்படுகிறீர்கள். நீங்கள் **எங்கே போக** விரும்புகிறீர்கள்?",
}
_ASK_TIME = {
    "en": "Great! What time are you planning to **depart**? (e.g. 08:30) — or say 'now' to skip.",
    "si": "ඔබ **ගමන් ආරම්භ කරන වේලාව** කුමක්ද? (උදා: 08:30) — 'now' ලෙස කිව්වොත් skip කළ හැක.",
    "ta": "நீங்கள் **புறப்படும் நேரம்** என்ன? (எ.கா: 08:30) — 'now' என்று சொன்னால் தவிர்க்கலாம்.",
}
_ASK_ARRIVAL = {
    "en": "Do you have an **arrival deadline**? (e.g. 'must be there by 10:00') — or say 'no' to skip.",
    "si": "**ළඟා විය යුතු කාලය** තිබේද? (උදා: '10:00 ට කලින් ළඟා විය යුතුයි') — 'no' ලෙස skip කළ හැක.",
    "ta": "**வருவதற்கான காலக்கெடு** உண்டா? (எ.கா: '10:00 மணிக்கு முன்') — 'no' என்று சொன்னால் தவிர்க்கலாம்.",
}
_RESTART = {
    "en": "Sure, let's start fresh! Where would you like to travel?",
    "si": "හරි, අලුතින් පටන් ගමු! ඔබ කොහේට යන්න කැමතිද?",
    "ta": "சரி, புதிதாக ஆரம்பிக்கலாம்! நீங்கள் எங்கே பயணிக்க விரும்புகிறீர்கள்?",
}
_OFF_TOPIC = {
    "en": (
        "I can only help with public transport journeys in Sri Lanka. "
        "Please ask about a train or bus route."
    ),
    "si": "මට උදව් කළ හැක්කේ ශ්‍රී ලංකාවේ පොදු ප්‍රවාහන ගමන් සම්බන්ධව පමණි. දුම්රිය හෝ බස් මාර්ගයක් ගැන අසන්න.",
    "ta": "இலங்கையின் பொதுப் போக்குவரத்து பயணங்களுக்கு மட்டுமே உதவ முடியும். ரயில் அல்லது பேருந்து வழி பற்றி கேளுங்கள்.",
}

WELCOME = {
    "en": (
        "Welcome! I'm **CommuteAI** 🚂\n\n"
        "I can help you plan train and bus journeys across Sri Lanka — "
        "ask me in **English**, **Sinhala (සිංහල)**, or **Tamil (தமிழ்)**.\n\n"
        "Where would you like to travel today?"
    ),
    "si": (
        "ආයුබෝවන්! මම **CommuteAI** 🚂\n\n"
        "ශ්‍රී ලංකාව පුරා දුම්රිය සහ බස් ගමන් සැලසුම් කිරීමට මට උදව් කළ හැක.\n\n"
        "අද ඔබ කොහේට යන්න කැමතිද?"
    ),
    "ta": (
        "வணக்கம்! நான் **CommuteAI** 🚂\n\n"
        "இலங்கை முழுவதும் ரயில் மற்றும் பேருந்து பயணங்களைத் திட்டமிட உதவ முடியும்.\n\n"
        "இன்று நீங்கள் எங்கே பயணிக்க விரும்புகிறீர்கள்?"
    ),
}


def _t(table: dict[str, str], lang: str) -> str:
    """Look up a template by language, falling back to English."""
    return table.get(lang, table["en"])


@dataclass
class IntakeResult:
    """Everything the caller needs after feeding one message to the machine."""

    outcome: TurnOutcome
    intent: JourneyIntent
    """The updated intent — always store this, whatever the outcome."""

    message: str = ""
    """Text to show the commuter. Empty when outcome is PLAN (the graph's
    responder produces the reply in that case)."""

    clarification: Optional[ClarificationKind] = None
    """Which field the pending question targets, when outcome is CLARIFY."""

    detail: str = ""
    """Diagnostic context for PARSE_ERROR — safe to surface, never the only text."""

    @property
    def should_plan(self) -> bool:
        return self.outcome is TurnOutcome.PLAN


def language_of(intent: JourneyIntent) -> str:
    return intent.get("language") or "en"


def plan_intent(intent: JourneyIntent) -> JourneyIntent:
    """Strip conversation bookkeeping, leaving only what the graph consumes."""
    return {k: v for k, v in intent.items() if not k.startswith("_")}


def intent_changed(previous: Optional[JourneyIntent], current: JourneyIntent) -> bool:
    """True when any planning-relevant field differs from the last planned run."""
    if previous is None:
        return True
    return any(previous.get(k) != current.get(k) for k in PLANNING_FIELDS)


def next_clarification(
    intent: JourneyIntent,
) -> Optional[tuple[ClarificationKind, str]]:
    """Return the next question to ask, or None when the intent is complete.

    Order matters: stations first (planning is impossible without them), then
    departure time, then the optional arrival deadline.
    """
    lang = language_of(intent)
    origin = intent.get("origin")
    destination = intent.get("destination")

    # "Resolved" covers both paths: the commuter volunteered a time up front,
    # or we asked and they answered (including a skip).
    time_resolved = intent.get("requested_time") is not None or intent.get("_time_asked")

    if not origin and not destination:
        return ClarificationKind.BOTH, _t(_ASK_BOTH, lang)
    if not origin:
        return ClarificationKind.ORIGIN, _t(_ASK_ORIGIN, lang).format(destination=destination)
    if not destination:
        return ClarificationKind.DESTINATION, _t(_ASK_DESTINATION, lang).format(origin=origin)
    if not time_resolved:
        return ClarificationKind.TIME, _t(_ASK_TIME, lang)
    if not intent.get("_arrival_asked"):
        return ClarificationKind.ARRIVAL, _t(_ASK_ARRIVAL, lang)
    return None


def _apply_departure_answer(message: str, intent: JourneyIntent) -> JourneyIntent:
    """Fold a reply to the departure-time question into the intent.

    A full re-parse runs here rather than a time-only extraction, because
    commuters routinely correct themselves at this point ("8am, and actually
    make that from Maradana"). Only the departure time is forced to None on a
    skip — the other fields keep whatever the parse found.
    """
    updated = dict(intent)
    if message.strip().lower() in _SKIP_DEPARTURE:
        updated["requested_time"] = None
        return updated

    try:
        parsed = parse_update(message, intent)
    except (NLUParseError, OffTopicQueryError) as exc:
        # Not worth failing the turn over: the commuter can restate the time,
        # and everything else in the intent is still valid.
        logger.info("Could not parse departure-time answer %r: %s", message[:60], exc)
        updated["requested_time"] = None
        return updated

    updated.update(
        origin=parsed.origin,
        destination=parsed.destination,
        requested_time=parsed.requested_time,
        expected_arrival_time=parsed.expected_arrival_time,
        preferred_mode=parsed.preferred_mode,
        optimise_for=parsed.optimise_for,
    )
    return updated


def _apply_arrival_answer(message: str, intent: JourneyIntent) -> JourneyIntent:
    """Fold a reply to the arrival-deadline question into the intent.

    Unlike the departure answer this touches only `expected_arrival_time` —
    by this point every other field is settled, and letting a terse "by 10"
    re-write the stations would do more harm than good.
    """
    updated = dict(intent)
    if message.strip().lower() in _SKIP_ARRIVAL:
        updated["expected_arrival_time"] = None
        return updated

    try:
        parsed = parse_update(message, intent)
        updated["expected_arrival_time"] = parsed.expected_arrival_time
    except (NLUParseError, OffTopicQueryError) as exc:
        logger.info("Could not parse arrival-deadline answer %r: %s", message[:60], exc)
        updated["expected_arrival_time"] = None
    return updated


def _parse_fresh_turn(message: str, intent: JourneyIntent) -> JourneyIntent:
    """Parse a normal (non-answer) turn, merging into any existing intent."""
    parsed = parse_update(message, intent) if intent else parse_query(message)
    return {
        "origin": parsed.origin,
        "destination": parsed.destination,
        "requested_time": parsed.requested_time,
        "expected_arrival_time": parsed.expected_arrival_time,
        "preferred_mode": parsed.preferred_mode,
        "optimise_for": parsed.optimise_for,
        "language": str(parsed.language),
        # Carry conversation bookkeeping across the turn.
        "_time_asked": intent.get("_time_asked", False),
        "_arrival_asked": intent.get("_arrival_asked", False),
        "_awaiting": None,
    }


def advance(
    message: str,
    intent: Optional[JourneyIntent] = None,
    last_planned: Optional[JourneyIntent] = None,
) -> IntakeResult:
    """Feed one commuter message into the intake machine.

    Args:
        message: Raw text from the commuter, in any supported language.
        intent: Journey intent accumulated so far; None/empty on the first turn.
        last_planned: The intent used for the most recent successful graph run,
            so an unchanged repeat can be answered without replanning.

    Returns:
        An IntakeResult carrying the updated intent and the next action.
    """
    intent = dict(intent or {})
    awaiting = intent.get("_awaiting")

    # ── Targeted answers to a question we just asked ──────────────────────────
    # Dispatch on `_awaiting` alone. Whichever question was displayed set this,
    # so there is no ambiguity about which field the reply belongs to.
    if awaiting == ClarificationKind.TIME.value:
        intent = _apply_departure_answer(message, intent)
        intent["_awaiting"] = None
    elif awaiting == ClarificationKind.ARRIVAL.value:
        intent = _apply_arrival_answer(message, intent)
        intent["_awaiting"] = None
    else:
        # ── Normal NLU turn ──────────────────────────────────────────────────
        had_intent = bool(intent)
        try:
            intent = _parse_fresh_turn(message, intent)
        except OffTopicQueryError:
            return IntakeResult(
                outcome=TurnOutcome.OFF_TOPIC,
                intent=intent,
                message=_t(_OFF_TOPIC, language_of(intent)),
            )
        except NLUParseError as exc:
            return IntakeResult(
                outcome=TurnOutcome.PARSE_ERROR,
                intent=intent,
                message="Sorry, I couldn't understand that. Could you rephrase?",
                detail=str(exc),
            )

        # An established journey that parses to no stations at all reads as
        # "forget that, start over" rather than as a refinement.
        if had_intent and not intent.get("origin") and not intent.get("destination"):
            lang = language_of(intent)
            return IntakeResult(
                outcome=TurnOutcome.RESTART,
                intent={},
                message=_t(_RESTART, lang),
            )

    # ── Anything still missing? ───────────────────────────────────────────────
    clarification = next_clarification(intent)
    if clarification is not None:
        kind, question = clarification
        # Record that this question was asked, so a skip still counts as
        # resolved and the next turn is attributed to the right field.
        if kind is ClarificationKind.TIME:
            intent["_time_asked"] = True
            intent["_awaiting"] = ClarificationKind.TIME.value
        elif kind is ClarificationKind.ARRIVAL:
            intent["_arrival_asked"] = True
            intent["_awaiting"] = ClarificationKind.ARRIVAL.value
        return IntakeResult(
            outcome=TurnOutcome.CLARIFY,
            intent=intent,
            message=question,
            clarification=kind,
        )

    # ── Complete — plan, unless nothing actually changed ──────────────────────
    ready = plan_intent(intent)
    if not intent_changed(last_planned, ready):
        return IntakeResult(
            outcome=TurnOutcome.UNCHANGED,
            intent=intent,
            message=(
                f"Your journey from **{ready.get('origin')}** to "
                f"**{ready.get('destination')}** is still planned above. "
                f"Want to change the **time**, **mode**, or **destination**?"
            ),
        )

    return IntakeResult(outcome=TurnOutcome.PLAN, intent=intent)
