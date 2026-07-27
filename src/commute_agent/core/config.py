"""Central settings — loaded once at startup, injected everywhere via DI."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Google / Gemini (kept for reference but not used when groq_api_key is set)
    google_api_key: str = Field(default="", description="Google API key for Gemini")
    google_maps_api_key: str = Field("", description="Google Maps API key; falls back to google_api_key if empty")
    gemini_model: str = "gemini-2.0-flash"
    gemini_temperature: float = 0.1
    gemini_max_tokens: int = 1024

    # Groq (free tier, no billing required — console.groq.com)
    groq_api_key: str = Field(default="", description="Groq API key")
    groq_model: str = "llama-3.3-70b-versatile"

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # RAG / Chroma
    chroma_persist_dir: Path = ROOT / "data" / "chroma_db"
    embedding_model: str = "models/text-embedding-004"

    # Cache
    cache_ttl_seconds: int = 300
    cache_enabled: bool = True

    # Agent behaviour
    max_replan_attempts: int = 2

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated origins allowed to call the API — the Next.js dev server by default",
    )

    google_maps_browser_key: str = Field(
        default="",
        description=(
            "Maps JavaScript API key served to the frontend for the route map. "
            "Kept separate from google_maps_api_key because a browser key is "
            "publicly visible and should be HTTP-referrer restricted, whereas "
            "the server key must not be exposed at all."
        ),
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    # Derived paths (not from env)
    data_dir: Path = ROOT / "data"
    config_dir: Path = ROOT / "config"

    @property
    def routes_path(self) -> Path:
        return self.data_dir / "routes.json"

    @property
    def disruptions_path(self) -> Path:
        return self.data_dir / "disruptions.json"

    @property
    def fares_path(self) -> Path:
        return self.data_dir / "fares.json"

    @property
    def agents_config(self) -> dict:
        return _load_yaml(self.config_dir / "agents.yaml")

    @property
    def prompts_config(self) -> dict:
        return _load_yaml(self.config_dir / "prompts.yaml")

    @property
    def app_settings(self) -> dict:
        return _load_yaml(self.config_dir / "settings.yaml")


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
