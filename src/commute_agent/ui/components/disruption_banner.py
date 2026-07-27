"""Streamlit component: disruption alert banner — visually unmissable when active."""

from __future__ import annotations

import streamlit as st

from commute_agent.domain.enums import DisruptionLevel


def render_disruption_banner(disruption_status: dict | None) -> None:
    """
    Render a prominent disruption alert if disruption_status is not CLEAR.

    Deliberately styled to stand out — this is the moment judges notice.
    """
    if not disruption_status:
        return

    level = disruption_status.get("level", DisruptionLevel.CLEAR)
    disruption = disruption_status.get("disruption")

    if level == DisruptionLevel.CLEAR:
        st.success("All services operating normally.", icon="✅")
        return

    message = disruption.get("message", "Service disruption detected.") if disruption else "Service disruption detected."
    delay = disruption.get("delay_minutes") if disruption else None

    if level == DisruptionLevel.CANCELLED:
        st.error(f"🚨 **Train Cancelled** — {message}", icon="🚨")
    elif level == DisruptionLevel.DELAYED:
        delay_text = f" ({delay} min delay)" if delay else ""
        st.warning(f"⚠️ **Train Delayed**{delay_text} — {message}", icon="⚠️")
