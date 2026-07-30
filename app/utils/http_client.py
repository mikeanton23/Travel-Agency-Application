# -*- coding: utf-8 -*-

"""
Shared async HTTP client with retry, backoff, and rate-limit handling.

Every external API service in the platform should go through
``arequest_json`` so retry behaviour, timeouts, and error reporting
are consistent across the codebase.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ApiError(Exception):
    """Raised when an external API call fails permanently."""

    def __init__(self, message: str, status_code: Optional[int] = None,
                 payload: Optional[Any] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.25

    def delay(self, attempt: int) -> float:
        """Exponential backoff with jitter for the given attempt (0-based)."""
        raw = min(self.max_delay, self.base_delay * (2 ** attempt))
        return raw + random.uniform(0, self.jitter)


@dataclass
class HttpJsonClient:
    """Thin wrapper around ``httpx.AsyncClient`` used by all services.

    A custom ``transport`` can be injected in tests
    (``httpx.MockTransport``) so the whole service layer is testable
    without network access.
    """

    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: httpx.Timeout = DEFAULT_TIMEOUT
    transport: Optional[httpx.AsyncBaseTransport] = None

    async def arequest_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, Any]] = None,
        json: Optional[Any] = None,
    ) -> Any:
        """Perform a request and return decoded JSON.

        Retries transient failures (network errors, 429, 5xx) with
        exponential backoff, honouring ``Retry-After`` when present.
        Raises :class:`ApiError` on permanent failure.
        """
        last_error: Optional[Exception] = None
        started = time.monotonic()

        def _record(status: Optional[int]) -> None:
            try:
                from app.services.metrics import metrics
                metrics.record_http(
                    method, url, status,
                    int((time.monotonic() - started) * 1000),
                )
            except Exception:  # pragma: no cover - defensive
                pass

        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            for attempt in range(self.retry.max_attempts):
                try:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        data=data,
                        json=json,
                    )
                except httpx.TransportError as exc:
                    last_error = exc
                    _record(None)
                    logger.warning(
                        "HTTP transport error on %s (attempt %d/%d): %s",
                        url, attempt + 1, self.retry.max_attempts, exc,
                    )
                    await asyncio.sleep(self.retry.delay(attempt))
                    continue

                if response.status_code in RETRYABLE_STATUS:
                    _record(response.status_code)
                    last_error = ApiError(
                        f"{url} returned {response.status_code}",
                        status_code=response.status_code,
                    )
                    delay = self._retry_after(response) or self.retry.delay(attempt)
                    logger.warning(
                        "Retryable status %d from %s (attempt %d/%d), "
                        "sleeping %.2fs",
                        response.status_code, url,
                        attempt + 1, self.retry.max_attempts, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if response.is_error:
                    _record(response.status_code)
                    raise ApiError(
                        f"{url} failed with {response.status_code}: "
                        f"{response.text[:500]}",
                        status_code=response.status_code,
                        payload=_safe_json(response),
                    )

                _record(response.status_code)
                return _safe_json(response)

        raise ApiError(
            f"{url} failed after {self.retry.max_attempts} attempts: "
            f"{last_error}",
            status_code=getattr(last_error, "status_code", None),
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
