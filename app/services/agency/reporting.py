"""Agency reporting — Phase C.

Access boundary (set by the office owner, enforced here rather than in the UI):

    Accounting data, profits, margins and cash totals are visible ONLY to the
    owner/manager. Counter staff keep bookings, vouchers, documents, their own
    clients and their own quotes.

Every method on :class:`ReportingService` that returns money the office earns
starts with a hard guard. An agent calling one gets :class:`ReportingDenied`,
not a quietly emptied result — a silently blank report looks like "the office
made nothing this month", which is worse than an error.

Honesty rules carried over from the rest of the codebase:

* Nothing here estimates. Where a figure cannot be read from stored data the
  row carries ``None`` and a reason, and the UI prints "unavailable" instead
  of a zero. A zero and an unknown are different answers.
* Commission and profit margin are whatever the agent typed into the quote
  line (``service_charge``). The system never infers a margin from supplier
  cost, because the office calculates commission manually.
* Service charge is excluded on ferry tickets by law and on ~95% of airfares
  by policy; those lines therefore contribute 0 margin, and that is correct,
  not missing data.
* VAT (24%) applies to the service charge only and only on domestic
  (Greek) lines. It is the state's money, never the office's, so it is
  reported separately and never counted in margin.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Access
# --------------------------------------------------------------------------

from app.services.agency.access import (  # noqa: E402
    ADMIN,
    MANAGER,
    role_of,
    sees_whole_office,
)


class ReportingDenied(PermissionError):
    """Raised when a user without office-wide sight asks for financials."""


def may_view_financials(user: Any) -> bool:
    """True only for the owner/manager (and admin).

    Deliberately a separate predicate from :func:`sees_whole_office` even
    though it currently delegates to it: "can see the whole office's
    bookings" and "can see the whole office's money" are different
    permissions, and a future senior-agent role will want the first without
    the second. Call sites should use this one for money.
    """
    try:
        return bool(sees_whole_office(user))
    except Exception:  # pragma: no cover - defensive
        return role_of(user) in (MANAGER, ADMIN)


def require_financials(user: Any) -> None:
    """Guard. Raises :class:`ReportingDenied` for anyone but owner/manager."""
    if not may_view_financials(user):
        raise ReportingDenied(
            "Accounting and profit figures are restricted to the office "
            "owner/manager."
        )


# --------------------------------------------------------------------------
# Line arithmetic
# --------------------------------------------------------------------------

#: The five services the office sells.
SERVICE_TYPES: Tuple[str, ...] = (
    "hotel",
    "ticket",
    "transfer",
    "car_rental",
    "tour",
)

SERVICE_LABELS: Dict[str, str] = {
    "hotel": "Hotels",
    "ticket": "Tickets",
    "transfer": "Transfers",
    "car_rental": "Car rental",
    "tour": "Tours",
}

#: Quote statuses that mean the office actually earned the line.
EARNED_QUOTE_STATUSES: Tuple[str, ...] = ("accepted", "booked", "confirmed", "invoiced")

#: Quote statuses that are still in play.
OPEN_QUOTE_STATUSES: Tuple[str, ...] = ("draft", "sent", "pending")


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce to float without inventing a number for genuine junk."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money(value: float) -> float:
    """Round half-up to cents, the way an invoice rounds."""
    return float(int(round(_f(value) * 100.0 + (0.5 if value >= 0 else -0.5)))) / 100.0


@dataclass
class LineMoney:
    """What one quote line is worth, split the way the books need it."""

    service_type: str = ""
    net_cost: float = 0.0        # supplier cost — passes through, not income
    service_charge: float = 0.0  # the office's income, typed by the agent
    vat: float = 0.0             # state's money, on the charge only, domestic only
    gross: float = 0.0           # what the client pays for this line

    @property
    def margin(self) -> float:
        """The office's gross margin = the service charge, nothing else."""
        return self.service_charge


def line_money(item: Dict[str, Any]) -> LineMoney:
    """Price one stored quote/booking line.

    Reads only fields the quote service persists (``net_cost``,
    ``service_charge``, ``quantity``, ``is_domestic``, ``vat_rate``,
    ``service_type``). Mirrors ``app.services.agency.pricing`` on purpose;
    ``tests/test_agency_reporting.py`` asserts the two agree so they cannot
    drift apart silently.
    """
    qty = _f(item.get("quantity"), 1.0) or 1.0
    net = money(_f(item.get("net_cost")) * qty)
    charge = money(_f(item.get("service_charge")) * qty)

    domestic = bool(item.get("is_domestic"))
    rate = _f(item.get("vat_rate"), 24.0)
    # VAT on the service charge only, and only on domestic lines.
    vat = money(charge * rate / 100.0) if (domestic and charge) else 0.0

    return LineMoney(
        service_type=str(item.get("service_type") or "") or "other",
        net_cost=net,
        service_charge=charge,
        vat=vat,
        gross=money(net + charge + vat),
    )


@dataclass
class Totals:
    """A bucket of money. ``margin`` is the only line the office keeps."""

    label: str = ""
    count: int = 0
    net_cost: float = 0.0
    service_charge: float = 0.0
    vat: float = 0.0
    gross: float = 0.0

    @property
    def margin(self) -> float:
        return money(self.service_charge)

    @property
    def margin_pct(self) -> Optional[float]:
        """Margin as a share of gross. ``None`` when gross is zero.

        Not 0.0 — a zero-gross bucket has no percentage, and printing 0%
        would read as "we made nothing on sales we did make".
        """
        if not self.gross:
            return None
        return round(self.service_charge / self.gross * 100.0, 2)

    def add(self, line: LineMoney) -> None:
        self.count += 1
        self.net_cost = money(self.net_cost + line.net_cost)
        self.service_charge = money(self.service_charge + line.service_charge)
        self.vat = money(self.vat + line.vat)
        self.gross = money(self.gross + line.gross)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "net_cost": self.net_cost,
            "service_charge": self.service_charge,
            "vat": self.vat,
            "gross": self.gross,
            "margin": self.margin,
            "margin_pct": self.margin_pct,
        }


@dataclass
class Report:
    """A report plus an audit trail of what it could not read.

    ``notes`` is not decoration. It is how the report stays honest: if 3 of
    40 quotes could not be loaded, the owner sees that sentence next to the
    total instead of a confidently wrong number.
    """

    title: str = ""
    rows: List[Dict[str, Any]] = field(default_factory=list)
    total: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)
    period: Optional[str] = None

    @property
    def complete(self) -> bool:
        return not self.notes

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "rows": self.rows,
            "total": self.total,
            "notes": list(self.notes),
            "period": self.period,
            "complete": self.complete,
        }


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_DATE_KEYS = ("created_at", "created", "issued_at", "accepted_at", "date", "travel_start")


def _as_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def record_date(record: Dict[str, Any]) -> Optional[date]:
    """Best available date for a quote/booking, or ``None`` if unreadable."""
    for key in _DATE_KEYS:
        if key in record:
            parsed = _as_date(record.get(key))
            if parsed is not None:
                return parsed
    return None


def _in_period(when: Optional[date], start: Optional[date], end: Optional[date]) -> bool:
    if start is None and end is None:
        return True
    if when is None:
        return False  # undated records are excluded from a dated period, and counted in notes
    if start is not None and when < start:
        return False
    if end is not None and when > end:
        return False
    return True


def month_key(when: date) -> str:
    return f"{when.year:04d}-{when.month:02d}"


# --------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------

class ReportingService:
    """Office-wide financial reporting. Owner/manager only.

    Built on top of the quote, booking and cash services rather than on the
    ORM directly, so it reports exactly the numbers the desk shows the client
    and cannot drift from them.
    """

    def __init__(
        self,
        quote_service: Any = None,
        booking_service: Any = None,
        cash_service: Any = None,
    ) -> None:
        self._quotes = quote_service
        self._bookings = booking_service
        self._cash = cash_service

    # -- lazy wiring ------------------------------------------------------

    @property
    def quotes(self) -> Any:
        if self._quotes is None:
            from app.services.agency.quotes import QuoteService

            self._quotes = QuoteService()
        return self._quotes

    @property
    def bookings(self) -> Any:
        if self._bookings is None:
            from app.services.agency.bookings import BookingService

            self._bookings = BookingService()
        return self._bookings

    @property
    def cash(self) -> Any:
        if self._cash is None:
            from app.services.agency.cash import CashService

            self._cash = CashService()
        return self._cash

    # -- loading ----------------------------------------------------------

    def _load_quotes(
        self,
        agency_id: int,
        notes: List[str],
        statuses: Optional[Sequence[str]] = None,
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Fetch full quotes (with line items) for the whole office.

        ``list_for`` returns summaries; ``get`` returns the lines. Two calls
        per quote is slower than one join, but it guarantees the report's
        arithmetic is the same arithmetic the quote page showed the client.
        """
        try:
            summaries = self.quotes.list_for(agency_id, limit=limit) or []
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("reporting: could not list quotes for agency %s: %s", agency_id, exc)
            notes.append("Quotes could not be read, so sales figures are incomplete.")
            return []

        if len(summaries) >= limit:
            notes.append(
                f"Only the most recent {limit} quotes were read; older ones are not "
                "included in these totals."
            )

        wanted = {s.lower() for s in statuses} if statuses else None
        out: List[Dict[str, Any]] = []
        unreadable = 0

        for summary in summaries:
            status = str(summary.get("status") or "").lower()
            if wanted is not None and status not in wanted:
                continue
            quote_id = summary.get("id")
            if quote_id is None:
                unreadable += 1
                continue
            try:
                full = self.quotes.get(quote_id)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("reporting: quote %s unreadable: %s", quote_id, exc)
                full = None
            if not full:
                unreadable += 1
                continue
            merged = dict(summary)
            merged.update(full)
            out.append(merged)

        if unreadable:
            notes.append(
                f"{unreadable} quote(s) could not be opened and are excluded from "
                "these totals."
            )
        return out

    @staticmethod
    def _items(quote: Dict[str, Any]) -> List[Dict[str, Any]]:
        for key in ("items", "lines", "quote_items"):
            value = quote.get(key)
            if isinstance(value, list):
                return [i for i in value if isinstance(i, dict)]
        return []

    # -- reports ----------------------------------------------------------

    def sales_by_agent(
        self,
        user: Any,
        agency_id: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Report:
        """Earned sales, margin and VAT per agent.

        Counts only quotes in :data:`EARNED_QUOTE_STATUSES` — a sent quote is
        not revenue.
        """
        require_financials(user)
        report = Report(title="Sales by agent", period=_period_label(start, end))

        quotes = self._load_quotes(agency_id, report.notes, EARNED_QUOTE_STATUSES)
        buckets: Dict[Any, Totals] = {}
        names: Dict[Any, str] = {}
        grand = Totals(label="Office total")
        undated = 0

        for quote in quotes:
            when = record_date(quote)
            if not _in_period(when, start, end):
                if when is None:
                    undated += 1
                continue
            agent_id = quote.get("agent_id")
            bucket = buckets.setdefault(agent_id, Totals(label=_agent_label(quote)))
            names.setdefault(agent_id, bucket.label)
            for item in self._items(quote):
                line = line_money(item)
                bucket.add(line)
                grand.add(line)

        if undated:
            report.notes.append(
                f"{undated} earned quote(s) carry no usable date and fall outside "
                "this period."
            )

        report.rows = [
            b.as_dict()
            for b in sorted(buckets.values(), key=lambda t: t.margin, reverse=True)
        ]
        report.total = grand.as_dict()
        return report

    def sales_by_service(
        self,
        user: Any,
        agency_id: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Report:
        """Earned sales, margin and VAT per service type.

        Hotels, tickets, transfers, car rental and tours each get a row even
        at zero, so a service the office stopped selling is visible as a
        zero rather than a missing line.
        """
        require_financials(user)
        report = Report(title="Sales by service", period=_period_label(start, end))

        quotes = self._load_quotes(agency_id, report.notes, EARNED_QUOTE_STATUSES)
        buckets: Dict[str, Totals] = {
            key: Totals(label=SERVICE_LABELS[key]) for key in SERVICE_TYPES
        }
        grand = Totals(label="Office total")

        for quote in quotes:
            if not _in_period(record_date(quote), start, end):
                continue
            for item in self._items(quote):
                line = line_money(item)
                key = line.service_type if line.service_type in buckets else "other"
                if key == "other":
                    buckets.setdefault("other", Totals(label="Other"))
                buckets[key].add(line)
                grand.add(line)

        ordered = [buckets[k].as_dict() for k in SERVICE_TYPES]
        if "other" in buckets:
            ordered.append(buckets["other"].as_dict())
        report.rows = ordered
        report.total = grand.as_dict()
        return report

    def monthly_totals(
        self,
        user: Any,
        agency_id: int,
        months: int = 12,
    ) -> Report:
        """Earned sales and margin per calendar month, most recent last."""
        require_financials(user)
        report = Report(title="Monthly totals")

        quotes = self._load_quotes(agency_id, report.notes, EARNED_QUOTE_STATUSES)
        buckets: Dict[str, Totals] = {}
        grand = Totals(label="All months")
        undated = 0

        for quote in quotes:
            when = record_date(quote)
            if when is None:
                undated += 1
                continue
            bucket = buckets.setdefault(month_key(when), Totals(label=month_key(when)))
            for item in self._items(quote):
                line = line_money(item)
                bucket.add(line)
                grand.add(line)

        if undated:
            report.notes.append(
                f"{undated} earned quote(s) carry no usable date and are not in any "
                "month below."
            )

        keys = sorted(buckets)[-months:] if months else sorted(buckets)
        report.rows = [buckets[k].as_dict() for k in keys]
        report.total = grand.as_dict()
        return report

    def conversion(
        self,
        user: Any,
        agency_id: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Report:
        """Quote-to-booking conversion, per agent and office-wide.

        A counter metric, not a money one, but it belongs behind the same
        door: it ranks staff.
        """
        require_financials(user)
        report = Report(title="Quote conversion", period=_period_label(start, end))

        quotes = self._load_quotes(agency_id, report.notes)
        per_agent: Dict[Any, Dict[str, Any]] = {}
        totals = {"issued": 0, "earned": 0, "open": 0, "lost": 0}

        for quote in quotes:
            if not _in_period(record_date(quote), start, end):
                continue
            agent_id = quote.get("agent_id")
            row = per_agent.setdefault(
                agent_id,
                {"label": _agent_label(quote), "issued": 0, "earned": 0, "open": 0, "lost": 0},
            )
            status = str(quote.get("status") or "").lower()
            row["issued"] += 1
            totals["issued"] += 1
            if status in EARNED_QUOTE_STATUSES:
                row["earned"] += 1
                totals["earned"] += 1
            elif status in OPEN_QUOTE_STATUSES:
                row["open"] += 1
                totals["open"] += 1
            else:
                row["lost"] += 1
                totals["lost"] += 1

        for row in per_agent.values():
            decided = row["earned"] + row["lost"]
            # Rate over decided quotes only. Counting still-open quotes as
            # losses would punish an agent for quotes the client has not
            # answered yet.
            row["rate_pct"] = (
                round(row["earned"] / decided * 100.0, 1) if decided else None
            )

        decided_total = totals["earned"] + totals["lost"]
        totals["label"] = "Office total"
        totals["rate_pct"] = (
            round(totals["earned"] / decided_total * 100.0, 1) if decided_total else None
        )

        report.rows = sorted(
            per_agent.values(),
            key=lambda r: (r["rate_pct"] is None, -(r["rate_pct"] or 0), -r["issued"]),
        )
        report.total = totals
        if totals["open"]:
            report.notes.append(
                f"{totals['open']} quote(s) are still open and excluded from the "
                "conversion rate."
            )
        return report

    def cash_reconciliation(
        self,
        user: Any,
        agency_id: int,
        account_id: Optional[int] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Report:
        """Office cash account: balance, split by payment method and by agent.

        The single office account every representative's receipts land in.
        The ledger is append-only, so this reads it rather than recomputing
        it — if the ledger and the quotes disagree, that disagreement is the
        finding, and it is reported, not reconciled away.
        """
        require_financials(user)
        report = Report(title="Office cash", period=_period_label(start, end))

        if account_id is None:
            try:
                account = self.cash.ensure_account(agency_id)
                account_id = account.get("id") if isinstance(account, dict) else account
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("reporting: no cash account for agency %s: %s", agency_id, exc)
                report.notes.append("The office cash account could not be read.")
                return report

        rows: List[Dict[str, Any]] = []

        balance: Optional[float] = None
        try:
            balance = money(_f(self.cash.balance(account_id)))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("reporting: cash balance unreadable: %s", exc)
            report.notes.append("The current office balance could not be read.")

        by_method = _safe_mapping(self.cash, "totals_by_method", account_id, report.notes,
                                  "Totals by payment method could not be read.")
        by_agent = _safe_mapping(self.cash, "totals_by_agent", account_id, report.notes,
                                 "Totals by agent could not be read.")

        for key, amount in sorted(by_method.items(), key=lambda kv: -_f(kv[1])):
            rows.append({
                "group": "method",
                "label": _method_label(key),
                "amount": money(_f(amount)),
            })
        for key, amount in sorted(by_agent.items(), key=lambda kv: -_f(kv[1])):
            rows.append({
                "group": "agent",
                "label": str(key),
                "amount": money(_f(amount)),
            })

        report.rows = rows
        report.total = {
            "label": "Office balance",
            "balance": balance,
            "methods_sum": money(sum(_f(v) for v in by_method.values())) if by_method else None,
        }

        if balance is not None and by_method:
            drift = money(balance - sum(_f(v) for v in by_method.values()))
            if abs(drift) >= 0.01:
                report.notes.append(
                    f"Balance and payment-method totals differ by {drift:.2f}. "
                    "Check for movements recorded without a method."
                )
        return report

    def outstanding(
        self,
        user: Any,
        agency_id: int,
        limit: int = 500,
    ) -> Report:
        """Confirmed bookings with money still owed by the client.

        Where a booking's payment history cannot be read the row carries
        ``balance: None`` — never 0.00, which would read as "paid in full".
        """
        require_financials(user)
        report = Report(title="Outstanding balances")

        try:
            bookings = self.bookings.list_for(agency_id, limit=limit) or []
        except TypeError:
            try:
                bookings = self.bookings.list_for(agency_id) or []
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("reporting: bookings unreadable: %s", exc)
                report.notes.append("Bookings could not be read.")
                return report
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("reporting: bookings unreadable: %s", exc)
            report.notes.append("Bookings could not be read.")
            return report

        rows: List[Dict[str, Any]] = []
        total_due = 0.0
        unknown = 0

        for summary in bookings:
            booking_id = summary.get("id")
            booking = summary
            if booking_id is not None:
                try:
                    full = self.bookings.get(booking_id)
                    if full:
                        booking = {**summary, **full}
                except Exception as exc:  # pragma: no cover - defensive
                    log.debug("reporting: booking %s unreadable: %s", booking_id, exc)

            gross = _booking_gross(booking, self._items(booking))
            paid = _booking_paid(booking)

            if gross is None or paid is None:
                unknown += 1
                rows.append({
                    "reference": booking.get("reference") or booking_id,
                    "client": booking.get("client_name") or booking.get("client") or "",
                    "status": booking.get("status") or "",
                    "gross": gross,
                    "paid": paid,
                    "balance": None,
                })
                continue

            balance = money(gross - paid)
            if balance <= 0.0:
                continue
            total_due = money(total_due + balance)
            rows.append({
                "reference": booking.get("reference") or booking_id,
                "client": booking.get("client_name") or booking.get("client") or "",
                "status": booking.get("status") or "",
                "gross": gross,
                "paid": paid,
                "balance": balance,
            })

        if unknown:
            report.notes.append(
                f"{unknown} booking(s) have no readable payment history; their "
                "balance is shown as unavailable and is not in the total."
            )

        report.rows = sorted(
            rows, key=lambda r: (r["balance"] is None, -(r["balance"] or 0))
        )
        report.total = {"label": "Total owed", "balance": money(total_due)}
        return report

    def dashboard(
        self,
        user: Any,
        agency_id: int,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Everything the owner's one screen needs, in one call."""
        require_financials(user)
        return {
            "by_agent": self.sales_by_agent(user, agency_id, start, end).as_dict(),
            "by_service": self.sales_by_service(user, agency_id, start, end).as_dict(),
            "monthly": self.monthly_totals(user, agency_id).as_dict(),
            "conversion": self.conversion(user, agency_id, start, end).as_dict(),
            "cash": self.cash_reconciliation(user, agency_id, None, start, end).as_dict(),
            "outstanding": self.outstanding(user, agency_id).as_dict(),
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _agent_label(quote: Dict[str, Any]) -> str:
    for key in ("agent_name", "agent_full_name", "agent_email", "agent"):
        value = quote.get(key)
        if value:
            return str(value)
    agent_id = quote.get("agent_id")
    return f"Agent #{agent_id}" if agent_id is not None else "Unassigned"


def _method_label(key: Any) -> str:
    try:
        from app.services.agency.cash import METHOD_LABELS

        return str(METHOD_LABELS.get(key, key))
    except Exception:  # pragma: no cover - defensive
        return str(key)


def _period_label(start: Optional[date], end: Optional[date]) -> Optional[str]:
    if start and end:
        return f"{start.isoformat()} to {end.isoformat()}"
    if start:
        return f"from {start.isoformat()}"
    if end:
        return f"until {end.isoformat()}"
    return None


def _safe_mapping(
    service: Any,
    method: str,
    account_id: Any,
    notes: List[str],
    failure_note: str,
) -> Dict[Any, Any]:
    fn = getattr(service, method, None)
    if not callable(fn):
        notes.append(failure_note)
        return {}
    try:
        result = fn(account_id)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("reporting: %s failed: %s", method, exc)
        notes.append(failure_note)
        return {}
    if isinstance(result, dict):
        return result
    if isinstance(result, Iterable):
        out: Dict[Any, Any] = {}
        for entry in result:
            if isinstance(entry, dict):
                key = entry.get("method") or entry.get("agent_id") or entry.get("label")
                out[key] = entry.get("total", entry.get("amount"))
            elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                out[entry[0]] = entry[1]
        return out
    notes.append(failure_note)
    return {}


def _booking_gross(booking: Dict[str, Any], items: List[Dict[str, Any]]) -> Optional[float]:
    for key in ("gross_total", "total_gross", "total", "gross"):
        if key in booking and booking[key] is not None:
            return money(_f(booking[key]))
    if items:
        return money(sum(line_money(i).gross for i in items))
    return None


def _booking_paid(booking: Dict[str, Any]) -> Optional[float]:
    for key in ("paid", "amount_paid", "total_paid", "payments_total"):
        if key in booking and booking[key] is not None:
            return money(_f(booking[key]))
    payments = booking.get("payments")
    if isinstance(payments, list):
        return money(sum(_f(p.get("amount")) for p in payments if isinstance(p, dict)))
    return None


#: Shared instance, matching the pattern used by the other agency services.
reporting_service = ReportingService()

__all__ = [
    "EARNED_QUOTE_STATUSES",
    "LineMoney",
    "OPEN_QUOTE_STATUSES",
    "Report",
    "ReportingDenied",
    "ReportingService",
    "SERVICE_LABELS",
    "SERVICE_TYPES",
    "Totals",
    "line_money",
    "may_view_financials",
    "money",
    "month_key",
    "record_date",
    "reporting_service",
    "require_financials",
]
