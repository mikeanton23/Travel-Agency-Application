# -*- coding: utf-8 -*-

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base, CustomerOffer, HotelOfferRequest, Payment,
)
from app.services.payments import (
    PaymentError, PaymentService, to_minor_units,
    verify_stripe_signature,
)
from app.utils.http_client import HttpJsonClient, RetryPolicy

SECRET = "whsec_test_secret"


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from app.utils import settings as settings_module
    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("APP_BASE_URL", "https://aevyra.example")
    yield
    settings_module.get_settings.cache_clear()


def make_offer(factory, price=380.0, expired=False, revoked=False):
    session = factory()
    lead = HotelOfferRequest(customer_name="M", customer_email="m@e.co",
                             consent=True, status="offer_sent")
    session.add(lead)
    session.flush()
    # token_hash is unique per offer; a fixed value collides as soon
    # as a test creates a second offer.
    import secrets as _secrets
    offer = CustomerOffer(
        request_id=lead.id, token_hash=_secrets.token_hex(32),
        hotel_name="Hotel Grande", our_price=price, currency="EUR",
        status="sent",
        expires_at=datetime.now(timezone.utc)
        + (timedelta(hours=-1) if expired else timedelta(days=2)),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    session.add(offer)
    session.commit()
    offer_id = offer.id
    session.close()
    return offer_id


def sign(payload: bytes, secret=SECRET, timestamp=None) -> str:
    ts = str(int(timestamp or time.time()))
    signature = hmac.new(secret.encode(), f"{ts}.".encode() + payload,
                         hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


# ---------------------------- units ----------------------------

def test_minor_units_respects_zero_decimal_currencies():
    assert to_minor_units(380.0, "EUR") == 38000
    assert to_minor_units(12.34, "usd") == 1234
    assert to_minor_units(5000, "JPY") == 5000       # not multiplied


# ---------------------------- signatures ----------------------------

def test_valid_signature_accepted():
    payload = b'{"type":"checkout.session.completed"}'
    ok, reason = verify_stripe_signature(payload, sign(payload), SECRET)
    assert ok and reason == "ok"


def test_tampered_payload_rejected():
    payload = b'{"amount": 100}'
    header = sign(payload)
    ok, reason = verify_stripe_signature(b'{"amount": 1}', header,
                                         SECRET)
    assert not ok and reason == "signature mismatch"


def test_replayed_old_event_rejected():
    payload = b"{}"
    old = sign(payload, timestamp=time.time() - 3600)
    ok, reason = verify_stripe_signature(payload, old, SECRET)
    assert not ok and "tolerance" in reason


def test_missing_or_malformed_headers_rejected():
    assert verify_stripe_signature(b"{}", "", SECRET)[0] is False
    assert verify_stripe_signature(b"{}", "garbage", SECRET)[0] is False
    assert verify_stripe_signature(b"{}", sign(b"{}"), "")[0] is False


# ---------------------------- checkout ----------------------------

@pytest.mark.asyncio
async def test_checkout_session_created_and_recorded(factory):
    offer_id = make_offer(factory)

    def handler(request):
        assert request.headers["Authorization"] == "Bearer sk_test_123"
        # Stripe takes form-encoded data, so the bracketed keys
        # arrive percent-encoded.
        from urllib.parse import parse_qs
        body = parse_qs(request.content.decode())
        assert body["line_items[0][price_data][unit_amount]"] == \
            ["38000"]
        assert body["line_items[0][price_data][currency]"] == ["eur"]
        return httpx.Response(200, json={
            "id": "cs_test_1",
            "url": "https://checkout.stripe.com/c/pay/cs_test_1",
        })

    service = PaymentService(
        session_factory=factory,
        http=HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1)),
    )
    result = await service.create_checkout_session(offer_id)
    assert result["checkout_url"].startswith("https://checkout.stripe")

    session = factory()
    payment = session.query(Payment).one()
    session.close()
    assert payment.status == "pending"
    assert payment.provider_session_id == "cs_test_1"
    assert payment.amount == 380.0


@pytest.mark.asyncio
async def test_expired_or_revoked_offer_cannot_be_paid(factory):
    service = PaymentService(session_factory=factory)
    expired = make_offer(factory, expired=True)
    with pytest.raises(PaymentError, match="expired"):
        await service.create_checkout_session(expired)
    revoked = make_offer(factory, revoked=True)
    with pytest.raises(PaymentError, match="withdrawn"):
        await service.create_checkout_session(revoked)


@pytest.mark.asyncio
async def test_unconfigured_stripe_refuses_cleanly(factory, monkeypatch):
    from app.utils import settings as settings_module
    monkeypatch.setenv("STRIPE_SECRET_KEY", "")
    settings_module.get_settings.cache_clear()
    service = PaymentService(session_factory=factory)
    with pytest.raises(PaymentError, match="not configured"):
        await service.create_checkout_session(make_offer(factory))


# ---------------------------- webhooks ----------------------------

def _seed_payment(factory, offer_id, session_id="cs_test_1"):
    session = factory()
    session.add(Payment(offer_id=offer_id, provider="stripe",
                        provider_session_id=session_id, amount=380.0,
                        currency="EUR", status="pending"))
    session.commit()
    session.close()


def test_webhook_marks_paid_and_updates_offer(factory):
    offer_id = make_offer(factory)
    _seed_payment(factory, offer_id)
    service = PaymentService(session_factory=factory)

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_1",
                            "payment_intent": "pi_1",
                            "metadata": {"offer_id": str(offer_id)}}},
    }
    payload = json.dumps(event).encode()
    result = service.handle_webhook(payload, sign(payload))
    assert result["ok"] and result["status"] == "paid"

    session = factory()
    payment = session.query(Payment).one()
    offer = session.get(CustomerOffer, offer_id)
    lead = session.get(HotelOfferRequest, offer.request_id)
    session.close()
    assert payment.status == "paid" and payment.paid_at is not None
    assert payment.provider_payment_id == "pi_1"
    assert offer.status == "paid" and lead.status == "paid"


def test_unsigned_webhook_changes_nothing(factory):
    offer_id = make_offer(factory)
    _seed_payment(factory, offer_id)
    service = PaymentService(session_factory=factory)
    payload = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_1"}},
    }).encode()

    result = service.handle_webhook(payload, "t=1,v1=deadbeef")
    assert result["ok"] is False
    session = factory()
    assert session.query(Payment).one().status == "pending"
    session.close()


def test_failed_payment_records_reason(factory):
    offer_id = make_offer(factory)
    _seed_payment(factory, offer_id)
    service = PaymentService(session_factory=factory)
    event = {
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": "cs_test_1",
                            "last_payment_error": {
                                "message": "card declined"}}},
    }
    payload = json.dumps(event).encode()
    service.handle_webhook(payload, sign(payload))
    session = factory()
    payment = session.query(Payment).one()
    session.close()
    assert payment.status == "failed"
    assert "declined" in payment.failure_reason


def test_paid_state_is_not_walked_backwards(factory):
    offer_id = make_offer(factory)
    _seed_payment(factory, offer_id)
    service = PaymentService(session_factory=factory)
    paid = json.dumps({
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_1"}},
    }).encode()
    service.handle_webhook(paid, sign(paid))

    late_expiry = json.dumps({
        "type": "checkout.session.expired",
        "data": {"object": {"id": "cs_test_1"}},
    }).encode()
    service.handle_webhook(late_expiry, sign(late_expiry))

    session = factory()
    assert session.query(Payment).one().status == "paid"
    session.close()


def test_unknown_event_types_ignored(factory):
    service = PaymentService(session_factory=factory)
    payload = json.dumps({"type": "customer.created",
                          "data": {"object": {}}}).encode()
    result = service.handle_webhook(payload, sign(payload))
    assert result["ok"] and result.get("ignored") == "customer.created"


def test_invalid_json_rejected(factory):
    service = PaymentService(session_factory=factory)
    payload = b"not json"
    result = service.handle_webhook(payload, sign(payload))
    assert result["ok"] is False and "json" in result["reason"]
