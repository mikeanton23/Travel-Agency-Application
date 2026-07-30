# -*- coding: utf-8 -*-

"""
Sliding-window rate limiter (in-process, thread-safe).

Usage::

    from app.utils.rate_limit import RateLimiter
    limiter = RateLimiter()
    allowed, retry_after = limiter.allow("login:1.2.3.4", limit=5,
                                         window_s=60)

One instance per concern (login attempts, LLM calls, search) or share
one with namespaced keys. For multi-worker deployments swap the store
for Redis behind the same interface.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple


class RateLimiter:
    def __init__(self, max_keys: int = 10_000) -> None:
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(
        self, key: str, limit: int, window_s: float,
        now: float | None = None,
    ) -> Tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)``."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if (len(self._events) >= self._max_keys
                    and key not in self._events):
                self._prune_all(now, window_s)
            events = self._events[key]
            cutoff = now - window_s
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = events[0] + window_s - now
                return False, max(0.0, retry_after)
            events.append(now)
            return True, 0.0

    def remaining(self, key: str, limit: int, window_s: float,
                  now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.get(key)
            if not events:
                return limit
            cutoff = now - window_s
            live = sum(1 for t in events if t > cutoff)
            return max(0, limit - live)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def _prune_all(self, now: float, window_s: float) -> None:
        cutoff = now - window_s
        dead = [k for k, ev in self._events.items()
                if not ev or ev[-1] <= cutoff]
        for k in dead:
            del self._events[k]


# Shared limiters with sensible defaults.
login_limiter = RateLimiter()
search_limiter = RateLimiter()
llm_limiter = RateLimiter()
