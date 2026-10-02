# -*- coding: utf-8 -*-

"""Office cash account and multi-service quotes."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Agency, Base, CashMovement, User
from app.services.agency.cash import CashError, CashService
from app.services.agency.quotes import QuoteError, QuoteService


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
                agency_id=agency.id)
    nikos = User(email="nikos@a.gr", password_hash="x", role="agent",
                 agency_id=agency.id)
    session.add_all([anna, nikos])
    session.commit()
    ids = {"agency": agency.id, "anna": anna.id, "nikos": nikos.id}
    session.close()
    return ids


# ---------------------------------------------------------------
# Cash
# ---------------------------------------------------------------

def test_all_agents_pay_into_one_office_account(office, factory):
    cash = CashService(session_factory=factory)
    account = cash.ensure_account(office["agency"])
    # Calling again must not create a second account.
    assert cash.ensure_account(office["agency"]) == account

    cash.record(account, 500, "cash", agent_id=office["anna"])
    cash.record(account, 300, "card", agent_id=office["nikos"])
    cash.record(account, 200, "iris", agent_id=office["anna"])

    assert cash.balance(account) == Decimal("1000.00")
    by_agent = {row["agent_id"]: row["total"]
                for row in cash.totals_by_agent(account)}
    assert by_agent[office["anna"]] == 700.0
    assert by_agent[office["nikos"]] == 300.0


def test_methods_are_tracked_for_reconciliation(office, factory):
    cash = CashService(session_factory=factory)
    account = cash.ensure_account(office["agency"])
    cash.record(account, 120, "cash", agent_id=office["anna"])
    cash.record(account, 80, "card", agent_id=office["anna"])
    totals = cash.totals_by_method(account)
    assert totals["cash"] == 120.0
    assert totals["card"] == 80.0
    assert totals["iris"] == 0.0


def test_unknown_method_and_zero_amount_are_refused(office, factory):
    cash = CashService(session_factory=factory)
    account = cash.ensure_account(office["agency"])
    with pytest.raises(CashError, match="payment method"):
        cash.record(account, 50, "bitcoin")
    with pytest.raises(CashError, match="greater than zero"):
        cash.record(account, 0, "cash")


def test_a_mistake_is_reversed_not_edited(office, factory):
    """The original receipt must survive untouched for the audit."""
    cash = CashService(session_factory=factory)
    account = cash.ensure_account(office["agency"])
    wrong = cash.record(account, 500, "cash", agent_id=office["anna"])
    cash.reverse(wrong["id"], agent_id=office["anna"],
                 reason="wrong amount")

    assert cash.balance(account) == Decimal("0.00")
    session = factory()
    rows = session.query(CashMovement).order_by(CashMovement.id).all()
    session.close()
    assert len(rows) == 2                 # nothing deleted
    assert rows[0].amount == 500.0        # original intact
    assert rows[1].reverses_id == rows[0].id

    with pytest.raises(CashError, match="already reversed"):
        cash.reverse(wrong["id"])


def test_payments_out_reduce_the_balance(office, factory):
    cash = CashService(session_factory=factory)
    account = cash.ensure_account(office["agency"])
    cash.record(account, 1000, "cash", agent_id=office["anna"])
    cash.record(account, 250, "cash", agent_id=office["anna"],
                direction="out", description="Supplier payment")
    assert cash.balance(account) == Decimal("750.00")


# ---------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------

def test_a_quote_holds_all_five_services(office, factory):
    quotes = QuoteService(session_factory=factory)
    created = quotes.create(office["agency"], office["anna"],
                            title="Honeymoon")
    for service, title, net, charge in (
        ("ticket", "ATH-JTR return", 420, 0),
        ("hotel", "Canaves Oia, 4 nights", 1600, 120),
        ("transfer", "Airport to hotel", 45, 10),
        ("car_rental", "Fiat Panda, 3 days", 135, 15),
        ("tour", "Caldera sunset cruise", 180, 20),
    ):
        quotes.add_item(created["id"], service, title,
                        net_cost=net, service_charge=charge)

    quote = quotes.get(created["id"])
    assert len(quote["items"]) == 5
    assert {i["service_type"] for i in quote["items"]} == {
        "ticket", "hotel", "transfer", "car_rental", "tour"}
    # Lines keep the order they were added.
    assert [i["position"] for i in quote["items"]] == [0, 1, 2, 3, 4]
    totals = quote["totals"]
    assert totals["net_cost"] == 2380.0
    assert totals["service_charge"] == 165.0
    assert totals["total"] == 2545.0


def test_quote_reference_is_unique_and_readable(office, factory):
    quotes = QuoteService(session_factory=factory)
    first = quotes.create(office["agency"], office["anna"])
    second = quotes.create(office["agency"], office["anna"])
    assert first["reference"] != second["reference"]
    assert first["reference"].startswith("Q")


def test_unknown_service_type_is_refused(office, factory):
    quotes = QuoteService(session_factory=factory)
    created = quotes.create(office["agency"], office["anna"])
    with pytest.raises(QuoteError, match="Unknown service"):
        quotes.add_item(created["id"], "submarine", "Nope")
    with pytest.raises(QuoteError, match="description"):
        quotes.add_item(created["id"], "hotel", "   ")


def test_domestic_lines_add_vat_to_the_quote_total(office, factory):
    quotes = QuoteService(session_factory=factory)
    created = quotes.create(office["agency"], office["anna"])
    quotes.add_item(created["id"], "hotel", "Athens city hotel",
                    net_cost=400, service_charge=50,
                    is_domestic=True, vat_rate=24)
    totals = quotes.get(created["id"])["totals"]
    assert totals["vat"] == 12.0
    assert totals["total"] == 462.0


def test_quotes_are_listed_per_agent(office, factory):
    quotes = QuoteService(session_factory=factory)
    quotes.create(office["agency"], office["anna"], title="Anna trip")
    quotes.create(office["agency"], office["nikos"], title="Nikos trip")

    anna_quotes = quotes.list_for(office["agency"],
                                  agent_id=office["anna"])
    assert [q["title"] for q in anna_quotes] == ["Anna trip"]
    assert len(quotes.list_for(office["agency"])) == 2
