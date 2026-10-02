# -*- coding: utf-8 -*-

"""Each agent owns their book; managers see the whole office."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Agency, Base, Client, User
from app.services.agency.access import (
    may_edit_quote, may_reassign_client, may_view_client,
    may_view_office_cash, role_of, sees_whole_office,
)
from app.services.agency.clients import ClientError, ClientService


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def office(factory):
    session = factory()
    agency = Agency(name="Aevyra Travel")
    session.add(agency)
    session.flush()
    anna = User(email="anna@a.gr", password_hash="x", role="agent",
                agency_id=agency.id, display_name="Anna")
    nikos = User(email="nikos@a.gr", password_hash="x", role="agent",
                 agency_id=agency.id, display_name="Nikos")
    maria = User(email="maria@a.gr", password_hash="x", role="manager",
                 agency_id=agency.id, display_name="Maria")
    session.add_all([anna, nikos, maria])
    session.commit()
    ids = {"agency": agency.id, "anna": anna.id,
           "nikos": nikos.id, "maria": maria.id}
    session.close()
    return ids


class FakeUser:
    def __init__(self, user_id, role="agent", is_admin=False):
        self.id = user_id
        self.role = role
        self.is_admin = is_admin


def test_role_falls_back_to_is_admin_for_older_rows():
    legacy = FakeUser(1, role="", is_admin=True)
    assert role_of(legacy) == "admin"
    assert sees_whole_office(legacy)
    assert role_of(FakeUser(2, role="")) == "agent"


def test_an_agent_cannot_see_another_agents_client(office, factory):
    service = ClientService(session_factory=factory)
    anna = FakeUser(office["anna"])
    nikos = FakeUser(office["nikos"])

    created = service.create(office["agency"], office["anna"],
                             "Giorgos Papadopoulos",
                             email="g@example.com")
    assert service.get(anna, created["id"]) is not None
    # Nikos must not see Anna's client at all.
    assert service.get(nikos, created["id"]) is None


def test_a_manager_sees_the_whole_office(office, factory):
    service = ClientService(session_factory=factory)
    maria = FakeUser(office["maria"], role="manager")
    created = service.create(office["agency"], office["anna"],
                             "Giorgos Papadopoulos")
    assert service.get(maria, created["id"]) is not None


def test_search_is_scoped_to_the_owner(office, factory):
    service = ClientService(session_factory=factory)
    service.create(office["agency"], office["anna"], "Anna Client")
    service.create(office["agency"], office["nikos"], "Nikos Client")

    anna_sees = service.search(FakeUser(office["anna"]),
                               office["agency"])
    assert [c["full_name"] for c in anna_sees] == ["Anna Client"]

    manager_sees = service.search(
        FakeUser(office["maria"], role="manager"), office["agency"])
    assert len(manager_sees) == 2


def test_only_a_manager_may_reassign_a_client(office, factory):
    service = ClientService(session_factory=factory)
    created = service.create(office["agency"], office["anna"], "Client")
    with pytest.raises(ClientError, match="manager"):
        service.reassign(FakeUser(office["anna"]), created["id"],
                         office["nikos"])
    assert service.reassign(FakeUser(office["maria"], role="manager"),
                            created["id"], office["nikos"])
    # Now it belongs to Nikos, and Anna can no longer see it.
    assert service.get(FakeUser(office["anna"]), created["id"]) is None
    assert service.get(FakeUser(office["nikos"]), created["id"])


def test_notes_follow_the_same_ownership_rule(office, factory):
    service = ClientService(session_factory=factory)
    created = service.create(office["agency"], office["anna"], "Client")
    assert service.add_note(FakeUser(office["anna"]), created["id"],
                            "Prefers morning flights")
    assert not service.add_note(FakeUser(office["nikos"]),
                                created["id"], "Should not stick")
    assert len(service.notes(FakeUser(office["anna"]),
                             created["id"])) == 1
    assert service.notes(FakeUser(office["nikos"]), created["id"]) == []


def test_a_sent_quote_is_locked_to_its_agent():
    class FakeQuote:
        def __init__(self, agent_id, status):
            self.agent_id = agent_id
            self.status = status

    agent = FakeUser(1)
    manager = FakeUser(9, role="manager")
    assert may_edit_quote(agent, FakeQuote(1, "draft"))
    # Once sent it is a record; only a manager may change it.
    assert not may_edit_quote(agent, FakeQuote(1, "sent"))
    assert may_edit_quote(manager, FakeQuote(1, "sent"))


def test_only_managers_see_the_office_balance():
    assert not may_view_office_cash(FakeUser(1))
    assert may_view_office_cash(FakeUser(2, role="manager"))
    assert may_view_office_cash(FakeUser(3, role="admin"))
