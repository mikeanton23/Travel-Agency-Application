# -*- coding: utf-8 -*-

"""
Typed application settings (single source of truth).

Replaces scattered ``os.getenv`` calls with a validated
``pydantic-settings`` model. ``app.utils.config`` remains as a
backward-compatible shim so no existing import breaks.

Resolution order for any value:
    1. Environment variable / .env file      (this module)
    2. Encrypted per-provider override in DB (app.services.key_manager)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core ---
    db_url: str = ""
    app_secret_key: str = ""   # required for encrypted API-key storage
    debug: bool = False

    # --- AI ---
    ollama_model: str = "llama3"
    ollama_host: str = "http://localhost:11434"
    # Which LLM parses natural-language search; empty = auto
    # (gemini -> openai -> anthropic, first one configured).
    nl_parse_provider: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # --- Existing integrations ---
    geoapify_api_key: str = ""
    pexels_api_key: str = ""
    ticketmaster_api_key: str = ""
    ticketmaster_consumer_secret: str = ""
    openrouteservice_api_key: str = ""
    openweather_api_key: str = ""

    # --- Phase 2: real data ---
    amadeus_env: str = "test"
    amadeus_api_key: str = ""
    amadeus_api_secret: str = ""
    openexchangerates_api_key: str = ""
    numbeo_api_key: str = ""

    # --- Reserved / future ---
    booking_api_key: str = ""
    viator_api_key: str = ""
    getyourguide_api_key: str = ""
    opentable_api_key: str = ""

    @property
    def amadeus_base_url(self) -> str:
        if self.amadeus_env.strip().lower() == "production":
            return "https://api.amadeus.com"
        return "https://test.api.amadeus.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
