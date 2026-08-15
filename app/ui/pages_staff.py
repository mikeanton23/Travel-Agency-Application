# -*- coding: utf-8 -*-

"""
Staff offer pipeline and acquisition dashboard (Phase C).

Routes (all admin-gated, all noindex):
    /admin/requests   lead queue -> prepare -> send -> track
    /admin/hotels     funnel metrics and revenue pipeline

The prepare-offer form deliberately separates "our price" from
"reference price": the reference field is labelled as requiring a
verified comparable quote, and the customer-facing offer page only
renders savings when staff filled it in.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.analytics import analytics
from app.services.leads import STATUSES, LeadError, lead_service
from app.services.payments import payment_service
from app.ui.components.layout import page_shell
from app.ui.pages_account import require_admin

STATUS_COLOR = {
    "new": "primary", "pending": "grey", "in_negotiation": "amber",
    "offer_prepared": "amber", "offer_sent": "teal",
    "offer_opened": "teal", "payment_pending": "amber",
    "paid": "green", "expired": "grey", "cancelled": "grey",
    "rejected": "red",
}


def _load_requests(status: Optional[str]) -> List[Dict[str, Any]]:
    return lead_service.list_requests(status=status, limit=200)


def _dashboard_metrics() -> Dict[str, Any]:
    from sqlalchemy import func as sql_func
    from app.db.database import SessionLocal
    from app.db.models import (
        CustomerOffer, HotelOfferRequest, Payment, SearchEvent,
    )

    session = SessionLocal()
    try:
        by_status = dict(
            session.query(HotelOfferRequest.status,
                          sql_func.count(HotelOfferRequest.id))
            .group_by(HotelOfferRequest.status).all()
        )
        total_requests = sum(by_status.values())
        offers_sent = (session.query(CustomerOffer)
                       .filter(CustomerOffer.sent_at.isnot(None))
                       .count())
        offers_opened = (session.query(CustomerOffer)
                         .filter(CustomerOffer.opened_at.isnot(None))
                         .count())
        paid = (session.query(Payment)
                .filter(Payment.status == "paid").count())
        paid_value = (session.query(sql_func.sum(Payment.amount))
                      .filter(Payment.status == "paid").scalar()) or 0.0
        avg_requested = (
            session.query(sql_func.avg(
                HotelOfferRequest.competitor_price))
            .filter(HotelOfferRequest.competitor_price.isnot(None))
            .scalar())
        avg_offered = (session.query(sql_func.avg(
            CustomerOffer.our_price)).scalar())
        top_destinations = (
            session.query(HotelOfferRequest.destination,
                          sql_func.count(HotelOfferRequest.id))
            .filter(HotelOfferRequest.destination.isnot(None))
            .group_by(HotelOfferRequest.destination)
            .order_by(sql_func.count(HotelOfferRequest.id).desc())
            .limit(5).all()
        )
        events = dict(
            session.query(SearchEvent.event,
                          sql_func.count(SearchEvent.id))
            .group_by(SearchEvent.event).all()
        )
        return {
            "by_status": by_status,
            "total_requests": total_requests,
            "offers_sent": offers_sent,
            "offers_opened": offers_opened,
            "paid": paid,
            "paid_value": round(paid_value, 2),
            "avg_requested": (round(avg_requested, 2)
                              if avg_requested else None),
            "avg_offered": (round(avg_offered, 2)
                            if avg_offered else None),
            "top_destinations": list(top_destinations),
            "events": events,
        }
    finally:
        session.close()


# ----------------------------------------------------------------------
# /admin/requests
# ----------------------------------------------------------------------

@ui.page("/admin/requests")
def admin_requests_page() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_admin()
    if user is None:
        return

    with page_shell("Offer requests"):
        ui.label("Offer requests").classes(
            "tv-display text-2xl font-semibold")
        ui.label(
            "Prepare offers here. A reference price should only be "
            "entered when you have verified a genuinely comparable "
            "quote -- the customer page shows savings only when it is "
            "present."
        ).classes("text-sm tv-muted max-w-3xl")

        with ui.row().classes("items-center gap-3"):
            status_filter = ui.select(
                ["all"] + STATUSES, value="all", label="Status",
            ).props("dense outlined").classes("w-56")
            ui.button("Refresh",
                      on_click=lambda: asyncio.create_task(refresh())
                      ).props("flat no-caps icon=sym_r_refresh")

        queue = ui.column().classes("w-full gap-2")

        async def refresh() -> None:
            chosen = (None if status_filter.value == "all"
                      else status_filter.value)
            rows = await asyncio.to_thread(_load_requests, chosen)
            try:
                queue.clear()
            except RuntimeError:
                return
            with queue:
                if not rows:
                    ui.label("No requests in this state.").classes(
                        "tv-muted text-sm")
                for row in rows:
                    render_request(row)

        status_filter.on_value_change(
            lambda _: asyncio.create_task(refresh()))

        def render_request(row: Dict[str, Any]) -> None:
            with ui.card().classes("tv-glass w-full p-4 gap-2"):
                with ui.row().classes("w-full items-center gap-3"):
                    ui.label(f"#{row['id']}").classes(
                        "tv-mono text-sm tv-muted")
                    ui.label(row.get("hotel_name")
                             or row.get("destination") or "--").classes(
                        "font-semibold flex-grow")
                    ui.label(row["status"]).classes("tv-badge").style(
                        f"color: var(--q-"
                        f"{STATUS_COLOR.get(row['status'], 'primary')})")
                with ui.row().classes("w-full gap-4 flex-wrap"):
                    ui.label(f"{row['customer_name']} - "
                             f"{row['customer_email']}").classes(
                        "text-sm")
                    if row.get("check_in"):
                        ui.label(f"{row['check_in']} -> "
                                 f"{row.get('check_out')}").classes(
                            "tv-mono text-xs tv-muted")
                    if row.get("competitor_price"):
                        ui.label(
                            f"They found: {row['competitor_price']:.2f} "
                            f"{row.get('currency') or ''} "
                            f"(customer-reported)"
                        ).classes("tv-mono text-xs tv-muted")
                with ui.row().classes("gap-2"):
                    ui.button(
                        "Prepare offer",
                        on_click=lambda r=row: prepare_dialog(r),
                    ).props("unelevated dense color=primary no-caps "
                            "icon=sym_r_edit_note")
                    ui.button(
                        "Add note / status",
                        on_click=lambda r=row: status_dialog(r),
                    ).props("flat dense no-caps icon=sym_r_edit")

        def status_dialog(row: Dict[str, Any]) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("tv-glass p-5 gap-3 w-96"):
                ui.label(f"Request #{row['id']}").classes(
                    "tv-display text-lg font-semibold")
                status_in = ui.select(STATUSES, value=row["status"],
                                      label="Status").props(
                    "dense outlined").classes("w-full")
                note_in = ui.textarea("Internal note").props(
                    "dense outlined").classes("w-full")

                async def save() -> None:
                    await asyncio.to_thread(
                        lead_service.set_status, row["id"],
                        status_in.value, note_in.value or None)
                    dialog.close()
                    ui.notify("Updated", type="positive")
                    await refresh()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props(
                        "flat no-caps")
                    ui.button("Save", on_click=save).props(
                        "unelevated color=primary no-caps")
            dialog.open()

        def prepare_dialog(row: Dict[str, Any]) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes(
                "tv-glass p-6 gap-3 w-full max-w-xl"
            ):
                ui.label(f"Prepare offer -- request #{row['id']}").classes(
                    "tv-display text-xl font-semibold")
                hotel_in = ui.input(
                    "Hotel name", value=row.get("hotel_name") or "",
                ).props("dense outlined").classes("w-full")
                room_in = ui.input("Room description").props(
                    "dense outlined").classes("w-full")
                with ui.row().classes("w-full gap-3"):
                    price_in = ui.number("Our price (total)").props(
                        "dense outlined").classes("flex-grow")
                    currency_in = ui.input(
                        "Currency", value=row.get("currency") or "EUR",
                    ).props("dense outlined").classes("w-28")
                    days_in = ui.number("Valid for (days)", value=3,
                                        min=1, max=30).props(
                        "dense outlined").classes("w-36")
                reference_in = ui.number(
                    "Reference price -- only if verified comparable",
                ).props("dense outlined").classes("w-full")
                ui.label(
                    "Leave blank unless you checked the same hotel, "
                    "room, dates, occupancy, board and cancellation "
                    "terms. Savings are shown to the customer only "
                    "when this is filled in."
                ).classes("text-xs tv-muted")
                cancel_in = ui.input("Cancellation policy").props(
                    "dense outlined").classes("w-full")
                conditions_in = ui.textarea("Conditions").props(
                    "dense outlined").classes("w-full")
                send_now = ui.checkbox("Email the offer immediately",
                                       value=True)
                status_label = ui.label("").classes("text-sm")

                async def create() -> None:
                    try:
                        prepared = await asyncio.to_thread(
                            lead_service.prepare_offer,
                            row["id"], float(price_in.value or 0),
                            currency_in.value or "EUR",
                            hotel_in.value or "Your stay",
                            int(days_in.value or 3),
                            reference_in.value or None,
                            room_in.value or None, None,
                            conditions_in.value or None,
                            cancel_in.value or None,
                            user["user_id"],
                        )
                    except LeadError as exc:
                        status_label.set_text(str(exc))
                        status_label.classes(
                            replace="text-sm text-red-600")
                        return
                    if send_now.value:
                        result = await asyncio.to_thread(
                            lead_service.send_offer_email, prepared)
                        if result["success"]:
                            ui.notify("Offer sent to customer",
                                      type="positive")
                        else:
                            ui.notify(
                                f"Offer created but email failed: "
                                f"{result['error']}", type="warning")
                    else:
                        ui.notify("Offer prepared (not sent)",
                                  type="positive")
                    dialog.close()
                    await refresh()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props(
                        "flat no-caps")
                    ui.button("Create offer", on_click=create).props(
                        "unelevated color=primary no-caps "
                        "icon=sym_r_send")
            dialog.open()

        ui.timer(0.1, refresh, once=True)


# ----------------------------------------------------------------------
# /admin/hotels -- acquisition dashboard
# ----------------------------------------------------------------------

@ui.page("/admin/hotels")
def admin_hotels_dashboard() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    user = require_admin()
    if user is None:
        return

    with page_shell("Acquisition"):
        ui.label("Hotel acquisition").classes(
            "tv-display text-2xl font-semibold")
        body = ui.column().classes("w-full gap-4")

        async def refresh() -> None:
            metrics = await asyncio.to_thread(_dashboard_metrics)
            try:
                body.clear()
            except RuntimeError:
                return
            with body:
                with ui.element("div").classes(
                    "grid grid-cols-2 lg:grid-cols-4 gap-4 w-full"
                ):
                    _metric("Requests", metrics["total_requests"])
                    _metric("Offers sent", metrics["offers_sent"])
                    _metric("Offers opened", metrics["offers_opened"])
                    _metric("Paid", metrics["paid"])

                sent = metrics["offers_sent"]
                paid = metrics["paid"]
                conversion = (f"{paid / sent * 100:.1f}%" if sent
                              else "no offers sent yet")
                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    ui.label("Pipeline").classes("font-semibold")
                    ui.label(f"Sent -> paid conversion: {conversion}") \
                        .classes("tv-mono text-sm")
                    ui.label(
                        "Average customer-reported price: "
                        + (f"{metrics['avg_requested']:.2f}"
                           if metrics["avg_requested"] else "--")
                    ).classes("tv-mono text-sm tv-muted")
                    ui.label(
                        "Average offered price: "
                        + (f"{metrics['avg_offered']:.2f}"
                           if metrics["avg_offered"] else "--")
                    ).classes("tv-mono text-sm tv-muted")
                    ui.label(
                        f"Paid value: {metrics['paid_value']:.2f}"
                    ).classes("tv-mono text-sm")
                    ui.label(
                        "Savings are not aggregated here: only offers "
                        "with a verified comparable reference price "
                        "represent a real saving."
                    ).classes("text-xs tv-muted")

                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    ui.label("Requests by status").classes(
                        "font-semibold")
                    if not metrics["by_status"]:
                        ui.label("No requests yet.").classes(
                            "text-sm tv-muted")
                    for status, count in sorted(
                            metrics["by_status"].items()):
                        ui.label(f"{status}: {count}").classes(
                            "tv-mono text-sm")

                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    ui.label("Top destinations").classes("font-semibold")
                    if not metrics["top_destinations"]:
                        ui.label("No destination data yet.").classes(
                            "text-sm tv-muted")
                    for name, count in metrics["top_destinations"]:
                        ui.label(f"{name}: {count} requests").classes(
                            "tv-mono text-sm")

                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    ui.label("Funnel events").classes("font-semibold")
                    if not metrics["events"]:
                        ui.label("No events recorded yet.").classes(
                            "text-sm tv-muted")
                    for event, count in sorted(
                            metrics["events"].items()):
                        ui.label(f"{event}: {count}").classes(
                            "tv-mono text-sm")

                with ui.card().classes("tv-glass w-full p-4 gap-1"):
                    ui.label("Payments").classes("font-semibold")
                    ui.label(
                        "Stripe configured"
                        if payment_service.configured
                        else "Stripe not configured -- checkout disabled"
                    ).classes("tv-mono text-sm")

        ui.button("Refresh", on_click=refresh).props(
            "unelevated color=primary no-caps icon=sym_r_refresh")
        ui.timer(0.1, refresh, once=True)


def _metric(label: str, value: Any) -> None:
    with ui.card().classes("tv-glass p-4 gap-0"):
        ui.label(str(value)).classes("tv-mono text-3xl font-semibold")
        ui.label(label).classes("tv-mono text-xs tv-muted uppercase")
