"""Pydantic request/response schemas for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    user_query: str = Field(..., min_length=1, max_length=500)


class Provenance(BaseModel):
    """Where a value came from and whether anyone checked it.

    Carried on routes, on individual legs, and on fare estimates. Documented
    here as a type even though routes travel the wire as `dict[str, Any]`, so
    a client has one place to read the contract from.

    `verified` is a claim about validation done in this repository, not about
    the upstream feed's own quality — see `domain/provenance.py`.
    """

    source: Optional[str] = None
    verified: bool = False
    captured_date: Optional[str] = None


class PlanTotalFare(BaseModel):
    """A plan's fare, summed over its legs.

    `amount` is None — never 0 — when nothing could be priced, and `complete`
    is false whenever any leg's fare was missing. A client must render an
    incomplete total as a floor ("at least LKR X"), not as the price.

    `uncertainty_pct` is the widest leg's margin, not an average: a total is
    only as certain as its least certain component.
    """

    currency: str = "LKR"
    amount: Optional[int] = None
    max_amount: Optional[int] = None
    uncertainty_pct: float = 0.0
    complete: bool = False
    priced_legs: int = 0
    total_legs: int = 0
    estimated: bool = True
    verified: bool = False
    source: Optional[str] = None
    captured_date: Optional[str] = None


class PlanVariant(BaseModel):
    """One named plan — see graph/plan_variants.py.

    Every field defaults, so a variant the backend stops emitting degrades to
    a sparse card rather than a validation error on the whole turn.
    """

    variant_id: str = ""
    label: str = ""
    """Names every strategy this route won — "Fastest & cheapest" when two
    strategies picked it. Identical picks collapse to one card."""

    strategies: list[str] = Field(default_factory=list)
    blurb: str = ""

    route_id: str = ""
    line: str = ""
    transit_mode: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    total_duration_min: Optional[int] = None

    total_fare: PlanTotalFare = Field(default_factory=PlanTotalFare)
    legs: list[dict[str, Any]] = Field(default_factory=list)

    provenance_summary: str = "estimated"
    """verified | partially_verified | estimated, across every leg."""

    times_source: Optional[str] = None
    """Where the displayed departure and arrival came from — not necessarily
    the legs' source, since local data can replace a route's headline times
    while leaving the per-leg times as Maps recorded them."""

    times_overridden: bool = False

    missed_deadline: bool = False
    departs_before_requested: bool = False


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

    plan_variants: list[PlanVariant] = Field(default_factory=list)
    """Fastest / cheapest / balanced, each independently costed. Additive:
    `candidate_routes` and `ranked_routes` above are unchanged, so a client
    that ignores this field behaves exactly as before."""

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


class BookingRequest(BaseModel):
    """One tap. Pickup and drop-off are the leg's endpoints, time is now, and
    the only genuine choice is the class of vehicle."""

    session_id: str = Field(..., min_length=1, max_length=64)
    pickup: str = Field(..., min_length=1, max_length=200)
    dropoff: str = Field(..., min_length=1, max_length=200)
    ride_class: str = Field(default="tuk", max_length=32)
    """bike | tuk | car, or any synonym ride_service.normalize_vehicle knows."""


class RideClassOption(BaseModel):
    """One bookable vehicle class for a segment, with its simulated price."""

    ride_class: str
    label: str
    available: bool
    price: Optional[int] = None
    eta_min: Optional[int] = None
    distance_km: Optional[float] = None
    currency: str = "LKR"
    simulated: bool = True
    disclaimer: str = ""


class RideClassOptions(BaseModel):
    """What can be booked for a segment right now.

    Exists so the booking action stays one tap: the UI offers only classes
    that will actually succeed, rather than letting the commuter pick one and
    then telling them it isn't available. It asks nothing of the commuter — it
    is a lookup, not a question.
    """

    pickup: str
    dropoff: str
    options: list[RideClassOption] = Field(default_factory=list)
    already_booked: bool = False
    """True when this session has already booked this exact segment. The UI
    hides the action rather than offering the same ride twice."""

    simulated: bool = True
    disclaimer: str = ""


class SimulatedBookingOut(BaseModel):
    """A booking that is not a booking.

    `simulated` is always true and `disclaimer` is always populated. Both come
    from the backend rather than being asserted by the UI, so a client cannot
    render this as a real confirmation by omitting a badge.
    """

    booking_ref: str
    pickup: str
    dropoff: str
    ride_class: str
    ride_class_label: str

    eta_min: int
    """Minutes until the ride reaches the pickup point."""

    ride_duration_min: int
    """Minutes in the vehicle."""

    price: int
    currency: str = "LKR"
    distance_km: float
    booked_at: str

    simulated: bool = True
    disclaimer: str = ""
    source: Optional[str] = None
    verified: bool = False


class BookingResponse(BaseModel):
    """The booking, and the journey that follows it."""

    booking: SimulatedBookingOut
    session_id: str

    terminal: bool = False
    """True when the drop-off is the commuter's final destination — there is
    nothing left to plan, so no replan ran."""

    replanned: bool = False
    replan_departure_time: Optional[str] = None
    """HH:MM the onward journey was planned from: booking time + eta_min +
    ride_duration_min. Never "now" — a connecting service that leaves before
    the ride arrives is not a connection."""

    replan_offset_min: int = 0
    """eta_min + ride_duration_min, published so the arithmetic is checkable
    from the response alone."""

    final_destination: Optional[str] = None
    onward_plan: Optional[AgentResponse] = None
    """Full agent state for the remainder of the journey. Same shape as a
    /chat plan, so the frontend renders it with the same component."""

    booked_segments: list[str] = Field(default_factory=list)
    """Normalised keys of every segment booked in this session. The UI hides
    the book action for these, so a segment can't be offered twice."""

    message: str = ""
    detail: str = ""


class DisruptionInfo(BaseModel):
    disruption_id: str
    train_id: str = ""
    affected_segment: str = ""
    type: str = ""
    delay_minutes: Optional[int] = None
    active: bool = False
    message: str = ""
