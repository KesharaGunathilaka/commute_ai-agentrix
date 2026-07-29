"""
Core business entities — the shared language between all modules.

These are pure data classes with no I/O or LLM calls.
All fields use snake_case to match the AgentState contract.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from commute_agent.domain.enums import DisruptionLevel, DisruptionType, Language, TransitMode


class RouteOption(BaseModel):
    """A single schedulable transit journey (train or bus)."""

    route_id: str
    line: str
    stops: list[str]
    departure_times: list[str] = Field(description="HH:MM per stop, index-aligned with stops")
    arrival_times: list[str] = Field(description="HH:MM per stop, index-aligned with stops")
    days_of_operation: list[str]
    transit_mode: TransitMode = TransitMode.TRAIN
    vehicle_type: str = ""
    description: str = ""
    last_mile_distance_m: Optional[int] = None
    """Walking distance (metres) from the final transit alighting stop to the
    journey's actual end, when Google Maps reports a trailing walking leg.
    None when transit already ends at the destination, or for routes not
    sourced from Google Maps (which don't populate this field)."""

    legs: list[dict] = Field(default_factory=list)
    """Structured per-TRANSIT-step data (mode, line, board/alight stop, times,
    distance_m), in journey order. Populated by google_maps_tool so downstream
    nodes can reason about individual legs (e.g. "is the final leg a short
    local hop worth an Uber alternative?") without re-parsing `description`.
    Empty for routes not sourced from Google Maps."""

    polyline: Optional[str] = None
    """Google's encoded overview polyline for the whole journey — the shape a
    map draws to trace the route. Encoded rather than decoded because the
    frontend's map library decodes it natively, and the point list is an order
    of magnitude larger over the wire. None for non-Google-Maps routes."""

    stop_coords: list[dict] = Field(default_factory=list)
    """{"name", "lat", "lng"} per stop, index-aligned with `stops` — the marker
    positions a map places along the route. Empty for non-Google-Maps routes."""

    bounds: Optional[dict] = None
    """Google's viewport for the journey: {"north", "south", "east", "west"}.
    Lets a map frame the whole route without recomputing extents from the
    polyline. None for non-Google-Maps routes."""

    fare_estimate: Optional[dict] = None
    """Estimated fare for this route, attached by the fare node — amount,
    displayed range, per-class breakdown, and the distance it was derived
    from. Always an ESTIMATE (see tools/fare_tool.py); None when no defensible
    estimate exists, which callers must treat as "unknown", never as free."""

    # ── Provenance (see domain/provenance.py) ────────────────────────────────
    # All three default, so every existing construction site keeps working and
    # an unstamped route reads as "source unknown, unverified" — the safe way
    # round. Legs carry the same three keys individually, because a journey
    # can mix a Maps-sourced leg with one whose times came from local data.

    source: Optional[str] = None
    """Which dataset or API these times came from — "google_maps",
    "local_timetable", "simulated", and so on. None means unrecorded."""

    verified: bool = False
    """Whether this source has been checked against a published authority *by
    this project*. False for everything shipped today; see the audit's Part 7."""

    captured_date: Optional[str] = None
    """ISO date the local data behind these times was captured. None for live
    sources, and for local data that recorded no capture date."""

    @property
    def origin(self) -> str:
        return self.stops[0]

    @property
    def destination(self) -> str:
        return self.stops[-1]

    @property
    def departure_time(self) -> str:
        return self.departure_times[0]

    @property
    def arrival_time(self) -> str:
        return self.arrival_times[-1]


class DisruptionRecord(BaseModel):
    """Raw entry from disruptions.json — the live disruption feed contract."""

    disruption_id: str
    train_id: str
    affected_segment: str
    type: DisruptionType
    delay_minutes: Optional[int] = None
    active: bool = False
    message: str


class DisruptionStatus(BaseModel):
    """Output of check_disruption() — consumed by the Monitor node."""

    level: DisruptionLevel
    disruption: Optional[DisruptionRecord] = None

    @property
    def is_disrupted(self) -> bool:
        return self.level != DisruptionLevel.CLEAR
