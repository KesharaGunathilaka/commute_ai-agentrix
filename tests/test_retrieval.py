"""
Member 1 — Tests for retrieve_routes() and check_disruption().

Run: pytest tests/test_retrieval.py -v
"""

from __future__ import annotations

import json
import pytest

from commute_agent.domain.models import DisruptionStatus, RouteOption
from commute_agent.domain.enums import DisruptionLevel


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_routes(tmp_path, monkeypatch):
    """Write a minimal routes.json and point settings at it."""
    routes = [
        {
            "train_id": "TEST01",
            "line": "Colombo–Kandy",
            "stations": ["Colombo Fort", "Kandy"],
            "departure_times": ["06:30", "10:45"],
            "arrival_times": ["06:30", "10:45"],
            "days_of_operation": ["Mon"],
            "train_type": "Test",
            "description": "Test train from Colombo Fort to Kandy departing 06:30.",
        }
    ]
    routes_file = tmp_path / "routes.json"
    routes_file.write_text(json.dumps(routes))

    from commute_agent.core import config as cfg
    monkeypatch.setattr(cfg.get_settings(), "routes_path", routes_file)
    return routes


@pytest.fixture()
def sample_disruptions(tmp_path, monkeypatch):
    """Write disruptions.json with one active disruption."""
    disruptions = [
        {
            "disruption_id": "D-TEST",
            "train_id": "TEST01",
            "affected_segment": "Colombo Fort → Kandy",
            "type": "delay",
            "delay_minutes": 20,
            "active": True,
            "message": "TEST delay",
        }
    ]
    disruptions_file = tmp_path / "disruptions.json"
    disruptions_file.write_text(json.dumps(disruptions))

    from commute_agent.core import config as cfg
    monkeypatch.setattr(cfg.get_settings(), "disruptions_path", disruptions_file)
    return disruptions


# ── Tests: retrieve_routes ────────────────────────────────────────────────────

class TestRetrieveRoutes:
    def test_returns_list_of_route_options(self, sample_routes):
        """TODO(Member 1): Replace stub assertion with real Chroma retrieval test."""
        from commute_agent.rag.retrieval import retrieve_routes
        # TODO: once Chroma is wired, call retrieve_routes() and assert RouteOption instances
        # routes = retrieve_routes("train to Kandy", destination="Kandy")
        # assert all(isinstance(r, RouteOption) for r in routes)
        pytest.skip("Stub — implement after Chroma ingestion is complete.")

    def test_raises_when_no_match(self, sample_routes):
        """TODO(Member 1): Assert RouteNotFoundError on impossible destination."""
        from commute_agent.rag.retrieval import retrieve_routes
        from commute_agent.core.exceptions import RouteNotFoundError
        # with pytest.raises(RouteNotFoundError):
        #     retrieve_routes("train to Mars")
        pytest.skip("Stub — implement after Chroma ingestion is complete.")

    def test_fallback_keyword_filter(self, sample_routes):
        """Stub filter by destination should work even without Chroma."""
        from commute_agent.rag.retrieval import retrieve_routes
        routes = retrieve_routes("train", destination="Kandy")
        assert len(routes) >= 1
        assert routes[0].destination == "Kandy"


# ── Tests: check_disruption ───────────────────────────────────────────────────

class TestCheckDisruption:
    def test_clear_when_no_active_disruption(self, tmp_path, monkeypatch):
        """Route with no matching active disruption should return CLEAR."""
        disruptions = [
            {
                "disruption_id": "D-INACTIVE",
                "train_id": "TEST01",
                "affected_segment": "Colombo Fort → Kandy",
                "type": "delay",
                "delay_minutes": 20,
                "active": False,
                "message": "Inactive disruption",
            }
        ]
        disruptions_file = tmp_path / "disruptions.json"
        disruptions_file.write_text(json.dumps(disruptions))

        from commute_agent.core import config as cfg
        monkeypatch.setattr(cfg.get_settings(), "disruptions_path", disruptions_file)

        from commute_agent.rag.retrieval import check_disruption
        route = RouteOption(
            train_id="TEST01", line="Test", stations=["A", "B"],
            departure_times=["06:00", "07:00"], arrival_times=["06:00", "07:00"],
            days_of_operation=["Mon"],
        )
        status = check_disruption(route)
        assert status.level == DisruptionLevel.CLEAR

    def test_delayed_when_active_delay(self, sample_disruptions):
        """Route matching an active delay disruption should return DELAYED."""
        from commute_agent.rag.retrieval import check_disruption
        route = RouteOption(
            train_id="TEST01", line="Test", stations=["A", "B"],
            departure_times=["06:30", "10:45"], arrival_times=["06:30", "10:45"],
            days_of_operation=["Mon"],
        )
        status = check_disruption(route)
        assert status.level == DisruptionLevel.DELAYED
        assert status.disruption is not None
