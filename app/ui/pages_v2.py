# -*- coding: utf-8 -*-

"""
Travel Intelligence Platform — v2 pages.

Routes:
    /                    Explore: NL search + filters + card grid
    /destination/{id}    Detail: map, real costs, AI score with reasons
    /chat                AI Copilot (streaming, memory)
    /settings            Encrypted API keys + validation

Every number rendered here is real API/database data or an explicit
"unavailable" state — nothing estimated.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from nicegui import ui

from app.db.database import SessionLocal
from app.repositories.destination_repository import DestinationRepository
from app.services.cost_service import cost_service
from app.services.image_service import image_service
from app.services.intelligence.score import UserProfile, compute_score
from app.services.intelligence.signals import signals_collector
from app.services.key_manager import KeyManager
from app.services.llm.service import LLMService
from app.services.nl_search import nl_search_parser
from app.ui.components.cards import destination_card, skeleton_card
from app.ui.components.chat_panel import chat_panel
from app.ui.components.layout import page_shell
from app.ui.components.score_panel import score_panel
from app.ui.components.settings_panel import settings_panel
from app.ui.format import cost_badge, unavailable_reason, weather_badge

llm_service = LLMService(session_factory=SessionLocal)

CONTINENTS = ["Any", "Europe", "Asia", "Africa", "North America",
              "South America", "Oceania"]
INTEREST_OPTIONS = ["food", "history", "nature", "nightlife", "family",
                    "adventure", "luxury", "hidden_gem", "beach"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def _search_db(query, continent, max_budget):
    session = SessionLocal()
    try:
        repo = DestinationRepository(session)
        return repo.search(
            query=query or None,
            continent=None if continent in (None, "Any") else continent,
            max_cost_per_day=max_budget,
        )
    finally:
        session.close()


def _get_destination(destination_id: int):
    session = SessionLocal()
    try:
        return DestinationRepository(session).get(destination_id)
    finally:
        session.close()


async def _score_for(destination, profile: UserProfile,
                     month: int) -> dict:
    signals = await signals_collector.collect(
        destination.name, destination.country,
        destination.latitude or 0.0, destination.longitude or 0.0,
        month=month,
    )
    return compute_score(signals, profile).to_dict()


@ui.page("/")
def explore_page() -> None:
    with page_shell("Explore"):
        # ---------------- Hero + natural-language search ----------------
        with ui.element("div").classes("tv-hero w-full"):
            with ui.column().classes(
                "w-full p-8 sm:p-12 pb-6 gap-2 relative z-10"
            ):
                ui.label("DEPARTURES · LIVE DATA BOARD").classes(
                    "tv-eyebrow"
                )
                ui.label(
                    "Where does the data say you should go?"
                ).classes(
                    "tv-display text-3xl sm:text-5xl font-semibold "
                    "leading-tight"
                )
                ui.label(
                    "Real prices, real weather, real places — scored "
                    "transparently."
                ).classes("opacity-85 text-sm sm:text-base")
                with ui.row().classes(
                    "w-full mt-4 gap-2 items-center"
                ):
                    nl_input = ui.input(
                        placeholder='Try: "romantic quiet island in '
                                    'Europe with wine tasting under '
                                    '$180/day"'
                    ).classes(
                        "tv-hero-input flex-grow px-4 text-black"
                    ).props("borderless dense")
                    search_button = ui.button("Search").props(
                        "unelevated color=accent text-color=black "
                        "icon=sym_r_travel_explore no-caps rounded"
                    )
            _ticker = (
                "LIVE WEATHER · OPEN-METEO — REAL PRICES · NUMBEO — "
                "FARES & HOTELS · AMADEUS — PLACES · GEOAPIFY — "
                "EVENTS · TICKETMASTER — PHOTOS · PEXELS — "
                "NOTHING ESTIMATED, EVER — "
            )
            with ui.element("div").classes(
                "tv-ticker w-full relative z-10"
            ):
                ui.label(_ticker * 2).classes("tv-ticker-track")

        # ---------------- Filters + results ----------------
        with ui.row().classes("w-full gap-6 items-start"):
            with ui.column().classes(
                "tv-glass p-4 gap-3 w-full sm:w-64 shrink-0"
            ):
                ui.label("Filters").classes("font-semibold")
                continent_select = ui.select(
                    CONTINENTS, value="Any", label="Continent"
                ).classes("w-full")
                budget_slider = ui.slider(
                    min=20, max=500, value=500, step=10
                ).props("label-always").classes("w-full")
                ui.label("Max listed cost / day (database value)") \
                    .classes("text-xs opacity-60 -mt-2")
                month_select = ui.select(
                    {i + 1: name for i, name in enumerate(MONTH_NAMES)},
                    value=9, label="Travel month",
                ).classes("w-full")
                interests_select = ui.select(
                    INTEREST_OPTIONS, multiple=True, label="Interests"
                ).props("use-chips").classes("w-full")
                parse_note = ui.label("").classes("tv-mono text-xs tv-muted")

            with ui.column().classes("flex-grow gap-3"):
                with ui.row().classes("items-baseline gap-3"):
                    ui.label("Departures").classes(
                        "tv-display text-2xl font-semibold"
                    )
                    ui.label("scored from live data").classes(
                        "tv-mono text-xs tv-muted uppercase "
                        "tracking-widest"
                    )
                results_grid = ui.element("div").classes(
                    "grid grid-cols-1 md:grid-cols-2 "
                    "xl:grid-cols-3 gap-4 w-full"
                )

        async def run_search() -> None:
            results_grid.clear()
            with results_grid:
                for _ in range(6):
                    skeleton_card()

            text = nl_input.value.strip()
            parsed = None
            if text:
                from app.utils.settings import get_settings
                available = llm_service.available_providers()
                # NL_PARSE_PROVIDER in .env overrides; otherwise prefer
                # Gemini (free tier) then paid providers. parse() falls
                # back to the rule-based parser on any provider error.
                preferred = get_settings().nl_parse_provider.strip()
                if preferred and preferred in available:
                    provider = preferred
                else:
                    provider = next(
                        (p for p in ("gemini", "openai", "anthropic")
                         if p in available), None,
                    )
                parsed = await nl_search_parser.parse(
                    text, provider=provider
                )
                if parsed.continent:
                    continent_select.set_value(parsed.continent)
                if parsed.month:
                    month_select.set_value(parsed.month)
                if parsed.interests:
                    interests_select.set_value(parsed.interests)
                parse_note.set_text(
                    "Understood: "
                    + ", ".join(filter(None, [
                        f"≤{parsed.budget_per_day:.0f} "
                        f"{parsed.currency or ''}/day"
                        if parsed.budget_per_day else None,
                        parsed.continent,
                        "island" if parsed.wants_island else None,
                        "quiet" if parsed.wants_quiet else None,
                        *parsed.interests,
                    ]))
                )

            destinations = await asyncio.to_thread(
                _search_db, None, continent_select.value,
                budget_slider.value,
            )
            results_grid.clear()
            if not destinations:
                with results_grid:
                    ui.label(
                        "No destinations match — adjust filters or seed "
                        "the database."
                    ).classes("opacity-70")
                return

            month = month_select.value or 9
            profile = UserProfile(
                budget_per_day=(parsed.budget_per_day
                                if parsed else None),
                month=month,
                interests=(parsed.interests if parsed
                           else (interests_select.value or [])),
                traveling_with_kids=bool(
                    parsed and parsed.traveling_with_kids
                ),
            )
            with results_grid:
                for destination in destinations:
                    render_result(destination, profile, month)

        def render_result(destination, profile: UserProfile,
                          month: int) -> None:
            card_holder = ui.element("div")
            # Async loads merge into one state so a late score doesn't
            # wipe out the photo, and vice versa.
            state = {"image": None, "badges": None, "score": None}

            def draw() -> None:
                try:
                    card_holder.clear()
                except RuntimeError:
                    return  # user navigated away; client is gone
                with card_holder:
                    destination_card(
                        destination,
                        image_url=state["image"],
                        badges=state["badges"],
                        score=state["score"],
                        on_open=lambda d=destination: ui.navigate.to(
                            f"/destination/{d.id}"
                        ),
                        on_score=lambda: asyncio.create_task(
                            load_score()
                        ),
                    )

            async def load_media_and_badges() -> None:
                image, costs, climate = await asyncio.gather(
                    image_service.destination_image(
                        destination.name, destination.country,
                        getattr(destination, "image_urls", None),
                    ),
                    cost_service.city_costs(destination.name,
                                            destination.country),
                    signals_collector.climate_month(
                        destination.latitude or 0.0,
                        destination.longitude or 0.0, month,
                    ),
                )
                state["image"] = image
                state["badges"] = [cost_badge(costs),
                                   weather_badge(climate)]
                try:
                    draw()
                except RuntimeError:
                    pass  # client closed while data was loading

            async def load_score() -> None:
                score = await _score_for(destination, profile, month)
                state["score"] = score
                try:
                    draw()
                except RuntimeError:
                    pass

            draw()
            asyncio.create_task(load_media_and_badges())

        search_button.on_click(run_search)
        nl_input.on("keydown.enter", run_search)
        ui.timer(0.1, run_search, once=True)


def _favorite_button(destination_id: int) -> None:
    from nicegui import app
    from app.repositories.user_repository import FavoriteRepository

    auth = app.storage.user.get("auth")
    if not auth or not auth.get("user_id"):
        return
    user_id = auth["user_id"]

    def _is_favorite() -> bool:
        session = SessionLocal()
        try:
            return FavoriteRepository(session).is_favorite(
                user_id, destination_id
            )
        finally:
            session.close()

    def _toggle() -> bool:
        session = SessionLocal()
        try:
            now_fav = FavoriteRepository(session).toggle(
                user_id, destination_id
            )
            session.commit()
            return now_fav
        finally:
            session.close()

    favorited = _is_favorite()
    button = ui.button().props(
        f"round flat text-color=white "
        f"icon={'favorite' if favorited else 'favorite_border'}"
    ).tooltip("Favorite")

    async def flip() -> None:
        now_fav = await asyncio.to_thread(_toggle)
        button.props(
            f"round flat text-color=white "
            f"icon={'favorite' if now_fav else 'favorite_border'}"
        )
        ui.notify("Added to favorites" if now_fav
                  else "Removed from favorites")

    button.on_click(flip)


@ui.page("/destination/{destination_id}")
def destination_page(destination_id: int) -> None:
    with page_shell("Destination"):
        destination = _get_destination(destination_id)
        if destination is None:
            ui.label("Destination not found.").classes("text-lg")
            ui.button("Back to Explore",
                      on_click=lambda: ui.navigate.to("/"))
            return

        with ui.row().classes("w-full items-start gap-6"):
            with ui.column().classes("flex-grow gap-4"):
                with ui.element("div").classes(
                    "tv-hero w-full p-8 relative overflow-hidden"
                ) as hero:
                    with ui.row().classes(
                        "w-full items-center relative z-10"
                    ):
                        ui.label(destination.name).classes(
                            "text-3xl font-extrabold text-white "
                            "drop-shadow"
                        )
                        ui.space()
                        _favorite_button(destination.id)
                    ui.label(
                        f"{destination.country} · "
                        f"{destination.continent or ''}"
                    ).classes("text-white/90 relative z-10")

                async def load_hero_image() -> None:
                    url = await image_service.destination_image(
                        destination.name, destination.country,
                        getattr(destination, "image_urls", None),
                    )
                    if not url:
                        return
                    try:
                        hero.style(
                            "background: linear-gradient(180deg,"
                            "rgba(10,10,30,.35),rgba(10,10,30,.65)),"
                            f"url('{url}') center/cover no-repeat;"
                            "animation: none;"
                        )
                        hero.update()
                    except RuntimeError:
                        pass

                ui.timer(0.1, load_hero_image, once=True)
                if destination.description:
                    ui.label(destination.description).classes(
                        "opacity-80"
                    )

                costs_holder = ui.column().classes("w-full")
                with costs_holder:
                    skeleton_card()

                score_holder = ui.column().classes("w-full")
                with score_holder:
                    ui.button(
                        "Compute Travel Intelligence Score",
                        on_click=lambda: asyncio.create_task(
                            load_score()
                        ),
                    ).props("unelevated color=primary icon=insights")

            with ui.column().classes("w-full lg:w-96 shrink-0 gap-4"):
                if destination.latitude and destination.longitude:
                    coords = (destination.latitude,
                              destination.longitude)
                    the_map = ui.leaflet(center=coords, zoom=11) \
                        .classes("w-full h-72 tv-glass")
                    the_map.marker(latlng=coords)
                else:
                    ui.label(unavailable_reason(
                        "Map", "no coordinates stored"
                    )).classes("opacity-60")

        async def load_costs() -> None:
            costs = await cost_service.city_costs(
                destination.name, destination.country
            )
            costs_holder.clear()
            with costs_holder, ui.card().classes(
                "tv-glass w-full p-4 gap-1"
            ):
                ui.label("Real daily prices (Numbeo)").classes(
                    "font-semibold"
                )
                if not costs:
                    ui.label(unavailable_reason(
                        "Cost data", cost_service.unavailable_reason()
                    )).classes("text-sm opacity-70 italic")
                    return
                currency = costs.get("currency", "")
                for key, entry in costs["items"].items():
                    ui.label(
                        f"{key.replace('_', ' ')}: "
                        f"{entry['average']:.2f} {currency}"
                    ).classes("text-sm")
                ui.label(
                    f"Source: Numbeo, {costs.get('contributors', '?')} "
                    f"contributors"
                ).classes("text-xs opacity-60")

        async def load_score() -> None:
            score_holder.clear()
            with score_holder:
                skeleton_card()
            score = await _score_for(
                destination, UserProfile(month=9), month=9
            )
            score_holder.clear()
            with score_holder:
                score_panel(score)

        ui.timer(0.1, load_costs, once=True)


@ui.page("/chat")
def chat_page() -> None:
    with page_shell("AI Copilot"):
        ui.label("AI Copilot").classes("text-2xl font-bold")
        ui.label(
            "Streaming answers with conversation memory. Providers with "
            "a valid key appear in the dropdown; Ollama runs locally."
        ).classes("text-sm opacity-70")
        chat_panel(llm_service)


import app.ui.pages_account  # noqa: E402,F401  (registers routes)


@ui.page("/settings")
def settings_page() -> None:
    with page_shell("Settings"):
        ui.label("Settings").classes("text-2xl font-bold")
        settings_panel(KeyManager())
