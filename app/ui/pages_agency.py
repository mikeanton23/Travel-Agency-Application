# -*- coding: utf-8 -*-

"""
Agency back office: desk, client book, quotes list.

Every page is guarded by :func:`require_agent` and scoped by the rules
in :mod:`app.services.agency.access` - an agent sees their own book, a
manager sees the office.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.agency.cash import cash_service
from app.services.agency.clients import ClientError, client_service
from app.services.agency.pricing import SERVICE_LABELS
from app.services.agency.quotes import quote_service
from app.ui.agency_common import (
    SERVICE_ICONS, agency_shell, ensure_agency, money_label,
    require_agent, status_chip,
)
from app.ui.helpers import safe_clear


# ----------------------------------------------------------------------
# /agency - the desk
# ----------------------------------------------------------------------

@ui.page("/agency")
def agency_desk() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Desk", user):
        ui.label(f"Good to see you, {user.display_name}").classes(
            "tv-display text-2xl font-semibold")

        metrics = ui.element("div").classes(
            "grid grid-cols-2 lg:grid-cols-4 gap-4 w-full")
        recent = ui.column().classes("w-full gap-2")

        async def load() -> None:
            agent_filter = None if user.is_manager else user.id
            clients = await asyncio.to_thread(
                client_service.search, user, agency_id, "", 500)
            quotes = await asyncio.to_thread(
                quote_service.list_for, agency_id, agent_filter,
                None, None, 200)
            account = await asyncio.to_thread(
                cash_service.ensure_account, agency_id)
            movements = await asyncio.to_thread(
                cash_service.movements, account, 200,
                None if user.is_manager else user.id)

            open_quotes = [q for q in quotes
                           if q["status"] in ("draft", "sent")]
            taken = sum(m["amount"] for m in movements
                        if m["direction"] == "in")

            if not safe_clear(metrics):
                return
            with metrics:
                _metric("Clients", len(clients), "sym_r_contacts")
                _metric("Open quotes", len(open_quotes),
                        "sym_r_request_quote")
                _metric("All quotes", len(quotes), "sym_r_history")
                _metric(
                    "Taken" if not user.is_manager else "Office taken",
                    money_label(taken), "sym_r_payments")

            safe_clear(recent)
            with recent:
                with ui.row().classes("w-full gap-2"):
                    ui.button(
                        "New client",
                        on_click=lambda: ui.navigate.to(
                            "/agency/clients")).props(
                        "unelevated color=primary no-caps "
                        "icon=sym_r_person_add")
                    ui.button(
                        "New quote",
                        on_click=lambda: asyncio.create_task(
                            _new_quote(user, agency_id))).props(
                        "outline no-caps icon=sym_r_note_add")

                ui.label("Recent quotes").classes(
                    "tv-display text-lg font-semibold pt-2")
                if not quotes:
                    ui.label(
                        "No quotes yet. Create one from a client, or "
                        "start a blank itinerary."
                    ).classes("text-sm tv-muted")
                for quote in quotes[:10]:
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
                            status_chip(quote["status"])
                            ui.label(money_label(
                                quote["total"],
                                quote["currency"])).classes(
                                "tv-mono text-sm")

        ui.timer(0.1, load, once=True)


def _metric(label: str, value: Any, icon: str) -> None:
    with ui.card().classes("tv-glass p-4 gap-0"):
        ui.icon(icon).classes("text-primary")
        ui.label(str(value)).classes(
            "tv-mono text-2xl font-semibold")
        ui.label(label).classes(
            "tv-mono text-xs tv-muted uppercase")


async def _new_quote(user: Any, agency_id: int,
                     client_id: Optional[int] = None) -> None:
    created = await asyncio.to_thread(
        quote_service.create, agency_id, user.id, client_id,
        "New itinerary")
    ui.navigate.to(f"/agency/quotes/{created['id']}")


# ----------------------------------------------------------------------
# /agency/clients
# ----------------------------------------------------------------------

@ui.page("/agency/clients")
def agency_clients() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Clients", user):
        with ui.row().classes("w-full items-center gap-3"):
            ui.label("Client book").classes(
                "tv-display text-2xl font-semibold")
            ui.space()
            ui.button("Add client",
                      on_click=lambda: add_dialog.open()).props(
                "unelevated color=primary no-caps "
                "icon=sym_r_person_add")

        search_in = ui.input(
            placeholder="Search by name, email, phone or company"
        ).props("dense outlined clearable").classes("w-full")

        results = ui.column().classes("w-full gap-2")

        async def load() -> None:
            rows = await asyncio.to_thread(
                client_service.search, user, agency_id,
                search_in.value or "", 200)
            if not safe_clear(results):
                return
            with results:
                ui.label(
                    f"{len(rows)} "
                    + ("clients in the office" if user.is_manager
                       else "clients on your book")
                ).classes("tv-mono text-xs tv-muted")
                if not rows:
                    ui.label(
                        "Nothing here yet. Add your first client."
                    ).classes("text-sm tv-muted")
                for row in rows:
                    with ui.card().classes(
                        "tv-glass w-full p-3 cursor-pointer"
                    ).on("click", lambda r=row: ui.navigate.to(
                            f"/agency/clients/{r['id']}")):
                        with ui.row().classes(
                            "w-full items-center gap-3"
                        ):
                            ui.icon("sym_r_person").classes(
                                "text-primary")
                            with ui.column().classes("gap-0 flex-grow"):
                                ui.label(row["full_name"]).classes(
                                    "font-medium")
                                detail = " - ".join(
                                    p for p in (row.get("email"),
                                                row.get("phone"),
                                                row.get("company_name"))
                                    if p)
                                if detail:
                                    ui.label(detail).classes(
                                        "text-xs tv-muted")
                            if user.is_manager and row.get(
                                    "owner_agent_id") != user.id:
                                ui.label("another agent").classes(
                                    "tv-badge")

        search_in.on("keydown.enter",
                     lambda: asyncio.create_task(load()))
        search_in.on("blur", lambda: asyncio.create_task(load()))

        # ---- add client dialog ----
        add_dialog = ui.dialog()
        with add_dialog, ui.card().classes(
            "tv-glass w-full max-w-2xl p-6 gap-3"
        ):
            ui.label("Add a client").classes(
                "tv-display text-xl font-semibold")
            with ui.row().classes("w-full gap-3"):
                name_in = ui.input("Full name *").props(
                    "dense outlined").classes("flex-grow")
                company_in = ui.input("Company").props(
                    "dense outlined").classes("flex-grow")
            with ui.row().classes("w-full gap-3"):
                email_in = ui.input("Email").props(
                    "dense outlined").classes("flex-grow")
                phone_in = ui.input("Phone").props(
                    "dense outlined").classes("flex-grow")
            with ui.row().classes("w-full gap-3"):
                vat_in = ui.input("VAT number").props(
                    "dense outlined").classes("flex-grow")
                tax_in = ui.input("Tax office").props(
                    "dense outlined").classes("flex-grow")
            address_in = ui.input("Address").props(
                "dense outlined").classes("w-full")
            with ui.row().classes("w-full gap-3"):
                passport_in = ui.input("Passport number").props(
                    "dense outlined").classes("flex-grow")
                expiry_in = ui.input("Passport expiry").props(
                    "dense outlined type=date").classes("flex-grow")
                dob_in = ui.input("Date of birth").props(
                    "dense outlined type=date").classes("flex-grow")
            nationality_in = ui.input("Nationality").props(
                "dense outlined").classes("w-full")
            notes_in = ui.textarea("Notes").props(
                "dense outlined").classes("w-full")
            consent_in = ui.checkbox(
                "Client agreed to marketing contact")
            status = ui.label("").classes("text-sm")

            async def save() -> None:
                try:
                    await asyncio.to_thread(
                        client_service.create, agency_id, user.id,
                        name_in.value,
                        company_name=company_in.value or None,
                        email=email_in.value or None,
                        phone=phone_in.value or None,
                        vat_number=vat_in.value or None,
                        tax_office=tax_in.value or None,
                        address=address_in.value or None,
                        passport_number=passport_in.value or None,
                        passport_expiry=expiry_in.value or None,
                        date_of_birth=dob_in.value or None,
                        nationality=nationality_in.value or None,
                        notes=notes_in.value or None,
                        consent_marketing=bool(consent_in.value),
                    )
                except ClientError as exc:
                    status.set_text(str(exc))
                    status.style("color: #dc2626")
                    return
                except Exception as exc:
                    status.set_text(
                        f"Could not save ({type(exc).__name__}).")
                    status.style("color: #dc2626")
                    return
                add_dialog.close()
                name_in.set_value("")
                ui.notify("Client added", type="positive")
                await load()

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=add_dialog.close).props(
                    "flat no-caps")
                ui.button("Save client", on_click=save).props(
                    "unelevated color=primary no-caps")

        ui.timer(0.1, load, once=True)


# ----------------------------------------------------------------------
# /agency/clients/{client_id}
# ----------------------------------------------------------------------

@ui.page("/agency/clients/{client_id}")
def agency_client_detail(client_id: int) -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_agent()
    if user is None:
        return
    agency_id = ensure_agency(user)

    with agency_shell("Client", user):
        body = ui.column().classes("w-full gap-4")

        async def load() -> None:
            client = await asyncio.to_thread(
                client_service.get, user, client_id)
            if not safe_clear(body):
                return
            with body:
                if client is None:
                    ui.label("Client not found").classes(
                        "tv-display text-xl font-semibold")
                    ui.label(
                        "It may belong to another agent's book."
                    ).classes("text-sm tv-muted")
                    ui.button(
                        "Back to clients",
                        on_click=lambda: ui.navigate.to(
                            "/agency/clients")).props(
                        "unelevated color=primary no-caps")
                    return

                with ui.row().classes("w-full items-center gap-3"):
                    ui.label(client["full_name"]).classes(
                        "tv-display text-2xl font-semibold")
                    ui.space()
                    ui.button(
                        "New quote for this client",
                        on_click=lambda: asyncio.create_task(
                            _new_quote(user, agency_id,
                                       client["id"]))).props(
                        "unelevated color=primary no-caps "
                        "icon=sym_r_note_add")

                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    for label, key in (
                        ("Company", "company_name"),
                        ("Email", "email"), ("Phone", "phone"),
                        ("VAT number", "vat_number"),
                        ("Tax office", "tax_office"),
                        ("Address", "address"),
                        ("Passport", "passport_number"),
                        ("Passport expiry", "passport_expiry"),
                        ("Date of birth", "date_of_birth"),
                        ("Nationality", "nationality"),
                    ):
                        if client.get(key):
                            with ui.row().classes("gap-3"):
                                ui.label(label).classes(
                                    "tv-mono text-xs tv-muted w-36")
                                ui.label(str(client[key])).classes(
                                    "text-sm")
                    ui.label(
                        "Marketing consent: "
                        + ("given" if client["consent_marketing"]
                           else "not given")
                    ).classes("tv-mono text-xs tv-muted pt-2")

                # ---- quotes for this client ----
                quotes = await asyncio.to_thread(
                    quote_service.list_for, agency_id,
                    None if user.is_manager else user.id,
                    client["id"], None, 50)
                ui.label("Quotes").classes(
                    "tv-display text-lg font-semibold")
                if not quotes:
                    ui.label("No quotes for this client yet.").classes(
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
                                .classes("flex-grow")
                            status_chip(quote["status"])
                            ui.label(money_label(
                                quote["total"],
                                quote["currency"])).classes(
                                "tv-mono text-sm")

                # ---- notes ----
                ui.label("Notes").classes(
                    "tv-display text-lg font-semibold pt-2")
                note_in = ui.textarea(
                    placeholder="Preferences, requirements, history"
                ).props("dense outlined").classes("w-full")

                async def add_note() -> None:
                    if not (note_in.value or "").strip():
                        return
                    await asyncio.to_thread(
                        client_service.add_note, user, client["id"],
                        note_in.value)
                    note_in.set_value("")
                    await load()

                ui.button("Add note", on_click=add_note).props(
                    "outline dense no-caps icon=sym_r_edit_note")

                notes = await asyncio.to_thread(
                    client_service.notes, user, client["id"], 50)
                for note in notes:
                    with ui.card().classes("tv-glass w-full p-3"):
                        ui.label(note["body"]).classes("text-sm")
                        ui.label(note["created_at"] or "").classes(
                            "tv-mono text-[10px] tv-muted")

        ui.timer(0.1, load, once=True)
