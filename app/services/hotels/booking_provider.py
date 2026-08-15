# -*- coding: utf-8 -*-

"""
Booking.com Demand API v3.2 client.

Docs: https://developers.booking.com/demand/docs/open-api/3.2/demand-api

Shape of the API (differs from Amadeus in every respect):
* Every endpoint is **POST** with a JSON body -- there are no query
  strings.
* Auth is a bearer token plus an affiliate identifier header.
* Two environments:
    production https://demandapi.booking.com/3.2
    sandbox    https://demandapi-sandbox.booking.com/3.2

Endpoints used here:
    POST /accommodations/search        find properties + cheapest product
    POST /accommodations/availability  real-time prices for <=50 ids
    POST /accommodations/details       static content (names, address)
    POST /common/locations/cities      resolve a city name to a city id

Credentials require Affiliate Partner approval; without them the client
reports itself unconfigured and the platform shows "not configured"
rather than inventing anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services.cache_service import api_cache
from app.services.hotels.offers import NormalizedOffer, normalize_board
from app.utils.http_client import ApiError, HttpJsonClient
from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

CITY_TTL = 30 * 86400
SEARCH_TTL = 900
OFFER_TTL_MINUTES = 30

PRODUCTION_URL = "https://demandapi.booking.com/3.2"
SANDBOX_URL = "https://demandapi-sandbox.booking.com/3.2"

# Booking.com meal-plan wording -> our canonical board types.
BOARD_MAP = {
    "room_only": "room_only",
    "breakfast_included": "breakfast",
    "breakfast": "breakfast",
    "half_board": "half_board",
    "full_board": "full_board",
    "all_inclusive": "all_inclusive",
}


class BookingProvider:
    """Async client for the Demand API."""

    supplier = "booking"

    def __init__(
        self,
        affiliate_id: Optional[str] = None,
        token: Optional[str] = None,
        environment: Optional[str] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        settings = get_settings()
        self.affiliate_id = (
            affiliate_id if affiliate_id is not None
            else settings.booking_affiliate_id
        )
        self.token = (
            token if token is not None else settings.booking_api_token
        )
        env = (environment or settings.booking_env or "sandbox").lower()
        self.base_url = (PRODUCTION_URL if env == "production"
                         else SANDBOX_URL)
        self.http = http or HttpJsonClient()

    @property
    def configured(self) -> bool:
        return bool(self.affiliate_id and self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Affiliate-Id": str(self.affiliate_id),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _post(self, path: str, body: Dict[str, Any]) -> Any:
        return await self.http.arequest_json(
            "POST", f"{self.base_url}{path}",
            headers=self._headers(), json=body,
        )

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    async def resolve_city_id(
        self, city: str, country_code: Optional[str] = None
    ) -> Optional[int]:
        """City name -> Booking.com city id (used by other endpoints)."""
        if not self.configured or not city:
            return None

        @api_cache.cached("booking:city", ttl=CITY_TTL)
        async def _lookup(name: str, cc: Optional[str]) -> Optional[int]:
            body: Dict[str, Any] = {"languages": ["en-gb"]}
            if cc:
                body["country"] = cc.lower()
            try:
                payload = await self._post(
                    "/common/locations/cities", body)
            except ApiError as exc:
                logger.warning("Booking city lookup failed: %s", exc)
                return None
            target = name.strip().lower()
            for entry in (payload or {}).get("data", []):
                names = entry.get("name") or {}
                candidates = (
                    list(names.values()) if isinstance(names, dict)
                    else [names]
                )
                if any(str(c).strip().lower() == target
                       for c in candidates):
                    return entry.get("id")
            return None

        return await _lookup(city, country_code)

    # ------------------------------------------------------------------
    # Search + availability
    # ------------------------------------------------------------------

    async def search(
        self,
        check_in: str,
        check_out: str,
        city_id: Optional[int] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: int = 10,
        guests: int = 2,
        rooms: int = 1,
        currency: str = "EUR",
        country_of_residence: str = "nl",
        max_results: int = 20,
    ) -> List[NormalizedOffer]:
        """Search accommodations and return normalized real offers.

        Returns an empty list when unconfigured or when the API fails --
        the caller renders an explicit unavailable state.
        """
        if not self.configured:
            return []

        booker = {"country": country_of_residence,
                  "platform": "desktop"}
        body: Dict[str, Any] = {
            "booker": booker,
            "checkin": check_in,
            "checkout": check_out,
            "currency": currency.upper(),
            "guests": {"number_of_rooms": max(1, rooms),
                       "number_of_adults": max(1, guests)},
            "rows": max_results,
            "extras": ["extra_charges"],
        }
        if city_id is not None:
            body["city"] = city_id
        elif latitude is not None and longitude is not None:
            body["coordinates"] = {"latitude": latitude,
                                   "longitude": longitude,
                                   "radius": radius_km}
        else:
            return []

        try:
            payload = await self._post("/accommodations/search", body)
        except ApiError as exc:
            logger.warning("Booking search failed: %s", exc)
            return []

        rows = (payload or {}).get("data") or []
        if not rows:
            return []

        names = await self._names_for(
            [r.get("id") for r in rows if r.get("id")]
        )
        offers: List[NormalizedOffer] = []
        for row in rows:
            offer = self._normalize(row, check_in, check_out, guests,
                                    currency, names)
            if offer is not None:
                offers.append(offer)
        return offers

    async def availability(
        self,
        accommodation_ids: List[int],
        check_in: str,
        check_out: str,
        guests: int = 2,
        rooms: int = 1,
        currency: str = "EUR",
        country_of_residence: str = "nl",
    ) -> List[NormalizedOffer]:
        """Real-time prices for specific properties (max 50 per call)."""
        if not self.configured or not accommodation_ids:
            return []
        results: List[NormalizedOffer] = []
        names = await self._names_for(accommodation_ids)
        for chunk_start in range(0, len(accommodation_ids), 50):
            chunk = accommodation_ids[chunk_start:chunk_start + 50]
            body = {
                "accommodations": chunk,
                "booker": {"country": country_of_residence,
                           "platform": "desktop"},
                "checkin": check_in,
                "checkout": check_out,
                "currency": currency.upper(),
                "guests": {"number_of_rooms": max(1, rooms),
                           "number_of_adults": max(1, guests)},
            }
            try:
                payload = await self._post(
                    "/accommodations/availability", body)
            except ApiError as exc:
                logger.warning("Booking availability failed: %s", exc)
                continue
            for row in (payload or {}).get("data") or []:
                offer = self._normalize(row, check_in, check_out,
                                        guests, currency, names)
                if offer is not None:
                    results.append(offer)
        return results

    async def _names_for(
        self, accommodation_ids: List[int]
    ) -> Dict[int, str]:
        """Static property names for the ids we are about to display."""
        ids = [i for i in accommodation_ids if i][:100]
        if not ids:
            return {}
        try:
            payload = await self._post("/accommodations/details", {
                "accommodations": ids,
                "languages": ["en-gb"],
                "extras": [],
            })
        except ApiError as exc:
            logger.warning("Booking details failed: %s", exc)
            return {}
        names: Dict[int, str] = {}
        for entry in (payload or {}).get("data") or []:
            entry_id = entry.get("id")
            raw_name = entry.get("name")
            if isinstance(raw_name, dict):
                raw_name = (raw_name.get("en-gb")
                            or next(iter(raw_name.values()), None))
            if entry_id and raw_name:
                names[entry_id] = raw_name
        return names

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(
        self, row: Dict[str, Any], check_in: str, check_out: str,
        guests: int, currency: str, names: Dict[int, str],
    ) -> Optional[NormalizedOffer]:
        """Map one accommodation row to a NormalizedOffer.

        Returns ``None`` when no real all-in price is present -- a
        missing price is never substituted.
        """
        accommodation_id = row.get("id")
        products = row.get("products") or []
        if not products:
            return None
        product = products[0]

        price_block = (product.get("price") or {})
        total = (price_block.get("total")
                 or price_block.get("book") or {})
        amount = total.get("amount") if isinstance(total, dict) else total
        if amount is None:
            amount = price_block.get("amount")
        try:
            total_price = float(amount)
        except (TypeError, ValueError):
            return None

        currency_code = (
            (total.get("currency") if isinstance(total, dict) else None)
            or price_block.get("currency") or currency
        ).upper()

        charges = price_block.get("extra_charges") or []
        taxes = sum(
            float(c.get("amount", 0) or 0) for c in charges
            if str(c.get("type", "")).lower() in ("tax", "vat",
                                                  "city_tax")
        ) or None
        fees = sum(
            float(c.get("amount", 0) or 0) for c in charges
            if str(c.get("type", "")).lower() in ("fee",
                                                  "service_charge")
        ) or None
        # Booking totals are all-in only when extra charges are
        # included in the total; otherwise flag it so the comparison
        # engine refuses to treat it as like-for-like.
        excluded = any(
            not c.get("included_in_price", True) for c in charges
        )

        policies = product.get("policies") or {}
        cancellation = policies.get("cancellation") or {}
        refundable = cancellation.get("free_cancellation")
        if refundable is None:
            refundable = product.get("refundable")

        board = product.get("meal_plan") or product.get("board")
        if isinstance(board, dict):
            board = board.get("type") or board.get("name")
        board_type = BOARD_MAP.get(
            str(board).strip().lower().replace(" ", "_")
            if board else "", normalize_board(board),
        )

        now = datetime.now(timezone.utc)
        return NormalizedOffer(
            hotel_id=None,
            supplier=self.supplier,
            total_price=total_price,
            currency=currency_code,
            check_in=check_in,
            check_out=check_out,
            occupancy=max(1, guests),
            room_id=str(product.get("id") or ""),
            room_name=(product.get("name")
                       or names.get(accommodation_id)
                       or product.get("room_name")),
            board_type=board_type,
            taxes=taxes,
            fees=fees,
            cancellation_policy=cancellation.get("description"),
            refundable=refundable,
            availability=bool(row.get("available", True)),
            deep_link=row.get("url") or product.get("url"),
            retrieved_at=now,
            expires_at=now + timedelta(minutes=OFFER_TTL_MINUTES),
            taxes_included=not excluded,
        )


booking_provider = BookingProvider()
