# -*- coding: utf-8 -*-

"""Travel Intelligence Score panel: per-dimension bars, each with its
WHY explanation; unavailable dimensions state their reason plainly."""

from typing import Any, Dict

from nicegui import ui

from app.ui.format import (
    ai_score_badge, dimension_display_name, score_color, score_label,
)


def score_panel(score: Dict[str, Any]) -> None:
    with ui.card().classes("tv-glass w-full p-4 gap-3"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("insights").classes("text-2xl text-primary")
            ui.label(
                ai_score_badge(score.get("overall"), score.get("coverage"))
            ).classes("text-lg font-semibold")
        ui.label(
            "AI-derived from real data only — dimensions without data "
            "say so instead of guessing."
        ).classes("text-xs opacity-60")

        for dim in score.get("dimensions", []):
            value = dim.get("score")
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes(
                    "w-full items-center justify-between"
                ):
                    ui.label(dimension_display_name(dim["name"])).classes(
                        "text-sm font-medium"
                    )
                    ui.label(score_label(value)).classes(
                        "text-sm font-mono"
                    )
                if value is not None:
                    ui.linear_progress(
                        value=value / 100, show_value=False
                    ).props(f"color={score_color(value)} rounded")
                ui.label(dim.get("reason", "")).classes(
                    "text-xs opacity-70"
                    + (" italic" if value is None else "")
                )
