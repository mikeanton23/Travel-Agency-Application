# -*- coding: utf-8 -*-

from app.ui.format import (
    UNAVAILABLE, ai_score_badge, cost_badge, dimension_display_name,
    flag_emoji, flight_badge, fmt_duration, fmt_money, fmt_stops,
    provider_status_color, provider_status_icon, score_color,
    unavailable_reason, weather_badge,
)


def test_money_and_duration_formatting():
    assert fmt_money(121.4, "EUR", "day") == "121.40 EUR/day"
    assert fmt_money(None, "EUR") == UNAVAILABLE
    assert fmt_duration(210) == "3h 30m"
    assert fmt_duration(45) == "45m"
    assert fmt_duration(None) == UNAVAILABLE
    assert fmt_stops(0) == "non-stop"
    assert fmt_stops(2) == "2 stops"


def test_badges_hide_instead_of_estimating():
    # The "no fake values" rule at the display layer:
    assert flight_badge([]) is None
    assert cost_badge(None) is None
    assert cost_badge({"items": {}, "currency": "EUR"}) is None
    assert weather_badge({"temp_max_avg_c": None}) is None


def test_badges_render_real_data():
    offers = [
        {"price_total": 220.5, "currency": "EUR"},
        {"price_total": 150.0, "currency": "EUR"},
    ]
    assert flight_badge(offers) == "✈ from 150.00 EUR"
    costs = {"currency": "EUR",
             "items": {"meal_inexpensive": {"average": 15.0}}}
    assert cost_badge(costs) == "🍽 meal 15.00 EUR"
    assert weather_badge(
        {"temp_max_avg_c": 26.0, "rain_days": 3.0}
    ) == "☀ 26°C, 3 rain days"


def test_ai_score_badge_always_labeled_and_honest():
    assert ai_score_badge(None, None) == "AI score: insufficient data"
    text = ai_score_badge(82.4, 0.69)
    assert text.startswith("AI score 82/100")
    assert "69% data" in text


def test_score_color_thresholds():
    assert score_color(None) == "grey-5"
    assert score_color(80) == "green-6"
    assert score_color(60) == "amber-7"
    assert score_color(30) == "red-6"


def test_flag_and_names():
    assert flag_emoji("GR") == "🇬🇷"
    assert flag_emoji("bad!") == ""
    assert flag_emoji(None) == ""
    assert dimension_display_name("hidden_gem_match") == "Hidden Gem"


def test_provider_status_mapping():
    assert provider_status_icon({"configured": False}) == \
        "radio_button_unchecked"
    assert provider_status_icon(
        {"configured": True, "is_valid": True}) == "check_circle"
    assert provider_status_color(
        {"configured": True, "is_valid": False}) == "red-6"
    assert provider_status_color(
        {"configured": True, "is_valid": None}) == "amber-7"


def test_unavailable_reason_composition():
    assert unavailable_reason("Map") == "Map unavailable"
    assert unavailable_reason("Cost data", "needs Numbeo key") == \
        "Cost data unavailable — needs Numbeo key"
