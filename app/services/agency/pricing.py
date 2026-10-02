# -*- coding: utf-8 -*-

"""
Quote pricing: service charges, VAT and totals.

Rules as specified by the agency, encoded in one place so they can be
audited and changed without hunting through the UI:

* The **agent enters the service charge**. The system never invents a
  margin or a commission - it only arithmetic-checks what was typed.
* **International services** carry the agency's service charge.
* **Domestic (Greek) services** carry VAT at the agency's rate (24% by
  default) on the service charge.
* Air tickets and ferry tickets are flagged ``charge_allowed=False`` by
  default, because service charges do not apply to about 95% of
  airfares and are prohibited on ferry tickets. A charge entered
  against such a line is reported as a rule violation rather than
  silently accepted.

Everything here is pure arithmetic over plain values so it can be
tested without a database and reused by invoices and reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

# The five services the agency sells.
SERVICE_TYPES = ("hotel", "ticket", "transfer", "car_rental", "tour")

SERVICE_LABELS = {
    "hotel": "Hotel",
    "ticket": "Ticket (air / ferry / rail)",
    "transfer": "Transfer",
    "car_rental": "Car rental",
    "tour": "Tour / excursion",
}

# Ticket types where a service charge is not permitted or not customary.
NO_CHARGE_TICKET_KINDS = ("ferry", "air", "flight")


def money(value: Any) -> Decimal:
    """Convert to a 2-decimal Decimal, rounding half up like an till."""
    try:
        amount = Decimal(str(value if value is not None else 0))
    except Exception:
        amount = Decimal("0")
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class LinePrice:
    """The priced result of a single quote line."""

    net_cost: Decimal
    service_charge: Decimal
    vat: Decimal
    total: Decimal
    vat_rate: Decimal
    is_domestic: bool
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "net_cost": float(self.net_cost),
            "service_charge": float(self.service_charge),
            "vat": float(self.vat),
            "total": float(self.total),
            "vat_rate": float(self.vat_rate),
            "is_domestic": self.is_domestic,
            "warnings": self.warnings,
        }


def price_line(
    net_cost: Any,
    service_charge: Any = 0,
    quantity: int = 1,
    is_domestic: bool = False,
    vat_rate: Any = 24.0,
    service_type: str = "hotel",
    ticket_kind: Optional[str] = None,
) -> LinePrice:
    """Price one service line.

    ``quantity`` multiplies both the supplier cost and the charge, so
    three identical transfers cost three times as much.
    """
    quantity = max(1, int(quantity or 1))
    net = money(net_cost) * quantity
    charge = money(service_charge) * quantity
    warnings: List[str] = []

    if not charge_allowed(service_type, ticket_kind) and charge > 0:
        warnings.append(
            "A service charge is not permitted on this ticket type; "
            "check before issuing."
        )

    rate = money(vat_rate) if is_domestic else money(0)
    # VAT applies to the agency's charge, not to the supplier's fare.
    vat = (charge * rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)

    return LinePrice(
        net_cost=net.quantize(Decimal("0.01")),
        service_charge=charge.quantize(Decimal("0.01")),
        vat=vat,
        total=(net + charge + vat).quantize(Decimal("0.01")),
        vat_rate=rate,
        is_domestic=bool(is_domestic),
        warnings=warnings,
    )


def charge_allowed(service_type: str,
                   ticket_kind: Optional[str] = None) -> bool:
    """Whether a service charge may be added to this kind of line."""
    if service_type != "ticket":
        return True
    if not ticket_kind:
        # Unknown ticket kind: allow, but the UI should ask.
        return True
    return ticket_kind.strip().lower() not in NO_CHARGE_TICKET_KINDS


@dataclass
class QuoteTotals:
    net_cost: Decimal
    service_charge: Decimal
    vat: Decimal
    total: Decimal
    currency: str = "EUR"
    lines: List[LinePrice] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def gross_margin(self) -> Decimal:
        """What the agency keeps before its own costs: the charges.

        Deliberately not called profit - the agent works out the real
        margin, and the system does not guess at supplier commissions.
        """
        return self.service_charge

    def to_dict(self) -> Dict[str, Any]:
        return {
            "net_cost": float(self.net_cost),
            "service_charge": float(self.service_charge),
            "vat": float(self.vat),
            "total": float(self.total),
            "gross_margin": float(self.gross_margin),
            "currency": self.currency,
            "lines": [line.to_dict() for line in self.lines],
            "warnings": self.warnings,
        }


def price_quote(items: List[Dict[str, Any]],
                currency: str = "EUR",
                default_vat_rate: Any = 24.0) -> QuoteTotals:
    """Price a whole itinerary from plain line dictionaries."""
    lines: List[LinePrice] = []
    warnings: List[str] = []

    for index, item in enumerate(items or [], start=1):
        line = price_line(
            net_cost=item.get("net_cost"),
            service_charge=item.get("service_charge"),
            quantity=item.get("quantity", 1),
            is_domestic=bool(item.get("is_domestic")),
            vat_rate=item.get("vat_rate", default_vat_rate),
            service_type=item.get("service_type", "hotel"),
            ticket_kind=(item.get("details") or {}).get("ticket_kind")
            if isinstance(item.get("details"), dict) else None,
        )
        for warning in line.warnings:
            warnings.append(f"Line {index}: {warning}")
        lines.append(line)

    net = sum((line.net_cost for line in lines), Decimal("0"))
    charge = sum((line.service_charge for line in lines), Decimal("0"))
    vat = sum((line.vat for line in lines), Decimal("0"))
    return QuoteTotals(
        net_cost=net.quantize(Decimal("0.01")),
        service_charge=charge.quantize(Decimal("0.01")),
        vat=vat.quantize(Decimal("0.01")),
        total=(net + charge + vat).quantize(Decimal("0.01")),
        currency=currency,
        lines=lines,
        warnings=warnings,
    )


def balance_due(total: Any, paid: Any) -> Decimal:
    """What is still owed. Negative means the client overpaid."""
    return (money(total) - money(paid)).quantize(Decimal("0.01"))
