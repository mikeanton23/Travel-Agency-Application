# -*- coding: utf-8 -*-

"""Rates must be live: never cached, never displayed once expired."""

import inspect
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services.hotels.liteapi_provider import LiteApiProvider
from app.services.hotels.offers import NormalizedOffer, best_offer
from app.ui.pages_hotels import parse_date
from app.utils.http_client import HttpJsonClient, RetryPolicy

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

RATES_JSON = {"data": [{
    "hotelId": "lp1",
    "roomTypes": [{"rates": [{
        "name": "Classic Room",
        "retailRate": {"total": [{"amount": 2477.40,
                                  "currency": "EUR"}]},
    }]}],
}]}


def test_rates_method_is_not_cached():
    """Regression guard: a cache decorator on rates() would serve a
    stale price as if it were live."""
    source = inspect.getsource(LiteApiProvider.rates)
    assert "api_cache" not in source
    assert "cached(" not in source


@pytest.mark.asyncio
async def test_every_call_hits_the_supplier(fresh_cache):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=RATES_JSON)

    provider = LiteApiProvider(
        api_key="k",
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)))
    for _ in range(3):
        await provider.rates(["lp1"], "2026-09-12", "2026-09-15")
    assert calls["n"] == 3            # no caching between searches


@pytest.mark.asyncio
async def test_offers_carry_retrieval_and_expiry(fresh_cache):
    def handler(request):
        return httpx.Response(200, json=RATES_JSON)

    provider = LiteApiProvider(
        api_key="k",
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)))
    offer = (await provider.rates(["lp1"], "2026-09-12",
                                  "2026-09-15"))[0]
    assert offer.retrieved_at is not None
    assert offer.expires_at > offer.retrieved_at
    assert not offer.is_stale()


def test_expired_quote_is_excluded_not_shown():
    fresh = NormalizedOffer(
        hotel_id=None, supplier="liteapi", total_price=300.0,
        currency="EUR", check_in="2026-09-12", check_out="2026-09-15",
        retrieved_at=NOW, expires_at=NOW + timedelta(minutes=30))
    stale = NormalizedOffer(
        hotel_id=None, supplier="liteapi", total_price=100.0,
        currency="EUR", check_in="2026-09-12", check_out="2026-09-15",
        retrieved_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(minutes=1))
    assert stale.is_stale(NOW)
    # The cheaper but expired quote must never win.
    assert best_offer([fresh, stale], now=NOW) is fresh


def test_date_parsing_for_arbitrary_user_dates():
    assert parse_date("2027-03-01") == datetime(2027, 3, 1).date()
    assert parse_date("2027-03-01T00:00:00") == \
        datetime(2027, 3, 1).date()
    assert parse_date("") is None
    assert parse_date("not-a-date") is None
    assert parse_date(None) is None


@pytest.mark.asyncio
async def test_requested_dates_are_sent_verbatim(fresh_cache):
    import json
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RATES_JSON)

    provider = LiteApiProvider(
        api_key="k",
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)))
    await provider.rates(["lp1"], "2027-12-24", "2027-12-31")
    assert seen["body"]["checkin"] == "2027-12-24"
    assert seen["body"]["checkout"] == "2027-12-31"
