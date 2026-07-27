"""FastAPI route handlers."""

from __future__ import annotations

import io
import json
from typing import Iterator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from commute_agent.api.schemas import (
    AgentResponse,
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    DisruptionInfo,
    JourneySummary,
    QueryRequest,
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
