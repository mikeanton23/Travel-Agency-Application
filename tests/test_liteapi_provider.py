# -*- coding: utf-8 -*-

import json

import httpx
import pytest

from app.services.hotels.liteapi_provider import LiteApiProvider
from app.services.hotels.search import HotelSearchService
from app.utils.http_client import HttpJsonClient, RetryPolicy

HOTELS_JSON = {"data": [
    {"id": "lp1a2b", "name": "Hotel Grande Bretagne",
     "address": "Syntagma Square", "city": "Athens",
     "country": "GR", "latitude": 37.975, "longitude": 23.735,
     "rating": 4.7, "reviewCount": 812,
     "main_photo": "https://img/gb.jpg"},
    {"id": "lp3c4d", "name": "Athens Central",
     "latitude": 37.98, "longitude": 23.72},
]}

RATES_JSON = {"data": [
    {
        "hotelId": "lp1a2b",
        "roomTypes": [{
            "roomTypeName": "Deluxe Double",
            "offerId": "offer-1",
            "rates": [{
                "name": "Deluxe Double Room",
                "boardName": "Bed and breakfast",
                "retailRate": {"total": [
                    {"amount": 486.30, "currency": "EUR"}]},
                "cancellationPolicies": {
                    "refundableTag": "RFN",
                    "cancelPolicyInfos": [
                        {"cancelTime": "2026-09-10 12:00:00"}]},
            }],
        }],
    },
    {   # rate with no retail total -> must be dropped
        "hotelId": "lp3c4d",
        "roomTypes": [{"rates": [{"name": "Twin",
                                  "retailRate": {}}]}],
    },
]}

GEO_JSON = {"results": [
    {"city": "Athens", "country": "Greece", "country_code": "gr",
     "formatted": "Athens, Greece", "lat": 37.98, "lon": 23.73,
     "rank": {"importance": 0.79}, "population": 3150000},
]}


def make(handler, configured=True):
    return LiteApiProvider(
        api_key="sand_key" if configured else "",
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)),
    )


DETAIL_JSON = {"data": {
    "id": "lp3c4d", "name": "Athens Central",
    "address": "Ermou 1", "city": "Athens",
    "main_photo": "https://img/central.jpg",
    "rating": 4.1, "reviewCount": 220,
}}


def route(request):
    path = request.url.path
    if "geoapify" in str(request.url):
        return httpx.Response(200, json=GEO_JSON)
    # Single-property detail lookup used to fill in missing photos.
    if path.endswith("/data/hotel"):
        return httpx.Response(200, json=DETAIL_JSON)
    if path.endswith("/data/hotels"):
        return httpx.Response(200, json=HOTELS_JSON)
    if path.endswith("/hotels/rates"):
        return httpx.Response(200, json=RATES_JSON)
    raise AssertionError(f"unexpected path {path}")


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "GEOAPIFY_API_KEY", "geo-key")


def test_unconfigured_is_inert():
    assert make(route, configured=False).configured is False


@pytest.mark.asyncio
async def test_api_key_header_used(fresh_cache):
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-API-Key")
        return route(request)

    await make(handler).hotels_near(37.98, 23.73)
    assert seen["key"] == "sand_key"


@pytest.mark.asyncio
async def test_hotels_parsed(fresh_cache):
    hotels = await make(route).hotels_near(37.98, 23.73)
    assert len(hotels) == 2
    assert hotels[0]["hotel_id"] == "lp1a2b"
    assert hotels[0]["name"] == "Hotel Grande Bretagne"
    assert hotels[0]["review_count"] == 812
    assert hotels[0]["source"] == "liteapi"


@pytest.mark.asyncio
async def test_rates_normalised_and_priceless_dropped(fresh_cache):
    provider = make(route)
    offers = await provider.rates(["lp1a2b", "lp3c4d"], "2026-09-12",
                                  "2026-09-15", guests=2,
                                  hotels={"lp1a2b": {"name": "Hotel Grande"}})
    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier == "liteapi"
    assert offer.total_price == 486.30
    assert offer.currency == "EUR"
    assert offer.nights == 3
    assert offer.board_type == "breakfast"
    assert offer.refundable is True
    assert offer.taxes_included is True
    assert not offer.is_stale()


@pytest.mark.asyncio
async def test_rates_request_body_shape(fresh_cache):
    seen = {}

    def handler(request):
        if request.url.path.endswith("/hotels/rates"):
            seen["body"] = json.loads(request.content)
        return route(request)

    await make(handler).rates(["lp1a2b"], "2026-09-12", "2026-09-15",
                              guests=3, rooms=2, currency="usd")
    body = seen["body"]
    assert body["checkin"] == "2026-09-12"
    assert body["currency"] == "USD"
    assert len(body["occupancies"]) == 2          # one per room
    assert body["occupancies"][0]["adults"] == 3


@pytest.mark.asyncio
async def test_unstated_cancellation_stays_unknown(fresh_cache):
    payload = json.loads(json.dumps(RATES_JSON))
    del payload["data"][0]["roomTypes"][0]["rates"][0][
        "cancellationPolicies"]

    def handler(request):
        if request.url.path.endswith("/hotels/rates"):
            return httpx.Response(200, json=payload)
        return route(request)

    offers = await make(handler).rates(["lp1a2b"], "2026-09-12",
                                       "2026-09-15")
    # None, not False: the comparison engine must refuse equivalence.
    assert offers[0].refundable is None


@pytest.mark.asyncio
async def test_supplier_failure_returns_empty(fresh_cache):
    def handler(request):
        if request.url.path.endswith("/hotels/rates"):
            return httpx.Response(502, json={"error": "upstream"})
        return route(request)

    assert await make(handler).rates(["lp1a2b"], "2026-09-12",
                                     "2026-09-15") == []


@pytest.mark.asyncio
async def test_search_service_uses_liteapi_first(fresh_cache):
    service = HotelSearchService(liteapi=make(route))
    service.amadeus.api_key = ""
    service.amadeus.api_secret = ""
    service.booking.affiliate_id = ""
    service.booking.token = ""
    service.http = HttpJsonClient(
        transport=httpx.MockTransport(route),
        retry=RetryPolicy(max_attempts=1))
    assert service.enabled_suppliers() == ["liteapi"]
    result = await service.search("Athens", "2026-09-12", "2026-09-15",
                                  country="Greece")
    assert result.status == "ok"
    assert result.offers[0].supplier == "liteapi"
    assert result.cheapest().total_price == 486.30


@pytest.mark.asyncio
async def test_message_points_at_liteapi_when_unconfigured(fresh_cache):
    service = HotelSearchService(liteapi=make(route, configured=False))
    service.amadeus.api_key = ""
    service.amadeus.api_secret = ""
    service.booking.affiliate_id = ""
    service.booking.token = ""
    result = await service.search("Athens", "2026-09-12", "2026-09-15")
    assert result.status == "not_configured"
    assert "liteapi.travel" in result.message


def test_photo_extraction_across_field_variants():
    from app.services.hotels.liteapi_provider import _first_photo
    assert _first_photo({"main_photo": "https://a/x.jpg"}) == \
        "https://a/x.jpg"
    assert _first_photo({"mainPhoto": "https://b/y.jpg"}) == \
        "https://b/y.jpg"
    assert _first_photo(
        {"hotelImages": [{"url": "https://c/z.jpg"}]}) == \
        "https://c/z.jpg"
    assert _first_photo({"images": ["https://d/w.jpg"]}) == \
        "https://d/w.jpg"
    assert _first_photo({}) is None
    assert _first_photo({"main_photo": "not-a-url"}) is None


@pytest.mark.asyncio
async def test_search_returns_hotels_for_display(fresh_cache):
    service = HotelSearchService(liteapi=make(route))
    service.amadeus.api_key = ""
    service.amadeus.api_secret = ""
    service.booking.affiliate_id = ""
    service.booking.token = ""
    service.http = HttpJsonClient(
        transport=httpx.MockTransport(route),
        retry=RetryPolicy(max_attempts=1))
    result = await service.search("Athens", "2026-09-12", "2026-09-15",
                                  country="Greece")
    # Hotel metadata must travel with the offers so the page can show
    # the real property name and photo instead of a room name.
    assert result.hotels
    names = {h["hotel_id"]: h["name"] for h in result.hotels}
    assert names["lp1a2b"] == "Hotel Grande Bretagne"
    assert result.offers[0].room_id in names


@pytest.mark.asyncio
async def test_room_name_is_not_the_hotel_name(fresh_cache):
    offers = await make(route).rates(["lp1a2b"], "2026-09-12",
                                     "2026-09-15",
                                     hotels={"lp1a2b": {"name": "Hotel Grande"}})
    assert offers[0].room_name == "Deluxe Double Room"
