# -*- coding: utf-8 -*-

"""
Travel AI Recommendation Engine

Responsibilities:
- Destination ranking
- Budget compatibility
- Intelligence metrics
- Final recommendation sorting

Images are NOT loaded here.
Images are attached later by recommendation_service.py
after the final ranked destinations are selected.
"""


# =====================================================
# SAFE HELPERS
# =====================================================

def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def clamp(value, minimum=0, maximum=100):
    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


# =====================================================
# BUDGET SCORE
# =====================================================

def budget_score(
    destination_budget,
    user_budget,
):
    destination_budget = safe_float(
        destination_budget,
        0,
    )

    user_budget = safe_float(
        user_budget,
        0,
    )

    if user_budget <= 0:
        return 70

    difference = abs(
        destination_budget
        - user_budget
    )

    ratio = difference / max(
        user_budget,
        1,
    )

    score = 100 - (
        ratio * 100
    )

    return clamp(score)


# =====================================================
# CONTINENT SCORE
# =====================================================

def continent_score(
    destination_continent,
    requested_continent,
):
    if (
        not requested_continent
        or requested_continent == "Any"
    ):
        return 80

    if (
        safe_text(destination_continent).lower()
        ==
        safe_text(requested_continent).lower()
    ):
        return 100

    return 40


# =====================================================
# DESTINATION TYPE SCORE
# =====================================================

def type_score(
    destination,
    user_text="",
):
    text = safe_text(
        user_text
    ).lower()

    score = 60

    name = safe_text(
        getattr(
            destination,
            "name",
            "",
        )
    ).lower()

    description = safe_text(
        getattr(
            destination,
            "description",
            "",
        )
    ).lower()

    combined = (
        name
        + " "
        + description
    )

    if "beach" in text:
        if any(
            word in combined
            for word in [
                "beach",
                "coast",
                "island",
                "sea",
            ]
        ):
            score += 25

    if "mountain" in text:
        if any(
            word in combined
            for word in [
                "mountain",
                "hiking",
                "trail",
                "nature",
            ]
        ):
            score += 20

    if "food" in text:
        score += 10

    if "history" in text:
        score += 10

    if "culture" in text:
        score += 10

    if "nightlife" in text:
        score += 10

    return clamp(score)


# =====================================================
# REALITY SIMULATOR
# =====================================================

def build_reality_metrics(
    destination_budget,
):
    destination_budget = safe_float(
        destination_budget,
        100,
    )

    if destination_budget < 70:
        budget_label = "Very realistic"

    elif destination_budget < 120:
        budget_label = "Realistic"

    elif destination_budget < 180:
        budget_label = "Moderate"

    else:
        budget_label = "Expensive"

    return {
        "trip_twin": 70,
        "hidden_gem": 65,
        "crowd": "Low",
        "budget": budget_label,
        "walking": "Medium",
        "local_score": 80,
        "tourist_trap": "Low",
        "energy": "Easy",
    }


# =====================================================
# DESTINATION ENRICHMENT
# =====================================================

def enrich_destination(
    destination,
    user_budget=100,
    continent="",
    user_text="",
):
    estimated_budget = safe_float(
        getattr(
            destination,
            "avg_cost_per_day",
            getattr(
                destination,
                "estimated_budget",
                100,
            ),
        ),
        100,
    )

    ai_score = round(
        (
            budget_score(
                estimated_budget,
                user_budget,
            )
            * 0.45
            +
            continent_score(
                getattr(
                    destination,
                    "continent",
                    "",
                ),
                continent,
            )
            * 0.20
            +
            type_score(
                destination,
                user_text,
            )
            * 0.35
        ),
        1,
    )

    destination.ai_score = ai_score

    destination.daily_budget = (
        estimated_budget
    )

    destination.reality = (
        build_reality_metrics(
            estimated_budget
        )
    )

    return destination


# =====================================================
# RANKING
# =====================================================

def rank_destinations(
    destinations,
    user_budget=100,
    continent="",
    user_text="",
    user_preferences=None,
):
    enriched = []

    for destination in destinations:

        try:

            enriched.append(
                enrich_destination(
                    destination=destination,
                    user_budget=user_budget,
                    continent=continent,
                    user_text=user_text,
                )
            )

        except Exception as e:

            print(
                "[RECOMMENDATION ENGINE ERROR] "
                f"{getattr(destination,'name','unknown')}: "
                f"{e}"
            )

    enriched.sort(
        key=lambda d: (
            getattr(
                d,
                "travel_dna_match",
                0,
            ),
            getattr(
                d,
                "hidden_gem_score",
                0,
            ),
            getattr(
                d,
                "local_authenticity_score",
                0,
            ),
            getattr(
                d,
                "ai_score",
                0,
            ),
        ),
        reverse=True,
    )

    return enriched