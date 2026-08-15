# -*- coding: utf-8 -*-

"""
Payment orchestration (Stripe Checkout).

Hard rules encoded here:
* We never see, transmit or store card numbers, CVV or expiry. The
  customer is redirected to Stripe's hosted checkout; we hold only the
  provider's session/payment identifiers and a status.
* Webhook payloads are verified with an HMAC-SHA256 signature check
  against ``STRIPE_WEBHOOK_SECRET`` before any state change. Unsigned
  or stale events are rejected.
* Payment status is only advanced by verified provider events, never
  by a browser redirect (which a user can forge by visiting a URL).

The Stripe REST API is called over plain HTTPS via the shared HTTP
client, so no extra dependency is required and the whole flow is
testable offline with a mock transport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from app.utils.http_client import ApiError, HttpJsonClient
from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

STRIPE_API = "https://api.stripe.com/v1"
WEBHOOK_TOLERANCE_S = 300      # reject replayed/stale events

STATUSES = ("pending", "processing", "paid", "failed", "cancelled",
            "expired", "refunded")

# Zero-decimal currencies must not be multiplied by 100.
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
                "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


class PaymentError(Exception):
    """User-safe payment failure."""


def to_minor_units(amount: float, currency: str) -> int:
    """Convert a display amount to the provider's smallest unit."""
    code = (currency or "").upper()
    if code in ZERO_DECIMAL:
        return int(round(amount))
    return int(round(amount * 100))


def verify_stripe_signature(
    payload: bytes, signature_header: str, secret: str,
    now: Optional[float] = None, tolerance: int = WEBHOOK_TOLERANCE_S,
) -> Tuple[bool, str]:
    """Validate a ``Stripe-Signature`` header.

    Returns ``(ok, reason)``. Comparison is constant-time and the
    timestamp is checked to block replays.
    """
    if not secret:
        return False, "webhook secret not configured"
    if not signature_header:
        return False, "missing signature header"

    timestamp = None
    signatures = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        return False, "malformed signature header"

    try:
        event_time = int(timestamp)
    except ValueError:
        return False, "malformed timestamp"

    current = now if now is not None else time.time()
    if abs(current - event_time) > tolerance:
        return False, "timestamp outside tolerance"

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload,
                        hashlib.sha256).hexdigest()
    if any(hmac.compare_digest(expected, candidate)
           for candidate in signatures):
        return True, "ok"
    return False, "signature mismatch"


class PaymentService:
    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self._session_factory = session_factory
        self.http = http or HttpJsonClient()

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    @property
    def configured(self) -> bool:
        return bool(get_settings().stripe_secret_key)

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    async def create_checkout_session(
        self, offer_id: int, customer_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a Stripe Checkout session for a live customer offer.

        The offer must exist, be unexpired and unrevoked -- an expired
        link can never be turned into a payment.
        """
        from app.db.models import CustomerOffer, Payment

        settings = get_settings()
        if not self.configured:
            raise PaymentError(
                "Payments are not configured yet. Add Stripe keys in "
                "Settings to enable checkout."
            )

        session = self._sessions()()
        try:
            offer = session.get(CustomerOffer, offer_id)
            if offer is None:
                raise PaymentError("Offer not found.")
            if offer.revoked_at is not None:
                raise PaymentError("This offer has been withdrawn.")
            expires = offer.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                raise PaymentError("This offer has expired.")
            amount = offer.our_price
            currency = offer.currency
            description = offer.hotel_name
        finally:
            session.close()

        base = settings.app_base_url.rstrip("/")
        form: Dict[str, Any] = {
            "mode": "payment",
            "success_url": f"{base}/pay/success?offer={offer_id}",
            "cancel_url": f"{base}/pay/cancelled?offer={offer_id}",
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]":
                to_minor_units(amount, currency),
            "line_items[0][price_data][product_data][name]": description,
            "client_reference_id": str(offer_id),
            "metadata[offer_id]": str(offer_id),
        }
        if customer_email:
            form["customer_email"] = customer_email

        try:
            payload = await self.http.arequest_json(
                "POST", f"{STRIPE_API}/checkout/sessions",
                headers={
                    "Authorization":
                        f"Bearer {settings.stripe_secret_key}",
                    "Content-Type":
                        "application/x-www-form-urlencoded",
                },
                data=form,
            )
        except ApiError as exc:
            logger.warning("Stripe session creation failed: %s", exc)
            raise PaymentError(
                "We couldn't start the payment. Please try again or "
                "contact us."
            ) from exc

        checkout_url = (payload or {}).get("url")
        provider_session_id = (payload or {}).get("id")
        if not checkout_url:
            raise PaymentError("Payment provider returned no checkout "
                               "URL.")

        session = self._sessions()()
        try:
            record = Payment(
                offer_id=offer_id, provider="stripe",
                provider_session_id=provider_session_id,
                amount=amount, currency=currency, status="pending",
            )
            session.add(record)
            session.commit()
            payment_id = record.id
        finally:
            session.close()

        self._event(offer_id, "checkout_started",
                    f"session={provider_session_id}")
        return {"checkout_url": checkout_url,
                "payment_id": payment_id,
                "provider_session_id": provider_session_id}

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    def handle_webhook(
        self, payload: bytes, signature_header: str,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Verify and apply a Stripe event. Returns a result dict;
        never raises on bad input so the endpoint can answer 400."""
        settings = get_settings()
        ok, reason = verify_stripe_signature(
            payload, signature_header, settings.stripe_webhook_secret,
            now=now,
        )
        if not ok:
            logger.warning("Rejected webhook: %s", reason)
            return {"ok": False, "reason": reason}

        try:
            event = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {"ok": False, "reason": "invalid json"}

        event_type = event.get("type", "")
        obj = (event.get("data") or {}).get("object") or {}
        session_id = obj.get("id")
        offer_id = (obj.get("metadata") or {}).get("offer_id") \
            or obj.get("client_reference_id")

        if event_type == "checkout.session.completed":
            status, failure = "paid", None
        elif event_type in ("checkout.session.expired",):
            status, failure = "expired", None
        elif event_type in ("checkout.session.async_payment_failed",
                            "payment_intent.payment_failed"):
            status = "failed"
            failure = ((obj.get("last_payment_error") or {})
                       .get("message"))
        else:
            return {"ok": True, "ignored": event_type}

        applied = self._apply_status(
            session_id=session_id, offer_id=offer_id, status=status,
            provider_payment_id=obj.get("payment_intent"),
            failure_reason=failure,
        )
        return {"ok": True, "status": status, "applied": applied}

    def _apply_status(
        self, session_id: Optional[str], offer_id: Optional[str],
        status: str, provider_payment_id: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> bool:
        from app.db.models import CustomerOffer, HotelOfferRequest, Payment

        session = self._sessions()()
        try:
            record = None
            if session_id:
                record = (session.query(Payment)
                          .filter(Payment.provider_session_id ==
                                  session_id).one_or_none())
            if record is None and offer_id:
                record = (session.query(Payment)
                          .filter(Payment.offer_id == int(offer_id))
                          .order_by(Payment.id.desc()).first())
            if record is None:
                logger.warning("Webhook for unknown payment "
                               "(session=%s offer=%s)",
                               session_id, offer_id)
                return False
            # Terminal states are not walked backwards by late events.
            if record.status == "paid" and status != "refunded":
                return False

            record.status = status
            if provider_payment_id:
                record.provider_payment_id = provider_payment_id
            if failure_reason:
                record.failure_reason = failure_reason[:500]
            if status == "paid":
                record.paid_at = datetime.now(timezone.utc)
                offer = session.get(CustomerOffer, record.offer_id)
                if offer is not None:
                    offer.status = "paid"
                    lead = session.get(HotelOfferRequest,
                                       offer.request_id)
                    if lead is not None:
                        lead.status = "paid"
            session.commit()
            offer_ref = record.offer_id
        finally:
            session.close()

        self._event(offer_ref,
                    "payment_completed" if status == "paid"
                    else "payment_failed", f"status={status}")
        return True

    # ------------------------------------------------------------------

    def payment_for_offer(self, offer_id: int) -> Optional[Dict[str, Any]]:
        from app.db.models import Payment

        session = self._sessions()()
        try:
            record = (session.query(Payment)
                      .filter(Payment.offer_id == offer_id)
                      .order_by(Payment.id.desc()).first())
            if record is None:
                return None
            return {"id": record.id, "status": record.status,
                    "amount": record.amount, "currency": record.currency,
                    "paid_at": (record.paid_at.isoformat()
                                if record.paid_at else None),
                    "failure_reason": record.failure_reason}
        finally:
            session.close()

    def _event(self, offer_id: Optional[int], event: str,
               detail: str = "") -> None:
        from app.db.models import OfferEvent

        try:
            session = self._sessions()()
            try:
                session.add(OfferEvent(offer_id=offer_id, event=event,
                                       detail=detail))
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("offer_event skipped: %s", exc)


payment_service = PaymentService()
