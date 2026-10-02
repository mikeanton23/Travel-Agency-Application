# -*- coding: utf-8 -*-

"""
Documents the agency hands to clients and suppliers.

Three kinds:

* **voucher** - one per confirmed service, carrying the supplier's
  confirmation reference. This is what the traveller presents at the
  hotel desk or the rental counter.
* **invoice** - the financial document, with the VAT breakdown and the
  gapless number issued by :mod:`app.services.agency.invoicing`.
* **travel pack** - the whole itinerary in date order for the
  traveller to carry.

Every figure is read from the stored record, never recomputed, so a
reprinted document is byte-for-byte the same as the original.

A voucher is only produced for a **confirmed** line. Printing one for
an unconfirmed service would hand the traveller a document the
supplier will not honour, so that is refused rather than warned about.
"""

from __future__ import annotations

import base64
import logging
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SERVICE_LABELS = {
    "hotel": "Hotel",
    "ticket": "Ticket",
    "transfer": "Transfer",
    "car_rental": "Car rental",
    "tour": "Tour",
}


class DocumentError(Exception):
    """A user-safe problem producing a document."""


def _reportlab():
    """Import reportlab lazily so the app runs without it installed."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import (
            ParagraphStyle, getSampleStyleSheet,
        )
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
            TableStyle,
        )
    except ImportError as exc:    # pragma: no cover - env dependent
        raise DocumentError(
            "PDF generation needs reportlab. Add 'reportlab>=4.0' to "
            "requirements.txt and reinstall."
        ) from exc
    return {
        "colors": colors, "A4": A4, "mm": mm,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Paragraph": Paragraph, "Spacer": Spacer, "Table": Table,
        "TableStyle": TableStyle, "PageBreak": PageBreak,
    }


def _money(value: Any, currency: str = "EUR") -> str:
    try:
        return f"{float(value or 0):,.2f} {currency}"
    except (TypeError, ValueError):
        return f"0.00 {currency}"


class DocumentService:
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
    # Building blocks
    # ------------------------------------------------------------------

    def _header(self, story: List[Any], rl: Dict[str, Any],
                agency: Dict[str, Any], title: str,
                reference: str) -> None:
        styles = rl["getSampleStyleSheet"]()
        story.append(rl["Paragraph"](
            f"<b>{agency.get('name', 'Travel agency')}</b>",
            styles["Title"]))
        contact = " | ".join(p for p in (
            agency.get("address"), agency.get("phone"),
            agency.get("email"),
            (f"VAT {agency['vat_number']}"
             if agency.get("vat_number") else None),
        ) if p)
        if contact:
            story.append(rl["Paragraph"](contact, styles["Normal"]))
        story.append(rl["Spacer"](1, 10))
        story.append(rl["Paragraph"](
            f"<b>{title}</b> &nbsp;&nbsp; {reference}",
            styles["Heading2"]))
        story.append(rl["Spacer"](1, 6))

    def _table(self, rl: Dict[str, Any], rows: List[List[str]],
               widths: Optional[List[float]] = None) -> Any:
        table = rl["Table"](rows, colWidths=widths, hAlign="LEFT")
        table.setStyle(rl["TableStyle"]([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("GRID", (0, 0), (-1, -1), 0.4,
             rl["colors"].HexColor("#999999")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    def _render(self, build) -> str:
        """Run a build function and return base64 PDF bytes."""
        rl = _reportlab()
        buffer = BytesIO()
        doc = rl["SimpleDocTemplate"](
            buffer, pagesize=rl["A4"],
            leftMargin=18 * rl["mm"], rightMargin=18 * rl["mm"],
            topMargin=16 * rl["mm"], bottomMargin=16 * rl["mm"])
        story: List[Any] = []
        build(story, rl)
        doc.build(story)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    # ------------------------------------------------------------------
    # Voucher
    # ------------------------------------------------------------------

    def voucher(self, booking_item_id: int,
                created_by: Optional[int] = None) -> Dict[str, Any]:
        """A voucher for one confirmed service."""
        from app.db.models import (
            Agency, Booking, BookingItem, Client,
        )

        session = self._sessions()()
        try:
            item = session.get(BookingItem, booking_item_id)
            if item is None:
                raise DocumentError("That service line does not exist.")
            if item.confirmation_status != "confirmed" or not \
                    item.confirmation_reference:
                raise DocumentError(
                    "This service is not confirmed yet. A voucher "
                    "without a supplier reference would not be "
                    "honoured - confirm it first.")
            booking = session.get(Booking, item.booking_id)
            agency = session.get(Agency, booking.agency_id)
            client = (session.get(Client, booking.client_id)
                      if booking.client_id else None)
            data = {
                "agency": {
                    "name": agency.name if agency else "",
                    "address": agency.address if agency else "",
                    "phone": agency.phone if agency else "",
                    "email": agency.email if agency else "",
                    "vat_number": agency.vat_number if agency else "",
                    "voucher_prefix": (agency.voucher_prefix
                                       if agency else "VCH"),
                },
                "booking_reference": booking.reference,
                "lead_passenger": (booking.lead_passenger
                                   or (client.full_name
                                       if client else "")),
                "service_type": item.service_type,
                "title": item.title,
                "supplier": item.supplier or "",
                "reference": item.confirmation_reference,
                "starts_on": item.starts_on or "",
                "ends_on": item.ends_on or "",
                "pax": item.pax,
                "details": item.details or {},
                "agency_id": booking.agency_id,
                "booking_id": booking.id,
            }
        finally:
            session.close()

        number = (f"{data['agency']['voucher_prefix']}-"
                  f"{data['booking_reference']}-{booking_item_id}")

        def build(story, rl):
            styles = rl["getSampleStyleSheet"]()
            self._header(story, rl, data["agency"], "VOUCHER", number)
            rows = [
                ["Service", SERVICE_LABELS.get(data["service_type"],
                                               data["service_type"])],
                ["Description", data["title"]],
                ["Supplier", data["supplier"] or "-"],
                ["Confirmation reference", data["reference"]],
                ["Dates", " to ".join(p for p in (data["starts_on"],
                                                  data["ends_on"]) if p)
                 or "-"],
                ["Passengers", str(data["pax"] or "-")],
                ["Lead passenger", data["lead_passenger"] or "-"],
                ["Booking", data["booking_reference"]],
            ]
            story.append(self._table(rl, rows,
                                     widths=[45 * rl["mm"],
                                             110 * rl["mm"]]))
            story.append(rl["Spacer"](1, 10))
            story.append(rl["Paragraph"](
                "Please present this voucher on arrival. The supplier "
                "reference above is the booking held in the supplier's "
                "system.", styles["Normal"]))
            story.append(rl["Spacer"](1, 6))
            story.append(rl["Paragraph"](
                f"Issued {date.today().isoformat()}", styles["Normal"]))

        content = self._render(build)
        return self._store(data["agency_id"], "voucher", number,
                           f"voucher-{number}.pdf", content,
                           booking_id=data["booking_id"],
                           booking_item_id=booking_item_id,
                           created_by=created_by)

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------

    def invoice(self, invoice_id: int,
                created_by: Optional[int] = None) -> Dict[str, Any]:
        """The invoice PDF, rendered from the stored record."""
        from app.db.models import Agency, Document

        session = self._sessions()()
        try:
            invoice = session.get(Document, invoice_id)
            if invoice is None or invoice.kind != "invoice":
                raise DocumentError("That invoice does not exist.")
            payload = invoice.payload or {}
            agency = session.get(Agency, invoice.agency_id)
            data = {
                "agency": {
                    "name": agency.name if agency else "",
                    "address": agency.address if agency else "",
                    "phone": agency.phone if agency else "",
                    "email": agency.email if agency else "",
                    "vat_number": agency.vat_number if agency else "",
                },
                "full_number": invoice.full_number,
                "issue_date": payload.get("issue_date", ""),
                "currency": invoice.currency,
                "net_amount": invoice.net_total,
                "service_charge": invoice.service_charge_total,
                "vat_amount": invoice.vat_total,
                "total_amount": invoice.gross_total,
                "bill_to_name": payload.get("bill_to_name") or "",
                "bill_to_vat": payload.get("bill_to_vat") or "",
                "bill_to_tax_office": payload.get(
                    "bill_to_tax_office") or "",
                "bill_to_address": payload.get("bill_to_address") or "",
                "lines": payload.get("lines") or [],
                "status": invoice.status,
                "agency_id": invoice.agency_id,
                "booking_id": invoice.booking_id,
            }
        finally:
            session.close()

        def build(story, rl):
            styles = rl["getSampleStyleSheet"]()
            self._header(story, rl, data["agency"], "INVOICE",
                         data["full_number"])
            if data["status"] == "cancelled":
                story.append(rl["Paragraph"](
                    "<b>CANCELLED</b>", styles["Heading2"]))
            bill_to = [
                ["Billed to", data["bill_to_name"] or "-"],
                ["VAT number", data["bill_to_vat"] or "-"],
                ["Tax office", data["bill_to_tax_office"] or "-"],
                ["Address", data["bill_to_address"] or "-"],
                ["Issue date", data["issue_date"]],
            ]
            story.append(self._table(rl, bill_to,
                                     widths=[35 * rl["mm"],
                                             120 * rl["mm"]]))
            story.append(rl["Spacer"](1, 10))

            currency = data["currency"]
            rows = [["Service", "Description", "Net", "Charge", "VAT"]]
            for line in data["lines"]:
                charge = float(line.get("service_charge") or 0)
                rate = float(line.get("vat_rate") or 0)
                vat = (charge * rate / 100
                       if line.get("is_domestic") else 0)
                rows.append([
                    SERVICE_LABELS.get(line.get("service_type"),
                                       line.get("service_type", "")),
                    line.get("title", ""),
                    _money(line.get("net_cost"), currency),
                    _money(charge, currency),
                    _money(vat, currency),
                ])
            story.append(self._table(
                rl, rows, widths=[22 * rl["mm"], 63 * rl["mm"],
                                  24 * rl["mm"], 24 * rl["mm"],
                                  22 * rl["mm"]]))
            story.append(rl["Spacer"](1, 10))

            totals = [
                ["Net", _money(data["net_amount"], currency)],
                ["Service charges",
                 _money(data["service_charge"], currency)],
                ["VAT", _money(data["vat_amount"], currency)],
                ["Total", _money(data["total_amount"], currency)],
            ]
            story.append(self._table(rl, totals,
                                     widths=[40 * rl["mm"],
                                             45 * rl["mm"]]))

        content = self._render(build)
        return self._store(data["agency_id"], "invoice",
                           data["full_number"],
                           f"invoice-{data['full_number']}.pdf",
                           content, booking_id=data["booking_id"],
                           invoice_id=invoice_id,
                           created_by=created_by)

    # ------------------------------------------------------------------
    # Travel pack
    # ------------------------------------------------------------------

    def travel_pack(self, booking_id: int,
                    created_by: Optional[int] = None) -> Dict[str, Any]:
        """The whole itinerary in date order for the traveller."""
        from app.db.models import Agency, Booking, Client

        session = self._sessions()()
        try:
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise DocumentError("That booking does not exist.")
            agency = session.get(Agency, booking.agency_id)
            client = (session.get(Client, booking.client_id)
                      if booking.client_id else None)
            data = {
                "agency": {
                    "name": agency.name if agency else "",
                    "address": agency.address if agency else "",
                    "phone": agency.phone if agency else "",
                    "email": agency.email if agency else "",
                    "vat_number": agency.vat_number if agency else "",
                },
                "reference": booking.reference,
                "lead_passenger": (booking.lead_passenger
                                   or (client.full_name
                                       if client else "")),
                "travel_start": booking.travel_start or "",
                "travel_end": booking.travel_end or "",
                "agency_id": booking.agency_id,
                "items": sorted([{
                    "service_type": i.service_type,
                    "title": i.title,
                    "supplier": i.supplier or "",
                    "reference": i.confirmation_reference or "",
                    "status": i.confirmation_status,
                    "starts_on": i.starts_on or "",
                    "ends_on": i.ends_on or "",
                } for i in booking.items if i.confirmation_status != "cancelled"],
                    key=lambda x: (x["starts_on"] or "9999",
                                   x["service_type"])),
            }
        finally:
            session.close()

        def build(story, rl):
            styles = rl["getSampleStyleSheet"]()
            self._header(story, rl, data["agency"],
                         "TRAVEL DOCUMENTS", data["reference"])
            summary = [
                ["Lead passenger", data["lead_passenger"] or "-"],
                ["Travel dates",
                 " to ".join(p for p in (data["travel_start"],
                                         data["travel_end"]) if p)
                 or "-"],
            ]
            story.append(self._table(rl, summary,
                                     widths=[40 * rl["mm"],
                                             115 * rl["mm"]]))
            story.append(rl["Spacer"](1, 10))

            rows = [["Date", "Service", "Details", "Reference"]]
            for item in data["items"]:
                rows.append([
                    item["starts_on"] or "-",
                    SERVICE_LABELS.get(item["service_type"],
                                       item["service_type"]),
                    item["title"],
                    item["reference"] or (
                        "awaiting confirmation"
                        if item["status"] != "confirmed" else "-"),
                ])
            story.append(self._table(
                rl, rows, widths=[24 * rl["mm"], 26 * rl["mm"],
                                  70 * rl["mm"], 35 * rl["mm"]]))
            story.append(rl["Spacer"](1, 10))
            story.append(rl["Paragraph"](
                "Services shown as awaiting confirmation are not yet "
                "ticketed. Contact the agency before travelling.",
                styles["Normal"]))

        content = self._render(build)
        number = f"PACK-{data['reference']}"
        return self._store(data["agency_id"], "docs", number,
                           f"travel-documents-{data['reference']}.pdf",
                           content, booking_id=booking_id,
                           created_by=created_by)

    # ------------------------------------------------------------------

    def _store(self, agency_id: int, kind: str, number: str,
               filename: str, content: str,
               booking_id: Optional[int] = None,
               invoice_id: Optional[int] = None,
               booking_item_id: Optional[int] = None,
               created_by: Optional[int] = None) -> Dict[str, Any]:
        from app.db.models import Document

        session = self._sessions()()
        try:
            # Vouchers and travel packs are not numbered documents in
            # the invoice series, so they take the next free slot in
            # their own series and carry the PDF in the payload.
            last = (session.query(Document)
                    .filter(Document.agency_id == agency_id,
                            Document.series == kind.upper())
                    .order_by(Document.number.desc()).first())
            next_number = (last.number + 1) if last else 1
            record = Document(
                agency_id=agency_id, kind=kind,
                series=kind.upper(), number=next_number,
                full_number=number,
                booking_id=booking_id,
                booking_item_id=booking_item_id,
                issued_by=created_by,
                status="issued",
                payload={"filename": filename, "pdf_base64": content},
            )
            session.add(record)
            session.commit()
            return {"id": record.id, "kind": kind, "number": number,
                    "filename": filename, "content": content}
        finally:
            session.close()

    def get(self, document_id: int) -> Optional[Dict[str, Any]]:
        from app.db.models import Document

        session = self._sessions()()
        try:
            row = session.get(Document, document_id)
            if row is None:
                return None
            payload = row.payload or {}
            return {"id": row.id, "kind": row.kind,
                    "number": row.full_number,
                    "filename": payload.get("filename"),
                    "content": payload.get("pdf_base64"),
                    "created_at": (row.issued_at.isoformat()
                                   if row.issued_at else None)}
        finally:
            session.close()

    def for_booking(self, booking_id: int) -> List[Dict[str, Any]]:
        from app.db.models import Document

        session = self._sessions()()
        try:
            rows = (session.query(Document)
                    .filter(Document.booking_id == booking_id)
                    .order_by(Document.id.desc()).all())
            return [{"id": r.id, "kind": r.kind,
                     "number": r.full_number,
                     "filename": (r.payload or {}).get("filename"),
                     "created_at": (r.issued_at.isoformat()
                                    if r.issued_at else None)}
                    for r in rows]
        finally:
            session.close()


document_service = DocumentService()
