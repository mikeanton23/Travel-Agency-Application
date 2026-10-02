# -*- coding: utf-8 -*-

"""Service charges and VAT. The agent sets the charge; the system only
does the arithmetic and flags rule violations."""

from decimal import Decimal

from app.services.agency.pricing import (
    balance_due, charge_allowed, price_line, price_quote,
)


def test_international_line_carries_a_charge_and_no_vat():
    line = price_line(net_cost=800, service_charge=40,
                      is_domestic=False)
    assert line.net_cost == Decimal("800.00")
    assert line.service_charge == Decimal("40.00")
    assert line.vat == Decimal("0.00")
    assert line.total == Decimal("840.00")


def test_domestic_line_adds_vat_on_the_charge_only():
    """VAT applies to the agency's charge, never to the supplier fare."""
    line = price_line(net_cost=500, service_charge=50,
                      is_domestic=True, vat_rate=24)
    assert line.vat == Decimal("12.00")          # 24% of 50, not 550
    assert line.total == Decimal("562.00")


def test_quantity_multiplies_cost_and_charge():
    line = price_line(net_cost=30, service_charge=5, quantity=3)
    assert line.net_cost == Decimal("90.00")
    assert line.service_charge == Decimal("15.00")
    assert line.total == Decimal("105.00")


def test_rounding_is_half_up_like_a_till():
    line = price_line(net_cost="10.005", service_charge="0.005")
    assert line.net_cost == Decimal("10.01")
    assert line.service_charge == Decimal("0.01")


def test_ferry_and_air_tickets_may_not_carry_a_charge():
    assert not charge_allowed("ticket", "ferry")
    assert not charge_allowed("ticket", "air")
    assert charge_allowed("ticket", "rail")
    assert charge_allowed("hotel")

    flagged = price_line(net_cost=60, service_charge=5,
                         service_type="ticket", ticket_kind="ferry")
    assert flagged.warnings
    # The charge is still counted - the warning tells the agent to fix
    # it rather than silently changing their figures.
    assert flagged.service_charge == Decimal("5.00")


def test_zero_charge_on_a_ferry_raises_no_warning():
    clean = price_line(net_cost=60, service_charge=0,
                       service_type="ticket", ticket_kind="ferry")
    assert clean.warnings == []
    assert clean.total == Decimal("60.00")


def test_mixed_itinerary_totals():
    """A real quote: international flight, Greek hotel, transfer."""
    totals = price_quote([
        {"service_type": "ticket", "net_cost": 420,
         "service_charge": 0, "details": {"ticket_kind": "air"}},
        {"service_type": "hotel", "net_cost": 600,
         "service_charge": 60, "is_domestic": True, "vat_rate": 24},
        {"service_type": "transfer", "net_cost": 45,
         "service_charge": 10, "quantity": 2, "is_domestic": True,
         "vat_rate": 24},
    ])
    assert totals.net_cost == Decimal("1110.00")   # 420 + 600 + 90
    assert totals.service_charge == Decimal("80.00")  # 60 + 20
    assert totals.vat == Decimal("19.20")          # 24% of 80
    assert totals.total == Decimal("1209.20")
    # The agency keeps the charges; supplier commission is not guessed.
    assert totals.gross_margin == Decimal("80.00")


def test_empty_quote_totals_zero():
    totals = price_quote([])
    assert totals.total == Decimal("0.00")
    assert totals.warnings == []


def test_balance_due_handles_overpayment():
    assert balance_due(1209.20, 500) == Decimal("709.20")
    assert balance_due(100, 120) == Decimal("-20.00")
    assert balance_due(100, 100) == Decimal("0.00")
