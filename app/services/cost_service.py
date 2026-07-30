# -*- coding: utf-8 -*-

"""
Real cost-of-living data from the Numbeo API.

This module is the replacement for the estimate-based
``pricing_service``: every number returned here is a real Numbeo
average for the requested city.

Policy (matches the platform's "no fake values" rule):
* If ``NUMBEO_API_KEY`` is missing → return ``None`` with a reason.
* If Numbeo has no data for a city → return ``None`` with a reason.
* Numbers are converted to the requested currency with real exchange
  rates via :mod:`app.services.currency_service`.

Numbeo item mapping (item_id, stable per Numbeo docs):
    1   Meal, inexpensive restaurant
    2   Meal for 2, mid-range restaurant
    4   Domestic beer (0.5 l draught)
    114 Cappuccino
    18  One-way ticket, local transport
    20  Monthly pass, local transport
    108 Taxi start (normal tariff)
    107 Taxi 1 km (normal tariff)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.services.cache_service import api_cache
from app.services.currency_service import currency_service
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

COST_TTL = 604800  # 7 days – cost-of-living data moves slowly

ITEM_MAP = {
    1: "meal_inexpensive",
    2: "meal_mid_range_for_two",
    4: "beer_domestic_0_5l",
    114: "cappuccino",
    18: "public_transport_one_way",
    20: "public_transport_monthly",
    108: "taxi_start",
    107: "taxi_per_km",
}


class CostOfLivingService:
    def __init__(
        self,
        api_key: Optional[str] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else config.NUMBEO_API_KEY
        )
        self.http = http or HttpJsonClient()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def city_costs(
        self,
        city: str,
        country: Optional[str] = None,
        target_currency: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Real average prices for a city.

        Returns ``None`` when real data cannot be obtained; check
        :meth:`unavailable_reason` to explain the gap in the UI.
        """
        if not self.configured:
            return None

        query = f"{city}, {country}" if country else city

        @api_cache.cached("numbeo:city_costs", ttl=COST_TTL)
        async def _fetch(q: str) -> Optional[Dict[str, Any]]:
            try:
                payload = await self.http.arequest_json(
                    "GET",
                    "https://www.numbeo.com/api/city_prices",
                    params={"api_key": self.api_key, "query": q},
                )
            except ApiError as exc:
                logger.warning("Numbeo request failed for %s: %s", q, exc)
                return None
            if not payload or payload.get("error"):
                logger.info("Numbeo has no data for %s: %s",
                            q, (payload or {}).get("error"))
                return None
            items: Dict[str, Dict[str, Any]] = {}
            for item in payload.get("prices", []):
                name = ITEM_MAP.get(item.get("item_id"))
                if not name:
                    continue
                items[name] = {
                    "average": item.get("average_price"),
                    "low": item.get("lowest_price"),
                    "high": item.get("highest_price"),
                }
            if not items:
                return None
            return {
                "city": payload.get("name", q),
                "currency": payload.get("currency"),
                "items": items,
                "contributors": payload.get("contributors"),
                "last_update": payload.get("monthLastUpdate"),
                "source": "numbeo",
            }

        data = await _fetch(query)
        if data is None:
            return None
        if target_currency and data.get("currency") \
                and target_currency.upper() != data["currency"].upper():
            data = await self._convert(data, target_currency.upper())
        return data

    def unavailable_reason(self) -> str:
        if not self.configured:
            return (
                "Cost-of-living data requires a Numbeo API key "
                "(Settings → API Keys)."
            )
        return "Numbeo has no data for this city."

    async def _convert(
        self, data: Dict[str, Any], target: str
    ) -> Dict[str, Any]:
        conv = await currency_service.convert(1.0, data["currency"], target)
        if not conv:
            # Keep original currency rather than inventing numbers.
            return data
        rate = conv["rate"]
        converted_items = {}
        for name, values in data["items"].items():
            converted_items[name] = {
                k: (round(v * rate, 2) if isinstance(v, (int, float)) else v)
                for k, v in values.items()
            }
        data = dict(data)
        data["items"] = converted_items
        data["currency"] = target
        data["fx_provider"] = conv.get("provider")
        return data


cost_service = CostOfLivingService()
