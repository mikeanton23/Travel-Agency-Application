# -*- coding: utf-8 -*-

"""
Unified two-tier cache for external API responses.

Tier 1: process-local in-memory TTL cache (fast, per-run).
Tier 2: PostgreSQL ``api_cache`` table (survives restarts, shared
        between workers).

Usage::

    from app.services.cache_service import api_cache

    @api_cache.cached("amadeus:flights", ttl=1800)
    async def search_flights(origin: str, destination: str, date: str):
        ...

Cache keys are derived from the namespace plus a SHA-256 hash of the
call arguments, so any JSON-serialisable signature works.

Recommended TTLs (seconds):
    weather current      600
    weather forecast    3600
    currency rates     43200
    flight offers       1800
    hotel offers        3600
    cost of living    604800
    places / POIs      86400
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def make_cache_key(namespace: str, *args: Any, **kwargs: Any) -> str:
    """Build a deterministic cache key from a namespace and arguments."""
    try:
        raw = json.dumps([args, kwargs], sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = repr((args, sorted(kwargs.items())))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{namespace}:{digest}"


@dataclass
class _MemoryEntry:
    value: Any
    expires_at: float


@dataclass
class ApiCacheService:
    """Two-tier cache. The DB tier is optional and lazily wired in.

    Call :meth:`bind_session_factory` once at startup with the
    SQLAlchemy session factory to enable persistence; without it the
    cache still works fully in-memory.
    """

    max_memory_entries: int = 4096
    hits: int = 0
    misses: int = 0
    _memory: Dict[str, _MemoryEntry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _session_factory: Optional[Callable[[], Any]] = None

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def bind_session_factory(self, session_factory: Callable[[], Any]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # Core get / set
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Tuple[bool, Any]:
        """Return ``(hit, value)``. Checks memory first, then the DB."""
        now = time.monotonic()
        entry = self._memory.get(key)
        if entry is not None:
            if entry.expires_at > now:
                self.hits += 1
                return True, entry.value
            self._memory.pop(key, None)

        row = await self._db_get(key)
        if row is not None:
            value, expires_at = row
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                await self._memory_set(key, value, remaining)
                self.hits += 1
                return True, value
        self.misses += 1
        return False, None

    async def set(self, key: str, value: Any, ttl: float) -> None:
        await self._memory_set(key, value, ttl)
        await self._db_set(key, value, ttl)

    async def invalidate(self, key: str) -> None:
        self._memory.pop(key, None)
        await self._db_delete(key)

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def cached(
        self, namespace: str, ttl: float
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Decorator caching the result of an async function.

        ``None`` results are not cached, so transient upstream failures
        do not poison the cache.
        """

        def decorator(func: Callable[..., Awaitable[Any]]):
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = make_cache_key(namespace, *args, **kwargs)
                hit, value = await self.get(key)
                if hit:
                    return value
                value = await func(*args, **kwargs)
                if value is not None:
                    await self.set(key, value, ttl)
                return value

            return wrapper

        return decorator

    # ------------------------------------------------------------------
    # Memory tier
    # ------------------------------------------------------------------

    async def _memory_set(self, key: str, value: Any, ttl: float) -> None:
        async with self._lock:
            if len(self._memory) >= self.max_memory_entries:
                self._evict_expired_locked()
            if len(self._memory) >= self.max_memory_entries:
                # Drop the entry closest to expiry.
                victim = min(
                    self._memory, key=lambda k: self._memory[k].expires_at
                )
                self._memory.pop(victim, None)
            self._memory[key] = _MemoryEntry(
                value=value, expires_at=time.monotonic() + ttl
            )

    def _evict_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, e in self._memory.items() if e.expires_at <= now]
        for k in expired:
            self._memory.pop(k, None)

    # ------------------------------------------------------------------
    # DB tier (best-effort: cache must never break the request path)
    # ------------------------------------------------------------------

    async def _db_get(self, key: str) -> Optional[Tuple[Any, datetime]]:
        if self._session_factory is None:
            return None
        try:
            return await asyncio.to_thread(self._db_get_sync, key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("api_cache DB read failed for %s: %s", key, exc)
            return None

    def _db_get_sync(self, key: str) -> Optional[Tuple[Any, datetime]]:
        from app.db.models import ApiCache

        session = self._session_factory()
        try:
            row = session.get(ApiCache, key)
            if row is None:
                return None
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                session.delete(row)
                session.commit()
                return None
            return json.loads(row.payload), expires_at
        finally:
            session.close()

    async def _db_set(self, key: str, value: Any, ttl: float) -> None:
        if self._session_factory is None:
            return
        try:
            await asyncio.to_thread(self._db_set_sync, key, value, ttl)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("api_cache DB write failed for %s: %s", key, exc)

    def _db_set_sync(self, key: str, value: Any, ttl: float) -> None:
        from app.db.models import ApiCache

        payload = json.dumps(value, default=str)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        session = self._session_factory()
        try:
            row = session.get(ApiCache, key)
            if row is None:
                row = ApiCache(cache_key=key)
                session.add(row)
            row.payload = payload
            row.expires_at = expires_at
            session.commit()
        finally:
            session.close()

    async def _db_delete(self, key: str) -> None:
        if self._session_factory is None:
            return
        try:
            await asyncio.to_thread(self._db_delete_sync, key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("api_cache DB delete failed for %s: %s", key, exc)

    def _db_delete_sync(self, key: str) -> None:
        from app.db.models import ApiCache

        session = self._session_factory()
        try:
            row = session.get(ApiCache, key)
            if row is not None:
                session.delete(row)
                session.commit()
        finally:
            session.close()


    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else None,
            "memory_entries": len(self._memory),
            "db_tier": self._session_factory is not None,
        }


# Module-level singleton used across services.
api_cache = ApiCacheService()
