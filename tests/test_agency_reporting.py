"""Phase C reporting: access boundary and arithmetic.

Runs fully offline — the reporting service is constructed with fake quote,
booking and cash services, so no database is touched.

The access tests are the important ones. They assert that an agent gets an
exception, not an empty report: a blank page reads as "the office earned
nothing", which is a worse failure than a visible refusal.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest

from app.services.agency.reporting import (
    ReportingDenied,
    ReportingService,
    line_money,
    may_view_financials,
    money,
)

TODAY = date.today()
RECENT = (TODAY - timedelta(days=3)).isoformat()
OLD = (TODAY - timedelta(days=400)).isoformat()


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

@dataclass
class FakeUser:
    id: int
    role: str
    agency_id: int = 1
    email: str = "x@example.com"

    @property
    def is_manager(self) -> bool:
        return self.role in ("manager", "admin")


AGENT = FakeUser(id=2, role="agent", email="agent@example.com")
MANAGER = FakeUser(id=1, role="manager", email="boss@example.com")


def _quote(
    quote_id: int,
    agent_id: int,
    status: str,
    items: List[Dict[str, Any]],
    created: str = RECENT,
    agent_name: str = "",
) -> Dict[str, Any]:
    return {
        "id": quote_id,
        "agency_id": 1,
        "agent_id": agent_id,
        "agent_name": agent_name or f"Agent #{agent_id}",
        "status": status,
        "currency": "EUR",
        "created_at": created,
        "items": items,
    }


def _item(
    service_type: str,
    net_cost: float,
    service_charge: float,
    quantity: int = 1,
    is_domestic: bool = False,
    vat_rate: float = 24.0,
) -> Dict[str, Any]:
    return {
        "service_type": service_type,
        "title": service_type,
        "net_cost": net_cost,
        "service_charge": service_charge,
        "quantity": quantity,
        "is_domestic": is_domestic,
        "vat_rate": vat_rate,
    }


class FakeQuotes:
    def __init__(self, quotes: List[Dict[str, Any]]) -> None:
        self._quotes = {q["id"]: q for q in quotes}

    def list_for(self, agency_id, agent_id=None, client_id=None, status=None, limit=100):
        return [dict(q) for q in self._quotes.values() if q["agency_id"] == agency_id]

    def get(self, quote_id):
        found = self._quotes.get(quote_id)
        return dict(found) if found else None


class FakeBookings:
    def __init__(self, bookings: List[Dict[str, Any]]) -> None:
        self._bookings = {b["id"]: b for b in bookings}

    def list_for(self, agency_id, limit=100):
        return [dict(b) for b in self._bookings.values()]

    def get(self, booking_id):
        found = self._bookings.get(booking_id)
        return dict(found) if found else None


class FakeCash:
    def __init__(self, balance=0.0, by_method=None, by_agent=None) -> None:
        self._balance = balance
        self._by_method = by_method or {}
        self._by_agent = by_agent or {}

    def ensure_account(self, agency_id):
        return {"id": 99, "agency_id": agency_id}

    def balance(self, account_id):
        return self._balance

    def totals_by_method(self, account_id):
        return dict(self._by_method)

    def totals_by_agent(self, account_id):
        return dict(self._by_agent)


def build_service(
    quotes: Optional[List[Dict[str, Any]]] = None,
    bookings: Optional[List[Dict[str, Any]]] = None,
    cash: Optional[FakeCash] = None,
) -> ReportingService:
    return ReportingService(
        quote_service=FakeQuotes(quotes or []),
        booking_service=FakeBookings(bookings or []),
        cash_service=cash or FakeCash(),
    )


# --------------------------------------------------------------------------
# Access boundary
# --------------------------------------------------------------------------

FINANCIAL_CALLS = [
    ("sales_by_agent", ()),
    ("sales_by_service", ()),
    ("monthly_totals", ()),
    ("conversion", ()),
    ("cash_reconciliation", ()),
    ("outstanding", ()),
    ("dashboard", ()),
]


@pytest.mark.parametrize("method,extra", FINANCIAL_CALLS)
def test_agent_cannot_read_any_financial_report(method, extra):
    service = build_service(
        quotes=[_quote(1, AGENT.id, "accepted", [_item("hotel", 100.0, 20.0)])]
    )
    with pytest.raises(ReportingDenied):
        getattr(service, method)(AGENT, 1, *extra)


@pytest.mark.parametrize("method,extra", FINANCIAL_CALLS)
def test_manager_can_read_every_financial_report(method, extra):
    service = build_service(
        quotes=[_quote(1, AGENT.id, "accepted", [_item("hotel", 100.0, 20.0)])]
    )
    result = getattr(service, method)(MANAGER, 1, *extra)
    assert result is not None


def test_may_view_financials_separates_the_roles():
    assert may_view_financials(MANAGER) is True
    assert may_view_financials(AGENT) is False


def test_denial_is_an_exception_not_an_empty_report():
    """A blank report would read as 'the office earned nothing'."""
    service = build_service(
        quotes=[_quote(1, AGENT.id, "accepted", [_item("tour", 500.0, 80.0)])]
    )
    try:
        service.sales_by_agent(AGENT, 1)
    except ReportingDenied as exc:
        assert "manager" in str(exc).lower() or "owner" in str(exc).lower()
    else:  # pragma: no cover
        pytest.fail("an agent was handed office financials")


# --------------------------------------------------------------------------
# Line arithmetic
# --------------------------------------------------------------------------

def test_vat_applies_to_the_service_charge_only_and_only_domestically():
    domestic = line_money(_item("hotel", 200.0, 50.0, is_domestic=True))
    assert domestic.vat == money(50.0 * 0.24)          # 12.00 — on the charge
    assert domestic.vat != money(250.0 * 0.24)         # never on the supplier fare
    assert domestic.gross == money(200.0 + 50.0 + 12.0)

    abroad = line_money(_item("hotel", 200.0, 50.0, is_domestic=False))
    assert abroad.vat == 0.0
    assert abroad.gross == money(250.0)


def test_margin_is_the_service_charge_the_agent_typed():
    line = line_money(_item("transfer", 60.0, 15.0))
    assert line.margin == 15.0
    # Supplier cost never becomes margin — commission is calculated by hand.
    assert line.margin != line.net_cost


def test_zero_charge_lines_contribute_zero_margin():
    """Ferries (prohibited by law) and most airfares (policy) carry no charge."""
    ferry = line_money(_item("ticket", 48.0, 0.0, is_domestic=True))
    assert ferry.service_charge == 0.0
    assert ferry.margin == 0.0
    assert ferry.vat == 0.0            # no charge means no VAT to collect
    assert ferry.gross == 48.0         # the client pays the fare and nothing more


def test_quantity_multiplies_both_cost_and_charge():
    line = line_money(_item("hotel", 100.0, 10.0, quantity=3, is_domestic=True))
    assert line.net_cost == 300.0
    assert line.service_charge == 30.0
    assert line.vat == money(30.0 * 0.24)


def test_line_money_agrees_with_the_pricing_module():
    """Reporting mirrors pricing. If they drift, this test is the alarm."""
    pricing = pytest.importorskip("app.services.agency.pricing")
    price_line = getattr(pricing, "price_line", None)
    if not callable(price_line):
        pytest.skip("pricing.price_line is not available")

    cases = [
        _item("hotel", 200.0, 50.0, is_domestic=True),
        _item("hotel", 200.0, 50.0, is_domestic=False),
        _item("ticket", 48.0, 0.0, is_domestic=True),
        _item("tour", 90.0, 12.5, quantity=4, is_domestic=True),
    ]

    params = inspect.signature(price_line).parameters
    for item in cases:
        mine = line_money(item)
        try:
            if len(params) == 1:
                theirs = price_line(item)
            else:
                theirs = price_line(**{k: v for k, v in item.items() if k in params})
        except TypeError:
            pytest.skip("pricing.price_line takes a shape this test cannot build")

        for attr in ("vat", "gross"):
            expected = getattr(theirs, attr, None)
            if expected is None:
                continue
            assert money(expected) == getattr(mine, attr), (
                f"reporting and pricing disagree on {attr} for {item}"
            )


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def test_only_earned_quotes_count_as_sales():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [_item("hotel", 100.0, 20.0)]),
        _quote(2, 2, "sent", [_item("hotel", 999.0, 500.0)]),
        _quote(3, 2, "draft", [_item("tour", 999.0, 500.0)]),
    ])
    report = service.sales_by_agent(MANAGER, 1)
    assert report.total["margin"] == 20.0
    assert report.total["net_cost"] == 100.0


def test_sales_split_per_agent():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [_item("hotel", 100.0, 20.0)], agent_name="Maria"),
        _quote(2, 3, "booked", [_item("tour", 300.0, 45.0)], agent_name="Nikos"),
    ])
    report = service.sales_by_agent(MANAGER, 1)
    labels = {row["label"]: row for row in report.rows}
    assert labels["Maria"]["margin"] == 20.0
    assert labels["Nikos"]["margin"] == 45.0
    assert report.total["margin"] == 65.0
    # Ranked by margin, best first.
    assert report.rows[0]["label"] == "Nikos"


def test_every_service_gets_a_row_even_at_zero():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [_item("hotel", 100.0, 20.0)]),
    ])
    report = service.sales_by_service(MANAGER, 1)
    labels = [row["label"] for row in report.rows]
    for expected in ("Hotels", "Tickets", "Transfers", "Car rental", "Tours"):
        assert expected in labels
    tickets = next(r for r in report.rows if r["label"] == "Tickets")
    assert tickets["count"] == 0
    assert tickets["margin"] == 0.0
    assert tickets["margin_pct"] is None   # no sales means no percentage, not 0%


def test_period_filter_excludes_older_quotes():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [_item("hotel", 100.0, 20.0)], created=RECENT),
        _quote(2, 2, "accepted", [_item("hotel", 100.0, 99.0)], created=OLD),
    ])
    report = service.sales_by_agent(
        MANAGER, 1, TODAY - timedelta(days=30), TODAY
    )
    assert report.total["margin"] == 20.0


def test_monthly_totals_are_chronological():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [_item("hotel", 10.0, 1.0)], created="2026-01-15"),
        _quote(2, 2, "accepted", [_item("hotel", 10.0, 2.0)], created="2026-03-02"),
        _quote(3, 2, "accepted", [_item("hotel", 10.0, 3.0)], created="2026-02-20"),
    ])
    report = service.monthly_totals(MANAGER, 1, months=12)
    assert [r["label"] for r in report.rows] == ["2026-01", "2026-02", "2026-03"]
    assert report.total["margin"] == 6.0


def test_margin_pct_is_none_rather_than_zero_when_there_are_no_sales():
    report = build_service().sales_by_agent(MANAGER, 1)
    assert report.total["margin_pct"] is None


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

def test_open_quotes_do_not_count_against_an_agent():
    service = build_service(quotes=[
        _quote(1, 2, "accepted", [], agent_name="Maria"),
        _quote(2, 2, "sent", [], agent_name="Maria"),
        _quote(3, 2, "sent", [], agent_name="Maria"),
    ])
    report = service.conversion(MANAGER, 1)
    row = report.rows[0]
    assert row["issued"] == 3
    assert row["open"] == 2
    assert row["rate_pct"] == 100.0        # 1 won of 1 decided
    assert any("still open" in n for n in report.notes)


def test_conversion_rate_is_none_when_nothing_is_decided():
    service = build_service(quotes=[_quote(1, 2, "sent", [])])
    report = service.conversion(MANAGER, 1)
    assert report.rows[0]["rate_pct"] is None


# --------------------------------------------------------------------------
# Cash
# --------------------------------------------------------------------------

def test_cash_reconciliation_reports_balance_and_splits():
    cash = FakeCash(
        balance=1250.0,
        by_method={"cash": 500.0, "card": 600.0, "iris": 150.0},
        by_agent={"Maria": 800.0, "Nikos": 450.0},
    )
    report = build_service(cash=cash).cash_reconciliation(MANAGER, 1)
    assert report.total["balance"] == 1250.0
    methods = {r["label"]: r["amount"] for r in report.rows if r["group"] == "method"}
    assert sum(methods.values()) == 1250.0
    assert report.complete


def test_cash_drift_is_reported_not_reconciled_away():
    cash = FakeCash(balance=1000.0, by_method={"cash": 400.0, "card": 500.0})
    report = build_service(cash=cash).cash_reconciliation(MANAGER, 1)
    assert not report.complete
    assert any("differ by" in n for n in report.notes)


def test_unreadable_cash_balance_is_none_not_zero():
    class Broken(FakeCash):
        def balance(self, account_id):
            raise RuntimeError("ledger unavailable")

    report = build_service(cash=Broken()).cash_reconciliation(MANAGER, 1)
    assert report.total["balance"] is None
    assert any("balance could not be read" in n for n in report.notes)


# --------------------------------------------------------------------------
# Outstanding
# --------------------------------------------------------------------------

def test_outstanding_lists_only_what_is_still_owed():
    service = build_service(bookings=[
        {"id": 1, "reference": "B-1", "client_name": "A", "status": "confirmed",
         "gross_total": 500.0, "paid": 200.0},
        {"id": 2, "reference": "B-2", "client_name": "B", "status": "confirmed",
         "gross_total": 300.0, "paid": 300.0},
    ])
    report = service.outstanding(MANAGER, 1)
    assert [r["reference"] for r in report.rows] == ["B-1"]
    assert report.rows[0]["balance"] == 300.0
    assert report.total["balance"] == 300.0


def test_outstanding_sums_a_payment_list_when_there_is_no_total_field():
    service = build_service(bookings=[
        {"id": 1, "reference": "B-1", "status": "confirmed", "gross_total": 500.0,
         "payments": [{"amount": 100.0}, {"amount": 50.0}]},
    ])
    report = service.outstanding(MANAGER, 1)
    assert report.rows[0]["balance"] == 350.0


def test_unreadable_payment_history_shows_unavailable_not_paid_in_full():
    service = build_service(bookings=[
        {"id": 1, "reference": "B-1", "status": "confirmed", "gross_total": 500.0},
    ])
    report = service.outstanding(MANAGER, 1)
    row = report.rows[0]
    assert row["balance"] is None       # not 0.00, which would read as settled
    assert report.total["balance"] == 0.0
    assert any("no readable payment history" in n for n in report.notes)


# --------------------------------------------------------------------------
# Honesty of the report envelope
# --------------------------------------------------------------------------

def test_unreadable_quotes_are_counted_in_notes():
    class HalfBroken(FakeQuotes):
        def get(self, quote_id):
            return None if quote_id == 2 else super().get(quote_id)

    service = ReportingService(
        quote_service=HalfBroken([
            _quote(1, 2, "accepted", [_item("hotel", 100.0, 20.0)]),
            _quote(2, 2, "accepted", [_item("hotel", 100.0, 20.0)]),
        ]),
        booking_service=FakeBookings([]),
        cash_service=FakeCash(),
    )
    report = service.sales_by_agent(MANAGER, 1)
    assert not report.complete
    assert any("could not be opened" in n for n in report.notes)
    assert report.total["margin"] == 20.0   # the readable one, not an estimate of both


def test_dashboard_returns_every_section():
    data = build_service().dashboard(MANAGER, 1)
    for key in ("by_agent", "by_service", "monthly", "conversion", "cash", "outstanding"):
        assert key in data
