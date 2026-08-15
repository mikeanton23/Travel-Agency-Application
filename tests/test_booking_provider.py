# -*- coding: utf-8 -*-

import json

import httpx
import pytest

from app.services.hotels.booking_provider import BookingProvider
from app.services.hotels.search import HotelSearchService
from app.utils.http_client import HttpJsonClient, RetryPolicy

SEARCH_JSON = {"data": [
    {
        "id": 1234, "available": True,
        "url": "https://www.booking.com/hotel/gr/x.html",
        "products": [{
            "id": "prod-1",
            "name": "Deluxe Double Room",
            "meal_plan": "breakfast_included",
            "price": {
                "total": {"amount": "412.50", "currency": "EUR"},
                "extra_charges": [
                    {"type": "city_tax", "amount": 12.0,
                     "included_in_price": True},
                ],
            },
            "policies": {"cancellation": {
                "free_cancellation": True,
                "description": "Free until 24h before arrival"}},
        }],
    },
    {   # no price -> must be dropped, never substituted
        "id": 5678, "available": True,
        "products": [{"id": "prod-2", "name": "Twin", "price": {}}],
    },
]}

CITIES_JSON = {"data": [
    {"id": -814876, "name": {"en-gb": "Athens"}},
    {"id": -1456928, "name": {"en-gb": "Paris"}},
]}

DETAILS_JSON = {"data": [
    {"id": 1234, "name": {"en-gb": "Hotel Grande Bretagne"}},
]}


def make(handler, configured=True, env="sandbox"):
    return BookingProvider(
        affiliate_id="12345" if configured else "",
        token="tok" if configured else "",
        environment=env,
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)),
    )


def route(request):
    path = request.url.path
    if path.endswith("/common/locations/cities"):
        return httpx.Response(200, json=CITIES_JSON)
    if path.endswith("/accommodations/search"):
        return httpx.Response(200, json=SEARCH_JSON)
    if path.endswith("/accommodations/details"):
        return httpx.Response(200, json=DETAILS_JSON)
    if path.endswith("/accommodations/availability"):
        return httpx.Response(200, json=SEARCH_JSON)
    raise AssertionError(f"unexpected path {path}")


def test_unconfigured_provider_is_inert():
    provider = make(lambda r: httpx.Response(500), configured=False)
    assert provider.configured is False


def test_sandbox_and_production_urls():
    assert "sandbox" in make(route).base_url
    assert make(route, env="production").base_url == \
        "https://demandapi.booking.com/3.2"


@pytest.mark.asyncio
async def test_auth_headers_and_post_shape(fresh_cache):
    seen = {}

    def handler(request):
        # Capture the search call only: /accommodations/details runs
        # afterwards and would overwrite the body we want to inspect.
        if request.url.path.endswith("/accommodations/search"):
            seen["auth"] = request.headers.get("Authorization")
            seen["affiliate"] = request.headers.get("X-Affiliate-Id")
            seen["method"] = request.method
            seen["body"] = json.loads(request.content)
        return route(request)

    provider = make(handler)
    await provider.search("2026-09-01", "2026-09-04", city_id=-814876)
    assert seen["auth"] == "Bearer tok"
    assert seen["affiliate"] == "12345"
    assert seen["method"] == "POST"          # never GET
    body = seen["body"]
    assert body["checkin"] == "2026-09-01"
    assert body["guests"]["number_of_adults"] == 2
    assert "booker" in body                  # mandatory field


@pytest.mark.asyncio
async def test_city_resolution(fresh_cache):
    provider = make(route)
    assert await provider.resolve_city_id("Athens", "gr") == -814876
    assert await provider.resolve_city_id("Atlantis", "gr") is None


@pytest.mark.asyncio
async def test_offers_are_normalised(fresh_cache):
    provider = make(route)
    offers = await provider.search("2026-09-01", "2026-09-04",
                                   city_id=-814876, guests=2)
    assert len(offers) == 1                  # priceless row dropped
    offer = offers[0]
    assert offer.supplier == "booking"
    assert offer.total_price == 412.50
    assert offer.currency == "EUR"
    assert offer.nights == 3
    assert offer.board_type == "breakfast"
    assert offer.refundable is True
    assert offer.taxes == 12.0
    assert offer.taxes_included is True
    assert not offer.is_stale()


@pytest.mark.asyncio
async def test_excluded_charges_block_like_for_like(fresh_cache):
    payload = json.loads(json.dumps(SEARCH_JSON))
    payload["data"][0]["products"][0]["price"]["extra_charges"][0][
        "included_in_price"] = False

    def handler(request):
        if request.url.path.endswith("/accommodations/search"):
            return httpx.Response(200, json=payload)
        return route(request)

    offers = await make(handler).search("2026-09-01", "2026-09-04",
                                        city_id=-814876)
    # Taxes not in the total -> comparison engine must refuse to
    # treat this as equivalent to an all-in quote.
    assert offers[0].taxes_included is False


@pytest.mark.asyncio
async def test_api_failure_returns_empty_not_fake(fresh_cache):
    def handler(request):
        if request.url.path.endswith("/accommodations/search"):
            return httpx.Response(503, json={"error": "down"})
        return route(request)

    assert await make(handler).search("2026-09-01", "2026-09-04",
                                      city_id=-814876) == []


@pytest.mark.asyncio
async def test_availability_chunks_ids(fresh_cache):
    calls = {"n": 0}

    def handler(request):
        if request.url.path.endswith("/accommodations/availability"):
            calls["n"] += 1
            assert len(json.loads(request.content)["accommodations"]) \
                <= 50
        return route(request)

    provider = make(handler)
    await provider.availability(list(range(1, 121)), "2026-09-01",
                                "2026-09-04")
    assert calls["n"] == 3                   # 120 ids -> 50/50/20


@pytest.mark.asyncio
async def test_search_service_prefers_booking(fresh_cache):
    service = HotelSearchService(booking=make(route))
    service.amadeus.api_key = ""             # Amadeus unconfigured
    service.amadeus.api_secret = ""
    service.liteapi.api_key = ""             # LiteAPI unconfigured
    assert service.enabled_suppliers() == ["booking"]
    result = await service.search("Athens", "2026-09-01", "2026-09-04",
                                  country="Greece")
    assert result.status == "ok"
    assert result.offers[0].supplier == "booking"
    assert result.cheapest().total_price == 412.50


@pytest.mark.asyncio
async def test_no_supplier_configured_message(fresh_cache):
    service = HotelSearchService(
        booking=make(route, configured=False))
    service.amadeus.api_key = ""
    service.amadeus.api_secret = ""
    service.liteapi.api_key = ""
    result = await service.search("Athens", "2026-09-01", "2026-09-04")
    assert result.status == "not_configured"
    assert result.offers == []
