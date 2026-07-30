# -*- coding: utf-8 -*-

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import ApiKey, Base
from app.services.key_manager import KeyManager
from app.utils.http_client import HttpJsonClient, RetryPolicy

SECRET = "unit-test-secret-key-0123456789"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def make_manager(session_factory, handler=None):
    http = None
    if handler is not None:
        http = HttpJsonClient(
            transport=httpx.MockTransport(handler),
            retry=RetryPolicy(max_attempts=1),
        )
    return KeyManager(
        secret_key=SECRET, session_factory=session_factory, http=http
    )


def test_keys_are_encrypted_at_rest(session_factory):
    manager = make_manager(session_factory)
    manager.set_key("pexels", "px-12345")

    session = session_factory()
    row = session.query(ApiKey).filter_by(provider="pexels").one()
    session.close()
    assert "px-12345" not in row.encrypted_value  # ciphertext only
    assert manager.get_key("pexels") == "px-12345"


def test_db_key_overrides_env(session_factory, monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "PEXELS_API_KEY", "env-key")
    manager = make_manager(session_factory)
    assert manager.get_key("pexels") == "env-key"     # env fallback
    manager.set_key("pexels", "db-key")
    assert manager.get_key("pexels") == "db-key"      # DB wins


def test_delete_key(session_factory):
    manager = make_manager(session_factory)
    manager.set_key("geoapify", "g-1")
    assert manager.delete_key("geoapify") is True
    assert manager.delete_key("geoapify") is False


def test_list_keys_never_exposes_values(session_factory):
    manager = make_manager(session_factory)
    manager.set_key("openai", "sk-secret-value")
    listing = manager.list_keys()
    assert "sk-secret-value" not in str(listing)
    entry = next(x for x in listing if x["provider"] == "openai")
    assert entry["stored"] is True
    assert entry["is_valid"] is None  # not validated yet


@pytest.mark.asyncio
async def test_validate_success_persists_status(session_factory):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer sk-good"
        return httpx.Response(200, json={"data": [{"id": "gpt"}]})

    manager = make_manager(session_factory, handler)
    manager.set_key("openai", "sk-good")
    result = await manager.validate("openai")
    assert result["is_valid"] is True

    entry = next(x for x in manager.list_keys()
                 if x["provider"] == "openai")
    assert entry["is_valid"] is True
    assert entry["last_validated_at"] is not None


@pytest.mark.asyncio
async def test_validate_failure_records_error(session_factory):
    def handler(request):
        return httpx.Response(401, json={"error": "bad key"})

    manager = make_manager(session_factory, handler)
    manager.set_key("openai", "sk-bad")
    result = await manager.validate("openai")
    assert result["is_valid"] is False
    entry = next(x for x in manager.list_keys()
                 if x["provider"] == "openai")
    assert entry["is_valid"] is False
    assert entry["last_error"]


@pytest.mark.asyncio
async def test_validate_amadeus_uses_token_endpoint(session_factory):
    def handler(request):
        assert str(request.url).endswith("/v1/security/oauth2/token")
        return httpx.Response(
            200, json={"access_token": "t", "expires_in": 1799}
        )

    manager = make_manager(session_factory, handler)
    manager.set_key("amadeus", "client-id")
    manager.set_key("amadeus_secret", "client-secret")
    result = await manager.validate("amadeus")
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_validate_without_key_fails_cleanly(session_factory,
                                                  monkeypatch):
    import app.utils.config as config
    monkeypatch.setattr(config, "NUMBEO_API_KEY", "")
    manager = make_manager(session_factory)
    result = await manager.validate("numbeo")
    assert result["is_valid"] is False
    assert "No key" in result["error"]


def test_list_keys_includes_signup_info(session_factory):
    manager = make_manager(session_factory)
    listing = {e["provider"]: e for e in manager.list_keys()}
    amadeus = listing["amadeus"]
    assert "developers.amadeus.com" in amadeus["signup"]
    assert amadeus["label"].startswith("Amadeus")
    assert "tier" in listing["numbeo"] and "Paid" in listing["numbeo"]["tier"]
