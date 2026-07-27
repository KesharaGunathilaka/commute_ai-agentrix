"""Shared AgentState — single source of truth for all node I/O."""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────────────────────────
    user_query: str
    """Raw text from the commuter, in any of the three supported languages."""

    # ── NLU output (Planner node) ──────────────────────────────────────────────
    language: str
    """Detected language code: 'si' | 'ta' | 'en'."""

    origin: Optional[str]
    """Parsed departure station (English name), or None if not provided."""

    destination: Optional[str]
    """Parsed arrival station (English name), or None if not provided."""

    requested_time: Optional[str]
    """Requested departure time in HH:MM 24h format, or None."""

    expected_arrival_time: Optional[str]
    """Arrival deadline in HH:MM 24h format, or None if no deadline was given."""

    preferred_mode: Optional[str]
    """User's preferred transit mode: 'train' | 'bus' | None (any)."""

    optimise_for: Optional[str]
    """What the commuter is optimising for — 'fastest' | 'cheapest' |
    'fewest_changes' | None (balanced). Drives the ranker's sort order.
    Deadline compliance always outranks this: a cheap route that misses the
    commuter's deadline is not a useful answer."""

    # ── Route planning (Planner node) ─────────────────────────────────────────
    candidate_routes: list[dict]
    """All transit options returned by Google Maps (train + bus), serialised RouteOption dicts."""

    candidate_route: Optional[dict]
    """Best route selected from candidate_routes before any disruption check."""

    # ── Enrichment and ranking (bus_rag / train_rag / ranker nodes) ───────────
    ranked_routes: list[dict]
    """Top-5 routes after ranking by departure time, deadline fit, and mode preference."""

    uber_options: Optional[list[dict]]
    """Ride-hailing quotes from RideService — populated when no transit fits or for last-mile."""

    uber_last_mile: Optional[list[dict]]
    """Ride-hailing quotes for the final transfer leg of a multi-leg journey."""

    uber_last_mile_distance_m: Optional[int]
    """Distance (metres) the last-mile ride is covering — either a walking
    gap with no transit, or a multi-leg route's short final leg."""

    last_mile_transit_leg: Optional[dict]
    """The local bus/train Google Maps found for a multi-leg route's final
    leg (mode, line, board/alight stop, times, distance_m), presented as an
    alternative alongside uber_last_mile so the commuter can choose. None
    when there's no transit for the last stretch (pure walking-gap case) or
    when there's nothing to offer at all."""

    tts_audio: Optional[bytes]
    """MP3 bytes of the English response — played by st.audio() in the UI."""

    # ── Disruption monitoring (Monitor node) ──────────────────────────────────
    disruption_status: Optional[dict]
    """Output of check_disruption(): {'level': str, 'disruption': dict | None}.
    level is one of: 'clear' | 'delayed' | 'cancelled'."""

    # ── Replanning (Replanner node) ────────────────────────────────────────────
    alternative_route: Optional[dict]
    """Alternative route found by the Replanner; None until replanning is triggered."""

    replan_attempts: int
    """Current replanning iteration count — checked against MAX_REPLAN_ATTEMPTS."""

    original_disruption: Optional[dict]
    """The disruption_status captured the FIRST time Monitor found a disruption
    (before any replanning). Preserved across replan iterations so the Responder
    can still explain what went wrong even after a later Monitor check — on the
    replanned alternative — comes back clear."""

    # ── Final output (Responder node) ─────────────────────────────────────────
    final_response_native: str
    """Journey answer in the commuter's detected language."""

    final_response_en: str
    """English gloss — always present alongside the native response."""

    # ── Observability ─────────────────────────────────────────────────────────
    trace: list[str]
    """Ordered list of node names that fired — used by the UI trace panel and demo video."""

    error: Optional[str]
    """Human-readable error message if the agent encountered a non-fatal issue."""
