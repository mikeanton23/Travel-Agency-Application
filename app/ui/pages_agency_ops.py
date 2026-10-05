# -*- coding: utf-8 -*-

"""
Bookings, documents and the cash desk.

Confirmation is deliberately explicit: until a supplier integration is
contracted, the agent books in the supplier's own system and records
the reference here. The screen says so rather than implying the
software confirmed anything itself.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.agency.cash import (
    METHOD_LABELS, PAYMENT_METHODS, CashError, cash_service,
)
from app.services.agency.pricing import SERVICE_LABELS
from app.ui.agency_common import (
    SERVICE_ICONS, agency_shell, ensure_agency, money_label,
    require_agent, status_chip,
)
from app.ui.helpers import safe_clear


def _bookings():
    from app.services.agency.bookings import booking_service
    return booking_service


def _invoices():
    from app.services.agency.invoicing import invoice_service
    return invoice_service


def _documents():
    from app.services.agency.documents import document_service
    return document_service


# ----------------------------------------------------------------------
# /agency/bookings
# ----------------------------------------------------------------------

@ui.page("/agency/bookings")
def agency_bookings() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Bookings", user):
        ui.label("Bookings").classes(
            "tv-display text-2xl font-semibold")
        rows = ui.column().classes("w-full gap-2")

        async def load() -> None:
            try:
                bookings = await asyncio.to_thread(
                    _bookings().list_for, agency_id,
                    None if user.is_manager else user.id, None, 200)
            except Exception as exc:
                if safe_clear(rows):
                    with rows:
                        ui.label(f"Could not load bookings: {exc}") \
                            .classes("text-sm text-red-600")
                return
            if not safe_clear(rows):
                return
            with rows:
                ui.label(f"{len(bookings)} bookings").classes(
                    "tv-mono text-xs tv-muted")
                if not bookings:
                    ui.label(
                        "Nothing booked yet. Accept a quote and "
                        "convert it."
                    ).classes("text-sm tv-muted")
                for booking in bookings:
                    with ui.card().classes(
                        "tv-glass w-full p-3 cursor-pointer"
                    ).on("click", lambda b=booking: ui.navigate.to(
                            f"/agency/bookings/{b['id']}")):
                        with ui.row().classes(
                            "w-full items-center gap-3"
                        ):
                            ui.label(booking.get("reference", "")) \
                                .classes("tv-mono text-xs tv-muted")
                            ui.label(
                                booking.get("lead_passenger")
                                or "Booking").classes(
                                "font-medium flex-grow")
                            status_chip(booking.get("status", "draft"))
                            ui.label(money_label(
                                booking.get("total_amount", 0),
                                booking.get("currency", "EUR"))) \
                                .classes("tv-mono text-sm")

        ui.timer(0.1, load, once=True)


# ----------------------------------------------------------------------
# /agency/bookings/{booking_id}
# ----------------------------------------------------------------------

@ui.page("/agency/bookings/{booking_id}")
def agency_booking_detail(booking_id: int) -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Booking", user):
        body = ui.column().classes("w-full gap-4")

        async def load() -> None:
            booking = await asyncio.to_thread(_bookings().get,
                                              booking_id)
            if not safe_clear(body):
                return
            with body:
                if booking is None:
                    ui.label("Booking not found").classes(
                        "tv-display text-xl font-semibold")
                    return
                if not user.is_manager and \
                        booking.get("agent_id") != user.id:
                    ui.label("Not your booking").classes(
                        "tv-display text-xl font-semibold")
                    return

                currency = booking.get("currency", "EUR")
                with ui.row().classes("w-full items-center gap-3"):
                    ui.label(booking.get("lead_passenger")
                             or "Booking").classes(
                        "tv-display text-2xl font-semibold")
                    status_chip(booking.get("status", "draft"))
                    ui.space()
                    ui.label(booking.get("reference", "")).classes(
                        "tv-mono text-sm tv-muted")

                # ---- money ----
                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    for label, key in (("Total", "total_amount"),
                                       ("Paid", "paid_amount"),
                                       ("Balance due", "balance_due")):
                        with ui.row().classes("w-full gap-3"):
                            ui.label(label).classes(
                                "tv-mono text-xs tv-muted flex-grow")
                            ui.label(money_label(
                                booking.get(key, 0), currency)).classes(
                                "tv-mono text-sm"
                                + (" font-semibold"
                                   if key == "balance_due" else ""))
                    _payment_form(booking, user, agency_id, load)

                # ---- services ----
                ui.label("Services").classes(
                    "tv-display text-lg font-semibold")
                ui.label(
                    "Book with the supplier in their own system, then "
                    "record the reference here. Automatic confirmation "
                    "needs a contracted integration."
                ).classes("text-xs tv-muted")
                for item in booking.get("items", []):
                    _booking_item(item, currency, user, load)

                # ---- documents ----
                _documents_panel(booking, user, load)

        ui.timer(0.1, load, once=True)


def _booking_item(item: Dict[str, Any], currency: str,
                  user: Any, reload) -> None:
    with ui.card().classes("tv-glass w-full p-3 gap-2"):
        with ui.row().classes("w-full items-start gap-3"):
            ui.icon(SERVICE_ICONS.get(item["service_type"],
                                      "sym_r_sell")).classes(
                "text-primary")
            with ui.column().classes("gap-0 flex-grow"):
                ui.label(item["title"]).classes("font-medium")
                bits = [SERVICE_LABELS.get(item["service_type"],
                                           item["service_type"])]
                if item.get("supplier"):
                    bits.append(item["supplier"])
                if item.get("starts_on"):
                    bits.append(item["starts_on"])
                ui.label(" - ".join(bits)).classes("text-xs tv-muted")
                reference = item.get("confirmation_reference")
                if reference:
                    ui.label(f"Reference: {reference}").classes(
                        "tv-mono text-xs text-primary")
                else:
                    ui.label("Not confirmed with the supplier").classes(
                        "tv-mono text-xs text-amber-700")
            with ui.column().classes("items-end gap-1"):
                status_chip(item.get("confirmation_status", "pending"))
                ui.label(money_label(
                    (item.get("net_cost") or 0)
                    + (item.get("service_charge") or 0),
                    currency)).classes("tv-mono text-sm")

        with ui.row().classes("w-full gap-2 items-center"):
            ref_in = ui.input(
                placeholder="PNR / voucher / confirmation code"
            ).props("dense outlined").classes("flex-grow")

            async def confirm() -> None:
                if not (ref_in.value or "").strip():
                    ui.notify(
                        "Enter the reference the supplier gave you.",
                        type="warning")
                    return
                try:
                    await asyncio.to_thread(
                        _bookings().confirm_item, item["id"],
                        ref_in.value.strip(), user.id)
                except Exception as exc:
                    ui.notify(f"Could not confirm: {exc}",
                              type="negative")
                    return
                ui.notify("Line confirmed", type="positive")
                await reload()

            ui.button("Confirm", on_click=confirm).props(
                "unelevated dense color=primary no-caps "
                "icon=sym_r_check")

            async def try_supplier() -> None:
                try:
                    result = await asyncio.to_thread(
                        _bookings().confirm_via_supplier, item["id"])
                except Exception as exc:
                    ui.notify(str(exc), type="warning", timeout=8000)
                    return
                ui.notify(str(result.get("message") or result),
                          type="info", timeout=8000)
                await reload()

            ui.button("Try supplier", on_click=try_supplier).props(
                "flat dense no-caps icon=sym_r_cloud_sync").tooltip(
                "Attempt automatic confirmation")


def _payment_form(booking: Dict[str, Any], user: Any,
                  agency_id: int, reload) -> None:
    with ui.row().classes("w-full gap-2 items-end pt-2"):
        amount_in = ui.number(
            "Take payment", value=booking.get("balance_due") or 0,
            min=0).props("dense outlined").classes("w-40")
        method_in = ui.select(
            {m: METHOD_LABELS[m] for m in PAYMENT_METHODS},
            value="cash", label="Method",
        ).props("dense outlined").classes("w-52")
        ref_in = ui.input("Reference").props(
            "dense outlined").classes("flex-grow")

        async def take() -> None:
            try:
                await asyncio.to_thread(
                    _bookings().record_payment, booking["id"],
                    float(amount_in.value or 0), method_in.value,
                    user.id, ref_in.value or None)
            except Exception as exc:
                ui.notify(f"Could not record the payment: {exc}",
                          type="negative", timeout=10000)
                return
            ui.notify("Payment recorded in the office account",
                      type="positive")
            await reload()

        ui.button("Record", on_click=take).props(
            "unelevated color=primary no-caps icon=sym_r_payments")


def _documents_panel(booking: Dict[str, Any], user: Any,
                     reload) -> None:
    ui.label("Documents").classes(
        "tv-display text-lg font-semibold pt-2")
    with ui.row().classes("w-full gap-2 flex-wrap"):

        async def make_invoice() -> None:
            try:
                invoice = await asyncio.to_thread(
                    _invoices().issue_for_booking, booking["id"])
            except Exception as exc:
                ui.notify(f"Could not issue the invoice: {exc}",
                          type="negative", timeout=10000)
                return
            ui.notify(
                f"Invoice {invoice.get('number', '')} issued",
                type="positive")
            await reload()

        ui.button("Issue invoice", on_click=make_invoice).props(
            "unelevated color=primary no-caps icon=sym_r_receipt_long")

        async def make_pack() -> None:
            try:
                document = await asyncio.to_thread(
                    _documents().travel_pack, booking["id"], user.id)
            except Exception as exc:
                ui.notify(f"Could not build the pack: {exc}",
                          type="negative", timeout=10000)
                return
            _offer_download(document)

        ui.button("Travel pack", on_click=make_pack).props(
            "outline no-caps icon=sym_r_description")

    # Vouchers are per confirmed service.
    for item in booking.get("items", []):
        if not item.get("confirmation_reference"):
            continue

        async def make_voucher(target=item) -> None:
            try:
                document = await asyncio.to_thread(
                    _documents().voucher, target["id"], user.id)
            except Exception as exc:
                ui.notify(f"Could not build the voucher: {exc}",
                          type="negative", timeout=10000)
                return
            _offer_download(document)

        ui.button(f"Voucher: {item['title'][:40]}",
                  on_click=make_voucher).props(
            "flat dense no-caps icon=sym_r_local_activity")


def _offer_download(document: Dict[str, Any]) -> None:
    """Hand the generated PDF to the agent.

    The document service returns the PDF as base64 in ``content``
    rather than writing a file, so it is decoded and streamed straight
    to the browser.
    """
    import base64

    content = document.get("content")
    filename = document.get("filename") or "document.pdf"
    if not content:
        ui.notify(
            "The document record was created but carries no PDF.",
            type="warning")
        return
    try:
        payload = base64.b64decode(content)
    except Exception:
        ui.notify("The stored document could not be decoded.",
                  type="negative")
        return
    ui.download(payload, filename)
    ui.notify(f"{filename} ready", type="positive")


# ----------------------------------------------------------------------
# /agency/cash
# ----------------------------------------------------------------------

@ui.page("/agency/cash")
def agency_cash() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Cash", user):
        ui.label("Cash desk").classes(
            "tv-display text-2xl font-semibold")
        ui.label(
            "Every receipt goes into the one office account. Mistakes "
            "are corrected by a reversing entry, never by editing - "
            "the ledger stays auditable."
        ).classes("text-sm tv-muted")

        summary = ui.column().classes("w-full gap-2")
        ledger = ui.column().classes("w-full gap-2")

        async def load() -> None:
            account = await asyncio.to_thread(
                cash_service.ensure_account, agency_id)
            movements = await asyncio.to_thread(
                cash_service.movements, account, 200,
                None if user.is_manager else user.id)

            if safe_clear(summary):
                with summary:
                    if user.is_manager:
                        balance = await asyncio.to_thread(
                            cash_service.balance, account)
                        by_method = await asyncio.to_thread(
                            cash_service.totals_by_method, account)
                        with ui.card().classes(
                            "tv-glass w-full p-4 gap-1"
                        ):
                            ui.label("Office balance").classes(
                                "tv-mono text-xs tv-muted uppercase")
                            ui.label(money_label(float(balance))) \
                                .classes(
                                "tv-mono text-3xl font-semibold")
                            with ui.row().classes("gap-4 pt-1"):
                                for method, total in by_method.items():
                                    ui.label(
                                        f"{METHOD_LABELS[method]}: "
                                        f"{total:,.2f}").classes(
                                        "tv-mono text-xs tv-muted")
                    else:
                        taken = sum(m["amount"] for m in movements
                                    if m["direction"] == "in")
                        with ui.card().classes(
                            "tv-glass w-full p-4 gap-0"
                        ):
                            ui.label("Taken by you").classes(
                                "tv-mono text-xs tv-muted uppercase")
                            ui.label(money_label(taken)).classes(
                                "tv-mono text-2xl font-semibold")
                            ui.label(
                                "The office balance is visible to "
                                "managers."
                            ).classes("text-xs tv-muted")

                    _manual_entry(account, user, load)

            if safe_clear(ledger):
                with ledger:
                    ui.label("Movements").classes(
                        "tv-display text-lg font-semibold")
                    if not movements:
                        ui.label("Nothing recorded yet.").classes(
                            "text-sm tv-muted")
                    for movement in movements:
                        _movement_row(movement, user, load)

        ui.timer(0.1, load, once=True)


def _manual_entry(account: int, user: Any, reload) -> None:
    with ui.expansion("Record a movement",
                      icon="sym_r_add").classes("w-full").props("dense"):
        with ui.row().classes("w-full gap-2 items-end pt-2"):
            amount_in = ui.number("Amount", value=0, min=0).props(
                "dense outlined").classes("w-32")
            method_in = ui.select(
                {m: METHOD_LABELS[m] for m in PAYMENT_METHODS},
                value="cash", label="Method",
            ).props("dense outlined").classes("w-52")
            direction_in = ui.select(
                {"in": "Money in", "out": "Money out"},
                value="in", label="Direction",
            ).props("dense outlined").classes("w-36")
            description_in = ui.input("Description").props(
                "dense outlined").classes("flex-grow")

            async def record() -> None:
                try:
                    await asyncio.to_thread(
                        cash_service.record, account,
                        float(amount_in.value or 0), method_in.value,
                        user.id, direction_in.value, None, None, None,
                        description_in.value or None)
                except CashError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                except Exception as exc:
                    ui.notify(f"Could not record: {exc}",
                              type="negative")
                    return
                amount_in.set_value(0)
                description_in.set_value("")
                ui.notify("Recorded", type="positive")
                await reload()

            ui.button("Record", on_click=record).props(
                "unelevated color=primary no-caps")


def _movement_row(movement: Dict[str, Any], user: Any,
                  reload) -> None:
    reversed_already = movement.get("reverses_id") is not None
    with ui.card().classes("tv-glass w-full p-3"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.icon("sym_r_south_west" if movement["direction"] == "in"
                    else "sym_r_north_east").classes(
                "text-green-600" if movement["direction"] == "in"
                else "text-red-600")
            with ui.column().classes("gap-0 flex-grow"):
                ui.label(movement.get("description")
                         or movement["method_label"]).classes(
                    "text-sm")
                ui.label(
                    f"{movement['method_label']} - "
                    f"{movement.get('created_at') or ''}"
                    + (f" - agent {movement['agent_id']}"
                       if user.is_manager and movement.get("agent_id")
                       else "")
                ).classes("tv-mono text-[10px] tv-muted")
            ui.label(
                ("+" if movement["direction"] == "in" else "-")
                + money_label(movement["amount"],
                              movement.get("currency", "EUR"))
            ).classes("tv-mono text-sm font-semibold")

            if user.is_manager and not reversed_already:
                async def reverse() -> None:
                    try:
                        await asyncio.to_thread(
                            cash_service.reverse, movement["id"],
                            user.id, "corrected at the desk")
                    except CashError as exc:
                        ui.notify(str(exc), type="warning")
                        return
                    ui.notify("Reversed", type="positive")
                    await reload()

                ui.button(on_click=reverse).props(
                    "flat dense icon=sym_r_undo").tooltip(
                    "Post a reversing entry")
