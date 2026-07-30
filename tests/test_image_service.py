# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.image_service import ImageService
from app.utils.http_client import HttpJsonClient

PEXELS_JSON = {
    "photos": [
        {"src": {"large2x": "https://img.pexels/seville-2x.jpg",
                 "large": "https://img.pexels/seville.jpg"}},
        {"src": {"large": "https://img.pexels/seville-b.jpg"}},
    ]
}


def make_service(handler):
    return ImageService(
        http=HttpJsonClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_stored_urls_win_without_any_api_call(fresh_cache):
    def handler(request):
        raise AssertionError("should not call Pexels")

    service = make_service(handler)
    url = await service.destination_image(
        "Seville", "Spain", stored_urls=["https://mine.jpg"]
    )
    assert url == "https://mine.jpg"


@pytest.mark.asyncio
async def test_pexels_best_size_selected(fresh_cache, monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "PEXELS_API_KEY", "px-key")

    def handler(request):
        assert request.headers["Authorization"] == "px-key"
        assert "Seville" in str(request.url)
        return httpx.Response(200, json=PEXELS_JSON)

    service = make_service(handler)
    url = await service.destination_image("Seville", "Spain")
    assert url == "https://img.pexels/seville-2x.jpg"


@pytest.mark.asyncio
async def test_broader_country_fallback(fresh_cache, monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "PEXELS_API_KEY", "px-key")
    calls = []

    def handler(request):
        query = str(request.url)
        calls.append(query)
        if "Ba%C4%8Devi%C4%87i" in query or "Ba" in query.split("query=")[1][:4]:
            return httpx.Response(200, json={"photos": []})
        return httpx.Response(200, json=PEXELS_JSON)

    service = make_service(handler)
    url = await service.destination_image("Bačevići",
                                          "Bosnia and Herzegovina")
    assert url == "https://img.pexels/seville-2x.jpg"
    assert len(calls) == 2  # exact query, then country landscape


@pytest.mark.asyncio
async def test_no_key_returns_none_never_fake(fresh_cache, monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "PEXELS_API_KEY", "")

    def handler(request):
        raise AssertionError("should not be called")

    service = make_service(handler)
    assert await service.destination_image("Seville", "Spain") is None
