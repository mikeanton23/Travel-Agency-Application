# -*- coding: utf-8 -*-

"""
Phase 5 pages: /login, /account, /admin.

Session state lives in ``app.storage.user`` (server-side, signed with
APP_SECRET_KEY via NiceGUI's storage_secret). Guards redirect to
/login; /admin additionally requires the is_admin flag.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from nicegui import app, ui

from app.db.database import SessionLocal
from app.repositories.user_repository import (
    FavoriteRepository, NotificationRepository, TripRepository,
    UserAdminRepository,
)
from app.services.auth_service import AuthError, auth_service
from app.services.cache_service import api_cache
from app.services.key_manager import KeyManager
from app.services.metrics import metrics
from app.ui.components.cards import destination_card
from app.ui.components.layout import page_shell


# ----------------------------------------------------------------------
# Session helpers
# ----------------------------------------------------------------------

def current_user() -> Optional[dict]:
    data = app.storage.user.get("auth")
    return data if data and data.get("user_id") else None


def require_login() -> Optional[dict]:
    user = current_user()
    if user is None:
        ui.navigate.to("/login")
    return user


def require_admin() -> Optional[dict]:
    user = current_user()
    if user is None:
        ui.navigate.to("/login")
        return None
    if not user.get("is_admin"):
        ui.navigate.to("/")
        return None
    return user


def _client_key() -> str:
    try:
        from nicegui import context
        request = context.client.request
        return request.client.host if request and request.client \
            else "unknown"
    except Exception:
        return "unknown"


# ----------------------------------------------------------------------
# /login
# ----------------------------------------------------------------------

@ui.page("/login")
def login_page() -> None:
    with page_shell("Sign in"):
        with ui.card().classes(
            "tv-glass w-full max-w-md mx-auto p-6 gap-3"
        ):
            with ui.tabs().classes("w-full") as tabs:
                login_tab = ui.tab("Sign in")
                register_tab = ui.tab("Create account")
            with ui.tab_panels(tabs, value=login_tab).classes("w-full"):
                with ui.tab_panel(login_tab).classes("gap-3"):
                    email_in = ui.input("Email").classes("w-full")
                    password_in = ui.input(
                        "Password", password=True,
                        password_toggle_button=True,
                    ).classes("w-full")

                    async def do_login() -> None:
                        try:
                            user = await asyncio.to_thread(
                                auth_service.authenticate,
                                email_in.value, password_in.value,
                                _client_key(),
                            )
                        except AuthError as exc:
                            ui.notify(str(exc), type="negative")
                            return
                        app.storage.user["auth"] = {
                            "user_id": user.id, "email": user.email,
                            "display_name": user.display_name,
                            "is_admin": user.is_admin,
                        }
                        ui.navigate.to("/account")

                    password_in.on("keydown.enter", do_login)
                    ui.button("Sign in", on_click=do_login).props(
                        "unelevated color=primary"
                    ).classes("w-full")

                with ui.tab_panel(register_tab).classes("gap-3"):
                    name_r = ui.input("Display name").classes("w-full")
                    email_r = ui.input("Email").classes("w-full")
                    password_r = ui.input(
                        "Password (min 8 chars)", password=True,
                        password_toggle_button=True,
                    ).classes("w-full")

                    async def do_register() -> None:
                        try:
                            user = await asyncio.to_thread(
                                auth_service.register,
                                email_r.value, password_r.value,
                                name_r.value,
                            )
                        except AuthError as exc:
                            ui.notify(str(exc), type="negative")
                            return
                        app.storage.user["auth"] = {
                            "user_id": user.id, "email": user.email,
                            "display_name": user.display_name,
                            "is_admin": user.is_admin,
                        }
                        ui.notify("Welcome to Aevyra!",
                                  type="positive")
                        ui.navigate.to("/account")

                    ui.button("Create account",
                              on_click=do_register).props(
                        "unelevated color=primary"
                    ).classes("w-full")


# ----------------------------------------------------------------------
# /account
# ----------------------------------------------------------------------

def _load_account_data(user_id: int):
    """Return UI-ready data. Relationship counts are resolved inside
    the session so nothing lazy-loads after it closes."""
    session = SessionLocal()
    try:
        favorites = FavoriteRepository(session).destinations_for(user_id)
        # Detach favourites safely: the card only needs scalar columns.
        for destination in favorites:
            session.expunge(destination)

        trips = [
            {
                "id": trip.id,
                "title": trip.title,
                "status": trip.status,
                "item_count": len(trip.items),   # inside the session
                "currency": trip.currency,
            }
            for trip in TripRepository(session).for_user(user_id)
        ]

        notes_repo = NotificationRepository(session)
        notes = [
            {
                "id": note.id,
                "title": note.title,
                "body": note.body,
                "read": note.read_at is not None,
            }
            for note in notes_repo.for_user(user_id)
        ]
        unread = notes_repo.unread_count(user_id)
        return favorites, trips, notes, unread
    finally:
        session.close()


def _create_trip(user_id: int, title: str):
    session = SessionLocal()
    try:
        trip = TripRepository(session).create(user_id, title)
        session.commit()
        return trip.id
    finally:
        session.close()


def _mark_read(user_id: int, note_id: int) -> None:
    session = SessionLocal()
    try:
        NotificationRepository(session).mark_read(user_id, note_id)
        session.commit()
    finally:
        session.close()


@ui.page("/account")
def account_page() -> None:
    user = require_login()
    if user is None:
        return
    with page_shell("My account"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.icon("account_circle").classes("text-3xl text-primary")
            ui.label(
                user.get("display_name") or user["email"]
            ).classes("text-2xl font-bold")
            ui.space()

            def logout() -> None:
                app.storage.user.pop("auth", None)
                ui.navigate.to("/")

            ui.button("Sign out", on_click=logout).props(
                "flat icon=logout"
            )

        content = ui.column().classes("w-full gap-6")

        async def refresh() -> None:
            favorites, trips, notes, unread = await asyncio.to_thread(
                _load_account_data, user["user_id"]
            )
            content.clear()
            with content:
                # ---- Favorites ----
                ui.label("Favorites").classes("text-lg font-semibold")
                if not favorites:
                    ui.label(
                        "No favorites yet — tap the heart on any "
                        "destination."
                    ).classes("opacity-60 text-sm")
                with ui.element("div").classes(
                    "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 "
                    "gap-4 w-full"
                ):
                    for destination in favorites:
                        destination_card(
                            destination,
                            on_open=lambda d=destination:
                                ui.navigate.to(f"/destination/{d.id}"),
                        )

                # ---- Trips ----
                ui.label("Trips").classes("text-lg font-semibold mt-2")
                with ui.row().classes("w-full gap-2 items-center"):
                    trip_title = ui.input(
                        placeholder="New trip title…"
                    ).classes("flex-grow")

                    async def add_trip() -> None:
                        if not trip_title.value.strip():
                            return
                        await asyncio.to_thread(
                            _create_trip, user["user_id"],
                            trip_title.value,
                        )
                        trip_title.set_value("")
                        await refresh()

                    ui.button("Create", on_click=add_trip).props(
                        "unelevated color=primary icon=add"
                    )
                for trip in trips:
                    with ui.card().classes("tv-glass w-full p-3"):
                        with ui.row().classes(
                            "w-full items-center gap-3"
                        ):
                            ui.icon("sym_r_luggage")
                            ui.label(trip["title"]).classes(
                                "font-medium"
                            )
                            ui.label(trip["status"]).classes(
                                "tv-badge"
                            )
                            ui.space()
                            ui.label(
                                f"{trip['item_count']} items"
                            ).classes("tv-mono text-xs tv-muted")

                # ---- Notifications ----
                ui.label(
                    f"Notifications ({unread} unread)"
                ).classes("text-lg font-semibold mt-2")
                if not notes:
                    ui.label("Nothing here yet.").classes(
                        "opacity-60 text-sm"
                    )
                for note in notes:
                    with ui.row().classes(
                        "w-full items-center gap-2 py-1"
                    ):
                        ui.icon(
                            "sym_r_mark_email_read" if note["read"]
                            else "sym_r_mark_email_unread"
                        ).classes(
                            "opacity-50" if note["read"]
                            else "text-primary"
                        )
                        ui.label(note["title"]).classes(
                            "text-sm"
                            + (" opacity-60" if note["read"] else "")
                        )
                        ui.space()
                        if not note["read"]:
                            async def mark(n=note) -> None:
                                await asyncio.to_thread(
                                    _mark_read, user["user_id"], n["id"]
                                )
                                await refresh()

                            ui.button(on_click=mark).props(
                                "dense flat icon=sym_r_done"
                            ).tooltip("Mark read")

        ui.timer(0.1, refresh, once=True)


# ----------------------------------------------------------------------
# /admin
# ----------------------------------------------------------------------

def _db_status():
    from sqlalchemy import text
    from app.db.models import Destination, User

    session = SessionLocal()
    try:
        session.execute(text("SELECT 1"))
        return {
            "ok": True,
            "users": session.query(User).count(),
            "destinations": session.query(Destination).count(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        session.close()


def _all_users():
    session = SessionLocal()
    try:
        return [
            {"id": u.id, "email": u.email, "is_admin": u.is_admin,
             "is_active": u.is_active,
             "last_login": (u.last_login_at.isoformat()
                            if u.last_login_at else "never")}
            for u in UserAdminRepository(session).all_users()
        ]
    finally:
        session.close()


def _set_user_flag(user_id: int, field: str, value: bool) -> None:
    session = SessionLocal()
    try:
        repo = UserAdminRepository(session)
        if field == "active":
            repo.set_active(user_id, value)
        else:
            repo.set_admin(user_id, value)
        session.commit()
    finally:
        session.close()


@ui.page("/admin")
def admin_page() -> None:
    user = require_admin()
    if user is None:
        return
    with page_shell("Admin"):
        ui.label("Admin dashboard").classes("text-2xl font-bold")

        with ui.element("div").classes(
            "grid grid-cols-1 md:grid-cols-3 gap-4 w-full"
        ):
            db_card = ui.card().classes("tv-glass p-4 gap-1")
            cache_card = ui.card().classes("tv-glass p-4 gap-1")
            api_card = ui.card().classes("tv-glass p-4 gap-1")

        usage_card = ui.card().classes("tv-glass w-full p-4 gap-2")
        users_card = ui.card().classes("tv-glass w-full p-4 gap-2")

        async def refresh() -> None:
            status = await asyncio.to_thread(_db_status)
            db_card.clear()
            with db_card:
                ui.label("Database").classes("font-semibold")
                if status["ok"]:
                    ui.label("Connected").classes("text-green-6")
                    ui.label(
                        f"{status['users']} users · "
                        f"{status['destinations']} destinations"
                    ).classes("text-sm opacity-70")
                else:
                    ui.label("Error").classes("text-red-6")
                    ui.label(status.get("error", "")).classes(
                        "text-xs opacity-70"
                    )

            stats = api_cache.stats()
            cache_card.clear()
            with cache_card:
                ui.label("Cache").classes("font-semibold")
                rate = stats["hit_rate"]
                ui.label(
                    "No traffic yet" if rate is None
                    else f"{rate * 100:.0f}% hit rate"
                )
                ui.label(
                    f"{stats['hits']} hits · {stats['misses']} misses "
                    f"· {stats['memory_entries']} in memory · "
                    f"DB tier {'on' if stats['db_tier'] else 'off'}"
                ).classes("text-sm opacity-70")

            api_card.clear()
            with api_card:
                ui.label("API traffic (this process)").classes(
                    "font-semibold"
                )
                summary = metrics.summary()
                if not summary:
                    ui.label("No outbound calls yet").classes(
                        "text-sm opacity-70"
                    )
                for row in summary:
                    ui.label(
                        f"{row['provider']}: {row['requests']} req, "
                        f"{row['errors']} err, ~{row['avg_ms']}ms"
                    ).classes("text-sm")

            recent = await asyncio.to_thread(metrics.recent_usage, 25)
            usage_card.clear()
            with usage_card:
                ui.label("Recent API calls").classes("font-semibold")
                if not recent:
                    ui.label(
                        "No persisted usage yet."
                    ).classes("text-sm opacity-70")
                for row in recent:
                    ui.label(
                        f"[{row['at'] or '?'}] {row['provider']} "
                        f"{row['method']} {row['host']} → "
                        f"{row['status']} ({row['duration_ms']}ms)"
                    ).classes(
                        "text-xs font-mono"
                        + ("" if row["ok"] else " text-red-6")
                    )

            users = await asyncio.to_thread(_all_users)
            users_card.clear()
            with users_card:
                ui.label("Users").classes("font-semibold")
                for entry in users:
                    with ui.row().classes(
                        "w-full items-center gap-3 py-1"
                    ):
                        ui.label(str(entry["id"])).classes(
                            "w-8 text-xs opacity-60"
                        )
                        ui.label(entry["email"]).classes(
                            "flex-grow text-sm"
                        )
                        ui.label(
                            f"last login {entry['last_login']}"
                        ).classes("text-xs opacity-60")

                        async def flip_active(e=entry) -> None:
                            await asyncio.to_thread(
                                _set_user_flag, e["id"], "active",
                                not e["is_active"],
                            )
                            await refresh()

                        async def flip_admin(e=entry) -> None:
                            await asyncio.to_thread(
                                _set_user_flag, e["id"], "admin",
                                not e["is_admin"],
                            )
                            await refresh()

                        ui.button(
                            "active" if entry["is_active"]
                            else "disabled",
                            on_click=flip_active,
                        ).props(
                            "dense flat "
                            + ("color=green" if entry["is_active"]
                               else "color=red")
                        )
                        ui.button(
                            "admin" if entry["is_admin"] else "user",
                            on_click=flip_admin,
                        ).props(
                            "dense flat "
                            + ("color=purple" if entry["is_admin"]
                               else "")
                        )

        async def key_health() -> None:
            ui.notify("Validating all configured provider keys…")
            await KeyManager().health()
            ui.notify("Provider health updated — see Settings",
                      type="positive")

        with ui.row().classes("gap-2"):
            ui.button("Refresh", on_click=refresh).props(
                "unelevated color=primary icon=refresh"
            )
            ui.button("Check provider keys", on_click=key_health).props(
                "flat icon=monitor_heart"
            )
        ui.timer(0.1, refresh, once=True)
