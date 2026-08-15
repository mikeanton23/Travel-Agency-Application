# -*- coding: utf-8 -*-

"""Shared test fixtures. All tests run fully offline via MockTransport."""

import pytest

from app.services.cache_service import ApiCacheService


@pytest.fixture()
def fresh_cache(monkeypatch):
    """Give every test its own in-memory cache so results don't leak."""
    cache = ApiCacheService()
    import app.services.cache_service as cache_module
    monkeypatch.setattr(cache_module, "api_cache", cache)
    # Services import the singleton by reference; patch their modules too.
    for mod_name in (
        "app.services.amadeus_service",
        "app.services.currency_service",
        "app.services.cost_service",
        "app.services.rag.knowledge",
        "app.services.discovery",
        "app.services.hotels.liteapi_provider",
        "app.services.hotels.booking_provider",
        "app.services.hotels.search",
        "app.services.intelligence.signals",
    ):
        try:
            mod = __import__(mod_name, fromlist=["api_cache"])
            monkeypatch.setattr(mod, "api_cache", cache)
        except ImportError:
            pass
    return cache
