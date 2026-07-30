# -*- coding: utf-8 -*-

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, User
from app.services.auth_service import (
    AuthError, AuthService, hash_password, verify_password,
)
from app.utils.rate_limit import RateLimiter


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


# ---------------------------- hashing ----------------------------

def test_password_hash_roundtrip_and_uniqueness():
    h1 = hash_password("correct horse battery")
    h2 = hash_password("correct horse battery")
    assert h1 != h2                       # unique salts
    assert h1.startswith("scrypt$")
    assert "correct horse" not in h1
    assert verify_password("correct horse battery", h1)
    assert not verify_password("wrong", h1)


def test_verify_rejects_malformed_hashes():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "md5$deadbeef")
    assert not verify_password("x", "")


# ---------------------------- auth flow ----------------------------

def test_register_and_authenticate(factory):
    service = AuthService(session_factory=factory)
    user = service.register("Traveler@Example.com", "s3cretpass",
                            "Mike")
    assert user.email == "traveler@example.com"   # normalized
    logged_in = service.authenticate("traveler@example.com",
                                     "s3cretpass", client_key="t1")
    assert logged_in.id == user.id

    session = factory()
    row = session.query(User).one()
    session.close()
    assert "s3cretpass" not in row.password_hash
    assert row.last_login_at is not None


def test_duplicate_email_and_weak_password_rejected(factory):
    service = AuthService(session_factory=factory)
    service.register("a@b.co", "longenough")
    with pytest.raises(AuthError):
        service.register("a@b.co", "longenough")
    with pytest.raises(AuthError):
        service.register("new@b.co", "short")
    with pytest.raises(AuthError):
        service.register("not-an-email", "longenough")


def test_wrong_password_and_unknown_email_same_error(factory):
    service = AuthService(session_factory=factory)
    service.register("a@b.co", "longenough")
    with pytest.raises(AuthError) as e1:
        service.authenticate("a@b.co", "wrongpass", client_key="t2")
    with pytest.raises(AuthError) as e2:
        service.authenticate("ghost@b.co", "whatever", client_key="t3")
    assert str(e1.value) == str(e2.value)  # no account enumeration


def test_disabled_account_cannot_login(factory):
    service = AuthService(session_factory=factory)
    user = service.register("a@b.co", "longenough")
    session = factory()
    session.query(User).filter_by(id=user.id).update(
        {"is_active": False})
    session.commit()
    session.close()
    with pytest.raises(AuthError, match="disabled"):
        service.authenticate("a@b.co", "longenough", client_key="t4")


def test_login_rate_limited(factory):
    service = AuthService(session_factory=factory)
    service.register("a@b.co", "longenough")
    for _ in range(5):
        with pytest.raises(AuthError, match="Invalid"):
            service.authenticate("a@b.co", "bad", client_key="same-ip")
    with pytest.raises(AuthError, match="Too many attempts"):
        service.authenticate("a@b.co", "longenough",
                             client_key="same-ip")


def test_change_password(factory):
    service = AuthService(session_factory=factory)
    user = service.register("a@b.co", "oldpassword")
    with pytest.raises(AuthError):
        service.change_password(user.id, "wrong", "newpassword")
    service.change_password(user.id, "oldpassword", "newpassword")
    assert service.authenticate("a@b.co", "newpassword",
                                client_key="t5").id == user.id


# ---------------------------- rate limiter ----------------------------

def test_rate_limiter_window_and_recovery():
    limiter = RateLimiter()
    t = 1000.0
    for i in range(3):
        allowed, _ = limiter.allow("k", limit=3, window_s=60, now=t + i)
    allowed, retry = limiter.allow("k", limit=3, window_s=60, now=t + 3)
    assert not allowed and retry > 0
    # After the window slides, requests flow again.
    allowed, _ = limiter.allow("k", limit=3, window_s=60, now=t + 61)
    assert allowed


def test_rate_limiter_keys_are_independent():
    limiter = RateLimiter()
    assert limiter.allow("a", 1, 60, now=1.0)[0]
    assert not limiter.allow("a", 1, 60, now=2.0)[0]
    assert limiter.allow("b", 1, 60, now=2.0)[0]
    assert limiter.remaining("b", 1, 60, now=2.0) == 0
