"""UI-agnostic conversational intake.

The multi-turn journey intake (origin -> destination -> departure -> deadline)
used to live inside the Streamlit app, which meant it could not be reused by
any other frontend. It lives here now so both the Streamlit UI and the HTTP
API drive the exact same state machine.

Nothing in this package imports Streamlit, FastAPI, or any other framework.
"""

from commute_agent.conversation.intake import (
    WELCOME,
    ClarificationKind,
    IntakeResult,
    JourneyIntent,
    TurnOutcome,
    advance,
    intent_changed,
    language_of,
    next_clarification,
    plan_intent,
)

__all__ = [
    "WELCOME",
    "ClarificationKind",
    "IntakeResult",
    "JourneyIntent",
    "TurnOutcome",
    "advance",
    "intent_changed",
    "language_of",
    "next_clarification",
    "plan_intent",
]
