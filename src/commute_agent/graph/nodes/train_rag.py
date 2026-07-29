"""
Train enrichment node.

**The trainschedule.lk scrape is disabled and must stay disabled.** `_SCRAPE_BASE`
below pins a site-internal path segment (`abucnia`) that resolves to one fixed
journey — Colombo Fort → Rambukkana — and returns that same page, at HTTP 200
with a valid table, for *every* origin/destination slug. Nothing in the response
signals the mismatch, so the parse succeeded and the wrong times were trusted.

Until 2026-07-29 this node then *deleted* every Google Maps train route and
rebuilt `candidate_routes` from those rows, which meant a Colombo Fort → Kandy
query answered with Rambukkana times labelled Kandy. Maps' correct times were
not retained anywhere in state, so the error was unrecoverable downstream. That
made the system measurably less accurate than Google Maps alone for every train
query in the country.

The node now keeps the Google Maps times and records where they came from. It
still runs, and still reports itself in the trace, so the pipeline shape and the
agent-trace panel are unchanged — it simply no longer destroys the one accurate
source of train times the system has.

Re-enabling any scrape here requires a source that is verifiably route-specific
(assert the response actually names the requested destination before trusting a
single row of it), and the replacement must record provenance rather than
silently overwriting Maps.

The scrape helpers below are retained, unreferenced, so the failure mode stays
documented next to the code that caused it.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from langchain_groq import ChatGroq

from commute_agent.core.config import get_settings
from commute_agent.core.exceptions import NLUParseError
from commute_agent.core.logging import get_logger
from commute_agent.domain.enums import TransitMode
from commute_agent.domain.provenance import SOURCE_GOOGLE_MAPS, stamp_route_provenance
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)

NODE_NAME = "train_rag"

_STATIONS_PATH = Path(__file__).parents[4] / "data" / "stations.json"
_stations_list: Optional[list[str]] = None

_SCRAPE_BASE = "https://trainschedule.lk/schedule/abucnia/{src}-to-{dst}-train-timetable"
_REQUEST_TIMEOUT = 10
_HEADERS = {"User-Agent": "Mozilla/5.0 (CommuteAI; educational use)"}


def _load_stations() -> list[str]:
    global _stations_list
    if _stations_list is None:
        with open(_STATIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _stations_list = data.get("stations", [])
    return _stations_list


def _slugify(name: str) -> str:
    """Convert a station name to the URL slug format used by trainschedule.lk."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _map_station_name(gmaps_name: str) -> Optional[str]:
    """Use Groq LLM to map a Google Maps station name to an official trainschedule.lk name."""
    settings = get_settings()
    stations = _load_stations()

    prompt_template: str = settings.prompts_config.get("map_station_name", "")
    if not prompt_template:
        logger.warning("[%s] map_station_name prompt not found in config.", NODE_NAME)
        return None

    prompt = prompt_template.format(
        gmaps_name=gmaps_name,
        station_list=json.dumps(stations, ensure_ascii=False),
    )

    try:
        llm = ChatGroq(
            model=settings.groq_model,
            temperature=0.0,
            groq_api_key=settings.groq_api_key,
        )
        response = llm.invoke(prompt)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(raw)
        matched = parsed.get("matched_station")
        if matched and matched != "null":
            logger.info("[%s] Mapped %r -> %r", NODE_NAME, gmaps_name, matched)
            return matched
        logger.debug("[%s] No match for station %r", NODE_NAME, gmaps_name)
        return None
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("[%s] Station mapping failed for %r: %s", NODE_NAME, gmaps_name, exc)
        return None


def _scrape_schedule(src_name: str, dst_name: str) -> list[dict]:
    """
    Scrape trainschedule.lk for trains between src_name and dst_name.

    Returns a list of dicts: [{departure, arrival, train_name}, ...].
    Returns empty list on any failure.
    """
    src_slug = _slugify(src_name)
    dst_slug = _slugify(dst_name)
    url = _SCRAPE_BASE.format(src=src_slug, dst=dst_slug)

    logger.info("[%s] Scraping: %s", NODE_NAME, url)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[%s] HTTP error scraping %s: %s", NODE_NAME, url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # trainschedule.lk uses a <table> with columns: Train | Departure | Arrival | ...
    table = soup.find("table")
    if not table:
        logger.warning("[%s] No table found on page: %s", NODE_NAME, url)
        return []

    rows = table.find_all("tr")
    schedules = []
    for row in rows[1:]:  # skip header
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 3:
            continue
        # Column order varies — detect time-like values (HH:MM)
        times = [c for c in cols if re.match(r"^\d{1,2}:\d{2}", c)]
        train_name = next((c for c in cols if not re.match(r"^\d{1,2}:\d{2}", c) and c), "Train")
        if len(times) >= 2:
            schedules.append({
                "train_name": train_name,
                "departure": times[0],
                "arrival": times[1],
            })
        elif len(times) == 1:
            schedules.append({
                "train_name": train_name,
                "departure": times[0],
                "arrival": "—",
            })

    logger.info("[%s] Scraped %d schedule entries for %s -> %s", NODE_NAME, len(schedules), src_name, dst_name)
    return schedules


def _find_next_trains(
    schedules: list[dict],
    requested_time: Optional[str],
    max_results: int = 5,
) -> list[dict]:
    """Return up to max_results trains departing at or after requested_time."""
    if not schedules or not requested_time:
        return schedules[:max_results]

    try:
        from datetime import datetime
        base = datetime.strptime(requested_time, "%H:%M")
    except ValueError:
        return schedules[:max_results]

    after = []
    before = []
    for s in schedules:
        try:
            dep = datetime.strptime(s["departure"], "%H:%M")
            if dep >= base:
                after.append(s)
            else:
                before.append(s)
        except ValueError:
            after.append(s)

    result = after[:max_results]
    if len(result) < max_results:
        result += before[: max_results - len(result)]
    return result


def train_rag_node(state: AgentState) -> AgentState:
    """
    Retain the Google Maps train times and record their provenance.

    No network call, no LLM call, no mutation of any time. See the module
    docstring for why the scrape this node used to perform was removed rather
    than repaired.

    Reads:  candidate_routes
    Writes: candidate_routes (provenance stamped on train routes only)
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])

    train_routes = [r for r in candidate_routes if r.get("transit_mode") == TransitMode.TRAIN.value]
    if not train_routes:
        logger.info("[%s] No train routes present.", NODE_NAME)
        return {**state, "trace": trace}

    logger.info(
        "[%s] Keeping Google Maps times for %d train route(s); local schedule source disabled.",
        NODE_NAME, len(train_routes),
    )

    stamped = [
        stamp_route_provenance(route, SOURCE_GOOGLE_MAPS)
        if route.get("transit_mode") == TransitMode.TRAIN.value
        else route
        for route in candidate_routes
    ]

    candidate_route = state.get("candidate_route")
    if candidate_route is not None:
        best_id = candidate_route.get("route_id")
        candidate_route = next(
            (r for r in stamped if r.get("route_id") == best_id),
            candidate_route,
        )

    return {
        **state,
        "trace": trace,
        "candidate_routes": stamped,
        "candidate_route": candidate_route,
    }
