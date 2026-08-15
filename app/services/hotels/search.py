# -*- coding: utf-8 -*-

"""
Hotel search across configured suppliers.

Resolves a city to coordinates (Geoapify), asks each enabled supplier
for real availability, normalizes every quote through
:mod:`app.services.hotels.offers`, and returns results together with an
explicit status so the UI can distinguish:

* ``ok``            - live results
* ``not_configured``- no supplier credentials; nothing invented
* ``unavailable``   - supplier(s) failed; "live pricing temporarily
                      unavailable"
* ``no_results``    - supplier answered, genuinely nothing available

Cache keys include destination, dates, guests, rooms, currency and
provider. Cached rows keep their original ``retrieved_at`` /
``expires_at``, and expired quotes are dropped rather than re-served as
if live.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.amadeus_service import AmadeusService, amadeus_service
from app.services.cache_service import api_cache
from app.services.hotels.booking_provider import (
    BookingProvider, booking_provider,
)
from app.services.hotels.liteapi_provider import (
    LiteApiProvider, liteapi_provider,
)
from app.services.hotels.offers import (
    NormalizedOffer, best_offer, from_amadeus_offer,
)
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient
from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

GEOCODE_TTL = 30 * 86400
SEARCH_TTL = 900          # 15 min; individual offers carry own expiry


@dataclass
class HotelSearchResult:
    status: str                      # ok / not_configured / unavailable
    offers: List[NormalizedOffer] = field(default_factory=list)
    hotels: List[Dict[str, Any]] = field(default_factory=list)
    message: Optional[str] = None
    suppliers_tried: List[str] = field(default_factory=list)
    retrieved_at: Optional[datetime] = None

    @property
    def has_live_prices(self) -> bool:
        return self.status == "ok" and bool(self.offers)

    def cheapest(self) -> Optional[NormalizedOffer]:
        return best_offer(self.offers)


class HotelSearchService:
    def __init__(
        self,
        amadeus: Optional[AmadeusService] = None,
        booking: Optional[BookingProvider] = None,
        liteapi: Optional[LiteApiProvider] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.amadeus = amadeus or amadeus_service
        self.booking = booking or booking_provider
        self.liteapi = liteapi or liteapi_provider
        self.http = http or HttpJsonClient()
        self.radius_m = 15000

    # ------------------------------------------------------------------
    # Geocoding
    # ------------------------------------------------------------------

    async def geocode_city(
        self, city: str, country: Optional[str] = None
    ) -> Optional[Tuple[float, float]]:
        """Coordinates for a city, preferring the best-known match."""
        place = await self.resolve_place(city, country)
        if place is None:
            return None
        return place["latitude"], place["longitude"]

    async def resolve_place(
        self, city: str, country: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Resolve a city name to one specific place.

        Many city names exist in several countries, and taking the
        first result silently sent users to the wrong continent. This
        applies to every search, not to any particular city: candidates
        are ranked by the geocoder's own importance score and then
        population, and the resolved place is returned so the UI can
        show which one was chosen and offer the alternatives.
        """
        candidates = await self.place_candidates(city, country)
        return candidates[0] if candidates else None

    async def place_candidates(
        self, city: str, country: Optional[str] = None, limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Ranked matches for an ambiguous place name."""
        if not config.GEOAPIFY_API_KEY or not city:
            return []

        @api_cache.cached("geoapify:city_candidates", ttl=GEOCODE_TTL)
        async def _lookup(text: str, n: int) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.geoapify.com/v1/geocode/search",
                    params={"text": text, "type": "city", "limit": n,
                            "format": "json",
                            "apiKey": config.GEOAPIFY_API_KEY},
                )
            except ApiError as exc:
                logger.warning("Geocode failed for %s: %s", text, exc)
                return None
            rows = []
            for row in (payload or {}).get("results") or []:
                lat, lon = row.get("lat"), row.get("lon")
                if lat is None or lon is None:
                    continue
                rank = row.get("rank") or {}
                rows.append({
                    "name": (row.get("city") or row.get("name")
                             or city),
                    "country": row.get("country"),
                    "country_code": (row.get("country_code")
                                     or "").upper(),
                    "state": row.get("state"),
                    "formatted": row.get("formatted"),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "importance": float(rank.get("importance") or 0.0),
                    "population": int(row.get("population") or 0),
                })
            return rows

        query = f"{city}, {country}" if country else city
        rows = await _lookup(query, limit) or []

        # A stated qualifier is a hard requirement, not a hint. It
        # may be a country name, an ISO country code, or a state or
        # region - users write all three interchangeably.
        if country:
            wanted = country.strip().lower()
            exact = [
                r for r in rows
                if wanted in {
                    (r.get("country") or "").lower(),
                    (r.get("country_code") or "").lower(),
                    (r.get("state") or "").lower(),
                }
            ]
            if exact:
                rows = exact

        # Best known place first: Geoapify importance, then population.
        rows.sort(key=lambda r: (r["importance"], r["population"]),
                  reverse=True)
        return rows

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        city: str,
        check_in: str,
        check_out: str,
        country: Optional[str] = None,
        guests: int = 2,
        rooms: int = 1,
        currency: str = "EUR",
        max_hotels: int = 20,
    ) -> HotelSearchResult:
        suppliers = self.enabled_suppliers()
        if not suppliers:
            return HotelSearchResult(
                status="not_configured",
                message=(
                    "Live hotel pricing is not configured yet. Add a free "
                    "LiteAPI sandbox key (liteapi.travel) to "
                    "enable live hotel search -- no prices are "
                    "estimated in the meantime."
                ),
            )

        # LiteAPI first: free sandbox key, real inventory, no
        # approval process.
        if "liteapi" in suppliers:
            offers, hotels = await self._search_liteapi(
                city, country, check_in, check_out, guests, rooms,
                currency, max_hotels,
            )
            if offers:
                return HotelSearchResult(
                    status="ok", offers=offers, hotels=hotels,
                    suppliers_tried=suppliers,
                    retrieved_at=datetime.now(timezone.utc),
                )

        # Booking.com Demand API next when configured: it resolves
        # its own city ids and returns priced products in one call.
        if "booking" in suppliers:
            offers = await self._search_booking(
                city, country, check_in, check_out, guests, rooms,
                currency, max_hotels,
            )
            if offers:
                return HotelSearchResult(
                    status="ok", offers=offers,
                    suppliers_tried=suppliers,
                    retrieved_at=datetime.now(timezone.utc),
                )
            if "amadeus" not in suppliers:
                return HotelSearchResult(
                    status="no_results", suppliers_tried=suppliers,
                    message=("No rooms were returned for these dates. "
                             "Try different dates, or ask us to check "
                             "direct and partner rates for you."),
                    retrieved_at=datetime.now(timezone.utc),
                )

        coords = await self.geocode_city(city, country)
        if coords is None:
            return HotelSearchResult(
                status="unavailable",
                suppliers_tried=suppliers,
                message=(
                    "We couldn't locate that destination to search live "
                    "availability."
                ),
            )

        latitude, longitude = coords
        hotels = await self.amadeus.hotels_near(
            latitude, longitude, radius_km=12, max_results=max_hotels
        )
        if not hotels:
            logger.info(
                "No hotel inventory returned for %s (suppliers=%s). In "
                "the Amadeus test environment inventory is limited to "
                "a subset of cities.", city, suppliers)
            return HotelSearchResult(
                status="unavailable", suppliers_tried=suppliers,
                message=("Live hotel pricing is temporarily unavailable "
                         "for this destination."),
            )

        logger.info("Hotel search %s: %d hotels near %.3f,%.3f",
                    city, len(hotels), latitude, longitude)
        hotel_ids = [h["hotel_id"] for h in hotels if h.get("hotel_id")]
        try:
            raw_offers = await self.amadeus.hotel_offers(
                hotel_ids, check_in, check_out,
                adults=max(1, guests), currency=currency,
            )
        except Exception as exc:      # supplier fault, never fatal
            logger.warning("Hotel offer search failed: %s", exc)
            return HotelSearchResult(
                status="unavailable", hotels=hotels,
                suppliers_tried=suppliers,
                message=("Live hotel pricing is temporarily "
                         "unavailable. Please try again shortly."),
            )

        by_external = {h.get("hotel_id"): h for h in hotels}
        offers: List[NormalizedOffer] = []
        for raw in raw_offers:
            normalized = from_amadeus_offer(raw)
            if normalized is None:
                continue
            normalized.occupancy = max(1, guests)
            meta = by_external.get(raw.get("hotel_id"), {})
            normalized.room_name = raw.get("room_type")
            normalized.deep_link = meta.get("deep_link")
            offers.append(normalized)

        if not offers:
            return HotelSearchResult(
                status="no_results", hotels=hotels,
                suppliers_tried=suppliers,
                message=("No rooms were returned for these dates. Try "
                         "different dates, or ask us to check direct "
                         "and partner rates for you."),
                retrieved_at=datetime.now(timezone.utc),
            )

        offers = [o for o in offers if not o.is_stale()]
        logger.info("Hotel search %s: %d live offers", city, len(offers))
        return HotelSearchResult(
            status="ok", offers=offers, hotels=hotels,
            suppliers_tried=suppliers,
            retrieved_at=datetime.now(timezone.utc),
        )

    async def _search_liteapi(
        self, city: str, country: Optional[str], check_in: str,
        check_out: str, guests: int, rooms: int, currency: str,
        max_results: int,
    ) -> Tuple[List[NormalizedOffer], List[Dict[str, Any]]]:
        """LiteAPI path: locate properties, then request live rates.
        Returns ``(offers, hotels)`` so the UI has property metadata."""
        coords = await self.geocode_city(city, country)
        if coords is None:
            logger.info("LiteAPI: could not geocode %s", city)
            return [], []
        hotels = await self.liteapi.hotels_near(
            coords[0], coords[1], radius_m=self.radius_m,
            limit=max_results)
        if not hotels:
            logger.info("LiteAPI: no properties found near %s", city)
            return [], []
        hotels = await self.liteapi.enrich_photos(hotels)
        by_id = {h["hotel_id"]: h for h in hotels}
        try:
            offers = await self.liteapi.rates(
                list(by_id.keys()), check_in, check_out,
                guests=guests, rooms=rooms, currency=currency,
                guest_nationality=(
                    get_settings().liteapi_guest_nationality),
                hotels=by_id,
            )
        except Exception as exc:      # supplier fault, never fatal
            logger.warning("LiteAPI rates failed: %s", exc)
            return [], hotels
        live = [o for o in offers if not o.is_stale()]
        logger.info("LiteAPI search %s: %d properties, %d live offers",
                    city, len(hotels), len(live))
        return live, hotels

    async def _search_booking(
        self, city: str, country: Optional[str], check_in: str,
        check_out: str, guests: int, rooms: int, currency: str,
        max_results: int,
    ) -> List[NormalizedOffer]:
        """Booking.com path: city id -> search; coordinates fallback."""
        country_code = (country or "")[:2].lower() if country else None
        city_id = await self.booking.resolve_city_id(city, country_code)
        latitude = longitude = None
        if city_id is None:
            coords = await self.geocode_city(city, country)
            if coords is None:
                return []
            latitude, longitude = coords
        try:
            offers = await self.booking.search(
                check_in=check_in, check_out=check_out,
                city_id=city_id, latitude=latitude,
                longitude=longitude, guests=guests, rooms=rooms,
                currency=currency, max_results=max_results,
            )
        except Exception as exc:      # supplier fault, never fatal
            logger.warning("Booking.com search failed: %s", exc)
            return []
        live = [o for o in offers if not o.is_stale()]
        logger.info("Booking.com search %s: %d live offers",
                    city, len(live))
        return live

    # ------------------------------------------------------------------

    # Suppliers this codebase can actually call. Hotelbeds and Expedia
    # have credential slots in .env but no client implementation yet
    # (both require commercial approval), so they must never be counted
    # as "configured" -- that would make the UI claim a search happened
    # against a supplier we never contacted.
    IMPLEMENTED_SUPPLIERS = ("liteapi", "booking", "amadeus")

    def enabled_suppliers(self) -> List[str]:
        """Suppliers that are both implemented and have credentials."""
        active: List[str] = []
        if self.liteapi.configured:
            active.append("liteapi")
        if self.booking.configured:
            active.append("booking")
        if self.amadeus.configured:
            active.append("amadeus")
        return active

    def credentialled_but_unimplemented(self) -> List[str]:
        """Keys present for suppliers we cannot call yet -- surfaced so
        the operator knows why they are being ignored."""
        from app.utils.settings import get_settings
        s = get_settings()
        pending: List[str] = []
        if s.hotelbeds_api_key and s.hotelbeds_secret:
            pending.append("hotelbeds")
        if s.expedia_api_key and s.expedia_api_secret:
            pending.append("expedia")
        return pending


hotel_search_service = HotelSearchService()
