"""
Member 3 — Tests for parse_query() and generate_response().

Includes the real Sinhala and Tamil test set (task 18 from the handover doc).
Run: pytest tests/test_nlu.py -v
"""

from __future__ import annotations

import pytest

from commute_agent.nlu.models import ParsedIntent
from commute_agent.domain.enums import Language


# ── Real multilingual test queries (Member 3 must verify these parse correctly) ──

SINHALA_QUERIES = [
    "කොළඹ සිට කන්දය ට ට්‍රේන් කීයට?",        # Train time from Colombo to Kandy?
    "ගාල්ල ට හෙට උදේ ට්‍රේන් තිබේද?",         # Is there a morning train to Galle tomorrow?
    "කොළඹ ෆෝට් සිට කෑගල්ල ට ට්‍රේන් ?",       # Train from Colombo Fort to Kegalle?
    "උදෑසන 6 ට කොළඹ ට ට්‍රේන් ?",             # Train to Colombo at 6am?
    "කොළඹ සිට මාතර ට ඉක්මන්ම ට්‍රේන් ?",      # Fastest train from Colombo to Matara?
]

TAMIL_QUERIES = [
    "கொழும்பிலிருந்து கண்டிக்கு ரயில் எத்தனை மணிக்கு?",   # What time is the train to Kandy?
    "காலை ரயில் கொழும்பு முதல் காலி வரை?",                 # Morning train Colombo to Galle?
    "கண்டிக்கு இன்று ரயில் உண்டா?",                         # Is there a train to Kandy today?
    "கொழும்பு கோட்டை நிலையத்திலிருந்து?",                   # From Colombo Fort station?
    "விரைவான ரயில் கொழும்பு முதல் மாத்தறை வரை?",           # Fastest train Colombo to Matara?
]

ENGLISH_QUERIES = [
    "What time is the morning train from Colombo to Kandy?",
    "Is there a train to Galle at 7am?",
    "Next train from Colombo Fort to Peradeniya?",
    "Colombo to Kandy fastest service?",
    "Train schedule Colombo Galle tomorrow morning",
]


class TestParseQuery:
    """Tests for Member 3's parse_query() implementation."""

    @pytest.mark.parametrize("query", ENGLISH_QUERIES)
    def test_english_queries_parse(self, query):
        """TODO(Member 3): These should all parse to Language.ENGLISH with non-null destination."""
        # TODO: remove skip once LLM call is wired in parser.py
        pytest.skip("Stub — enable once Gemini is wired in parse_query().")

        from commute_agent.nlu.parser import parse_query
        intent = parse_query(query)
        assert intent.language == Language.ENGLISH
        assert intent.destination is not None

    @pytest.mark.parametrize("query", SINHALA_QUERIES)
    def test_sinhala_queries_detect_language(self, query):
        """TODO(Member 3): Verify Sinhala queries are detected as Language.SINHALA."""
        pytest.skip("Stub — enable once Gemini is wired in parse_query().")

        from commute_agent.nlu.parser import parse_query
        intent = parse_query(query)
        assert intent.language == Language.SINHALA

    @pytest.mark.parametrize("query", TAMIL_QUERIES)
    def test_tamil_queries_detect_language(self, query):
        """TODO(Member 3): Verify Tamil queries are detected as Language.TAMIL."""
        pytest.skip("Stub — enable once Gemini is wired in parse_query().")

        from commute_agent.nlu.parser import parse_query
        intent = parse_query(query)
        assert intent.language == Language.TAMIL

    def test_off_topic_raises(self):
        """Off-topic queries must be caught by guardrails before hitting the LLM."""
        from commute_agent.core.guardrails import check_off_topic
        from commute_agent.core.exceptions import OffTopicQueryError
        with pytest.raises(OffTopicQueryError):
            check_off_topic("What is the weather today?")

    def test_parsed_intent_time_normalisation(self):
        """'null' strings from LLM output should normalise to None."""
        intent = ParsedIntent(
            language="en",
            origin="Colombo Fort",
            destination="Kandy",
            requested_time="null",
            raw_intent="test",
        )
        assert intent.requested_time is None


class TestGenerateResponse:
    """Tests for Member 3's generate_response() implementation."""

    def test_always_produces_both_fields(self):
        """generate_response() must always return both native and English fields."""
        pytest.skip("Stub — enable once Gemini is wired in responder.py.")

        from commute_agent.nlu.responder import generate_response
        state = {
            "language": "si",
            "candidate_route": {"train_id": "1015", "departure_times": ["06:30"], "arrival_times": ["10:45"]},
            "disruption_status": {"level": "clear", "disruption": None},
            "alternative_route": None,
            "origin": "Colombo Fort",
            "destination": "Kandy",
        }
        result = generate_response(state)
        assert "final_response_native" in result
        assert "final_response_en" in result
        assert result["final_response_native"]
        assert result["final_response_en"]

    def test_disrupted_response_differs_from_clear(self):
        """TODO(Member 3): Disrupted response must not be identical to clear response."""
        pytest.skip("Stub — implement and enable once Gemini is wired.")
