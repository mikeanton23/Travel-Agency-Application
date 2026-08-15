# -*- coding: utf-8 -*-

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, SearchEvent
from app.services.amadeus_service import AmadeusService
from app.services.analytics import Analytics, DatabaseSink
from app.services.hotels.search import HotelSearchService
from app.utils.http_client import HttpJsonClient, RetryPolicy

GEO_JSON = {"results": [
    {"city": "Paris", "country": "France", "country_code": "fr",
     "formatted": "Paris, France", "lat": 48.85, "lon": 2.35,
     "rank": {"importance": 0.9}, "population": 2100000},
]}
TOKEN_JSON = {"access_token": "tok", "expires_in": 1799}


def build(handler, configured=True, retries=1):
    transport = httpx.MockTransport(handler)
    amadeus = AmadeusService(
        api_key="id" if configured else "",
        api_secret="secret" if configured else "",
        base_url="https://test.api.amadeus.com",
        http=HttpJsonClient(transport=transport,
                            retry=RetryPolicy(max_attempts=retries)),
    )
    service = HotelSearchService(
        amadeus=amadeus,
        http=HttpJsonClient(transport=transport,
                            retry=RetryPolicy(max_attempts=retries)),
    )
    # These tests exercise the Amadeus path only. Without this the
    # developer's real LITEAPI_KEY leaks in from .env and takes over.
    service.liteapi.api_key = ""
    service.booking.affiliate_id = ""
    service.booking.token = ""
    return service


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "GEOAPIFY_API_KEY", "geo-key")


@pytest.mark.asyncio
async def test_no_supplier_configured_never_invents_prices(fresh_cache):
    def handler(request):
        raise AssertionError("no calls expected")

    service = build(handler, configured=False)
    result = await service.search("Paris", "2026-09-01", "2026-09-04")
    assert result.status == "not_configured"
    assert result.offers == []
    assert "not configured" in result.message.lower()
    assert not result.has_live_prices


@pytest.mark.asyncio
async def test_supplier_failure_reports_unavailable(fresh_cache):
    def handler(request):
        url = str(request.url)
        if "geoapify" in url:
            return httpx.Response(200, json=GEO_JSON)
        if url.endswith("/v1/security/oauth2/token"):
            return httpx.Response(200, json=TOKEN_JSON)
        return httpx.Response(500)

    service = build(handler)
    result = await service.search("Paris", "2026-09-01", "2026-09-04")
    assert result.status == "unavailable"
    assert result.offers == []
    assert "temporarily unavailable" in result.message.lower()


@pytest.mark.asyncio
async def test_live_search_normalises_and_sorts(fresh_cache):
    def handler(request):
        url = str(request.url)
        if "geoapify" in url:
            return httpx.Response(200, json=GEO_JSON)
        if url.endswith("/v1/security/oauth2/token"):
            return httpx.Response(200, json=TOKEN_JSON)
        if "by-geocode" in url:
            return httpx.Response(200, json={"data": [
                {"hotelId": "H1", "name": "Hotel One",
                 "geoCode": {"latitude": 48.8, "longitude": 2.3}},
                {"hotelId": "H2", "name": "Hotel Two",
                 "geoCode": {"latitude": 48.9, "longitude": 2.4}},
            ]})
        if "hotel-offers" in url:
            return httpx.Response(200, json={"data": [
                {"available": True,
                 "hotel": {"hotelId": "H1", "name": "Hotel One"},
                 "offers": [{"checkInDate": "2026-09-01",
                             "checkOutDate": "2026-09-04",
                             "price": {"total": "420.00",
                                       "currency": "EUR"},
                             "room": {"typeEstimated":
                                      {"category": "DELUXE"}}}]},
                {"available": True,
                 "hotel": {"hotelId": "H2", "name": "Hotel Two"},
                 "offers": [{"checkInDate": "2026-09-01",
                             "checkOutDate": "2026-09-04",
                             "price": {"total": "310.00",
                                       "currency": "EUR"},
                             "room": {"typeEstimated":
                                      {"category": "STANDARD"}}}]},
            ]})
        raise AssertionError(f"unexpected {url}")

    service = build(handler)
    result = await service.search("Paris", "2026-09-01", "2026-09-04",
                                  guests=2)
    assert result.status == "ok"
    assert result.has_live_prices
    assert len(result.offers) == 2
    cheapest = result.cheapest()
    assert cheapest.total_price == 310.0
    assert cheapest.nights == 3
    assert cheapest.supplier == "amadeus"
    # Board unknown from this payload: must not be assumed comparable.
    assert cheapest.board_type == "unknown"


@pytest.mark.asyncio
async def test_geocode_failure_is_graceful(fresh_cache):
    def handler(request):
        if "geoapify" in str(request.url):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json=TOKEN_JSON)

    service = build(handler)
    result = await service.search("Nowhereville", "2026-09-01",
                                  "2026-09-04")
    assert result.status == "unavailable"
    assert result.offers == []


def test_enabled_suppliers_reflects_credentials(monkeypatch):
    from app.utils import settings as settings_module
    settings_module.get_settings.cache_clear()
    service = build(lambda r: httpx.Response(200, json={}))
    assert service.enabled_suppliers() == ["amadeus"]
    service.liteapi.api_key = "sand_x"
    assert service.enabled_suppliers() == ["liteapi", "amadeus"]
    service.liteapi.api_key = ""
    # Credentials alone must NOT make a supplier count as usable:
    # there is no Hotelbeds client, so claiming we searched it would
    # be a false statement to the user.
    monkeypatch.setenv("HOTELBEDS_API_KEY", "k")
    monkeypatch.setenv("HOTELBEDS_SECRET", "s")
    settings_module.get_settings.cache_clear()
    assert "hotelbeds" not in service.enabled_suppliers()
    assert "hotelbeds" in service.credentialled_but_unimplemented()
    settings_module.get_settings.cache_clear()


def test_analytics_writes_events_without_pii():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    tracker = Analytics(sink=DatabaseSink(session_factory=factory))
    tracker.track("hotel_search", destination="Paris",
                  session_hash="abc123",
                  attributes={"guests": 2})
    session = factory()
    row = session.query(SearchEvent).one()
    session.close()
    assert row.event == "hotel_search"
    assert row.destination == "Paris"
    assert row.session_hash == "abc123"
    assert "email" not in str(row.attributes)


def test_analytics_never_raises():
    class Boom(DatabaseSink):
        def emit(self, event, payload):
            raise RuntimeError("sink down")

    Analytics(sink=Boom()).track("hotel_search")  # must not raise
