# -*- coding: utf-8 -*-

"""
API usage metrics: in-memory counters for dashboards + best-effort
persistence to the ``api_usage`` table.

``HttpJsonClient`` calls :func:`record_http` after every outbound
request, so every real integration (Amadeus, Numbeo, Geoapify, LLMs…)
is counted automatically. Monetary cost is deliberately NOT shown —
we track request counts, statuses and latency, which are real; billing
math without provider price sheets would be a fake value.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROVIDER_BY_HOST = {
    "api.amadeus.com": "amadeus",
    "test.api.amadeus.com": "amadeus",
    "www.numbeo.com": "numbeo",
    "api.geoapify.com": "geoapify",
    "api.pexels.com": "pexels",
    "app.ticketmaster.com": "ticketmaster",
    "api.openrouteservice.org": "openrouteservice",
    "api.openweathermap.org": "openweather",
    "openexchangerates.org": "openexchangerates",
    "api.frankfurter.dev": "frankfurter",
    "open.er-api.com": "er-api",
    "climate-api.open-meteo.com": "open-meteo",
    "api.open-meteo.com": "open-meteo",
    "api.openai.com": "openai",
    "api.anthropic.com": "anthropic",
    "generativelanguage.googleapis.com": "gemini",
}


def provider_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host in PROVIDER_BY_HOST:
        return PROVIDER_BY_HOST[host]
    if host.endswith(("wikipedia.org",)):
        return "wikipedia"
    if host.endswith(("wikivoyage.org",)):
        return "wikivoyage"
    if "localhost:11434" in host or host == "127.0.0.1:11434":
        return "ollama"
    return host or "unknown"


class Metrics:
    def __init__(
        self, session_factory: Optional[Callable[[], Any]] = None
    ) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = defaultdict(int)
        self._errors: Dict[str, int] = defaultdict(int)
        self._duration_ms: Dict[str, int] = defaultdict(int)
        self._session_factory = session_factory

    def bind_session_factory(
        self, session_factory: Callable[[], Any]
    ) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------

    def record_http(
        self, method: str, url: str,
        status_code: Optional[int], duration_ms: int,
    ) -> None:
        provider = provider_from_url(url)
        ok = status_code is not None and status_code < 400
        with self._lock:
            self._counts[provider] += 1
            self._duration_ms[provider] += duration_ms
            if not ok:
                self._errors[provider] += 1
        self._persist(provider, method, url, status_code, ok, duration_ms)

    def _persist(self, provider, method, url, status_code, ok,
                 duration_ms) -> None:
        if self._session_factory is None:
            return
        try:
            from app.db.models import ApiUsageLog

            session = self._session_factory()
            try:
                session.add(ApiUsageLog(
                    provider=provider, method=method.upper(),
                    host=urlparse(url).netloc[:200],
                    status_code=status_code, ok=ok,
                    duration_ms=duration_ms,
                ))
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("api_usage persist skipped: %s", exc)

    # ------------------------------------------------------------------

    def summary(self) -> List[Dict[str, Any]]:
        with self._lock:
            providers = sorted(self._counts)
            return [{
                "provider": p,
                "requests": self._counts[p],
                "errors": self._errors[p],
                "avg_ms": (self._duration_ms[p] // self._counts[p]
                           if self._counts[p] else 0),
            } for p in providers]

    def recent_usage(self, limit: int = 50) -> List[Dict[str, Any]]:
        if self._session_factory is None:
            return []
        from app.db.models import ApiUsageLog

        session = self._session_factory()
        try:
            rows = (
                session.query(ApiUsageLog)
                .order_by(ApiUsageLog.id.desc())
                .limit(limit).all()
            )
            return [{
                "provider": r.provider, "method": r.method,
                "host": r.host, "status": r.status_code,
                "ok": r.ok, "duration_ms": r.duration_ms,
                "at": r.created_at.isoformat() if r.created_at else None,
            } for r in rows]
        finally:
            session.close()


metrics = Metrics()
