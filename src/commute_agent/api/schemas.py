"""Pydantic request/response schemas for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    user_query: str = Field(..., min_length=1, max_length=500)


class AgentResponse(BaseModel):
    """The full agent state, flattened for the wire.

    Every planning-relevant field of AgentState is exposed. An earlier version
    published only a handful, which meant a client had no way to render the
    ranked alternatives or the ride-hailing fallbacks the agent had already
    computed — the work was done and then dropped on the way out.

    `tts_audio` is the one deliberate omission: raw MP3 bytes don't belong in
    a JSON payload. Clients fetch audio from POST /api/v1/tts instead.
    """

    user_query: str
    language: str
    origin: Optional[str] = None
    destination: Optional[str] = None
    requested_time: Optional[str] = None
    expected_arrival_time: Optional[str] = None
    preferred_mode: Optional[str] = None
    optimise_for: Optional[str] = None

    # Routes
    candidate_route: Optional[dict[str, Any]] = None
    candidate_routes: list[dict[str, Any]] = Field(default_factory=list)
    ranked_routes: list[dict[str, Any]] = Field(default_factory=list)
    alternative_route: Optional[dict[str, Any]] = None

    # Disruption
    disruption_status: Optional[dict[str, Any]] = None
    original_disruption: Optional[dict[str, Any]] = None
    replan_attempts: int = 0

    # Ride-hailing
    uber_options: Optional[list[dict[str, Any]]] = None
    uber_last_mile: Optional[list[dict[str, Any]]] = None
    uber_last_mile_distance_m: Optional[int] = None
    last_mile_transit_leg: Optional[dict[str, Any]] = None

    # Response
    final_response_native: str = ""
    final_response_en: str = ""

    trace: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "AgentResponse":
        """Project an AgentState onto the wire schema, dropping unknown keys."""
        return cls(**{k: v for k, v in state.items() if k in cls.model_fields})


class ChatRequest(BaseModel):
    """One turn of the conversation."""

    message: str = Field(..., min_length=1, max_length=500)
    session_id: Optional[str] = Field(
        default=None,
        description="Omit on the first turn; the response returns an id to reuse.",
    )


TurnKind = Literal["clarify", "plan", "unchanged", "restart", "off_topic", "parse_error", "error"]


class JourneySummary(BaseModel):
    """The journey as understood so far — drives the sidebar summary.

    Bookkeeping fields (`_awaiting` and friends) are intentionally not here;
    they steer the state machine and mean nothing to a commuter.
    """

    origin: Optional[str] = None
    destination: Optional[str] = None
    requested_time: Optional[str] = None
    expected_arrival_time: Optional[str] = None
    preferred_mode: Optional[str] = None
    optimise_for: Optional[str] = None
    language: str = "en"

    @classmethod
    def from_intent(cls, intent: dict[str, Any]) -> "JourneySummary":
        return cls(**{k: v for k, v in intent.items() if k in cls.model_fields})


class ChatResponse(BaseModel):
    """The assistant's reply to one turn."""

    session_id: str
    kind: TurnKind
    """What happened. `plan` means `state` is populated; every other kind is
    conversational and carries only `message`."""

    message: str = ""
    """Assistant text, in the commuter's language."""

    message_en: str = ""
    """English gloss. Equals `message` when the conversation is in English;
    always the text used for read-aloud."""

    clarification: Optional[str] = None
    """Which field a `clarify` turn is asking about — lets the UI hint the
    expected answer (a time picker for `time`, station suggestions for
    `origin`, and so on)."""

    journey: JourneySummary = Field(default_factory=JourneySummary)
    state: Optional[AgentResponse] = None
    detail: str = ""
    """Diagnostic context for error kinds. Never the only text shown."""


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    lang: str = Field(default="en", max_length=8)


class ConfigResponse(BaseModel):
    """What the frontend needs to know about this backend's capabilities.

    The Maps key is returned rather than baked into the frontend build so the
    UI can degrade to a stop-list view when no key is configured, instead of
    rendering a broken map.
    """

    maps_browser_key: str = ""
    maps_enabled: bool = False
    max_replan_attempts: int = 2
    supported_languages: list[str] = Field(default_factory=lambda: ["en", "si", "ta"])


class DisruptionInfo(BaseModel):
    disruption_id: str
    train_id: str = ""
    affected_segment: str = ""
    type: str = ""
    delay_minutes: Optional[int] = None
    active: bool = False
    message: str = ""
