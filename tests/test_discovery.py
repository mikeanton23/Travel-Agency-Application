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


COUNTRY_JSON = {"results": [
    {"country": "Greece", "country_code": "gr", "lat": 39.0,
     "lon": 22.0, "place_id": "51a1b2c3greece"},
]}

CITIES_JSON = {"features": [
    {"properties": {"city": "Athens", "country": "Greece",
                    "country_code": "gr", "lat": 37.98, "lon": 23.72,
                    "timezone": {"name": "Europe/Athens"}}},
    {"properties": {"city": "Thessaloniki", "country": "Greece",
                    "country_code": "gr", "lat": 40.64, "lon": 22.94,
                    "timezone": {"name": "Europe/Athens"}}},
]}


@pytest.mark.asyncio
async def test_country_only_search_lists_cities(fresh_cache):
    """Geocoding a country as a city returns nothing, which made a
    country-only search look broken."""
    def handler(request):
        url = str(request.url)
        if "type=country" in url:
            return httpx.Response(200, json=COUNTRY_JSON)
        if "/v2/places" in url:
            # Places accepts only spatial filters; a country must be
            # expressed as its boundary place_id.
            assert request.url.params["filter"] == \
                "place:51a1b2c3greece"
            return httpx.Response(200, json=CITIES_JSON)
        return httpx.Response(200, json={"results": []})

    found = await make(handler).browse_country("Greece")
    assert [d.name for d in found] == ["Athens", "Thessaloniki"]
    assert all(d.country == "Greece" for d in found)


@pytest.mark.asyncio
async def test_suggest_prefers_the_most_specific_signal(fresh_cache):
    calls = []

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if "Athens" in url:
            return httpx.Response(200, json=GEO_JSON)
        if "type=country" in url:
            return httpx.Response(200, json=COUNTRY_JSON)
        if "/v2/places" in url:
            return httpx.Response(200, json=CITIES_JSON)
        return httpx.Response(200, json={"results": []})

    service = make(handler)
    # A named place wins and the country browse is never reached.
    found = await service.suggest(name="Athens", country="Greece")
    assert found[0].name == "Athens"
    assert not any("/v2/places" in c for c in calls)


@pytest.mark.asyncio
async def test_suggest_falls_back_to_country(fresh_cache):
    def handler(request):
        url = str(request.url)
        if "type=country" in url:
            return httpx.Response(200, json=COUNTRY_JSON)
        if "/v2/places" in url:
            return httpx.Response(200, json=CITIES_JSON)
        return httpx.Response(200, json={"results": []})

    found = await make(handler).suggest(country="Greece")
    assert [d.name for d in found] == ["Athens", "Thessaloniki"]


@pytest.mark.asyncio
async def test_suggest_with_nothing_returns_nothing(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={"results": []})

    assert await make(handler).suggest() == []


@pytest.mark.asyncio
async def test_country_without_city_features_falls_back_to_radius(
    fresh_cache,
):
    """Some country boundaries return no city features; a radius
    search around the centre is still real data, not a guess."""
    seen = []

    def handler(request):
        url = str(request.url)
        if "type=country" in url:
            return httpx.Response(200, json=COUNTRY_JSON)
        if "/v2/places" in url:
            seen.append(request.url.params["filter"])
            if request.url.params["filter"].startswith("place:"):
                return httpx.Response(200, json={"features": []})
            return httpx.Response(200, json=CITIES_JSON)
        return httpx.Response(200, json={"results": []})

    found = await make(handler).browse_country("Greece")
    assert [d.name for d in found] == ["Athens", "Thessaloniki"]
    assert seen[0].startswith("place:")
    assert seen[1].startswith("circle:")


@pytest.mark.asyncio
async def test_country_lookup_failure_is_silent(fresh_cache):
    def handler(request):
        return httpx.Response(500)

    assert await make(handler).browse_country("Greece") == []


@pytest.mark.asyncio
async def test_continent_search_spreads_across_countries(fresh_cache):
    """A continent search must not be filled by one country."""
    def handler(request):
        url = str(request.url)
        if "type=country" in url:
            name = request.url.params.get("text", "")
            return httpx.Response(200, json={"results": [
                {"country": name, "country_code": name[:2].lower(),
                 "lat": 10.0, "lon": 10.0,
                 "place_id": f"place-{name}"},
            ]})
        if "/v2/places" in url:
            place = request.url.params["filter"].split(":")[-1]
            country = place.replace("place-", "")
            return httpx.Response(200, json={"features": [
                {"properties": {
                    "city": f"{country} City {i}",
                    "country": country, "country_code": "xx",
                    "lat": 10.0 + i, "lon": 10.0 + i,
                    "timezone": {"name": "Europe/Athens"}}}
                for i in range(3)
            ]})
        return httpx.Response(200, json={"results": []})

    found = await make(handler).browse_continent("Europe", limit=12)
    countries = {d.country for d in found}
    assert len(found) == 12
    # Several different countries represented, not just the first.
    assert len(countries) >= 4


@pytest.mark.asyncio
async def test_unknown_continent_returns_nothing(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={"results": []})

    assert await make(handler).browse_continent("Atlantis") == []


@pytest.mark.asyncio
async def test_offset_reaches_different_countries(fresh_cache):
    seen = {"countries": []}

    def handler(request):
        url = str(request.url)
        if "type=country" in url:
            name = request.url.params.get("text", "")
            seen["countries"].append(name)
            return httpx.Response(200, json={"results": [
                {"country": name, "country_code": "xx", "lat": 1.0,
                 "lon": 1.0, "place_id": f"place-{name}"},
            ]})
        if "/v2/places" in url:
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json={"results": []})

    service = make(handler)
    await service.browse_continent("Europe", limit=12, offset=0)
    first = set(seen["countries"])
    seen["countries"] = []
    await service.browse_continent("Europe", limit=12, offset=24)
    second = set(seen["countries"])
    # A later page must look at countries the first page did not.
    assert second - first
