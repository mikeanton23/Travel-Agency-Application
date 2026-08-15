# -*- coding: utf-8 -*-

"""
Travel Intelligence Platform -- v2 pages.

Routes:
    /                    Explore: NL search + filters + card grid
    /destination/{id}    Detail: map, real costs, AI score with reasons
    /chat                AI Copilot (streaming, memory)
    /settings            Encrypted API keys + validation

Every number rendered here is real API/database data or an explicit
"unavailable" state -- nothing estimated.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from nicegui import ui

from app.db.database import SessionLocal
from app.repositories.destination_repository import DestinationRepository
from app.services.cost_service import cost_service
from app.services.discovery import discovery_service
from app.utils.dates import month_matches
from app.services.image_service import image_service
from app.services.seo import hotels_city_path
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
INTEREST_OPTIONS = ["food", "history", "nature", "nightlife",
                    "family", "adventure", "luxury", "hidden_gem",
                    "beach", "wine", "museums", "shopping",
                    "romantic", "wellness", "skiing", "diving",
                    "hiking", "photography", "architecture",
                    "nomad"]
TRAVEL_STYLES = ["solo", "couple", "family", "friends",
                 "business", "backpacking", "roadtrip",
                 "city break", "island hopping"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def _parse_iso(value):
    """ISO date from a date input, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


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
                ui.label("DEPARTURES - LIVE DATA BOARD").classes(
                    "tv-eyebrow"
                )
                ui.label(
                    "Where does the data say you should go?"
                ).classes(
                    "tv-display text-3xl sm:text-5xl font-semibold "
                    "leading-tight"
                )
                ui.label(
                    "Real prices, real weather, real places -- scored "
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
                "LIVE WEATHER - OPEN-METEO -- REAL PRICES - NUMBEO -- "
                "FARES & HOTELS - AMADEUS -- PLACES - GEOAPIFY -- "
                "EVENTS - TICKETMASTER -- PHOTOS - PEXELS -- "
                "NOTHING ESTIMATED, EVER -- "
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
                ui.label("Filters").classes(
                    "tv-display text-lg font-semibold")

                # ---- Where ----
                ui.label("WHERE").classes("tv-eyebrow pt-1").style(
                    "color: var(--tv-teal)")
                continent_select = ui.select(
                    CONTINENTS, value="Any", label="Continent"
                ).props("dense outlined").classes("w-full")
                country_input = ui.input(
                    label="Country contains",
                ).props("dense outlined clearable").classes("w-full")
                name_input = ui.input(
                    label="Destination name contains",
                ).props("dense outlined clearable").classes("w-full")

                # ---- When ----
                ui.label("WHEN").classes("tv-eyebrow pt-2").style(
                    "color: var(--tv-teal)")
                date_mode = ui.toggle(
                    {"month": "By month", "dates": "Exact dates"},
                    value="month",
                ).props("dense no-caps").classes("w-full")
                month_select = ui.select(
                    {i + 1: name for i, name in enumerate(MONTH_NAMES)},
                    value=date.today().month, label="Travel month",
                ).props("dense outlined").classes("w-full")
                start_input = ui.input(label="Start date").props(
                    "dense outlined type=date").classes("w-full")
                end_input = ui.input(label="End date").props(
                    "dense outlined type=date").classes("w-full")
                trip_note = ui.label("").classes(
                    "tv-mono text-[10px] tv-muted")
                start_input.visible = False
                end_input.visible = False

                def _sync_when() -> None:
                    """Exact dates drive the month used for climate and
                    scoring, so the two controls never disagree."""
                    by_dates = date_mode.value == "dates"
                    start_input.visible = by_dates
                    end_input.visible = by_dates
                    month_select.visible = not by_dates
                    if not by_dates:
                        trip_note.set_text("")
                        return
                    start = _parse_iso(start_input.value)
                    end = _parse_iso(end_input.value)
                    if start is None:
                        trip_note.set_text("Pick a start date")
                        return
                    if end is None or end <= start:
                        end = start + timedelta(days=3)
                        end_input.set_value(end.isoformat())
                    month_select.set_value(start.month)
                    nights = (end - start).days
                    trip_note.set_text(
                        f"{nights} nights in "
                        f"{MONTH_NAMES[start.month - 1]}")

                date_mode.on_value_change(lambda _: _sync_when())
                start_input.on_value_change(lambda _: _sync_when())
                end_input.on_value_change(lambda _: _sync_when())

                # ---- Budget ----
                ui.label("BUDGET").classes("tv-eyebrow pt-2").style(
                    "color: var(--tv-teal)")
                budget_max = ui.number(
                    label="Max per day", value=None, min=0,
                    placeholder="any amount",
                ).props("dense outlined").classes("w-full")
                budget_currency = ui.select(
                    ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD"],
                    value="EUR", label="Currency",
                ).props("dense outlined").classes("w-full")
                ui.label(
                    "One number, your own cap. Used to filter listed "
                    "costs and to score budget match against real "
                    "prices."
                ).classes("text-[10px] tv-muted")

                # ---- Taste ----
                ui.label("TASTE").classes("tv-eyebrow pt-2").style(
                    "color: var(--tv-teal)")
                interests_select = ui.select(
                    INTEREST_OPTIONS, multiple=True, label="Interests",
                ).props("use-chips dense outlined").classes("w-full")
                travel_style = ui.select(
                    TRAVEL_STYLES, multiple=True, label="Trip style",
                ).props("use-chips dense outlined").classes("w-full")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    temp_min = ui.number(label="Min C", value=18).props(
                        "dense outlined").classes("flex-grow")
                    temp_max = ui.number(label="Max C", value=27).props(
                        "dense outlined").classes("flex-grow")
                rain_max = ui.number(
                    label="Max rainy days / month", value=None,
                    min=0, max=31, placeholder="any",
                ).props("dense outlined").classes("w-full")
                with_kids = ui.checkbox("Travelling with kids")
                sort_select = ui.select(
                    ["AI score", "Cost: low to high",
                     "Cost: high to low", "Name: A to Z"],
                    value="AI score", label="Sort by",
                ).props("dense outlined").classes("w-full")

                with ui.row().classes("w-full gap-2 pt-2"):
                    ui.button("Apply",
                              on_click=lambda: asyncio.create_task(
                                  run_search(reset_offset=True))).props(
                        "unelevated color=primary dense no-caps "
                        "icon=sym_r_filter_alt").classes("flex-grow")
                    ui.button(on_click=lambda: reset_filters()).props(
                        "outline dense no-caps icon=sym_r_restart_alt"
                    ).tooltip("Reset filters")

                def reset_filters() -> None:
                    continent_select.set_value("Any")
                    country_input.set_value("")
                    name_input.set_value("")
                    date_mode.set_value("month")
                    month_select.set_value(date.today().month)
                    start_input.set_value("")
                    end_input.set_value("")
                    budget_max.set_value(None)
                    interests_select.set_value([])
                    travel_style.set_value([])
                    temp_min.set_value(18)
                    temp_max.set_value(27)
                    rain_max.set_value(None)
                    with_kids.set_value(False)
                    sort_select.set_value("AI score")
                    _sync_when()
                    asyncio.create_task(run_search())

                # Dynamic: any change re-runs the search.
                for widget in (continent_select, month_select,
                               interests_select, travel_style,
                               sort_select, with_kids, budget_currency):
                    widget.on_value_change(
                        lambda _: asyncio.create_task(
                            run_search(reset_offset=True)))
                for widget in (country_input, name_input,
                               budget_max, rain_max, temp_min,
                               temp_max):
                    widget.on("blur",
                              lambda _: asyncio.create_task(
                                  run_search(reset_offset=True)))

                _sync_when()

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

        discovery_state: Dict[str, int] = {"offset": 0}

        async def show_more() -> None:
            discovery_state["offset"] += 24
            await run_search()

        async def run_search(reset_offset: bool = False) -> None:
            if reset_offset:
                discovery_state["offset"] = 0
            results_grid.clear()
            with results_grid:
                for _ in range(6):
                    skeleton_card()

            text = nl_input.value.strip() if nl_input.value else ""
            parsed = None
            if text:
                from app.utils.settings import get_settings
                available = llm_service.available_providers()
                preferred = get_settings().nl_parse_provider.strip()
                if preferred and preferred in available:
                    provider = preferred
                else:
                    provider = next(
                        (p for p in ("gemini", "openai", "anthropic")
                         if p in available), None,
                    )
                parsed = await nl_search_parser.parse(
                    text, provider=provider)
                # Natural language fills the controls, which then stay
                # editable - the two never diverge silently.
                if parsed.continent:
                    continent_select.set_value(parsed.continent)
                if parsed.month:
                    month_select.set_value(parsed.month)
                if parsed.interests:
                    interests_select.set_value(parsed.interests)
                if parsed.budget_per_day and not budget_max.value:
                    budget_max.set_value(parsed.budget_per_day)
                if parsed.currency:
                    budget_currency.set_value(parsed.currency)
                if parsed.traveling_with_kids:
                    with_kids.set_value(True)
                parse_note.set_text(
                    "Understood: " + ", ".join(filter(None, [
                        (f"<={parsed.budget_per_day:.0f} "
                         f"{parsed.currency or ''}/day"
                         if parsed.budget_per_day else None),
                        parsed.continent,
                        "island" if parsed.wants_island else None,
                        "quiet" if parsed.wants_quiet else None,
                        *parsed.interests,
                    ])))

            def _num(widget):
                try:
                    return (float(widget.value)
                            if widget.value not in (None, "") else None)
                except (TypeError, ValueError):
                    return None

            budget_high = _num(budget_max)
            max_rain = _num(rain_max)

            destinations = await asyncio.to_thread(
                _search_db, name_input.value or None,
                continent_select.value, budget_high,
            )

            # Filters the repository query cannot express.
            country_text = (country_input.value or "").strip().lower()
            styles = travel_style.value or []
            chosen_interests = interests_select.value or []
            filtered = []
            for destination in destinations:
                if country_text and country_text not in \
                        (destination.country or "").lower():
                    continue
                # Interests are a ranking signal, not a hard filter:
                # tag coverage is sparse, and silently hiding a place
                # because nobody tagged it is worse than ordering it
                # lower. Strict filtering stays with budget and dates.
                tags = [str(x).lower()
                        for x in (getattr(destination, "tags", None)
                                  or [])]
                wanted = [w.lower() for w in
                          list(chosen_interests) + list(styles)]
                destination._match_score = sum(
                    1 for w in wanted
                    if any(w in tag or tag in w for tag in tags)
                ) if wanted else 0
                months = getattr(destination, "best_months", None) or []
                if months and month_select.value and \
                        not month_matches(months, month_select.value):
                    continue
                filtered.append(destination)

            sort_by = sort_select.value
            if sort_by == "Cost: low to high":
                filtered.sort(
                    key=lambda d: d.avg_cost_per_day or float("inf"))
            elif sort_by == "Cost: high to low":
                filtered.sort(
                    key=lambda d: d.avg_cost_per_day or 0,
                    reverse=True)
            elif sort_by == "Name: A to Z":
                filtered.sort(key=lambda d: (d.name or "").lower())
            else:
                filtered.sort(
                    key=lambda d: (getattr(d, "_match_score", 0),
                                   d.ai_score or 0),
                    reverse=True)

            results_grid.clear()

            # Nothing stored matches: look the place up for real
            # instead of showing an empty page. These come from live
            # geocoding, so they are genuine places with no stored
            # cost or score - the cards say so.
            discovered = []
            if not filtered:
                discovered = await discovery_service.suggest(
                    name=name_input.value or "",
                    country=country_input.value or "",
                    text=text,
                    continent=(continent_select.value
                               if continent_select.value != "Any"
                               else ""),
                    limit=24,
                    offset=discovery_state["offset"],
                )

            if not filtered and not discovered:
                with results_grid:
                    ui.label(
                        "No destinations match these filters, and we "
                        "could not find that place. Try a city or "
                        "country name, widen the budget, or clear a "
                        "filter - nothing is loosened silently."
                    ).classes("tv-muted")
                return

            month = month_select.value or date.today().month
            profile = UserProfile(
                budget_per_day=budget_high,
                month=month,
                preferred_temp_c=(_num(temp_min) or 18.0,
                                  _num(temp_max) or 27.0),
                interests=(chosen_interests
                           or (parsed.interests if parsed else [])),
                traveling_with_kids=bool(with_kids.value),
            )
            with results_grid:
                if filtered:
                    ui.label(
                        f"{len(filtered)} of {len(destinations)} "
                        f"saved destinations match"
                    ).classes(
                        "tv-mono text-xs tv-muted col-span-full")
                    for destination in filtered:
                        render_result(destination, profile, month,
                                      max_rain)
                if discovered:
                    ui.label(
                        f"{len(discovered)} places found live "
                        f"(Geoapify) - real locations, no stored cost "
                        f"or score yet"
                    ).classes(
                        "tv-mono text-xs tv-muted col-span-full")
                    for destination in discovered:
                        render_result(destination, profile, month,
                                      max_rain)
                    with ui.row().classes(
                        "col-span-full justify-center pt-2"
                    ):
                        ui.button(
                            "Show more places",
                            on_click=lambda: asyncio.create_task(
                                show_more()),
                        ).props("outline no-caps "
                                "icon=sym_r_expand_more")

        def render_result(destination, profile: UserProfile,
                          month: int, max_rain=None) -> None:
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
                            f"/destination/{d.id}" if getattr(
                                d, "id", None)
                            else hotels_city_path(d.name, d.country)
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
                # A rainy-days limit can only be honoured once the
                # real climate figure arrives.
                if max_rain is not None and climate and \
                        climate.get("rain_days") is not None and \
                        climate["rain_days"] > max_rain:
                    try:
                        card_holder.clear()
                    except RuntimeError:
                        pass
                    return
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
                        f"{destination.country} - "
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
import app.ui.pages_hotels  # noqa: E402,F401  (registers routes)
import app.ui.pages_staff  # noqa: E402,F401  (registers routes)
from app.ui.seo_routes import (  # noqa: E402
    register_payment_routes, register_seo_routes,
)

register_seo_routes()
register_payment_routes()


@ui.page("/settings")
def settings_page() -> None:
    with page_shell("Settings"):
        ui.label("Settings").classes("text-2xl font-bold")
        settings_panel(KeyManager())
