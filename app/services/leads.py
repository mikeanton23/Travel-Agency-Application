# -*- coding: utf-8 -*-

"""
Lead capture and the customer-offer pipeline.

Covers: validating and persisting a "beat this price" request,
notifying both customer and sales inbox, staff preparing an offer with
a secure token, sending it, and recording funnel events.

A competitor price supplied by the customer is stored as
``source_type="customer_reported"`` -- it is evidence for the sales
team, never grounds for a public "cheaper than X" claim.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.email_service import (
    EmailMessageData, email_service, valid_email,
)
from app.services.offer_tokens import generate_token
from app.utils.rate_limit import RateLimiter
from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

lead_limiter = RateLimiter()
LEAD_LIMIT = 5
LEAD_WINDOW_S = 3600.0

STATUSES = [
    "new", "pending", "in_negotiation", "offer_prepared", "offer_sent",
    "offer_opened", "payment_pending", "paid", "expired", "cancelled",
    "rejected",
]


class LeadError(Exception):
    """User-safe validation/rate-limit message."""


def session_hash(raw: str) -> str:
    """Salted, truncated hash -- analytics without storing identities."""
    salt = get_settings().app_secret_key or "aevyra"
    return hashlib.sha256(
        f"{salt}:{raw}".encode("utf-8")
    ).hexdigest()[:32]


class LeadService:
    def __init__(
        self, session_factory: Optional[Callable[[], Any]] = None,
        emailer=None,
    ) -> None:
        self._session_factory = session_factory
        self._emailer = emailer or email_service

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    # ------------------------------------------------------------------
    # Customer side
    # ------------------------------------------------------------------

    def create_request(
        self, data: Dict[str, Any], client_key: str = "unknown"
    ) -> Dict[str, Any]:
        """Validate, persist, and notify. Returns the created lead."""
        from app.db.models import HotelOfferRequest

        name = (data.get("customer_name") or "").strip()
        email = (data.get("customer_email") or "").strip().lower()
        if len(name) < 2:
            raise LeadError("Please enter your name.")
        if not valid_email(email):
            raise LeadError("Please enter a valid email address.")
        if not data.get("consent"):
            raise LeadError(
                "Please confirm we may contact you about this request."
            )
        allowed, retry_after = lead_limiter.allow(
            f"lead:{client_key}", LEAD_LIMIT, LEAD_WINDOW_S
        )
        if not allowed:
            raise LeadError(
                f"Too many requests -- please try again in "
                f"{retry_after / 60:.0f} minutes."
            )

        session = self._sessions()()
        try:
            lead = HotelOfferRequest(
                customer_name=name[:160],
                customer_email=email[:255],
                customer_phone=(data.get("customer_phone") or "")[:60]
                or None,
                destination=(data.get("destination") or "")[:160] or None,
                hotel_id=data.get("hotel_id"),
                hotel_name=(data.get("hotel_name") or "")[:200] or None,
                check_in=data.get("check_in"),
                check_out=data.get("check_out"),
                guests=int(data.get("guests") or 2),
                rooms=int(data.get("rooms") or 1),
                room_type=(data.get("room_type") or "")[:200] or None,
                meal_plan=data.get("meal_plan"),
                current_provider=(data.get("current_provider") or "")[:80]
                or None,
                competitor_price=data.get("competitor_price"),
                currency=(data.get("currency") or "EUR")[:3].upper(),
                competitor_url=data.get("competitor_url"),
                customer_message=data.get("customer_message"),
                consent=True,
                status="new",
                source_page=(data.get("source_page") or "")[:250] or None,
            )
            session.add(lead)
            session.commit()
            payload = {
                "id": lead.id,
                "customer_name": lead.customer_name,
                "customer_email": lead.customer_email,
                "hotel_name": lead.hotel_name,
                "destination": lead.destination,
                "check_in": lead.check_in,
                "check_out": lead.check_out,
                "status": lead.status,
            }
        finally:
            session.close()

        self._record_event(request_id=payload["id"],
                           event="offer_request_created")
        self._notify_new_request(payload)
        return payload

    def _notify_new_request(self, lead: Dict[str, Any]) -> None:
        stay = ""
        if lead.get("check_in") and lead.get("check_out"):
            stay = f"\nDates: {lead['check_in']} -> {lead['check_out']}"
        subject_where = lead.get("hotel_name") or \
            lead.get("destination") or "your stay"

        self._emailer.send(EmailMessageData(
            to_email=lead["customer_email"],
            subject=f"We received your offer request -- {subject_where}",
            kind="request_received",
            request_id=lead["id"],
            text_body=(
                f"Hi {lead['customer_name']},\n\n"
                f"Thanks -- we've received your request for "
                f"{subject_where}.{stay}\n\n"
                "Our travel team will check direct and partner rates "
                "and get back to you. If we can't beat the price you "
                "found, we'll tell you that plainly rather than waste "
                "your time.\n\n"
                f"Reference: #{lead['id']}\n\n"
                f"{get_settings().site_name}"
            ),
        ))

        sales_inbox = get_settings().sales_inbox_email
        if sales_inbox:
            self._emailer.send(EmailMessageData(
                to_email=sales_inbox,
                subject=f"New hotel offer request #{lead['id']} -- "
                        f"{subject_where}",
                kind="request_internal",
                request_id=lead["id"],
                text_body=(
                    f"New request #{lead['id']}\n"
                    f"Customer: {lead['customer_name']} "
                    f"<{lead['customer_email']}>\n"
                    f"Hotel: {lead.get('hotel_name') or '--'}\n"
                    f"Destination: {lead.get('destination') or '--'}"
                    f"{stay}\n\n"
                    "Open the admin dashboard to prepare an offer."
                ),
            ))

    # ------------------------------------------------------------------
    # Staff side
    # ------------------------------------------------------------------

    def prepare_offer(
        self, request_id: int, our_price: float, currency: str,
        hotel_name: str, valid_days: int = 3,
        reference_price: Optional[float] = None,
        room_description: Optional[str] = None,
        board_type: Optional[str] = None,
        conditions: Optional[str] = None,
        cancellation_policy: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create an offer and return it with the one-time token.

        The plaintext token is returned exactly once (to be emailed);
        only its hash is stored.
        """
        from app.db.models import CustomerOffer, HotelOfferRequest

        if our_price is None or our_price <= 0:
            raise LeadError("Offer price must be greater than zero.")
        token, token_hash = generate_token()
        session = self._sessions()()
        try:
            lead = session.get(HotelOfferRequest, request_id)
            if lead is None:
                raise LeadError("Request not found.")
            offer = CustomerOffer(
                request_id=request_id,
                token_hash=token_hash,
                hotel_name=hotel_name[:200],
                room_description=room_description,
                board_type=board_type,
                check_in=lead.check_in,
                check_out=lead.check_out,
                guests=lead.guests,
                rooms=lead.rooms,
                conditions=conditions,
                cancellation_policy=cancellation_policy,
                reference_price=reference_price,
                our_price=float(our_price),
                currency=currency.upper()[:3],
                status="prepared",
                created_by=created_by,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=valid_days),
            )
            session.add(offer)
            lead.status = "offer_prepared"
            session.commit()
            payload = {
                "offer_id": offer.id,
                "request_id": request_id,
                "token": token,          # shown once, never stored raw
                "our_price": offer.our_price,
                "currency": offer.currency,
                "expires_at": offer.expires_at,
                "customer_email": lead.customer_email,
                "customer_name": lead.customer_name,
                "hotel_name": offer.hotel_name,
            }
        finally:
            session.close()
        self._record_event(offer_id=payload["offer_id"],
                           request_id=request_id, event="offer_created")
        return payload

    def send_offer_email(self, prepared: Dict[str, Any]) -> Dict[str, Any]:
        """Email the secure offer link. Requires the plaintext token
        from :meth:`prepare_offer` -- it cannot be recovered later."""
        from app.db.models import CustomerOffer, HotelOfferRequest

        settings = get_settings()
        link = (f"{settings.app_base_url.rstrip('/')}"
                f"/offer/{prepared['token']}")
        expires = prepared["expires_at"]
        result = self._emailer.send(EmailMessageData(
            to_email=prepared["customer_email"],
            subject=f"Your personalised offer -- {prepared['hotel_name']}",
            kind="offer_sent",
            request_id=prepared["request_id"],
            offer_id=prepared["offer_id"],
            text_body=(
                f"Hi {prepared['customer_name']},\n\n"
                f"Your offer for {prepared['hotel_name']} is ready:\n"
                f"{prepared['our_price']:.2f} {prepared['currency']}\n\n"
                f"View the full conditions and confirm here:\n{link}\n\n"
                f"This link is personal to you and expires on "
                f"{expires.date().isoformat()}.\n\n"
                f"{settings.site_name}"
            ),
        ))
        if result["success"]:
            session = self._sessions()()
            try:
                offer = session.get(CustomerOffer, prepared["offer_id"])
                if offer is not None:
                    offer.status = "sent"
                    offer.sent_at = datetime.now(timezone.utc)
                lead = session.get(HotelOfferRequest,
                                   prepared["request_id"])
                if lead is not None:
                    lead.status = "offer_sent"
                session.commit()
            finally:
                session.close()
            self._record_event(offer_id=prepared["offer_id"],
                               request_id=prepared["request_id"],
                               event="offer_email_sent")
        return result

    def set_status(self, request_id: int, status: str,
                   note: Optional[str] = None) -> bool:
        from app.db.models import HotelOfferRequest

        if status not in STATUSES:
            raise LeadError(f"Unknown status '{status}'.")
        session = self._sessions()()
        try:
            lead = session.get(HotelOfferRequest, request_id)
            if lead is None:
                return False
            lead.status = status
            if note:
                existing = lead.internal_notes or ""
                stamp = datetime.now(timezone.utc).isoformat(
                    timespec="minutes")
                lead.internal_notes = f"{existing}\n[{stamp}] {note}".strip()
            session.commit()
            return True
        finally:
            session.close()

    def list_requests(
        self, status: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        from app.db.models import HotelOfferRequest

        session = self._sessions()()
        try:
            query = session.query(HotelOfferRequest)
            if status:
                query = query.filter(HotelOfferRequest.status == status)
            rows = (query.order_by(HotelOfferRequest.id.desc())
                    .limit(limit).all())
            return [{
                "id": r.id,
                "customer_name": r.customer_name,
                "customer_email": r.customer_email,
                "hotel_name": r.hotel_name,
                "destination": r.destination,
                "check_in": r.check_in,
                "check_out": r.check_out,
                "competitor_price": r.competitor_price,
                "currency": r.currency,
                "status": r.status,
                "created_at": (r.created_at.isoformat()
                               if r.created_at else None),
            } for r in rows]
        finally:
            session.close()

    # ------------------------------------------------------------------

    def _record_event(self, event: str, request_id: Optional[int] = None,
                      offer_id: Optional[int] = None,
                      detail: Optional[str] = None) -> None:
        from app.db.models import OfferEvent

        try:
            session = self._sessions()()
            try:
                session.add(OfferEvent(offer_id=offer_id,
                                       request_id=request_id,
                                       event=event, detail=detail))
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("offer_event skipped: %s", exc)


lead_service = LeadService()
