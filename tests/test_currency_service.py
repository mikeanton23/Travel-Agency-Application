# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.currency_service import CurrencyService
from app.utils.http_client import HttpJsonClient


def make_service(handler, api_key=""):
    transport = httpx.MockTransport(handler)
    return CurrencyService(
        api_key=api_key, http=HttpJsonClient(transport=transport)
    )


@pytest.mark.asyncio
async def test_frankfurter_used_without_key(fresh_cache):
    def handler(request):
        assert "frankfurter" in str(request.url)
        return httpx.Response(200, json={
            "base": "EUR", "date": "2026-07-28",
            "rates": {"USD": 1.10, "GBP": 0.85},
        })

    service = make_service(handler)
    data = await service.get_rates("EUR")
    assert data["provider"] == "frankfurter"
    assert data["rates"]["USD"] == 1.10


@pytest.mark.asyncio
async def test_fallback_chain_on_provider_failure(fresh_cache):
    def handler(request):
        url = str(request.url)
        if "frankfurter" in url:
            return httpx.Response(500)
        if "er-api.com" in url:
            return httpx.Response(200, json={
                "result": "success",
                "rates": {"USD": 1.0, "JPY": 155.2},
            })
        raise AssertionError(f"unexpected url {url}")

    service = make_service(handler)
    service.http.retry.max_attempts = 1  # keep the failure path fast
    data = await service.get_rates("USD")
    assert data["provider"] == "open.er-api.com"


@pytest.mark.asyncio
async def test_convert_uses_real_rate(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={
            "base": "EUR", "date": "2026-07-28", "rates": {"USD": 1.20},
        })

    service = make_service(handler)
    result = await service.convert(100, "EUR", "USD")
    assert result["converted"] == 120.0
    assert result["rate"] == 1.20


@pytest.mark.asyncio
async def test_returns_none_when_all_providers_fail(fresh_cache):
    def handler(request):
        return httpx.Response(500)

    service = make_service(handler)
    service.http.retry.max_attempts = 1
    assert await service.get_rates("EUR") is None


@pytest.mark.asyncio
async def test_openexchangerates_rebases_from_usd(fresh_cache):
    def handler(request):
        assert "openexchangerates" in str(request.url)
        return httpx.Response(200, json={
            "timestamp": 1753660800,
            "rates": {"USD": 1.0, "EUR": 0.5, "GBP": 0.4},
        })

    service = make_service(handler, api_key="key123")
    data = await service.get_rates("EUR")
    assert data["provider"] == "openexchangerates"
    assert data["rates"]["USD"] == pytest.approx(2.0)
    assert data["rates"]["GBP"] == pytest.approx(0.8)
