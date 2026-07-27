"""
Streamlit conversational chat UI for CommuteAI.

Maintains short-term memory in st.session_state:
  messages              -- full chat history for display
  current_intent        -- accumulated journey intent across turns
  last_planned_intent   -- intent used in the most recent graph run (for change detection)

Run with:
  streamlit run src/commute_agent/ui/app.py
"""

from __future__ import annotations

import streamlit as st

from commute_agent.core.exceptions import NLUParseError, OffTopicQueryError
from commute_agent.core.logging import setup_logging
from commute_agent.graph.builder import run_commute_agent_from_intent
from commute_agent.nlu.parser import parse_query, parse_update
from commute_agent.ui.components.agent_trace import render_agent_trace
from commute_agent.ui.components.disruption_banner import render_disruption_banner
from commute_agent.ui.components.route_card import render_route_card

setup_logging()

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CommuteAI",
    page_icon="🚂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialisation ───────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_intent" not in st.session_state:
    st.session_state.current_intent = {}
if "last_planned_intent" not in st.session_state:
    st.session_state.last_planned_intent = None

# ── Clarification question templates ──────────────────────────────────────────
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
_WELCOME = (
    "Welcome! I'm **CommuteAI** 🚂\n\n"
    "I can help you plan train and bus journeys across Sri Lanka — "
    "ask me in **English**, **Sinhala (සිංහල)**, or **Tamil (தமிழ்)**.\n\n"
    "Where would you like to travel today?"
)


def _render_read_aloud_button(text: str, msg_index: int) -> None:
    """Render a Read aloud button for any assistant message.

    On click, generates gTTS audio in-browser and autoplays it.
    msg_index must be unique per message (use the message's position in
    st.session_state.messages, or its anticipated position for new messages).
    """
    btn_key = f"tts_btn_{msg_index}"
    audio_key = f"tts_audio_{msg_index}"

    if st.button("🔊 Read aloud", key=btn_key):
        try:
            import io
            from gtts import gTTS
            buf = io.BytesIO()
            gTTS(text=text, lang="en", slow=False).write_to_fp(buf)
            buf.seek(0)
            st.session_state[audio_key] = buf.read()
        except Exception as exc:
            st.warning(f"Could not generate audio: {exc}")

    if st.session_state.get(audio_key):
        st.audio(st.session_state[audio_key], format="audio/mp3", autoplay=True)


def _lang(intent: dict) -> str:
    return intent.get("language", "en")


def _ask_clarification(intent: dict) -> tuple[str, str] | None:
    """Return (kind, question_text) for whichever required field is missing, or None.

    kind is one of "both" | "origin" | "destination" | "time" | "arrival" —
    the caller uses it to set `_awaiting` unambiguously, rather than inferring
    which question was asked from a combination of boolean flags.
    """
    lang = _lang(intent)
    origin = intent.get("origin")
    destination = intent.get("destination")
    requested_time = intent.get("requested_time")
    # "Resolved" covers both cases: the user already gave a time up front, or
    # we explicitly asked and got an answer (even a "skip"/"now").
    time_resolved = requested_time is not None or intent.get("_time_asked")

    if not origin and not destination:
        return "both", _ASK_BOTH.get(lang, _ASK_BOTH["en"])
    if not origin:
        tmpl = _ASK_ORIGIN.get(lang, _ASK_ORIGIN["en"])
        return "origin", tmpl.format(destination=destination)
    if not destination:
        tmpl = _ASK_DESTINATION.get(lang, _ASK_DESTINATION["en"])
        return "destination", tmpl.format(origin=origin)
    if not time_resolved:
        return "time", _ASK_TIME.get(lang, _ASK_TIME["en"])
    if not intent.get("_arrival_asked"):
        return "arrival", _ASK_ARRIVAL.get(lang, _ASK_ARRIVAL["en"])
    return None


def _intent_changed(old: dict | None, new: dict) -> bool:
    """Return True if any journey-relevant field changed."""
    if old is None:
        return True
    return any(
        old.get(k) != new.get(k)
        for k in ("origin", "destination", "requested_time", "preferred_mode", "expected_arrival_time")
    )


def _render_ranked_routes(ranked_routes: list[dict]) -> None:
    """Display top-5 ranked routes as compact cards in an expander."""
    if len(ranked_routes) <= 1:
        return
    with st.expander(f"Top {len(ranked_routes)} ranked options"):
        for i, r in enumerate(ranked_routes):
            label = r.get("description") or r.get("line") or r.get("route_id", "—")
            mode = r.get("transit_mode", "").upper()
            dep = (r.get("departure_times") or ["—"])[0]
            arr = (r.get("arrival_times") or ["—"])[-1]
            col_rank, col_info = st.columns([1, 5])
            with col_rank:
                st.metric(f"#{i + 1}", mode)
            with col_info:
                st.markdown(f"**{label[:80]}**")
                st.caption(f"Departs {dep} · Arrives {arr} · {len(r.get('stops', []))} stops")
            if i < len(ranked_routes) - 1:
                st.divider()


def _render_uber_card(quotes: list[dict], title: str) -> None:
    """Render ride-hailing options as a styled card."""
    if not quotes:
        return
    with st.container(border=True):
        st.markdown(f"**{title}**")
        cols = st.columns(len(quotes))
        for col, q in zip(cols, quotes):
            with col:
                if q.get("available"):
                    st.metric(
                        label=q.get("vehicle_type", "Ride"),
                        value=f"LKR {q.get('price', '—')}",
                        delta=f"ETA {q.get('eta_min', '?')} min",
                    )
                else:
                    st.metric(label=q.get("vehicle_type", "Ride"), value="Unavailable")


def _render_transit_leg_card(leg: dict) -> None:
    """Render a route's final local transit leg — the 'local bus/train' side
    of a last-mile choice (paired with a ride-hailing card via _render_uber_card).

    Shows this leg's OWN road-route distance, not the ride's — the two can
    legitimately differ, since a bus doesn't necessarily take the same path
    a taxi would.
    """
    icon = "🚆" if leg.get("mode") == "train" else "🚌"
    mode_label = "Train" if leg.get("mode") == "train" else "Bus"
    with st.container(border=True):
        st.markdown(f"**{icon} Local {mode_label}**")
        ref = f"No.{leg['route_ref']} " if leg.get("route_ref") else ""
        st.caption(f"{ref}({leg.get('line', '')})")
        st.caption(f"Board {leg.get('board_stop', '')} · Departs {leg.get('departure', '—')}")
        st.caption(f"Alight {leg.get('alight_stop', '')} · Arrives {leg.get('arrival', '—')}")
        leg_km = (leg.get("distance_m") or 0) / 1000
        if leg_km:
            st.caption(f"~{leg_km:.1f} km by road")


def _render_plan_components(state: dict) -> None:
    """Render route cards, disruption banner, ranked routes, Uber cards, TTS, trace."""
    disruption = state.get("disruption_status", {})
    has_disruption = bool(disruption and disruption.get("level") != "clear")

    render_disruption_banner(disruption)

    if has_disruption and state.get("alternative_route"):
        col_orig, col_alt = st.columns(2)
        with col_orig:
            render_route_card(state.get("candidate_route"), title="Original Route (Disrupted)")
        with col_alt:
            render_route_card(state.get("alternative_route"), title="Best Alternative Route")
    elif state.get("candidate_route"):
        render_route_card(state.get("candidate_route"), title="Your Best Route")

    # Ranked top-5 options
    ranked: list[dict] = state.get("ranked_routes", [])
    _render_ranked_routes(ranked)

    # All Google Maps options (fallback expander)
    candidate_routes: list[dict] = state.get("candidate_routes", [])
    if len(candidate_routes) > 1 and not ranked:
        with st.expander(f"Show all {len(candidate_routes)} options from Google Maps"):
            for i, r in enumerate(candidate_routes):
                label = r.get("description") or r.get("line") or r.get("route_id", "—")
                st.markdown(f"**Option {i + 1}** — {label}")
                dep = (r.get("departure_times") or ["—"])[0]
                arr = (r.get("arrival_times") or ["—"])[-1]
                st.caption(f"Departs {dep} · Arrives {arr} · {len(r.get('stops', []))} stops")
                if i < len(candidate_routes) - 1:
                    st.divider()

    # Uber full-trip options
    uber_options = state.get("uber_options")
    if uber_options:
        _render_uber_card(uber_options, "No suitable transit found — Ride-hailing options:")

    # Last-mile options: local transit leg + ride-hailing, side by side when
    # both exist (a multi-leg route's final local hop); ride-only when it's a
    # pure walking gap with no transit for that segment. Distance is shown
    # per-card, not as one combined number — a bus's road-route distance and
    # a ride's distance can legitimately differ.
    uber_last_mile = state.get("uber_last_mile")
    last_mile_transit_leg = state.get("last_mile_transit_leg")
    gap_m = state.get("uber_last_mile_distance_m")

    if last_mile_transit_leg and uber_last_mile:
        st.markdown("**Last-mile options — choose one:**")
        col_transit, col_ride = st.columns(2)
        with col_transit:
            _render_transit_leg_card(last_mile_transit_leg)
        with col_ride:
            ride_note = f" (~{gap_m / 1000:.1f} km)" if gap_m else ""
            _render_uber_card(uber_last_mile, f"🚗 Ride-hailing{ride_note}")
    elif uber_last_mile:
        walk_note = f" ({gap_m / 1000:.1f} km walk)" if gap_m else ""
        _render_uber_card(uber_last_mile, f"Last-mile ride to your destination{walk_note}:")

    if state.get("trace"):
        render_agent_trace(state["trace"])

    if state.get("error"):
        with st.expander("Agent note"):
            st.warning(state["error"])


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🚂 CommuteAI")
    st.caption("CommuteAI · AGENTRIX 2026 · Team 23 · AlphaZero")
    st.divider()

    intent_now = st.session_state.current_intent
    if intent_now.get("origin") or intent_now.get("destination"):
        st.subheader("Current Journey")
        if intent_now.get("origin"):
            st.caption(f"From: **{intent_now['origin']}**")
        if intent_now.get("destination"):
            st.caption(f"To: **{intent_now['destination']}**")
        if intent_now.get("requested_time"):
            st.caption(f"Departs: **{intent_now['requested_time']}**")
        if intent_now.get("expected_arrival_time"):
            st.caption(f"Must arrive by: **{intent_now['expected_arrival_time']}**")
        if intent_now.get("preferred_mode"):
            st.caption(f"Mode: **{intent_now['preferred_mode'].title()}**")
        st.divider()

    if st.button("New Journey", use_container_width=True):
        st.session_state.messages = []
        st.session_state.current_intent = {}
        st.session_state.last_planned_intent = None
        st.rerun()

    st.divider()
    st.caption("Example openers:")
    st.code("I want to go to Kandy from Colombo at 7am", language=None)
    st.code("ට්‍රේන් එකෙන් කෑගල්ල ට යන්නේ කොහොමද?", language=None)
    st.code("கண்டிக்கு எப்படி போவது?", language=None)


# ── Main chat area ─────────────────────────────────────────────────────────────
st.title("🚂 CommuteAI")
st.caption("Ask about trains and buses across Sri Lanka — in English, Sinhala, or Tamil.")

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown(_WELCOME)

for _i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "assistant":
            # Read aloud always uses English text (stored as tts_text, else english_translation, else content)
            _msg_tts_text = msg.get("tts_text") or msg.get("english_translation") or msg["content"]
            _render_read_aloud_button(_msg_tts_text, msg_index=_i)

        if msg.get("english_translation") and msg.get("language", "en") != "en":
            with st.expander("English translation"):
                st.markdown(msg["english_translation"])

        if msg.get("agent_state"):
            _render_plan_components(msg["agent_state"])


# ── Chat input ─────────────────────────────────────────────────────────────────
if prompt := st.chat_input("Ask about your journey…"):

    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            current = st.session_state.current_intent
            awaiting = current.get("_awaiting")

            # Handle time / arrival-deadline intake turns. `_awaiting` is set
            # explicitly by whichever question was actually just displayed
            # (see the clarification block below), so there's no ambiguity
            # about which field this reply is answering.
            if awaiting == "arrival":
                # User is answering the arrival-deadline question
                lower = prompt.strip().lower()
                if lower in ("no", "none", "skip", "n", "no deadline"):
                    current["expected_arrival_time"] = None
                else:
                    # Try to extract a time from the answer
                    try:
                        updated = parse_update(prompt, current)
                        current["expected_arrival_time"] = updated.expected_arrival_time
                    except Exception:
                        current["expected_arrival_time"] = None
                current["_awaiting"] = None
                st.session_state.current_intent = current
                # Fall through to planning if all fields are ready
                new_intent = dict(current)
            elif awaiting == "time":
                # User answered the departure time question
                lower = prompt.strip().lower()
                if lower in ("now", "skip", "asap", "any"):
                    current["requested_time"] = None
                else:
                    try:
                        updated = parse_update(prompt, current)
                        current["origin"] = updated.origin
                        current["destination"] = updated.destination
                        current["requested_time"] = updated.requested_time
                        current["expected_arrival_time"] = updated.expected_arrival_time
                        current["preferred_mode"] = updated.preferred_mode
                    except Exception:
                        current["requested_time"] = None
                current["_awaiting"] = None
                st.session_state.current_intent = current
                new_intent = dict(current)
            else:
                # Normal NLU turn
                try:
                    if current:
                        intent = parse_update(prompt, current)
                    else:
                        intent = parse_query(prompt)
                except OffTopicQueryError:
                    off_topic_msg = (
                        "I can only help with public transport journeys in Sri Lanka. "
                        "Please ask about a train or bus route."
                    )
                    st.markdown(off_topic_msg)
                    _render_read_aloud_button(off_topic_msg, len(st.session_state.messages))
                    st.session_state.messages.append({"role": "assistant", "content": off_topic_msg})
                    st.stop()
                except NLUParseError as exc:
                    err_msg = f"Sorry, I couldn't understand that. Could you rephrase? _(error: {exc})_"
                    st.markdown(err_msg)
                    _render_read_aloud_button(err_msg, len(st.session_state.messages))
                    st.session_state.messages.append({"role": "assistant", "content": err_msg})
                    st.stop()

                new_intent = {
                    "origin": intent.origin,
                    "destination": intent.destination,
                    "requested_time": intent.requested_time,
                    "expected_arrival_time": intent.expected_arrival_time,
                    "preferred_mode": intent.preferred_mode,
                    "language": str(intent.language),
                    "_time_asked": current.get("_time_asked", False),
                    "_arrival_asked": current.get("_arrival_asked", False),
                    "_awaiting": None,
                }

                # Handle "start over"
                if current and not new_intent.get("origin") and not new_intent.get("destination"):
                    st.session_state.current_intent = {}
                    st.session_state.last_planned_intent = None
                    restart_msg = "Sure, let's start fresh! Where would you like to travel?"
                    st.markdown(restart_msg)
                    _render_read_aloud_button(restart_msg, len(st.session_state.messages))
                    st.session_state.messages.append({"role": "assistant", "content": restart_msg})
                    st.stop()

                st.session_state.current_intent = new_intent

        # Check what we still need via intake flow
        clarification = _ask_clarification(new_intent)

        if clarification:
            kind, question_text = clarification
            if kind == "time":
                new_intent["_time_asked"] = True
                new_intent["_awaiting"] = "time"
            elif kind == "arrival":
                new_intent["_arrival_asked"] = True
                new_intent["_awaiting"] = "arrival"
            st.session_state.current_intent = new_intent

            st.markdown(question_text)
            _render_read_aloud_button(question_text, len(st.session_state.messages))
            st.session_state.messages.append({"role": "assistant", "content": question_text})
            st.stop()

        # All required fields collected — check if plan needs to be (re-)run
        last = st.session_state.last_planned_intent
        plan_intent = {k: v for k, v in new_intent.items() if not k.startswith("_")}

        if not _intent_changed(last, plan_intent):
            same_plan_msg = (
                f"Your journey from **{plan_intent['origin']}** to "
                f"**{plan_intent['destination']}** is still planned above. "
                f"Want to change the **time**, **mode**, or **destination**?"
            )
            st.markdown(same_plan_msg)
            _render_read_aloud_button(same_plan_msg, len(st.session_state.messages))
            st.session_state.messages.append({"role": "assistant", "content": same_plan_msg})
            st.stop()

        # Run the planning graph
        with st.spinner("Finding your route…"):
            try:
                state = run_commute_agent_from_intent(plan_intent)
            except Exception as exc:
                err = f"Agent error: {exc}"
                st.error(err, icon="❌")
                _render_read_aloud_button(err, len(st.session_state.messages))
                st.session_state.messages.append({"role": "assistant", "content": err})
                st.stop()

        st.session_state.last_planned_intent = plan_intent

        # Build response text
        native = state.get("final_response_native", "")
        english = state.get("final_response_en", "")
        lang = plan_intent.get("language", "en")
        response_text = native or english

        lang_map = {"si": "Sinhala", "ta": "Tamil", "en": "English"}
        st.caption(f"Detected language: **{lang_map.get(lang, lang)}**")
        st.markdown(response_text)

        # Read aloud uses English text regardless of native language
        tts_text = english or response_text
        _render_read_aloud_button(tts_text, len(st.session_state.messages))

        english_translation: str | None = None
        if lang != "en" and english:
            with st.expander("English translation"):
                st.markdown(english)
            english_translation = english

        _render_plan_components(state)

        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "language": lang,
            "english_translation": english_translation,
            "tts_text": tts_text,
            "agent_state": state,
        })
