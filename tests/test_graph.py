"""
Member 2 — Tests for the LangGraph topology and run_commute_agent().

Verifies:
- Graph wires up without errors
- Trace list is populated
- Replanning cap is enforced (cannot spin forever)
- Both response fields are always populated
"""

from __future__ import annotations

import pytest

from commute_agent.graph.state import AgentState


class TestGraphTopology:
    def test_graph_compiles_without_error(self):
        """Graph construction must not raise at import time."""
        from commute_agent.graph.builder import build_graph
        graph = build_graph()
        assert graph is not None

    def test_run_returns_agent_state_shape(self):
        """run_commute_agent() must return a dict with all required AgentState keys."""
        from commute_agent.graph.builder import run_commute_agent
        result = run_commute_agent("Test query — stub mode")

        required_keys = {
            "user_query", "language", "trace",
            "final_response_native", "final_response_en",
        }
        for key in required_keys:
            assert key in result, f"Missing key in AgentState: {key}"

    def test_trace_is_populated(self):
        """At minimum, 'planner' and 'responder' must appear in the trace."""
        from commute_agent.graph.builder import run_commute_agent
        result = run_commute_agent("What time is the train to Kandy?")
        trace = result.get("trace", [])
        assert "planner" in trace
        assert "responder" in trace

    def test_replan_cap_not_exceeded(self):
        """
        replan_attempts in final state must not exceed MAX_REPLAN_ATTEMPTS.

        TODO(Member 2): Enable once a disruption scenario triggers replanning.
        Force an active disruption in fixtures, then verify the cap holds.
        """
        pytest.skip("Stub — enable once disruption activation is wired in tests.")

    def test_both_response_fields_populated(self):
        """final_response_native and final_response_en must both be non-empty strings."""
        from commute_agent.graph.builder import run_commute_agent
        result = run_commute_agent("Train from Colombo to Galle?")
        assert isinstance(result.get("final_response_native"), str)
        assert isinstance(result.get("final_response_en"), str)
        assert len(result["final_response_native"]) > 0
        assert len(result["final_response_en"]) > 0


class TestConditionalRouting:
    def test_clear_route_does_not_trigger_replanning(self):
        """
        When disruption_status is CLEAR, replanner must NOT appear in trace.

        TODO: wire a clear disruption fixture and assert 'replanner' not in trace.
        """
        pytest.skip("Stub — enable once full fixture setup is in place.")

    def test_disrupted_route_triggers_replanning(self):
        """
        When disruption_status is not CLEAR, replanner must appear in trace.

        TODO: wire an active disruption fixture and assert 'replanner' in trace.
        """
        pytest.skip("Stub — enable once disruption activation is wired in tests.")
