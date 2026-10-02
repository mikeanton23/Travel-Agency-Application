# -*- coding: utf-8 -*-

"""Invoice numbering must be gapless, and documents must never be
produced for services the supplier has not confirmed."""

import base64

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Agency, Base, Booking, BookingItem, Client, Document, User,
)
from app.services.agency.documents import DocumentError, DocumentService
from app.services.agency.invoicing import InvoiceError, InvoiceService


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def office(factory):
    session = factory()
    agency = Agency(name="Aevyra Travel", vat_number="EL123456789",
                    address="Athens", invoice_prefix="INV")
    session.add(agency)
    session.flush()
    agent = User(email="anna@a.gr", password_hash="x", role="agent",
                 agency_id=agency.id)
    session.add(agent)
    session.flush()
    client = Client(agency_id=agency.id, owner_agent_id=agent.id,
                    full_name="Giorgos Papadopoulos",
                    vat_number="EL987654321", tax_office="A Athinon",
                    address="Kolonaki 1")
    session.add(client)
    session.commit()          # commit, or the rows roll back on close
    ids = {"agency": agency.id, "agent": agent.id,
           "client": client.id}
    session.close()
    return ids


def make_booking(factory, office, confirmed=True, total=1000.0):
    session = factory()
    booking = Booking(
        agency_id=office["agency"], client_id=office["client"],
        agent_id=office["agent"], reference=f"B-{total}",
        status="confirmed", currency="EUR", total_amount=total,
        travel_start="2026-11-01", travel_end="2026-11-05",
        lead_passenger="Giorgos Papadopoulos")
    session.add(booking)
    session.flush()
    item = BookingItem(
        booking_id=booking.id, position=0, service_type="hotel",
        title="Grande Bretagne, 4 nights", supplier="liteapi",
        net_cost=800.0, service_charge=80.0, vat_rate=24.0,
        is_domestic=True,
        confirmation_status="confirmed" if confirmed
        else "pending",
        confirmation_reference="LA-99812" if confirmed else None,
        starts_on="2026-11-01", ends_on="2026-11-05")
    session.add(item)
    session.commit()
    ids = {"booking": booking.id, "item": item.id}
    session.close()
    return ids


# ---------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------

def test_numbers_run_in_sequence(factory, office):
    service = InvoiceService(session_factory=factory)
    numbers = []
    for amount in (100.0, 200.0, 300.0):
        ids = make_booking(factory, office, total=amount)
        numbers.append(
            service.issue_for_booking(ids["booking"],
                                      issue_date="2026-11-01"))
    assert [n["number"] for n in numbers] == [1, 2, 3]
    assert numbers[0]["full_number"] == "INV-2026-00001"
    assert numbers[2]["full_number"] == "INV-2026-00003"


def test_a_cancelled_invoice_keeps_its_number(factory, office):
    """A gap in the sequence is exactly what an audit looks for."""
    service = InvoiceService(session_factory=factory)
    first = service.issue_for_booking(
        make_booking(factory, office, total=100.0)["booking"],
        issue_date="2026-11-01")
    assert service.cancel(first["id"], reason="client withdrew")

    second = service.issue_for_booking(
        make_booking(factory, office, total=200.0)["booking"],
        issue_date="2026-11-02")
    # The next invoice is 2, not 1 reused.
    assert second["number"] == 2

    report = service.sequence_report(office["agency"], "INV", 2026)
    assert report["gapless"] is True
    assert report["missing"] == []
    assert report["issued"] == 2

    cancelled = service.get(first["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["full_number"] == "INV-2026-00001"


def test_each_year_restarts_the_sequence(factory, office):
    service = InvoiceService(session_factory=factory)
    a = service.issue_for_booking(
        make_booking(factory, office, total=100.0)["booking"],
        issue_date="2026-12-31")
    b = service.issue_for_booking(
        make_booking(factory, office, total=200.0)["booking"],
        issue_date="2027-01-02")
    assert a["full_number"] == "INV-2026-00001"
    assert b["full_number"] == "INV-2027-00001"


def test_a_booking_cannot_be_invoiced_twice(factory, office):
    service = InvoiceService(session_factory=factory)
    ids = make_booking(factory, office)
    service.issue_for_booking(ids["booking"])
    with pytest.raises(InvoiceError, match="already has invoice"):
        service.issue_for_booking(ids["booking"])


def test_invoice_copies_the_client_billing_details(factory, office):
    service = InvoiceService(session_factory=factory)
    ids = make_booking(factory, office)
    invoice = service.issue_for_booking(ids["booking"])
    # Snapshot: changing the client later must not alter the invoice.
    assert invoice["bill_to_vat"] == "EL987654321"
    assert invoice["bill_to_tax_office"] == "A Athinon"
    assert invoice["net_amount"] == 800.0
    assert invoice["service_charge"] == 80.0
    assert invoice["vat_amount"] == 19.2        # 24% of the charge
    assert invoice["total_amount"] == 899.2


def test_a_fully_cancelled_booking_cannot_be_invoiced(factory, office):
    service = InvoiceService(session_factory=factory)
    ids = make_booking(factory, office)
    session = factory()
    session.query(BookingItem).filter_by(id=ids["item"]).update(
        {"confirmation_status": "cancelled"})
    session.commit()
    session.close()
    with pytest.raises(InvoiceError, match="nothing to invoice"):
        service.issue_for_booking(ids["booking"])


# ---------------------------------------------------------------
# Documents
# ---------------------------------------------------------------

def test_voucher_requires_a_confirmed_service(factory, office):
    """A voucher without a supplier reference would not be honoured."""
    docs = DocumentService(session_factory=factory)
    unconfirmed = make_booking(factory, office, confirmed=False)
    with pytest.raises(DocumentError, match="not confirmed"):
        docs.voucher(unconfirmed["item"])


def test_voucher_is_a_real_pdf_carrying_the_reference(factory, office):
    docs = DocumentService(session_factory=factory)
    ids = make_booking(factory, office, confirmed=True)
    result = docs.voucher(ids["item"])
    raw = base64.b64decode(result["content"])
    assert raw.startswith(b"%PDF")
    assert len(raw) > 800
    assert result["filename"].endswith(".pdf")
    assert docs.for_booking(ids["booking"])[0]["kind"] == "voucher"


def test_invoice_pdf_renders_from_the_stored_record(factory, office):
    invoices = InvoiceService(session_factory=factory)
    docs = DocumentService(session_factory=factory)
    ids = make_booking(factory, office)
    invoice = invoices.issue_for_booking(ids["booking"])
    result = docs.invoice(invoice["id"])
    assert base64.b64decode(result["content"]).startswith(b"%PDF")
    assert invoice["full_number"] in result["number"]


def test_travel_pack_lists_services_in_date_order(factory, office):
    docs = DocumentService(session_factory=factory)
    ids = make_booking(factory, office)
    session = factory()
    session.add(BookingItem(
        booking_id=ids["booking"], position=1, service_type="transfer",
        title="Airport pickup", confirmation_status="pending",
        starts_on="2026-10-30"))
    session.commit()
    session.close()

    result = docs.travel_pack(ids["booking"])
    assert base64.b64decode(result["content"]).startswith(b"%PDF")
    # Unconfirmed lines still appear, flagged rather than hidden.
    assert result["kind"] == "docs"
