"""Streamlit component: agent trace panel — shows which nodes fired, in order."""

from __future__ import annotations

import streamlit as st

_NODE_ICONS = {
    "planner": "🗺️",
    "bus_rag": "🚌",
    "train_rag": "🚆",
    "fares": "🎫",
    "ranker": "🏆",
    "plan_variants": "⚖️",
    "uber": "🚗",
    "monitor": "📡",
    "replanner": "🔄",
    "responder": "💬",
}

_NODE_DESCRIPTIONS = {
    "planner": "Parsed query & discovered routes via Google Maps",
    "bus_rag": "Looked up bus timetables for scheduled departure times",
    # Not "Scraped trainschedule.lk" any more. That scrape returned the same
    # Colombo Fort -> Rambukkana page for every route and its results replaced
    # correct Maps times; it is disabled (see graph/nodes/train_rag.py).
    "train_rag": "Kept Google Maps train times and recorded their source",
    "fares": "Estimated fares per route from the modelled rate table",
    "ranker": "Ranked top-5 routes by time, deadline, mode, and transfers",
    "plan_variants": "Costed the fastest, cheapest and balanced plans",
    "uber": "Checked ride-hailing options for gaps or last-mile",
    "monitor": "Checked live disruption feed for the selected route",
    "replanner": "Disruption detected — found alternative route",
    "responder": "Generated bilingual response and TTS audio",
}


def render_agent_trace(trace: list[str]) -> None:
    """
    Render the agent execution trace as an expandable step-by-step flow.

    Makes the multi-agent architecture visible to judges.
    """
    if not trace:
        return

    with st.expander("Agent Trace", expanded=False):
        st.caption("Nodes that executed for this query (in order):")
        for i, node in enumerate(trace):
            icon = _NODE_ICONS.get(node, "⚙️")
            desc = _NODE_DESCRIPTIONS.get(node, node)
            st.markdown(f"**{i + 1}.** {icon} `{node}` — {desc}")

        if "replanner" in trace:
            st.info("Replanning was triggered — disruption detected and resolved.", icon="🔄")
