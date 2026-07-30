# -*- coding: utf-8 -*-

from app.services.intelligence.score import (
    DestinationSignals, UserProfile, budget_match, compute_score,
    crowd_match, hidden_gem_match, luxury_match, weather_match,
)


def rich_signals() -> DestinationSignals:
    return DestinationSignals(
        currency="EUR", meal_inexpensive=15.0, cappuccino=3.5,
        transport_ticket=1.2, hotel_median_nightly=90.0,
        month=9, temp_max_avg_c=26.0, rain_days=3.0,
        poi={"restaurants": 250, "cafes": 80, "bars_clubs": 60,
             "museums": 20, "monuments": 15, "parks": 12,
             "natural": 8, "beaches": 6, "playgrounds": 10,
             "theme_parks": 1, "sports_outdoor": 30},
        safety_index=72.0, hotel_ratings=[4.5, 4.0, 3.5, 3.0],
        annual_visitors_millions=2.0, population=650_000,
    )


def test_every_available_dimension_explains_why():
    result = compute_score(rich_signals(), UserProfile(budget_per_day=150))
    for dim in result.dimensions:
        assert dim.reason  # explanation is mandatory
        if dim.available:
            assert dim.inputs_used  # backed by actual data


def test_missing_data_yields_none_not_a_guess():
    empty = DestinationSignals()
    profile = UserProfile(budget_per_day=100)
    assert budget_match(empty, profile).score is None
    assert weather_match(empty, profile).score is None
    assert luxury_match(empty, profile).score is None
    assert crowd_match(empty, profile).score is None
    result = compute_score(empty, profile)
    assert result.overall is None
    assert result.coverage == 0.0


def test_budget_score_reflects_real_basket():
    s = rich_signals()
    generous = budget_match(s, UserProfile(budget_per_day=250))
    tight = budget_match(s, UserProfile(budget_per_day=60))
    assert generous.score > tight.score
    assert "basket" in generous.reason or "budget" in generous.reason
    assert generous.inputs_used["daily_cost"] > 0


def test_weather_in_range_scores_high():
    s = rich_signals()
    good = weather_match(s, UserProfile(preferred_temp_c=(20, 28)))
    s2 = rich_signals()
    s2.temp_max_avg_c = 38.0
    hot = weather_match(s2, UserProfile(preferred_temp_c=(20, 28)))
    assert good.score > hot.score
    assert "26" in good.reason


def test_interest_weighting_changes_overall():
    s = rich_signals()
    foodie = compute_score(s, UserProfile(budget_per_day=150,
                                          interests=["food"]))
    historian = compute_score(s, UserProfile(budget_per_day=150,
                                             interests=["history"]))
    assert foodie.overall != historian.overall


def test_output_labeled_as_ai_score():
    result = compute_score(rich_signals(), UserProfile())
    payload = result.to_dict()
    assert payload["kind"] == "ai_score"
    assert 0 < payload["coverage"] <= 1


def test_hidden_gem_needs_visitor_data():
    s = rich_signals()
    s.annual_visitors_millions = None
    assert hidden_gem_match(s, UserProfile()).score is None
