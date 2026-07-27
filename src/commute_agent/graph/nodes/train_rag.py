"""
Train RAG node — enriches train routes with real schedule data from trainschedule.lk.

For each train route in candidate_routes:
1. Uses the Groq LLM to map Google Maps station names to official trainschedule.lk names
   (reference list loaded from data/stations.json).
2. Scrapes the timetable page for that origin-destination pair.
3. Updates departure_times and arrival_times in the route dict.

Falls back gracefully on network errors or scrape failures.
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
    Enrich train routes in candidate_routes with real trainschedule.lk data.

    Reads:  candidate_routes, origin, destination, requested_time
    Writes: candidate_routes (updated train routes with real departure/arrival times)
    """
    trace = list(state.get("trace", []))
    trace.append(NODE_NAME)

    candidate_routes: list[dict] = state.get("candidate_routes", [])
    requested_time = state.get("requested_time")

    train_routes = [r for r in candidate_routes if r.get("transit_mode") == TransitMode.TRAIN.value]
    if not train_routes:
        logger.info("[%s] No train routes to enrich.", NODE_NAME)
        return {**state, "trace": trace}

    # Map station names once for the whole batch
    origin_gmaps = state.get("origin", "")
    dest_gmaps = state.get("destination", "")

    official_origin = _map_station_name(origin_gmaps) if origin_gmaps else None
    official_dest = _map_station_name(dest_gmaps) if dest_gmaps else None

    if not official_origin:
        official_origin = origin_gmaps
    if not official_dest:
        official_dest = dest_gmaps

    # Small polite delay before scraping
    time.sleep(0.5)
    schedules = _scrape_schedule(official_origin, official_dest)

    if not schedules:
        logger.warning(
            "[%s] No schedule data retrieved for %r -> %r; keeping Google Maps times.",
            NODE_NAME, official_origin, official_dest,
        )
        return {**state, "trace": trace}

    next_trains = _find_next_trains(schedules, requested_time, max_results=5)

    # Rebuild candidate_routes: replace each train route with one enriched entry per scraped train
    enriched: list[dict] = []
    bus_routes = [r for r in candidate_routes if r.get("transit_mode") != TransitMode.TRAIN.value]
    enriched.extend(bus_routes)

    base_train_route = train_routes[0]  # use first train route as template
    for i, sched in enumerate(next_trains):
        updated = dict(base_train_route)
        updated["route_id"] = f"{base_train_route.get('route_id', 'TRAIN')}-sched{i}"
        updated["departure_times"] = [sched["departure"]]
        updated["arrival_times"] = [sched["arrival"]]
        updated["_train_name"] = sched.get("train_name", "")
        desc = base_train_route.get("description", "")
        if sched.get("train_name") and sched["train_name"] not in desc:
            updated["description"] = f"{sched['train_name']} — {desc}" if desc else sched["train_name"]
        enriched.append(updated)

    # Preserve candidate_route as updated best
    candidate_route = state.get("candidate_route")
    if enriched:
        # Prefer first available train route among enriched
        train_enriched = [r for r in enriched if r.get("transit_mode") == TransitMode.TRAIN.value]
        if train_enriched:
            candidate_route = train_enriched[0]

    logger.info(
        "[%s] Replaced %d Google Maps train route(s) with %d scraped schedule(s).",
        NODE_NAME, len(train_routes), len(next_trains),
    )

    return {
        **state,
        "trace": trace,
        "candidate_routes": enriched,
        "candidate_route": candidate_route,
    }
