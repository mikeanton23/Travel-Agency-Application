"""Agency reporting pages — Phase C.

Route: ``/agency/reports`` — owner/manager only.

The guard here is a redirect, not a hidden widget. An agent who types the URL
lands back on the desk with a short message; the figures are never rendered
into a page they could read with devtools. The service layer refuses them
independently (``reporting.require_financials``), so this page being wrong
would still not leak numbers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.agency.reporting import (
    ReportingDenied,
    may_view_financials,
    reporting_service,
)
from app.ui.agency_common import (
    agency_shell,
    ensure_agency,
    money_label,
    require_agent,
)

log = logging.getLogger(__name__)

PERIODS: Dict[str, int] = {
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 12 months": 365,
    "All time": 0,
}


def _period_dates(choice: str) -> tuple[Optional[date], Optional[date]]:
    days = PERIODS.get(choice, 30)
    if not days:
        return None, None
    today = date.today()
    return today - timedelta(days=days), today


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def _notes(report: Dict[str, Any]) -> None:
    """Print what the report could not read, right next to the figures."""
    for note in report.get("notes") or []:
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.icon("info").style("color: #b45309")
            ui.label(note).style("color: #b45309; font-size: 0.8rem")


def _cell(value: Any, money: bool = False, suffix: str = "") -> None:
    """One table cell. ``None`` prints as 'unavailable', never as zero."""
    if value is None:
        ui.label("unavailable").style("color: #94a3b8; font-style: italic")
        return
    if money:
        # money_label() returns a string; it does not create an element.
        ui.label(money_label(value))
        return
    ui.label(f"{value}{suffix}")


def _totals_table(report: Dict[str, Any], first_column: str) -> None:
    rows: List[Dict[str, Any]] = report.get("rows") or []
    total = report.get("total")

    if not rows:
        ui.label("No sales recorded for this period.").style("color: #64748b")
        _notes(report)
        return

    columns = [
        {"name": "label", "label": first_column, "field": "label", "align": "left"},
        {"name": "count", "label": "Lines", "field": "count", "align": "right"},
        {"name": "net_cost", "label": "Supplier cost", "field": "net_cost", "align": "right"},
        {"name": "gross", "label": "Client pays", "field": "gross", "align": "right"},
        {"name": "vat", "label": "VAT (24%)", "field": "vat", "align": "right"},
        {"name": "margin", "label": "Office margin", "field": "margin", "align": "right"},
        {"name": "margin_pct", "label": "Margin %", "field": "margin_pct", "align": "right"},
    ]

    display: List[Dict[str, Any]] = []
    for row in rows:
        display.append({
            "label": row.get("label", ""),
            "count": row.get("count", 0),
            "net_cost": f"{row.get('net_cost', 0):,.2f}",
            "gross": f"{row.get('gross', 0):,.2f}",
            "vat": f"{row.get('vat', 0):,.2f}",
            "margin": f"{row.get('margin', 0):,.2f}",
            "margin_pct": "—" if row.get("margin_pct") is None else f"{row['margin_pct']}%",
        })

    ui.table(columns=columns, rows=display, row_key="label").classes("w-full")

    if total:
        with ui.row().classes("w-full justify-end gap-6 mt-2"):
            ui.label(f"Client pays {total.get('gross', 0):,.2f}").style("color: #475569")
            ui.label(f"VAT {total.get('vat', 0):,.2f}").style("color: #475569")
            ui.label(f"Office margin {total.get('margin', 0):,.2f}").style(
                "font-weight: 700; color: #0f172a"
            )
    _notes(report)


def _conversion_table(report: Dict[str, Any]) -> None:
    rows = report.get("rows") or []
    if not rows:
        ui.label("No quotes issued for this period.").style("color: #64748b")
        _notes(report)
        return

    columns = [
        {"name": "label", "label": "Agent", "field": "label", "align": "left"},
        {"name": "issued", "label": "Issued", "field": "issued", "align": "right"},
        {"name": "earned", "label": "Won", "field": "earned", "align": "right"},
        {"name": "lost", "label": "Lost", "field": "lost", "align": "right"},
        {"name": "open", "label": "Still open", "field": "open", "align": "right"},
        {"name": "rate_pct", "label": "Win rate", "field": "rate_pct", "align": "right"},
    ]
    display = [
        {
            "label": r.get("label", ""),
            "issued": r.get("issued", 0),
            "earned": r.get("earned", 0),
            "lost": r.get("lost", 0),
            "open": r.get("open", 0),
            "rate_pct": "—" if r.get("rate_pct") is None else f"{r['rate_pct']}%",
        }
        for r in rows
    ]
    ui.table(columns=columns, rows=display, row_key="label").classes("w-full")
    ui.label(
        "Win rate counts decided quotes only — quotes the client has not answered "
        "yet are listed separately and do not count against an agent."
    ).style("color: #64748b; font-size: 0.8rem")
    _notes(report)


def _cash_panel(report: Dict[str, Any]) -> None:
    total = report.get("total") or {}
    balance = total.get("balance")

    with ui.row().classes("items-baseline gap-3"):
        ui.label("Office balance").style("color: #64748b")
        if balance is None:
            ui.label("unavailable").style("color: #94a3b8; font-style: italic")
        else:
            ui.label(f"{balance:,.2f}").style("font-size: 1.6rem; font-weight: 700")

    rows = report.get("rows") or []
    methods = [r for r in rows if r.get("group") == "method"]
    agents = [r for r in rows if r.get("group") == "agent"]

    with ui.row().classes("w-full gap-6 flex-wrap mt-3"):
        for title, subset in (("By payment method", methods), ("Deposited by", agents)):
            with ui.column().classes("gap-1").style("min-width: 240px"):
                ui.label(title).style("font-weight: 600")
                if not subset:
                    ui.label("No movements recorded.").style("color: #64748b")
                for row in subset:
                    with ui.row().classes("w-full justify-between"):
                        ui.label(str(row.get("label", "")))
                        ui.label(f"{row.get('amount', 0):,.2f}")
    _notes(report)


def _outstanding_table(report: Dict[str, Any]) -> None:
    rows = report.get("rows") or []
    total = report.get("total") or {}

    if not rows:
        ui.label("Nothing outstanding — every booking is settled.").style("color: #15803d")
        _notes(report)
        return

    columns = [
        {"name": "reference", "label": "Booking", "field": "reference", "align": "left"},
        {"name": "client", "label": "Client", "field": "client", "align": "left"},
        {"name": "status", "label": "Status", "field": "status", "align": "left"},
        {"name": "gross", "label": "Total", "field": "gross", "align": "right"},
        {"name": "paid", "label": "Paid", "field": "paid", "align": "right"},
        {"name": "balance", "label": "Owed", "field": "balance", "align": "right"},
    ]
    display = []
    for r in rows:
        display.append({
            "reference": str(r.get("reference") or ""),
            "client": str(r.get("client") or ""),
            "status": str(r.get("status") or ""),
            "gross": "unavailable" if r.get("gross") is None else f"{r['gross']:,.2f}",
            "paid": "unavailable" if r.get("paid") is None else f"{r['paid']:,.2f}",
            "balance": "unavailable" if r.get("balance") is None else f"{r['balance']:,.2f}",
        })
    ui.table(columns=columns, rows=display, row_key="reference").classes("w-full")
    with ui.row().classes("w-full justify-end mt-2"):
        ui.label(f"Total owed {total.get('balance', 0):,.2f}").style(
            "font-weight: 700; color: #0f172a"
        )
    _notes(report)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

@ui.page("/agency/reports")
async def agency_reports_page() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')

    user = require_agent()
    if user is None:
        return

    if not may_view_financials(user):
        # Redirect rather than render-and-hide. Called from the page body, so
        # a slot is active and navigate.to is safe here.
        ui.notify(
            "Reports are available to the office manager only.",
            type="warning",
        )
        ui.navigate.to("/agency")
        return

    agency_id = ensure_agency(user)
    if agency_id is None:
        return

    period = {"choice": "Last 30 days"}
    body = None

    async def load() -> None:
        start, end = _period_dates(period["choice"])
        body.clear()
        with body:
            spinner = ui.row().classes("items-center gap-2")
            with spinner:
                ui.spinner(size="sm")
                ui.label("Reading the books...").style("color: #64748b")

        try:
            data = await asyncio.to_thread(
                reporting_service.dashboard, user, agency_id, start, end
            )
        except ReportingDenied:
            body.clear()
            with body:
                ui.label(
                    "Reports are available to the office manager only."
                ).style("color: #b45309")
            return
        except Exception as exc:
            log.exception("agency reports failed")
            body.clear()
            with body:
                ui.label("The reports could not be built.").style(
                    "font-weight: 600; color: #dc2626"
                )
                ui.label(str(exc)).style("color: #64748b; font-size: 0.8rem")
            return

        body.clear()
        with body:
            _render(data)

    def _render(data: Dict[str, Any]) -> None:
        by_agent = data.get("by_agent") or {}
        total = by_agent.get("total") or {}

        with ui.row().classes("w-full gap-4 flex-wrap"):
            for label, value in (
                ("Client billings", total.get("gross")),
                ("Supplier cost", total.get("net_cost")),
                ("Office margin", total.get("margin")),
                ("VAT collected", total.get("vat")),
            ):
                with ui.card().classes("flex-1").style("min-width: 180px"):
                    ui.label(label).style("color: #64748b; font-size: 0.8rem")
                    if value is None:
                        ui.label("unavailable").style(
                            "color: #94a3b8; font-style: italic"
                        )
                    else:
                        ui.label(f"{value:,.2f}").style(
                            "font-size: 1.5rem; font-weight: 700"
                        )
            ui.label(
                "Margin is the service charges your agents entered. The system does "
                "not calculate commission."
            ).style("color: #64748b; font-size: 0.75rem; width: 100%")

        with ui.card().classes("w-full mt-4"):
            ui.label("Sales by agent").style("font-weight: 600; font-size: 1.05rem")
            _totals_table(by_agent, "Agent")

        with ui.card().classes("w-full mt-4"):
            ui.label("Sales by service").style("font-weight: 600; font-size: 1.05rem")
            _totals_table(data.get("by_service") or {}, "Service")

        with ui.card().classes("w-full mt-4"):
            ui.label("Monthly totals").style("font-weight: 600; font-size: 1.05rem")
            _totals_table(data.get("monthly") or {}, "Month")

        with ui.card().classes("w-full mt-4"):
            ui.label("Office cash").style("font-weight: 600; font-size: 1.05rem")
            _cash_panel(data.get("cash") or {})

        with ui.card().classes("w-full mt-4"):
            ui.label("Outstanding balances").style(
                "font-weight: 600; font-size: 1.05rem"
            )
            _outstanding_table(data.get("outstanding") or {})

        with ui.card().classes("w-full mt-4"):
            ui.label("Quote conversion").style("font-weight: 600; font-size: 1.05rem")
            _conversion_table(data.get("conversion") or {})

    with agency_shell(user, "Reports"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("Reports").style("font-size: 1.5rem; font-weight: 700")
                ui.label("Visible to the office manager only.").style(
                    "color: #64748b; font-size: 0.85rem"
                )

            async def on_period(event: Any) -> None:
                # An async handler, not create_task(): NiceGUI awaits it with
                # the client's slot stack in place. Spawning a bare task here
                # is what makes `ui.navigate.to` blow up elsewhere in the
                # agency UI.
                period["choice"] = event.value
                await load()

            ui.select(
                list(PERIODS),
                value=period["choice"],
                on_change=on_period,
            ).props("dense outlined").style("min-width: 180px")

        body = ui.column().classes("w-full gap-0 mt-2")
        await load()
