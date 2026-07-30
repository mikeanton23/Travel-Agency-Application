# -*- coding: utf-8 -*-

"""Settings page: encrypted API-key management with live validation
and provider health — the UI over the Phase 1 key manager."""

import asyncio

from nicegui import ui

from app.services.key_manager import KeyManager
from app.ui.format import provider_status_color, provider_status_icon


def settings_panel(manager: KeyManager) -> None:
    with ui.card().classes("tv-glass w-full p-4 gap-2"):
        ui.label("API keys").classes("text-lg font-semibold")
        ui.label(
            "Stored encrypted (Fernet) in the database; a key saved "
            "here overrides the .env value. Validate runs one real "
            "minimal call against the provider."
        ).classes("text-xs opacity-60")
        rows_column = ui.column().classes("w-full gap-1")

        async def refresh() -> None:
            entries = await asyncio.to_thread(manager.list_keys)
            rows_column.clear()
            with rows_column:
                for entry in entries:
                    render_row(entry)

        def render_row(entry: dict) -> None:
            provider = entry["provider"]
            with ui.row().classes(
                "w-full items-center gap-3 py-1 border-b "
                "border-white/10"
            ):
                ui.icon(provider_status_icon(entry)).classes(
                    f"text-{provider_status_color(entry)}"
                )
                with ui.column().classes("w-56 gap-0"):
                    ui.label(entry.get("label", provider)).classes(
                        "text-sm font-medium"
                    )
                    if entry.get("tier"):
                        ui.label(entry["tier"]).classes(
                            "text-xs opacity-60"
                        )
                if entry.get("signup") and not entry.get("configured"):
                    ui.link("Get key", entry["signup"],
                            new_tab=True).classes("text-xs")
                source = (
                    "db (encrypted)" if entry["stored"]
                    else "env" if entry["env_fallback"]
                    else "not configured"
                )
                ui.label(source).classes("w-32 text-xs opacity-70")
                if entry.get("last_error"):
                    ui.icon("info").classes("text-amber-7").tooltip(
                        entry["last_error"]
                    )
                ui.space()
                key_input = ui.input(
                    password=True, placeholder="paste key"
                ).props("dense").classes("w-48")

                async def save(p=provider, field=key_input) -> None:
                    if not field.value:
                        return
                    await asyncio.to_thread(
                        manager.set_key, p, field.value
                    )
                    ui.notify(f"{p} key stored encrypted",
                              type="positive")
                    await refresh()

                async def validate(p=provider) -> None:
                    result = await manager.validate(p)
                    if result["is_valid"]:
                        ui.notify(f"{p}: key is valid",
                                  type="positive")
                    else:
                        ui.notify(f"{p}: {result['error']}",
                                  type="negative")
                    await refresh()

                ui.button(on_click=save).props(
                    "dense flat icon=save"
                ).tooltip("Save encrypted")
                ui.button(on_click=validate).props(
                    "dense flat icon=network_check"
                ).tooltip("Validate with a real API call")

        async def health_all() -> None:
            ui.notify("Checking every configured provider…")
            await manager.health()
            await refresh()
            ui.notify("Health check complete", type="positive")

        ui.button("Run health check on all providers",
                  on_click=health_all).props(
            "unelevated color=primary icon=monitor_heart"
        ).classes("mt-2")
        ui.timer(0.1, refresh, once=True)
