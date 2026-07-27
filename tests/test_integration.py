"""
Member 5 — End-to-end integration tests.

Run every 1–2 hours (see synchronisation checkpoints) to catch module integration
issues before they pile up.

Run: pytest tests/test_integration.py -v
"""

from __future__ import annotations

import json
import pytest


class TestEndToEndClearRoute:
    """Full pipeline: query → NLU → route retrieval → disruption check → response."""

    def test_english_clear_journey(self):
        """
        Happy path — English query, no disruption, agent returns route + response.

        TODO(Member 5): Enable once Member 1 & 3 stubs are replaced with real calls.
        """
        pytest.skip("Integration stub — enable at Hour 4 checkpoint.")

    def test_sinhala_clear_journey(self):
        """TODO: Sinhala query produces native response."""
        pytest.skip("Integration stub — enable at Hour 7 checkpoint.")

    def test_tamil_clear_journey(self):
        """TODO: Tamil query produces native response."""
        pytest.skip("Integration stub — enable at Hour 7 checkpoint.")


class TestEndToEndDisruptedRoute:
    """Full pipeline with disruption: triggers replan and returns alternative."""

    def test_disrupted_journey_triggers_replan(self, tmp_path, monkeypatch):
        """
        When a disruption is active, the final state must include alternative_route
        and 'replanner' must appear in the trace.

        TODO(Member 5): Wire a fixture that activates a disruption and run the full graph.
        """
        pytest.skip("Integration stub — enable at Hour 9 checkpoint.")

    def test_no_alternative_produces_graceful_response(self):
        """
        When no alternative exists, the agent must still produce a non-empty
        final_response and must not raise an exception.

        TODO(Member 5): Wire a scenario where all alternatives are also disrupted.
        """
        pytest.skip("Integration stub — enable at Hour 9 checkpoint.")


class TestAPILayer:
    """FastAPI endpoint smoke tests."""

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from commute_agent.api.main import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_query_endpoint_returns_200(self, client):
        """TODO(Member 5): Enable once the graph runs end to end."""
        pytest.skip("Integration stub — enable at Hour 7 checkpoint.")
        response = client.post("/api/v1/query", json={"user_query": "Train to Kandy?"})
        assert response.status_code == 200
        data = response.json()
        assert "final_response_en" in data
        assert "trace" in data
