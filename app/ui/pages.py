# -*- coding: utf-8 -*-

import asyncio
import random
import traceback

from nicegui import ui

from app.services.comparison_service import build_destination_comparison
from app.services.recommendation_service import get_recommendations
from app.services.itinerary_service import create_itinerary, itinerary_to_markdown
from app.services.weather_service import WeatherService
from app.services.llm_service import enhance_itinerary_with_ai
from app.services.image_service import get_destination_image, get_place_image
from app.services.travel_plan_service import (
    get_saved_travel_plan,
    save_travel_plan,
)
from app.services.restcountries_service import get_countries_by_continent


FALLBACK_IMAGE = "https://images.pexels.com/photos/346885/pexels-photo-346885.jpeg"

PROMPT_IDEAS = [
    "Romantic islands with sunsets, sea views, local food, cozy hotels, calm nightlife, and cultural walks.",
    "Hidden nature escapes with scenic villages, viewpoints, walking routes, authentic food, and peaceful stays.",
    "Cultural old towns with museums, cafes, wine bars, historic streets, architecture, and local experiences.",
    "Luxury relaxing sea views with boutique hotels, sunset dinners, beaches, spa-like calm, and slow travel.",
    "Budget-friendly hidden gems with safe walkable areas, local restaurants, culture, nature, and good value.",
]


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=1) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_text(value, default="") -> str:
    value = str(value or "").strip()
    return value if value else default


def _get_attr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def home_page():
    ui.add_head_html("""
    <style>
        body {
            margin: 0;
            background:
                radial-gradient(circle at top left, rgba(37,99,235,.22), transparent 35%),
                radial-gradient(circle at top right, rgba(124,58,237,.20), transparent 35%),
                linear-gradient(135deg, #f8fafc, #eef2ff);
            font-family: Inter, Arial, sans-serif;
        }

        .page-shell {
            max-width: 1500px;
            margin: 0 auto;
            padding: 28px;
        }

        .hero {
            min-height: 470px;
            border-radius: 42px;
            padding: 64px 70px 145px 70px;
            color: white;
            background:
                linear-gradient(120deg, rgba(15,23,42,.96), rgba(15,23,42,.48)),
                url('https://images.unsplash.com/photo-1500530855697-b586d89ba3ee');
            background-size: cover;
            background-position: center;
            box-shadow: 0 35px 95px rgba(15,23,42,.32);
            overflow: hidden;
        }

        .hero-title {
            font-size: 64px;
            line-height: 1.02;
            font-weight: 950;
            max-width: 1050px;
        }

        .hero-subtitle {
            font-size: 21px;
            line-height: 1.55;
            max-width: 950px;
            color: #dbeafe;
            margin-top: 22px;
        }

        .kicker {
            display: inline-flex;
            background: rgba(255,255,255,.16);
            border: 1px solid rgba(255,255,255,.28);
            backdrop-filter: blur(14px);
            border-radius: 999px;
            padding: 10px 16px;
            font-weight: 900;
            font-size: 13px;
            margin-bottom: 24px;
        }

        .search-panel {
            margin-top: -98px;
            position: relative;
            z-index: 5;
            background: rgba(255,255,255,.96);
            border: 1px solid rgba(255,255,255,.85);
            backdrop-filter: blur(26px);
            border-radius: 36px;
            box-shadow: 0 35px 90px rgba(15,23,42,.18);
            padding: 32px;
        }

        .mode-btn,
        .primary-btn,
        .dark-btn,
        .map-layer-pill {
            cursor: pointer !important;
            pointer-events: auto !important;
        }

        .mode-btn {
            border-radius: 999px !important;
            padding: 12px 24px !important;
            font-weight: 950 !important;
            border: 1px solid #dbeafe !important;
            background: white !important;
            color: #1e3a8a !important;
            box-shadow: 0 8px 20px rgba(15,23,42,.08);
            text-transform: none !important;
        }

        .mode-btn-active {
            background: linear-gradient(135deg, #2563eb, #7c3aed) !important;
            color: white !important;
            border: 1px solid transparent !important;
        }

        .field-card {
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 22px;
            padding: 14px;
            box-shadow: 0 12px 28px rgba(15,23,42,.06);
        }

        .innovation-card {
            background: linear-gradient(135deg, #f8fafc, #eef2ff);
            border: 1px solid #dbeafe;
            border-radius: 26px;
            padding: 18px;
        }

        .prompt-chip {
            background: white;
            color: #334155;
            border: 1px solid #e2e8f0;
            border-radius: 999px;
            padding: 10px 15px;
            font-size: 13px;
            font-weight: 850;
            cursor: pointer;
            transition: .2s;
            pointer-events: auto;
        }

        .prompt-chip:hover {
            background: #2563eb;
            color: white;
            transform: translateY(-2px);
        }

        .destination-card {
            border-radius: 30px;
            overflow: hidden;
            background: white;
            border: 1px solid #e2e8f0;
            box-shadow: 0 22px 55px rgba(15,23,42,.13);
            transition: .25s ease;
        }

        .destination-card:hover {
            transform: translateY(-8px);
            box-shadow: 0 30px 75px rgba(15,23,42,.20);
        }

        .destination-img {
            height: 275px;
            width: 100%;
            object-fit: cover;
            background: #e5e7eb;
        }

        .score-pill {
            background: linear-gradient(135deg, #16a34a, #22c55e);
            color: white;
            border-radius: 999px;
            padding: 7px 13px;
            font-size: 13px;
            font-weight: 950;
        }

        .small-pill {
            background: #eff6ff;
            color: #1d4ed8;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 13px;
            font-weight: 850;
        }

        .dark-pill {
            background: #0f172a;
            color: white;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 13px;
            font-weight: 850;
        }

        .risk-pill {
            background: #fff7ed;
            color: #c2410c;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 13px;
            font-weight: 850;
        }

        .ai-note {
            background: linear-gradient(135deg, #f0fdf4, #ecfeff);
            border: 1px solid #bbf7d0;
            border-radius: 18px;
            padding: 12px;
            color: #166534;
            font-size: 14px;
            font-weight: 650;
        }

        .warning-note {
            background: #fff7ed;
            border: 1px solid #fed7aa;
            border-radius: 18px;
            padding: 12px;
            color: #9a3412;
            font-size: 14px;
            font-weight: 650;
        }

        .insight-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 14px;
        }

        .primary-btn {
            border-radius: 18px !important;
            background: linear-gradient(135deg, #2563eb, #7c3aed) !important;
            color: white !important;
            font-weight: 950 !important;
            box-shadow: 0 14px 30px rgba(37,99,235,.28);
            text-transform: none !important;
        }

        .dark-btn {
            border-radius: 18px !important;
            background: #0f172a !important;
            color: white !important;
            font-weight: 950 !important;
            text-transform: none !important;
        }

        .skeleton-card {
            height: 430px;
            border-radius: 30px;
            background: linear-gradient(90deg, #e5e7eb 25%, #f8fafc 37%, #e5e7eb 63%);
            background-size: 400% 100%;
            animation: shimmer 1.4s infinite;
        }

        @keyframes shimmer {
            0% { background-position: 100% 0; }
            100% { background-position: 0 0; }
        }

        .plan-dialog {
            border-radius: 32px;
            padding: 28px;
            max-height: 92vh;
            overflow-y: auto;
        }

        .plan-markdown {
            line-height: 1.75;
            font-size: 16px;
        }

        .compare-bar {
            position: sticky;
            bottom: 18px;
            z-index: 50;
            background: rgba(15,23,42,.96);
            color: white;
            border-radius: 24px;
            padding: 16px 20px;
            box-shadow: 0 20px 55px rgba(15,23,42,.35);
            pointer-events: auto;
        }

        .compare-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 24px;
            padding: 18px;
            box-shadow: 0 14px 35px rgba(15,23,42,.10);
        }

        .winner-card {
            background: linear-gradient(135deg, #ecfdf5, #eff6ff);
            border: 1px solid #bbf7d0;
            border-radius: 26px;
            padding: 20px;
        }

        .map-os-panel {
            position: relative;
            overflow: visible;
            background: linear-gradient(135deg, #0f172a, #1e1b4b);
            color: white;
            border-radius: 32px;
            padding: 24px;
            box-shadow: 0 24px 70px rgba(15,23,42,.25);
            border: 1px solid rgba(255,255,255,.14);
            pointer-events: auto;
            z-index: 20;
        }

        .map-header {
            position: relative;
            z-index: 100;
            pointer-events: auto;
        }

        .map-layer-row {
            position: relative;
            z-index: 120;
            pointer-events: auto;
        }

        .map-canvas {
            min-height: 360px;
            border-radius: 28px;
            background:
                radial-gradient(circle at 20% 30%, rgba(34,197,94,.45), transparent 16%),
                radial-gradient(circle at 65% 35%, rgba(234,179,8,.42), transparent 15%),
                radial-gradient(circle at 80% 70%, rgba(239,68,68,.35), transparent 14%),
                linear-gradient(135deg, #dbeafe, #eef2ff);
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,.45);
            pointer-events: none;
            z-index: 1;
        }

        .map-dot {
            position: absolute;
            transform: translate(-50%, -50%);
            border-radius: 999px;
            padding: 8px 11px;
            background: #0f172a;
            color: white;
            font-size: 12px;
            font-weight: 950;
            box-shadow: 0 12px 30px rgba(15,23,42,.35);
            border: 2px solid white;
            max-width: 190px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            pointer-events: auto;
            z-index: 2;
        }

        .map-layer-pill {
            position: relative;
            z-index: 130;
            background: rgba(255,255,255,.12) !important;
            border: 1px solid rgba(255,255,255,.20) !important;
            color: white !important;
            border-radius: 999px !important;
            padding: 8px 12px !important;
            font-size: 12px !important;
            font-weight: 900 !important;
            user-select: none;
            text-transform: none !important;
            min-height: 34px !important;
        }

        .map-layer-pill:hover {
            background: rgba(255,255,255,.24) !important;
        }

        .map-layer-pill-active {
            background: linear-gradient(135deg, #22c55e, #2563eb) !important;
            border-color: rgba(255,255,255,.55) !important;
            box-shadow: 0 10px 28px rgba(37,99,235,.35);
        }
    </style>
    """)

    with ui.column().classes("page-shell gap-8"):

        with ui.element("div").classes("hero w-full"):
            ui.label("Aevyra AI Travel OS").classes("kicker")
            ui.label("Simulate the trip before you choose it.").classes("hero-title")
            ui.label(
                "Global discovery, country focus, AI Trip Twin, regret prediction, budget realism, "
                "crowd strategy, hidden-gem scoring, local authenticity, and destination reality simulation."
            ).classes("hero-subtitle")

        with ui.card().classes("search-panel w-full"):
            search_mode = {"value": "global"}

            with ui.row().classes("w-full items-center justify-between gap-4"):
                with ui.column().classes("gap-1"):
                    ui.label("Build your intelligent trip").classes("text-3xl font-black text-slate-900")
                    ui.label("Choose how the AI should think, not only where it should search.").classes("text-slate-500")

                with ui.row().classes("gap-2 relative z-50 pointer-events-auto"):
                    global_btn = ui.button("Global Search")
                    country_btn = ui.button("Country Focus")
                    global_btn.classes("mode-btn mode-btn-active")
                    country_btn.classes("mode-btn")

            with ui.grid(columns=6).classes("w-full gap-4 mt-6"):
                with ui.element("div").classes("field-card"):
                    budget = ui.number("Budget / day", value=120, min=1).classes("w-full").props("outlined suffix='EUR'")

                with ui.element("div").classes("field-card"):
                    month = ui.select(
                        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
                        label="Month",
                        value="Jun",
                    ).classes("w-full").props("outlined")

                with ui.element("div").classes("field-card"):
                    travelers = ui.select(
                        ["Solo", "Couple", "Friends", "Family"],
                        label="Travelers",
                        value="Couple",
                    ).classes("w-full").props("outlined")

                with ui.element("div").classes("field-card"):
                    continent = ui.select(
                        ["Any", "Europe", "Asia", "Africa", "North America", "South America", "Oceania"],
                        label="Continent",
                        value="Any",
                    ).classes("w-full").props("outlined")

                with ui.element("div").classes("field-card"):
                    country = ui.select(
                        ["Any"] + get_countries_by_continent("Any"),
                        label="Country",
                        value="Any",
                    ).classes("w-full").props("outlined use-input clearable")

                with ui.element("div").classes("field-card"):
                    trip_days = ui.number("Days", value=5, min=1, max=60).classes("w-full").props("outlined")

            def refresh_mode_buttons():
                if search_mode["value"] == "global":
                    global_btn.classes(add="mode-btn-active")
                    country_btn.classes(remove="mode-btn-active")
                else:
                    country_btn.classes(add="mode-btn-active")
                    global_btn.classes(remove="mode-btn-active")

            def set_global_mode():
                search_mode["value"] = "global"
                country.value = "Any"
                country.disable()
                country.update()
                refresh_mode_buttons()
                ui.notify("Global Search enabled.", type="positive")

            def set_country_mode():
                search_mode["value"] = "country"
                country.enable()
                country.update()
                refresh_mode_buttons()
                ui.notify("Country Focus enabled. Choose a country.", type="info")

            global_btn.on("click", lambda _: set_global_mode())
            country_btn.on("click", lambda _: set_country_mode())

            def update_country_options(e):
                selected_continent = e.value or "Any"
                countries = get_countries_by_continent(selected_continent)
                country.options = ["Any"] + countries
                country.value = "Any"
                country.update()

            continent.on_value_change(update_country_options)
            set_global_mode()

            with ui.grid(columns=4).classes("w-full gap-4 mt-5"):
                with ui.element("div").classes("innovation-card"):
                    ui.label("AI Trip Twin").classes("font-black text-slate-900")
                    travel_dna = ui.select(
                        ["Balanced", "Romantic", "Hidden Gems", "Luxury Calm", "Food & Culture", "Nature Escape", "Adventure Light"],
                        value="Balanced",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Crowd Strategy").classes("font-black text-slate-900")
                    crowd_strategy = ui.select(
                        ["Normal", "Avoid Crowds", "Only Quiet Places", "Popular but Smart Timing"],
                        value="Avoid Crowds",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Trip Pace").classes("font-black text-slate-900")
                    trip_pace = ui.select(
                        ["Slow & Relaxed", "Balanced", "Full Schedule", "Minimal Walking"],
                        value="Slow & Relaxed",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Discovery Mode").classes("font-black text-slate-900")
                    discovery_mode = ui.select(
                        ["Best Match", "Surprise Me", "Underrated Places", "Romantic Hidden Gems", "Budget Maximizer"],
                        value="Best Match",
                    ).classes("w-full mt-2").props("outlined")

            with ui.grid(columns=4).classes("w-full gap-4 mt-4"):
                with ui.element("div").classes("innovation-card"):
                    ui.label("Walking Level").classes("font-black text-slate-900")
                    walking_level = ui.select(
                        ["Any", "Low Walking", "Medium Walking", "High Walking"],
                        value="Any",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Tourist Trap Sensitivity").classes("font-black text-slate-900")
                    tourist_trap_sensitivity = ui.select(
                        ["Normal", "Avoid Tourist Traps", "Strictly Authentic"],
                        value="Avoid Tourist Traps",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Local Authenticity").classes("font-black text-slate-900")
                    local_authenticity = ui.select(
                        ["Balanced", "Prefer Local", "Only Local Feeling"],
                        value="Prefer Local",
                    ).classes("w-full mt-2").props("outlined")

                with ui.element("div").classes("innovation-card"):
                    ui.label("Comfort vs Adventure").classes("font-black text-slate-900")
                    comfort_adventure = ui.select(
                        ["Balanced", "Comfort First", "Adventure First"],
                        value="Balanced",
                    ).classes("w-full mt-2").props("outlined")

            interests = ui.textarea(
                label="Describe your dream trip",
                placeholder=(
                    "Example: romantic relaxing trip, sea views, sunsets, local food, walking areas, "
                    "cozy hotels, cafes, wine bars, cultural places, and hidden gems."
                ),
            ).classes("w-full mt-5").props("outlined autogrow")

            with ui.row().classes("gap-2 mt-4 flex-wrap relative z-50 pointer-events-auto"):
                for text in [
                    "Romantic islands with sunsets",
                    "Cheap cultural weekend",
                    "Hidden nature escapes",
                    "Food, cafes and old towns",
                    "Luxury relaxing sea views",
                ]:
                    ui.label(text).classes("prompt-chip").on(
                        "click",
                        lambda e, t=text: interests.set_value(t)
                    )

                def surprise_me():
                    interests.set_value(
                        random.choice(PROMPT_IDEAS)
                    )
                
                    discovery_mode.value = (
                        "Surprise Me"
                    )
                
                    discovery_mode.update()
                
                    ui.notify(
                        "Surprise idea generated.",
                        type="positive",
                    )
                
                
                async def find_destinations():
                    await search()
                
                
                ui.button(
                    "Surprise Me",
                    on_click=surprise_me,
                ).classes(
                    "dark-btn px-5"
                )
                
                ui.button(
                    "Find Destinations",
                    on_click=find_destinations,
                ).classes(
                    """
                    primary-btn
                    px-8
                    py-3
                    text-lg
                    font-bold
                    rounded-xl
                    """
                )
                
                active_map_layer = {
                    "value": "Trip Fit Heatmap"
                }
                
                current_map_results = {
                    "items": []
                }
                
                map_layer_buttons = {}

            with ui.element("div").classes("map-os-panel w-full mt-8 hidden") as map_panel:
                with ui.row().classes("map-header w-full items-center justify-between gap-4"):
                    with ui.column().classes("gap-1"):
                        ui.label("AI Travel Map Intelligence").classes("text-3xl font-black")
                        ui.label("Visual trip-fit, crowd, budget, and hidden-gem signals for the current results.").classes("text-blue-100")

                    with ui.row().classes("map-layer-row gap-2 flex-wrap"):
                        pass

                map_buttons_row = ui.row().classes("map-layer-row gap-2 flex-wrap mt-4")
                map_canvas = ui.element("div").classes("map-canvas w-full mt-5")
                map_summary = ui.label("Run a search to activate the intelligent map.").classes("text-blue-100 mt-3 relative z-40")

            results_container = ui.grid(columns=3).classes("w-full gap-7 mt-8")
            selected_for_compare = {}

            with ui.row().classes("compare-bar w-full items-center justify-between hidden") as compare_bar:
                compare_status = ui.label("0 selected choose 2-4 destinations").classes("font-black")
                with ui.row().classes("gap-2"):
                    clear_compare_btn = ui.button("Clear")
                    compare_btn = ui.button("Compare selected trips").classes("primary-btn px-5")

            def destination_label(dest):
                return f"{_safe_text(_get_attr(dest, 'name', 'Unknown'))}, {_safe_text(_get_attr(dest, 'country', 'Unknown'))}"

            def update_compare_bar():
                count = len(selected_for_compare)
                compare_status.set_text(f"{count} selected choose 2-4 destinations")

                if count > 0:
                    compare_bar.classes(remove="hidden")
                else:
                    compare_bar.classes(add="hidden")

                if count < 2:
                    compare_btn.disable()
                else:
                    compare_btn.enable()

            def toggle_compare(dest):
                key = f"{_get_attr(dest, 'id', '')}-{destination_label(dest)}"

                if key in selected_for_compare:
                    selected_for_compare.pop(key, None)
                    ui.notify("Removed from comparison.", type="info")
                else:
                    if len(selected_for_compare) >= 4:
                        ui.notify("You can compare up to 4 destinations.", type="warning")
                        return
                    selected_for_compare[key] = dest
                    ui.notify("Added to comparison.", type="positive")

                update_compare_bar()

            def clear_compare():
                selected_for_compare.clear()
                update_compare_bar()
                ui.notify("Comparison cleared.", type="info")

            def open_comparison():
                items = list(selected_for_compare.values())

                if len(items) < 2:
                    ui.notify("Select at least 2 destinations.", type="warning")
                    return

                comparison = build_destination_comparison(items)
                ranked_items = comparison.get("items", [])
                winner = comparison.get("winner", {}) or {}
                summary = comparison.get("summary", "")
                columns = max(1, min(4, len(ranked_items)))

                with ui.dialog() as dialog, ui.card().classes("plan-dialog w-[1180px] max-w-full"):
                    ui.label("Aevyra Comparison Mode").classes("text-4xl font-black text-slate-900")
                    ui.label(
                        "Compare value, realism, hidden-gem potential, crowd risk, Trip Twin match, and final decision score."
                    ).classes("text-slate-500 mt-1")

                    with ui.element("div").classes("winner-card mt-5"):
                        ui.label(f"Recommended winner: {winner.get('best_overall', 'N/A')}").classes("text-2xl font-black text-slate-900")
                        ui.label(summary or "No comparison summary available.").classes("text-slate-700 mt-2")

                    with ui.grid(columns=columns).classes("w-full gap-4 mt-5"):
                        for item in ranked_items:
                            with ui.element("div").classes("compare-card"):
                                ui.label(f"{item.get('name', 'N/A')}, {item.get('country', 'N/A')}").classes("text-xl font-black text-slate-900")
                                decision_score = item.get("decision_score", item.get("ai_score", 0))
                                ui.label(f"Decision Score: {decision_score} / 100").classes("score-pill mt-2")
                                ui.separator().classes("my-3")

                                rows = [
                                    ("AI Match", f"{item.get('ai_score', 0)}%"),
                                    ("Trip Twin", f"{item.get('travel_dna_match', 0)}%"),
                                    ("Hidden Gem", f"{item.get('hidden_gem_score', 0)}/100"),
                                    ("Local Feel", f"{item.get('local_authenticity_score', 0)}/100"),
                                    ("Budget", item.get("budget_realism", "Unknown")),
                                    ("Crowd", item.get("crowd_level", "Unknown")),
                                    ("Walking", item.get("walking_difficulty", "Unknown")),
                                    ("Tourist Trap", item.get("tourist_trap_risk", "Unknown")),
                                    ("Risk", item.get("risk_level", "Unknown")),
                                ]

                                for label, value in rows:
                                    with ui.row().classes("w-full justify-between gap-2"):
                                        ui.label(label).classes("text-slate-500 font-semibold")
                                        ui.label(str(value)).classes("font-black text-slate-800")

                                if item.get("avoid_if"):
                                    ui.label(f"Avoid if: {item['avoid_if']}").classes("warning-note mt-3")

                                if item.get("ai_tip"):
                                    ui.label(f"AI tip: {item['ai_tip']}").classes("ai-note mt-2")

                    ui.button("Close", on_click=dialog.close).classes("dark-btn mt-6 px-6 py-3")

                dialog.open()

            clear_compare_btn.on("click", lambda _: clear_compare())
            compare_btn.on("click", lambda _: open_comparison())
            update_compare_bar()

            def get_image(dest):
                try:
            
                    image_url = _get_attr(
                        dest,
                        "image_url",
                        None,
                    )
            
                    if image_url:
                        return image_url
            
                    image_data = get_destination_image(
                        destination_name=_get_attr(
                            dest,
                            "name",
                            "",
                        ),
                        country=_get_attr(
                            dest,
                            "country",
                            "",
                        ),
                        continent=_get_attr(
                            dest,
                            "continent",
                            "",
                        ),
                    )
            
                    image_url = image_data.get(
                        "image_url",
                        "",
                    )
            
                    if image_url:
                        return image_url
            
                except Exception as e:
                    print(
                        f"[IMAGE ERROR] {e}"
                    )
            
                return FALLBACK_IMAGE

            def get_selected_country():
                if search_mode["value"] == "global":
                    return "Any"
                return country.value if country.value and country.value != "Any" else "Any"

            def build_ai_preferences():
                selected_country = get_selected_country()

                enhanced = (
                    f"{interests.value or ''}\n\n"
                    f"AI Travel DNA: {travel_dna.value}.\n"
                    f"Crowd Strategy: {crowd_strategy.value}.\n"
                    f"Trip Pace: {trip_pace.value}.\n"
                    f"Discovery Mode: {discovery_mode.value}.\n"
                    f"Walking Level: {walking_level.value}.\n"
                    f"Tourist Trap Sensitivity: {tourist_trap_sensitivity.value}.\n"
                    f"Local Authenticity Preference: {local_authenticity.value}.\n"
                    f"Comfort vs Adventure: {comfort_adventure.value}.\n"
                    f"Find realistic, safe, memorable, personalized destinations. "
                    f"Prefer authentic local experiences, good transport practicality, hidden-gem potential, "
                    f"beautiful walking areas, food/cafes, strong travel value, and places that are not generic."
                )

                if selected_country != "Any":
                    enhanced += (
                        f"\nSelected country: {selected_country}. "
                        f"Search only inside {selected_country}. "
                        f"Return real cities, islands, towns, villages, coastal places, nature places, "
                        f"cultural areas, underrated places, and realistic travel destinations from this country."
                    )
                else:
                    enhanced += (
                        "\nGlobal search mode is enabled. Search across all countries and continents "
                        "based on budget, month, travel style, and preferences."
                    )

                return enhanced

            def _map_position(dest, index, total):
                lat = _safe_float(_get_attr(dest, "latitude", None), None)
                lon = _safe_float(_get_attr(dest, "longitude", None), None)

                if lat is not None and lon is not None:
                    x = 8 + (abs(lon) % 84)
                    y = 12 + (abs(lat) % 72)
                    return x, y

                x = 14 + ((index * 23) % 72)
                y = 18 + ((index * 31) % 62)
                return x, y

            def _map_layer_style(dest, layer_name):
                ai_score = _safe_float(_get_attr(dest, "ai_score", 0), 0)
                hidden = _safe_float(_get_attr(dest, "hidden_gem_score", 0), 0)
                crowd = _safe_text(_get_attr(dest, "crowd_level", "Medium"), "Medium")
                budget_realism = _safe_text(_get_attr(dest, "budget_realism", "Unknown"), "Unknown")
                tourist_trap = _safe_text(_get_attr(dest, "tourist_trap_risk", "Medium"), "Medium")
                name = _safe_text(_get_attr(dest, "name", "Place"), "Place")

                if layer_name == "Crowd Risk":
                    value = {"Low": 30, "Medium": 65, "High": 95}.get(crowd, 55)
                    color = "#22c55e" if crowd == "Low" else "#f59e0b" if crowd == "Medium" else "#ef4444"
                    label = f"{name} - {crowd}"
                    tooltip = f"Crowd risk: {crowd}. Tourist-trap risk: {tourist_trap}."
                elif layer_name == "Budget Reality":
                    value = {
                        "Very realistic": 95,
                        "Realistic": 82,
                        "Flexible": 72,
                        "Tight": 55,
                        "Risky": 30,
                    }.get(budget_realism, 55)
                    color = "#22c55e" if value >= 80 else "#f59e0b" if value >= 55 else "#ef4444"
                    label = f"{name} - {budget_realism}"
                    tooltip = f"Budget realism: {budget_realism}."
                elif layer_name == "Hidden Gems":
                    value = hidden
                    color = "#22c55e" if hidden >= 75 else "#38bdf8" if hidden >= 60 else "#64748b"
                    label = f"{name} - {hidden:.0f}/100"
                    tooltip = f"Hidden-gem score: {hidden:.0f}/100."
                else:
                    value = ai_score
                    color = "#22c55e" if ai_score >= 80 else "#3b82f6" if ai_score >= 65 else "#f59e0b"
                    label = f"{name} - {ai_score:.0f}%"
                    tooltip = f"AI trip-fit match: {ai_score:.0f}%."

                size = max(0.92, min(1.35, 0.85 + (value / 180)))
                return label, tooltip, color, size

            def refresh_map_layer_buttons():
                for layer_name, button in map_layer_buttons.items():
                    if layer_name == active_map_layer["value"]:
                        button.classes(add="map-layer-pill-active")
                    else:
                        button.classes(remove="map-layer-pill-active")
                    button.update()

            def render_ai_map(results):
                map_canvas.clear()
                current_map_results["items"] = results or []

                if not results:
                    map_panel.classes(add="hidden")
                    map_panel.update()
                    return

                map_panel.classes(remove="hidden")
                map_panel.update()

                layer = active_map_layer["value"]

                best_score = max([_safe_float(_get_attr(d, "ai_score", 0), 0) for d in results] or [0])
                hidden_count = sum(1 for d in results if _safe_float(_get_attr(d, "hidden_gem_score", 0), 0) >= 70)
                quiet_count = sum(1 for d in results if str(_get_attr(d, "crowd_level", "")).lower() == "low")
                risky_budget_count = sum(1 for d in results if str(_get_attr(d, "budget_realism", "")).lower() == "risky")
                high_crowd_count = sum(1 for d in results if str(_get_attr(d, "crowd_level", "")).lower() == "high")

                if layer == "Crowd Risk":
                    map_summary.set_text(
                        f"{len(results)} destinations mapped - {high_crowd_count} higher-crowd options - "
                        f"{quiet_count} quieter options"
                    )
                elif layer == "Budget Reality":
                    map_summary.set_text(
                        f"{len(results)} destinations mapped - {risky_budget_count} budget-risk options - "
                        f"best AI match {best_score:.0f}%"
                    )
                elif layer == "Hidden Gems":
                    map_summary.set_text(
                        f"{len(results)} destinations mapped - {hidden_count} strong hidden-gem options - "
                        f"{quiet_count} quieter options"
                    )
                else:
                    map_summary.set_text(
                        f"{len(results)} destinations mapped - best AI match {best_score:.0f}% - "
                        f"{hidden_count} strong hidden-gem options - {quiet_count} quieter options"
                    )

                with map_canvas:
                    for index, dest in enumerate(results[:25]):
                        x, y = _map_position(dest, index, len(results))
                        label, tooltip, color, size = _map_layer_style(dest, layer)

                        dot = ui.label(label).classes("map-dot")
                        dot.style(
                            f"left:{x}%; top:{y}%; "
                            f"background:{color}; "
                            f"transform:translate(-50%, -50%) scale({size});"
                        )
                        dot.tooltip(tooltip)

                refresh_map_layer_buttons()

            def set_map_layer(layer_name):
                active_map_layer["value"] = layer_name
                refresh_map_layer_buttons()
                render_ai_map(current_map_results["items"])
                ui.notify(f"{layer_name} selected.", type="info")

            with map_buttons_row:
                for layer_name in ["Trip Fit Heatmap", "Crowd Risk", "Budget Reality", "Hidden Gems"]:
                    btn = ui.button(layer_name)
                    btn.classes("map-layer-pill")
                    btn.on("click", lambda e, name=layer_name: set_map_layer(name))
                    map_layer_buttons[layer_name] = btn

            refresh_map_layer_buttons()

            def clean_error_message():
                return (
                    "Could not generate the itinerary right now. "
                    "Check Geoapify, database fields, Ollama, and service logs."
                )
            
            def build_day_markdown(day):

                lines = []
            
                lines.append("## Morning")
            
                for place in day.get("morning", []):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                lines.append("")
                lines.append("## Afternoon")
            
                for place in day.get("afternoon", []):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                lines.append("")
                lines.append("## Evening")
            
                for place in day.get("evening", []):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                return "\n".join(lines)
                
            def build_day_markdown(day):

                lines = []
            
                lines.append("## Morning")
            
                for place in day.get(
                    "morning",
                    [],
                ):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                lines.append("")
                lines.append("## Afternoon")
            
                for place in day.get(
                    "afternoon",
                    [],
                ):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                lines.append("")
                lines.append("## Evening")
            
                for place in day.get(
                    "evening",
                    [],
                ):
                    lines.append(
                        f"- {place.get('name')}"
                    )
            
                return "\n".join(lines)
                   
            def open_plan(dest):
                selected_image = get_image(dest)
                selected_country = get_selected_country()
                destination_continent = _get_attr(dest, "continent", None) or continent.value
                ai_score = _get_attr(dest, "ai_score", 0)
                score_summary = _get_attr(dest, "score_summary", "")
                plan_preferences = build_ai_preferences()

                with ui.dialog() as dialog, ui.card().classes("plan-dialog w-[1120px] max-w-full"):
                    ui.label(f"AI Travel Plan: {dest.name}, {dest.country}").classes("text-4xl font-black")

                    with ui.row().classes("gap-2 mt-3 flex-wrap"):
                        ui.label(f"AI Match: {ai_score}%").classes("score-pill")
                        ui.label(str(month.value)).classes("small-pill")
                        ui.label(str(travelers.value)).classes("small-pill")
                        ui.label(str(destination_continent)).classes("small-pill")
                        ui.label(str(selected_country)).classes("small-pill")
                        ui.label(str(travel_dna.value)).classes("small-pill")
                        ui.label(str(crowd_strategy.value)).classes("small-pill")
                        ui.label(str(discovery_mode.value)).classes("small-pill")
                        ui.label(f"{_safe_int(trip_days.value, 5)} days").classes("small-pill")
                        ui.label(f"{_safe_float(budget.value, 0):.0f} EUR/day").classes("small-pill")

                    if score_summary:
                        ui.label(score_summary).classes("ai-note mt-4")

                    ui.image(selected_image).classes("w-full h-80 object-cover rounded-3xl my-5")

                    with ui.row().classes(
                        "items-center gap-3"
                    ):
                        spinner = ui.spinner(
                            size="lg"
                        )
                    
                        status_label = ui.label(
                            "Checking saved travel plan..."
                        ).classes(
                            "text-slate-600 font-semibold"
                        )
                    
                    
                    with ui.expansion(
                        "Trip Budget Dashboard",
                        value=True,
                    ).classes(
                        "w-full mt-4"
                    ):
                    
                        budget_card = ui.column().classes(
                            "w-full bg-slate-50 rounded-2xl p-4"
                        )
                    
                        with budget_card:
                    
                            total_budget_label = ui.label(
                                "Total Budget: calculating..."
                            ).classes(
                                "text-lg font-bold"
                            )
                    
                            total_cost_label = ui.label(
                                "Estimated Trip Cost: calculating..."
                            ).classes(
                                "text-lg font-bold"
                            )
                    
                            remaining_budget_label = ui.label(
                                "Remaining Budget: calculating..."
                            ).classes(
                                "text-lg font-bold"
                            )
                    
                            budget_usage_label = ui.label(
                                "Budget Usage: calculating..."
                            ).classes(
                                "text-lg font-bold"
                            )
                            
                            budget_health_label = ui.label(
                                "Budget Health: calculating..."
                            ).classes(
                                "text-lg font-bold"
                            )
                            
                            budget_progress = ui.linear_progress(
                                value=0
                            ).classes(
                                "w-full mt-2"
                            )
                    
                    with ui.expansion(
                        "Booking & Ticket Summary",
                        value=False,
                    ).classes(
                        "w-full mt-2"
                    ):
                    
                        with ui.grid(columns=4).classes(
                            "w-full gap-4"
                        ):
                    
                            ticket_card = ui.card().classes(
                                "p-4 text-center"
                            )
                    
                            reservation_card = ui.card().classes(
                                "p-4 text-center"
                            )
                    
                            booking_card = ui.card().classes(
                                "p-4 text-center"
                            )
                    
                            transport_card = ui.card().classes(
                                "p-4 text-center"
                            )
                    
                            with ticket_card:
                                ticket_count_label = ui.label(
                                    "Ticketed Attractions: 0"
                                )
                    
                            with reservation_card:
                                reservation_count_label = ui.label(
                                    "Reservations: 0"
                                )
                    
                            with booking_card:
                                booking_count_label = ui.label(
                                    "Booking Links: 0"
                                )
                    
                            with transport_card:
                                transport_info_label = ui.label(
                                    "Transport: N/A"
                                )
                    
                    with ui.row().classes(
                        "w-full gap-4 mt-4 items-start"
                    ):
                    
                        with ui.card().classes(
                            "w-64 p-4"
                        ):
                    
                            itinerary_menu = ui.column().classes(
                                "w-full gap-2"
                            )
                    
                        with ui.card().classes(
                            "flex-grow p-6 min-h-[600px]"
                        ):
                    
                            plan_area = ui.column().classes(
                                "w-full"
                            ).classes(
                                "plan-markdown"
                            ).style(
                                """
                                height:70vh;
                                overflow-y:auto;
                                width:100%;
                                """
                            )
                            
                        def show_day(day_data):

                            plan_area.clear()
                        
                            with plan_area:
                        
                                ui.label(
                                    f"Day {day_data['day']}"
                                ).classes(
                                    "text-2xl font-bold"
                                )
                        
                                ui.separator()
                        
                                ui.markdown(
                                    build_day_markdown(day_data)
                                )
                                
                    async def load_plan():
                        try:
                            saved_plan = await asyncio.to_thread(
                                get_saved_travel_plan,
                                destination_id=dest.id,
                                month=month.value,
                                travelers=travelers.value,
                                continent=destination_continent,
                                days=_safe_int(trip_days.value, 5),
                                budget=_safe_float(budget.value, 0),
                                user_preferences=plan_preferences,
                            )
                    
                            if saved_plan:

                                plan_area.clear()
                            
                                with plan_area:
                                    ui.markdown(saved_plan)
                            
                                total_cost_label.set_text(
                                    "Estimated Trip Cost: Loaded from saved plan"
                                )
                            
                                remaining_budget_label.set_text(
                                    "Remaining Budget: Loaded from saved plan"
                                )
                            
                                budget_usage_label.set_text(
                                    "Budget Usage: Saved plan"
                                )
                            
                                budget_health_label.set_text(
                                    "Budget Health: Saved plan"
                                )
                            
                                transport_info_label.set_text(
                                    "Transport information unavailable for saved plans."
                                )
                            
                                status_label.set_text(
                                    "Loaded saved travel plan."
                                )
                            
                                return
                    
                            status_label.set_text(
                                "Building real itinerary from nearby places..."
                            )
                    
                            itinerary = await create_itinerary(
                                destination=dest,
                                days=_safe_int(
                                    trip_days.value,
                                    5,
                                ),
                                user_text=plan_preferences,
                                travelers=travelers.value,
                                budget=_safe_float(
                                    budget.value,
                                    0,
                                ),
                            )
                            
                            # ------------------------------------
                            # Ticket / Reservation Summary
                            # ------------------------------------
                            
                            tickets_required = 0
                            reservations_required = 0
                            booking_links_available = 0
                            walk_count = 0
                            car_count = 0
                            transit_count = 0
                            
                            for place in itinerary.get("places", []):

                                if place.get(
                                    "ticket_required",
                                    False,
                                ):
                                    tickets_required += 1
                            
                                if place.get(
                                    "reservation_required",
                                    False,
                                ):
                                    reservations_required += 1
                            
                                if place.get(
                                    "booking_url",
                                    "",
                                ):
                                    booking_links_available += 1
                            
                                transport_mode = place.get(
                                    "transport_mode",
                                    "walk",
                                )
                            
                                if transport_mode == "walk":
                                    walk_count += 1
                            
                                elif transport_mode in [
                                    "car",
                                    "taxi",
                                ]:
                                    car_count += 1
                            
                                else:
                                    transit_count += 1
                            
                            
                            ticket_count_label.set_text(
                                f"Ticketed Attractions: {tickets_required}"
                            )
                            
                            reservation_count_label.set_text(
                                f"Reservations: {reservations_required}"
                            )
                            
                            booking_count_label.set_text(
                                f"Booking Links: {booking_links_available}"
                            )
                            
                            transport_info_label.set_text(
                                (
                                    f"{walk_count} | "
                                    f"{car_count} | "
                                    f"{transit_count}"
                                )
                            )
                            
                            # ------------------------------------
                            # Budget Calculations
                            # ------------------------------------
                            
                            estimated_trip_cost = itinerary.get(
                                "estimated_trip_cost",
                                0,
                            )
                            
                            remaining_budget = itinerary.get(
                                "remaining_budget_estimate",
                                0,
                            )
                            
                            total_budget = (
                                _safe_float(
                                    budget.value,
                                    0,
                                )
                                *
                                _safe_int(
                                    trip_days.value,
                                    5,
                                )
                            )
                            
                            budget_usage = 0
                            
                            if total_budget > 0:
                                budget_usage = round(
                                    (
                                        estimated_trip_cost
                                        / total_budget
                                    ) * 100,
                                    1,
                                )
                            
                            total_budget_label.set_text(
                                f"Total Budget: {total_budget:.2f}"
                            )
                            total_cost_label.set_text(
                                f"Estimated Trip Cost: {estimated_trip_cost:.2f}"
                            )
                    
                            remaining_budget_label.set_text(
                                f"Remaining Budget: {remaining_budget:.2f}"
                            )
                    
                            try:
                                budget_usage_label.set_text(
                                    f"Budget Usage: {budget_usage:.1f}%"
                                )
                                
                                if budget_usage <= 50:
                                
                                    budget_health_label.set_text(
                                        "Budget Health: Excellent"
                                    )
                                
                                elif budget_usage <= 85:
                                
                                    budget_health_label.set_text(
                                        "Budget Health: Moderate"
                                    )
                                
                                else:
                                
                                    budget_health_label.set_text(
                                        "Budget Health: Tight"
                                    )
                                
                                progress_value = min(
                                    budget_usage / 100,
                                    1.0,
                                )
                                
                                budget_progress.value = progress_value
                                
                                if budget_usage <= 50:
                                
                                    budget_progress.props(
                                        "color=positive"
                                    )
                                
                                elif budget_usage <= 85:
                                
                                    budget_progress.props(
                                        "color=warning"
                                    )
                                
                                else:
                                
                                    budget_progress.props(
                                        "color=negative"
                                    )
                                
                                budget_progress.update()
                                
                            except Exception:
                                pass
                    
                            markdown_plan = itinerary_to_markdown(
                                itinerary
                            )
                            
                            itinerary_menu.clear()

                            with itinerary_menu:

                                ui.label(
                                    "Trip Overview"
                                ).classes(
                                    "text-2xl font-bold mb-2"
                                )
                            
                                for day in itinerary.get(
                                    "days",
                                    [],
                                ):
                            
                                    day_number = day.get(
                                        "day",
                                        0,
                                    )
                            
                                    ui.button(
                                        f"DAY {day_number}",
                                        on_click=lambda d=day:
                                            show_day(d)
                                    ).classes(
                                        "w-full"
                                    )
                            
                                if itinerary.get("days"):
                            
                                    show_day(
                                        itinerary["days"][0]
                                    )
                    
                            plan_area.clear()

                            with plan_area:
                                ui.markdown(markdown_plan)
                    
                            status_label.set_text(
                                "Enhancing itinerary with AI..."
                            )
                    
                            enhanced_plan = await asyncio.to_thread(
                                enhance_itinerary_with_ai,
                                destination=dest,
                                itinerary_markdown=markdown_plan,
                                user_text=plan_preferences,
                                travelers=travelers.value,
                                month=month.value,
                                budget=_safe_float(
                                    budget.value,
                                    0,
                                ),
                                days=_safe_int(
                                    trip_days.value,
                                    5,
                                ),
                                itinerary=itinerary,
                            )
                    
                            final_plan = (
                                enhanced_plan
                                or markdown_plan
                            )
                    
                            plan_area.clear()

                            with plan_area:
                                ui.markdown(final_plan)
                    
                            status_label.set_text(
                                "AI-enhanced travel plan ready and saved."
                            )
                    
                            await asyncio.to_thread(
                                save_travel_plan,
                                destination_id=dest.id,
                                month=month.value,
                                travelers=travelers.value,
                                continent=destination_continent,
                                days=_safe_int(
                                    trip_days.value,
                                    5,
                                ),
                                budget=_safe_float(
                                    budget.value,
                                    0,
                                ),
                                user_preferences=plan_preferences,
                                plan_markdown=final_plan,
                            )
                    
                        except Exception as e:

                            print("\n==============================")
                            print("[ITINERARY ERROR]")
                            print("==============================")
                            print(str(e))
                            traceback.print_exc()
                            print("==============================\n")
                        
                            status_label.set_text(
                                "Could not generate itinerary."
                            )
                        
                            plan_area.clear()

                            with plan_area:
                                ui.markdown(
                                    clean_error_message()
                                )
                        
                            total_budget_label.set_text(
                                "Total Budget: unavailable"
                            )
                        
                            total_cost_label.set_text(
                                "Estimated Trip Cost: unavailable"
                            )
                        
                            remaining_budget_label.set_text(
                                "Remaining Budget: unavailable"
                            )
                        
                            budget_usage_label.set_text(
                                "Budget Usage: unavailable"
                            )
                        
                            budget_health_label.set_text(
                                "Budget Health: unavailable"
                            )
                        
                            booking_count_label.set_text(
                                "Ticket and reservation information unavailable"
                            )
                        
                            transport_info_label.set_text(
                                "Transport information unavailable"
                            )
                        
                            budget_progress.value = 0
                        
                            budget_progress.props(
                                "color=grey"
                            )
                        
                            budget_progress.update()
                        
                            ui.notify(
                                "Trip planning failed. Check terminal logs.",
                                type="negative",
                            )
                    
                        finally:
                            spinner.visible = False
                            spinner.update()

                    ui.timer(0.3, lambda: asyncio.create_task(load_plan()), once=True)

                    with ui.row().classes("justify-end w-full mt-5"):
                        ui.button("Close", on_click=dialog.close).classes("dark-btn px-6 py-3")

                dialog.open()

            async def search():
                results_container.clear()

                with results_container:
                    for _ in range(6):
                        ui.element("div").classes("skeleton-card")

                selected_country = get_selected_country()
                search_preferences = build_ai_preferences()

                try:
                    results = await asyncio.to_thread(
                        get_recommendations,
                
                        # -----------------------------
                        # Core trip information
                        # -----------------------------
                        budget_per_day=_safe_float(
                            budget.value,
                            120,
                        ),
                
                        travel_month=month.value,
                
                        user_preferences=search_preferences,
                
                        travelers=travelers.value,
                
                        continent=continent.value,
                
                        country=selected_country,
                
                        days=_safe_int(
                            trip_days.value,
                            5,
                        ),
                
                        limit=25,
                
                        # -----------------------------
                        # AI personalization
                        # -----------------------------
                        travel_dna=travel_dna.value,
                
                        crowd_strategy=crowd_strategy.value,
                
                        trip_pace=trip_pace.value,
                
                        discovery_mode=discovery_mode.value,
                
                        walking_level=walking_level.value,
                
                        tourist_trap_sensitivity=
                            tourist_trap_sensitivity.value,
                
                        local_authenticity=
                            local_authenticity.value,
                
                        comfort_adventure=
                            comfort_adventure.value,
                
                        # -----------------------------
                        # Optional modules
                        # -----------------------------
                        include_weather=True,
                
                        include_events=True,
                
                        include_real_prices=True,
                
                        include_transport=True,
                
                        include_hotels=True,
                
                        include_images=True,
                
                        include_hidden_gems=True,
                
                        include_airport_accessibility=True,
                
                        include_crowd_estimation=True,
                
                        include_local_authenticity_score=True,
                
                        include_budget_realism=True,
                
                        include_ai_summary=True,
                    )
                
                    # ------------------------------------
                    # Prevent NoneType crashes
                    # ------------------------------------
                    results = results or []
                
                    print("\n==============================")
                    print("[UI RESULTS RECEIVED]")
                    print("==============================")
                    print(f"Results count: {len(results)}")
                
                except Exception as e:
                    print("\n==============================")
                    print("[SEARCH ERROR]")
                    print("==============================")
                    print(str(e))
                    traceback.print_exc()
                    print("==============================\n")
                
                    results_container.clear()
                    render_ai_map([])
                    ui.notify(
                        "Search failed. Check terminal logs.",
                        type="negative",
                    )
                    return

                results_container.clear()
                selected_for_compare.clear()
                update_compare_bar()

                if not results:
                    render_ai_map([])
                    ui.notify(
                        "No destinations found. Try Global Search, higher budget, or broader preferences.",
                        type="warning",
                    )
                    return

                render_ai_map(results)

                for d in results:
                    image_url = get_image(d)
                    destination_continent = _get_attr(d, "continent", None) or continent.value
                    ai_score = _get_attr(d, "ai_score", 0)
                    score_summary = _get_attr(d, "score_summary", "")
                    cost = _get_attr(d, "avg_cost_per_day", 0)

                    travel_dna_match = _get_attr(d, "travel_dna_match", None)
                    hidden_gem_score = _get_attr(d, "hidden_gem_score", None)
                    crowd_risk = _get_attr(d, "crowd_risk", None) or _get_attr(d, "crowd_level", None)
                    budget_realism = _get_attr(d, "budget_realism", None)
                    walking_difficulty = _get_attr(d, "walking_difficulty", None)
                    local_authenticity_score = _get_attr(d, "local_authenticity_score", None)
                    tourist_trap_risk = _get_attr(d, "tourist_trap_risk", None)

                    trip_mood = _get_attr(d, "trip_mood", None)
                    daily_energy_level = _get_attr(d, "daily_energy_level", None)
                    budget_reality_check = _get_attr(d, "budget_reality_check", None)
                    regret_predictor = _get_attr(d, "regret_predictor", []) or []
                    smart_timing_tip = _get_attr(d, "smart_timing_tip", None)
                    trip_twin_label = _get_attr(d, "trip_twin_label", None)

                    best_for = _get_attr(d, "best_for", None)
                    avoid_if = _get_attr(d, "avoid_if", None)
                    ai_tip = _get_attr(d, "ai_tip", None)
                    risk_flags = _get_attr(d, "risk_flags", []) or []

                    with results_container:

                        with ui.card().classes("destination-card"):
                    
                            display_name = (
                                _get_attr(d, "display_name", None)
                                or _get_attr(d, "name", "Unknown Destination")
                            )
                    
                            country_name = _get_attr(
                                d,
                                "country",
                                "",
                            )
                    
                            title = display_name
                    
                            if (
                                country_name
                                and country_name.lower()
                                not in display_name.lower()
                            ):
                                title += f", {country_name}"
                    
                            daily_cost = round(
                                _safe_float(
                                    cost,
                                    0,
                                ),
                                0,
                            )
                    
                            cost_text = (
                                f"{daily_cost:.0f} EUR/day"
                                if daily_cost > 0
                                else "Price unavailable"
                            )
                    
                            weather_summary = _get_attr(
                                d,
                                "weather_summary",
                                None,
                            )
                    
                            events = _get_attr(
                                d,
                                "events",
                                [],
                            ) or []
                    
                            airport_transfer_time = _get_attr(
                                d,
                                "airport_transfer_time",
                                None,
                            )
                    
                            current_temperature = _get_attr(
                                d,
                                "current_temperature",
                                None,
                            )
                    
                            real_hotel_price = _get_attr(
                                d,
                                "real_hotel_price",
                                None,
                            )
                    
                            real_food_price = _get_attr(
                                d,
                                "real_food_price",
                                None,
                            )
                    
                            real_transport_price = _get_attr(
                                d,
                                "real_transport_price",
                                None,
                            )
                    
                            ui.image(
                                image_url
                            ).classes(
                                "destination-img"
                            )
                    
                            with ui.column().classes(
                                "p-5 gap-3"
                            ):
                    
                                ui.label(
                                    title
                                ).classes(
                                    "text-2xl font-black text-slate-900"
                                )
                    
                                with ui.row().classes(
                                    "gap-2 flex-wrap"
                                ):
                    
                                    ui.label(
                                        f"AI Match: {ai_score}%"
                                    ).classes(
                                        "score-pill"
                                    )
                    
                                    if trip_twin_label:
                                        ui.label(
                                            str(trip_twin_label)
                                        ).classes(
                                            "dark-pill"
                                        )
                    
                                    ui.label(
                                        str(destination_continent)
                                    ).classes(
                                        "small-pill"
                                    )
                    
                                    ui.label(
                                        cost_text
                                    ).classes(
                                        "small-pill"
                                    )
                    
                                    if weather_summary:
                                        ui.label(
                                            weather_summary
                                        ).classes(
                                            "small-pill"
                                        )
                    
                                    if current_temperature is not None:
                                        ui.label(
                                            f"{current_temperature}C"
                                        ).classes(
                                            "small-pill"
                                        )
                    
                                    if airport_transfer_time:
                                        ui.label(
                                            f"{airport_transfer_time} min airport transfer"
                                        ).classes(
                                            "small-pill"
                                        )
                    
                                    if events:
                                        ui.label(
                                            f"{len(events)} live events"
                                        ).classes(
                                            "small-pill"
                                        )
                    
                                if score_summary:
                                    ui.label(
                                        score_summary
                                    ).classes(
                                        "ai-note"
                                    )
                    
                                with ui.element(
                                    "div"
                                ).classes(
                                    "insight-box"
                                ):
                    
                                    ui.label(
                                        "Destination Reality Simulator"
                                    ).classes(
                                        "font-black text-slate-800 mb-2"
                                    )
                    
                                    with ui.row().classes(
                                        "gap-2 flex-wrap"
                                    ):
                    
                                        if travel_dna_match is not None:
                                            ui.label(
                                                f"Trip Twin: {travel_dna_match}%"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if hidden_gem_score is not None:
                                            ui.label(
                                                f"Hidden Gem: {hidden_gem_score}/100"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if crowd_risk:
                                            ui.label(
                                                f"Crowd: {crowd_risk}"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if budget_realism:
                                            ui.label(
                                                f"Budget: {budget_realism}"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if walking_difficulty:
                                            ui.label(
                                                f"Walking: {walking_difficulty}"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if local_authenticity_score is not None:
                                            ui.label(
                                                f"Local: {local_authenticity_score}/100"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if tourist_trap_risk:
                                            ui.label(
                                                f"Tourist Trap: {tourist_trap_risk}"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                        if daily_energy_level:
                                            ui.label(
                                                f"Energy: {daily_energy_level}"
                                            ).classes(
                                                "small-pill"
                                            )
                    
                                    if real_hotel_price:
                                        ui.label(
                                            f"Average hotel: {real_hotel_price:.0f} EUR/night"
                                        ).classes(
                                            "text-sm text-slate-700 mt-2"
                                        )
                    
                                    if real_food_price:
                                        ui.label(
                                            f"Food estimate: {real_food_price:.0f} EUR/day"
                                        ).classes(
                                            "text-sm text-slate-700"
                                        )
                    
                                    if real_transport_price:
                                        ui.label(
                                            f"Transport estimate: {real_transport_price:.0f} EUR/day"
                                        ).classes(
                                            "text-sm text-slate-700"
                                        )
                    
                                    if trip_mood:
                                        ui.label(
                                            f"Trip mood: {trip_mood}"
                                        ).classes(
                                            "text-sm text-slate-700 mt-2"
                                        )
                    
                                    if best_for:
                                        ui.label(
                                            f"Best for: {best_for}"
                                        ).classes(
                                            "text-sm text-slate-700 mt-1"
                                        )
                    
                                    if avoid_if:
                                        ui.label(
                                            f"Avoid if: {avoid_if}"
                                        ).classes(
                                            "text-sm text-orange-700 mt-1"
                                        )
                    
                                    if budget_reality_check:
                                        ui.label(
                                            f"Budget reality: {budget_reality_check}"
                                        ).classes(
                                            "ai-note mt-2"
                                        )
                    
                                    if smart_timing_tip:
                                        ui.label(
                                            f"Smart timing: {smart_timing_tip}"
                                        ).classes(
                                            "ai-note mt-2"
                                        )
                    
                                    if ai_tip:
                                        ui.label(
                                            f"AI tip: {ai_tip}"
                                        ).classes(
                                            "ai-note mt-2"
                                        )
                    
                                    if regret_predictor:
                                        for regret in regret_predictor[:2]:
                                            ui.label(
                                                f"Regret check: {regret}"
                                            ).classes(
                                                "warning-note mt-2"
                                            )
                    
                                    if risk_flags:
                                        with ui.row().classes(
                                            "gap-2 flex-wrap mt-2"
                                        ):
                                            for risk in risk_flags[:3]:
                                                ui.label(
                                                    risk
                                                ).classes(
                                                    "risk-pill"
                                                )
                    
                                ui.label(
                                    _safe_text(
                                        _get_attr(
                                            d,
                                            "description",
                                            "",
                                        ),
                                        "No description available.",
                                    )
                                ).classes(
                                    "text-base text-slate-600 leading-relaxed"
                                )
                    
                                with ui.row().classes(
                                    "gap-2 flex-wrap mt-2"
                                ):
                                    ui.label(
                                        str(travel_dna.value)
                                    ).classes(
                                        "small-pill"
                                    )
                    
                                    ui.label(
                                        str(crowd_strategy.value)
                                    ).classes(
                                        "small-pill"
                                    )
                    
                                    ui.label(
                                        str(discovery_mode.value)
                                    ).classes(
                                        "small-pill"
                                    )
                    
                                with ui.row().classes(
                                    "gap-2 w-full mt-3"
                                ):
                    
                                    ui.button(
                                        "Add / Remove Compare",
                                        on_click=lambda dest=d:
                                            toggle_compare(dest),
                                    ).classes(
                                        "dark-btn px-4 py-3"
                                    )
                    
                                    ui.button(
                                        "View AI Travel Plan",
                                        on_click=lambda dest=d:
                                            open_plan(dest),
                                    ).classes(
                                        "primary-btn px-5 py-3 grow"
                                    )