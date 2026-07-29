"""
Three named plans from one candidate set: fastest, cheapest, balanced.

`build_plan_variants` is a pure function. Same routes in, same variants out;
no LLM, no network, no clock, no state mutation. It is deliberately not a node
so it can be unit-tested and reasoned about on its own, and so that nothing in
it can reach for a model to break a tie.

**Selection reuses `ranker._score` unchanged.** That function's first two
elements are the hard constraints — arrives after the commuter's deadline, and
departs before the commuter can leave — and they lead the sort key in every
branch. Calling it three times with three `optimise_for` values therefore
cannot produce a variant that satisfies a preference by violating feasibility:
the preference only ever reorders *within* the constraints. Variants are picked
from the feasible set; they do not override it. Rewriting the scoring here
would have silently dropped that guarantee, which is exactly why it isn't
rewritten here.

Deduplication matters more than it looks. On a corridor with one good option
all three strategies converge, and rendering that option three times under
three different headings would suggest the agent found three plans when it
found one. Identical picks collapse into a single card whose label says so
("Fastest & cheapest"). Fewer than three distinct routes yields fewer than
three variants — the list is never padded to look fuller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from commute_agent.domain.provenance import summarise_provenance
from commute_agent.graph.nodes.ranker import (
    OPTIMISE_CHEAPEST,
    OPTIMISE_FASTEST,
    _leg_count,
    _parse_time,
    _score,
)
from commute_agent.tools.fare_tool import plan_total_fare

# Ordered: the label of a collapsed variant reads in this order, so a route
# that wins both speed and cost is always "Fastest & cheapest", never the
# reverse. Balanced is `None` because that is what the ranker calls it.
_STRATEGIES: tuple[tuple[str, Optional[str]], ...] = (
    ("fastest", OPTIMISE_FASTEST),
    ("cheapest", OPTIMISE_CHEAPEST),
    ("balanced", None),
)

_STRATEGY_LABELS = {
    "fastest": "Fastest",
    "cheapest": "Cheapest",
    "balanced": "Balanced",
}

_STRATEGY_BLURBS = {
    "fastest": "Earliest arrival.",
    "cheapest": "Lowest estimated fare.",
    "balanced": "Fewest changes, then earliest arrival.",
}

# Cards to aim for. Fewer is fine when fewer distinct viable routes exist; the
# list is never padded with a duplicate.
_TARGET_VARIANTS = 3

# Labels for a filler — a route that won none of the three strategies but is
# worth a card because a strategy slot would otherwise sit empty. Every one of
# these states something demonstrably true about the route, checked before it
# is applied. A filler is NEVER labelled Fastest, Cheapest or Balanced: it did
# not win those, and a card claiming an advantage it does not have is worse
# than an empty slot.
_FILLER_BY_TRAIN = "By train"
_FILLER_BY_BUS = "By bus"
_FILLER_FEWEST_CHANGES = "Fewest changes"
_FILLER_ALTERNATIVE = "Alternative route"

_FILLER_BLURBS = {
    _FILLER_BY_TRAIN: "The rail option on this corridor.",
    _FILLER_BY_BUS: "The bus option on this corridor.",
    _FILLER_FEWEST_CHANGES: "Fewest transfers of any option.",
    _FILLER_ALTERNATIVE: "A different route worth comparing.",
}


@dataclass(frozen=True)
class PlanConstraints:
    """What the commuter said, as the scorer needs it."""

    requested_time: Optional[str] = None
    expected_arrival_time: Optional[str] = None


@dataclass(frozen=True)
class PlanVariant:
    """One named, independently costed plan."""

    variant_id: str
    label: str
    """Display heading. Names every strategy this route won."""

    strategies: tuple[str, ...]
    blurb: str

    route_id: str
    line: str
    transit_mode: str
    departure_time: str
    arrival_time: str
    total_duration_min: Optional[int]
    """None when either endpoint is unparseable — never a guessed number."""

    total_fare: dict[str, Any]
    """Sum over legs. Carries `complete`, `uncertainty_pct` and `amount`,
    where `amount` is None (not 0) if nothing could be priced."""

    legs: list[dict] = field(default_factory=list)
    provenance_summary: str = "estimated"
    """verified | partially_verified | estimated, across every leg."""

    times_source: Optional[str] = None
    """Where `departure_time` and `arrival_time` above actually came from.

    Distinct from the legs' own sources, and it has to be: `bus_rag` replaces a
    route's headline times with curated timetable values while leaving the leg
    times as Maps recorded them. Reading provenance off the legs alone would
    caption a local-timetable arrival as "Google Maps" — attributing a number
    to a source that did not produce it, which is the mislabelling this whole
    field set exists to prevent."""

    times_overridden: bool = False
    """True when local data replaced this route's Maps-sourced times."""

    missed_deadline: bool = False
    departs_before_requested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "label": self.label,
            "strategies": list(self.strategies),
            "blurb": self.blurb,
            "route_id": self.route_id,
            "line": self.line,
            "transit_mode": self.transit_mode,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "total_duration_min": self.total_duration_min,
            "total_fare": self.total_fare,
            "legs": self.legs,
            "provenance_summary": self.provenance_summary,
            "times_source": self.times_source,
            "times_overridden": self.times_overridden,
            "missed_deadline": self.missed_deadline,
            "departs_before_requested": self.departs_before_requested,
        }


def _duration_minutes(departure: str, arrival: str) -> Optional[int]:
    """Minutes between two clock times, wrapping past midnight.

    None when either side won't parse — a plan card showing "—" is honest; one
    showing a duration derived from a time nobody could read is not.
    """
    dep = _parse_time(departure)
    arr = _parse_time(arrival)
    if dep is None or arr is None:
        return None
    minutes = int((arr - dep).total_seconds() // 60)
    return minutes + 24 * 60 if minutes < 0 else minutes


def _combined_label(strategies: tuple[str, ...]) -> str:
    """"Fastest" / "Fastest & cheapest" / "Fastest, cheapest & balanced"."""
    names = [_STRATEGY_LABELS[s] for s in strategies]
    if len(names) == 1:
        return names[0]
    head = [names[0], *(n.lower() for n in names[1:])]
    return f"{head[0]} & {head[1]}" if len(head) == 2 else f"{', '.join(head[:-1])} & {head[-1]}"


def _scoring_view(route: dict, total_fare: dict) -> dict:
    """`route` with its headline fare swapped for the plan total, for scoring.

    `_score` sorts "cheapest" on `fare_estimate.amount` — the route-level
    figure, which prices a whole journey under one scheme with one minimum
    fare. The variant cards display the per-leg sum instead, which is higher
    for a multi-leg route because each vehicle charges its own minimum.

    Scoring on one number and displaying the other would let the card labelled
    "Cheapest" show a higher total than the "Balanced" card sitting beside it.
    So the same number does both jobs. `_score` is untouched and still owns the
    ordering, including the hard constraints that lead its key; it is simply
    handed the fare the commuter is actually going to be shown.

    A `None` total leaves a non-numeric `amount`, which `_fare_amount` already
    sorts last — an unpriceable plan must never win on cost.

    Returns a shallow copy. `routes` belongs to LangGraph state.
    """
    return {**route, "fare_estimate": {**(route.get("fare_estimate") or {}),
                                       "amount": total_fare.get("amount")}}


def _pick_from(
    views: list[dict],
    indices: list[int],
    strategy: Optional[str],
    constraints: PlanConstraints,
) -> int:
    """Index of the best route under one strategy, among `indices`.

    Ties break on input order, so the function is deterministic for a given
    candidate list rather than dependent on dict ordering or sort stability.
    """
    requested_dt = _parse_time(constraints.requested_time)
    deadline_dt = _parse_time(constraints.expected_arrival_time)
    return min(
        indices,
        key=lambda i: (_score(views[i], requested_dt, deadline_dt, strategy), i),
    )


def _pick(views: list[dict], strategy: Optional[str], constraints: PlanConstraints) -> int:
    """Index of the best route under one strategy, across the whole set."""
    return _pick_from(views, list(range(len(views))), strategy, constraints)


def _is_feasible(view: dict, constraints: PlanConstraints) -> bool:
    """True when a route breaks neither hard constraint.

    Read straight off `_score`'s leading pair, so feasibility here means
    exactly what it means to the ranker — no second definition to drift.
    """
    requested_dt = _parse_time(constraints.requested_time)
    deadline_dt = _parse_time(constraints.expected_arrival_time)
    return _score(view, requested_dt, deadline_dt, None)[:2] == (0, 0)


def _filler_label(
    candidate: dict,
    routes: list[dict],
    chosen_modes: set[str],
) -> str:
    """Name a filler by an advantage it demonstrably has.

    Checked in order of how much the label tells a commuter, and every branch
    is verified against the candidate set before it is used. The last branch is
    unconditionally true, so there is always an honest label available and the
    function never has to reach for a strategy name it did not earn.
    """
    mode = candidate.get("transit_mode")
    if mode and mode not in chosen_modes:
        return _FILLER_BY_TRAIN if mode == "train" else _FILLER_BY_BUS

    legs = _leg_count(candidate)
    if legs < min((_leg_count(r) for r in routes if r is not candidate), default=legs + 1):
        return _FILLER_FEWEST_CHANGES

    return _FILLER_ALTERNATIVE


def _choose_filler(
    routes: list[dict],
    views: list[dict],
    taken: set[int],
    chosen_modes: set[str],
    constraints: PlanConstraints,
    allow_infeasible: bool,
) -> Optional[int]:
    """Index of the best distinct route to occupy a free card slot.

    Two preferences, in order:

    1. A mode not already on screen. Three cards that are all trains tell a
       commuter nothing about whether a bus exists, and the bus may be the
       answer when the train is full or cancelled.
    2. Otherwise the best remaining route under balanced scoring.

    Feasibility is never traded away. `allow_infeasible` is true only when the
    strategy winners themselves all miss a hard constraint — if the commuter's
    deadline is unreachable, showing the alternatives is still useful and every
    card carries `missed_deadline`. When a feasible plan IS on screen, a filler
    that breaks a hard constraint is not offered at all: an empty slot beats a
    card that cannot be used.
    """
    remaining = [i for i in range(len(routes)) if i not in taken]
    if not remaining:
        return None

    feasible = [i for i in remaining if _is_feasible(views[i], constraints)]
    pool = feasible if feasible else (remaining if allow_infeasible else [])
    if not pool:
        return None

    diverse = [i for i in pool if routes[i].get("transit_mode") not in chosen_modes]
    pool = diverse or pool

    return _pick_from(views, pool, None, constraints)


def _build_variant(
    route: dict,
    total_fare: dict,
    strategies: tuple[str, ...],
    constraints: PlanConstraints,
    label: Optional[str] = None,
    blurb: Optional[str] = None,
    variant_id: Optional[str] = None,
) -> PlanVariant:
    departure = (route.get("departure_times") or [""])[0]
    arrival = (route.get("arrival_times") or [""])[-1]
    legs = route.get("legs") or []

    # Provenance is judged per leg where legs exist, because a journey can mix
    # a Maps-sourced leg with one the local timetable replaced. The route's own
    # stamp is included too — the headline times shown on the card are the
    # route's, and a route whose times were overridden must not inherit a
    # verification claim from legs that were left alone.
    provenance_items = [*legs, route] if legs else [route]

    requested_dt = _parse_time(constraints.requested_time)
    deadline_dt = _parse_time(constraints.expected_arrival_time)
    missed, early = _score(route, requested_dt, deadline_dt, None)[:2]

    # A filler wins no strategy, so `strategies` is empty and the caller
    # supplies all three of these. Guarded rather than assumed, so a future
    # caller that forgets one gets a dull label instead of an IndexError.
    return PlanVariant(
        variant_id=variant_id or (f"variant-{strategies[0]}" if strategies else "variant-alt"),
        label=label or (_combined_label(strategies) if strategies else _FILLER_ALTERNATIVE),
        strategies=strategies,
        blurb=blurb or " ".join(_STRATEGY_BLURBS[s] for s in strategies),
        route_id=route.get("route_id", ""),
        line=route.get("line", ""),
        transit_mode=route.get("transit_mode", ""),
        departure_time=departure,
        arrival_time=arrival,
        total_duration_min=_duration_minutes(departure, arrival),
        total_fare=total_fare,
        legs=legs,
        provenance_summary=summarise_provenance(provenance_items),
        times_source=route.get("source"),
        times_overridden=bool(route.get("_provenance_override")),
        missed_deadline=bool(missed),
        departs_before_requested=bool(early),
    )


def build_plan_variants(
    routes: list[dict],
    constraints: PlanConstraints,
) -> list[PlanVariant]:
    """
    Return up to three distinct plans — fastest, cheapest, balanced.

    Fewer than three when the strategies converge on the same route, and none
    at all when `routes` is empty. Never pads, never returns duplicates, and
    never mutates `routes`.
    """
    if not routes:
        return []

    # Priced once, then used for both selection and display so the two can't
    # tell different stories about the same plan.
    totals = [plan_total_fare(route) for route in routes]
    views = [_scoring_view(route, total) for route, total in zip(routes, totals)]

    # Which route each strategy chose. An index, not the dict itself, so that
    # two structurally identical routes are still told apart.
    picks: dict[int, list[str]] = {}
    for name, optimise_for in _STRATEGIES:
        index = _pick(views, optimise_for, constraints)
        picks.setdefault(index, []).append(name)

    # Preserve strategy order (fastest first), not route order: the fastest
    # plan should lead the row of cards whichever candidate it landed on.
    ordered = sorted(picks.items(), key=lambda item: _strategy_rank(item[1][0]))
    variants = [
        _build_variant(routes[index], totals[index], tuple(names), constraints)
        for index, names in ordered
    ]

    # Fill the slots the collapsed labels left behind.
    #
    # Two strategies landing on one route is correct and stays collapsed —
    # "Fastest & cheapest" is a true statement and three identical cards would
    # be worse. But the freed slot is not therefore worthless: there is usually
    # another distinct route the commuter would want to see, and an empty
    # third of the row reads as a bug.
    #
    # Fillers are added, never substituted. A card that genuinely won its
    # strategy is never displaced to make room, because the label it carries is
    # true and the replacement's would be weaker. That also means this cannot
    # regress a working three-card corridor.
    taken = set(picks)
    chosen_modes = {routes[i].get("transit_mode") for i in taken}
    any_feasible = any(_is_feasible(views[i], constraints) for i in taken)

    while len(variants) < _TARGET_VARIANTS:
        index = _choose_filler(
            routes, views, taken, chosen_modes, constraints,
            allow_infeasible=not any_feasible,
        )
        if index is None:
            break  # Fewer than three distinct viable routes exist. Show fewer.
        label = _filler_label(routes[index], routes, chosen_modes)
        variants.append(
            _build_variant(
                routes[index], totals[index], (), constraints,
                label=label,
                blurb=_FILLER_BLURBS[label],
                variant_id=f"variant-alt{len(variants)}",
            )
        )
        taken.add(index)
        chosen_modes.add(routes[index].get("transit_mode"))

    return variants


def _strategy_rank(name: str) -> int:
    return next(i for i, (label, _) in enumerate(_STRATEGIES) if label == name)


def build_plan_variant_dicts(
    routes: list[dict],
    constraints: PlanConstraints,
) -> list[dict[str, Any]]:
    """`build_plan_variants` as plain dicts, for LangGraph state and the wire."""
    return [variant.to_dict() for variant in build_plan_variants(routes, constraints)]
