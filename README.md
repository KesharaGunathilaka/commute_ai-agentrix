# CommuteAI — Disruption-Aware Commute Agent for Sri Lanka

**AGENTRIX 2026 · Team 23 AlphaZero**

An AI-powered commute assistant that helps Sri Lanka commuters find the best bus or train route, detects live disruptions, automatically replans when needed, and responds in Sinhala, Tamil, or English — with a voice read-aloud option.

---

## Features

- **Multilingual** — understands and responds in Sinhala, Tamil, and English
- **Live route discovery** — Google Maps Directions API (transit mode, bus + train alternatives)
- **Real train schedules** — scrapes [trainschedule.lk](https://trainschedule.lk) on demand, with LLM-assisted station name mapping
- **Bus timetable lookup** — next scheduled departure from a curated Sri Lanka bus timetable dataset, with a semantic-search (RAG) fallback over ~100 archived route timetables when the curated dataset has no match
- **Multi-criteria route ranking** — scores routes by deadline compliance, departure time, mode preference, and number of transfers
- **Fare estimates & cost ranking** — every route is priced by distance and class (train 1st/2nd/3rd, bus normal/semi-luxury/AC); ask for "the cheapest way to Kandy" and the ranker optimises for cost, or use the Fastest / Cheapest / Fewest-changes toggle in the UI ([see caveat](#fare-estimates))
- **Disruption detection & auto-replanning** — detects delays and cancellations, retries up to 2 alternative routes
- **Ride-hailing fallback** — bike / tuk-tuk / car quotes when no transit route fits, or for the last-mile leg when transit drops the commuter more than 1 km from their actual destination
- **Text-to-speech** — per-message Read Aloud button (Google TTS) in the chat UI
- **Conversational intake** — collects origin, destination, departure time, and arrival deadline over multiple turns

---

## Architecture

```
User Query (Sinhala / Tamil / English)
        │
        ▼
  ┌─────────────┐
  │   Planner   │  NLU parse (Groq LLM) → route discovery (Google Maps)
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   Bus RAG   │  Enrich bus routes with next scheduled departure
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │  Train RAG  │  Map station names → scrape trainschedule.lk
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │    Fares    │  Estimate fare per route by distance & class
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   Ranker    │  Score & rank top-5 (by speed, cost, or transfers)
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │    Uber     │  Ride-hailing fallback quotes (if needed)
  └──────┬──────┘
         │
  ┌──────▼──────┐
  │   Monitor   │  Disruption check against live feed
  └──────┬──────┘
         │
    ┌────┴──────────────────┐
    │ CLEAR                 │ DISRUPTED
    ▼                       ▼
┌──────────┐         ┌────────────┐
│ Responder│         │ Replanner  │──► Monitor (loop, max 2)
└──────────┘         └────────────┘
                           │ (cap reached)
                           ▼
                       Responder
```

The graph is implemented with **LangGraph** `StateGraph`. All node I/O passes through a single `AgentState` TypedDict — no global state, no side channels.

### Key components

| Layer | Location |
|-------|----------|
| LangGraph orchestration | `src/commute_agent/graph/` |
| NLU (Groq llama-3.3-70b) | `src/commute_agent/nlu/` |
| RAG / ChromaDB retrieval | `src/commute_agent/rag/` |
| Conversational intake (UI-agnostic) | `src/commute_agent/conversation/` |
| FastAPI backend | `src/commute_agent/api/` |
| **Next.js frontend (primary UI)** | `frontend/` |
| Streamlit UI (legacy fallback) | `src/commute_agent/ui/` |

### Frontend

The primary interface is a **Next.js 16** app (App Router, TypeScript, Tailwind
v4) in `frontend/`, styled as a dark "transit console" — departure-board
typography, cyan for live state, amber for scheduled times, rose for
disruption.

Beyond the Streamlit UI's feature set it adds:

- **Live agent trace** — the LangGraph pipeline animates node by node as it
  executes, streamed over SSE, including the replanning loop
- **Interactive route map** — Google Maps with the route polyline, stop
  markers, and the disrupted route overlaid for comparison
- **Fare comparison** — estimated fares per route with a class breakdown, and
  a Fastest / Cheapest / Fewest-changes toggle that re-sorts instantly in the
  browser (no graph round trip) and lets you pin any option to the map
- **Voice input** — Web Speech API dictation in English, Sinhala, or Tamil
- **Context-aware composer** — placeholder and quick-reply chips adapt to
  whichever field the agent is asking for

The Streamlit UI still works and is unchanged; both drive the same graph.

Multi-turn intake (origin → destination → departure → deadline) lives in
`src/commute_agent/conversation/` so the two frontends share one state
machine rather than each keeping their own copy.

### RAG layer

Two Chroma collections, both embedded locally via ChromaDB's bundled ONNX
MiniLM-L6-v2 model — **no API key required**, no external embedding calls:

- **`sri_lanka_railways_routes`** — semantic search over `data/routes.json`
  (train schedules). Falls back to a keyword filter if the collection hasn't
  been ingested yet.
- **`sri_lanka_bus_timetables_docs`** — semantic search over the ~100
  already-collected bus-timetable documents in `data/processed/bus/**/*.md`
  (PDF-extracted; the narrative Sinhala text in these files has a font-encoding
  corruption from the original extraction, so the embedding text is built from
  the clean YAML frontmatter instead, and schedule samples are pulled from the
  markdown tables positionally rather than by header name). `bus_rag_node`
  queries this collection as a fallback whenever a bus route isn't found in
  the curated `data/bus_timetables.json` — it only ever adds a matched route
  name / archived sample schedule as supplementary info, never overwrites the
  live Google Maps departure/arrival times.

Ingest both with:

```bash
uv run ingest       # data/routes.json -> Chroma
uv run ingest-bus   # data/processed/bus/**/*.md -> Chroma
```

Without ingestion, the agent still works — the graph's live Google Maps /
trainschedule.lk / curated-JSON path never depended on Chroma; RAG is
additive enrichment, not a hard dependency.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager — `pip install uv`
- **Groq API key** (free at [console.groq.com](https://console.groq.com)) — required for NLU and response generation
- Google API key (optional — enables Google Maps route discovery and TTS; **not** needed for RAG/embeddings, which run locally)

### 1. Clone and install

```bash
git clone https://github.com/Agentrix-ComES/AGENTRIX26-TEAM23-AlphaZero.git
cd AGENTRIX26-TEAM23-AlphaZero
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Set your keys in `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
GOOGLE_API_KEY=your_google_api_key_here   # optional
```

All other settings have working defaults.

### 3. (Optional) Ingest data into ChromaDB

```bash
uv run ingest       # data/routes.json -> Chroma
uv run ingest-bus   # data/processed/bus/**/*.md -> Chroma
```

Embeds locally (no API key needed) and persists the vector store to `data/chroma_db/`. Without this step the agent still works fully — route retrieval falls back to a keyword filter, and the bus RAG fallback simply has nothing extra to offer beyond the curated `data/bus_timetables.json`.

### 4. Run the agent

**Next.js UI (recommended)** — needs both servers running.

Terminal 1, the API:

```bash
uv run uvicorn commute_agent.api.main:app --reload --port 8000
```

Terminal 2, the frontend:

```bash
cd frontend
npm install     # first time only
npm run dev
```

Open `http://localhost:3000`. The header shows **Agent online** once it reaches
the backend; if it says offline, terminal 1 isn't up. Try an example query, or
trigger a disruption first (see [Demo: Disruption Activation](#demo-disruption-activation))
to watch the agent replan live.

API docs at `http://localhost:8000/docs`.

**Streamlit UI (fallback)**

```bash
uv run streamlit run src/commute_agent/ui/app.py
```

Opens at `http://localhost:8501`. Self-contained — no separate API process.

**CLI smoke test**

```bash
uv run run-agent
```

### 5. Run tests

```bash
pytest tests/ -v
```

---

## Example Queries

| Language | Query |
|----------|-------|
| English  | `I need to get from Colombo to Kandy by 10am, leaving around 7:30` |
| English  | `What buses go from Nugegoda to Galle?` |
| Sinhala  | `කොළඹ සිට මහනුවර දක්වා දුම්රිය ගමන් වේලාවන් මොනවාද?` |
| Tamil    | `கொழும்பிலிருந்து கண்டி செல்ல சிறந்த பேருந்து எது?` |

---

## Demo: Disruption Activation

Disruptions in `data/disruptions.json` are `active: false` at startup (except D001, which
ships active). Activate them for demos:

1. **API** — `POST /api/v1/disruptions/{id}/activate` (flips `active: true` for that
   disruption and invalidates the cache)
2. **Manually** — set `"active": true` in `data/disruptions.json`

Call `POST /api/v1/disruptions/clear` to reset all disruptions to inactive (also
invalidates the cache).

Pre-loaded scenarios:

| ID | Segment | Type |
|----|---------|------|
| D001 | Fort Railway Station → Kandy | 45-minute delay |
| D002 | Fort Railway Station → Kandy | Full cancellation |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | Groq API key for NLU and response generation |
| `GOOGLE_API_KEY` | No | — | Google Cloud key (Maps route discovery) |
| `GOOGLE_MAPS_API_KEY` | No | — | Dedicated Maps key (overrides `GOOGLE_API_KEY` for Maps) |
| `CHROMA_PERSIST_DIR` | No | `./data/chroma_db` | ChromaDB vector store location (local embeddings, no key needed) |
| `CACHE_TTL_SECONDS` | No | `300` | Route cache TTL in seconds |
| `MAX_REPLAN_ATTEMPTS` | No | `2` | Hard cap on disruption replanning loops |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |
| `API_HOST` / `API_PORT` | No | `0.0.0.0` / `8000` | FastAPI bind address |
| `CORS_ORIGINS` | No | `http://localhost:3000,…` | Origins allowed to call the API |
| `GOOGLE_MAPS_BROWSER_KEY` | No | — | Maps JS key for the frontend route map (see below) |

### Fare estimates

> **⚠️ The shipped fare rates are unverified placeholders.** They produce
> realistic magnitudes but are **not** transcribed from a published tariff.
> Replace them before any public use or demo where accuracy is claimed.

Sri Lanka publishes no machine-readable fare feed — bus fares come from the
NTC's stage-based schedule, rail fares from SLR's distance-and-class tariff.
`data/fares.json` models both as *a minimum fare covering an initial distance
band, plus a per-km rate, times a class multiplier*.

To correct them, edit `data/fares.json` only — **no code changes needed**:

```jsonc
"train": {
  "minimum_fare": 20,        // covers the first `minimum_covers_km`
  "minimum_covers_km": 5,
  "per_km": 1.3,
  "classes": [ { "id": "third", "label": "3rd class", "multiplier": 1.0 }, ... ]
}
```

Then set `"verified": true`. While it is `false` the UI shows a **±25% margin**
on every figure and labels them "rates unverified". Setting it to `true` drops
the margin, so don't flip it until the numbers are real.

Distance comes from the per-leg distances Google Maps returns. A route with no
leg distances (one sourced from the curated timetable archive) gets **no
estimate at all** rather than a guessed one, and sorts *last* under "cheapest"
— unknown cost must never masquerade as zero cost.

### The map key

`GOOGLE_MAPS_BROWSER_KEY` is **separate from `GOOGLE_MAPS_API_KEY` on purpose**.
The server key is used for Directions API calls and must never reach a browser;
a browser key is publicly visible by design and should be restricted by HTTP
referrer in the Google Cloud console, with only the *Maps JavaScript API*
enabled.

Leave it blank and the frontend degrades gracefully — the map is replaced by a
stop-by-stop route list. Everything else works unchanged.

### API endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/chat` | One conversational turn (non-streaming) |
| `GET /api/v1/chat/stream` | Same turn, streamed node by node over SSE |
| `POST /api/v1/tts` | gTTS speech synthesis, returns MP3 |
| `POST /api/v1/session/reset` | Clear a conversation, keep the session id |
| `GET /api/v1/config` | Frontend capability discovery (maps key, limits) |
| `POST /api/v1/query` | Stateless one-shot query, no session |
| `GET /api/v1/disruptions` | Current disruption feed |

---

## Data Files

| File | Description |
|------|-------------|
| `data/routes.json` | Train schedule reference data (used for ChromaDB ingestion) |
| `data/disruptions.json` | Simulated live disruption feed — set `active: true` to trigger |
| `data/bus_timetables.json` | Curated Sri Lanka bus timetables with departure schedules (20 routes) |
| `data/processed/bus/**/*.md` | Archived bus timetables (~100 routes, PDF-extracted) — ingested into Chroma via `uv run ingest-bus` as a RAG fallback for routes not in the curated dataset above |
| `data/stations.json` | 390 official Sri Lanka Railways station names from trainschedule.lk |
| `data/fares.json` | Fare rate model (distance bands × class multipliers) — **unverified placeholders**, see [Fare estimates](#fare-estimates) |

---

## Design Principles

- **Bounded replanning** — hard cap of 2 replan attempts enforced at two independent levels (graph routing function + replanner node) so the graph always terminates
- **Graceful degradation** — each node falls back silently on failures: scraping errors retain Google Maps times, missing timetable entries pass through unchanged, LLM parse failures trigger a clarification prompt
- **Loose coupling** — all prompts live in `config/prompts.yaml`, not hardcoded in nodes
- **TTL caching** — route and disruption results cached (5 min / 60 sec) to avoid redundant API calls
- **Multilingual at every layer** — NLU detects language, all responses return both native and English text, TTS always reads the English version
