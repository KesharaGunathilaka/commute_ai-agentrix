"""Pydantic models for NLU input/output — strict schemas so parsing never fails silently."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator

from commute_agent.domain.enums import Language


class ParsedIntent(BaseModel):
    """Structured journey intent extracted from a raw multilingual user query."""

    language: Language
    origin: Optional[str] = None
    destination: Optional[str] = None
    requested_time: Optional[str] = None
    expected_arrival_time: Optional[str] = None
    preferred_mode: Optional[str] = None  # "train" | "bus" | None (any)
    optimise_for: Optional[str] = None  # "fastest" | "cheapest" | "fewest_changes" | None
    raw_intent: str = ""

    @field_validator("optimise_for", mode="before")
    @classmethod
    def normalise_optimisation(cls, v: Optional[str]) -> Optional[str]:
        """Coerce the LLM's answer to a strategy the ranker recognises.

        Anything unrecognised becomes None (balanced ranking) rather than an
        error — a hallucinated value shouldn't fail an otherwise good parse.
        """
        if v in (None, "null", "", "any", "none"):
            return None
        # Imported here to keep the domain models free of a graph-layer import
        # at module scope.
        from commute_agent.graph.nodes.ranker import normalise_optimisation

        return normalise_optimisation(str(v))

    @field_validator("requested_time", "expected_arrival_time", mode="before")
    @classmethod
    def normalise_time(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "null", "", "no", "none", "skip"):
            return None
        return v

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def normalise_station(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "null", ""):
            return None
        return v.strip().title()

    @field_validator("preferred_mode", mode="before")
    @classmethod
    def normalise_mode(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "null", "", "any"):
            return None
        return v.lower().strip()
