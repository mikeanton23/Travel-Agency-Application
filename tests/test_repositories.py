# -*- coding: utf-8 -*-

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Country, Destination, Favorite, User
from app.repositories.destination_repository import DestinationRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.close()


def seed(session):
    session.add_all([
        Destination(name="Santorini", country="Greece",
                    continent="Europe", avg_cost_per_day=150,
                    ai_score=9.1, tags=["romantic", "beach"]),
        Destination(name="Naxos", country="Greece",
                    continent="Europe", avg_cost_per_day=90,
                    ai_score=8.4),
        Destination(name="Kyoto", country="Japan",
                    continent="Asia", avg_cost_per_day=110,
                    ai_score=9.4),
    ])
    session.flush()


def test_full_schema_creates_on_sqlite(session):
    # 22 models incl. FKs, unique constraints, JSON columns.
    assert session.query(Destination).count() == 0


def test_search_filters_and_ordering(session):
    seed(session)
    repo = DestinationRepository(session)

    europe = repo.search(continent="Europe")
    assert [d.name for d in europe] == ["Santorini", "Naxos"]  # score desc

    cheap = repo.search(max_cost_per_day=100)
    assert [d.name for d in cheap] == ["Naxos"]

    by_q = repo.search(query="kyo")
    assert [d.name for d in by_q] == ["Kyoto"]


def test_by_name_and_country_case_insensitive(session):
    seed(session)
    repo = DestinationRepository(session)
    d = repo.by_name_and_country("santorini", "GREECE")
    assert d is not None and d.avg_cost_per_day == 150


def test_favorite_unique_constraint(session):
    seed(session)
    user = User(email="a@b.c", password_hash="x")
    session.add(user)
    session.flush()
    dest = session.query(Destination).first()
    session.add(Favorite(user_id=user.id, destination_id=dest.id))
    session.flush()
    session.add(Favorite(user_id=user.id, destination_id=dest.id))
    with pytest.raises(Exception):
        session.flush()


def test_country_iso_unique(session):
    session.add(Country(iso2="GR", name="Greece"))
    session.flush()
    session.add(Country(iso2="GR", name="Duplicate"))
    with pytest.raises(Exception):
        session.flush()
