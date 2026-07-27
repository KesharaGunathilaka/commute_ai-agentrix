"""
LangGraph StateGraph construction.

Graph topology:
  [START]
     |
  planner ──(error/no route)──► responder ──► [END]
     |
  bus_rag
     |
  train_rag
     |
  fares
     |
  ranker
     |
  uber
     |
  monitor
     |
  +──────────────────────────────+
  | level==CLEAR                 | level!=CLEAR
  v                              v
responder                     replanner
  |                              |
[END]                     (loop back to monitor,
                           max MAX_REPLAN_ATTEMPTS)
                                 |
                            (cap reached)
                                 v
                           responder ──► [END]

Public API:
  run_commute_agent(user_query)             -> AgentState
  run_commute_agent_from_intent(intent)     -> AgentState
  stream_commute_agent_from_intent(intent)  -> Iterator[(node_name, AgentState)]
"""

from __future__ import annotations

from typing import Iterator

from langgraph.graph import END, START, StateGraph

from commute_agent.core.config import get_settings
from commute_agent.core.logging import get_logger, setup_logging
from commute_agent.domain.enums import DisruptionLevel
from commute_agent.graph.nodes.bus_rag import bus_rag_node
from commute_agent.graph.nodes.fares import fare_node
from commute_agent.graph.nodes.monitor import monitor_node
from commute_agent.graph.nodes.planner import planner_node
from commute_agent.graph.nodes.ranker import ranker_node
from commute_agent.graph.nodes.replanner import replanner_node
from commute_agent.graph.nodes.responder import responder_node
from commute_agent.graph.nodes.train_rag import train_rag_node
from commute_agent.graph.nodes.uber import uber_node
from commute_agent.graph.state import AgentState

logger = get_logger(__name__)


def _route_after_planner(state: AgentState) -> str:
    """If planner hit an unrecoverable error, skip to responder."""
    if state.get("error") and not state.get("candidate_route"):
        return "responder"
    return "bus_rag"


def _route_after_monitor(state: AgentState) -> str:
    """Conditional edge: clear -> responder, disrupted -> replanner (if cap not hit)."""
    settings = get_settings()
    disruption = state.get("disruption_status", {})
    level = disruption.get("level", DisruptionLevel.CLEAR) if disruption else DisruptionLevel.CLEAR

    if level == DisruptionLevel.CLEAR:
        return "responder"

    replan_attempts = state.get("replan_attempts", 0)
    if replan_attempts >= settings.max_replan_attempts:
        logger.warning(
            "Max replan attempts (%d) reached — routing to responder.",
            settings.max_replan_attempts,
        )
        return "responder"

    return "replanner"


def _route_after_replanner(state: AgentState) -> str:
    """After replanning, always loop back to monitor to check the new route."""
    return "monitor"


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph StateGraph."""
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("planner", planner_node)
    graph.add_node("bus_rag", bus_rag_node)
    graph.add_node("train_rag", train_rag_node)
    graph.add_node("fares", fare_node)
    graph.add_node("ranker", ranker_node)
    graph.add_node("uber", uber_node)
    graph.add_node("monitor", monitor_node)
    graph.add_node("replanner", replanner_node)
    graph.add_node("responder", responder_node)

    # Entry point
    graph.add_edge(START, "planner")

    # Planner -> conditional (error short-circuit or enrichment pipeline)
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"bus_rag": "bus_rag", "responder": "responder"},
    )

    # Enrichment pipeline (linear). Fares are priced before ranking because
    # cheapest-first sorting depends on them.
    graph.add_edge("bus_rag", "train_rag")
    graph.add_edge("train_rag", "fares")
    graph.add_edge("fares", "ranker")
    graph.add_edge("ranker", "uber")
    graph.add_edge("uber", "monitor")

    # Monitor -> conditional (clear or disrupted)
    graph.add_conditional_edges(
        "monitor",
        _route_after_monitor,
        {"responder": "responder", "replanner": "replanner"},
    )

    # Replanner -> back to Monitor (loop, bounded by cap in _route_after_monitor)
    graph.add_conditional_edges(
        "replanner",
        _route_after_replanner,
        {"monitor": "monitor"},
    )

    # Responder -> END
    graph.add_edge("responder", END)

    return graph.compile()


# Compiled graph singleton (lazy — only built when first needed)
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _blank_state() -> AgentState:
    """Every AgentState key at its zero value.

    Nodes read with `.get()`, so this isn't strictly required — but seeding
    every key keeps the state shape identical on the first node as on the
    last, which matters for the streaming API where partial states go over
    the wire before the graph has finished.
    """
    return {
        "user_query": "",
        "language": "en",
        "origin": None,
        "destination": None,
        "requested_time": None,
        "expected_arrival_time": None,
        "preferred_mode": None,
        "optimise_for": None,
        "trace": [],
        "replan_attempts": 0,
        "candidate_routes": [],
        "candidate_route": None,
        "ranked_routes": [],
        "uber_options": None,
        "uber_last_mile": None,
        "uber_last_mile_distance_m": None,
        "last_mile_transit_leg": None,
        "tts_audio": None,
        "disruption_status": None,
        "alternative_route": None,
        "original_disruption": None,
        "final_response_native": "",
        "final_response_en": "",
        "error": None,
    }


def _state_from_intent(intent: dict) -> AgentState:
    """Seed an AgentState from an already-parsed intent (conversational mode).

    The planner node sees origin + destination already set and skips its NLU
    parse, going straight to Google Maps route discovery.
    """
    state = _blank_state()
    state.update(
        user_query=f"{intent.get('origin', '')} to {intent.get('destination', '')}",
        language=intent.get("language", "en"),
        origin=intent.get("origin"),
        destination=intent.get("destination"),
        requested_time=intent.get("requested_time"),
        expected_arrival_time=intent.get("expected_arrival_time"),
        preferred_mode=intent.get("preferred_mode"),
        optimise_for=intent.get("optimise_for"),
    )
    return state


def run_commute_agent(user_query: str) -> AgentState:
    """
    Run the full commute agent pipeline from a raw user query.

    Args:
        user_query: Raw text from the commuter in any supported language.

    Returns:
        Populated AgentState with final_response_native, final_response_en,
        ranked_routes, tts_audio, and trace.
    """
    logger.info("run_commute_agent: query=%r", user_query[:80])

    initial_state = _blank_state()
    initial_state["user_query"] = user_query

    result: AgentState = _get_graph().invoke(initial_state)

    logger.info("Agent finished. Trace: %s", result.get("trace", []))
    return result


def run_commute_agent_from_intent(intent: dict) -> AgentState:
    """
    Run the planning graph with a pre-parsed intent (conversational mode).

    Args:
        intent: dict with keys: origin, destination, requested_time,
                expected_arrival_time, preferred_mode, language.
    """
    logger.info(
        "run_commute_agent_from_intent: %r -> %r",
        intent.get("origin"), intent.get("destination"),
    )

    result: AgentState = _get_graph().invoke(_state_from_intent(intent))

    logger.info("Agent finished. Trace: %s", result.get("trace", []))
    return result


def stream_commute_agent_from_intent(intent: dict) -> Iterator[tuple[str, AgentState]]:
    """
    Run the planning graph, yielding after each node instead of only at the end.

    Yields `(node_name, state_so_far)` as every node completes, then a final
    `("__end__", full_state)`. This is what backs the live agent-trace panel —
    the commuter watches Planner → Bus RAG → … light up in real time rather
    than staring at a spinner for the whole run.

    The accumulated state is rebuilt here rather than taken from LangGraph's
    "values" stream mode, because "updates" mode is what identifies *which*
    node produced each change — and the node name is the entire point.

    A node that fires twice (the monitor, on a replan loop) yields twice, so
    the frontend can render the loop rather than collapsing it.
    """
    logger.info(
        "stream_commute_agent_from_intent: %r -> %r",
        intent.get("origin"), intent.get("destination"),
    )

    accumulated = _state_from_intent(intent)

    for chunk in _get_graph().stream(accumulated, stream_mode="updates"):
        # Each chunk is {node_name: partial_state}. Fan-out would put more
        # than one key here; this graph is sequential, but loop anyway.
        for node_name, update in chunk.items():
            if update:
                accumulated = {**accumulated, **update}
            yield node_name, accumulated

    logger.info("Agent stream finished. Trace: %s", accumulated.get("trace", []))
    yield "__end__", accumulated


def main() -> None:
    """Quick CLI smoke-test."""
    setup_logging()
    result = run_commute_agent("What time is the morning train from Colombo to Kandy?")
    print("\n=== Agent Result ===")
    print("Native :", result.get("final_response_native"))
    print("English:", result.get("final_response_en"))
    print("Trace  :", result.get("trace"))


if __name__ == "__main__":
    main()
