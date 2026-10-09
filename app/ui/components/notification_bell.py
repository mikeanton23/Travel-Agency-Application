# -*- coding: utf-8 -*-

"""
The header bell.

Sits beside the account chip and the day/night toggle on both the public
shell and the agency desk, so an agent sees a new "beat this price"
request wherever they happen to be in the app.

Every piece of UI built after the first render happens inside an
explicit ``with container:`` block. The timer callback runs in its own
task, where NiceGUI has no slot of its own to fall back on.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.notifications import KIND_ICONS, notification_service

logger = logging.getLogger(__name__)

#: How often the badge re-checks, in seconds. Long enough to be cheap,
#: short enough that an agent notices a request while the customer is
#: still on the phone.
POLL_SECONDS = 30.0

MAX_IN_MENU = 12


def _current_user_id() -> Optional[int]:
    from nicegui import app

    try:
        auth = app.storage.user.get("auth")
    except RuntimeError:          # no request context (startup, tests)
        return None
    if not auth or not auth.get("user_id"):
        return None
    return int(auth["user_id"])


def _relative(created_at: Optional[str]) -> str:
    """A short age label. Falls back to the raw date rather than guessing."""
    if not created_at:
        return ""
    from datetime import datetime, timezone

    try:
        when = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return created_at[:16]
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    return when.date().isoformat()


def notification_bell() -> None:
    """Render the bell. Renders nothing at all when signed out."""
    user_id = _current_user_id()
    if user_id is None:
        return

    state: Dict[str, Any] = {"unread": 0}

    # The glyph is an explicit child, not the q-btn `icon=` prop: a
    # button carrying its own default-slot content (the badge and the
    # menu below) can swallow that prop and render an empty circle.
    with ui.button(on_click=lambda: menu.open()).props(
        "flat round"
    ).tooltip("Notifications") as bell:

        glyph = ui.icon("sym_r_notifications")

        badge = ui.badge("").props("floating color=red").style(
            "display: none")

        with ui.menu().props("auto-close=false") as menu:
            with ui.column().classes("p-0 gap-0").style(
                "min-width: 330px; max-width: 390px"
            ):
                with ui.row().classes(
                    "w-full items-center px-3 py-2 gap-2"
                ).style("border-bottom: 1px solid var(--tv-line)"):
                    ui.label("Notifications").classes(
                        "tv-display text-base font-semibold")
                    ui.space()
                    mark_all = ui.button("Mark all read").props(
                        "flat dense no-caps size=sm")

                list_box = ui.column().classes("w-full gap-0").style(
                    "max-height: 60vh; overflow-y: auto")

    # ------------------------------------------------------------------

    def _open(target: Optional[str], notification_id: int) -> None:
        """Mark read, then go. Fired from a click, so a slot is active."""
        notification_service.mark_read(notification_id, user_id)
        menu.close()
        if target:
            ui.navigate.to(target)
        else:
            asyncio.ensure_future(_reload())

    def _render(rows: List[Dict[str, Any]]) -> None:
        list_box.clear()
        with list_box:
            if not rows:
                with ui.column().classes("w-full items-center p-6 gap-1"):
                    ui.icon("sym_r_notifications_off").classes(
                        "text-3xl").style("color: var(--tv-muted)")
                    ui.label("Nothing new").classes("text-sm tv-muted")
                return

            for row in rows:
                unread = not row["read"]
                card = ui.row().classes(
                    "w-full items-start gap-3 px-3 py-2 cursor-pointer"
                ).style(
                    "border-bottom: 1px solid var(--tv-line);"
                    + (" background: rgba(15,163,163,0.07);"
                       if unread else "")
                )
                card.on("click",
                        lambda r=row: _open(r.get("link"), r["id"]))
                with card:
                    ui.icon(
                        KIND_ICONS.get(row["kind"], KIND_ICONS["info"])
                    ).classes("text-primary mt-1")
                    with ui.column().classes("gap-0 flex-grow"):
                        ui.label(row["title"]).classes(
                            "text-sm "
                            + ("font-semibold" if unread else "font-normal"))
                        if row.get("body"):
                            ui.label(row["body"]).classes(
                                "text-xs tv-muted").style(
                                "white-space: normal")
                        ui.label(_relative(row.get("created_at"))).classes(
                            "tv-mono text-[10px] tv-muted")

    async def _reload() -> None:
        """Re-read the list and the count."""
        try:
            rows = await asyncio.to_thread(
                notification_service.list_for, user_id, MAX_IN_MENU)
            unread = await asyncio.to_thread(
                notification_service.unread_count, user_id)
        except Exception as exc:
            logger.warning("notification reload failed: %s", exc)
            return
        state["unread"] = unread
        _apply_badge(unread)
        _render(rows)

    def _apply_badge(unread: int) -> None:
        if unread > 0:
            badge.set_text(str(unread) if unread < 100 else "99+")
            badge.style("display: block")
            glyph.style("color: var(--tv-teal)")
        else:
            badge.set_text("")
            badge.style("display: none")
            glyph.style("color: inherit")

    async def _mark_all() -> None:
        await asyncio.to_thread(notification_service.mark_all_read, user_id)
        await _reload()

    mark_all.on_click(_mark_all)

    async def _poll() -> None:
        """Only the count on a tick; the list is rebuilt when it changes."""
        try:
            unread = await asyncio.to_thread(
                notification_service.unread_count, user_id)
        except Exception as exc:
            logger.debug("notification poll failed: %s", exc)
            return
        if unread != state["unread"]:
            state["unread"] = unread
            await _reload()

    ui.timer(POLL_SECONDS, _poll)
    ui.timer(0.1, _reload, once=True)
