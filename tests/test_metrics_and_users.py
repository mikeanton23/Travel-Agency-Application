# -*- coding: utf-8 -*-

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.repositories.user_repository import (
    FavoriteRepository, NotificationRepository, TripRepository,
    UserAdminRepository,
)
from app.services.auth_service import AuthService
from app.services.cache_service import ApiCacheService
from app.services.metrics import Metrics, provider_from_url
from app.utils.http_client import HttpJsonClient, RetryPolicy


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


# ---------------------------- metrics ----------------------------

def test_provider_from_url_mapping():
    assert provider_from_url(
        "https://test.api.amadeus.com/v2/x") == "amadeus"
    assert provider_from_url(
        "https://en.wikivoyage.org/w/api.php") == "wikivoyage"
    assert provider_from_url("http://localhost:11434/api/chat") == \
        "ollama"
    assert provider_from_url("https://unknown.example.com/x") == \
        "unknown.example.com"


def test_metrics_counters_and_persistence(factory):
    m = Metrics(session_factory=factory)
    m.record_http("GET", "https://api.geoapify.com/v2/places", 200, 120)
    m.record_http("GET", "https://api.geoapify.com/v2/places", 500, 80)
    m.record_http("POST", "https://api.openai.com/v1/chat", 200, 900)

    summary = {row["provider"]: row for row in m.summary()}
    assert summary["geoapify"]["requests"] == 2
    assert summary["geoapify"]["errors"] == 1
    assert summary["geoapify"]["avg_ms"] == 100
    assert summary["openai"]["requests"] == 1

    recent = m.recent_usage()
    assert len(recent) == 3
    assert recent[0]["provider"] == "openai"  # newest first
    assert recent[1]["ok"] is False


@pytest.mark.asyncio
async def test_http_client_records_into_metrics(factory, monkeypatch):
    import app.services.metrics as metrics_module
    fresh = Metrics(session_factory=factory)
    monkeypatch.setattr(metrics_module, "metrics", fresh)

    def handler(request):
        return httpx.Response(200, json={"ok": True})

    client = HttpJsonClient(transport=httpx.MockTransport(handler),
                            retry=RetryPolicy(max_attempts=1))
    await client.arequest_json(
        "GET", "https://api.geoapify.com/v2/places"
    )
    assert fresh.summary()[0]["provider"] == "geoapify"
    assert fresh.recent_usage()[0]["status"] == 200


@pytest.mark.asyncio
async def test_cache_stats_track_hits_and_misses():
    cache = ApiCacheService()
    await cache.set("k", 1, ttl=60)
    await cache.get("k")            # hit
    await cache.get("nope")         # miss
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["memory_entries"] == 1


# ---------------------------- user domain ----------------------------

def _make_user(factory, email="u@e.co"):
    return AuthService(session_factory=factory).register(
        email, "longenough")


def _make_destination(factory):
    from app.db.models import Destination
    session = factory()
    d = Destination(name="Naxos", country="Greece")
    session.add(d)
    session.commit()
    dest_id = d.id
    session.close()
    return dest_id


def test_favorites_toggle_and_list(factory):
    user = _make_user(factory)
    dest_id = _make_destination(factory)
    session = factory()
    repo = FavoriteRepository(session)
    assert repo.toggle(user.id, dest_id) is True
    assert repo.is_favorite(user.id, dest_id)
    favs = repo.destinations_for(user.id)
    assert [d.name for d in favs] == ["Naxos"]
    assert repo.toggle(user.id, dest_id) is False
    assert not repo.is_favorite(user.id, dest_id)
    session.close()


def test_trips_create_and_items_ordered(factory):
    user = _make_user(factory)
    session = factory()
    repo = TripRepository(session)
    trip = repo.create(user.id, "Greek islands", currency="EUR")
    repo.add_item(trip.id, "flight", "ATH → JTR",
                  reference={"offer": 1}, price_total=150.0,
                  currency="EUR")
    repo.add_item(trip.id, "hotel", "Sea View 3 nights")
    session.commit()

    trips = repo.for_user(user.id)
    assert trips[0].title == "Greek islands"
    items = trips[0].items
    assert [i.position for i in items] == [0, 1]
    assert items[0].reference == {"offer": 1}
    session.close()


def test_notifications_flow(factory):
    user = _make_user(factory)
    session = factory()
    repo = NotificationRepository(session)
    note = repo.notify(user.id, "Price drop", "ATH→JTR now 120 EUR")
    assert repo.unread_count(user.id) == 1
    assert repo.mark_read(user.id, note.id) is True
    assert repo.unread_count(user.id) == 0
    assert repo.mark_read(user.id, 9999) is False
    session.close()


def test_admin_user_management(factory):
    user = _make_user(factory)
    session = factory()
    repo = UserAdminRepository(session)
    assert repo.set_admin(user.id, True) is True
    assert repo.set_active(user.id, False) is True
    session.commit()
    refreshed = repo.all_users()[0]
    assert refreshed.is_admin and not refreshed.is_active
    assert repo.set_admin(424242, True) is False
    session.close()
