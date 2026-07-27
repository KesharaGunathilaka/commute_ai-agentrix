"""
Responder node — terminal node that builds the bilingual final response and TTS audio.

Reads:  language, candidate_route, disruption_status, alternative_route,
        ranked_routes, uber_options
Writes: final_response_native, final_response_en, tts_audio
"""

from __future__ import annotations

import io

from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import DisruptionLevel
from commute_agent.graph.state import AgentState
from commute_agent.nlu.responder import generate_response

logger = get_logger(__name__)

NODE_NAME = "responder"


def _build_tts_audio(text: str) -> bytes | None:
    """Convert English text to MP3 bytes using gTTS. Returns None on failure."""
    try:
        from gtts import gTTS  # noqa: PLC0415
        buf = io.BytesIO()
        tts = gTTS(text=text, lang="en", slow=False)
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception as exc:
        logger.warning("[%s] TTS generation failed: %s", NODE_NAME, exc)
        return None


def responder_node(state: AgentState) -> AgentState:
    """
    Generate bilingual response, append Uber suggestions if present, and synthesise TTS audio.

    Always produces both final_response_native and final_response_en.
    Handles gracefully if the state contains an error from an earlier node.
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    logger.info("[%s] Generating response (language=%r)", NODE_NAME, state.get("language"))

    # If an upstream node set an error with no route, return the error directly
    if state.get("error") and not state.get("candidate_route"):
        uber_options: list[dict] = state.get("uber_options") or []
        if uber_options:
            uber_text = _format_uber_suggestion(uber_options, state.get("origin", ""), state.get("destination", ""))
            error_msg = f"{state['error']}\n\n{uber_text}"
        else:
            error_msg = state["error"]

        tts_audio = _build_tts_audio(error_msg)
        return {
            **state,
            "trace": trace,
            "final_response_native": error_msg,
            "final_response_en": error_msg,
            "tts_audio": tts_audio,
        }

    response = generate_response(dict(state))
    native = response["final_response_native"]
    english = response["final_response_en"]

    # Append Uber options to the response if present
    uber_options = state.get("uber_options") or []
    uber_last_mile = state.get("uber_last_mile") or []

    if uber_options:
        uber_text = _format_uber_suggestion(uber_options, state.get("origin", ""), state.get("destination", ""))
        native += f"\n\n{uber_text}"
        english += f"\n\n{uber_text}"
    elif uber_last_mile:
        transit_leg = state.get("last_mile_transit_leg")
        if transit_leg:
            # The ride replaces/parallels this leg, so it starts where the
            # leg BOARDS — not the route's overall final alighting stop
            # (which is where this leg ENDS, a different place).
            from_stop = transit_leg.get("board_stop", "")
        else:
            from_stop = (state.get("candidate_route", {}).get("stops") or [state.get("destination", "")])[-1]
        last_mile_text = _format_last_mile_options(
            transit_leg,
            uber_last_mile,
            from_stop,
            state.get("destination", ""),
            state.get("uber_last_mile_distance_m"),
        )
        native += f"\n\n{last_mile_text}"
        english += f"\n\n{last_mile_text}"

    tts_audio = _build_tts_audio(english)
    logger.info("[%s] TTS audio %s", NODE_NAME, "generated" if tts_audio else "failed")

    result: AgentState = {
        **state,
        "trace": trace,
        "final_response_native": native,
        "final_response_en": english,
        "tts_audio": tts_audio,
    }

    # Replanning succeeded: Monitor's latest check (of alternative_route) came
    # back clear. Promote it to candidate_route so everything downstream (UI
    # cards, the API response, a follow-up turn) reflects the route that was
    # actually recommended instead of the stale, still-disrupted original.
    disruption_status = state.get("disruption_status") or {}
    if (
        state.get("replan_attempts", 0) > 0
        and disruption_status.get("level") == DisruptionLevel.CLEAR
        and state.get("alternative_route")
    ):
        result["candidate_route"] = state["alternative_route"]

    return result


def _format_uber_suggestion(quotes: list[dict], origin: str, destination: str) -> str:
    """Format Uber options as readable markdown for the response."""
    lines = [f"**Ride-hailing options from {origin} to {destination}:**"]
    for q in quotes:
        if q.get("available"):
            lines.append(
                f"- {q['vehicle_type']}: LKR {q['price']} · ETA {q['eta_min']} min · {q['distance_km']} km"
            )
    if len(lines) == 1:
        lines.append("- No rides available right now.")
    return "\n".join(lines)


def _format_last_mile_options(
    transit_leg: dict | None,
    quotes: list[dict],
    from_stop: str,
    destination: str,
    distance_m: int | None = None,
) -> str:
    """
    Format the last-mile leg as either one option (ride only, when there's a
    walking gap with no transit) or two options side by side (a local
    bus/train Google Maps already found, plus a ride-hailing alternative for
    the same segment) — letting the commuter choose rather than silently
    locking in whichever bus Maps happened to pick.

    Distance is shown PER OPTION rather than one combined number: the transit
    leg's road-route distance and the ride's distance can legitimately differ
    (a bus doesn't necessarily take the same path a taxi would), so showing
    a single figure next to a price based on the other one would be misleading.
    """
    if transit_leg:
        lines = [f"**Getting from {from_stop} to {destination} — two options:**"]
        mode_label = "Train" if transit_leg.get("mode") == "train" else "Bus"
        ref = f"No.{transit_leg['route_ref']} " if transit_leg.get("route_ref") else ""
        line_name = transit_leg.get("line", "")
        leg_km = (transit_leg.get("distance_m") or 0) / 1000
        leg_note = f" (~{leg_km:.1f} km by road)" if leg_km else ""
        lines.append(
            f"1. **Local {mode_label} {ref}({line_name})**{leg_note} — "
            f"board at {transit_leg.get('board_stop', from_stop)}, "
            f"departs {transit_leg.get('departure', '—')}, "
            f"arrives {transit_leg.get('alight_stop', destination)} at {transit_leg.get('arrival', '—')}"
        )
        ride_note = f" (~{distance_m / 1000:.1f} km)" if distance_m else ""
        lines.append(f"2. **Ride-hailing{ride_note}:**")
        for q in quotes:
            if q.get("available"):
                lines.append(f"   - {q['vehicle_type']}: LKR {q['price']} · ETA {q['eta_min']} min")
        if len(lines) == 2:
            lines.append("   - No rides available right now.")
        return "\n".join(lines)

    walk_note = f" ({distance_m / 1000:.1f} km walk)" if distance_m else ""
    lines = [f"**Last-mile ride from {from_stop} to {destination}{walk_note}:**"]
    for q in quotes:
        if q.get("available"):
            lines.append(f"- {q['vehicle_type']}: LKR {q['price']} · ETA {q['eta_min']} min")
    if len(lines) == 1:
        lines.append("- No rides available right now.")
    return "\n".join(lines)
