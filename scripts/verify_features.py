"""
Verification harness for the plan-variants and simulated-booking work.

Runs the regression and new-functionality checks from the change brief against
the real app — real Google Maps calls, real Groq calls, the real graph — and
prints a pass/fail line per check plus measured per-node latency.

    uv run python scripts/verify_features.py
    .venv/Scripts/python.exe scripts/verify_features.py     # Windows, no uv

Needs GROQ_API_KEY and a Maps key in .env, and network access. It activates and
then clears a demo disruption, so it writes to data/disruptions.json; the
disruption section restores the original file even if a check fails.

Not a pytest suite. The repository's `dev` extras were never installed (the
audit found pytest missing from .venv), so this is written to run on the
interpreter that is actually present.
"""

from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Sinhala and Tamil go through this script's own output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    return ok


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ── Regression: wire shapes ───────────────────────────────────────────────────

# Every field POST /chat and GET /chat/stream published before this work.
# `plan_variants` is the one addition to AgentResponse; ChatResponse itself is
# unchanged. Anything else appearing or disappearing is a broken contract.
BASE_AGENT_RESPONSE_FIELDS = {
    "user_query", "language", "origin", "destination", "requested_time",
    "expected_arrival_time", "preferred_mode", "optimise_for",
    "candidate_route", "candidate_routes", "ranked_routes", "alternative_route",
    "disruption_status", "original_disruption", "replan_attempts",
    "uber_options", "uber_last_mile", "uber_last_mile_distance_m",
    "last_mile_transit_leg", "final_response_native", "final_response_en",
    "trace", "error",
}
BASE_CHAT_RESPONSE_FIELDS = {
    "session_id", "kind", "message", "message_en", "clarification",
    "journey", "state", "detail",
}
ADDED_AGENT_RESPONSE_FIELDS = {"plan_variants"}


def verify_wire_shapes() -> None:
    section("REGRESSION · response shapes of POST /chat and GET /chat/stream")
    from commute_agent.api.schemas import AgentResponse, ChatResponse

    agent_fields = set(AgentResponse.model_fields)
    chat_fields = set(ChatResponse.model_fields)

    check(
        "AgentResponse keeps every pre-existing field",
        BASE_AGENT_RESPONSE_FIELDS <= agent_fields,
        f"missing: {sorted(BASE_AGENT_RESPONSE_FIELDS - agent_fields) or 'none'}",
    )
    check(
        "AgentResponse adds only plan_variants",
        agent_fields - BASE_AGENT_RESPONSE_FIELDS == ADDED_AGENT_RESPONSE_FIELDS,
        f"added: {sorted(agent_fields - BASE_AGENT_RESPONSE_FIELDS)}",
    )
    check(
        "ChatResponse is unchanged",
        chat_fields == BASE_CHAT_RESPONSE_FIELDS,
        f"fields: {sorted(chat_fields)}",
    )

    required = [n for n, f in AgentResponse.model_fields.items() if f.is_required()]
    check("no new required field on AgentResponse", required == ["user_query", "language"],
          f"required: {required}")

    from commute_agent.domain.models import RouteOption
    route_required = [n for n, f in RouteOption.model_fields.items() if f.is_required()]
    check(
        "RouteOption's new provenance fields are all optional with defaults",
        {"source", "verified", "captured_date"} <= set(RouteOption.model_fields)
        and not ({"source", "verified", "captured_date"} & set(route_required)),
        f"required on RouteOption: {route_required}",
    )
    # The construction site that would break first if a required field crept in.
    RouteOption(route_id="X", line="L", stops=["a", "b"], departure_times=["08:00"],
                arrival_times=["09:00"], days_of_operation=["daily"])
    check("RouteOption still constructs without any provenance argument", True)


# ── Regression: conversation, streaming, languages ────────────────────────────


def verify_conversation(client) -> dict:
    section("REGRESSION · multi-turn conversation, SSE node events, languages")

    # Multi-turn: stations, then a departure time. The intake machine must ask
    # for the time and file the answer as the DEPARTURE, not the deadline.
    turn1 = client.post("/api/v1/chat", json={"message": "I want to go to Kandy"}).json()
    session_id = turn1["session_id"]
    check("turn 1 asks a clarifying question", turn1["kind"] == "clarify",
          f"kind={turn1['kind']} clarification={turn1['clarification']} — {turn1['message'][:70]}")

    turn2 = client.post("/api/v1/chat", json={
        "message": "from Colombo Fort", "session_id": session_id}).json()
    check("turn 2 advances the intake machine", turn2["kind"] in {"clarify", "plan"},
          f"kind={turn2['kind']} journey={turn2['journey']['origin']} -> "
          f"{turn2['journey']['destination']}")

    turn3 = client.post("/api/v1/chat", json={
        "message": "at 7:30am", "session_id": session_id}).json()
    check(
        "departure answer is filed as requested_time, not the deadline",
        turn3["journey"]["requested_time"] == "07:30"
        and turn3["journey"]["expected_arrival_time"] is None,
        f"requested_time={turn3['journey']['requested_time']} "
        f"expected_arrival_time={turn3['journey']['expected_arrival_time']}",
    )

    turn4 = client.post("/api/v1/chat", json={
        "message": "no deadline", "session_id": session_id}).json()
    check("multi-turn conversation reaches a plan", turn4["kind"] == "plan",
          f"kind={turn4['kind']}")
    if turn4["kind"] != "plan":
        return {}

    state = turn4["state"]
    check("POST /chat returns a populated state", bool(state and state["candidate_route"]))
    check("candidate_routes still populated alongside the new field",
          len(state["candidate_routes"]) > 0, f"{len(state['candidate_routes'])} routes")
    check("ranked_routes still populated", len(state["ranked_routes"]) > 0,
          f"{len(state['ranked_routes'])} ranked")

    # SSE: one `node` event per node, then exactly one terminal `turn`.
    # The intake asks for an arrival deadline before it will plan, so the
    # journey is set up over POST /chat first and the streamed turn is the one
    # that actually runs the graph.
    setup = client.post("/api/v1/chat", json={
        "message": "Colombo Fort to Galle at 08:00"}).json()
    stream_session = setup["session_id"]
    with client.stream("GET", "/api/v1/chat/stream", params={
        "message": "no deadline", "session_id": stream_session,
    }) as response:
        raw = "".join(chunk for chunk in response.iter_text())

    events = [f for f in raw.split("\n\n") if f.strip()]
    kinds = [e.split("\n")[0].removeprefix("event: ") for e in events]
    node_names = [
        json.loads(e.split("data: ", 1)[1])["node"]
        for e, k in zip(events, kinds) if k == "node"
    ]
    print(f"         node events: {node_names}")
    check("SSE still emits one `node` event per graph node", len(node_names) >= 8,
          f"{len(node_names)} node events")
    check("SSE emits exactly one terminal `turn` event", kinds.count("turn") == 1,
          f"event kinds: {kinds}")
    check("the new plan_variants node appears in the streamed trace",
          "plan_variants" in node_names)

    terminal = json.loads(events[-1].split("data: ", 1)[1])
    terminal_state = terminal.get("state") or {}
    check("the terminal turn still carries the full trace for the trace panel",
          len(terminal_state.get("trace", [])) >= 8,
          f"kind={terminal.get('kind')} trace={terminal_state.get('trace')}")

    # Sinhala and Tamil must parse and return BOTH native and English.
    for label, message in (
        ("Sinhala", "කොළඹ කොටුවේ සිට මහනුවරට උදේ 8ට"),
        ("Tamil", "கொழும்பு கோட்டையிலிருந்து கண்டிக்கு காலை 8 மணிக்கு"),
    ):
        reply = client.post("/api/v1/chat", json={"message": message}).json()
        native, english = reply["message"], reply["message_en"]
        print(f"         {label} kind={reply['kind']} lang={reply['journey']['language']}")
        print(f"           native : {native[:90]}")
        print(f"           english: {english[:90]}")
        check(f"{label} query parses without error",
              reply["kind"] in {"plan", "clarify"}, f"kind={reply['kind']}")
        check(f"{label} returns both native and English text",
              bool(native) and bool(english))

    return state


def verify_tts(client) -> None:
    section("REGRESSION · server-side TTS in all three languages")
    for lang, text in (("en", "Your train departs at 8:30."),
                       ("si", "ඔබේ දුම්රිය 8:30 ට පිටත් වේ."),
                       ("ta", "உங்கள் ரயில் 8:30 மணிக்குப் புறப்படும்.")):
        response = client.post("/api/v1/tts", json={"text": text, "lang": lang})
        check(f"POST /tts returns audio for {lang!r}",
              response.status_code == 200 and len(response.content) > 1000,
              f"HTTP {response.status_code}, {len(response.content)} bytes, "
              f"{response.headers.get('content-type')}")


def verify_fare_hedging(state: dict) -> None:
    section("REGRESSION · fare uncertainty still renders as a hedged range")
    fare = (state.get("candidate_route") or {}).get("fare_estimate")
    if not fare:
        check("route carries a fare estimate", False, "no fare_estimate on candidate_route")
        return
    print(f"         {json.dumps({k: fare[k] for k in ('amount', 'max_amount', 'uncertainty_pct', 'verified', 'source')})}")
    check("fare still exposes a low/high range", fare["max_amount"] >= fare["amount"])
    check("fare still exposes uncertainty_pct for the ±25% chip",
          fare["uncertainty_pct"] > 0, f"±{round(fare['uncertainty_pct'] * 100)}%")
    check("fare still self-declares unverified, driving the 'treat as a guide' note",
          fare["verified"] is False)
    check("fare now also carries captured_date", "captured_date" in fare,
          f"captured_date={fare.get('captured_date')}")


def verify_disruption(client) -> None:
    section("REGRESSION · disruption activation still triggers the replan loop")
    from commute_agent.core.config import get_settings

    path = get_settings().disruptions_path
    original = path.read_text(encoding="utf-8")
    try:
        activated = client.post("/api/v1/disruptions/D001/activate")
        check("demo activation endpoint still works", activated.status_code == 200,
              f"HTTP {activated.status_code}")

        reply = client.post("/api/v1/chat", json={
            "message": "Colombo Fort to Kandy by train at 07:30, no deadline"}).json()
        if reply["kind"] == "clarify":
            reply = client.post("/api/v1/chat", json={
                "message": "no deadline", "session_id": reply["session_id"]}).json()

        state = reply.get("state") or {}
        trace = state.get("trace", [])
        print(f"         trace: {trace}")
        print(f"         replan_attempts={state.get('replan_attempts')} "
              f"level={(state.get('disruption_status') or {}).get('level')}")
        check("replanner still fires on an active disruption",
              "replanner" in trace or state.get("replan_attempts", 0) > 0,
              f"replan_attempts={state.get('replan_attempts')}")
        check("monitor still runs more than once on a replan loop",
              trace.count("monitor") > 1 or state.get("replan_attempts", 0) == 0,
              f"monitor visits={trace.count('monitor')}")
        check("the replan loop still terminates within the cap",
              state.get("replan_attempts", 0) <= get_settings().max_replan_attempts,
              f"{state.get('replan_attempts')} <= {get_settings().max_replan_attempts}")
    finally:
        path.write_text(original, encoding="utf-8")
        from commute_agent.tools.cache import invalidate_all
        invalidate_all()
        print("         (disruptions.json restored)")


# ── New functionality ─────────────────────────────────────────────────────────


def verify_variants_live(client) -> None:
    section("NEW · plan variants over live route data")
    from commute_agent.graph.builder import run_commute_agent_from_intent

    # Nugegoda -> Kandy is the corridor that separates all three strategies:
    # no direct train, so fastest, cheapest and balanced land on three
    # different multi-leg itineraries. Most Sri Lankan corridors do NOT do
    # this, and that is a property of the network rather than a fault — where a
    # direct train exists it tends to win speed, cost and simplicity at once,
    # and the honest render is one card naming all three, not three copies.
    corridors = [
        ("Nugegoda", "Kandy", "08:00"),
        ("Colombo Fort", "Kandy", "07:30"),
        ("Colombo Fort", "Anuradhapura", "08:00"),
        ("Colombo Fort", "Galle", "08:00"),
    ]
    seen_three = False
    seen_collapse = False

    for origin, destination, when in corridors:
        state = run_commute_agent_from_intent({
            "origin": origin, "destination": destination,
            "requested_time": when, "language": "en",
        })
        variants = state.get("plan_variants") or []
        labels = [v["label"] for v in variants]
        route_ids = [v["route_id"] for v in variants]
        print(f"\n         {origin} -> {destination} @ {when}: "
              f"{len(state.get('candidate_routes') or [])} candidates -> {len(variants)} variants")
        for v in variants:
            total = v["total_fare"]
            amount = (f"{total['currency']} {total['amount']}"
                      if total["amount"] is not None else "unavailable")
            print(f"           {v['label']:<26} {v['route_id']:<9} "
                  f"{v['departure_time']}->{v['arrival_time']} "
                  f"total={amount} complete={total['complete']} "
                  f"unc={total['uncertainty_pct']} prov={v['provenance_summary']} "
                  f"times={v['times_source']}"
                  f"{' (overrode maps)' if v['times_overridden'] else ''}")

        check(f"{origin}->{destination}: displayed times are attributed to the "
              f"source that produced them",
              all(v["times_source"] for v in variants),
              f"times_source: {[v['times_source'] for v in variants]}")

        check(f"{origin}->{destination}: no duplicate route across variant cards",
              len(set(route_ids)) == len(route_ids), f"route_ids={route_ids}")
        check(f"{origin}->{destination}: never more than three variants",
              len(variants) <= 3, f"{len(variants)} variants")
        check(f"{origin}->{destination}: no leg fare treated as zero",
              all(v["total_fare"]["amount"] != 0 for v in variants))
        if len(variants) == 3:
            seen_three = True
        if variants and len(variants) < 3:
            seen_collapse = True
        if any(len(v["strategies"]) > 1 for v in variants):
            seen_collapse = True

    check("at least one live corridor produces three distinct variants", seen_three,
          "" if seen_three else "no corridor tested had three distinct winners")
    check("at least one live corridor collapses converging strategies into one card",
          seen_collapse)

    # A deadline nothing can meet must still be reported, not hidden: the
    # variant is selected and flagged rather than suppressed.
    #
    # 07:45 rather than something more generous on purpose. `bus_rag` attaches
    # `journey_time_minutes` from data/bus_timetables.json, and that field
    # contradicts its own route name in at least 9 of 20 records (audit R3) —
    # a Colombo Fort -> Kandy bus comes back claiming a 47-minute journey. Bus
    # data correction is out of scope for this work, so the check picks a
    # deadline no route can satisfy even with that figure taken at face value.
    infeasible = run_commute_agent_from_intent({
        "origin": "Colombo Fort", "destination": "Kandy", "requested_time": "07:30",
        "expected_arrival_time": "07:45", "language": "en",
    })
    late = infeasible.get("plan_variants") or []
    print(f"\n         Colombo Fort -> Kandy with an impossible 07:45 deadline: "
          f"{[(v['label'], v['arrival_time'], v['missed_deadline']) for v in late]}")
    check("a plan that cannot meet the deadline is flagged, not silently dropped",
          bool(late) and all(v["missed_deadline"] for v in late))


def verify_provenance_live(client) -> None:
    section("NEW · per-leg provenance distinguishes sources on live data")
    from commute_agent.graph.builder import run_commute_agent_from_intent

    state = run_commute_agent_from_intent({
        "origin": "Colombo Fort", "destination": "Kandy",
        "requested_time": "07:30", "language": "en",
    })
    routes = state.get("candidate_routes") or []
    sources = {r.get("source") for r in routes}
    overridden = [r for r in routes if r.get("_provenance_override")]

    for r in routes:
        print(f"         {r['route_id']:<9} route.source={r.get('source'):<17} "
              f"verified={r.get('verified')} legs="
              f"{[leg.get('source') for leg in (r.get('legs') or [])]}")

    check("every route carries all three provenance fields",
          all({"source", "verified", "captured_date"} <= set(r) for r in routes))
    check("every leg carries all three provenance fields",
          all({"source", "verified", "captured_date"} <= set(leg)
              for r in routes for leg in (r.get("legs") or [])))
    check("more than one distinct source appears, so the badge distinguishes something",
          len(sources) > 1, f"sources seen: {sorted(s or 'None' for s in sources)}")
    check("a route whose times local data replaced records what it replaced",
          all("previous_departure_times" in r["_provenance_override"] for r in overridden),
          f"{len(overridden)} route(s) overridden by local_timetable")
    check("nothing claims to be verified, matching the audit's finding that "
          "no dataset here has been checked",
          all(r.get("verified") is False for r in routes))

    # R1: Maps train times survive.
    trains = [r for r in routes if r.get("transit_mode") == "train"]
    print(f"         train routes: "
          f"{[(r['route_id'], (r.get('departure_times') or ['-'])[0]) for r in trains]}")
    check("R1 fixed — train routes keep Google Maps ids and times, not scraped '-schedN'",
          all("-sched" not in r["route_id"] for r in trains)
          and all(r.get("source") == "google_maps" for r in trains))


def verify_booking(client) -> None:
    section("NEW · simulated booking and re-entry replan")
    from commute_agent.tools.booking_tool import segment_key, simulate_booking

    # Worked example against a fixed clock.
    fixed = datetime(2026, 7, 29, 8, 0, 0)
    booking = simulate_booking("Fort Railway station", "Kadawatha", "bike", now=fixed)
    departs = booking.replan_departure_at()
    print(f"         booked 08:00 + eta {booking.eta_min}min + ride "
          f"{booking.ride_duration_min}min -> onward departs {departs.strftime('%H:%M')}")
    check("replan time == booking + eta_min + ride_duration_min",
          departs.hour * 60 + departs.minute
          == 8 * 60 + booking.eta_min + booking.ride_duration_min)

    session_id = "verify-booking"
    store_session(session_id, {
        "origin": "Colombo Fort", "destination": "Kandy", "requested_time": "07:30",
        "expected_arrival_time": "18:00", "optimise_for": "cheapest", "language": "en",
    })

    options = client.get("/api/v1/booking/options", params={
        "pickup": "Colombo Fort", "dropoff": "Kadawatha", "session_id": session_id}).json()
    available = [o["ride_class"] for o in options["options"] if o["available"]]
    print(f"         bookable classes: {available}")
    check("options endpoint reports availability so booking stays one tap",
          bool(available), f"available={available}")
    if not available:
        return

    response = client.post("/api/v1/booking/simulate", json={
        "session_id": session_id, "pickup": "Colombo Fort",
        "dropoff": "Kadawatha", "ride_class": available[0]})
    check("POST /booking/simulate succeeds", response.status_code == 200,
          f"HTTP {response.status_code}: {response.text[:200]}")
    if response.status_code != 200:
        return

    data = response.json()
    bk = data["booking"]
    print(f"         {bk['booking_ref']} {bk['pickup']} -> {bk['dropoff']} "
          f"{bk['ride_class_label']} LKR {bk['price']}")
    print(f"         offset {data['replan_offset_min']}min -> onward departs "
          f"{data['replan_departure_time']}")

    check("booking returns simulated: true", bk["simulated"] is True)
    check("disclaimer originates in the API response, not the frontend",
          "PickMe" in bk["disclaimer"] and "Uber" in bk["disclaimer"], bk["disclaimer"])
    check("no fabricated driver name or plate on the confirmation",
          not ({"driver_name", "vehicle_plate"} & set(bk)))

    booked_at = datetime.fromisoformat(bk["booked_at"])
    expected = (booked_at.hour * 60 + booked_at.minute + bk["eta_min"]
                + bk["ride_duration_min"]) % (24 * 60)
    hh, mm = data["replan_departure_time"].split(":")
    check("onward replan departs at now + eta + ride_duration, not now",
          int(hh) * 60 + int(mm) == expected,
          f"{booked_at.strftime('%H:%M')} + {bk['eta_min']} + {bk['ride_duration_min']} "
          f"= {data['replan_departure_time']}")

    onward = data["onward_plan"]
    check("a replan ran", data["replanned"] is True and onward is not None)
    if onward:
        check("onward journey starts at the drop-off", onward["origin"] == "Kadawatha",
              str(onward["origin"]))
        check("onward journey targets the FINAL destination, not the leg end",
              onward["destination"] == "Kandy", str(onward["destination"]))
        check("arrival_deadline survives re-entry",
              onward["expected_arrival_time"] == "18:00",
              str(onward["expected_arrival_time"]))
        check("optimise_for survives re-entry", onward["optimise_for"] == "cheapest",
              str(onward["optimise_for"]))
        check("onward departure time is the replan time, not the original 07:30",
              onward["requested_time"] == data["replan_departure_time"],
              f"{onward['requested_time']} vs {data['replan_departure_time']}")

        departures = [(r["route_id"], (r.get("departure_times") or ["-"])[0])
                      for r in (onward.get("ranked_routes") or [])]
        print(f"         onward departures: {departures}")
        check("onward plan carries its own variants", "plan_variants" in onward,
              f"{len(onward.get('plan_variants') or [])} variants")

    check("the booked segment is recorded on the session",
          segment_key("Colombo Fort", "Kadawatha") in data["booked_segments"],
          str(data["booked_segments"]))

    after = client.get("/api/v1/booking/options", params={
        "pickup": "Colombo Fort", "dropoff": "Kadawatha", "session_id": session_id}).json()
    check("the replan does not re-offer a ride for the segment just booked",
          after["already_booked"] is True)

    # Terminal case.
    store_session("verify-terminal", {
        "origin": "Colombo Fort", "destination": "Kandy", "language": "en"})
    terminal_options = client.get("/api/v1/booking/options", params={
        "pickup": "Peradeniya Junction", "dropoff": "Kandy Railway Station"}).json()
    terminal_class = next(
        (o["ride_class"] for o in terminal_options["options"] if o["available"]), None)
    if terminal_class:
        terminal = client.post("/api/v1/booking/simulate", json={
            "session_id": "verify-terminal", "pickup": "Peradeniya Junction",
            "dropoff": "Kandy Railway Station", "ride_class": terminal_class}).json()
        print(f"         terminal: {terminal['message']}")
        check("drop-off at the final destination returns a booking with no replan",
              terminal["terminal"] is True and terminal["replanned"] is False
              and terminal["onward_plan"] is None)
    else:
        check("terminal case exercised", False, "no vehicle available for that segment")


def store_session(session_id: str, intent: dict) -> None:
    from commute_agent.api.sessions import get_store
    store = get_store()
    session = store.get_or_create(session_id)
    session.intent = intent
    store.save(session)


# ── Latency ───────────────────────────────────────────────────────────────────


def measure_latency(runs: int = 3) -> None:
    section("LATENCY · per node, warm (audit baseline: 10.74s total)")
    from commute_agent.graph.builder import stream_commute_agent_from_intent

    intent = {"origin": "Colombo Fort", "destination": "Kandy",
              "requested_time": "07:30", "language": "en"}

    per_node: dict[str, list[float]] = {}
    totals: list[float] = []

    for index in range(runs + 1):
        start = time.perf_counter()
        last = start
        timings: dict[str, float] = {}
        for node, _ in stream_commute_agent_from_intent(dict(intent)):
            now = time.perf_counter()
            if node != "__end__":
                timings[node] = timings.get(node, 0.0) + (now - last)
            last = now
        total = time.perf_counter() - start
        if index == 0:
            print(f"         (discarding cold run: {total:.2f}s — Chroma import and "
                  f"first embedding query are one-off per process)")
            continue
        totals.append(total)
        for node, value in timings.items():
            per_node.setdefault(node, []).append(value)

    def median(values: list[float]) -> float:
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    print(f"\n         median of {runs} warm runs:")
    for node, values in per_node.items():
        print(f"           {node:<15} {median(values):6.2f}s")
    total_median = median(totals)
    print(f"           {'TOTAL':<15} {total_median:6.2f}s   (runs: "
          f"{', '.join(f'{t:.2f}s' for t in totals)})")

    added = median(per_node.get("plan_variants", [0.0]))
    print(f"\n         cost of the new plan_variants node: {added:.3f}s")
    check("the new node adds under 0.1s to the request path", added < 0.1,
          f"{added:.3f}s")

    responder = median(per_node.get("responder", [0.0]))
    non_llm = total_median - responder
    print(f"         responder (Groq, server-side): {responder:.2f}s")
    print(f"         everything else:               {non_llm:.2f}s")
    check("the pipeline excluding the Groq response call stays under the audit's "
          "4.24s non-responder budget", non_llm < 4.24, f"{non_llm:.2f}s vs 4.24s")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    from fastapi.testclient import TestClient
    from commute_agent.api.main import app

    client = TestClient(app)

    verify_wire_shapes()
    state = verify_conversation(client)
    if state:
        verify_fare_hedging(state)
    verify_tts(client)
    verify_disruption(client)
    verify_variants_live(client)
    verify_provenance_live(client)
    verify_booking(client)
    measure_latency()

    section("SUMMARY")
    failed = [(n, d) for n, ok, d in _RESULTS if not ok]
    print(f"{len(_RESULTS) - len(failed)}/{len(_RESULTS)} checks passed")
    for name, detail in failed:
        print(f"  FAILED: {name}" + (f" — {detail}" if detail else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
