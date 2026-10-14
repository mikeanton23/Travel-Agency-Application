# -*- coding: utf-8 -*-

"""
Who works here - /agency/staff. Manager only.

Exists so hiring someone does not require a database client. A new
colleague registers on the public site like anyone else, then appears
here as a customer, and the manager promotes them with one click.

The page shows the rules rather than hiding them: why a row is not
editable, and what happens when a role changes. A greyed-out dropdown
with no explanation is how people end up back in psql.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from nicegui import ui

from app.services.agency.staff import (
    ROLE_LABELS,
    StaffError,
    staff_service,
)
from app.ui.agency_common import (
    agency_shell,
    ensure_agency,
    require_agent,
)
from app.ui.helpers import safe_clear, spawn

log = logging.getLogger(__name__)

ROLE_COLOURS = {
    "customer": "#64748b",
    "agent": "#0FA3A3",
    "manager": "#15803d",
    "admin": "#b45309",
}


@ui.page("/agency/staff")
def agency_staff_page() -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')

    user = require_agent()
    if user is None:
        return

    if not user.is_manager:
        # Redirect rather than render-and-hide: the service refuses too,
        # but an agent should never see a staff list at all.
        ui.notify("Staff administration is manager only.", type="warning")
        ui.navigate.to("/agency")
        return

    agency_id = ensure_agency(user)
    if agency_id is None:
        return

    with agency_shell("Staff", user):
        with ui.column().classes("gap-0"):
            ui.label("Who works here").classes(
                "tv-display text-2xl font-semibold")
            ui.label(
                "A new colleague registers on the public site first, then "
                "appears below as a customer. Promote them to agent and "
                "they can use the desk on their next click - no sign-out "
                "needed."
            ).classes("text-sm tv-muted")

        body = ui.column().classes("w-full gap-2")

        async def load() -> None:
            try:
                people = staff_service.list_people(user, agency_id)
                assignable = staff_service.assignable_roles(user)
            except StaffError as exc:
                if not safe_clear(body):
                    return
                with body:
                    ui.label(str(exc)).style("color: #b45309")
                return
            except Exception as exc:
                log.exception("staff list failed")
                if not safe_clear(body):
                    return
                with body:
                    ui.label(
                        f"Could not load the staff list "
                        f"({type(exc).__name__})."
                    ).style("color: #dc2626")
                return

            if not safe_clear(body):
                return
            with body:
                _render(people, assignable)

        def _render(people: List[Dict[str, Any]],
                    assignable: List[str]) -> None:
            staff = [p for p in people if p["is_staff"]]
            others = [p for p in people if not p["is_staff"]]

            ui.label(
                f"{len(staff)} on the desk, {len(others)} registered "
                f"customer(s)"
            ).classes("tv-mono text-xs tv-muted")

            if staff:
                ui.label("Office").classes(
                    "tv-display text-lg font-semibold pt-2")
                for person in staff:
                    _person_card(person, assignable)

            if others:
                ui.label("Registered accounts").classes(
                    "tv-display text-lg font-semibold pt-3")
                ui.label(
                    "Customers of the public site. Promote one only if "
                    "they work for the agency."
                ).classes("text-xs tv-muted")
                for person in others:
                    _person_card(person, assignable)

            if not people:
                ui.label("Nobody has registered yet.").classes(
                    "text-sm tv-muted")

        def _person_card(person: Dict[str, Any],
                         assignable: List[str]) -> None:
            with ui.card().classes("tv-glass w-full p-3"):
                with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                    ui.icon(
                        "sym_r_badge" if person["is_staff"]
                        else "sym_r_person"
                    ).style(f"color: {ROLE_COLOURS.get(person['role'], '#64748b')}")

                    with ui.column().classes("gap-0").style("min-width: 220px"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(person["display_name"]).classes(
                                "font-medium")
                            if person["is_self"]:
                                ui.label("you").classes("tv-badge")
                            if not person["in_office"]:
                                ui.label("not yet in the office").classes(
                                    "tv-badge")
                        ui.label(person["email"]).classes(
                            "text-xs tv-muted")

                    ui.space()

                    status = ui.label("").classes("text-xs")

                    select = ui.select(
                        {r: ROLE_LABELS[r] for r in assignable},
                        value=person["role"]
                        if person["role"] in assignable else None,
                    ).props("dense outlined").style("min-width: 260px")

                    # Reasons a row is read-only, stated rather than
                    # silently disabling the control.
                    reason = ""
                    if person["is_self"]:
                        reason = "You cannot change your own role."
                    elif person["role"] not in assignable:
                        reason = (
                            f"Only an admin can change an "
                            f"{person['role']}'s role.")
                    if reason:
                        select.disable()
                        select.tooltip(reason)
                        ui.label(reason).classes("text-xs tv-muted")
                        return

                    async def save(target=person, chooser=select,
                                   label=status) -> None:
                        new_role = chooser.value
                        if not new_role or new_role == target["role"]:
                            return
                        try:
                            result = staff_service.set_role(
                                user, agency_id, target["id"], new_role)
                        except StaffError as exc:
                            label.set_text(str(exc))
                            label.style("color: #dc2626")
                            chooser.set_value(target["role"])
                            return
                        except Exception as exc:
                            log.exception("role change failed")
                            label.set_text(
                                f"Could not save ({type(exc).__name__}).")
                            label.style("color: #dc2626")
                            chooser.set_value(target["role"])
                            return
                        if result.get("changed"):
                            ui.notify(
                                f"{target['email']} is now "
                                f"{result['role']}", type="positive")
                        await load()

                    select.on_value_change(lambda e, fn=save: spawn(fn()))

        ui.timer(0.1, load, once=True)
