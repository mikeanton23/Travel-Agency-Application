# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.discovery import DiscoveryService
from app.utils.http_client import HttpJsonClient, RetryPolicy

GEO_JSON = {"results": [
    {"city": "Athens", "country": "Greece", "country_code": "gr",
     "lat": 37.9838, "lon": 23.7275, "place_id": "abc",
     "formatted": "Athens, Greece",
     "timezone": {"name": "Europe/Athens"}},
    {"city": "Thessaloniki", "country": "Greece", "country_code": "gr",
     "lat": 40.6403, "lon": 22.9439,
     "timezone": {"name": "Europe/Athens"}},
    {"name": "Nowhere", "country": "Greece"},   # no coords -> dropped
]}


def make(handler, configured=True, monkeypatch=None):
    return DiscoveryService(
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)))


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "GEOAPIFY_API_KEY", "geo-key")


@pytest.mark.asyncio
async def test_finds_real_places(fresh_cache):
    def handler(request):
        assert "Athens" in str(request.url)
        return httpx.Response(200, json=GEO_JSON)

    results = await make(handler).search("Athens")
    assert [d.name for d in results] == ["Athens", "Thessaloniki"]
    first = results[0]
    assert first.country == "Greece"
    assert first.continent == "Europe"
    assert first.latitude == pytest.approx(37.9838)


@pytest.mark.asyncio
async def test_discovered_places_carry_no_invented_figures(fresh_cache):
    def handler(request):
        return httpx.Response(200, json=GEO_JSON)

    place = (await make(handler).search("Athens"))[0]
    # A discovered place has no curated cost or score, and the card
    # must therefore show none.
    assert place.avg_cost_per_day is None
    assert place.ai_score is None
    assert place.id is None
    assert place.discovered is True


@pytest.mark.asyncio
async def test_rows_without_coordinates_are_dropped(fresh_cache):
    def handler(request):
        return httpx.Response(200, json=GEO_JSON)

    results = await make(handler).search("Greece")
    assert all(d.latitude is not None for d in results)
    assert "Nowhere" not in [d.name for d in results]


@pytest.mark.asyncio
async def test_unconfigured_returns_nothing(fresh_cache, monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "GEOAPIFY_API_KEY", "")

    def handler(request):
        raise AssertionError("should not call the API")

    assert await make(handler).search("Athens") == []


@pytest.mark.asyncio
async def test_api_failure_returns_nothing(fresh_cache):
    def handler(request):
        return httpx.Response(500)

    assert await make(handler).search("Athens") == []


def test_month_matching_handles_names_and_numbers():
    from app.utils.dates import month_matches as _month_matches

    # Seed data uses short month names; the UI uses numbers.
    assert _month_matches(["May", "Jun", "Sep"], 5)
    assert _month_matches(["May", "Jun", "Sep"], 6)
    assert not _month_matches(["May", "Jun", "Sep"], 8)
    assert _month_matches([5, 6, 9], 5)
    assert _month_matches(["5", "6"], 6)
    # No data, or data we cannot read, must not hide a destination.
    assert _month_matches([], 8)
    assert _month_matches(["whenever"], 8)
