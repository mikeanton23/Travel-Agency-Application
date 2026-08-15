# -*- coding: utf-8 -*-

"""
Live destination discovery.

The Explore page can only rank what the database contains, which makes
a small seed set feel broken: type "Athens" and nothing appears
because nobody ever inserted Athens.

This module fills that gap with real geocoded places from Geoapify.
Discovered places are genuine locations (name, country, coordinates)
returned by a live API - never invented - but they carry no stored
cost or score, and the UI must label them as such rather than
implying they were curated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.cache_service import api_cache
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

DISCOVERY_TTL = 7 * 86400

# Geoapify result types worth offering as a destination.
PLACE_TYPES = ("city", "county", "state", "country")

CONTINENT_BY_CODE = {
    "AF": "Africa", "AN": "Antarctica", "AS": "Asia", "EU": "Europe",
    "NA": "North America", "OC": "Oceania", "SA": "South America",
}


@dataclass
class DiscoveredDestination:
    """Shaped like the Destination model so the same card renders it.

    ``id`` is None: this row does not exist in the database, so it has
    no detail page. Cost and score are None because no real figure has
    been retrieved - the card shows nothing rather than a guess.
    """

    name: str
    country: Optional[str]
    continent: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    id: Optional[int] = None
    avg_cost_per_day: Optional[float] = None
    ai_score: Optional[float] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    best_months: List[Any] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)
    discovered: bool = True
    place_id: Optional[str] = None


class DiscoveryService:
    def __init__(self, http: Optional[HttpJsonClient] = None) -> None:
        self.http = http or HttpJsonClient()

    @property
    def configured(self) -> bool:
        return bool(config.GEOAPIFY_API_KEY)

    async def search(
        self,
        text: str,
        country: Optional[str] = None,
        limit: int = 12,
    ) -> List[DiscoveredDestination]:
        """Find real places matching free text. Empty when Geoapify is
        unconfigured or returns nothing - never fabricated."""
        query = " ".join(p for p in (text, country) if p).strip()
        if not self.configured or not query:
            return []

        @api_cache.cached("geoapify:discover", ttl=DISCOVERY_TTL)
        async def _search(q: str, n: int) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.geoapify.com/v1/geocode/search",
                    params={
                        "text": q,
                        "type": "city",
                        "limit": n,
                        "format": "json",
                        "apiKey": config.GEOAPIFY_API_KEY,
                    },
                )
            except ApiError as exc:
                logger.warning("Discovery failed for %s: %s", q, exc)
                return None
            return (payload or {}).get("results") or []

        rows = await _search(query, limit)
        return [d for d in (self._to_destination(r) for r in rows or [])
                if d is not None]

    async def country_code(self, country: str) -> Optional[str]:
        """ISO2 code for a country name, via geocoding."""
        if not self.configured or not country:
            return None

        @api_cache.cached("geoapify:country_code", ttl=DISCOVERY_TTL)
        async def _lookup(name: str) -> Optional[str]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.geoapify.com/v1/geocode/search",
                    params={"text": name, "type": "country", "limit": 1,
                            "format": "json",
                            "apiKey": config.GEOAPIFY_API_KEY},
                )
            except ApiError as exc:
                logger.warning("Country lookup failed for %s: %s",
                               name, exc)
                return None
            results = (payload or {}).get("results") or []
            if not results:
                return None
            code = results[0].get("country_code")
            return code.upper() if code else None

        return await _lookup(country.strip())

    async def browse_country(
        self, country: str, limit: int = 12
    ) -> List[DiscoveredDestination]:
        """Cities within a country.

        Geocoding "Greece" as a city returns nothing, which made a
        country-only search look broken. This resolves the country to
        its ISO code and then asks the Places API for populated places
        inside it.
        """
        code = await self.country_code(country)
        if not code:
            return []

        @api_cache.cached("geoapify:country_cities", ttl=DISCOVERY_TTL)
        async def _cities(cc: str, n: int) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.geoapify.com/v2/places",
                    params={
                        "categories": "populated_place.city",
                        "filter": f"countrycode:{cc.lower()}",
                        "limit": n,
                        "apiKey": config.GEOAPIFY_API_KEY,
                    },
                )
            except ApiError as exc:
                logger.warning("City browse failed for %s: %s", cc, exc)
                return None
            rows = []
            for feature in (payload or {}).get("features") or []:
                props = feature.get("properties") or {}
                rows.append({
                    "city": props.get("city") or props.get("name"),
                    "country": props.get("country"),
                    "country_code": props.get("country_code"),
                    "lat": props.get("lat"),
                    "lon": props.get("lon"),
                    "place_id": props.get("place_id"),
                    "formatted": props.get("formatted"),
                    "timezone": props.get("timezone") or {},
                })
            return rows

        rows = await _cities(code, limit)
        return [d for d in (self._to_destination(r) for r in rows or [])
                if d is not None]

    async def suggest(
        self, name: str = "", country: str = "", text: str = "",
        limit: int = 12,
    ) -> List[DiscoveredDestination]:
        """Best-effort discovery from whatever the user supplied.

        Tries the most specific signal first: an explicit place name,
        then free text, then all the cities of a named country.
        """
        for query in (name.strip(), text.strip()):
            if query:
                found = await self.search(query, country=country or None,
                                          limit=limit)
                if found:
                    return found
        if country.strip():
            return await self.browse_country(country.strip(),
                                             limit=limit)
        return []

    @staticmethod
    def _to_destination(
        row: Dict[str, Any]
    ) -> Optional[DiscoveredDestination]:
        name = (row.get("city") or row.get("name")
                or row.get("county") or row.get("state"))
        latitude = row.get("lat")
        longitude = row.get("lon")
        if not name or latitude is None or longitude is None:
            return None
        code = (row.get("country_code") or "").upper()
        return DiscoveredDestination(
            name=name,
            country=row.get("country"),
            continent=CONTINENT_BY_CODE.get(
                _continent_code(row), None),
            latitude=float(latitude),
            longitude=float(longitude),
            place_id=row.get("place_id"),
            description=row.get("formatted"),
        )


def _continent_code(row: Dict[str, Any]) -> str:
    """Geoapify does not always return a continent; derive it from the
    timezone or country code where possible, else leave it unknown."""
    timezone = (row.get("timezone") or {}).get("name", "")
    region = timezone.split("/")[0] if "/" in timezone else ""
    mapping = {
        "Africa": "AF", "America": "NA", "Antarctica": "AN",
        "Asia": "AS", "Atlantic": "NA", "Australia": "OC",
        "Europe": "EU", "Indian": "AS", "Pacific": "OC",
    }
    return mapping.get(region, "")


discovery_service = DiscoveryService()
