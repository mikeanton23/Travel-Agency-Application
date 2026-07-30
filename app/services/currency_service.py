# -*- coding: utf-8 -*-

"""
Real currency exchange rates with a documented provider chain.

Provider chain (all real data, never estimated):

1. OpenExchangeRates  – if ``OPENEXCHANGERATES_API_KEY`` is set
                        (base USD on the free plan).
2. Frankfurter        – https://api.frankfurter.dev (ECB reference
                        rates, no key required).
3. open.er-api.com    – keyless fallback.

If every provider fails, functions return ``None`` and the UI must say
"exchange rate unavailable" — never guess a rate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.services.cache_service import api_cache
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

RATES_TTL = 43200  # 12 h – reference rates update daily


class CurrencyService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None
            else config.OPENEXCHANGERATES_API_KEY
        )
        self.http = http or HttpJsonClient()

    # ------------------------------------------------------------------
    # Rates
    # ------------------------------------------------------------------

    async def get_rates(self, base: str = "USD") -> Optional[Dict[str, Any]]:
        """Return ``{"base": ..., "rates": {...}, "provider": ...}``."""
        base = base.upper()

        @api_cache.cached("currency:rates", ttl=RATES_TTL)
        async def _fetch(b: str) -> Optional[Dict[str, Any]]:
            for fetcher in (
                self._fetch_openexchangerates,
                self._fetch_frankfurter,
                self._fetch_erapi,
            ):
                result = await fetcher(b)
                if result:
                    return result
            logger.error("All currency providers failed for base %s", b)
            return None

        return await _fetch(base)

    async def convert(
        self, amount: float, from_currency: str, to_currency: str
    ) -> Optional[Dict[str, Any]]:
        """Convert an amount using real rates; ``None`` if unavailable."""
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return {
                "amount": amount, "converted": amount, "rate": 1.0,
                "from": from_currency, "to": to_currency,
                "provider": "identity",
            }
        data = await self.get_rates(from_currency)
        if not data:
            return None
        rate = data.get("rates", {}).get(to_currency)
        if rate is None:
            return None
        return {
            "amount": amount,
            "converted": round(amount * float(rate), 2),
            "rate": float(rate),
            "from": from_currency,
            "to": to_currency,
            "provider": data.get("provider"),
        }

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    async def _fetch_openexchangerates(
        self, base: str
    ) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            return None
        try:
            payload = await self.http.arequest_json(
                "GET",
                "https://openexchangerates.org/api/latest.json",
                params={"app_id": self.api_key},
            )
        except ApiError as exc:
            logger.warning("OpenExchangeRates failed: %s", exc)
            return None
        rates = (payload or {}).get("rates")
        if not rates:
            return None
        # Free plan is USD-based; re-base if another base was requested.
        if base != "USD":
            base_rate = rates.get(base)
            if not base_rate:
                return None
            rates = {k: v / base_rate for k, v in rates.items()}
        return {
            "base": base,
            "rates": rates,
            "provider": "openexchangerates",
            "timestamp": (payload or {}).get("timestamp"),
        }

    async def _fetch_frankfurter(self, base: str) -> Optional[Dict[str, Any]]:
        try:
            payload = await self.http.arequest_json(
                "GET",
                "https://api.frankfurter.dev/v1/latest",
                params={"base": base},
            )
        except ApiError as exc:
            logger.warning("Frankfurter failed: %s", exc)
            return None
        rates = (payload or {}).get("rates")
        if not rates:
            return None
        return {
            "base": base,
            "rates": rates,
            "provider": "frankfurter",
            "timestamp": (payload or {}).get("date"),
        }

    async def _fetch_erapi(self, base: str) -> Optional[Dict[str, Any]]:
        try:
            payload = await self.http.arequest_json(
                "GET", f"https://open.er-api.com/v6/latest/{base}"
            )
        except ApiError as exc:
            logger.warning("open.er-api.com failed: %s", exc)
            return None
        if (payload or {}).get("result") != "success":
            return None
        rates = payload.get("rates")
        if not rates:
            return None
        return {
            "base": base,
            "rates": rates,
            "provider": "open.er-api.com",
            "timestamp": payload.get("time_last_update_unix"),
        }


currency_service = CurrencyService()
