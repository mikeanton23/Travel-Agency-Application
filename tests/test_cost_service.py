# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.cost_service import CostOfLivingService
from app.utils.http_client import HttpJsonClient

NUMBEO_JSON = {
    "name": "Athens, Greece",
    "currency": "EUR",
    "contributors": 412,
    "monthLastUpdate": 7,
    "prices": [
        {"item_id": 1, "average_price": 15.0,
         "lowest_price": 10.0, "highest_price": 20.0},
        {"item_id": 114, "average_price": 3.4,
         "lowest_price": 2.5, "highest_price": 4.5},
        {"item_id": 18, "average_price": 1.2,
         "lowest_price": 1.2, "highest_price": 1.2},
        {"item_id": 9999, "average_price": 99.0},  # unmapped -> ignored
    ],
}


def make_service(handler, api_key="numbeo-key"):
    return CostOfLivingService(
        api_key=api_key,
        http=HttpJsonClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_returns_none_without_key_never_estimates(fresh_cache):
    service = CostOfLivingService(api_key="")
    assert await service.city_costs("Athens", "Greece") is None
    assert "Numbeo API key" in service.unavailable_reason()


@pytest.mark.asyncio
async def test_real_city_prices_are_mapped(fresh_cache):
    def handler(request):
        assert "numbeo.com" in str(request.url)
        return httpx.Response(200, json=NUMBEO_JSON)

    service = make_service(handler)
    data = await service.city_costs("Athens", "Greece")
    assert data["source"] == "numbeo"
    assert data["currency"] == "EUR"
    assert data["items"]["meal_inexpensive"]["average"] == 15.0
    assert data["items"]["cappuccino"]["average"] == 3.4
    assert "9999" not in str(data["items"].keys())


@pytest.mark.asyncio
async def test_numbeo_error_payload_returns_none(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={"error": "no city found"})

    service = make_service(handler)
    assert await service.city_costs("Nowhereville") is None


@pytest.mark.asyncio
async def test_currency_conversion_uses_real_rates(fresh_cache, monkeypatch):
    def handler(request):
        return httpx.Response(200, json=NUMBEO_JSON)

    service = make_service(handler)

    async def fake_convert(amount, from_c, to_c):
        assert (from_c, to_c) == ("EUR", "USD")
        return {"rate": 1.10, "provider": "frankfurter"}

    import app.services.cost_service as mod
    monkeypatch.setattr(mod.currency_service, "convert", fake_convert)

    data = await service.city_costs("Athens", "Greece",
                                    target_currency="USD")
    assert data["currency"] == "USD"
    assert data["items"]["meal_inexpensive"]["average"] == 16.5
    assert data["fx_provider"] == "frankfurter"
