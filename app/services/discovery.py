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

    async def browse_country(
        self, country: str, limit: int = 12
    ) -> List[DiscoveredDestination]:
        """Notable places within a country, for when the user picks a
        country but names no city."""
        return await self.search(f"cities in {country}", limit=limit)

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
