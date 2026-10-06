# -*- coding: utf-8 -*-

"""
Shared pieces for the agency back-office pages.

Kept separate from the public site so the agent-facing screens have
their own guards, navigation and formatting without entangling the
consumer pages.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Optional

from nicegui import app, ui

from app.services.agency.access import role_of, sees_whole_office
from app.ui.theme import apply_theme, theme_toggle

AGENCY_NAV = [
    ("Desk", "/agency", "sym_r_dashboard"),
    ("Clients", "/agency/clients", "sym_r_contacts"),
    ("Quotes", "/agency/quotes", "sym_r_request_quote"),
    ("Bookings", "/agency/bookings", "sym_r_confirmation_number"),
    ("Cash", "/agency/cash", "sym_r_payments"),
    ("Reports", "/agency/reports", "sym_r_insights"),
]

#: Routes the counter never sees. Accounting, profits and office-wide
#: figures belong to the owner/manager; staff keep bookings, vouchers,
#: documents and their own client book.
#:
#: Hiding the link is courtesy, not security - the page itself redirects
#: and :mod:`app.services.agency.reporting` refuses the data regardless.
MANAGER_ONLY_ROUTES = {"/agency/reports"}

SERVICE_ICONS = {
    "hotel": "sym_r_hotel",
    "ticket": "sym_r_confirmation_number",
    "transfer": "sym_r_airport_shuttle",
    "car_rental": "sym_r_directions_car",
    "tour": "sym_r_tour",
}


class CurrentUser:
    """A lightweight stand-in for the signed-in agent.

    The access rules only need ``id``, ``role`` and ``is_admin``, so
    the session dictionary is wrapped rather than hitting the database
    on every permission check.

    ``role`` is the exception: :func:`current_agent` always re-reads it
    from the database. See the note there.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        self.id = data.get("user_id")
        self.email = data.get("email")
        self.display_name = data.get("display_name") or data.get("email")
        self.is_admin = bool(data.get("is_admin"))
        self.agency_id = data.get("agency_id")
        self.role = data.get("role") or (
            "admin" if self.is_admin else "agent")

    @property
    def is_manager(self) -> bool:
        return sees_whole_office(self)


def current_agent() -> Optional[CurrentUser]:
    """The signed-in user, or None.

    The role is always re-read from the database rather than trusted
    from the session. A session is written once at sign-in and never
    updated, so a promotion or a demotion would otherwise take effect
    only when that person next happened to log out - a promoted manager
    silently sees nothing, and a demoted agent keeps their access. That
    is worth one primary-key lookup per page render, which is noise next
    to the quote and booking queries each page already runs.
    """
    data = app.storage.user.get("auth")
    if not data or not data.get("user_id"):
        return None
    return _refresh_from_database(CurrentUser(data))


def _refresh_from_database(user: CurrentUser) -> CurrentUser:
    try:
        from app.db.database import SessionLocal
        from app.db.models import User

        session = SessionLocal()
        try:
            row = session.get(User, user.id)
            if row is not None:
                user.role = role_of(row)
                user.agency_id = getattr(row, "agency_id", None)
                user.is_admin = bool(row.is_admin)
                data = dict(app.storage.user.get("auth") or {})
                if (data.get("role") != user.role
                        or data.get("agency_id") != user.agency_id
                        or data.get("is_admin") != user.is_admin):
                    data.update({"role": user.role,
                                 "agency_id": user.agency_id,
                                 "is_admin": user.is_admin})
                    app.storage.user["auth"] = data
        finally:
            session.close()
    except Exception:
        pass        # a stale session must not break the page
    return user


def require_agent() -> Optional[CurrentUser]:
    """Guard for every agency page."""
    user = current_agent()
    if user is None:
        ui.navigate.to("/login")
        return None
    return user


def ensure_agency(user: CurrentUser) -> Optional[int]:
    """The agency this agent belongs to, created on first use.

    A single-office deployment should not force anyone through a setup
    wizard, so the first signed-in user gets an office created for them
    and everyone else joins it.
    """
    if user.agency_id:
        return user.agency_id
    from app.db.database import SessionLocal
    from app.db.models import Agency, User

    session = SessionLocal()
    try:
        agency = session.query(Agency).order_by(Agency.id).first()
        if agency is None:
            agency = Agency(name="Aevyra Travel")
            session.add(agency)
            session.flush()
        row = session.get(User, user.id)
        if row is not None:
            row.agency_id = agency.id
        session.commit()
        user.agency_id = agency.id
    finally:
        session.close()

    data = dict(app.storage.user.get("auth") or {})
    data["agency_id"] = user.agency_id
    app.storage.user["auth"] = data
    return user.agency_id


def nav_for(user: CurrentUser):
    """The navigation this user is allowed to see."""
    if user.is_manager:
        return AGENCY_NAV
    return [entry for entry in AGENCY_NAV
            if entry[1] not in MANAGER_ONLY_ROUTES]


@contextmanager
def agency_shell(title: str, user: CurrentUser):
    """The back-office frame: its own nav, clearly not the public site."""
    dark = apply_theme()

    with ui.header().classes(
        "tv-glass items-center px-4 py-2 gap-3"
    ).props("elevated=false"):
        ui.button(on_click=lambda: drawer.toggle()).props(
            "flat round icon=sym_r_menu").classes("lg:hidden")
        ui.icon("sym_r_business_center").classes(
            "text-2xl text-primary")
        ui.label("Aevyra Desk").classes(
            "tv-display text-xl font-semibold")
        ui.label(title).classes(
            "tv-mono text-xs uppercase tracking-widest tv-muted "
            "hidden sm:block mt-1")
        ui.space()
        ui.label(f"{user.display_name} - {user.role}").classes(
            "tv-mono text-xs tv-muted hidden sm:block")
        ui.button(on_click=lambda: ui.navigate.to("/")).props(
            "flat round icon=sym_r_public").tooltip("Public site")
        theme_toggle(dark)

    with ui.left_drawer(value=True).classes("tv-glass p-3").props(
        "breakpoint=1024 width=220"
    ) as drawer:
        ui.label("AGENCY DESK").classes("tv-eyebrow px-3 pt-1 pb-2") \
            .style("color: var(--tv-teal)")
        for label, target, icon in nav_for(user):
            ui.button(label,
                      on_click=lambda t=target: ui.navigate.to(t)) \
                .props(f"flat align=left icon={icon} no-caps") \
                .classes("tv-nav-item w-full justify-start font-medium")
        ui.space()
        if user.is_manager:
            ui.label("Manager view: whole office").classes(
                "tv-mono text-[10px] tv-muted px-3 pb-1")
        else:
            ui.label("Your own client book").classes(
                "tv-mono text-[10px] tv-muted px-3 pb-1")

    with ui.column().classes(
        "w-full max-w-6xl mx-auto p-4 gap-5 tv-fade-in"
    ) as body:
        yield body


def money_label(amount: Any, currency: str = "EUR") -> str:
    """Format an amount. Returns a string - it does not create an element."""
    try:
        return f"{float(amount):,.2f} {currency}"
    except (TypeError, ValueError):
        return f"- {currency}"


def status_chip(status: str) -> None:
    colours = {
        "draft": "grey", "sent": "teal", "accepted": "green",
        "rejected": "red", "expired": "grey", "booked": "green",
        "cancelled": "red", "pending": "amber",
        "confirmed": "green", "paid": "green", "part_paid": "amber",
    }
    ui.label(status.replace("_", " ")).classes("tv-badge").style(
        f"color: var(--q-{colours.get(status, 'primary')})")
