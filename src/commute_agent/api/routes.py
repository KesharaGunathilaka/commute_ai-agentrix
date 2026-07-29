"""FastAPI route handlers."""

from __future__ import annotations

import io
import json
from typing import Iterator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from commute_agent.api.schemas import (
    AgentResponse,
    BookingRequest,
    BookingResponse,
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    DisruptionInfo,
    JourneySummary,
    QueryRequest,
    RideClassOption,
    RideClassOptions,
    SimulatedBookingOut,
    TTSRequest,
)
from commute_agent.api.sessions import Session, get_store
from commute_agent.conversation import TurnOutcome, advance, plan_intent
from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger
from commute_agent.graph.builder import (
    run_commute_agent,
    run_commute_agent_from_intent,
    stream_commute_agent_from_intent,
)
from commute_agent.tools.booking_tool import (
    DISCLAIMER as BOOKING_DISCLAIMER,
    RideUnavailableError,
    UnknownRideClassError,
    ride_class_options,
    same_place,
    scope_warning,
    segment_key,
    simulate_booking,
)
from commute_agent.tools.cache import invalidate_all

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["commute"])


# ── Health & capability discovery ─────────────────────────────────────────────


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    """Tell the frontend what this backend can do.

    Chiefly: is there a Maps browser key? Without one the UI shows a stop-list
    instead of a map, rather than an empty grey box.
    """
    settings = get_settings()
    key = settings.google_maps_browser_key
    return ConfigResponse(
        maps_browser_key=key,
        maps_enabled=bool(key),
        max_replan_attempts=settings.max_replan_attempts,
    )


# ── Conversational chat ───────────────────────────────────────────────────────

# Proxies and dev servers buffer streamed responses by default, which would
# defeat the point — these headers ask them not to.
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _reply(session: Session, kind: str, message: str, **extra) -> ChatResponse:
    """Build a ChatResponse from a session, filling in the journey summary."""
    return ChatResponse(
        session_id=session.session_id,
        kind=kind,
        message=message,
        message_en=extra.pop("message_en", None) or message,
        journey=JourneySummary.from_intent(session.intent),
        **extra,
    )


def _finalise_plan(session: Session, state: dict) -> ChatResponse:
    """Record a completed graph run on the session and shape the reply.

    `message` is the commuter's language and `message_en` the English gloss;
    when the conversation is already English the two are the same string. The
    frontend reads `message_en` for read-aloud, so it must never be empty.
    """
    session.last_planned_intent = plan_intent(session.intent)
    session.last_state = state
    get_store().save(session)

    native = state.get("final_response_native", "")
    english = state.get("final_response_en", "")

    return ChatResponse(
        session_id=session.session_id,
        kind="plan",
        message=native or english,
        message_en=english or native,
        journey=JourneySummary.from_intent(session.intent),
        state=AgentResponse.from_state(state),
    )


def _run_intake(message: str, session_id: Optional[str]) -> tuple[Session, object]:
    """Advance the intake machine one turn and persist the resulting intent."""
    store = get_store()
    session = store.get_or_create(session_id)

    result = advance(
        message=message,
        intent=session.intent,
        last_planned=session.last_planned_intent,
    )

    session.intent = result.intent
    if result.outcome is TurnOutcome.RESTART:
        # The machine already cleared the intent; drop the plan history too so
        # the next complete journey is treated as new rather than "unchanged".
        session.last_planned_intent = None
        session.last_state = None
    store.save(session)

    return session, result


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """One conversational turn — the non-streaming path.

    Mirrors /chat/stream exactly, minus the per-node events. Kept for clients
    that don't want SSE (curl, tests, the API docs page).
    """
    session, result = _run_intake(body.message, body.session_id)

    if result.outcome is not TurnOutcome.PLAN:
        return _reply(
            session,
            kind=result.outcome.value,
            message=result.message,
            clarification=result.clarification.value if result.clarification else None,
            detail=result.detail,
        )

    try:
        state = run_commute_agent_from_intent(plan_intent(session.intent))
    except Exception as exc:
        logger.exception("Graph run failed")
        return _reply(
            session,
            kind="error",
            message="Sorry — I couldn't plan that journey just now. Please try again.",
            detail=str(exc),
        )

    return _finalise_plan(session, state)


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame.

    ensure_ascii=False keeps Sinhala and Tamil legible on the wire; the
    response is explicitly UTF-8, so multi-byte characters are safe. The
    payload must not contain a bare newline — json.dumps guarantees that by
    escaping them inside strings.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/chat/stream")
async def chat_stream(
    message: str = Query(..., min_length=1, max_length=500),
    session_id: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """One conversational turn, streamed node by node.

    A GET with query params rather than a POST because the browser EventSource
    API cannot issue a POST — this is the endpoint the chat UI actually uses.

    Event sequence:
      `node`  — once per graph node as it completes (name + running trace)
      `turn`  — exactly one, terminal, carrying the full ChatResponse
      `error` — instead of `turn` if the run failed

    A clarification turn never runs the graph, so it emits `turn` immediately
    with no `node` events at all.
    """
    session, result = _run_intake(message, session_id)

    if result.outcome is not TurnOutcome.PLAN:
        payload = _reply(
            session,
            kind=result.outcome.value,
            message=result.message,
            clarification=result.clarification.value if result.clarification else None,
            detail=result.detail,
        )
        return StreamingResponse(
            iter([_sse("turn", payload.model_dump())]),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    def event_stream() -> Iterator[str]:
        """Sync generator — Starlette runs it in a worker thread, so the
        blocking LangGraph call doesn't stall the event loop."""
        final_state: Optional[dict] = None
        try:
            for node_name, state in stream_commute_agent_from_intent(plan_intent(session.intent)):
                if node_name == "__end__":
                    final_state = state
                    break
                yield _sse("node", {
                    "node": node_name,
                    "trace": state.get("trace", []),
                    # Surfaced live so the UI can flip the trace to a warning
                    # state the moment the monitor finds a disruption, rather
                    # than waiting for the whole run to finish.
                    "disruption_level": (state.get("disruption_status") or {}).get("level"),
                    "replan_attempts": state.get("replan_attempts", 0),
                })
        except Exception as exc:
            logger.exception("Streaming graph run failed")
            yield _sse("error", {
                "session_id": session.session_id,
                "kind": "error",
                "message": "Sorry — I couldn't plan that journey just now. Please try again.",
                "detail": str(exc),
            })
            return

        yield _sse("turn", _finalise_plan(session, final_state or {}).model_dump())

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/session/reset", response_model=ChatResponse)
async def reset_session(session_id: str = Query(...)) -> ChatResponse:
    """Clear a conversation, keeping the id so the client can carry straight on."""
    session = get_store().reset(session_id)
    return _reply(session, kind="restart", message="Started a new journey.")


# ── Text to speech ────────────────────────────────────────────────────────────


@router.post("/tts")
async def tts(body: TTSRequest) -> Response:
    """Synthesise speech for a chat message and return MP3 bytes.

    Server-side rather than browser speechSynthesis because Sinhala and Tamil
    voices are absent on most desktop browsers, and gTTS covers all three
    languages consistently.
    """
    try:
        from gtts import gTTS
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise HTTPException(status_code=503, detail="TTS unavailable: gtts not installed") from exc

    buf = io.BytesIO()
    try:
        gTTS(text=body.text, lang=body.lang, slow=False).write_to_fp(buf)
    except Exception as exc:
        # gTTS rejects unsupported language codes and needs network access;
        # English is the safe retry, and matches what the UI reads aloud anyway.
        logger.warning("gTTS failed for lang=%r (%s) — retrying in English.", body.lang, exc)
        buf = io.BytesIO()
        try:
            gTTS(text=body.text, lang="en", slow=False).write_to_fp(buf)
        except Exception as fallback_exc:
            logger.error("gTTS fallback failed: %s", fallback_exc)
            raise HTTPException(
                status_code=502, detail=f"Speech synthesis failed: {fallback_exc}"
            ) from fallback_exc

    audio = buf.getvalue()
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio)), "Cache-Control": "no-store"},
    )


# ── Simulated ride booking ────────────────────────────────────────────────────


def _strip_booked_ride_offers(state: dict, booked: set[str]) -> dict:
    """Remove ride offers for segments this session has already booked.

    In practice the replan starts *at* the drop-off, so its legs begin at or
    after that point and the just-booked segment cannot recur. The guard is
    here anyway because "in practice it can't happen" is how the first loop
    always gets written, and the cost of being sure is one dict comprehension.
    """
    if not booked:
        return state

    cleaned = dict(state)

    origin = state.get("origin") or ""
    destination = state.get("destination") or ""
    if segment_key(origin, destination) in booked:
        cleaned["uber_options"] = None

    leg = state.get("last_mile_transit_leg") or {}
    last_stops = (state.get("candidate_route") or {}).get("stops") or []
    pickup = leg.get("board_stop") or (last_stops[-1] if last_stops else "")
    if pickup and segment_key(pickup, destination) in booked:
        cleaned["uber_last_mile"] = None
        cleaned["uber_last_mile_distance_m"] = None
        cleaned["last_mile_transit_leg"] = None

    return cleaned


@router.get("/booking/options", response_model=RideClassOptions)
async def booking_options(
    pickup: str = Query(..., min_length=1, max_length=200),
    dropoff: str = Query(..., min_length=1, max_length=200),
    session_id: Optional[str] = Query(default=None),
    leg_distance_m: Optional[int] = Query(default=None, ge=0),
) -> RideClassOptions:
    """What can be booked for one segment, with simulated prices.

    In-process and instant — `ride_service` makes no network call. The point is
    to keep booking a single tap: the UI offers only the classes that will
    succeed, instead of letting the commuter choose one and then discovering
    the dummy's availability flip went against them. It asks the commuter
    nothing.

    `already_booked` reports whether this session has booked this exact
    segment, so the action can be hidden rather than offered twice.
    """
    booked: set[str] = set()
    if session_id:
        session = get_store().get_or_create(session_id)
        booked = {b["segment_key"] for b in session.bookings}

    distance_km = leg_distance_m / 1000 if leg_distance_m else None
    warning = scope_warning(distance_km)
    if warning:
        logger.warning(
            "Booking options for a %.1f km segment %r -> %r — probable mis-scoping.",
            distance_km, pickup, dropoff,
        )

    return RideClassOptions(
        pickup=pickup,
        dropoff=dropoff,
        options=[
            RideClassOption(**option)
            for option in ride_class_options(pickup, dropoff, distance_km=distance_km)
        ],
        already_booked=segment_key(pickup, dropoff) in booked,
        scope_warning=warning,
        disclaimer=BOOKING_DISCLAIMER,
    )


@router.post("/booking/simulate", response_model=BookingResponse)
async def simulate_ride_booking(body: BookingRequest) -> BookingResponse:
    """
    Book a simulated ride for one leg, then replan the rest of the journey.

    **This books nothing.** The price, the ETA and the availability all come
    from `ride_service.py`, a dummy backend; the response says so in
    `simulated` and `disclaimer`, and the UI renders that as a badge.

    The replan is a *re-entry*, not a mutation. Rather than editing the
    existing plan and trying to recompute its connections, the journey ends at
    the drop-off and the ordinary agent entry point is invoked again with a new
    origin and a new departure time. There is one graph and one planning path;
    this endpoint supplies different inputs to it.

    The departure time for that re-entry is:

        booking time + eta_min + ride_duration_min

    not "now". Planning from now would offer a connecting service that departs
    while the commuter is still in the vehicle. `replan_departure_time` and
    `replan_offset_min` are both published so the arithmetic can be checked
    from the response alone.

    The deadline, the mode preference and the optimisation the commuter stated
    are carried from the *original* intent, and the destination is their final
    destination — not the end of the leg being replaced. A drop-off that is
    already the final destination returns the booking alone.
    """
    session = get_store().get_or_create(body.session_id)

    # Judged on the leg's real Maps distance, never on the simulated quote's
    # own — that one is rng.uniform(1.5, 24.0) for an uncurated route and would
    # pass a 119 km leg straight through a 30 km threshold.
    leg_km = body.leg_distance_m / 1000 if body.leg_distance_m else None
    warning = scope_warning(leg_km)
    if warning:
        logger.warning(
            "Simulated booking scoped to a %.1f km segment %r -> %r — this looks "
            "like a whole journey rather than one leg.",
            leg_km, body.pickup, body.dropoff,
        )

    try:
        booking = simulate_booking(
            body.pickup, body.dropoff, body.ride_class, distance_km=leg_km
        )
    except UnknownRideClassError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RideUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{exc} "
                + (
                    f"Available right now: {', '.join(exc.available_classes)}."
                    if exc.available_classes
                    else "No vehicle class is available for this segment."
                )
            ),
        ) from exc

    session.bookings.append({
        "booking": booking.to_dict(),
        "segment_key": segment_key(booking.pickup, booking.dropoff),
    })
    get_store().save(session)

    booked = {b["segment_key"] for b in session.bookings}
    intent = plan_intent(session.intent)
    final_destination = intent.get("destination")

    # Terminal: the ride already ends where the commuter is going.
    if not final_destination or same_place(booking.dropoff, final_destination):
        return BookingResponse(
            booking=SimulatedBookingOut(**booking.to_dict()),
            session_id=session.session_id,
            terminal=True,
            final_destination=final_destination,
            booked_segments=sorted(booked),
            scope_warning=warning,
            message=(
                f"Simulated ride booked to {booking.dropoff}, which is your destination — "
                "nothing further to plan."
            ),
        )

    replan_at = booking.replan_departure_at()
    replan_departure_time = replan_at.strftime("%H:%M")

    # Re-entry. The origin and the departure time are new; everything the
    # commuter actually asked for is carried across unchanged.
    onward_intent = {
        **intent,
        "origin": booking.dropoff,
        "destination": final_destination,
        "requested_time": replan_departure_time,
    }

    logger.info(
        "Booking %s: replanning %r -> %r from %s (now + %d min eta + %d min ride), "
        "deadline=%r optimise_for=%r",
        booking.booking_ref, booking.dropoff, final_destination, replan_departure_time,
        booking.eta_min, booking.ride_duration_min,
        onward_intent.get("expected_arrival_time"), onward_intent.get("optimise_for"),
    )

    try:
        onward_state = run_commute_agent_from_intent(onward_intent)
    except Exception as exc:
        logger.exception("Onward replan failed after booking %s", booking.booking_ref)
        return BookingResponse(
            booking=SimulatedBookingOut(**booking.to_dict()),
            session_id=session.session_id,
            replanned=False,
            replan_departure_time=replan_departure_time,
            replan_offset_min=booking.arrival_offset_min(),
            final_destination=final_destination,
            booked_segments=sorted(booked),
            scope_warning=warning,
            message=(
                f"Simulated ride booked. I couldn't plan the onward journey from "
                f"{booking.dropoff} just now — the booking above still stands."
            ),
            detail=str(exc),
        )

    onward_state = _strip_booked_ride_offers(onward_state, booked)

    return BookingResponse(
        booking=SimulatedBookingOut(**booking.to_dict()),
        session_id=session.session_id,
        replanned=True,
        replan_departure_time=replan_departure_time,
        replan_offset_min=booking.arrival_offset_min(),
        final_destination=final_destination,
        onward_plan=AgentResponse.from_state(onward_state),
        booked_segments=sorted(booked),
            scope_warning=warning,
        message=(
            f"Simulated ride booked from {booking.pickup} to {booking.dropoff}. "
            f"Pickup in {booking.eta_min} min, about {booking.ride_duration_min} min in the "
            f"vehicle — so the onward journey to {final_destination} is planned from "
            f"{replan_departure_time}."
        ),
    )


# ── One-shot query (unchanged public contract) ────────────────────────────────


@router.post("/query", response_model=AgentResponse)
async def query_route(body: QueryRequest) -> AgentResponse:
    """Stateless single-shot query — no session, no intake, one graph run."""
    try:
        state = run_commute_agent(body.user_query)
    except Exception as exc:
        logger.exception("Unhandled error in run_commute_agent")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return AgentResponse.from_state(state)


# ── Disruption feed (demo controls) ───────────────────────────────────────────


def _load_disruptions() -> list[dict]:
    settings = get_settings()
    with open(settings.disruptions_path, encoding="utf-8") as f:
        return json.load(f)


def _save_disruptions(disruptions: list[dict]) -> None:
    settings = get_settings()
    with open(settings.disruptions_path, "w", encoding="utf-8") as f:
        json.dump(disruptions, f, indent=2, ensure_ascii=False)


@router.get("/disruptions", response_model=list[DisruptionInfo])
async def list_disruptions() -> list[DisruptionInfo]:
    return [DisruptionInfo(**d) for d in _load_disruptions()]


@router.post("/disruptions/{disruption_id}/activate")
async def activate_disruption(disruption_id: str) -> dict:
    """Demo helper — sets active=true for disruption_id in disruptions.json and
    invalidates the cache so the next disruption check picks it up immediately."""
    disruptions = _load_disruptions()
    match = next((d for d in disruptions if d.get("disruption_id") == disruption_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Unknown disruption_id: {disruption_id!r}")

    match["active"] = True
    _save_disruptions(disruptions)
    invalidate_all()
    logger.info("Disruption %s activated via API.", disruption_id)
    return {"message": f"Disruption {disruption_id} activated.", "disruption": match}


@router.post("/disruptions/clear")
async def clear_disruptions() -> dict:
    """Demo helper — sets active=false for every disruption and invalidates the cache."""
    disruptions = _load_disruptions()
    for d in disruptions:
        d["active"] = False
    _save_disruptions(disruptions)
    invalidate_all()
    logger.info("All disruptions cleared via API.")
    return {"message": "All disruptions cleared."}
