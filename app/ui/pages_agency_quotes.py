# -*- coding: utf-8 -*-

"""
The quote builder.

An agent assembles an itinerary from the five services, enters the
supplier cost and their own service charge, and sees the total, the
VAT and any rule warnings update immediately. Nothing here invents a
price: every figure on screen was typed by the agent or returned by a
supplier search.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.agency.pricing import (
    SERVICE_LABELS, SERVICE_TYPES, price_quote,
)
from app.services.agency.quotes import QuoteError, quote_service
from app.ui.agency_common import (
    SERVICE_ICONS, agency_shell, ensure_agency, money_label,
    require_agent, status_chip,
)
from app.ui.helpers import safe_clear

TICKET_KINDS = {
    "air": "Air",
    "ferry": "Ferry",
    "rail": "Rail",
    "bus": "Bus",
    "other": "Other",
}


@ui.page("/agency/quotes")
def agency_quotes() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Quotes", user):
        with ui.row().classes("w-full items-center gap-3"):
            ui.label("Quotes").classes(
                "tv-display text-2xl font-semibold")
            ui.space()
            status_filter = ui.select(
                ["all", "draft", "sent", "accepted", "rejected",
                 "booked", "cancelled"],
                value="all", label="Status",
            ).props("dense outlined").classes("w-40")

            async def new_quote() -> None:
                created = await asyncio.to_thread(
                    quote_service.create, agency_id, user.id, None,
                    "New itinerary")
                ui.navigate.to(f"/agency/quotes/{created['id']}")

            ui.button("New quote", on_click=new_quote).props(
                "unelevated color=primary no-caps icon=sym_r_note_add")

        rows = ui.column().classes("w-full gap-2")

        async def load() -> None:
            status = (None if status_filter.value == "all"
                      else status_filter.value)
            quotes = await asyncio.to_thread(
                quote_service.list_for, agency_id,
                None if user.is_manager else user.id, None, status,
                200)
            if not safe_clear(rows):
                return
            with rows:
                ui.label(f"{len(quotes)} quotes").classes(
                    "tv-mono text-xs tv-muted")
                if not quotes:
                    ui.label("Nothing to show.").classes(
                        "text-sm tv-muted")
                for quote in quotes:
                    with ui.card().classes(
                        "tv-glass w-full p-3 cursor-pointer"
                    ).on("click", lambda q=quote: ui.navigate.to(
                            f"/agency/quotes/{q['id']}")):
                        with ui.row().classes(
                            "w-full items-center gap-3"
                        ):
                            ui.label(quote["reference"]).classes(
                                "tv-mono text-xs tv-muted")
                            ui.label(quote["title"] or "Itinerary") \
                                .classes("font-medium flex-grow")
                            if quote.get("travel_start"):
                                ui.label(quote["travel_start"]).classes(
                                    "tv-mono text-xs tv-muted")
                            status_chip(quote["status"])
                            ui.label(money_label(
                                quote["total"],
                                quote["currency"])).classes(
                                "tv-mono text-sm font-semibold")

        status_filter.on_value_change(
            lambda _: asyncio.create_task(load()))
        ui.timer(0.1, load, once=True)


@ui.page("/agency/quotes/{quote_id}")
def agency_quote_detail(quote_id: int) -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    ensure_agency(user)

    with agency_shell("Quote", user):
        header = ui.column().classes("w-full gap-1")
        lines = ui.column().classes("w-full gap-2")
        totals_box = ui.column().classes("w-full gap-1")

        async def load() -> None:
            quote = await asyncio.to_thread(quote_service.get, quote_id)
            if quote is None:
                if safe_clear(header):
                    with header:
                        ui.label("Quote not found").classes(
                            "tv-display text-xl font-semibold")
                return
            if not user.is_manager and quote["agent_id"] != user.id:
                if safe_clear(header):
                    with header:
                        ui.label("Not your quote").classes(
                            "tv-display text-xl font-semibold")
                        ui.label(
                            "This itinerary belongs to another agent."
                        ).classes("text-sm tv-muted")
                return

            # ---- header ----
            if safe_clear(header):
                with header:
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.label(quote["title"] or "Itinerary").classes(
                            "tv-display text-2xl font-semibold")
                        status_chip(quote["status"])
                        ui.space()
                        ui.label(quote["reference"]).classes(
                            "tv-mono text-sm tv-muted")
                    with ui.row().classes("gap-2 items-center"):
                        for target in ("draft", "sent", "accepted",
                                       "rejected"):
                            ui.button(
                                target.title(),
                                on_click=lambda t=target:
                                    asyncio.create_task(
                                        set_status(t))).props(
                                "flat dense no-caps")
                        ui.space()
                        ui.button(
                            "Convert to booking",
                            on_click=lambda: asyncio.create_task(
                                to_booking())).props(
                            "unelevated color=primary dense no-caps "
                            "icon=sym_r_confirmation_number")

            # ---- lines ----
            if safe_clear(lines):
                with lines:
                    ui.label("Services").classes(
                        "tv-display text-lg font-semibold")
                    if not quote["items"]:
                        ui.label(
                            "No services yet. Add the first line "
                            "below."
                        ).classes("text-sm tv-muted")
                    for item in quote["items"]:
                        _line_card(item, quote["currency"], load)
                    _add_line_form(quote_id, load)

            # ---- totals ----
            if safe_clear(totals_box):
                totals = quote["totals"]
                with totals_box, ui.card().classes(
                    "tv-glass w-full p-4 gap-1"
                ):
                    ui.label("Totals").classes(
                        "tv-display text-lg font-semibold")
                    for label, key in (
                        ("Supplier cost", "net_cost"),
                        ("Service charges", "service_charge"),
                        ("VAT", "vat"),
                    ):
                        with ui.row().classes("w-full gap-3"):
                            ui.label(label).classes(
                                "tv-mono text-xs tv-muted flex-grow")
                            ui.label(money_label(
                                totals[key],
                                totals["currency"])).classes(
                                "tv-mono text-sm")
                    ui.separator()
                    with ui.row().classes("w-full gap-3 items-center"):
                        ui.label("Client pays").classes(
                            "font-semibold flex-grow")
                        ui.label(money_label(
                            totals["total"],
                            totals["currency"])).classes(
                            "tv-mono text-xl font-semibold")
                    ui.label(
                        "Agency keeps "
                        + money_label(totals["gross_margin"],
                                      totals["currency"])
                        + " in service charges. Supplier commission is "
                          "not included - work that out yourself."
                    ).classes("text-xs tv-muted")
                    for warning in totals.get("warnings", []):
                        ui.label(warning).classes(
                            "text-xs text-amber-700")

        async def set_status(status: str) -> None:
            await asyncio.to_thread(quote_service.set_status,
                                    quote_id, status)
            ui.notify(f"Quote marked {status}", type="positive")
            await load()

        async def to_booking() -> None:
            try:
                from app.services.agency.bookings import booking_service
            except ImportError:
                ui.notify("Bookings are not available in this build.",
                          type="warning")
                return
            try:
                created = await asyncio.to_thread(
                    booking_service.create_from_quote, quote_id)
            except Exception as exc:
                ui.notify(f"Could not create the booking: {exc}",
                          type="negative", timeout=10000)
                return
            ui.navigate.to(f"/agency/bookings/{created['id']}")

        ui.timer(0.1, load, once=True)


def _line_card(item: Dict[str, Any], currency: str, reload) -> None:
    from app.services.agency.pricing import price_line

    priced = price_line(
        net_cost=item["net_cost"],
        service_charge=item["service_charge"],
        quantity=item["quantity"],
        is_domestic=item["is_domestic"],
        vat_rate=item["vat_rate"],
        service_type=item["service_type"],
        ticket_kind=(item.get("details") or {}).get("ticket_kind")
        if isinstance(item.get("details"), dict) else None,
    )
    with ui.card().classes("tv-glass w-full p-3"):
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
                    span = item["starts_on"]
                    if item.get("ends_on"):
                        span += f" to {item['ends_on']}"
                    bits.append(span)
                if item["quantity"] > 1:
                    bits.append(f"x{item['quantity']}")
                ui.label(" - ".join(bits)).classes(
                    "text-xs tv-muted")
                ui.label(
                    "Domestic (VAT applies)" if item["is_domestic"]
                    else "International (no Greek VAT)"
                ).classes("tv-mono text-[10px] tv-muted")
                for warning in priced.warnings:
                    ui.label(warning).classes(
                        "text-xs text-amber-700")
            with ui.column().classes("items-end gap-0"):
                ui.label(money_label(float(priced.total),
                                     currency)).classes(
                    "tv-mono text-sm font-semibold")
                ui.label(
                    f"cost {float(priced.net_cost):.2f} + charge "
                    f"{float(priced.service_charge):.2f}"
                    + (f" + VAT {float(priced.vat):.2f}"
                       if priced.vat else "")
                ).classes("tv-mono text-[10px] tv-muted")

                async def remove() -> None:
                    await asyncio.to_thread(
                        quote_service.remove_item, item["id"])
                    await reload()

                ui.button(on_click=remove).props(
                    "flat dense icon=sym_r_delete").tooltip(
                    "Remove this line")


def _add_line_form(quote_id: int, reload) -> None:
    with ui.expansion("Add a service", icon="sym_r_add").classes(
        "w-full"
    ).props("dense"):
        with ui.column().classes("w-full gap-3 pt-2"):
            with ui.row().classes("w-full gap-3"):
                service_in = ui.select(
                    {k: SERVICE_LABELS[k] for k in SERVICE_TYPES},
                    value="hotel", label="Service",
                ).props("dense outlined").classes("w-52")
                ticket_kind_in = ui.select(
                    TICKET_KINDS, value="air", label="Ticket type",
                ).props("dense outlined").classes("w-36")
                title_in = ui.input("Description *").props(
                    "dense outlined").classes("flex-grow")

            def toggle_kind() -> None:
                ticket_kind_in.visible = service_in.value == "ticket"

            service_in.on_value_change(lambda _: toggle_kind())
            toggle_kind()

            with ui.row().classes("w-full gap-3"):
                supplier_in = ui.input("Supplier").props(
                    "dense outlined").classes("flex-grow")
                ref_in = ui.input("Supplier reference").props(
                    "dense outlined").classes("flex-grow")
                start_in = ui.input("From").props(
                    "dense outlined type=date").classes("w-40")
                end_in = ui.input("To").props(
                    "dense outlined type=date").classes("w-40")

            with ui.row().classes("w-full gap-3 items-center"):
                cost_in = ui.number("Supplier cost", value=0,
                                    min=0).props(
                    "dense outlined").classes("w-40")
                charge_in = ui.number("Service charge", value=0,
                                      min=0).props(
                    "dense outlined").classes("w-40")
                qty_in = ui.number("Quantity", value=1, min=1).props(
                    "dense outlined").classes("w-28")
                pax_in = ui.number("Pax", value=None, min=1).props(
                    "dense outlined").classes("w-24")
                domestic_in = ui.checkbox("Domestic (Greece)")
                vat_in = ui.number("VAT %", value=24, min=0,
                                   max=100).props(
                    "dense outlined").classes("w-28")

            notes_in = ui.textarea("Line notes").props(
                "dense outlined").classes("w-full")
            status = ui.label("").classes("text-sm")

            async def add() -> None:
                try:
                    await asyncio.to_thread(
                        quote_service.add_item,
                        quote_id,
                        service_in.value,
                        title_in.value,
                        float(cost_in.value or 0),
                        float(charge_in.value or 0),
                        int(qty_in.value or 1),
                        bool(domestic_in.value),
                        float(vat_in.value or 0),
                        supplier_in.value or None,
                        ref_in.value or None,
                        start_in.value or None,
                        end_in.value or None,
                        int(pax_in.value) if pax_in.value else None,
                        notes_in.value or None,
                        {"ticket_kind": ticket_kind_in.value}
                        if service_in.value == "ticket" else None,
                    )
                except QuoteError as exc:
                    status.set_text(str(exc))
                    status.style("color: #dc2626")
                    return
                except Exception as exc:
                    status.set_text(
                        f"Could not add the line "
                        f"({type(exc).__name__}).")
                    status.style("color: #dc2626")
                    return
                title_in.set_value("")
                cost_in.set_value(0)
                charge_in.set_value(0)
                status.set_text("")
                await reload()

            ui.button("Add to itinerary", on_click=add).props(
                "unelevated color=primary no-caps icon=sym_r_add")
