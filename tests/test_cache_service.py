# -*- coding: utf-8 -*-

import asyncio

import pytest

from app.services.cache_service import ApiCacheService, make_cache_key


def test_make_cache_key_is_deterministic():
    a = make_cache_key("ns", 1, "x", flag=True)
    b = make_cache_key("ns", 1, "x", flag=True)
    c = make_cache_key("ns", 2, "x", flag=True)
    assert a == b
    assert a != c
    assert a.startswith("ns:")


@pytest.mark.asyncio
async def test_set_get_and_expiry():
    cache = ApiCacheService()
    await cache.set("k", {"v": 1}, ttl=60)
    hit, value = await cache.get("k")
    assert hit and value == {"v": 1}

    await cache.set("short", "x", ttl=0.01)
    await asyncio.sleep(0.03)
    hit, _ = await cache.get("short")
    assert not hit


@pytest.mark.asyncio
async def test_cached_decorator_caches_and_skips_none():
    cache = ApiCacheService()
    calls = {"n": 0}

    @cache.cached("test:fn", ttl=60)
    async def fn(x):
        calls["n"] += 1
        return None if x == "miss" else x * 2

    assert await fn(3) == 6
    assert await fn(3) == 6
    assert calls["n"] == 1  # second call served from cache

    assert await fn("miss") is None
    assert await fn("miss") is None
    assert calls["n"] == 3  # None results are never cached


@pytest.mark.asyncio
async def test_memory_eviction_keeps_size_bounded():
    cache = ApiCacheService(max_memory_entries=5)
    for i in range(20):
        await cache.set(f"k{i}", i, ttl=60)
    assert len(cache._memory) <= 5
