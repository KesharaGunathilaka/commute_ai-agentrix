"""Streamlit component: route summary card."""

from __future__ import annotations

import streamlit as st


def render_route_card(route: dict | None, title: str = "Planned Route") -> None:
    """Render a compact train journey card."""
    if not route:
        return

    train_label = route.get("line") or route.get("route_id", "—")
    stops: list[str] = route.get("stops", [])
    departs = (route.get("departure_times") or ["—"])[0]
    arrives = (route.get("arrival_times") or ["—"])[-1]
    vehicle_type = route.get("vehicle_type", "")
    description = route.get("description", "")
    transit_mode = route.get("transit_mode", "")

    with st.container(border=True):
        st.markdown(f"**{title}**")
        col1, col2, col3 = st.columns(3)
        col1.metric("Service", train_label)
        col2.metric("Departs", departs)
        col3.metric("Arrives", arrives)

        if description:
            st.info(description, icon="🚆" if transit_mode == "train" else "🚌")

        if stops:
            with st.expander(f"Stops ({len(stops)})"):
                st.caption(" → ".join(stops))

        if vehicle_type:
            st.caption(f"Vehicle: {vehicle_type.replace('_', ' ').title()}")
