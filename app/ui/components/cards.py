# -*- coding: utf-8 -*-

"""Destination cards v2: real photo (or a styled gradient placeholder
with the destination's initial — never a broken image box), name over
a dark gradient on the photo, glass badges, hover zoom, shimmer
skeletons. Badges without real data behind them simply don't render."""

from typing import Any, Callable, Dict, List, Optional

from nicegui import ui

from app.ui.format import (
    UNAVAILABLE, ai_score_badge, fmt_money, flag_emoji, score_color,
)


def skeleton_card() -> None:
    with ui.card().tight().classes("tv-glass tv-card w-full"):
        ui.element("div").classes("tv-shimmer w-full h-44")
        with ui.card_section().classes("w-full gap-2"):
            ui.element("div").classes("tv-shimmer w-2/3 h-5 rounded")
            ui.element("div").classes("tv-shimmer w-1/2 h-4 rounded")
            ui.element("div").classes("tv-shimmer w-full h-8 rounded")


def badge_row(badges: List[Optional[str]]) -> None:
    real = [b for b in badges if b]
    if not real:
        ui.label("Live data pending — nothing estimated").classes(
            "text-xs tv-muted italic"
        )
        return
    with ui.row().classes("gap-2 flex-wrap"):
        for text in real:
            ui.label(text).classes("tv-badge")


def _card_media(destination: Any, image_url: Optional[str],
                iso2: Optional[str],
                score: Optional[Dict[str, Any]]) -> None:
    with ui.element("div").classes("tv-media"):
        # Bottom layer: always the branded gradient with the initial,
        # so a slow or failed photo never leaves a blank box.
        with ui.element("div").classes("tv-placeholder"):
            ui.label(destination.name[:1].upper()).classes("tv-initial")

        if image_url:
            ui.image(image_url).classes(
                "tv-zoom absolute inset-0 w-full h-full"
            ).props('fit=cover no-spinner')

        ui.element("div").classes("tv-img-overlay")

        with ui.column().classes(
            "absolute bottom-2 left-3 right-3 gap-0 z-10"
        ):
            ui.label(destination.name).classes(
                "text-lg font-bold text-white leading-tight drop-shadow"
            )
            subtitle = destination.country or ""
            if destination.continent:
                subtitle = (f"{subtitle} · {destination.continent}"
                            if subtitle else destination.continent)
            ui.label(subtitle).classes("text-xs text-white/85")

        flag = flag_emoji(iso2)
        if flag:
            ui.label(flag).classes(
                "absolute top-2 left-3 text-2xl drop-shadow z-10"
            )
        if score:
            overall = score.get("overall")
            ui.label(
                ai_score_badge(overall, score.get("coverage"))
            ).classes(
                "tv-badge tv-badge-onimg absolute top-2 right-2 z-10"
            )


def destination_card(
    destination: Any,
    iso2: Optional[str] = None,
    image_url: Optional[str] = None,
    badges: Optional[List[Optional[str]]] = None,
    score: Optional[Dict[str, Any]] = None,
    on_open: Optional[Callable[[], None]] = None,
    on_score: Optional[Callable[[], None]] = None,
) -> None:
    if image_url is None:
        stored = getattr(destination, "image_urls", None)
        if stored:
            image_url = stored[0]

    with ui.card().tight().classes("tv-glass tv-card w-full"):
        _card_media(destination, image_url, iso2, score)
        with ui.card_section().classes("w-full gap-1 pt-3"):
            if destination.avg_cost_per_day:
                ui.label(
                    fmt_money(destination.avg_cost_per_day, "EUR", "day")
                    + "  · listed (database value)"
                ).classes("tv-mono text-xs tv-muted")
            badge_row(badges or [])
        with ui.card_actions().classes(
            "w-full justify-between px-4 pb-3"
        ):
            if on_score and not score:
                ui.button("AI score", on_click=on_score).props(
                    "flat dense icon=sym_r_radar no-caps"
                )
            elif score and score.get("overall") is not None:
                ui.label(f"{score['overall']:.0f}").classes(
                    "text-xl font-extrabold"
                ).style(
                    f"color: var(--q-{score_color(score['overall'])})"
                )
            if on_open:
                ui.button("Explore", on_click=on_open).props(
                    "unelevated dense color=primary "
                    "icon-right=sym_r_arrow_forward rounded no-caps"
                )
