# -*- coding: utf-8 -*-

"""App shell: glass header, navigation sidebar, theme toggle."""

from contextlib import contextmanager

from nicegui import ui

from app.ui.theme import apply_theme, theme_toggle

NAV = [
    ("Explore", "/", "sym_r_flight_takeoff"),
    ("AI Copilot", "/chat", "sym_r_forum"),
    ("My account", "/account", "sym_r_person"),
    ("Settings", "/settings", "sym_r_tune"),
]


def _session_button() -> None:
    from nicegui import app

    auth = app.storage.user.get("auth")
    if auth and auth.get("user_id"):
        label = auth.get("display_name") or auth.get("email", "Account")
        ui.button(label,
                  on_click=lambda: ui.navigate.to("/account")).props(
            "flat icon=account_circle"
        )
        if auth.get("is_admin"):
            ui.button(on_click=lambda: ui.navigate.to("/admin")).props(
                "flat round icon=admin_panel_settings"
            ).tooltip("Admin dashboard")
    else:
        ui.button("Sign in",
                  on_click=lambda: ui.navigate.to("/login")).props(
            "flat icon=login"
        )


@contextmanager
def page_shell(title: str):
    """Wrap a page body with the shared shell."""
    dark = apply_theme()

    with ui.header().classes(
        "tv-glass items-center px-4 py-2 gap-3"
    ).props("elevated=false"):
        ui.button(on_click=lambda: drawer.toggle()).props(
            "flat round icon=sym_r_menu"
        ).classes("lg:hidden")
        ui.icon("sym_r_explore").classes("text-2xl text-primary")
        ui.label("TripVerse").classes(
            "tv-display text-xl font-semibold"
        )
        ui.label(title).classes(
            "tv-mono text-xs uppercase tracking-widest tv-muted "
            "hidden sm:block mt-1"
        )
        ui.space()
        _session_button()
        theme_toggle(dark)

    with ui.left_drawer(value=True).classes("tv-glass p-3").props(
        "breakpoint=1024 width=228"
    ) as drawer:
        ui.label("FLIGHT DECK").classes(
            "tv-eyebrow px-3 pt-1 pb-2"
        ).style("color: var(--tv-teal)")
        for label, target, icon in NAV:
            ui.button(
                label, on_click=lambda t=target: ui.navigate.to(t)
            ).props(f"flat align=left icon={icon} no-caps").classes(
                "tv-nav-item w-full justify-start font-medium"
            )
        ui.space()
        ui.label("Real data only — nothing estimated").classes(
            "tv-mono text-[10px] tv-muted px-3 pb-1"
        )

    with ui.column().classes(
        "w-full max-w-6xl mx-auto p-4 gap-6 tv-fade-in"
    ) as body:
        yield body
