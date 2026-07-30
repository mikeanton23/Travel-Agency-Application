# -*- coding: utf-8 -*-

"""
TripVerse Budget Engine

Responsibilities:
- Aggregate pricing data
- Aggregate transport costs
- Aggregate booking requirements
- Calculate day/trip budgets
- Budget-fit scoring
- Trip wallet generation

Data Sources:
- pricing_service.py
- transport_service.py
- booking_service.py

Future API Integrations:
- Amadeus
- Ticketmaster
- Viator
- GetYourGuide
- Rome2Rio
- Navitia
- Booking.com
- OpenTable
"""

from typing import Dict, List

from app.services.pricing_service import (
    get_place_pricing,
)

from app.services.transport_service import (
    get_transport_info,
)

from app.services.booking_service import (
    get_booking_info,
)


# --------------------------------------------------
# Safe Helpers
# --------------------------------------------------

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


# --------------------------------------------------
# Place Cost
# --------------------------------------------------

def calculate_place_cost(
    place: dict,
    daily_budget: float,
    traveler_count: int = 1,
) -> Dict:

    pricing = get_place_pricing(
        place=place,
        daily_budget=daily_budget,
        traveler_count=traveler_count,
    )

    transport = get_transport_info(
        place=place,
    )

    booking = get_booking_info(
        place=place,
    )

    ticket_cost = safe_float(
        pricing.get("estimated_ticket_price", 0)
    )

    food_cost = safe_float(
        pricing.get("estimated_food_price", 0)
    )

    transport_cost = safe_float(
        transport.get("estimated_transport_cost", 0)
    )

    total_cost = (
        ticket_cost
        + food_cost
        + transport_cost
    )

    return {
        "name": place.get("name"),

        "pricing": pricing,
        "transport": transport,
        "booking": booking,

        "ticket_cost": round(ticket_cost, 2),
        "food_cost": round(food_cost, 2),
        "transport_cost": round(transport_cost, 2),

        "estimated_total_cost": round(
            total_cost,
            2,
        ),

        "ticket_required":
            pricing.get("ticket_required", False),

        "reservation_required":
            booking.get("reservation_required", False),

        "booking_url":
            booking.get("booking_url"),

        "transport_mode":
            transport.get("recommended_mode"),
    }


# --------------------------------------------------
# Day Cost
# --------------------------------------------------

def calculate_day_cost(
    places: List[dict],
    daily_budget: float,
    traveler_count: int = 1,
) -> Dict:

    total_used = 0.0

    breakdown = []

    for place in places:

        place_summary = calculate_place_cost(
            place=place,
            daily_budget=daily_budget,
            traveler_count=traveler_count,
        )

        total_used += place_summary[
            "estimated_total_cost"
        ]

        breakdown.append(place_summary)

    remaining = (
        safe_float(daily_budget)
        - total_used
    )

    return {
        "budget": round(daily_budget, 2),
        "used": round(total_used, 2),
        "remaining": round(remaining, 2),
        "breakdown": breakdown,
    }


# --------------------------------------------------
# Trip Cost
# --------------------------------------------------

def calculate_trip_cost(
    itinerary_days: List[dict],
    daily_budget: float,
    traveler_count: int = 1,
):

    total_budget = (
        len(itinerary_days)
        * safe_float(daily_budget)
    )

    total_used = 0.0

    day_summaries = []

    for day in itinerary_days:

        places = []

        places.extend(
            day.get("morning", [])
        )

        places.extend(
            day.get("afternoon", [])
        )

        places.extend(
            day.get("evening", [])
        )

        summary = calculate_day_cost(
            places=places,
            daily_budget=daily_budget,
            traveler_count=traveler_count,
        )

        total_used += summary["used"]

        day_summaries.append({
            "day": day.get("day"),
            **summary,
        })

    return {
        "total_budget":
            round(total_budget, 2),

        "total_used":
            round(total_used, 2),

        "remaining":
            round(
                total_budget - total_used,
                2,
            ),

        "days":
            day_summaries,
    }


# --------------------------------------------------
# Budget Fit Score
# --------------------------------------------------

def calculate_budget_fit_score(
    estimated_cost: float,
    budget: float,
):

    estimated_cost = safe_float(
        estimated_cost
    )

    budget = safe_float(
        budget
    )

    if budget <= 0:
        return 50

    ratio = estimated_cost / budget

    if ratio <= 0.70:
        return 95

    if ratio <= 0.85:
        return 85

    if ratio <= 1.00:
        return 75

    if ratio <= 1.20:
        return 55

    return 35


# --------------------------------------------------
# Optimization
# --------------------------------------------------

def optimize_places_for_budget(
    places: List[dict],
    daily_budget: float,
    traveler_count: int = 1,
):

    results = []

    for place in places:

        cost = calculate_place_cost(
            place=place,
            daily_budget=daily_budget,
            traveler_count=traveler_count,
        )

        fit_score = (
            calculate_budget_fit_score(
                estimated_cost=cost[
                    "estimated_total_cost"
                ],
                budget=daily_budget,
            )
        )

        results.append({
            **place,
            **cost,
            "budget_fit_score":
                fit_score,
        })

    results.sort(
        key=lambda x: (
            x["budget_fit_score"],
            -x["estimated_total_cost"],
        ),
        reverse=True,
    )

    return results


# --------------------------------------------------
# Wallet
# --------------------------------------------------

def build_trip_wallet(
    itinerary: dict,
    daily_budget: float,
    traveler_count: int = 1,
):

    days = itinerary.get(
        "days",
        [],
    )

    summary = calculate_trip_cost(
        itinerary_days=days,
        daily_budget=daily_budget,
        traveler_count=traveler_count,
    )

    used = safe_float(
        summary["total_used"]
    )

    budget = safe_float(
        summary["total_budget"]
    )

    percentage = (
        round(
            (used / budget) * 100,
            1,
        )
        if budget > 0
        else 0
    )

    return {
        **summary,

        "usage_percentage":
            percentage,

        "budget_health": (
            "Excellent"
            if percentage <= 70
            else "Good"
            if percentage <= 90
            else "Tight"
            if percentage <= 100
            else "Over Budget"
        ),
    }