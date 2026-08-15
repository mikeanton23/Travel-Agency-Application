# -*- coding: utf-8 -*-

"""
Backward-compatible configuration shim.

Historically every module imported constants from here. The source of
truth is now :mod:`app.utils.settings` (pydantic-settings); this module
re-exports the same names so no existing import breaks.

New code should prefer::

    from app.utils.settings import get_settings
    settings = get_settings()
"""

from app.utils.settings import BASE_DIR, ENV_PATH, get_settings

_s = get_settings()

# ==========================================================
# DATABASE
# ==========================================================

DB_URL = _s.db_url

# ==========================================================
# AI
# ==========================================================

OLLAMA_MODEL = _s.ollama_model
OLLAMA_HOST = _s.ollama_host
OPENAI_API_KEY = _s.openai_api_key
ANTHROPIC_API_KEY = _s.anthropic_api_key
GEMINI_API_KEY = _s.gemini_api_key
GEMINI_MODEL = _s.gemini_model

# ==========================================================
# API KEYS
# ==========================================================

GEOAPIFY_API_KEY = _s.geoapify_api_key
PEXELS_API_KEY = _s.pexels_api_key
TICKETMASTER_API_KEY = _s.ticketmaster_api_key
TICKETMASTER_CONSUMER_SECRET = _s.ticketmaster_consumer_secret
OPENROUTESERVICE_API_KEY = _s.openrouteservice_api_key
OPENWEATHER_API_KEY = _s.openweather_api_key

AMADEUS_ENV = _s.amadeus_env
AMADEUS_BASE_URL = _s.amadeus_base_url
AMADEUS_API_KEY = _s.amadeus_api_key
AMADEUS_API_SECRET = _s.amadeus_api_secret
OPENEXCHANGERATES_API_KEY = _s.openexchangerates_api_key
NUMBEO_API_KEY = _s.numbeo_api_key

BOOKING_API_KEY = _s.booking_api_key
VIATOR_API_KEY = _s.viator_api_key
GETYOURGUIDE_API_KEY = _s.getyourguide_api_key
OPENTABLE_API_KEY = _s.opentable_api_key

APP_SECRET_KEY = _s.app_secret_key

if _s.debug:
    print(f"[CONFIG] .env: {ENV_PATH} | DB_URL set: {bool(DB_URL)} | "
          f"AMADEUS_ENV: {AMADEUS_ENV}")
