# -*- coding: utf-8 -*-

"""
Bookings: a quote the client accepted, now being worked.

What this does and does not do, stated plainly because it governs the
whole workflow:

* It does **not** create PNRs or supplier vouchers by itself. A PNR is
  created inside the airline's system and requires IATA accreditation
  plus a GDS contract; a hotel voucher requires a contracted supplier.
  Without those, no code can conjure a confirmation number.
* It **does** model confirmation as a first-class step per line: the
  agent books in the supplier's own system and records the reference
  here, which is what the voucher and the traveller actually need.
* The supplier adapter below is the seam. When a supplier contract
  lands, ``confirm_via_supplier`` takes over for that supplier and the
  agent's workflow does not change.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.pricing import balance_due, money, price_quote

logger = logging.getLogger(__name__)

BOOKING_STATUSES = ("confirmed", "partially_confirmed", "pending",
                    "cancelled", "completed")
CONFIRMATION_STATUSES = ("pending", "requested", "confirmed",
                         "failed", "cancelled")


class BookingError(Exception):
    """A user-safe problem with a booking."""


def new_reference(prefix: str = "B") -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m")
    return f"{prefix}{stamp}-{secrets.token_hex(3).upper()}"


class SupplierAdapter:
    """Where automatic confirmation will plug in, per supplier.

    ``supports`` returns False for every supplier today, so every line
    is confirmed by the agent from the supplier's own system. When a
    contract is signed, implement a subclass for that supplier and the
    booking flow starts confirming automatically with no UI change.
    """

    def supports(self, supplier: Optional[str]) -> bool:
        return False

    def confirm(self, item: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            "No contracted supplier integration is configured. Book in "
            "the supplier's system and record the reference here."
        )


class BookingService:
    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        adapter: Optional[SupplierAdapter] = None,
    ) -> None:
        self._session_factory = session_factory
        self.adapter = adapter or SupplierAdapter()

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    # ------------------------------------------------------------------
    # Creating a booking
    # ------------------------------------------------------------------

    def create_from_quote(self, quote_id: int,
                          lead_passenger: str = "") -> Dict[str, Any]:
        """Copy an accepted quote into a booking.

        The figures are copied, not referenced: editing the quote
        afterwards must never silently change what was sold.
        """
        from app.db.models import Booking, BookingItem, Quote

        session = self._sessions()()
        try:
            quote = session.get(Quote, quote_id)
            if quote is None:
                raise BookingError("That quote does not exist.")
            if not quote.items:
                raise BookingError(
                    "A quote needs at least one service before it can "
                    "be booked.")
            existing = (session.query(Booking)
                        .filter(Booking.quote_id == quote_id)
                        .filter(Booking.status != "cancelled").first())
            if existing is not None:
                raise BookingError(
                    f"This quote is already booked as "
                    f"{existing.reference}.")

            totals = price_quote(
                [{
                    "net_cost": i.net_cost,
                    "service_charge": i.service_charge,
                    "quantity": i.quantity,
                    "is_domestic": i.is_domestic,
                    "vat_rate": i.vat_rate,
                    "service_type": i.service_type,
                } for i in quote.items],
                currency=quote.currency)

            booking = Booking(
                agency_id=quote.agency_id, quote_id=quote.id,
                client_id=quote.client_id, agent_id=quote.agent_id,
                reference=new_reference(),
                status="pending",
                currency=quote.currency,
                travel_start=quote.travel_start,
                travel_end=quote.travel_end,
                lead_passenger=(lead_passenger or "").strip()[:200]
                or None,
                total_amount=float(totals.total),
                paid_amount=0.0,
            )
            session.add(booking)
            session.flush()

            for item in quote.items:
                session.add(BookingItem(
                    booking_id=booking.id, quote_item_id=item.id,
                    position=item.position,
                    service_type=item.service_type,
                    title=item.title, description=item.description,
                    supplier=item.supplier,
                    confirmation_reference=item.supplier_reference,
                    confirmation_status=(
                        "confirmed" if item.supplier_reference
                        else "pending"),
                    starts_on=item.starts_on, ends_on=item.ends_on,
                    quantity=item.quantity, pax=item.pax,
                    net_cost=item.net_cost,
                    service_charge=item.service_charge,
                    vat_rate=item.vat_rate,
                    is_domestic=item.is_domestic,
                    details=item.details,
                ))
            quote.status = "booked"
            session.commit()
            payload = {"id": booking.id,
                       "reference": booking.reference,
                       "total_amount": booking.total_amount}
        finally:
            session.close()

        self._refresh_status(payload["id"])
        return payload

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    def confirm_item(
        self, item_id: int, reference: str,
        agent_id: Optional[int] = None,
        supplier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record the supplier's confirmation for one line.

        ``reference`` is the PNR, voucher number or confirmation code
        the supplier issued. It is required: a line is not confirmed
        without something the traveller can quote at the desk.
        """
        from app.db.models import BookingItem

        reference = (reference or "").strip()
        if not reference:
            raise BookingError(
                "Enter the supplier's reference (PNR, voucher or "
                "confirmation number) to confirm this service.")

        session = self._sessions()()
        try:
            item = session.get(BookingItem, item_id)
            if item is None:
                raise BookingError("That service line does not exist.")
            item.confirmation_reference = reference[:120]
            item.confirmation_status = "confirmed"
            item.confirmed_at = datetime.now(timezone.utc)
            item.confirmed_by = agent_id
            if supplier:
                item.supplier = supplier[:120]
            booking_id = item.booking_id
            session.commit()
        finally:
            session.close()

        self._refresh_status(booking_id)
        return {"item_id": item_id, "reference": reference,
                "status": "confirmed"}

    def confirm_via_supplier(self, item_id: int) -> Dict[str, Any]:
        """Attempt automatic confirmation; refuse clearly if we cannot.

        Today this always reports that no contracted integration
        exists, rather than pretending to book.
        """
        from app.db.models import BookingItem

        session = self._sessions()()
        try:
            item = session.get(BookingItem, item_id)
            if item is None:
                raise BookingError("That service line does not exist.")
            supplier = item.supplier
            payload = {"id": item.id, "supplier": supplier,
                       "service_type": item.service_type}
        finally:
            session.close()

        if not self.adapter.supports(supplier):
            raise BookingError(
                f"No contracted integration for "
                f"{supplier or 'this supplier'}. Book it in the "
                f"supplier's system and record the reference here.")
        result = self.adapter.confirm(payload)
        return self.confirm_item(item_id, result.get("reference", ""),
                                 supplier=supplier)

    def set_item_status(self, item_id: int, status: str) -> bool:
        from app.db.models import BookingItem

        status = (status or "").strip().lower()
        if status not in CONFIRMATION_STATUSES:
            raise BookingError(f"Unknown status '{status}'.")
        session = self._sessions()()
        try:
            item = session.get(BookingItem, item_id)
            if item is None:
                return False
            item.confirmation_status = status
            booking_id = item.booking_id
            session.commit()
        finally:
            session.close()
        self._refresh_status(booking_id)
        return True

    def _refresh_status(self, booking_id: int) -> None:
        """Booking status follows its lines, so it cannot drift."""
        from app.db.models import Booking, BookingItem

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None or booking.status == "cancelled":
                return
            items = (session.query(BookingItem)
                     .filter(BookingItem.booking_id == booking_id)
                     .all())
            if not items:
                return
            states = {i.confirmation_status for i in items}
            if states == {"confirmed"}:
                booking.status = "confirmed"
            elif "confirmed" in states:
                booking.status = "partially_confirmed"
            else:
                booking.status = "pending"
            session.commit()
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Money and cancellation
    # ------------------------------------------------------------------

    def record_payment(
        self, booking_id: int, amount: Any, method: str,
        agent_id: Optional[int] = None, reference: Optional[str] = None,
        cash_service: Any = None,
    ) -> Dict[str, Any]:
        """Take a payment and post it to the office cash account."""
        from app.db.models import Booking
        from app.services.agency.cash import CashService

        cash = cash_service or CashService(self._session_factory)
        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise BookingError("That booking does not exist.")
            agency_id = booking.agency_id
            client_id = booking.client_id
            quote_id = booking.quote_id
            currency = booking.currency
        finally:
            session.close()

        account_id = cash.ensure_account(agency_id, currency)
        movement = cash.record(
            account_id, amount, method, agent_id=agent_id,
            client_id=client_id, quote_id=quote_id,
            reference=reference,
            description=f"Payment for booking {booking_id}",
            currency=currency)

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            booking.paid_amount = float(
                money(booking.paid_amount) + money(amount))
            paid = booking.paid_amount
            total = booking.total_amount
            session.commit()
        finally:
            session.close()

        return {"movement": movement, "paid": paid,
                "balance_due": float(balance_due(total, paid))}

    def cancel(self, booking_id: int, reason: str = "") -> bool:
        from app.db.models import Booking, BookingItem

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None:
                return False
            booking.status = "cancelled"
            booking.cancelled_at = datetime.now(timezone.utc)
            booking.cancellation_reason = reason or None
            (session.query(BookingItem)
             .filter(BookingItem.booking_id == booking_id)
             .update({"confirmation_status": "cancelled"}))
            session.commit()
            return True
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get(self, booking_id: int) -> Optional[Dict[str, Any]]:
        from app.db.models import Booking

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None:
                return None
            items = [{
                "id": i.id, "position": i.position,
                "service_type": i.service_type, "title": i.title,
                "description": i.description, "supplier": i.supplier,
                "confirmation_reference": i.confirmation_reference,
                "confirmation_status": i.confirmation_status,
                "starts_on": i.starts_on, "ends_on": i.ends_on,
                "quantity": i.quantity, "pax": i.pax,
                "net_cost": i.net_cost,
                "service_charge": i.service_charge,
                "vat_rate": i.vat_rate, "is_domestic": i.is_domestic,
                "details": i.details,
            } for i in booking.items]
            payload = {
                "id": booking.id, "reference": booking.reference,
                "status": booking.status,
                "agency_id": booking.agency_id,
                "client_id": booking.client_id,
                "agent_id": booking.agent_id,
                "quote_id": booking.quote_id,
                "currency": booking.currency,
                "travel_start": booking.travel_start,
                "travel_end": booking.travel_end,
                "lead_passenger": booking.lead_passenger,
                "total_amount": booking.total_amount,
                "paid_amount": booking.paid_amount,
                "balance_due": float(balance_due(booking.total_amount,
                                                 booking.paid_amount)),
                "items": items,
            }
            return payload
        finally:
            session.close()

    def list_for(self, agency_id: int, agent_id: Optional[int] = None,
                 status: Optional[str] = None,
                 limit: int = 100) -> List[Dict[str, Any]]:
        from app.db.models import Booking

        session = self._sessions()()
        try:
            query = (session.query(Booking)
                     .filter(Booking.agency_id == agency_id))
            if agent_id is not None:
                query = query.filter(Booking.agent_id == agent_id)
            if status:
                query = query.filter(Booking.status == status)
            rows = query.order_by(Booking.id.desc()).limit(limit).all()
            return [{
                "id": b.id, "reference": b.reference,
                "status": b.status, "client_id": b.client_id,
                "agent_id": b.agent_id, "currency": b.currency,
                "travel_start": b.travel_start,
                "lead_passenger": b.lead_passenger,
                "total_amount": b.total_amount,
                "paid_amount": b.paid_amount,
                "balance_due": float(balance_due(b.total_amount,
                                                 b.paid_amount)),
                "created_at": (b.created_at.isoformat()
                               if b.created_at else None),
            } for b in rows]
        finally:
            session.close()


booking_service = BookingService()
