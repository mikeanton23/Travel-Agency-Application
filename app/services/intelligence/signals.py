# -*- coding: utf-8 -*-

"""
Collect real :class:`DestinationSignals` from live APIs.

Sources (all real, all cached):
* Numbeo (via cost_service)     – prices; Numbeo indices – safety
* Open-Meteo Climate API        – monthly climate normals (keyless)
* Geoapify Places               – POI counts per category
* Amadeus                       – hotel counts/ratings (optional)

Anything unavailable stays ``None`` and the corresponding score
dimension reports "insufficient data".
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from datetime import date
from typing import Dict, Optional

from app.services.cache_service import api_cache
from app.services.cost_service import cost_service
from app.services.intelligence.score import DestinationSignals
from app.utils import config
from app.utils.http_client import (
    ApiError, HttpJsonClient, RetryPolicy,
)

logger = logging.getLogger(__name__)

CLIMATE_TTL = 30 * 86400      # normals are static
POI_TTL = 7 * 86400
SAFETY_TTL = 30 * 86400

GEOAPIFY_CATEGORIES = {
    "restaurants": "catering.restaurant",
    "cafes": "catering.cafe",
    "bars_clubs": "catering.bar,catering.pub,adult.nightclub",
    "museums": "entertainment.museum",
    "monuments": "tourism.sights",
    "parks": "leisure.park",
    "natural": "natural",
    "beaches": "beach",
    "playgrounds": "leisure.playground",
    "theme_parks": "entertainment.theme_park,entertainment.water_park",
    "sports_outdoor": "sport,activity",
}


class SignalsCollector:
    # Open-Meteo's free tier rate-limits aggressively when a results
    # grid requests many climates at once. Gate to 2 concurrent calls,
    # space them ~1s apart, retry only twice, and after a hard failure
    # back off for 10 minutes instead of hammering on every render.
    _CLIMATE_COOLDOWN_S = 600.0

    def __init__(self, http: Optional[HttpJsonClient] = None) -> None:
        self.http = http or HttpJsonClient()
        self._climate_http = http or HttpJsonClient(
            retry=RetryPolicy(max_attempts=2, base_delay=1.0)
        )
        self._climate_gate = asyncio.Semaphore(2)
        self._climate_pace = asyncio.Lock()
        self._climate_last_call = 0.0
        self._climate_backoff_until = 0.0

    # ------------------------------------------------------------------
    # Climate normals (Open-Meteo, keyless)
    # ------------------------------------------------------------------

    async def climate_month(
        self, latitude: float, longitude: float, month: int
    ) -> Dict[str, Optional[float]]:
        @api_cache.cached("openmeteo:climate", ttl=CLIMATE_TTL)
        async def _fetch(lat: float, lon: float) -> Optional[dict]:
            now = time.monotonic()
            if now < self._climate_backoff_until:
                logger.info(
                    "Open-Meteo in cooldown for %.0fs — skipping fetch",
                    self._climate_backoff_until - now,
                )
                return None
            async with self._climate_gate:
                if time.monotonic() < self._climate_backoff_until:
                    return None  # backoff engaged while we queued
                async with self._climate_pace:
                    wait = 1.1 - (time.monotonic()
                                  - self._climate_last_call)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._climate_last_call = time.monotonic()
                # ERA5 reanalysis (real past observations) on the
                # archive endpoint — a separate, far more generous
                # rate-limit pool than climate-api.
                today = date.today()
                start = date(today.year - 3, 1, 1).isoformat()
                end = date(today.year - 1, 12, 31).isoformat()
                try:
                    return await self._climate_http.arequest_json(
                        "GET",
                        "https://archive-api.open-meteo.com/v1/archive",
                        params={
                            "latitude": lat, "longitude": lon,
                            "start_date": start, "end_date": end,
                            "daily": "temperature_2m_max,"
                                     "precipitation_sum,"
                                     "sunshine_duration",
                            "timezone": "UTC",
                        },
                    )
                except ApiError as exc:
                    logger.warning("Open-Meteo archive failed: %s", exc)
                    if exc.status_code == 429:
                        self._climate_backoff_until = (
                            time.monotonic() + self._CLIMATE_COOLDOWN_S
                        )
                    return None

        payload = await _fetch(round(latitude, 3), round(longitude, 3))
        if not payload:
            return {"temp_max_avg_c": None, "rain_days": None,
                    "sunshine_hours_per_day": None}
        daily = payload.get("daily", {})
        dates = daily.get("time", [])
        temps = daily.get("temperature_2m_max", [])
        precip = daily.get("precipitation_sum", [])
        sun = daily.get("sunshine_duration", [])
        month_idx = [
            i for i, d in enumerate(dates)
            if len(d) >= 7 and d[5:7] == f"{month:02d}"
        ]
        if not month_idx:
            return {"temp_max_avg_c": None, "rain_days": None,
                    "sunshine_hours_per_day": None}

        def _vals(series):
            return [series[i] for i in month_idx
                    if i < len(series) and series[i] is not None]

        t_vals = _vals(temps)
        p_vals = _vals(precip)
        s_vals = _vals(sun)
        years = max(1, len({dates[i][:4] for i in month_idx}))
        return {
            "temp_max_avg_c": (
                round(statistics.mean(t_vals), 1) if t_vals else None
            ),
            "rain_days": (
                round(sum(1 for p in p_vals if p >= 1.0) / years, 1)
                if p_vals else None
            ),
            "sunshine_hours_per_day": (
                round(statistics.mean(s_vals) / 3600, 1) if s_vals else None
            ),
        }

    # ------------------------------------------------------------------
    # POI counts (Geoapify)
    # ------------------------------------------------------------------

    async def poi_counts(
        self, latitude: float, longitude: float, radius_m: int = 5000
    ) -> Dict[str, Optional[int]]:
        if not config.GEOAPIFY_API_KEY:
            return {}

        @api_cache.cached("geoapify:poi_count", ttl=POI_TTL)
        async def _count(lat: float, lon: float, r: int,
                         categories: str) -> Optional[int]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.geoapify.com/v2/places",
                    params={
                        "categories": categories,
                        "filter": f"circle:{lon},{lat},{r}",
                        "limit": 500,
                        "apiKey": config.GEOAPIFY_API_KEY,
                    },
                )
            except ApiError as exc:
                logger.warning("Geoapify count failed (%s): %s",
                               categories, exc)
                return None
            features = (payload or {}).get("features")
            return len(features) if features is not None else None

        counts: Dict[str, Optional[int]] = {}
        for name, categories in GEOAPIFY_CATEGORIES.items():
            counts[name] = await _count(
                round(latitude, 3), round(longitude, 3), radius_m, categories
            )
        return {k: v for k, v in counts.items() if v is not None}

    # ------------------------------------------------------------------
    # Safety index (Numbeo indices)
    # ------------------------------------------------------------------

    async def safety_index(self, city: str,
                           country: Optional[str]) -> Optional[float]:
        if not config.NUMBEO_API_KEY:
            return None
        query = f"{city}, {country}" if country else city

        @api_cache.cached("numbeo:indices", ttl=SAFETY_TTL)
        async def _fetch(q: str) -> Optional[dict]:
            try:
                return await self.http.arequest_json(
                    "GET", "https://www.numbeo.com/api/indices",
                    params={"api_key": config.NUMBEO_API_KEY, "query": q},
                )
            except ApiError as exc:
                logger.warning("Numbeo indices failed: %s", exc)
                return None

        payload = await _fetch(query)
        if not payload or payload.get("error"):
            return None
        value = payload.get("safety_index")
        return float(value) if value is not None else None

    # ------------------------------------------------------------------
    # Composite
    # ------------------------------------------------------------------

    async def collect(
        self,
        city: str,
        country: Optional[str],
        latitude: float,
        longitude: float,
        month: int,
        currency: Optional[str] = None,
        hotel_quotes: Optional[list] = None,
    ) -> DestinationSignals:
        """Assemble signals from every reachable real source."""
        signals = DestinationSignals(month=month)

        costs = await cost_service.city_costs(
            city, country, target_currency=currency
        )
        if costs:
            items = costs["items"]
            signals.currency = costs.get("currency")

            def avg(key: str) -> Optional[float]:
                entry = items.get(key)
                return entry.get("average") if entry else None

            signals.meal_inexpensive = avg("meal_inexpensive")
            signals.cappuccino = avg("cappuccino")
            signals.beer = avg("beer_domestic_0_5l")
            signals.transport_ticket = avg("public_transport_one_way")
            signals.taxi_per_km = avg("taxi_per_km")

        climate = await self.climate_month(latitude, longitude, month)
        signals.temp_max_avg_c = climate["temp_max_avg_c"]
        signals.rain_days = climate["rain_days"]
        signals.sunshine_hours_per_day = climate["sunshine_hours_per_day"]

        signals.poi = await self.poi_counts(latitude, longitude)
        signals.safety_index = await self.safety_index(city, country)

        if hotel_quotes:
            prices = [q.get("price_total") for q in hotel_quotes
                      if q.get("price_total")]
            if prices:
                signals.hotel_median_nightly = statistics.median(prices)
            signals.hotel_count = len(hotel_quotes)
            signals.hotel_ratings = [
                q["rating"] for q in hotel_quotes if q.get("rating")
            ]
        return signals


signals_collector = SignalsCollector()
