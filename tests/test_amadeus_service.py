# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.amadeus_service import (
    AmadeusService,
    parse_iso_duration_minutes,
)
from app.utils.http_client import HttpJsonClient

BASE = "https://test.api.amadeus.com"

TOKEN_JSON = {"access_token": "tok-1", "expires_in": 1799}

FLIGHT_OFFERS_JSON = {
    "data": [
        {
            "price": {"grandTotal": "220.50", "currency": "EUR"},
            "validatingAirlineCodes": ["A3"],
            "itineraries": [{
                "duration": "PT3H30M",
                "segments": [{
                    "departure": {"iataCode": "ATH", "at": "2026-09-01T08:00"},
                    "arrival": {"iataCode": "CDG", "at": "2026-09-01T11:30"},
                    "carrierCode": "A3", "number": "610",
                    "duration": "PT3H30M",
                }],
            }],
        },
        {
            "price": {"grandTotal": "150.00", "currency": "EUR"},
            "validatingAirlineCodes": ["FR"],
            "itineraries": [{
                "duration": "PT7H15M",
                "segments": [
                    {
                        "departure": {"iataCode": "ATH",
                                      "at": "2026-09-01T06:00"},
                        "arrival": {"iataCode": "BGY",
                                    "at": "2026-09-01T08:00"},
                        "carrierCode": "FR", "number": "112",
                        "duration": "PT2H",
                    },
                    {
                        "departure": {"iataCode": "BGY",
                                      "at": "2026-09-01T11:15"},
                        "arrival": {"iataCode": "CDG",
                                    "at": "2026-09-01T13:15"},
                        "carrierCode": "FR", "number": "455",
                        "duration": "PT2H",
                    },
                ],
            }],
        },
    ]
}


def make_service(handler):
    return AmadeusService(
        api_key="id", api_secret="secret", base_url=BASE,
        http=HttpJsonClient(transport=httpx.MockTransport(handler)),
    )


def test_parse_iso_duration():
    assert parse_iso_duration_minutes("PT3H30M") == 210
    assert parse_iso_duration_minutes("PT45M") == 45
    assert parse_iso_duration_minutes("P1DT2H") == 1560
    assert parse_iso_duration_minutes("") is None
    assert parse_iso_duration_minutes("garbage") is None


@pytest.mark.asyncio
async def test_flight_search_labels_cheapest_and_fastest(fresh_cache):
    def handler(request):
        url = str(request.url)
        if url.endswith("/v1/security/oauth2/token"):
            return httpx.Response(200, json=TOKEN_JSON)
        if "/v2/shopping/flight-offers" in url:
            assert request.headers["Authorization"] == "Bearer tok-1"
            return httpx.Response(200, json=FLIGHT_OFFERS_JSON)
        raise AssertionError(f"unexpected url {url}")

    service = make_service(handler)
    offers = await service.search_flights("ath", "cdg", "2026-09-01")
    assert len(offers) == 2
    # Sorted by price: FR (150, 1 stop, slow) first.
    assert offers[0]["price_total"] == 150.00
    assert "cheapest" in offers[0]["labels"]
    assert offers[0]["stops"] == 1
    assert offers[1]["price_total"] == 220.50
    assert "fastest" in offers[1]["labels"]
    assert offers[1]["duration_minutes"] == 210
    assert any("best" in o["labels"] for o in offers)
    assert all(o["source"] == "amadeus" for o in offers)


@pytest.mark.asyncio
async def test_unconfigured_service_returns_empty_never_estimates(fresh_cache):
    service = AmadeusService(api_key="", api_secret="")
    assert await service.search_flights("ATH", "CDG", "2026-09-01") == []
    assert await service.hotels_near(48.85, 2.35) == []


@pytest.mark.asyncio
async def test_token_refresh_on_401(fresh_cache):
    tokens = iter(["tok-old", "tok-new"])
    state = {"auth_calls": 0}

    def handler(request):
        url = str(request.url)
        if url.endswith("/v1/security/oauth2/token"):
            state["auth_calls"] += 1
            return httpx.Response(
                200, json={"access_token": next(tokens), "expires_in": 1799}
            )
        if "/v2/shopping/flight-offers" in url:
            if request.headers["Authorization"] == "Bearer tok-old":
                return httpx.Response(401, json={"error": "expired"})
            return httpx.Response(200, json=FLIGHT_OFFERS_JSON)
        raise AssertionError(f"unexpected url {url}")

    service = make_service(handler)
    offers = await service.search_flights("ATH", "CDG", "2026-09-01")
    assert state["auth_calls"] == 2
    assert len(offers) == 2


@pytest.mark.asyncio
async def test_flight_results_are_cached(fresh_cache):
    state = {"searches": 0}

    def handler(request):
        url = str(request.url)
        if url.endswith("/v1/security/oauth2/token"):
            return httpx.Response(200, json=TOKEN_JSON)
        state["searches"] += 1
        return httpx.Response(200, json=FLIGHT_OFFERS_JSON)

    service = make_service(handler)
    await service.search_flights("ATH", "CDG", "2026-09-01")
    await service.search_flights("ATH", "CDG", "2026-09-01")
    assert state["searches"] == 1


@pytest.mark.asyncio
async def test_hotel_offers_parse_and_sort(fresh_cache):
    def handler(request):
        url = str(request.url)
        if url.endswith("/v1/security/oauth2/token"):
            return httpx.Response(200, json=TOKEN_JSON)
        if "/v3/shopping/hotel-offers" in url:
            return httpx.Response(200, json={"data": [
                {
                    "available": True,
                    "hotel": {"hotelId": "H2", "name": "Sea View",
                              "latitude": 1.0, "longitude": 2.0},
                    "offers": [{
                        "checkInDate": "2026-09-01",
                        "checkOutDate": "2026-09-04",
                        "price": {"total": "310.00", "currency": "EUR"},
                        "room": {"typeEstimated": {"category": "DELUXE"}},
                    }],
                },
                {
                    "available": True,
                    "hotel": {"hotelId": "H1", "name": "Old Town Inn",
                              "latitude": 1.1, "longitude": 2.1},
                    "offers": [{
                        "checkInDate": "2026-09-01",
                        "checkOutDate": "2026-09-04",
                        "price": {"total": "180.00", "currency": "EUR"},
                        "room": {"typeEstimated": {"category": "STANDARD"}},
                    }],
                },
            ]})
        raise AssertionError(f"unexpected url {url}")

    service = make_service(handler)
    offers = await service.hotel_offers(
        ["H1", "H2"], "2026-09-01", "2026-09-04"
    )
    assert [o["hotel_id"] for o in offers] == ["H1", "H2"]  # price order
    assert offers[0]["price_total"] == 180.00
