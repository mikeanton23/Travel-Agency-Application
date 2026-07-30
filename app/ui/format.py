# -*- coding: utf-8 -*-

"""
Pure presentation helpers — no NiceGUI imports, fully unit-testable.

Every function that turns service data into display strings/colors
lives here so the UI layer stays thin and the honesty rules ("no fake
values" → explicit unavailable states) are enforced in one place.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

UNAVAILABLE = "—"


def fmt_money(amount: Optional[float], currency: Optional[str],
              per: str = "") -> str:
    """'121.40 EUR/day' or the unavailable dash — never a made-up
    number."""
    if amount is None:
        return UNAVAILABLE
    suffix = f"/{per}" if per else ""
    return f"{amount:,.2f} {currency or ''}{suffix}".strip()


def fmt_duration(minutes: Optional[int]) -> str:
    if not minutes:
        return UNAVAILABLE
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def fmt_stops(stops: Optional[int]) -> str:
    if stops is None:
        return UNAVAILABLE
    if stops == 0:
        return "non-stop"
    return f"{stops} stop" + ("s" if stops > 1 else "")


def score_color(score: Optional[float]) -> str:
    """Quasar color name for a 0–100 score; grey when unavailable."""
    if score is None:
        return "grey-5"
    if score >= 75:
        return "green-6"
    if score >= 50:
        return "amber-7"
    return "red-6"


def score_label(score: Optional[float]) -> str:
    if score is None:
        return "No data"
    return f"{score:.0f}"


def dimension_display_name(name: str) -> str:
    """'hidden_gem_match' -> 'Hidden Gem'."""
    return name.removesuffix("_match").replace("_", " ").title()


def flag_emoji(iso2: Optional[str]) -> str:
    """Country ISO2 -> flag emoji; empty string when unknown."""
    if not iso2 or len(iso2) != 2 or not iso2.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


def flight_badge(offers: List[Dict[str, Any]]) -> Optional[str]:
    """Badge text from real Amadeus offers; None means 'don't show a
    flight badge' (never estimate)."""
    if not offers:
        return None
    cheapest = min(offers, key=lambda o: o.get("price_total", float("inf")))
    price = cheapest.get("price_total")
    if price is None:
        return None
    return f"✈ from {fmt_money(price, cheapest.get('currency'))}"


def cost_badge(costs: Optional[Dict[str, Any]]) -> Optional[str]:
    """Badge from real Numbeo data; None hides the badge."""
    if not costs:
        return None
    items = costs.get("items", {})
    meal = (items.get("meal_inexpensive") or {}).get("average")
    if meal is None:
        return None
    return f"🍽 meal {fmt_money(meal, costs.get('currency'))}"


def weather_badge(climate: Optional[Dict[str, Any]]) -> Optional[str]:
    if not climate:
        return None
    temp = climate.get("temp_max_avg_c")
    if temp is None:
        return None
    rain = climate.get("rain_days")
    rain_part = f", {rain:.0f} rain days" if rain is not None else ""
    return f"☀ {temp:.0f}°C{rain_part}"


def ai_score_badge(overall: Optional[float],
                   coverage: Optional[float]) -> str:
    """Always labeled AI, always shows data coverage — spec rule."""
    if overall is None:
        return "AI score: insufficient data"
    pct = f" · {coverage * 100:.0f}% data" if coverage is not None else ""
    return f"AI score {overall:.0f}/100{pct}"


def unavailable_reason(feature: str, reason: str = "") -> str:
    base = f"{feature} unavailable"
    return f"{base} — {reason}" if reason else base


def provider_status_icon(entry: Dict[str, Any]) -> str:
    """Key-manager list entry -> status icon name (Quasar/Material)."""
    if not entry.get("configured"):
        return "radio_button_unchecked"
    if entry.get("is_valid") is True:
        return "check_circle"
    if entry.get("is_valid") is False:
        return "error"
    return "help"


def provider_status_color(entry: Dict[str, Any]) -> str:
    if not entry.get("configured"):
        return "grey-5"
    if entry.get("is_valid") is True:
        return "green-6"
    if entry.get("is_valid") is False:
        return "red-6"
    return "amber-7"
