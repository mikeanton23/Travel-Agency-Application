# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CustomerOffer, EmailLog, HotelOfferRequest
from app.services.email_service import (
    EmailMessageData, EmailService, EmailTransport, valid_email,
)
from app.services.leads import LeadError, LeadService, lead_limiter
from app.services.offer_tokens import (
    OfferTokenService, generate_token, hash_token, tokens_match,
)


class CapturingTransport(EmailTransport):
    name = "capture"

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, message, from_email, from_name):
        if self.fail:
            raise RuntimeError("smtp exploded")
        self.sent.append(message)


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def services(factory, monkeypatch):
    from app.utils import settings as settings_module
    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("SALES_INBOX_EMAIL", "sales@aevyra.example")
    monkeypatch.setenv("APP_BASE_URL", "https://aevyra.example")
    transport = CapturingTransport()
    emailer = EmailService(transport=transport, session_factory=factory)
    lead_limiter.reset("lead:test-ip")
    service = LeadService(session_factory=factory, emailer=emailer)
    yield service, transport, factory
    settings_module.get_settings.cache_clear()


LEAD = {
    "customer_name": "Mike A", "customer_email": "MIKE@Example.com",
    "hotel_name": "Hotel Grande", "destination": "Athens",
    "check_in": "2026-09-01", "check_out": "2026-09-04",
    "competitor_price": 420.0, "currency": "eur",
    "current_provider": "Booking.com", "consent": True,
}


# ---------------------------- validation ----------------------------

def test_email_validation():
    assert valid_email("a@b.co")
    assert not valid_email("nope")
    assert not valid_email("")


def test_lead_requires_name_email_and_consent(services):
    service, _, _ = services
    with pytest.raises(LeadError, match="name"):
        service.create_request({**LEAD, "customer_name": "M"},
                               client_key="test-ip")
    with pytest.raises(LeadError, match="valid email"):
        service.create_request({**LEAD, "customer_email": "bad"},
                               client_key="test-ip")
    with pytest.raises(LeadError, match="contact you"):
        service.create_request({**LEAD, "consent": False},
                               client_key="test-ip")


def test_lead_is_persisted_and_normalised(services):
    service, transport, factory = services
    lead = service.create_request(LEAD, client_key="test-ip")
    session = factory()
    row = session.query(HotelOfferRequest).one()
    session.close()
    assert row.customer_email == "mike@example.com"   # normalised
    assert row.currency == "EUR"
    assert row.status == "new"
    assert row.consent is True
    assert lead["id"] == row.id


def test_both_customer_and_sales_are_notified(services):
    service, transport, _ = services
    service.create_request(LEAD, client_key="test-ip")
    recipients = [m.to_email for m in transport.sent]
    assert "mike@example.com" in recipients
    assert "sales@aevyra.example" in recipients
    customer_mail = next(m for m in transport.sent
                         if m.to_email == "mike@example.com")
    assert "received" in customer_mail.subject.lower()


def test_lead_rate_limited(services):
    service, _, _ = services
    for _ in range(5):
        service.create_request(LEAD, client_key="flood")
    with pytest.raises(LeadError, match="Too many"):
        service.create_request(LEAD, client_key="flood")
    lead_limiter.reset("lead:flood")


# ---------------------------- email logging ----------------------------

def test_email_failures_are_logged_not_swallowed(factory):
    emailer = EmailService(transport=CapturingTransport(fail=True),
                           session_factory=factory)
    result = emailer.send(EmailMessageData(
        to_email="x@y.co", subject="s", text_body="b", kind="test"))
    assert result["success"] is False
    assert "smtp exploded" in result["error"]
    session = factory()
    row = session.query(EmailLog).one()
    session.close()
    assert row.success is False and row.kind == "test"


def test_invalid_recipient_is_rejected_before_sending(factory):
    transport = CapturingTransport()
    emailer = EmailService(transport=transport, session_factory=factory)
    result = emailer.send(EmailMessageData(
        to_email="not-an-email", subject="s", text_body="b"))
    assert result["success"] is False
    assert transport.sent == []


# ---------------------------- offer tokens ----------------------------

def test_tokens_are_random_and_only_hashes_stored():
    t1, h1 = generate_token()
    t2, h2 = generate_token()
    assert t1 != t2 and h1 != h2
    assert len(t1) > 30
    assert tokens_match(t1, h1)
    assert not tokens_match(t2, h1)
    assert t1 not in h1                  # hash reveals nothing


def test_offer_flow_creates_token_and_sends_link(services):
    service, transport, factory = services
    lead = service.create_request(LEAD, client_key="test-ip")
    prepared = service.prepare_offer(
        request_id=lead["id"], our_price=380.0, currency="EUR",
        hotel_name="Hotel Grande", valid_days=3,
        reference_price=420.0,
    )
    assert prepared["token"]

    session = factory()
    offer = session.query(CustomerOffer).one()
    session.close()
    # Raw token must never be persisted.
    assert offer.token_hash == hash_token(prepared["token"])
    assert prepared["token"] not in (offer.token_hash or "")
    assert offer.status == "prepared"

    result = service.send_offer_email(prepared)
    assert result["success"]
    mail = transport.sent[-1]
    assert f"/offer/{prepared['token']}" in mail.text_body
    assert "https://aevyra.example" in mail.text_body

    session = factory()
    offer = session.query(CustomerOffer).one()
    lead_row = session.query(HotelOfferRequest).one()
    session.close()
    assert offer.status == "sent" and offer.sent_at is not None
    assert lead_row.status == "offer_sent"


def test_token_resolution_expiry_and_revocation(services):
    service, _, factory = services
    tokens = OfferTokenService(session_factory=factory)
    lead = service.create_request(LEAD, client_key="test-ip")
    prepared = service.prepare_offer(
        request_id=lead["id"], our_price=380.0, currency="EUR",
        hotel_name="Hotel Grande")

    offer, reason = tokens.resolve(prepared["token"])
    assert reason == "ok" and offer is not None

    assert tokens.resolve("wrong-token-value-000000")[1] == "not_found"

    tokens.mark_opened(prepared["token"])
    session = factory()
    row = session.query(CustomerOffer).one()
    session.close()
    assert row.opened_at is not None

    tokens.revoke(prepared["offer_id"])
    assert tokens.resolve(prepared["token"])[1] == "revoked"


def test_expired_offer_is_not_resolvable(services):
    service, _, factory = services
    tokens = OfferTokenService(session_factory=factory)
    lead = service.create_request(LEAD, client_key="test-ip")
    prepared = service.prepare_offer(
        request_id=lead["id"], our_price=380.0, currency="EUR",
        hotel_name="Hotel Grande")
    session = factory()
    offer = session.query(CustomerOffer).one()
    offer.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.commit()
    session.close()
    assert tokens.resolve(prepared["token"])[1] == "expired"


def test_status_transitions_validated(services):
    service, _, _ = services
    lead = service.create_request(LEAD, client_key="test-ip")
    assert service.set_status(lead["id"], "in_negotiation",
                              note="Called supplier")
    with pytest.raises(LeadError):
        service.set_status(lead["id"], "not_a_status")
    rows = service.list_requests(status="in_negotiation")
    assert rows[0]["id"] == lead["id"]
