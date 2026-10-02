# -*- coding: utf-8 -*-

"""
Invoices.

Greek invoicing requires a continuous, gapless sequence per series and
year. Two rules follow from that and are enforced here rather than
left to discipline:

* A number is handed out under a row lock and never reused, so two
  agents issuing at the same moment cannot collide.
* A cancelled invoice **keeps its number** and is marked cancelled.
  Nothing is deleted, because a missing number in the sequence is
  exactly what an audit looks for.

Totals are copied onto the invoice at issue time. An invoice is a
record of what was agreed; editing the booking afterwards must never
change a document already in the client's hands.

The ``mydata_*`` columns exist so AADE electronic transmission can be
added later without another migration. Transmission itself is not
implemented - it needs the agency's AADE credentials and is a project
of its own.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.pricing import money, price_quote

logger = logging.getLogger(__name__)


class InvoiceError(Exception):
    """A user-safe problem with an invoice."""


class BookingMissing(InvoiceError):
    """The booking an invoice was requested for does not exist."""


class InvoiceService:
    def __init__(
        self, session_factory: Optional[Callable[[], Any]] = None
    ) -> None:
        self._session_factory = session_factory

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    # ------------------------------------------------------------------
    # Numbering
    # ------------------------------------------------------------------

    def _next_number(self, session: Any, agency_id: int,
                     series: str, year: int) -> int:
        """Reserve the next number in the sequence.

        The counter row is locked for update where the database
        supports it, so concurrent issuing cannot hand out the same
        number twice. SQLite ignores the lock but is single-writer
        anyway.
        """
        from app.db.models import InvoiceCounter

        query = (session.query(InvoiceCounter)
                 .filter(InvoiceCounter.agency_id == agency_id,
                         InvoiceCounter.series == series,
                         InvoiceCounter.year == year))
        try:
            counter = query.with_for_update().one_or_none()
        except Exception:
            # Backends without SELECT ... FOR UPDATE.
            counter = query.one_or_none()

        if counter is None:
            counter = InvoiceCounter(agency_id=agency_id,
                                     series=series, year=year,
                                     last_number=0)
            session.add(counter)
            session.flush()
        counter.last_number += 1
        return counter.last_number

    # ------------------------------------------------------------------
    # Issuing
    # ------------------------------------------------------------------

    def issue_for_booking(
        self, booking_id: int, series: Optional[str] = None,
        issue_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Issue an invoice for a booking, numbered in sequence."""
        from app.db.models import Agency, Booking, Client, Document

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise BookingMissing("That booking does not exist.")
            if booking.status == "cancelled":
                raise InvoiceError(
                    "A cancelled booking cannot be invoiced.")

            existing = (session.query(Document)
                        .filter(Document.booking_id == booking_id,
                                Document.kind == "invoice",
                                Document.status != "cancelled")
                        .first())
            if existing is not None:
                raise InvoiceError(
                    f"This booking already has invoice "
                    f"{existing.full_number}.")

            agency = session.get(Agency, booking.agency_id)
            client = (session.get(Client, booking.client_id)
                      if booking.client_id else None)
            series = (series or (agency.invoice_prefix
                                 if agency else "INV") or "INV")
            when = issue_date or date.today().isoformat()
            year = int(when[:4])

            # Price from the booking's own lines, not the quote: the
            # quote may have moved on since the client accepted it.
            lines = [{
                "service_type": item.service_type,
                "title": item.title,
                "net_cost": item.net_cost,
                "service_charge": item.service_charge,
                "quantity": 1,
                "is_domestic": item.is_domestic,
                "vat_rate": item.vat_rate,
                "supplier": item.supplier,
                "confirmation_reference": item.confirmation_reference,
                "starts_on": item.starts_on,
                "ends_on": item.ends_on,
            } for item in booking.items
                if item.confirmation_status != "cancelled"]
            if not lines:
                raise InvoiceError(
                    "Every service on this booking is cancelled; "
                    "there is nothing to invoice.")

            totals = price_quote(lines, currency=booking.currency)
            # The documents table is unique on (agency, series,
            # number), so the year belongs in the series: each year is
            # then its own gapless run and cannot collide with the last.
            series_key = f"{series}-{year}"
            number = self._next_number(session, booking.agency_id,
                                       series, year)
            full_number = f"{series_key}-{number:05d}"

            invoice = Document(
                agency_id=booking.agency_id, booking_id=booking.id,
                client_id=booking.client_id,
                issued_by=booking.agent_id,
                kind="invoice", series=series_key, number=number,
                full_number=full_number,
                currency=booking.currency,
                net_total=float(totals.net_cost),
                service_charge_total=float(totals.service_charge),
                vat_total=float(totals.vat),
                gross_total=float(totals.total),
                status="issued",
                # Snapshot: a later edit to the client or the quote
                # must never rewrite a document already issued.
                payload={
                    "issue_date": when,
                    "year": year,
                    "bill_to_name": (
                        (client.company_name or client.full_name)
                        if client else booking.lead_passenger),
                    "bill_to_vat": (client.vat_number
                                    if client else None),
                    "bill_to_tax_office": (client.tax_office
                                           if client else None),
                    "bill_to_address": (client.address
                                        if client else None),
                    "lines": lines,
                },
            )
            session.add(invoice)
            session.commit()
            return self._as_dict(invoice)
        finally:
            session.close()

    def cancel(self, invoice_id: int, reason: str = "") -> bool:
        """Mark cancelled, keeping the number in the sequence."""
        from app.db.models import Document

        session = self._sessions()()
        try:
            invoice = session.get(Document, invoice_id)
            if invoice is None:
                return False
            invoice.status = "cancelled"
            invoice.cancelled_at = datetime.now(timezone.utc)
            invoice.cancellation_reason = reason or None
            session.commit()
            return True
        finally:
            session.close()

    # ------------------------------------------------------------------

    def get(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        from app.db.models import Document

        session = self._sessions()()
        try:
            invoice = session.get(Document, invoice_id)
            return self._as_dict(invoice) if invoice else None
        finally:
            session.close()

    def list_for(self, agency_id: int, year: Optional[int] = None,
                 limit: int = 200) -> List[Dict[str, Any]]:
        from app.db.models import Document

        session = self._sessions()()
        try:
            query = (session.query(Document)
                     .filter(Document.agency_id == agency_id,
                             Document.kind == "invoice"))
            rows = (query.order_by(Document.series, Document.number)
                    .limit(limit).all())
            return [self._as_dict(row) for row in rows]
        finally:
            session.close()

    def sequence_report(self, agency_id: int, series: str,
                        year: int) -> Dict[str, Any]:
        """Prove the sequence is gapless - what an audit asks for."""
        from app.db.models import Document

        session = self._sessions()()
        try:
            rows = (session.query(Document)
                    .filter(Document.agency_id == agency_id,
                            Document.kind == "invoice",
                            Document.series == f"{series}-{year}")
                    .order_by(Document.number).all())
            numbers = [row.number for row in rows]
        finally:
            session.close()

        expected = list(range(1, len(numbers) + 1))
        missing = sorted(set(expected) - set(numbers)) if numbers else []
        return {
            "series": series, "year": year,
            "issued": len(numbers),
            "first": numbers[0] if numbers else None,
            "last": numbers[-1] if numbers else None,
            "gapless": numbers == expected,
            "missing": missing,
        }

    @staticmethod
    def _as_dict(row: Any) -> Dict[str, Any]:
        payload = row.payload or {}
        return {
            "id": row.id,
            "full_number": row.full_number,
            "series": row.series,
            "year": payload.get("year"),
            "number": row.number,
            "issue_date": payload.get("issue_date"),
            "status": row.status,
            "currency": row.currency,
            "net_amount": row.net_total,
            "service_charge": row.service_charge_total,
            "vat_amount": row.vat_total,
            "total_amount": row.gross_total,
            "bill_to_name": payload.get("bill_to_name"),
            "bill_to_vat": payload.get("bill_to_vat"),
            "bill_to_tax_office": payload.get("bill_to_tax_office"),
            "bill_to_address": payload.get("bill_to_address"),
            "booking_id": row.booking_id,
            "client_id": row.client_id,
            "agent_id": row.issued_by,
            "lines": payload.get("lines") or [],
            "mydata_mark": row.mydata_mark,
            "mydata_status": row.mydata_status,
        }

invoice_service = InvoiceService()
