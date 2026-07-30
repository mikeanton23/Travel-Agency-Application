# -*- coding: utf-8 -*-

"""
Amadeus Self-Service API integration: real flight and hotel data.

Replaces every estimated flight/hotel price in the platform. If the
Amadeus credentials are missing or a call fails permanently, functions
return ``None`` / empty lists — the UI must show "data unavailable",
never an estimate.

Endpoints used (test env: https://test.api.amadeus.com,
production: https://api.amadeus.com — set ``AMADEUS_ENV=production``):

* POST /v1/security/oauth2/token            – OAuth2 client credentials
* GET  /v1/reference-data/locations         – city / airport IATA lookup
* GET  /v2/shopping/flight-offers           – flight offers search
* GET  /v1/reference-data/locations/hotels/by-geocode – hotels near a point
* GET  /v3/shopping/hotel-offers            – live hotel prices
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.cache_service import api_cache
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

FLIGHT_CACHE_TTL = 1800       # 30 min – prices move fast
HOTEL_LIST_CACHE_TTL = 86400  # hotel inventory near a point is stable
HOTEL_OFFER_CACHE_TTL = 3600
LOCATION_CACHE_TTL = 604800   # IATA codes basically never change

_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?"
)


def parse_iso_duration_minutes(value: str) -> Optional[int]:
    """Parse an ISO-8601 duration like ``PT11H35M`` into total minutes."""
    if not value:
        return None
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    total = days * 1440 + hours * 60 + minutes
    return total if total > 0 else None


@dataclass
class FlightOffer:
    """Normalised, UI-ready flight offer built from real Amadeus data."""

    price_total: float
    currency: str
    duration_minutes: int
    stops: int
    carrier_code: str
    departure_at: str
    arrival_at: str
    origin: str
    destination: str
    segments: List[Dict[str, Any]] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)  # cheapest/fastest/best

    def to_dict(self) -> Dict[str, Any]:
        return {
            "price_total": self.price_total,
            "currency": self.currency,
            "duration_minutes": self.duration_minutes,
            "stops": self.stops,
            "carrier_code": self.carrier_code,
            "departure_at": self.departure_at,
            "arrival_at": self.arrival_at,
            "origin": self.origin,
            "destination": self.destination,
            "segments": self.segments,
            "labels": self.labels,
            "source": "amadeus",
        }


@dataclass
class _Token:
    value: str
    expires_at: float

    @property
    def valid(self) -> bool:
        # 60s safety margin so we never send an about-to-expire token.
        return time.monotonic() < self.expires_at - 60


class AmadeusService:
    """Async Amadeus client with token caching and response caching."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else config.AMADEUS_API_KEY
        self.api_secret = (
            api_secret if api_secret is not None else config.AMADEUS_API_SECRET
        )
        self.base_url = (base_url or config.AMADEUS_BASE_URL).rstrip("/")
        self.http = http or HttpJsonClient()
        self._token: Optional[_Token] = None
        self._token_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Availability / auth
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def _get_token(self) -> str:
        async with self._token_lock:
            if self._token and self._token.valid:
                return self._token.value
            payload = await self.http.arequest_json(
                "POST",
                f"{self.base_url}/v1/security/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.api_key,
                    "client_secret": self.api_secret,
                },
            )
            token = (payload or {}).get("access_token")
            expires_in = float((payload or {}).get("expires_in", 0))
            if not token:
                raise ApiError("Amadeus token response missing access_token")
            self._token = _Token(
                value=token, expires_at=time.monotonic() + expires_in
            )
            return token

    async def _get(self, path: str, params: Dict[str, Any]) -> Any:
        """Authenticated GET with one automatic re-auth on 401."""
        token = await self._get_token()
        url = f"{self.base_url}{path}"
        try:
            return await self.http.arequest_json(
                "GET", url, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except ApiError as exc:
            if exc.status_code == 401:
                self._token = None
                token = await self._get_token()
                return await self.http.arequest_json(
                    "GET", url, params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
            raise

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    async def resolve_city_code(self, keyword: str) -> Optional[str]:
        """Resolve a city name to its IATA city code (e.g. Paris -> PAR)."""
        if not self.configured or not keyword:
            return None

        @api_cache.cached("amadeus:citycode", ttl=LOCATION_CACHE_TTL)
        async def _lookup(kw: str) -> Optional[str]:
            try:
                payload = await self._get(
                    "/v1/reference-data/locations",
                    {"keyword": kw, "subType": "CITY", "page[limit]": 5},
                )
            except ApiError as exc:
                logger.warning("Amadeus city lookup failed for %s: %s", kw, exc)
                return None
            for item in (payload or {}).get("data", []):
                code = item.get("iataCode")
                if code:
                    return code
            return None

        return await _lookup(keyword.strip().lower())

    # ------------------------------------------------------------------
    # Flights
    # ------------------------------------------------------------------

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        currency: str = "EUR",
        non_stop: Optional[bool] = None,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search real flight offers; labels the cheapest/fastest/best.

        Returns a list of :class:`FlightOffer` dicts sorted by price.
        Empty list means "no real data available" — never estimate.
        """
        if not self.configured:
            logger.info("Amadeus not configured – no flight data returned")
            return []

        @api_cache.cached("amadeus:flights", ttl=FLIGHT_CACHE_TTL)
        async def _search(
            o: str, d: str, dep: str, ret: Optional[str],
            ad: int, cur: str, ns: Optional[bool], mx: int,
        ) -> Optional[List[Dict[str, Any]]]:
            params: Dict[str, Any] = {
                "originLocationCode": o,
                "destinationLocationCode": d,
                "departureDate": dep,
                "adults": ad,
                "currencyCode": cur,
                "max": mx,
            }
            if ret:
                params["returnDate"] = ret
            if ns is not None:
                params["nonStop"] = "true" if ns else "false"
            try:
                payload = await self._get("/v2/shopping/flight-offers", params)
            except ApiError as exc:
                logger.warning("Amadeus flight search failed: %s", exc)
                return None
            offers = self._parse_flight_offers(payload)
            self._label_offers(offers)
            offers.sort(key=lambda x: x.price_total)
            return [x.to_dict() for x in offers]

        result = await _search(
            origin.upper(), destination.upper(), departure_date,
            return_date, adults, currency.upper(), non_stop, max_results,
        )
        return result or []

    @staticmethod
    def _parse_flight_offers(payload: Any) -> List[FlightOffer]:
        offers: List[FlightOffer] = []
        for raw in (payload or {}).get("data", []):
            try:
                price = float(raw["price"]["grandTotal"])
                currency = raw["price"].get("currency", "EUR")
                itineraries = raw.get("itineraries", [])
                if not itineraries:
                    continue
                total_minutes = 0
                stops = 0
                segments: List[Dict[str, Any]] = []
                for itin in itineraries:
                    minutes = parse_iso_duration_minutes(
                        itin.get("duration", "")
                    )
                    segs = itin.get("segments", [])
                    if minutes is None:
                        seg_minutes = [
                            parse_iso_duration_minutes(s.get("duration", ""))
                            for s in segs
                        ]
                        minutes = sum(m for m in seg_minutes if m) or 0
                    total_minutes += minutes
                    stops += max(0, len(segs) - 1)
                    for seg in segs:
                        segments.append({
                            "from": seg.get("departure", {}).get("iataCode"),
                            "to": seg.get("arrival", {}).get("iataCode"),
                            "departure_at": seg.get("departure", {}).get("at"),
                            "arrival_at": seg.get("arrival", {}).get("at"),
                            "carrier": seg.get("carrierCode"),
                            "flight_number": seg.get("number"),
                            "duration": seg.get("duration"),
                        })
                first_itin_segs = itineraries[0].get("segments", [])
                last_itin_segs = itineraries[0].get("segments", [])
                offers.append(FlightOffer(
                    price_total=price,
                    currency=currency,
                    duration_minutes=total_minutes,
                    stops=stops,
                    carrier_code=(
                        raw.get("validatingAirlineCodes") or [""]
                    )[0],
                    departure_at=(
                        first_itin_segs[0]["departure"].get("at", "")
                        if first_itin_segs else ""
                    ),
                    arrival_at=(
                        last_itin_segs[-1]["arrival"].get("at", "")
                        if last_itin_segs else ""
                    ),
                    origin=(
                        first_itin_segs[0]["departure"].get("iataCode", "")
                        if first_itin_segs else ""
                    ),
                    destination=(
                        last_itin_segs[-1]["arrival"].get("iataCode", "")
                        if last_itin_segs else ""
                    ),
                    segments=segments,
                ))
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                logger.debug("Skipping malformed flight offer: %s", exc)
        return offers

    @staticmethod
    def _label_offers(offers: List[FlightOffer]) -> None:
        """Attach cheapest / fastest / best labels.

        "Best" is the offer minimising normalised price + duration +
        a stop penalty — a transparent, explainable rule.
        """
        if not offers:
            return
        cheapest = min(offers, key=lambda x: x.price_total)
        fastest = min(offers, key=lambda x: x.duration_minutes or 10 ** 9)
        cheapest.labels.append("cheapest")
        fastest.labels.append("fastest")

        prices = [x.price_total for x in offers]
        durations = [x.duration_minutes or 0 for x in offers]
        p_min, p_max = min(prices), max(prices)
        d_min, d_max = min(durations), max(durations)

        def norm(value: float, lo: float, hi: float) -> float:
            return 0.0 if hi <= lo else (value - lo) / (hi - lo)

        best = min(
            offers,
            key=lambda x: (
                0.5 * norm(x.price_total, p_min, p_max)
                + 0.4 * norm(x.duration_minutes or 0, d_min, d_max)
                + 0.1 * min(x.stops, 3) / 3
            ),
        )
        best.labels.append("best")

    # ------------------------------------------------------------------
    # Hotels
    # ------------------------------------------------------------------

    async def hotels_near(
        self,
        latitude: float,
        longitude: float,
        radius_km: int = 10,
        max_results: int = 30,
    ) -> List[Dict[str, Any]]:
        """List real hotels near a coordinate (Amadeus hotel inventory)."""
        if not self.configured:
            return []

        @api_cache.cached("amadeus:hotels_near", ttl=HOTEL_LIST_CACHE_TTL)
        async def _list(
            lat: float, lon: float, radius: int
        ) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self._get(
                    "/v1/reference-data/locations/hotels/by-geocode",
                    {
                        "latitude": lat,
                        "longitude": lon,
                        "radius": radius,
                        "radiusUnit": "KM",
                    },
                )
            except ApiError as exc:
                logger.warning("Amadeus hotel list failed: %s", exc)
                return None
            hotels = []
            for item in (payload or {}).get("data", []):
                hotels.append({
                    "hotel_id": item.get("hotelId"),
                    "name": item.get("name"),
                    "latitude": item.get("geoCode", {}).get("latitude"),
                    "longitude": item.get("geoCode", {}).get("longitude"),
                    "distance_km": item.get("distance", {}).get("value"),
                    "source": "amadeus",
                })
            return hotels

        hotels = await _list(round(latitude, 4), round(longitude, 4), radius_km)
        return (hotels or [])[:max_results]

    async def hotel_offers(
        self,
        hotel_ids: List[str],
        check_in: str,
        check_out: str,
        adults: int = 2,
        currency: str = "EUR",
    ) -> List[Dict[str, Any]]:
        """Live prices/availability for specific hotels (Hotel Search v3)."""
        if not self.configured or not hotel_ids:
            return []

        @api_cache.cached("amadeus:hotel_offers", ttl=HOTEL_OFFER_CACHE_TTL)
        async def _offers(
            ids: str, ci: str, co: str, ad: int, cur: str
        ) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self._get(
                    "/v3/shopping/hotel-offers",
                    {
                        "hotelIds": ids,
                        "checkInDate": ci,
                        "checkOutDate": co,
                        "adults": ad,
                        "currency": cur,
                        "bestRateOnly": "true",
                    },
                )
            except ApiError as exc:
                logger.warning("Amadeus hotel offers failed: %s", exc)
                return None
            results = []
            for entry in (payload or {}).get("data", []):
                hotel = entry.get("hotel", {})
                for offer in entry.get("offers", []):
                    price = offer.get("price", {})
                    try:
                        total = float(price.get("total"))
                    except (TypeError, ValueError):
                        continue
                    results.append({
                        "hotel_id": hotel.get("hotelId"),
                        "name": hotel.get("name"),
                        "latitude": hotel.get("latitude"),
                        "longitude": hotel.get("longitude"),
                        "check_in": offer.get("checkInDate"),
                        "check_out": offer.get("checkOutDate"),
                        "price_total": total,
                        "currency": price.get("currency", cur),
                        "room_type": (
                            offer.get("room", {})
                            .get("typeEstimated", {})
                            .get("category")
                        ),
                        "board": offer.get("boardType"),
                        "available": entry.get("available", True),
                        "source": "amadeus",
                    })
            results.sort(key=lambda x: x["price_total"])
            return results

        # Amadeus caps hotelIds per request; chunk to stay safe.
        chunks = [hotel_ids[i:i + 20] for i in range(0, len(hotel_ids), 20)]
        gathered = await asyncio.gather(*[
            _offers(",".join(chunk), check_in, check_out, adults,
                    currency.upper())
            for chunk in chunks
        ])
        merged: List[Dict[str, Any]] = []
        for part in gathered:
            merged.extend(part or [])
        merged.sort(key=lambda x: x["price_total"])
        return merged


# Module-level singleton for app code; tests build their own instances.
amadeus_service = AmadeusService()
