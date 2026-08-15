# -*- coding: utf-8 -*-

"""Ambiguous city names must resolve to the best-known place, and a
stated country must be honoured absolutely."""

import httpx
import pytest

from app.services.hotels.search import HotelSearchService
from app.utils.http_client import HttpJsonClient, RetryPolicy

# Geoapify returns the Georgia one first for a bare "Athens".
ATHENS_JSON = {"results": [
    {"city": "Athens", "country": "United States",
     "country_code": "us", "state": "Georgia",
     "formatted": "Athens, GA, United States",
     "lat": 33.96, "lon": -83.37,
     "rank": {"importance": 0.42}, "population": 127000},
    {"city": "Athens", "country": "Greece", "country_code": "gr",
     "formatted": "Athens, Greece",
     "lat": 37.98, "lon": 23.72,
     "rank": {"importance": 0.79}, "population": 3150000},
]}


def build(handler):
    transport = httpx.MockTransport(handler)
    service = HotelSearchService(
        http=HttpJsonClient(transport=transport,
                            retry=RetryPolicy(max_attempts=1)))
    service.liteapi.api_key = ""
    service.booking.affiliate_id = ""
    service.booking.token = ""
    return service


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "GEOAPIFY_API_KEY", "geo-key")


@pytest.mark.asyncio
async def test_bare_city_picks_the_best_known_place(fresh_cache):
    """Taking the first result sent users to the wrong continent."""
    def handler(request):
        return httpx.Response(200, json=ATHENS_JSON)

    place = await build(handler).resolve_place("Athens")
    assert place["country"] == "Greece"
    assert place["latitude"] == pytest.approx(37.98)


@pytest.mark.asyncio
async def test_stated_country_is_binding(fresh_cache):
    def handler(request):
        return httpx.Response(200, json=ATHENS_JSON)

    service = build(handler)
    us = await service.resolve_place("Athens", "United States")
    assert us["country"] == "United States"
    assert us["latitude"] == pytest.approx(33.96)

    gr = await service.resolve_place("Athens", "Greece")
    assert gr["country"] == "Greece"


@pytest.mark.asyncio
async def test_candidates_are_ranked_for_the_did_you_mean_row(
    fresh_cache,
):
    def handler(request):
        return httpx.Response(200, json=ATHENS_JSON)

    rows = await build(handler).place_candidates("Athens")
    assert [r["country"] for r in rows] == ["Greece", "United States"]


@pytest.mark.asyncio
async def test_geocode_city_uses_the_resolved_place(fresh_cache):
    def handler(request):
        return httpx.Response(200, json=ATHENS_JSON)

    coords = await build(handler).geocode_city("Athens")
    assert coords == (pytest.approx(37.98), pytest.approx(23.72))


@pytest.mark.asyncio
async def test_rows_without_coordinates_are_ignored(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={"results": [
            {"city": "Nowhere", "country": "X"},
        ]})

    assert await build(handler).resolve_place("Nowhere") is None


@pytest.mark.asyncio
async def test_geocode_failure_is_silent(fresh_cache):
    def handler(request):
        return httpx.Response(500)

    assert await build(handler).place_candidates("Athens") == []


# ---------------------------------------------------------------
# The ranking is generic: no city is special-cased anywhere. These
# cases use completely different places to prove it.
# ---------------------------------------------------------------

AMBIGUOUS = {
    "Paris": [
        {"city": "Paris", "country": "United States",
         "country_code": "us", "state": "Texas", "lat": 33.66,
         "lon": -95.55, "rank": {"importance": 0.35},
         "population": 25000},
        {"city": "Paris", "country": "France", "country_code": "fr",
         "state": "Ile-de-France", "lat": 48.85, "lon": 2.35,
         "rank": {"importance": 0.96}, "population": 2100000},
    ],
    "Cambridge": [
        {"city": "Cambridge", "country": "United States",
         "country_code": "us", "state": "Massachusetts",
         "lat": 42.37, "lon": -71.11, "rank": {"importance": 0.55},
         "population": 118000},
        {"city": "Cambridge", "country": "United Kingdom",
         "country_code": "gb", "state": "England", "lat": 52.20,
         "lon": 0.12, "rank": {"importance": 0.72},
         "population": 145000},
    ],
    "Tripoli": [
        {"city": "Tripoli", "country": "Greece", "country_code": "gr",
         "lat": 37.51, "lon": 22.37, "rank": {"importance": 0.41},
         "population": 30000},
        {"city": "Tripoli", "country": "Libya", "country_code": "ly",
         "lat": 32.88, "lon": 13.19, "rank": {"importance": 0.83},
         "population": 1150000},
    ],
    "Santiago": [
        {"city": "Santiago", "country": "Dominican Republic",
         "country_code": "do", "lat": 19.45, "lon": -70.70,
         "rank": {"importance": 0.48}, "population": 690000},
        {"city": "Santiago", "country": "Chile", "country_code": "cl",
         "lat": -33.45, "lon": -70.67, "rank": {"importance": 0.91},
         "population": 5600000},
    ],
}

EXPECTED_BEST = {
    "Paris": "France",
    "Cambridge": "United Kingdom",
    "Tripoli": "Libya",
    "Santiago": "Chile",
}


@pytest.mark.parametrize("city", sorted(AMBIGUOUS))
@pytest.mark.asyncio
async def test_any_ambiguous_city_resolves_to_the_best_known(
    city, fresh_cache,
):
    def handler(request):
        return httpx.Response(200,
                              json={"results": AMBIGUOUS[city]})

    place = await build(handler).resolve_place(city)
    assert place["country"] == EXPECTED_BEST[city]


@pytest.mark.asyncio
async def test_a_state_qualifier_is_honoured(fresh_cache):
    """Users write "Paris, Texas" as often as "Paris, France"."""
    def handler(request):
        return httpx.Response(200,
                              json={"results": AMBIGUOUS["Paris"]})

    service = build(handler)
    texas = await service.resolve_place("Paris", "Texas")
    assert texas["country"] == "United States"
    assert texas["state"] == "Texas"

    france = await service.resolve_place("Paris", "France")
    assert france["country"] == "France"


@pytest.mark.asyncio
async def test_country_code_qualifier_is_honoured(fresh_cache):
    def handler(request):
        return httpx.Response(200,
                              json={"results": AMBIGUOUS["Tripoli"]})

    place = await build(handler).resolve_place("Tripoli", "gr")
    assert place["country"] == "Greece"


def test_no_city_is_hardcoded_in_the_resolver():
    """Guard against anyone 'fixing' one city by special-casing it.

    Comments may name examples; executable code may not. This strips
    comments and docstrings before checking.
    """
    import ast
    import inspect

    from app.services.hotels import search as search_module

    tree = ast.parse(inspect.getsource(search_module))
    # Drop every docstring so only real logic is inspected.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    literals = {
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
    }
    for name in ("athens", "paris", "london", "greece", "georgia",
                 "france", "texas"):
        assert name not in literals, (
            f"'{name}' is a string literal in the resolver; ranking "
            f"must stay generic"
        )
