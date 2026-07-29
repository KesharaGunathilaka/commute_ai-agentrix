# CommuteAI — System Audit

**Date:** 2026-07-28
**Commit audited:** `33eb79f` ("Agentrix"), branch `main`. Working tree clean except `frontend/package-lock.json`.
**Scope:** read-only. No source file was modified. This document is the only file created.

**Confidence legend**

- `VERIFIED` — the code path was read end to end, or executed and the result observed.
- `INFERRED` — deduced from code structure; not directly observed.
- `UNKNOWN` — could not be determined from the repository.

---

## 1. Executive summary

1. **The train enrichment node actively replaces correct Google Maps times with wrong times, for every train query.** `train_rag.py:39` hardcodes `https://trainschedule.lk/schedule/abucnia/{src}-to-{dst}-train-timetable`. That URL returns **the same page — Colombo Fort → Rambukkana — for every slug**, including a nonsense one, at HTTP 200. Verified: `colombo-fort-to-kandy`, `colombo-fort-to-galle`, `maradana-to-jaffna` and `xyzzy-to-nowhere` all return a table with identical MD5. `VERIFIED`

2. **A live end-to-end run confirms the damage reaches the user.** Query `Colombo Fort → Kandy, depart 07:30`: the planner obtained a real Maps train route, `train_rag_node` discarded it and substituted 5 Rambukkana schedules, and the final English response told the commuter *"depart from Fort Railway station at 08:05 AM and arrive at Kandy at 10:30 AM"*. Those are Colombo Fort → **Rambukkana** times relabelled as Kandy. `VERIFIED`

3. **The system is, on current data, demonstrably *less* accurate than Google Maps alone for train queries.** Maps supplied a correct route; `train_rag.py:225-239` overwrote it. I could not find any query for which local data makes the answer *more* accurate than Maps. See Part 4. `VERIFIED`

4. **All 5 disruption records are `active: false`** (`data/disruptions.json:8,17,26,35,44`), and `check_disruption` skips inactive rows (`retrieval.py:145-146`). The DISRUPTED branch, the replanner, and the replan loop are therefore **inert on a default checkout** — they never fire unless someone POSTs to `/api/v1/disruptions/{id}/activate`. `VERIFIED`

5. **Disruption checking is switched off entirely for buses** (`monitor.py:50-56` returns CLEAR for any `TransitMode.BUS` before consulting the feed). `VERIFIED`

6. **`data/fares.json` self-declares `"verified": false` and `"source": "unverified placeholder rates"`** (`data/fares.json:21-22`), with a `_README` stating *"The rates below are plausible placeholders … NOT transcribed from a published tariff"* (`data/fares.json:11-13`). This is the most honest artefact in the repository, and the fare path is correctly hedged all the way to the UI (`RouteCard.tsx:62-63`). `VERIFIED`

7. **Ride-hailing prices are randomly generated and presented in chat text with no hedging.** `ride_service.py:1` calls itself a "Dummy ride backend"; distance is `rng.uniform(1.5, 24.0)` (`ride_service.py:121`) and availability is `rng.random() > 0.25` (`ride_service.py:150`). `responder.py:130` renders this as `LKR {price} · ETA {eta_min} min` — no "estimated", no caveat. Unlike fares, nothing downstream marks these as fake. `VERIFIED`

8. **The bus semantic fallback returns confidently wrong matches above threshold.** Executed against the live Chroma store: `"bus from Colombo Fort to Kandy"` → `Matara-Colombo` @ 0.731; `"bus from Maharagama to Colombo Fort"` → `Matara-Colombo` @ 0.736; `"bus from Jaffna to Vavuniya"` → `86 Batticolo - Jaffna` @ 0.647. The 0.60 threshold (`config/settings.yaml:6`) is far too low for short route-name strings. In the live graph run, route `38-1` and route `100` both received wrong matches at 0.65/0.64. `VERIFIED`

9. **`data/routes.json` is functionally inert at runtime.** Its only consumer is `retrieve_routes` (`retrieval.py:28`), which is called only by `tools/route_tool.py:19` — and `route_tool` is imported by nothing. The Chroma `sri_lanka_railways_routes` collection (6 documents, confirmed present) is queried by no live code path. `VERIFIED`

10. **`config/agents.yaml` is entirely dead.** `Settings.agents_config` (`config.py:90-91`) is defined and never read anywhere in the codebase. The four elaborate personas are decoration. `VERIFIED`

11. **The claim "all prompts live in `config/prompts.yaml`, not hardcoded in nodes" (README:349) is false.** ~10 hardcoded trilingual templates live in `conversation/intake.py:84-140`, a fallback table in `nlu/responder.py:87-91`, and all ride-hailing / last-mile response text is built in Python in `graph/nodes/responder.py:124-185`. `VERIFIED`

12. **The bus corpus's source files are absent from this checkout and were never committed.** `data/processed/` does not exist; `.gitignore:26` excludes it. 100 documents are present in Chroma, but the markdown they were built from is gone, so their provenance is **unverifiable from the repository**. Running `uv run ingest-bus` today would log a warning and ingest 0 documents (`ingest_bus_docs.py:111-113`). `VERIFIED`

13. **The test suite does not run in this checkout** — pytest is not installed in `.venv` and there is no pip. Of the tests that exist, **9 of 14 are `pytest.skip` stubs**, and the three `test_retrieval.py` fixtures construct `RouteOption` with a schema (`train_id`, `stations`, `train_type`) that the current model (`domain/models.py:20-25`: `route_id`, `stops`, `vehicle_type`) rejects — they would error, not pass. **Real coverage is approximately zero.** `VERIFIED`

14. **The replan loop is provably bounded** — `replanner_node` unconditionally increments `replan_attempts` (`replanner.py:39`) and `_route_after_monitor` exits at `>= max_replan_attempts` (`builder.py:79`). But the "defence in depth" second guard claimed by `replanner.py:7-8` and README:347 **does not exist** — the replanner enforces no cap. `VERIFIED`

15. **`optimise_for` is silently dropped on the one-shot query path.** `ParsedIntent` parses it (`nlu/models.py:21`), but `planner_node`'s `state_update` (`planner.py:67-77`) never copies `intent.optimise_for` into state. On the conversational path it survives only because `_state_from_intent` seeds it (`builder.py:209`). So `POST /api/v1/query` with *"cheapest way to Kandy"* silently ranks balanced. `VERIFIED`

16. **gTTS is called on every single turn and the result is then thrown away** for the Next.js frontend. `responder.py:98` synthesises MP3 into `tts_audio`; `schemas.py:22-23` deliberately omits it from the wire; the frontend re-fetches audio from `POST /api/v1/tts`. Measured cost of the wasted call: **1.02s per turn**. Only the legacy Streamlit UI could use it, and `ui/app.py:87-99` generates its own audio anyway rather than reading state. `VERIFIED`

17. **Measured end-to-end latency: 10.74s** for one Colombo→Kandy turn. Responder 6.50s, train_rag 2.60s, bus_rag 1.02s, planner 0.60s; fares/ranker/uber/monitor ≈ 0.00s. `VERIFIED`

18. **Sessions are in-process, non-durable, and unsafe across workers** — the module docstring admits it (`sessions.py:12-14`: *"Not safe across multiple worker processes … Run the API single-worker, or move this to Redis first"*). A restart loses every conversation. `VERIFIED`

---

## 2. Part 1 — System map and runtime data flow

### 2.1 Traced query

Query traced live: `origin="Colombo Fort", destination="Kandy", requested_time="07:30", language="en"` via `stream_commute_agent_from_intent`. Observed trace:
`planner → bus_rag → train_rag → fares → ranker → uber → monitor → responder`. `VERIFIED`

### 2.2 Node-by-node

| # | Node | Reads from state | Writes to state | External calls | On failure | Surfaced? |
|---|---|---|---|---|---|---|
| 1 | `planner` (`planner.py:22`) | `user_query`, `origin`, `destination`, `language`, `requested_time`, `expected_arrival_time`, `preferred_mode`, `trace`, `replan_attempts` | `trace`, `language`, `origin`, `destination`, `requested_time`, `expected_arrival_time`, `preferred_mode`, `replan_attempts`, `candidate_routes`, `candidate_route`, `error` | Groq (`parse_query`, skipped if origin+destination pre-set, `planner.py:34`); Google Maps Directions (`planner.py:81`) | `OffTopicQueryError` → canned response, early return (`:48-57`). `NLUParseError` → `error` set, early return (`:58-65`). `RouteNotFoundError` → `candidate_routes=[]`, `error` set, continues (`:110-113`) | **Surfaced** — `error` reaches `AgentResponse.error` (`schemas.py:57`) and is rendered at `JourneyPlan.tsx:137-140` |
| 2 | `bus_rag` (`bus_rag.py:145`) | `candidate_routes`, `requested_time`, `candidate_route`, `trace` | `trace`, `candidate_routes`, `candidate_route` | Chroma query via `retrieve_bus_timetable` (local ONNX embed, no network) | Route-number extraction miss → route passed through untouched (`:173-176`). RAG lookup exception → `return None`, logged at DEBUG (`bus_rag.py:128-130`) | **Silent** |
| 3 | `train_rag` (`train_rag.py:181`) | `candidate_routes`, `requested_time`, `origin`, `destination`, `candidate_route`, `trace` | `trace`, `candidate_routes`, `candidate_route` | **2× Groq** (`_map_station_name`, once per endpoint, `:203-204`); `time.sleep(0.5)` (`:212`); **HTTP GET** trainschedule.lk (`:108`) | Station map failure → falls back to the raw Maps name (`:206-209`). Scrape failure/no table → returns state unchanged, Maps times kept (`:215-220`) | **Silent** |
| 4 | `fares` (`fares.py:25`) | `candidate_routes`, `candidate_route`, `trace` | `trace`, `candidate_routes` (each `+fare_estimate`), `candidate_route` | None (reads `data/fares.json`) | Missing/invalid config → `_load_fare_config` returns `None`, every fare becomes `None` (`fare_tool.py:48-53`) | **Silent**, but correct — UI shows no fare rather than a wrong one |
| 5 | `ranker` (`ranker.py:170`) | `candidate_routes`, `requested_time`, `expected_arrival_time`, `optimise_for`, `trace` | `trace`, `ranked_routes`, `candidate_route`, `optimise_for` (normalised) | None | Empty candidates → `ranked_routes=[]` (`:185-187`). Unparseable times → `_parse_time` returns `None`, route sorts with `arrival_minutes=9999` (`:151`) | **Silent** |
| 6 | `uber` (`uber.py:108`) | `candidate_routes`, `ranked_routes`, `candidate_route`, `origin`, `destination`, `expected_arrival_time`, `trace` | `trace`, `uber_options`, `uber_last_mile`, `uber_last_mile_distance_m`, `last_mile_transit_leg` | `ride_service.RideService` — **in-process dummy, no network** (`uber.py:51-54`) | Any exception → `[]`, logged WARNING (`:55-57`) | **Silent** |
| 7 | `monitor` (`monitor.py:21`) | `candidate_route`, `alternative_route`, `replan_attempts`, `original_disruption`, `trace` | `trace`, `disruption_status`, `original_disruption` | None (reads `data/disruptions.json`) | No route → CLEAR (`:39-44`). Bus → CLEAR without checking (`:50-56`). Feed error → CLEAR after 2 attempts (`disruption_tool.py:50-56`) | **Silent — deliberately.** `disruption_tool.py:55`: *"Graceful degradation — don't surface the error to the commuter"* |
| 8 | `replanner` (`replanner.py:23`) | `candidate_route`, `alternative_route`, `ranked_routes`, `candidate_routes`, `replan_attempts`, `trace` | `trace`, `replan_attempts`, `alternative_route` | None | No untried route → `alternative_route=None`, WARNING (`:68-69`) | **Silent** — but the responder then takes the `_generate_no_alternative_response` branch (`nlu/responder.py:116`) |
| 9 | `responder` (`responder.py:37`) | `error`, `candidate_route`, `language`, `disruption_status`, `alternative_route`, `original_disruption`, `replan_attempts`, `uber_options`, `uber_last_mile`, `last_mile_transit_leg`, `uber_last_mile_distance_m`, `origin`, `destination`, `ranked_routes`, `trace` | `trace`, `final_response_native`, `final_response_en`, `tts_audio`, `candidate_route` (promoted on successful replan, `:119`) | Groq (response generation); gTTS (`:28`) | gTTS failure → `None`, WARNING (`:32-34`). **LLM failure → `RetryError` propagates and crashes the turn** — see 6.3 R4 | **Fatal**, caught only at the API boundary (`routes.py:151`/`226`) |

### 2.3 `AgentState` field lifecycle

`AgentState` is defined at `graph/state.py:9-101`. All keys are seeded by `_blank_state()` (`builder.py:166-191`).

| Field | First populated | Mutated by | Read by | Notes |
|---|---|---|---|---|
| `user_query` | `builder.py:228` / `:202` | — | `planner.py:31,47` | Also on the wire (`schemas.py:26`) |
| `language` | `builder.py:168`; `planner.py:70` | `planner.py:53,63` (error paths force `"en"`) | `responder.py:47`, `nlu/responder.py:107` | |
| `origin` / `destination` | `builder.py:206-207`; `planner.py:71-72` | — | `train_rag.py:200-201`, `uber.py:124-125`, `responder.py:53,76,87`, `nlu/responder.py:146,191` | |
| `requested_time` | `planner.py:73` | — | `bus_rag.py:156`, `train_rag.py:192`, `ranker.py:181` | |
| `expected_arrival_time` | `planner.py:74` | — | `ranker.py:182`, `uber.py:129` | |
| `preferred_mode` | `planner.py:75` | — | `planner.py:88`, `nlu/responder.py:142` | |
| `optimise_for` | `builder.py:209` **only** | `ranker.py:220` (normalised echo) | `ranker.py:183` | **Never written by the planner** — see 6.3 R6. `VERIFIED` |
| `candidate_routes` | `planner.py:104,112` | `bus_rag.py:233`, `train_rag.py:257`, `fares.py:77` | `ranker.py:180`, `uber.py:126`, `replanner.py:57` | Not rendered by the frontend (only `ranked_routes` is) |
| `candidate_route` | `planner.py:105` | `bus_rag.py:234`, `train_rag.py:258`, `fares.py:78`, `ranker.py:217`, `responder.py:119` | `monitor.py:35`, `uber.py:128`, `replanner.py:49`, `responder.py:50,87`, `nlu/responder.py:128,175` | |
| `ranked_routes` | `ranker.py:216` | — | `uber.py:127`, `replanner.py:56`, `JourneyPlan.tsx:52` | |
| `uber_options` | `uber.py:147` | — | `responder.py:51,72` | |
| `uber_last_mile` | `uber.py:161,180` | — | `responder.py:73` | |
| `uber_last_mile_distance_m` | `uber.py:162,183` | — | `responder.py:92`, `JourneyPlan.tsx:125` | |
| `last_mile_transit_leg` | `uber.py:184` | — | `responder.py:80`, `JourneyPlan.tsx:124` | |
| `tts_audio` | `responder.py:58,106` | — | **Nothing.** Excluded from the wire (`schemas.py:22-23`); Streamlit generates its own (`ui/app.py:87-94`) | **Written, never read.** `VERIFIED` |
| `disruption_status` | `monitor.py:43,55,70` | — | `builder.py:72`, `responder.py:113`, `nlu/responder.py:108`, `routes.py:223` | |
| `alternative_route` | `replanner.py:75` | — | `monitor.py:34`, `responder.py:117,119`, `nlu/responder.py:113,176` | |
| `replan_attempts` | `builder.py:176`; `planner.py:76` | `replanner.py:39` | `builder.py:78`, `monitor.py:32`, `responder.py:116`, `nlu/responder.py:109` | |
| `original_disruption` | `monitor.py:81` | — | `nlu/responder.py:173,210`, `JourneyPlan.tsx:37` | Only ever written when a disruption is active — i.e. never, by default |
| `final_response_native` / `_en` | `responder.py:62-63,104-105` | — | `routes.py:101-105` | |
| `trace` | every node | every node | `routes.py:219`, `AgentTrace.tsx` | |
| `error` | `planner.py:54,64,100,113` | — | `builder.py:64`, `responder.py:50`, `JourneyPlan.tsx:137` | |

**Written but never read:** `tts_audio`. `VERIFIED`
**Read but not reliably written:** `optimise_for` (read at `ranker.py:183`; only ever written on the conversational path). `original_disruption` is read in three places but written only under a condition that is false by default. `VERIFIED`

### 2.4 The three entry points (`graph/builder.py`)

| Entry point | Signature | Seeds state from | Used by |
|---|---|---|---|
| `run_commute_agent` (`:214`) | raw string | `_blank_state()` + `user_query` | `POST /api/v1/query` (`routes.py:299`); CLI `run-agent` (`builder.py:293`); `tests/test_graph.py` |
| `run_commute_agent_from_intent` (`:236`) | parsed intent dict | `_state_from_intent()` | `POST /api/v1/chat` (`routes.py:150`); Streamlit (`ui/app.py:465`) |
| `stream_commute_agent_from_intent` (`:255`) | parsed intent dict | `_state_from_intent()` | `GET /api/v1/chat/stream` (`routes.py:213`) — **the Next.js frontend's only path** (`frontend/src/lib/api.ts:115`) |

**The Next.js frontend uses only the streaming entry point.** `VERIFIED`
**None of the three is dead**, but `run_commute_agent` is reachable from the UI by no route — only `POST /api/v1/query`, which no frontend calls. `VERIFIED`

The functional difference between #1 and #2/#3: #1 leaves `origin`/`destination` as `None`, so `planner.py:34` takes the NLU branch and calls Groq; #2/#3 pre-populate them, so the planner skips NLU entirely (`planner.py:36-44`). This is also why `optimise_for` survives on #2/#3 and not on #1.

### 2.5 Conditional routing and the replan loop

Three routers, all in `builder.py`:

- `_route_after_planner` (`:62-66`) — `"responder"` if `error` **and** no `candidate_route`; else `"bus_rag"`. Note the conjunction: `planner.py:99` sets `error` for "no routes of your preferred mode" while a `candidate_route` still exists, so that case correctly continues down the pipeline.
- `_route_after_monitor` (`:69-86`) — `CLEAR` → `"responder"`; else if `replan_attempts >= settings.max_replan_attempts` → `"responder"` with a WARNING; else `"replanner"`.
- `_route_after_replanner` (`:89-91`) — unconditionally `"monitor"`.

**Iteration cap enforcement:** exactly one place — `builder.py:79`. The value comes from `Settings.max_replan_attempts` (`config.py:48`, default 2, overridable by env). It does **not** come from `config/settings.yaml:13`, which declares `graph.max_replan_attempts: 2` and is read by nothing.

**Is the loop provably bounded?** Yes. `VERIFIED` by reading `replanner.py:39` — `replan_attempts = state.get("replan_attempts", 0) + 1` executes unconditionally on every replanner visit, with no early return above it. Each monitor→replanner→monitor cycle therefore strictly increases the counter, and `builder.py:79` is a monotone termination test. Sequence: monitor(0) → replanner(→1) → monitor(1) → replanner(→2) → monitor(2) → `2>=2` → responder. Maximum 2 replans, 3 monitor visits. LangGraph's default recursion limit (25) is never approached.

**The second guard does not exist.** `replanner.py:7-8` claims *"The hard cap on iterations is enforced BOTH here (state guard) and in the conditional routing logic in builder.py — defence in depth."* Reading `replanner_node` (`:23-76`) in full: there is no comparison against `max_replan_attempts` anywhere. `settings.max_replan_attempts` is used only in a log format string (`:44`). `VERIFIED`

### 2.6 `conversation/intake.py` as a state machine

**Slots filled** (`PLANNING_FIELDS`, `intake.py:33-40`): `origin`, `destination`, `requested_time`, `preferred_mode`, `expected_arrival_time`, `optimise_for`.
**Bookkeeping slots** (underscore-prefixed, stripped by `plan_intent`, `:175-177`): `_time_asked`, `_arrival_asked`, `_awaiting`.

**Question order** (`next_clarification`, `:187-213`): both stations → origin → destination → departure time → arrival deadline → `None` (complete).

**Six outcomes** (`TurnOutcome`, `:59-79`):

| Outcome | Triggered at | Meaning |
|---|---|---|
| `CLARIFY` | `:357` | A slot is still empty; `message` is the question |
| `PLAN` | `:377` | All slots resolved and something changed — run the graph |
| `UNCHANGED` | `:367` | Complete but identical to `last_planned` — re-offer, don't replan |
| `RESTART` | `:339` | Had an intent, new parse yields no stations at all → treat as "start over" |
| `OFF_TOPIC` | `:322` | `OffTopicQueryError` from the parser |
| `PARSE_ERROR` | `:327` | `NLUParseError` from the parser |

**How `_awaiting` disambiguates:** `advance()` dispatches on `_awaiting` **alone** (`:305-315`) before any parsing. When a question is asked, the same call that returns it sets `_awaiting` to that `ClarificationKind` value (`:351-356`); the next turn routes the reply to `_apply_departure_answer` or `_apply_arrival_answer` and clears the flag. The two handlers behave differently on purpose: the departure handler runs a **full re-parse** (`:229`, so "8am, and actually from Maradana" works), while the arrival handler touches **only** `expected_arrival_time` (`:262-263`, so a terse "by 10" cannot rewrite the stations).

`_time_asked` / `_arrival_asked` are separate and serve a different purpose: they make a *skip* count as resolved (`:201`, `:211`), so declining to give a time doesn't re-ask forever. The docstring (`:13-15`) states the earlier Streamlit version inferred the pending field from these booleans alone and misfiled every departure answer as the deadline — `_awaiting` is the fix. `VERIFIED`

Skip vocabularies are hardcoded English-only sets (`:43-44`): `_SKIP_DEPARTURE = {now, skip, asap, any, anytime, whenever}`, `_SKIP_ARRIVAL = {no, none, skip, n, no deadline, nope, not really}`. A Sinhala or Tamil speaker saying "no" in their own language does not hit the skip path; it falls through to `parse_update`, which costs a Groq call and may return a spurious time. `VERIFIED` (code read)

### 2.7 Are prompts and personas genuinely externalised?

**No.** `config/prompts.yaml` holds the 6 LLM prompt templates, and all 6 are read through `settings.prompts_config` (`nlu/parser.py:39,135`; `nlu/responder.py:139,184,213`; `train_rag.py:63`). That much is true. But substantial user-facing text is hardcoded:

| Location | What |
|---|---|
| `intake.py:84-140` | 7 trilingual template tables — `_ASK_BOTH`, `_ASK_ORIGIN`, `_ASK_DESTINATION`, `_ASK_TIME`, `_ASK_ARRIVAL`, `_RESTART`, `_OFF_TOPIC`, plus `WELCOME` |
| `nlu/responder.py:87-91` | `_CLARIFY` trilingual fallback table |
| `responder.py:124-134` | `_format_uber_suggestion` — ride-hailing markdown, English only |
| `responder.py:137-185` | `_format_last_mile_options` — last-mile markdown, English only |
| `planner.py:54-56` | Off-topic message, English only |
| `routes.py:156,231` | Graph-failure message, English only |

`config/prompts.yaml:89-92` contains a `clarify_query` block that duplicates `nlu/responder.py:87-91` — and **nothing reads it**. The code uses its own hardcoded copy. `VERIFIED`

`config/agents.yaml` (4 personas, 68 lines) is read by nothing at all. `VERIFIED`

---

## 3. Part 2 — Data inventory and provenance

### 3.1 Provenance baseline

The entire repository is **2 commits**: `4dcd671` "Initial commit" and `33eb79f` "Agentrix" (2026-07-27). Every data file arrived in a single squashed commit with a one-word message. `git log --follow` on each file yields exactly one entry. **There is no per-file provenance in git history for any dataset.** `VERIFIED`

All six JSON files have mtime `2026-07-27 13:41` — the checkout time, not an authoring time. Filesystem mtime carries no information here. `VERIFIED`

### 3.2 `data/routes.json`

- **Size** 4,138 bytes. **Records** 6. `VERIFIED`
- **Schema**: `route_id, line, stops[], departure_times[], arrival_times[], days_of_operation[], transit_mode, vehicle_type, description`
- **Coverage**: 2 corridors only.
  - `Colombo–Kandy`: 3 trains (1015 InterCity Express, 1019 Intercity weekdays-only, 1035 Intercity). Stops: Colombo Fort, Maradana, Kelaniya, Veyangoda, Polgahawela, Peradeniya Junction, Kandy.
  - `Colombo–Galle`: 3 trains (8731, 8745, 8761). Stops: Colombo Fort, Maradana, Mount Lavinia, Moratuwa, Panadura, Kalutara South, Hikkaduwa, Galle.
  - **Not covered**: the Northern Line (Jaffna, Vavuniya, Anuradhapura), the Main Line beyond Kandy (Badulla, Nanu Oya, Ella), the Coastal Line beyond Galle (Matara, Beliatta), the Puttalam Line, the Batticaloa/Trincomalee lines, the Kelani Valley Line, and **every suburban Colombo service**.
- **Structural defect**: `departure_times` and `arrival_times` are **byte-identical arrays in all 6 of 6 records** (`VERIFIED` by comparison). They are per-stop timestamps duplicated into both fields, so `RouteOption.arrival_time` (`models.py:77`) returns the last stop's time and `departure_time` the first — which happens to work, but the file encodes no genuine arrival-vs-departure distinction.
- **Provenance**: `UNKNOWN`. No source URL, no comment, no generating script. `scripts/ingest_timetables.py` claims to extract from `data/raw/*.pdf`, but `extract_from_pdfs` never implements extraction (`ingest_timetables.py:38-41` logs *"PDF extraction not yet implemented"*) and `_parse_table` returns `[]` (`ingest_timetables.py:44-46`). `data/raw/` does not exist. The route IDs (1015, 1019, 1035, 8731, 8745, 8761) resemble real Sri Lanka Railways train numbers, which suggests manual transcription, but **I cannot confirm this** — it is equally consistent with plausible invention.
- **Staleness**: no internal date field, no validity window. Last commit 2026-07-27.
- **Self-declared reliability**: none. This file makes no admission of its own status.
- **Verifiability**: yes — against the Sri Lanka Railways published timetable (railway.gov.lk) or trainschedule.lk. A domain expert could check all 6 records in minutes.
- **Runtime relevance: none.** Its only consumer chain is dead (see 4.1). `VERIFIED`

### 3.3 `data/stations.json`

- **Size** 7,407 bytes. **Records** 390 station names; declared `total: 390` matches actual `len(stations) == 390`. `VERIFIED`
- **Schema**: `{source: str, total: int, stations: [str]}`
- **Coverage**: nationwide station-name list, alphabetical Abanpola → Yattalgoda. Includes Northern Line (Ariviyal Nagar, Anuradhapura), Hill Country (Ambewela), Southern (Ahangama, Ambalangoda). **Names only** — no coordinates, no line membership, no ordering, no codes.
- **Provenance**: **the only file with a declared source** — `"source": "https://trainschedule.lk/"` (`data/stations.json:2`). Scraped or transcribed from that site. `VERIFIED` that the claim exists; `INFERRED` that it is accurate (the format and inconsistent casing — `"Al wala"`, `"aluth ambalama"` lowercase among otherwise title-cased entries — is consistent with automated extraction).
- **Staleness**: no date field. `UNKNOWN` when it was captured.
- **Self-declared reliability**: none beyond the source URL.
- **Verifiability**: yes, against trainschedule.lk (the declared source) or the SLR station list. Note trainschedule.lk is itself a third-party aggregator, **not** an authoritative government source.
- **Runtime relevance**: real. Loaded at `train_rag.py:44-50` and injected into the `map_station_name` Groq prompt (`train_rag.py:69-71`) — the full 390-name JSON array goes into every station-mapping call, twice per train query.

### 3.4 `data/bus_timetables.json`

- **Size** 6,867 bytes. **Records** 20. `VERIFIED`
- **Schema**: `route_number, route_name, origin_stop, destination_stop, departures[], journey_time_minutes`
- **Coverage**: 20 routes, 7–26 departures each. Predominantly long-distance from Colombo (Bastian Mawatha / Pettah) to Kandy, Matale, Nuwara Eliya, Galle, Matara, Kurunegala, Anuradhapura, Negombo, Balangoda, Digana; plus a handful of regional (Kandy–Mawanella, Kandy–Awissawella, Kandy–Anuradhapura, Matara–Dickwella, Matara–Akurassa) and two Colombo-area (103 Narahenpita–Fort, 138 Kadawatha–Pettah).
  **Not covered**: essentially all Colombo suburban corridors (Maharagama, Nugegoda, Dehiwala, Moratuwa, Kottawa, Malabe, Battaramulla), all Eastern Province, all Northern Province, all private-operator route networks.
- **Integrity defects** — `VERIFIED` by inspection:
  - **`route_number: "EX1"` appears twice** (Colombo–Galle Expressway SLTB, and Colombo–Matara Expressway). `_find_timetable` (`bus_rag.py:78-80`) returns the **first** exact match, so a Maps description containing `Bus No.EX1` bound for Matara silently receives the **Galle** schedule. Confirmed by execution: `'Bus No.EX1 — … Alight at Matara'` → matched `('EX1', 'Colombo - Galle (Expressway SLTB)')`.
  - **`origin_stop`/`destination_stop`/`journey_time_minutes` frequently describe a sub-segment, not the named route.** Clear-cut cases: `32 "Colombo - Kataragama"` → `Bus Stand Matara → Ruhuna Campus`, **15 min**; `346 "Matara - Dickwella"` → `Bus Stand Matara → Ruhuna Campus`, 12 min; `360 "Matara - Akurassa"` → `Southern Express → Matara` ("Southern Express" is not a bus stop); `08 "Colombo - Matale"` → destination `Kandy Clock Tower`; `79 "Colombo - Nuwara Eliya"` → destination `Peradeniya`; `9 "Colombo - Digana"` → destination `Hotel Suisse`; `662 "Kandy - Mawanella"` → `Peradeniya → Kandy Goods Shead`, 20 min; `98 "Colombo - Balangoda"` → destination `Awissawella`; `103 "Narahenpita - Fort"` → `Pettah Bus Stop → Technical Junction Maradana`. **This matters directly**: `journey_time_minutes` is what `_compute_arrival` (`bus_rag.py:134-142`) adds to the departure to produce the arrival time shown to the user. A 15-minute journey time attached to a Colombo–Kataragama route produces a fabricated arrival.
- **Provenance**: `UNKNOWN`. No source field, no comment, no scraper. The stop names ("Kandy Goods Shead Bus Stand" — note the misspelling of "Shed", "Bastian Mawatha Bus Stand", "Pettah Slt Bus Stop") read like manual transcription from signage or a Google Maps place list rather than an NTC dataset. The internal inconsistencies above are more consistent with **hand-assembled, partly-guessed data** than with any authoritative extract. `INFERRED`
- **Staleness**: no internal date. `UNKNOWN`.
- **Self-declared reliability**: **none.** Unlike `fares.json`, this file makes no admission — and it is the file most directly responsible for departure and arrival times shown to users.
- **Verifiability**: partially. The National Transport Commission (NTC, ntc.gov.lk) publishes route numbers and permitted operators; SLTB (sltb.lk) publishes some schedules. A domain expert could verify route numbers and endpoints, but departure lists for private operators are not centrally published.

### 3.5 `data/fares.json`

- **Size** 1,944 bytes. **Records**: not a record list — a rate model with `bus` and `train` sections, 3 classes each. `VERIFIED`
- **Schema**: `_README[], currency, verified, source, last_reviewed, //, unverified_range_pct, bus{minimum_fare, minimum_covers_km, per_km, classes[]}, train{…}`
- **Coverage**: mode-and-distance model, nationwide by construction. Bus: LKR 30 minimum covering 5 km, 3.2/km beyond, ×1.0/1.5/2.2 for Normal/Semi-luxury/Luxury. Train: LKR 20 minimum covering 5 km, 1.3/km, ×1.0/1.85/3.4 for 3rd/2nd/1st.
- **Provenance**: **explicitly self-declared as invented.** `"source": "unverified placeholder rates"` (`:22`), `"verified": false` (`:21`). The `_README` states: *"ESTIMATES — NOT OFFICIAL TARIFFS"* (`:3`) and *"The rates below are plausible placeholders chosen to produce realistic magnitudes, NOT transcribed from a published tariff"* (`:11-13`). `VERIFIED`
- **Staleness**: `"last_reviewed": "2026-07-27"` (`:23`) — i.e. yesterday, and reviewed as *unverified*.
- **Self-declared reliability**: the strongest in the repo. Also echoed in `tools/fare_tool.py:10-13` and README:278-280.
- **Verifiability**: yes. NTC bus fare schedule (stage-based) and Sri Lanka Railways distance-and-class tariff. The `_README` names both (`:5-7`) and notes neither publishes a machine-readable feed.
- **Handling quality — the one component that gets uncertainty right.** Executed: a 120 km train route yields `{amount: 170, max_amount: 576, uncertainty_pct: 0.25, estimated: true, verified: false}`. The 25% margin flows to `FareEstimate.uncertainty_pct` (`types.ts:81`) and is rendered with *"rates unverified, treat as a guide"* (`RouteCard.tsx:63`). Class spread and rate uncertainty are deliberately kept separate (`fare_tool.py:136-140`). Unpriceable routes get `None`, never 0, and sort last under "cheapest" (`ranker.py:119`). `VERIFIED`

### 3.6 `data/disruptions.json`

- **Size** 1,837 bytes. **Records** 5. `VERIFIED`
- **Schema**: `disruption_id, train_id, affected_segment, type, delay_minutes, active, message`
- **Coverage**: 2 segments only — `Fort Railway station - Kandy` (D001 delay 45m, D003 delay 30m, D005 cancellation) and `Fort Railway station - Galle Railway Station` (D002 cancellation, D004 delay 60m).
- **`active` is `false` for all 5** (`:8, :17, :26, :35, :44`). `VERIFIED`
- **`train_id` values are `GMAPS-0`, `GMAPS-1`, `GMAPS-5`** — Google Maps synthetic route indices assigned at `google_maps_tool.py:182`, not train identifiers. **The field is never used for matching**: `check_disruption` matches only on substring containment of route origin/destination in `affected_segment` (`retrieval.py:147-148`). So `train_id` is decorative and its values are meaningless. `VERIFIED`
- **Provenance**: **invented as demo fixtures.** The `retrieval.py:129` docstring says *"Reads from disruptions.json (simulating a live feed)"*; the API exposes `POST /disruptions/{id}/activate` described as a *"Demo helper"* (`routes.py:329`). `VERIFIED`
- **Staleness**: no date field. Irrelevant — this is not real-world data.
- **Self-declared reliability**: `retrieval.py:129` "simulating a live feed"; README:337 "Simulated live disruption feed".
- **Verifiability**: **no.** There is no authoritative Sri Lankan real-time rail disruption feed to check against; that is precisely why this is simulated.
- **Matching brittleness** — `VERIFIED` by execution with all 5 forced active:

  | Route origin → destination | Result |
  |---|---|
  | `Colombo Fort` → `Kandy` | `delayed` |
  | `Colombo Fort Railway Station` → `Kandy Railway Station` | **`clear` — missed** |
  | `Fort Railway station` → `Kandy` | `delayed` |
  | `Maradana` → `Galle` | **`cancelled` — false positive** |
  | `Colombo Fort` → `Galle Railway Station` | `cancelled` |

  Two failure directions. **False negative**: `retrieval.py:147-148` tests `route_origin in segment`, so the *route's* name must be a substring of the *segment*. `"colombo fort railway station"` is not a substring of `"fort railway station - kandy"`, so the fuller stop names Google Maps commonly returns silently miss the disruption. **False positive**: matching is `origin OR destination`, so any route merely *touching* Galle is flagged as cancelled — Maradana→Galle is reported cancelled even though the disruption concerns the Fort–Galle service.

### 3.7 `data/ride_distances.json`

- **Size** 1,619 bytes. **Records** 3. `VERIFIED`
- **Schema**: `_comment, from_aliases[], to_aliases[], distance_km, typical_duration_min`
- **Coverage**: exactly 3 last-mile hops — Galle centre → Karapitiya Teaching Hospital (3.0 km), Colombo Fort → National Hospital (1.2 km), Kandy centre → Kandy General Hospital (1.5 km). All three are hospital runs. Everything else falls through to `rng.uniform(1.5, 24.0)` (`ride_service.py:121`).
- **Provenance**: manually curated, self-documented per record. Entry 1 says *"Real-world distance ~3km. Includes the exact stop name Google Maps Directions returns for this corridor (verified 2026-07)"* (`:3`). `VERIFIED`
- **Staleness**: `"verified 2026-07"` inline in entry 1 only; entries 2 and 3 carry no verification claim.
- **Self-declared reliability**: partial — entry 1 claims verification, 2 and 3 give distances with "~" in prose (`:24`, `:40`) but no flag.
- **Verifiability**: trivially, via any mapping service. These are short, checkable distances.
- **Purpose is narrow and honest**: `ride_service.py:5-7` says these exist so *"demo-relevant journeys (e.g. a hospital last-mile hop) [stay] realistic instead of an arbitrary 1.5-24km random distance"* — i.e. it is explicitly demo scaffolding.

### 3.8 `data/chroma_db/` (present, gitignored)

- **Size** 1,012 KB. Excluded by `.gitignore:25`, so it exists only in this working copy. `VERIFIED`
- **Contents** (read directly from `chroma.sqlite3`):
  - `sri_lanka_railways_routes` — **6 documents**, one per `routes.json` route. Stored document text is the `description` field; metadata `route_id, line, origin, destination, departure_time, arrival_time, transit_mode`.
  - `sri_lanka_bus_timetables_docs` — **100 documents**. Metadata `route_name, category, subcategory, source_file, sample_schedule`. **`category` and `subcategory` are the empty string on all 100** — the YAML frontmatter they were read from (`ingest_bus_docs.py:123-124`) did not contain them. Consequently every embedded document text is degraded to the form `"<route_name> bus route (, )"` (`ingest_bus_docs.py:128`), e.g. `"Ambalangoda -Colombo bus route (, )"`. The embeddings are therefore over little more than a route-name string. `VERIFIED`
- **Corpus coverage**: predominantly long-distance SLTB routes terminating in Colombo (`Matara-Colombo`, `15-87 Jaffna - Colombo`, `49 Trincomalee - Colombo`, `Badulla - Colombo New Panal 2022-10-21`), plus Kandy/Kurunegala/Anuradhapura regional. **No Colombo suburban routes at all.** At least 9 route names are duplicated across the 100 documents (e.g. `15-7 Vavuniya - Colombo`, `88-2 Trinco - Vauniya`, `31 Galle - Bandarawela, Ampara` each appear twice) — 100 files, fewer distinct routes.
- **Provenance**: `UNKNOWN` and **unrecoverable from this repository.** The source `data/processed/bus/**/*.md` is gitignored (`.gitignore:26`) and absent from disk. `ingest_bus_docs.py:5-8` describes them as *"~100 documents … extracted from PDF timetables"* whose *"narrative Sinhala text is corrupted by a font-encoding issue in the original PDF-to-markdown conversion (garbled `(cid:NN)` glyph codes)"*. Which PDFs, from which authority, when — not recorded. Several route names embed dates (`2025.12.24`, `2026.01.20`, `2022-10-21`, `New Imp 2025.10.10`) that look like NTC/SLTB timetable revision dates, which **suggests** an authoritative origin, but the chain of custody is broken. `INFERRED` at best.
- **Self-declared reliability**: strong and repeated. `bus_rag.py:14-15`: *"the archived data is best-effort (PDF-extracted, of unknown freshness)"*. `retrieval.py:83-86`: *"treat as a 'we found this in the archive' signal, not a live/authoritative schedule"*.
- **Verifiability**: **no** — not without recovering the source PDFs. That is the critical gap.

### 3.9 Summary table

| File | Records | Coverage | Provenance | Staleness | Trust | Confidence |
|---|---|---|---|---|---|---|
| `routes.json` | 6 | 2 rail corridors (Colombo–Kandy, Colombo–Galle); no Northern/Hill/Coastal-beyond-Galle/suburban | `UNKNOWN` — no source, no scraper; IDs look real | No date; single squashed commit | **Low** — and **inert at runtime** | `VERIFIED` (content, inertness); `UNKNOWN` (origin) |
| `stations.json` | 390 | Nationwide station **names only**; no coords/lines/order | Declared `https://trainschedule.lk/` — 3rd-party aggregator, not SLR | No date | **Medium** — plausible, name-only, low blast radius | `VERIFIED` (claim); `INFERRED` (accuracy) |
| `bus_timetables.json` | 20 | Mostly Colombo long-distance + 2 Colombo-area; **no suburban network** | `UNKNOWN` — no source; internal inconsistencies suggest hand-assembly | No date | **Low** — duplicate `EX1`; 9+ records whose stops/journey-time contradict the route name | `VERIFIED` (defects); `INFERRED` (origin) |
| `fares.json` | 2 schemes × 3 classes | Nationwide by model | **Self-declared invented placeholders** | `last_reviewed: 2026-07-27`, unverified | **Low values, high integrity** — correctly hedged end to end | `VERIFIED` |
| `disruptions.json` | 5 (0 active) | 2 segments (Fort–Kandy, Fort–Galle) | **Invented demo fixtures**; `train_id` values meaningless | n/a | **n/a — simulation**, but matching is brittle both ways | `VERIFIED` |
| `ride_distances.json` | 3 | 3 hospital last-mile hops | Manually curated, per-record comments; 1 of 3 claims verification | `"verified 2026-07"` on 1 record | **Medium** for the 3; everything else is `rng.uniform(1.5,24)` | `VERIFIED` |
| `chroma_db/` bus collection | 100 docs | Long-distance SLTB → Colombo; **no Colombo suburban**; ≥9 dupes | `UNKNOWN` — **source markdown absent and gitignored** | Route names embed 2022–2026 revision dates | **Low** — degraded embed text `"X bus route (, )"`; wrong matches above threshold | `VERIFIED` (contents); `UNKNOWN` (origin) |
| `chroma_db/` routes collection | 6 docs | Mirror of `routes.json` | Derived from `routes.json` | Same | **n/a — queried by no live code** | `VERIFIED` |

---

## 4. Part 3 — RAG pipeline: what actually retrieves at runtime

### 4.1 Live vs. orphaned retrieval paths

| Function | Location | Status |
|---|---|---|
| `retrieve_bus_timetable` | `retrieval.py:75` | **LIVE** — called from `bus_rag.py:127` |
| `retrieve_routes` | `retrieval.py:28` | **ORPHANED** — only caller is `tools/route_tool.py:19`, which nothing imports. Also referenced in `tests/test_retrieval.py:68,76,85` |
| `_semantic_search_routes` | `retrieval.py:162` | **ORPHANED** — reachable only via `retrieve_routes` |
| `_load_all_routes` | `retrieval.py:197` | **ORPHANED** — called from `retrieve_routes` (`:56`) and `_semantic_search_routes` (`:183`) only |
| `_build_filter` | `retrieval.py:213` | **ORPHANED** — called from `_semantic_search_routes` only |
| everything in `tools/route_tool.py` | — | **ORPHANED MODULE** — zero importers |
| `check_disruption` | `retrieval.py:125` | **LIVE** — via `disruption_tool.py:18` → `monitor.py:58` |
| `embed_texts` | `embedder.py:34` | **ORPHANED** — no callers. Only `get_embedding_function` (`:28`) is used, by `chroma_client.py:20,42` |
| `ingest_routes` | `ingest.py:25` | Script-only (`ingest_timetables.py:66`, `pyproject.toml:43`) — populates a collection nothing queries |
| `ingest_bus_docs` | `ingest_bus_docs.py:99` | Script-only (`pyproject.toml:44`) — populates the one collection that is queried |
| `extract_from_pdfs` / `_parse_table` | `ingest_timetables.py:20,44` | **STUBS** — extraction never implemented; `_parse_table` returns `[]` |

**Named dead retrieval code:** `retrieve_routes`, `_semantic_search_routes`, `_load_all_routes`, `_build_filter`, the whole of `tools/route_tool.py`, `embed_texts`, and the `sri_lanka_railways_routes` collection they serve. `VERIFIED`

### 4.2 `bus_rag` — the two paths

**Primary path (route-number lookup)** — `bus_rag.py:170-219`:
1. `_extract_route_number` (`:49-59`) regexes `Bus No\.([A-Z0-9]+(?:-\d+)?)` out of the Maps description; falls back to a loose `\b([A-Z]{2,}\d*(?:-\d+)?|\d{2,3}(?:-\d+)?)\b`.
2. `_find_timetable` (`:67-86`) tries an exact `route_number` match first (so `"01"` Normal and `"001"` A/C Luxury stay distinct), then a zero-stripped match **only if it resolves to exactly one candidate**, else `None`.
3. On a hit: `departure_times` and `arrival_times` are **overwritten** with `[next_dep]` and `[computed_arrival]` (`:210-211`), where arrival = departure + `journey_time_minutes` (`:134-142`).

Executed behaviour:

| Maps description fragment | Extracted | Matched |
|---|---|---|
| `Bus No.EX1-18 …` | `EX1-18` | `None` (ambiguous — two `EX1` rows) |
| `Bus No.138 (Kadawatha - Pettah)` | `138` | `('138', 'Kadawatha - Pettah')` ✓ |
| `Bus No.01 (Colombo - Kandy)` | `01` | `('01', 'Colombo - Kandy (Normal)')` ✓ |
| `Bus No.001` | `001` | `('001', 'Colombo - Kandy (A/C Luxury)')` ✓ |
| `Bus No.EX1 … Alight at Matara` | `EX1` | `('EX1', 'Colombo - Galle …')` ✗ **wrong** |
| `Bus No.155 (Mount Lavinia - Borella)` | `155` | `None` (not in the 20) |
| `Bus (Colombo - Kandy)` (no number) | `None` | `None` |

`VERIFIED`

**Fallback path (semantic)** — `_rag_fallback_lookup` (`bus_rag.py:113-131`): builds the query `f"bus from {stops[0]} to {stops[-1]}"`, calls `retrieve_bus_timetable(query, top_k=1)`, wraps any exception and returns `None`. Its result is attached **only** as `_timetable_route_name` and `_rag_match` metadata (`:187-194`) — it **never** touches `departure_times`/`arrival_times`. The docstring claim at `bus_rag.py:12-15` is accurate on this point. `VERIFIED`

**What happens right now when the fallback fires and the Chroma directory is absent** — `VERIFIED` by execution against a fresh temp `CHROMA_PERSIST_DIR`:

> It **silently no-ops, and creates the directory as a side effect.** `chroma_client.py:40` uses `get_or_create_collection`, so `PersistentClient` materialises the missing directory and an empty collection. The query returns empty `ids`, the loop at `retrieval.py:106` never executes, and `retrieve_bus_timetable` returns `[]`. It does **not** raise. Observed: `persist dir exists BEFORE: False` → `RESULT: [] (type list, len 0)` → `exists AFTER: True ['chroma.sqlite3']`. The `try/except` at `retrieval.py:97-99` is therefore not even the mechanism — the no-op happens on the success path. The only trace is `INFO retrieve_bus_timetable: 0 match(es)`.

**In this checkout the directory is present and populated**, so the fallback does fire — and returns wrong answers (see 4.6).

### 4.3 `train_rag` — station mapping, scrape, timeouts

1. **Station-name mapping** (`_map_station_name`, `:58-92`): loads all 390 names from `stations.json`, formats the `map_station_name` prompt with the full JSON array, and calls Groq at `temperature=0.0`. Called **twice per train query** (`:203-204`), once per endpoint. Strips markdown fences, parses `{"matched_station": …}`. Any exception → `None` → falls back to the raw Maps name (`:206-209`). Note `except (json.JSONDecodeError, Exception)` (`:90`) is effectively a bare `except Exception`.
2. **Polite delay**: unconditional `time.sleep(0.5)` (`:212`).
3. **Scrape** (`_scrape_schedule`, `:95-145`): GET `_SCRAPE_BASE` (`:39`) with `timeout=10` (`:40`) and a `Mozilla/5.0 (CommuteAI; educational use)` UA. **No retry** — a single `requests.get`, `RequestException` → `[]`.
4. **Parse**: takes `soup.find("table")` — the **first** table on the page. Skips row 0. Per row, collects cells matching `^\d{1,2}:\d{2}` as times and picks the first non-time non-empty cell as `train_name`.

**What the user sees on each external-source failure:**

| Failure | Behaviour | User sees |
|---|---|---|
| Site unreachable / DNS / connection refused | `RequestException` → `[]` (`:110-112`) | Nothing. Google Maps times retained (`:215-220`). **Correct degradation.** |
| Site slow (> 10s) | `requests.Timeout` → `[]` | Same — but the turn has already spent 10s |
| Non-2xx | `raise_for_status()` → `[]` | Same |
| **HTML structure changed** | No `<table>` → `[]` (`:117-120`) | Same |
| **URL semantics changed while still returning 200 with a table** | **Parsed and trusted** | **Wrong times, presented with full confidence** — this is what is happening now |

**The current failure is the last row, and it is silent by construction.** `_SCRAPE_BASE` (`:39`) contains a hardcoded path segment `abucnia` that pins one specific journey. Verified: the URL returns HTTP 200 with a valid table for **every** slug — `colombo-fort-to-kandy`, `colombo-fort-to-galle`, `maradana-to-jaffna`, and the invented `xyzzy-to-nowhere` all return a table whose text has identical MD5 `02da5090...`. The page's `<title>` is **"Colombo Fort to Rambukkana Train Time Table/Schedule"**, and its column headers are `['Colombo Fort  (departure)', 'Rambukkana (arrival)', 'Duration', 'Train Ends At', 'Train Stops', 'Train Type']`. Row 1 is `['04:25 AM', '06:49 AM', '2h 24m', 'Rambukkana', '1125', 'Slow']`. `VERIFIED`

Two consequences follow from that row:
- `train_name` is parsed as **`"2h 24m"`** — the Duration column, not a train name — because `"2h 24m"` is the first non-time-shaped non-empty cell (`:130`). It is then prefixed to the description (`:238`).
- Times are `"04:25 AM"`, not `HH:MM`. `_find_next_trains` (`:157-174`) parses with `"%H:%M"` only, so **every** entry raises `ValueError` and lands in `after` (`:172-173`) — **the requested-time filter is entirely non-functional for scraped trains.** Confirmed: a 07:30 request returned `04:25 AM` as the first option.

Then `train_rag_node:225-239` **discards every Google Maps train route** and rebuilds `candidate_routes` from the scraped rows. `VERIFIED` end to end:

```
INPUT  GMAPS-0            dep ['07:35']    arr ['10:52']   (real Maps Colombo Fort→Kandy)
OUTPUT GMAPS-0-sched0     dep ['04:25 AM'] arr ['06:49 AM'] | "2h 24m — Train (Fort-Kandy) …"
       GMAPS-0-sched1     dep ['07:05 AM'] arr ['09:31 AM'] | "2h 26m — …"
       GMAPS-0-sched2     dep ['08:05 AM'] arr ['10:30 AM'] | "2h 25m — …"
```

Those are Colombo Fort → **Rambukkana** times. Rambukkana is ~35 km short of Kandy.

### 4.4 Embeddings, chunking, collections

- **Model**: ChromaDB's bundled `ONNXMiniLM_L6_V2` (`embedder.py:19,31`) — all-MiniLM-L6-v2, 384-dim, local ONNX, no API key, ~80 MB downloaded once. `VERIFIED`
- **`Settings.embedding_model = "models/text-embedding-004"` (`config.py:41`) is dead** — read by nothing. It names a Google embedding model that is never used. `VERIFIED`
- **Distance metric**: cosine, set per collection via `metadata={"hnsw:space": "cosine"}` (`chroma_client.py:43`). Similarity computed as `1 - distance` (`retrieval.py:107,186`).
- **Chunking**: **there is none.** Both ingesters embed one short string per record — no splitting, no overlap, no windowing.
  - `sri_lanka_railways_routes`: document = `RouteOption.description` (`ingest.py:44`), a single sentence.
  - `sri_lanka_bus_timetables_docs`: document = `f"{route_name} bus route ({category}, {subcategory})"` (`ingest_bus_docs.py:128`) — and since category/subcategory are empty for all 100, this is effectively **just the route name**.
- **Threshold**: `0.60` from `config/settings.yaml:6` via `settings.app_settings["retrieval"]["similarity_threshold"]` (`retrieval.py:92`). `top_k` from the same file is read only in dead code (`retrieval.py:43`); the live caller passes `top_k=1` explicitly (`bus_rag.py:127`).

### 4.5 Vector store state and what ingest would do today

Present: `data/chroma_db/` (1,012 KB), both collections populated (6 and 100). Gitignored (`.gitignore:25`) — a fresh clone has neither. `VERIFIED`

| Command | Effect if run today |
|---|---|
| `uv run ingest` | Runs `ingest_timetables:main` → `extract_from_pdfs()` finds no `data/raw/` PDFs, logs *"No PDFs found … using existing routes.json"*, returns `[]` → `ingest_routes()` upserts the 6 `routes.json` descriptions. **Succeeds, and is pointless** — no live code queries that collection. |
| `uv run ingest-bus` | `bus_dir = data/processed/bus` **does not exist**. `rglob` on a missing dir yields nothing → logs `WARNING No markdown files found` → **returns 0**. The existing 100 documents are left untouched (upsert is never reached). So the collection cannot currently be rebuilt or corrected. `VERIFIED` |

### 4.6 Per-query hit/miss

Traced through the code; the bus-RAG rows were executed against the live store.

| Query | Path fired | Local data found? |
|---|---|---|
| **Colombo Fort → Kandy (train)** | `train_rag`: 2× Groq map → scrape | **MISS, worse than miss.** Returns Rambukkana times, overwrites correct Maps times. `VERIFIED` |
| **Colombo Fort → Kandy (bus, `Bus No.01`)** | `bus_rag` primary | **HIT.** Matches `('01','Colombo - Kandy (Normal)')`, 26 departures, 180 min. Times overwritten with curated ones. `VERIFIED` |
| **Colombo → Galle (train)** | `train_rag` | **MISS, worse than miss.** Same Rambukkana page. `VERIFIED` |
| **Colombo → Galle (bus, `Bus No.EX1`)** | `bus_rag` primary | **HIT — but ambiguous.** `EX1` is duplicated; matches Galle first. Correct here by luck; a Matara `EX1` gets the Galle schedule. `VERIFIED` |
| **Maharagama → Colombo Fort (suburban bus)** | primary miss (`155`-class routes absent) → semantic fallback | **FALSE HIT.** Returns `Matara-Colombo` @ 0.736. Metadata only, so no time corruption — but a wrong route name is attached. `VERIFIED` |
| **Jaffna → Vavuniya (bus)** | primary miss → semantic fallback | **FALSE HIT.** `86 Batticolo - Jaffna` @ 0.647. `VERIFIED` |
| **Jaffna → Colombo (train)** | `train_rag` | **MISS.** Same Rambukkana page. No Northern Line data anywhere. `VERIFIED` |
| **Nugegoda → Dehiwala (suburban)** | primary miss → semantic fallback over an all-long-distance corpus | **MISS or false hit.** No suburban routes in either dataset. `INFERRED` |
| Live run, `Colombo Fort → Kandy` | `bus_rag` fallback fired for routes `38-1` and `100` | **FALSE HITS** @ 0.65 and 0.64. `VERIFIED` |

**Net:** the only path that reliably improves on Maps is the curated bus-timetable exact-number match, covering 20 route numbers (19 distinct, `EX1` duplicated).

---

## 5. Part 4 — The Google Maps / local data boundary

### 5.1 Field-by-field origin

Every route begins as a `RouteOption` built by `_extract_route` (`google_maps_tool.py:71-196`).

| Field | Origin | Overwritten by local data? |
|---|---|---|
| `route_id` | Maps — synthetic `f"GMAPS-{idx}"` (`:182`) | **Yes** — `train_rag.py:232` rewrites to `…-sched{i}` |
| `line` | Maps — first leg's `line.name`/`short_name` (`:128-130`) | No |
| `stops[]` | Maps — `transit_details.departure_stop/arrival_stop`, deduped at transfers (`:137-143`) | No |
| `departure_times[]` | Maps — per-stop `HH:MM` from unix timestamps (`:119`) | **Yes — both paths.** `bus_rag.py:210` (curated) and `train_rag.py:233` (scrape) |
| `arrival_times[]` | Maps (same array as `departure_times`, `:186`) | **Yes** — `bus_rag.py:211` (dep + `journey_time_minutes`), `train_rag.py:234` |
| `days_of_operation` | Maps — hardcoded `["daily"]` (`:187`) | No. **Always `["daily"]`, never verified.** `routes.json` has real per-day data, but it is inert |
| `transit_mode` | Maps — `HEAVY_RAIL`/`COMMUTER_TRAIN`/… → TRAIN, else BUS (`:23-26,126,131-132`) | No |
| `vehicle_type` | Maps — first leg's `line.vehicle.type` (`:125,129-130`) | No |
| `description` | Maps — per-leg "Board at X, Alight at Y" (`:146-179`) | **Yes** — `train_rag.py:238` prefixes the parsed `train_name` (currently a duration string) |
| `last_mile_distance_m` | Maps — trailing WALKING step, reset on each TRANSIT (`:102-108`) | No |
| `legs[]` | Maps — per-TRANSIT-step dicts (`:153-168`) | No |
| `polyline`, `stop_coords`, `bounds` | Maps (`:193-195`) | No |
| `fare_estimate` | **Local** — `fare_tool.estimate_fare` (`fares.py:43`) | n/a — purely additive; Maps supplies no fare |
| `_timetable_route_name`, `_journey_time_minutes`, `_rag_match`, `_train_name` | **Local** — added by `bus_rag`/`train_rag` | n/a — additive |
| `uber_options`, `uber_last_mile`, `last_mile_transit_leg` | **Local** — dummy `RideService` | n/a |
| `disruption_status` | **Local** — `disruptions.json` | n/a |

### 5.2 Every point where local data overrides Maps

| # | Location | Override | If the local data is wrong |
|---|---|---|---|
| **1** | `train_rag.py:225-239` | **Deletes all Maps train routes**, substitutes up to 5 scraped rows | **This is the current state.** The user gets Rambukkana times labelled Kandy. Maps' correct times are unrecoverable — they are not retained anywhere in state. **The system silently presents strictly worse information than Maps would have.** `VERIFIED` |
| **2** | `bus_rag.py:210-211` | Replaces Maps departure/arrival with curated timetable values | Wrong `journey_time_minutes` → wrong arrival. Given the ≥9 records whose journey time describes a sub-segment (3.4), this is live. A "Colombo–Kataragama" route carrying `journey_time_minutes: 15` yields a fabricated arrival 15 min after departure. **Silently worse than Maps.** `VERIFIED` |
| **3** | `bus_rag.py:187-194` | Adds `_rag_match` metadata on primary miss | Wrong route name attached. Does **not** corrupt times — `bus_rag.py:12-15` is accurate here. Lower severity. `VERIFIED` |
| **4** | `train_rag.py:238` | Prefixes `train_name` to `description` | Currently prefixes `"2h 24m"`, so descriptions read *"2h 24m — Train (Fort-Kandy) …"*. Cosmetic but visibly wrong. `VERIFIED` |
| **5** | `monitor.py`/`retrieval.py:144-156` | Overlays disruption status | False positives (any route touching Galle → cancelled) and false negatives (fuller Maps stop names miss the match) — both demonstrated in 3.6. Currently masked because all records are inactive. `VERIFIED` |

### 5.3 What the system provides that Maps does not

`VERIFIED` — these are real additions:

1. **Fare estimates with explicit uncertainty** — per-class breakdown and a ±25% margin (`fare_tool.py:144-155`, `RouteCard.tsx:28-65`). Maps shows no fares for Sri Lankan transit. The *values* are placeholders, but the *mechanism* and its honesty are genuine.
2. **Trilingual conversational intake and response** — Sinhala/Tamil/English throughout (`intake.py:84-140`, `prompts.yaml`), with an English gloss always present.
3. **Cost/speed/transfer optimisation as a first-class intent** — `optimise_for` parsed from natural language and used as a sort key (`ranker.py:158-167`).
4. **Deadline-aware ranking** — "must be there by 10:00" becomes a hard constraint outranking all preferences (`ranker.py:145,156`).
5. **Ride-hailing offered alongside the last transit leg** — `uber.py:163-184` presents both the local bus Maps picked *and* a ride quote for the same hop, rather than silently accepting Maps' choice. Sound design; the quotes are fake.
6. **A disruption-and-replan mechanism** — architecturally complete, currently fed by simulated data.
7. **Live agent trace over SSE** — `routes.py:208-236`, node-by-node.
8. **Server-side TTS in all three languages** — `routes.py:255-289`, since browsers lack Sinhala/Tamil voices.

### 5.4 Where the system silently trusts Maps with no local verification

`VERIFIED`:

- **Geometry** — `polyline`, `stop_coords`, `bounds` are passed through unchecked to the map (`google_maps_tool.py:193-195`).
- **Stop names** — `stops[]` is used verbatim as the ride-hailing pickup (`uber.py:170`) and as the disruption-matching key (`retrieval.py:141-142`), with no canonicalisation against `stations.json`.
- **Mode classification** — the `_RAIL_VEHICLE_TYPES` set (`:23-26`) decides train-vs-bus, which then decides which enrichment node fires and which fare scheme applies. Never cross-checked.
- **Leg distances** — `distance_m` (`:161`) is the sole input to every fare figure (`fare_tool.py:69`). Never validated.
- **`days_of_operation`** — hardcoded `["daily"]` (`:187`). Nothing verifies a service runs on the requested day. `routes.json` carries real weekday/daily data (e.g. train 1019 is `Mon–Fri`), but it is inert.
- **Route existence and orderings** — the whole candidate set is whatever Maps returns; `alternatives=True` (`:216`) with no independent check.

### 5.5 Is there any query where this system beats Google Maps alone?

**Stated plainly: no, not demonstrably — and for train queries the system is measurably worse.**

- **Train queries: strictly worse.** `VERIFIED` by execution. Maps returned a correct Colombo Fort→Kandy route; `train_rag_node` deleted it and substituted Rambukkana times. Every train query in the country hits this, because the URL is route-independent.
- **Bus queries: unproven either way.** `bus_rag` overwrites Maps times with curated ones for ~19 route numbers. Whether that is an improvement depends entirely on whether `bus_timetables.json` is more accurate than Maps' transit feed — and that file has **no provenance and no verification** (3.4), plus a duplicate `EX1` key and ≥9 records with self-contradictory journey times. I cannot claim it is better. I also cannot claim it is worse. `UNKNOWN`.
- **Fares: an addition, not an accuracy win.** Maps offers nothing to be more accurate *than*, and the numbers are self-declared placeholders. The honest framing is "we surface a hedged estimate where Maps is silent", not "we are more accurate".
- **Disruptions: inert.** All records inactive; bus routes skipped entirely.

**The one candidate.** The narrowest defensible claim would be: *for a bus route whose number appears exactly once in `bus_timetables.json` and whose curated `journey_time_minutes` is correct — e.g. `Bus No.138` Kadawatha–Pettah, 47 min — the `departure_times` field reflects a full published departure list (16 departures) rather than the single next departure Maps returns.* That is a **coverage** advantage (more departure options shown), not an **accuracy** advantage. And it rests on data whose origin is `UNKNOWN`.

**To demonstrate a genuine accuracy win, someone would have to verify `bus_timetables.json` against an NTC/SLTB published schedule and show a case where it is right and Maps is wrong. No such verification exists anywhere in this repository (see Part 7).**

---

## 6. Part 5 — External dependencies, failure modes, bottlenecks

### 6.1 Dependency register

| Dependency | Called at | Timeout | Retry | On failure | Fatal? |
|---|---|---|---|---|---|
| **Groq — NLU parse** (`llama-3.3-70b-versatile`) | `nlu/parser.py:114-119` via `planner.py:47` | None set (SDK default) | `stop_after_attempt(2)`, `wait_fixed(1)`, `reraise=True` (`parser.py:104-109`) | `NLUParseError` → planner early-returns with `error` (`planner.py:58-65`) | Degrades — user sees an error message |
| **Groq — intent update** | `parser.py:29-79` via `intake.py:229,262` | None | Same | Returns the current intent unchanged (`parser.py:51-61`) | Degrades silently |
| **Groq — station mapping** | `train_rag.py:74-79` | None | **None** | Bare `except` → `None` → uses the raw Maps name (`:90-92`) | Degrades silently |
| **Groq — response generation** | `nlu/responder.py:31-37` | None | `stop_after_attempt(2)`, **`reraise=False`** (`:119-124`, `:161-166`) | **Raises `RetryError`** after 2 failures — see R4 | **FATAL to the turn** |
| **Google Maps Directions** | `google_maps_tool.py:213-219` | None set | **None** | `RouteNotFoundError` → `candidate_routes=[]`, `error` set, pipeline continues to the Uber fallback | Degrades |
| **trainschedule.lk** (scrape) | `train_rag.py:108` | **10s** (`:40`) | **None** | `[]` → Maps times kept | Degrades — but see R1: the current failure returns 200 and is *not* detected |
| **gTTS** (graph) | `responder.py:28` | None | None | `None`, WARNING | Degrades; result unused anyway |
| **gTTS** (`/tts` endpoint) | `routes.py:270` | None | 1 retry in English (`:274-277`) | HTTP 502 (`:280-282`) | Degrades — audio only |
| **ChromaDB** (local ONNX) | `chroma_client.py:34`, `retrieval.py:96` | n/a | n/a | `[]` (`retrieval.py:97-99`), or silent empty result if the dir is absent | Degrades silently |
| **`ride_service.RideService`** | `uber.py:51-54` | n/a | None | `[]`, WARNING | Degrades. **In-process, no network — not a real dependency** |

### 6.2 Single points of failure for a live demo, ranked by likelihood

1. **`train_rag` already returns wrong data (P ≈ 1.0).** Not a risk — a present-tense defect. Every train query shows Rambukkana times. `VERIFIED`
2. **Groq quota / rate limit (high).** 3–5 calls per turn (NLU + 2× station mapping + response). Free-tier Groq is rate-limited. A response-generation failure is **fatal to the turn** (R4). Watch the two station-mapping calls: they burn quota on a scrape whose output is wrong anyway.
3. **`GROQ_API_KEY` missing/expired (high impact, binary).** README:147 marks it required. Without it, NLU and response generation both fail — nothing works.
4. **Google Maps API key / billing / quota (high impact).** `planner.py:81` is the sole source of routes. Failure → `candidate_routes=[]` → the run degrades to dummy ride quotes only.
5. **`trainschedule.lk` reachability (medium).** Measured 1.53s. If it goes down, the system *improves* — Maps times survive.
6. **Chroma / ONNX model on a cold machine (medium).** First `get_embedding_function()` downloads ~80 MB (`embedder.py:6-7`). Measured cold import+first query: **9.18s import, 6.84s first query**, then 0.07–0.16s. On a fresh machine with no network, the bus fallback silently no-ops.
7. **Multi-worker uvicorn (medium, self-inflicted).** `sessions.py:12-14` warns explicitly. Running `--workers 2` breaks multi-turn conversations non-deterministically.
8. **Disruption demo requires manual activation (medium).** All 5 records are inactive; the disruption/replan showcase is invisible unless someone POSTs `/api/v1/disruptions/{id}/activate` first. README:242 wrongly says D001 ships active.
9. **`data/chroma_db/` absent on a fresh clone (low impact).** Gitignored. The bus fallback silently no-ops; `ingest-bus` cannot rebuild it (source gone).
10. **gTTS network dependency (low).** Degrades to no audio.

### 6.3 Latency — measured

One full `Colombo Fort → Kandy` run via `stream_commute_agent_from_intent`:

| Node | Time | What dominates |
|---|---|---|
| `planner` | 0.60s | 1 Maps Directions call (NLU skipped — intent pre-populated) |
| `bus_rag` | 1.02s | Chroma queries (warm) |
| `train_rag` | **2.60s** | 2 Groq calls + 0.5s hardcoded sleep + 1.53s scrape |
| `fares` | 0.00s | pure local |
| `ranker` | 0.00s | pure local |
| `uber` | 0.00s | in-process dummy |
| `monitor` | 0.01s | local JSON |
| `responder` | **6.50s** | Groq response generation + ~1.02s gTTS |
| **Total** | **10.74s** | |

`VERIFIED`. Two slowest nodes are `responder` (60%) and `train_rag` (24%). Note the whole of `train_rag`'s 2.60s is spent producing wrong data, and ~1.02s of `responder`'s 6.50s produces audio nothing reads.

Cold-start additions measured separately: Chroma import 9.18s, first embedding query 6.84s.

### 6.4 Rate limits and quotas as configured

**No rate limiting, quota tracking, or backoff is configured for any external service anywhere in this repository.** `VERIFIED`

- Groq: no timeout, no rate-limit handling. Retry policy is `wait_fixed(1)` — fixed, not exponential (`parser.py:107`, `nlu/responder.py:122`). Two of the four call sites have no retry at all.
- Google Maps: no timeout, no retry, no quota tracking.
- trainschedule.lk: 10s timeout, no retry; politeness is a single unconditional `time.sleep(0.5)` (`train_rag.py:212`).
- The only throttling mechanism is the TTL cache (`tools/cache.py`) — 300s default (`config.py:44`), 60s for disruptions (`disruption_tool.py:25`). But it is applied **only** to `check_disruption` (`disruption_tool.py:41-42`), which makes no network call at all. **No Groq, Maps, or scrape result is cached.** `_DISRUPTION_TTL_OVERRIDE` (`disruption_tool.py:25`) is defined and never used — `cache.set` uses the global TTL (`cache.py:53`). `VERIFIED`

### 6.5 Session and state durability

- **In-process dict** (`sessions.py:68,126`), guarded by a `threading.Lock` that protects the map but not the `Session` objects (`sessions.py:59-65`).
- **Lost on restart**: every session — accumulated intent, `last_planned_intent`, `last_state`. The docstring concedes it: *"Deliberately in-process and non-durable … a restart losing them is acceptable"* (`sessions.py:8-9`).
- **Breaks under concurrency**: multi-worker deployment. *"Not safe across multiple worker processes: two uvicorn workers each get their own store, so a commuter's follow-up turn could land on a worker that has never seen them. Run the API single-worker, or move this to Redis first."* (`sessions.py:12-14`)
- **Bounded**: `SESSION_TTL = 2h`, `MAX_SESSIONS = 500` (`sessions.py:31-32`), enforced at `_evict_expired` (`:106`) and `_enforce_capacity` (`:114`).
- **Also process-global and lost on restart**: `tools/cache.py:21` `_store`, and the `lru_cache` singletons for settings (`config.py:107`), Chroma client/collections (`chroma_client.py:28,37`), the embedding function (`embedder.py:27`), the fare config (`fare_tool.py:37`), and the module-level `_timetables` (`bus_rag.py:38`) and `_stations_list` (`train_rag.py:37`). **The data files are read once per process** — editing `bus_timetables.json` or `stations.json` at runtime has no effect until restart. `disruptions.json` is the exception: `_load_active_disruptions` (`retrieval.py:205`) re-reads on every call, which is what makes the demo activation endpoint work. `VERIFIED`

---

## 7. Part 6 — Coverage, correctness, and confident wrongness

### 7.1 Fraction of plausible queries served by real local data

Reasoning, stated so the arithmetic can be disputed:

**Train queries.** Local coverage would be `routes.json` (2 corridors) — but it is inert (4.1). The only live train path is the scrape, which returns the same wrong page for every route. **Genuine local coverage: 0%.** `VERIFIED`

**Bus queries.** The primary path needs (a) Maps to emit a parseable `Bus No.X`, and (b) `X` to resolve in the 20-row table. The table holds 19 distinct route numbers against a national network in the thousands. Weighting by realistic demand, its content is Colombo↔major-city long-distance, with only 2 Colombo-area entries (103, 138) — and Colombo suburban commuting is where query volume actually concentrates. The Chroma fallback adds no coverage: it is also all long-distance, and it never corrects times.
**Optimistic ceiling: ~10–15% of bus queries**, concentrated in intercity travel. **For Colombo suburban commuting — the core use case for a "commute" agent — closer to 0–5%.** `INFERRED`

**Fares.** Every route with Maps leg distances gets an estimate — ~100% coverage, 0% verified.

**Disruptions.** 2 hardcoded segments, all inactive, buses excluded. **~0%.**

**Overall: on the order of 5–10% of plausible Sri Lankan commute queries have any real local data behind them, and for train queries the local layer is net-negative.** The remaining ~90%+ is Google Maps output plus an unverified fare estimate. `INFERRED` — the input distribution is a judgement, but the coverage counts underneath it are `VERIFIED`.

### 7.2 Geographic and modal gaps

**Geographic** — no local data of any kind for: Northern Province (Jaffna, Kilinochchi, Vavuniya), Eastern Province (Batticaloa, Trincomalee, Ampara), North Central beyond a single Anuradhapura bus, Uva (Badulla, Monaragala), Sabaragamuwa beyond one Balangoda entry, the entire Hill Country rail network (Nanu Oya, Ella, Haputale), and — most consequentially — **the Colombo suburban network**: Maharagama, Nugegoda, Dehiwala, Moratuwa, Kottawa, Malabe, Battaramulla, Kelaniya, Ja-Ela.

**Modal** — no local data for: private bus operators (the majority of Sri Lankan bus capacity), school/staff services, the Kelani Valley narrow-gauge line, ferries, and real ride-hailing (PickMe/Uber — `ride_service.py` is a dummy).

**Structural** — no coordinates for stations (`stations.json` is names only), no line membership or stop ordering, no per-day service calendars in any live path (`days_of_operation` is always `["daily"]`), no accessibility data, no real-time vehicle positions.

### 7.3 Risk register — confidently wrong information

Ranked by (likelihood × severity). This is the section that matters most.

---

**R1 — Train departure and arrival times are wrong for every train query, and stated with no hedge.**
`train_rag.py:39` (stale URL), `:225-239` (overwrite), `nlu/responder.py:139-152` (rendering).
**Likelihood: certain.** **Severity: critical.**
The scrape URL returns Colombo Fort → Rambukkana for every route. Those times replace correct Maps times and are then rendered by the `respond_clear` prompt, which is told the data is *"from Google Maps live data"* (`prompts.yaml:101`) and instructed to *"State exact departure and arrival times"* (`prompts.yaml:112`).
**Observed output:** *"You will depart from Fort Railway station at 08:05 AM and arrive at Kandy at 10:30 AM."* A commuter acting on this misses their train. There is no uncertainty marker anywhere in the sentence. `VERIFIED`

**R2 — Ride-hailing prices and availability are randomly generated and presented as firm quotes.**
`ride_service.py:121,150-153`; rendered `responder.py:130,173,182`.
**Likelihood: certain when the last-mile path fires.** **Severity: high.**
Distance is `rng.uniform(1.5, 24.0)`, availability is a 75% coin flip, surge is `rng.choice([1.0,1.0,1.0,1.2,1.5])`. Output: `- Tuk-tuk: LKR 780 · ETA 5 min · 9.1 km`. The word "estimate" appears nowhere. Compare the fare path, which hedges correctly — **this is the same class of unverified number handled to a completely different standard within one response.** `VERIFIED`

**R3 — Bus arrival times are computed from journey durations that contradict their own route names.**
`bus_rag.py:206-211`, `_compute_arrival` `:134-142`; data at `data/bus_timetables.json`.
**Likelihood: high.** **Severity: high.**
Arrival = departure + `journey_time_minutes`, and that field is wrong in at least 9 of 20 records (3.4): route 32 "Colombo–Kataragama" carries 15 minutes; route 346 "Matara–Dickwella" carries 12. These overwrite Maps' arrival times and are presented as scheduled fact. `VERIFIED`

**R4 — A response-generation failure crashes the turn instead of degrading.**
`nlu/responder.py:119-124` and `:161-166` use `@retry(..., reraise=False)`.
**Likelihood: medium** (rises with Groq rate limiting). **Severity: high.**
Verified experimentally: with `reraise=False`, tenacity raises **`RetryError`** — not the original exception, and not `None` — once attempts are exhausted. `RetryError` is not an `NLUParseError`, so it propagates through `generate_response` and `responder_node` uncaught, and is only caught at the API boundary (`routes.py:151`, `:226`), producing *"Sorry — I couldn't plan that journey just now."* All completed planning work is discarded. The `_clarification_response` fallback (`nlu/responder.py:226-232`) is unreachable in this path. `VERIFIED`

**R5 — Wrong bus route names attached via semantic fallback, above threshold.**
`bus_rag.py:184-199`, `retrieval.py:108-109`, threshold `config/settings.yaml:6`.
**Likelihood: high.** **Severity: medium** (metadata only — times are correctly left alone, `bus_rag.py:12-15`).
Measured: Colombo→Kandy → `Matara-Colombo` @ 0.731; Maharagama→Colombo → `Matara-Colombo` @ 0.736; Jaffna→Vavuniya → `86 Batticolo - Jaffna` @ 0.647. A 0.60 threshold over ~5-token route names admits almost anything. Two false hits occurred in the single live run. Severity is capped only because the fallback is disciplined about not touching times. `VERIFIED`

**R6 — "Cheapest" is silently ignored on the one-shot query path.**
`planner.py:67-77` omits `optimise_for`; `builder.py:174` seeds it `None`; `ranker.py:183` reads it.
**Likelihood: certain on `POST /api/v1/query` and the CLI.** **Severity: medium.**
The user asks for the cheapest route, the NLU extracts `optimise_for="cheapest"` (`models.py:21`), and the planner never writes it to state. Ranking silently falls back to balanced. Nothing tells the user their stated preference was dropped. The frontend is unaffected (it uses the conversational path). `VERIFIED`

**R7 — Duplicate `EX1` route number silently attaches the wrong schedule.**
`data/bus_timetables.json` (two `EX1` rows), `bus_rag.py:78-80`.
**Likelihood: certain for `EX1` bound for Matara.** **Severity: medium.**
Exact match returns the first row. Verified: `'Bus No.EX1 … Alight at Matara'` → Colombo–Galle schedule (90 min instead of 150). Ironically, `_find_timetable`'s docstring (`:71-76`) explains at length why ambiguity must return `None` rather than guess — the exact-match branch above it bypasses that protection entirely.

**R8 — Disruption false positives and false negatives.**
`retrieval.py:144-156`.
**Likelihood: low today** (all inactive) **but certain once activated.** **Severity: medium.**
`Maradana → Galle` reports **cancelled** on a Fort–Galle disruption. `Colombo Fort Railway Station → Kandy Railway Station` reports **clear** on an active Fort–Kandy disruption. Both verified by execution. Telling a commuter their train is cancelled when it is not is a real-world cost.

**R9 — `days_of_operation` is always `["daily"]` and never checked.**
`google_maps_tool.py:187`.
**Likelihood: certain.** **Severity: medium.**
No route is ever validated against the requested day. `routes.json` records genuine constraints (train 1019 is `Mon–Fri`), but that file is inert. A Sunday query can be answered with a weekday-only service.

**R10 — The requested-time filter does not work for scraped trains.**
`train_rag.py:157-174`.
**Likelihood: certain.** **Severity: medium.**
Scraped times are `"04:25 AM"`; the filter parses `"%H:%M"` only, so every entry raises `ValueError` and is treated as "departs after". Verified: a 07:30 request returned `04:25 AM` first.

**R11 — Journey duration silently reported as "unknown".**
`nlu/responder.py:51-66`.
**Likelihood: high for trains.** **Severity: low.**
`_calc_duration` parses `"%H:%M"` only, so `"04:25 AM"` throws and returns `"unknown"`. In the observed run the LLM papered over this by computing a duration itself, and then appended a self-contradictory sentence: *"note that the train will be running from 8:30 AM to 11:03 AM, but your arrival time is expected to be 10:30 AM."* Two different arrival times in one paragraph. `VERIFIED`

**R12 — Off-topic detection is a 6-word English regex.**
`guardrails.py:24-28` — `weather|stock|cricket|football|politics|recipe`.
**Likelihood: high.** **Severity: low.**
No Sinhala or Tamil terms at all, despite trilingual support being the headline feature. Backstopped by the LLM's own `off_topic` classification (`guardrails.py:61-62`), so the impact is limited.

---

## 8. Part 7 — Verification status

### 8.1 Tests

`tests/` holds 5 files, 14 test functions. **The suite cannot run in this checkout** — `.venv` has neither `pytest` nor `pip`; the `dev` extras (`pyproject.toml:33-40`) were never installed. `VERIFIED`

| File | Tests | Skipped | Notes |
|---|---|---|---|
| `test_retrieval.py` | 5 | 2 (`:72`, `:80`) | The 3 non-skipped tests use fixtures built on a **schema the code no longer has**: `train_id`/`stations`/`train_type` (`:23-30`, `:113-117`, `:124-128`) vs. the current `route_id`/`stops`/`vehicle_type` (`models.py:20-27`). They would raise `ValidationError`, not pass. They also exercise `retrieve_routes` — dead code. |
| `test_graph.py` | 7 | 3 (`:52`, `:71`, `:79`) | The 4 live tests make **real Groq and Maps calls** — no mocking. `test_replan_cap_not_exceeded` (the one test for the loop-bounding property) is a stub. |
| `test_integration.py` | 8 | 7 (`:25,29,33,46,55,74`) | Only `test_health_endpoint` (`:67`) is real. Every end-to-end test is a stub with a TODO referencing "Hour 4/7/9 checkpoints" — hackathon scaffolding that was never filled in. |
| `test_nlu.py`, `test_google_maps.py` | not enumerated above | — | Not separately audited |

**Aggregate: 9 of 14 tests are `pytest.skip` stubs. Of the 5 that would attempt to run, 3 use an obsolete schema and would error, and the remaining 2 require live paid API calls. Effective automated coverage of the data and pipeline is zero.** `VERIFIED`

Every stub carries a `TODO(Member N)` naming a team member and a checkpoint hour — the suite is a work-allocation plan, not a verification artefact.

### 8.2 Has anything been validated against an authoritative external source?

**No. There is no validation artefact anywhere in this repository.** `VERIFIED`

Searched for and did not find: schema validators, data-consistency checks, golden files, fixtures captured from an official source, a scraper with a recorded source URL, or any test asserting a data value against a published timetable.

What exists instead:

- **`data/fares.json:1-18`** — a `_README` that *names* the authorities to check against (NTC stage-based schedule; SLR distance-and-class tariff) and states plainly that this has **not** been done: *"Verify against the current NTC and SLR schedules, then update the rates and set `verified` to true."* An instruction for future validation, not evidence of it.
- **`data/stations.json:2`** — a single `source` URL (`https://trainschedule.lk/`), a third-party aggregator rather than Sri Lanka Railways. No capture date, no verification.
- **`data/ride_distances.json:3`** — an inline claim of `"verified 2026-07"` on **one** of three records, with no method recorded.

Nothing else in `data/` carries any provenance or verification claim. `routes.json`, `bus_timetables.json`, and the 100-document Chroma corpus — the three datasets that most directly drive times shown to users — have **none**.

---

## 9. Documentation drift log

Where documentation and code disagree, the code is recorded as truth.

| # | Claim | Location | Reality | Confidence |
|---|---|---|---|---|
| 1 | *"Disruptions … are `active: false` at startup (except D001, which ships active)"* | README:242-243 | **All 5 are `active: false`** (`disruptions.json:8,17,26,35,44`) | `VERIFIED` |
| 2 | Pre-loaded scenario table: D002 = "Fort Railway Station → Kandy, Full cancellation" | README:254-257 | D002's `affected_segment` is **Fort → Galle Railway Station** (`disruptions.json:14`). The table also omits D003–D005 | `VERIFIED` |
| 3 | *"hard cap … enforced at two independent levels (graph routing function + replanner node)"* | README:347 | Enforced in **one** place, `builder.py:79`. `replanner_node` (`:23-76`) contains no cap check | `VERIFIED` |
| 4 | *"The hard cap on iterations is enforced BOTH here (state guard) and in the conditional routing logic … defence in depth"* | `replanner.py:7-8` | Same — no state guard exists. `settings.max_replan_attempts` appears only in a log string (`:44`) | `VERIFIED` |
| 5 | *"all prompts live in `config/prompts.yaml`, not hardcoded in nodes"* | README:349 | ~10 trilingual templates in `intake.py:84-140`; `_CLARIFY` in `nlu/responder.py:87-91`; all ride-hailing/last-mile text in `responder.py:124-185`; error strings in `planner.py:54-56` and `routes.py:156,231` | `VERIFIED` |
| 6 | *"Both functions are fault-tolerant: they log and raise typed exceptions rather than returning None or empty lists silently"* | `retrieval.py:9-10` | `retrieve_bus_timetable` **never raises** and returns `[]` by design (`:87-89`) — the module docstring contradicts the function docstring 80 lines below it | `VERIFIED` |
| 7 | `graph.max_replan_attempts: 2  # hard cap — graph will not loop beyond this` | `config/settings.yaml:13` | Never read. The cap comes from `Settings.max_replan_attempts` (`config.py:48`) / the `MAX_REPLAN_ATTEMPTS` env var | `VERIFIED` |
| 8 | `embedding_model: str = "models/text-embedding-004"` | `config.py:41` | Never read. Embeddings are local ONNX MiniLM-L6-v2 (`embedder.py:19,31`). README:111-112 describes the actual behaviour correctly — the code constant is the stale one | `VERIFIED` |
| 9 | `config/agents.yaml` — *"Loaded by src/commute_agent/core/config.py at startup"* | `agents.yaml:2` | `Settings.agents_config` (`config.py:90-91`) is read by nothing. The file is inert | `VERIFIED` |
| 10 | `clarify_query` block in prompts.yaml | `prompts.yaml:89-92` | Never read. `nlu/responder.py:87-91` hardcodes its own copy of the same three strings | `VERIFIED` |
| 11 | *"MP3 bytes of the English response — played by `st.audio()` in the UI"* | `state.py:68` | Never read by anything. Excluded from the wire (`schemas.py:22-23`); Streamlit generates its own audio (`ui/app.py:87-94`) | `VERIFIED` |
| 12 | `data/processed/bus/**/*.md` listed as a shipped data file | README:339 | Directory does not exist and is gitignored (`.gitignore:26`). `uv run ingest-bus` would ingest 0 documents | `VERIFIED` |
| 13 | *"`data/routes.json` — Train schedule reference data (used for ChromaDB ingestion)"* | README:336 | Accurate as far as it goes, but omits that the resulting collection is queried by no live code path — the file is inert at runtime | `VERIFIED` |
| 14 | *"scrapes trainschedule.lk on demand"* / *"Real train schedules"* | README:13 | It scrapes a **hardcoded route** (`abucnia`, Colombo Fort → Rambukkana) and returns it for every query | `VERIFIED` |
| 15 | *"Journey details (from Google Maps live data)"* | `prompts.yaml:101` | For train routes the values have been replaced by scraped data by the time this prompt is filled (`train_rag.py:225-239`). The LLM is told the wrong provenance | `VERIFIED` |
| 16 | *"Disruption check against live feed"* | README:55 | The feed is `data/disruptions.json`, a local file of 5 hand-written fixtures. README:337 elsewhere says "Simulated" — the architecture diagram does not | `VERIFIED` |
| 17 | *"PDF timetable extraction — attempts pdfplumber parsing"* | `ingest_timetables.py:2` | No pdfplumber import, no extraction. `extract_from_pdfs` logs *"not yet implemented"* (`:38-41`); `_parse_table` returns `[]` (`:44-46`) | `VERIFIED` |
| 18 | *"TTL caching — route and disruption results cached (5 min / 60 sec)"* | README:350 | Only `check_disruption` is cached (`disruption_tool.py:41-42`), and it makes no network call. **No route, Maps, Groq, or scrape result is cached.** `_DISRUPTION_TTL_OVERRIDE` (`disruption_tool.py:25`) is defined and unused — `cache.set` applies the global 300s TTL | `VERIFIED` |
| 19 | *"TTL configured from settings.yaml (default 5 min)"* | `cache.py:7` | Comes from `Settings.cache_ttl_seconds` (`config.py:44`) / env, not `settings.yaml` | `VERIFIED` |
| 20 | *"Avoid redundant Chroma / Gemini calls"* | `cache.py:5` | Gemini is not used anywhere; the LLM is Groq. Residue from an earlier design, as is `gemini_temperature` (`config.py:28`), which is still read to set Groq's temperature (`parser.py:117`, `nlu/responder.py:35`) | `VERIFIED` |
| 21 | Architecture diagram shows `Bus RAG → Train RAG` as pure enrichment | README:34-40 | `Train RAG` does not enrich — it **deletes and replaces** the Maps train routes (`train_rag.py:225-239`) | `VERIFIED` |
| 22 | *"`pytest tests/ -v`"* as a working step | README:224 | pytest is not installed in `.venv`; 9 of 14 tests are skip-stubs; 3 more use an obsolete `RouteOption` schema | `VERIFIED` |

---

## 10. Open questions

Things I could not determine, and what would resolve each. No solutions proposed.

1. **Where did `bus_timetables.json` come from?** No source, no scraper, no commit message. The stop names read like manual transcription, and ≥9 records contradict their own route names. *To determine:* ask the author; or diff every record against the NTC route list and SLTB published schedules.

2. **Where did the 100 bus-corpus documents come from?** The source markdown is gitignored and absent; only the Chroma embeddings survive. Route names embed dates (`2025.12.24`, `New Imp 2025.10.10`, `2022-10-21`) that look like NTC/SLTB revision markers. *To determine:* recover `data/processed/bus/` from whoever generated it, and the PDFs behind it. Without them the corpus cannot be re-ingested, corrected, or dated — `ingest-bus` currently ingests 0.

3. **Where did `routes.json` come from?** Six routes with plausible SLR train numbers and no provenance. *To determine:* check the 6 IDs and their times against the SLR published timetable. Cheap — 6 records.

4. **Was `trainschedule.lk` ever returning per-route pages, or was the URL always wrong?** The `abucnia` path segment looks like a site-internal identifier that was correct for one journey at capture time. Whether this is site drift or an original transcription error changes what happened here. *To determine:* the Wayback Machine for `trainschedule.lk/schedule/*`, or the site's current URL scheme.

5. **How accurate is `bus_timetables.json` where it is internally consistent?** This decides whether the bus override at `bus_rag.py:210-211` is a net gain or a net loss — and it is the only place a "better than Maps" claim could survive. *To determine:* verify a sample of the 19 distinct route numbers against published schedules.

6. **Is `stations.json` complete and current for the SLR network?** It declares 390 and contains 390, but no capture date. *To determine:* compare against the SLR station list.

7. **Was `docs/` intended to exist?** This audit created it; the repository had no docs directory.

8. **Do `tests/test_nlu.py` and `tests/test_google_maps.py` follow the same stub pattern?** I enumerated `test_retrieval.py`, `test_graph.py`, and `test_integration.py` in detail; the other two were not read line by line. Given 9 of 14 stubs across the three audited files, the pattern is likely but unconfirmed. *To determine:* read both, then install the `dev` extras and run the suite.

9. **What is the intended deployment topology?** `sessions.py:12-14` requires single-worker uvicorn. Nothing in the README, `pyproject.toml`, or any config enforces or documents this. *To determine:* ask; or inspect whatever deploy configuration exists outside this repository.

10. **Was `data/raw/` (PDF sources for `ingest_timetables.py`) ever populated?** The extraction path is a stub and the directory is gitignored (`.gitignore:27`). *To determine:* ask whether PDFs were ever collected.

11. **Is `_extract_route_number`'s loose fallback regex (`bus_rag.py:56`) producing false route numbers in practice?** In the observed run it yielded `38-1` and `100` from real Maps descriptions — but the pattern `\b([A-Z]{2,}\d*…|\d{2,3}…)\b` would also match uppercase tokens in stop names. *To determine:* log extraction results across a corpus of real Maps descriptions.

---

*End of audit. No source file was modified. `docs/SYSTEM_AUDIT.md` is the only file created.*
