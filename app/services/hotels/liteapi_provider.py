# -*- coding: utf-8 -*-

"""
LiteAPI (Nuitee Connect) v3.0 hotel provider.

Docs: https://docs.liteapi.travel

Why this exists: Amadeus decommissioned its self-service portal on
17 July 2026 and deactivated those keys, so it is no longer a viable
starting point for new projects. LiteAPI issues a free sandbox key on
registration with no credit card, and the sandbox mirrors production
inventory - which makes it the practical default supplier here.

Endpoints used:
    GET  /v3.0/data/hotels    static properties near a point / in a city
    POST /v3.0/hotels/rates   live rates and availability for hotel ids

Auth is a single ``X-API-Key`` header. Sandbox and production are
distinguished by the key itself, not by the host.
"""

from __future__ import annotations

import asyncio

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.cache_service import api_cache
from app.services.hotels.offers import NormalizedOffer, normalize_board
from app.utils.http_client import ApiError, HttpJsonClient
from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.liteapi.travel/v3.0"
HOTELS_TTL = 7 * 86400
OFFER_TTL_MINUTES = 30

# LiteAPI board names -> our canonical board types.
BOARD_MAP = {
    "room only": "room_only",
    "ro": "room_only",
    "bed and breakfast": "breakfast",
    "breakfast": "breakfast",
    "bb": "breakfast",
    "half board": "half_board",
    "full board": "full_board",
    "all inclusive": "all_inclusive",
}


def _first_photo(row: Dict[str, Any]) -> Optional[str]:
    """Best available property photo, or None. LiteAPI uses several
    field names depending on the endpoint."""
    for key in ("main_photo", "mainPhoto", "thumbnail", "image"):
        value = row.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    images = row.get("hotelImages") or row.get("images") or []
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str) and entry.startswith("http"):
                return entry
            if isinstance(entry, dict):
                url = entry.get("url") or entry.get("urlHd")
                if isinstance(url, str) and url.startswith("http"):
                    return url
    return None


class LiteApiProvider:
    supplier = "liteapi"

    def __init__(
        self,
        api_key: Optional[str] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None
            else get_settings().liteapi_key
        )
        self.http = http or HttpJsonClient()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key,
                "accept": "application/json",
                "content-type": "application/json"}

    # ------------------------------------------------------------------
    # Static hotel data
    # ------------------------------------------------------------------

    async def hotels_near(
        self, latitude: float, longitude: float,
        radius_m: int = 15000, limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Properties around a coordinate (static content, cached)."""
        if not self.configured:
            return []

        @api_cache.cached("liteapi:hotels_near", ttl=HOTELS_TTL)
        async def _fetch(lat: float, lon: float, radius: int,
                         count: int) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", f"{BASE_URL}/data/hotels",
                    headers=self._headers(),
                    params={"latitude": lat, "longitude": lon,
                            "radius": radius, "limit": count,
                            # ask for full content so the UI can show
                            # the real name, address and a photo
                            "hotelInfo": "true"},
                )
            except ApiError as exc:
                logger.warning("LiteAPI hotel list failed: %s", exc)
                return None
            return self._parse_hotels(payload)

        hotels = await _fetch(round(latitude, 4), round(longitude, 4),
                              radius_m, limit)
        return hotels or []

    async def hotels_in_city(
        self, city: str, country_code: str, limit: int = 25,
    ) -> List[Dict[str, Any]]:
        if not self.configured or not country_code:
            return []

        @api_cache.cached("liteapi:hotels_city", ttl=HOTELS_TTL)
        async def _fetch(name: str, cc: str,
                         count: int) -> Optional[List[Dict[str, Any]]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", f"{BASE_URL}/data/hotels",
                    headers=self._headers(),
                    params={"cityName": name,
                            "countryCode": cc.upper(),
                            "limit": count},
                )
            except ApiError as exc:
                logger.warning("LiteAPI city hotels failed: %s", exc)
                return None
            return self._parse_hotels(payload)

        hotels = await _fetch(city.strip(), country_code, limit)
        return hotels or []

    @staticmethod
    def _parse_hotels(payload: Any) -> List[Dict[str, Any]]:
        rows = (payload or {}).get("data") or []
        hotels: List[Dict[str, Any]] = []
        for row in rows:
            hotel_id = row.get("id") or row.get("hotelId")
            if not hotel_id:
                continue
            hotels.append({
                "hotel_id": str(hotel_id),
                "name": row.get("name"),
                "address": row.get("address"),
                "city": row.get("city"),
                "country": row.get("country"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "rating": row.get("rating") or row.get("stars"),
                "review_count": row.get("reviewCount"),
                "image": _first_photo(row),
                "source": "liteapi",
            })
        return hotels


    async def hotel_details(
        self, hotel_id: str
    ) -> Optional[Dict[str, Any]]:
        """Full content for one property (images, description, rating).

        The list endpoint often omits photos; this fills them in. Long
        TTL because static content rarely changes.
        """
        if not self.configured or not hotel_id:
            return None

        @api_cache.cached("liteapi:hotel_detail", ttl=HOTELS_TTL)
        async def _fetch(hid: str) -> Optional[Dict[str, Any]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", f"{BASE_URL}/data/hotel",
                    headers=self._headers(),
                    params={"hotelId": hid},
                )
            except ApiError as exc:
                logger.warning("LiteAPI hotel detail failed (%s): %s",
                               hid, exc)
                return None
            data = (payload or {}).get("data") or {}
            if not data:
                return None
            return {
                "hotel_id": hid,
                "name": data.get("name"),
                "address": data.get("address"),
                "city": data.get("city"),
                "country": data.get("country"),
                "rating": data.get("rating") or data.get("starRating"),
                "review_count": data.get("reviewCount"),
                "image": _first_photo(data),
                "description": data.get("hotelDescription"),
            }

        return await _fetch(str(hotel_id))

    async def enrich_photos(
        self, hotels: List[Dict[str, Any]], limit: int = 24,
    ) -> List[Dict[str, Any]]:
        """Fill in missing names/photos for the properties we will
        actually display, a few at a time so we stay polite."""
        if not self.configured:
            return hotels
        missing = [h for h in hotels
                   if not h.get("image") or not h.get("name")][:limit]
        if not missing:
            return hotels

        semaphore = asyncio.Semaphore(6)

        async def _one(entry: Dict[str, Any]) -> None:
            async with semaphore:
                detail = await self.hotel_details(entry["hotel_id"])
            if not detail:
                return
            for key in ("name", "image", "address", "city", "rating",
                        "review_count", "description"):
                if not entry.get(key) and detail.get(key):
                    entry[key] = detail[key]

        await asyncio.gather(*[_one(h) for h in missing])
        filled = sum(1 for h in hotels if h.get("image"))
        logger.info("LiteAPI: %d/%d properties have photos",
                    filled, len(hotels))
        return hotels

    # ------------------------------------------------------------------
    # Live rates
    # ------------------------------------------------------------------

    async def rates(
        self,
        hotel_ids: List[str],
        check_in: str,
        check_out: str,
        guests: int = 2,
        rooms: int = 1,
        currency: str = "EUR",
        guest_nationality: str = "GB",
        hotels: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[NormalizedOffer]:
        """Live rates for specific hotels, normalized.

        Deliberately NOT cached: hotel pricing and availability move
        minute to minute, so every call hits the supplier. Only static
        content (property names, photos) is cached. Each returned offer
        carries retrieved_at/expires_at so the UI can show its age and
        refuse to display an expired quote as if it were current.

        Empty on failure - a missing price is never replaced with an
        estimate.
        """
        if not self.configured or not hotel_ids:
            return []

        body = {
            "hotelIds": hotel_ids[:100],
            "checkin": check_in,
            "checkout": check_out,
            "currency": currency.upper(),
            "guestNationality": guest_nationality.upper(),
            "occupancies": [{"adults": max(1, guests)}
                            for _ in range(max(1, rooms))],
        }
        try:
            payload = await self.http.arequest_json(
                "POST", f"{BASE_URL}/hotels/rates",
                headers=self._headers(), json=body,
            )
        except ApiError as exc:
            logger.warning("LiteAPI rates failed: %s", exc)
            return []

        offers: List[NormalizedOffer] = []
        for row in (payload or {}).get("data") or []:
            offers.extend(self._normalize_hotel(
                row, check_in, check_out, guests, currency,
                hotels or {},
            ))
        return offers

    def _normalize_hotel(
        self, row: Dict[str, Any], check_in: str, check_out: str,
        guests: int, currency: str,
        hotels: Dict[str, Dict[str, Any]],
    ) -> List[NormalizedOffer]:
        hotel_id = str(row.get("hotelId") or row.get("id") or "")
        meta = hotels.get(hotel_id) or {}
        hotel_name = meta.get("name") or row.get("hotelName")
        now = datetime.now(timezone.utc)
        results: List[NormalizedOffer] = []

        for room_type in row.get("roomTypes") or []:
            for rate in room_type.get("rates") or []:
                total, code = self._extract_total(rate, currency)
                if total is None:
                    continue          # no real price -> skip the row
                cancellation = self._cancellation(rate)
                board_raw = (rate.get("boardName")
                             or rate.get("boardType"))
                board = BOARD_MAP.get(
                    str(board_raw).strip().lower() if board_raw else "",
                    normalize_board(board_raw),
                )
                results.append(NormalizedOffer(
                    hotel_id=None,
                    supplier=self.supplier,
                    total_price=total,
                    currency=code,
                    check_in=check_in,
                    check_out=check_out,
                    occupancy=max(1, guests),
                    room_id=hotel_id,
                    room_name=(rate.get("name")
                               or room_type.get("roomTypeName")),
                    hotel_name=hotel_name,
                    hotel_image=meta.get("image"),
                    hotel_rating=meta.get("rating"),
                    hotel_review_count=meta.get("review_count"),
                    hotel_address=meta.get("address"),
                    board_type=board,
                    cancellation_policy=cancellation[1],
                    refundable=cancellation[0],
                    availability=True,
                    deep_link=room_type.get("offerId"),
                    retrieved_at=now,
                    expires_at=now + timedelta(
                        minutes=OFFER_TTL_MINUTES),
                    # LiteAPI retail totals are inclusive of taxes and
                    # fees when 'total' is present.
                    taxes_included=True,
                ))
        return results

    @staticmethod
    def _extract_total(rate: Dict[str, Any],
                       fallback_currency: str) -> tuple:
        """Pull the all-in total out of retailRate. Returns
        ``(amount, currency)`` or ``(None, ...)`` when absent."""
        retail = rate.get("retailRate") or {}
        candidates = retail.get("total") or retail.get("suggestedSellingPrice")
        if isinstance(candidates, list) and candidates:
            entry = candidates[0]
        elif isinstance(candidates, dict):
            entry = candidates
        else:
            entry = None
        if entry is None:
            return None, fallback_currency
        amount = entry.get("amount")
        try:
            return float(amount), (entry.get("currency")
                                   or fallback_currency).upper()
        except (TypeError, ValueError):
            return None, fallback_currency

    @staticmethod
    def _cancellation(rate: Dict[str, Any]) -> tuple:
        """``(refundable, description)``; ``None`` when unstated so the
        comparison engine cannot assume equivalence."""
        policies = rate.get("cancellationPolicies") or {}
        if isinstance(policies, list):
            policies = policies[0] if policies else {}
        refundable_tag = policies.get("refundableTag")
        description = policies.get("cancelPolicyInfos")
        if isinstance(description, list) and description:
            description = description[0].get("cancelTime")
        if refundable_tag is None:
            return None, (description if isinstance(description, str)
                          else None)
        tag = str(refundable_tag).upper()
        if tag in ("RFN", "REFUNDABLE"):
            return True, (description if isinstance(description, str)
                          else None)
        if tag in ("NRFN", "NON_REFUNDABLE", "NRF"):
            return False, (description if isinstance(description, str)
                           else None)
        return None, (description if isinstance(description, str)
                      else None)


liteapi_provider = LiteApiProvider()
