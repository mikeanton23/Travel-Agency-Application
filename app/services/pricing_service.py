# -*- coding: utf-8 -*-

"""
Aevyra Pricing Service

Purpose:
- Central pricing engine
- Activity pricing
- Attraction pricing
- Food pricing
- Hotel pricing
- Budget-fit scoring

Future APIs:
- Amadeus
- Viator
- Ticketmaster
- Yelp
- Booking
"""

from typing import Dict


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

def country_text(place):
    return safe_text(
        place.get("country")
    ).lower()


def city_text(place):
    return safe_text(
        place.get("city")
    ).lower()


# =====================================================
# CATEGORY HELPERS
# =====================================================

def category_text(place: dict) -> str:
    categories = place.get("categories", [])

    if not isinstance(categories, list):
        return ""

    return " ".join(
        str(c).lower()
        for c in categories
    )


def has_category(place: dict, keywords: list[str]) -> bool:
    text = category_text(place)

    return any(
        keyword.lower() in text
        for keyword in keywords
    )


# =====================================================
# TICKET DETECTION
# =====================================================

def ticket_required(place: dict) -> bool:

    return has_category(
        place,
        [
            "museum",
            "attraction",
            "castle",
            "monument",
            "aquarium",
            "zoo",
            "theme",
            "gallery",
            "archaeological",
        ],
    )


# =====================================================
# RESERVATION DETECTION
# =====================================================

def reservation_required(place: dict) -> bool:

    return has_category(
        place,
        [
            "restaurant",
            "fine_dining",
            "tour",
            "cruise",
            "boat",
            "activity",
            "event",
        ],
    )


# =====================================================
# PRICE ESTIMATION
# =====================================================

def estimate_ticket_price(place: dict) -> float:

    text = category_text(place)
    
    country = country_text(place)

    city = city_text(place)
    
    name = safe_text(
        place.get("name")
    ).lower()

    # Famous attractions

    if "acropolis" in name:
        return 30
    
    if "louvre" in name:
        return 22
    
    if "colosseum" in name:
        return 18
    
    if "eiffel" in name:
        return 0
    
    if "vatican" in name:
        return 25
    
    if "sagrada familia" in name:
        return 26
    
    if "pompeii" in name:
        return 20
    
    if "british museum" in name:
        return 0
    
    if "uffizi" in name:
        return 25
        
    if "theme" in text:
        return 45

    if "aquarium" in text:
        return 25

    if "zoo" in text:
        return 22

    if "castle" in text:
        return 18

    if "museum" in text:
        return 15

    if "gallery" in text:
        return 12

    if "monument" in text:
        return 10

    if "archaeological" in text:
        return 18

    if "attraction" in text:
        return 12

    return 0


def estimate_food_price(
    place: dict,
    daily_budget: float = 120,
):
    text = category_text(place)

    country = country_text(place)

    name = safe_text(
        place.get("name")
    ).lower()

    country_multiplier = {
        "switzerland": 1.70,
        "norway": 1.60,
        "iceland": 1.70,
        "denmark": 1.45,
        "sweden": 1.35,
        "united states": 1.40,
        "canada": 1.30,
        "united kingdom": 1.30,
        "ireland": 1.25,
        "france": 1.20,
        "germany": 1.10,
        "netherlands": 1.15,
        "belgium": 1.10,
        "austria": 1.15,
        "italy": 1.10,
        "spain": 1.00,
        "greece": 0.90,
        "portugal": 0.90,
        "croatia": 0.90,
        "cyprus": 0.90,
        "turkey": 0.70,
        "japan": 1.20,
        "south korea": 1.10,
        "singapore": 1.30,
        "thailand": 0.60,
        "indonesia": 0.60,
        "vietnam": 0.55,
        "india": 0.50,
        "mexico": 0.70,
        "brazil": 0.75,
        "egypt": 0.60,
        "morocco": 0.60,
    }

    multiplier = country_multiplier.get(
        country,
        1.0,
    )

    # ------------------------------
    # Fine dining
    # ------------------------------

    if any(
        x in text
        for x in [
            "fine_dining",
            "fine dining",
            "steakhouse",
        ]
    ):
        return round(
            max(
                55,
                daily_budget * 0.45,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Restaurants
    # ------------------------------

    if "restaurant" in text:

        return round(
            max(
                18,
                daily_budget * 0.20,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Cafes
    # ------------------------------

    if "cafe" in text:

        return round(
            max(
                6,
                daily_budget * 0.06,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Bars
    # ------------------------------

    if "bar" in text:

        return round(
            max(
                10,
                daily_budget * 0.09,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Fast food
    # ------------------------------

    if any(
        x in text
        for x in [
            "fast_food",
            "fast food",
            "burger",
            "pizza",
        ]
    ):
        return round(
            max(
                8,
                daily_budget * 0.08,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Street food
    # ------------------------------

    if any(
        x in text
        for x in [
            "street_food",
            "street food",
            "food_court",
            "food court",
        ]
    ):
        return round(
            max(
                5,
                daily_budget * 0.05,
            ) * multiplier,
            2,
        )

    # ------------------------------
    # Bakery
    # ------------------------------

    if any(
        x in text
        for x in [
            "bakery",
            "pastry",
        ]
    ):
        return round(
            max(
                4,
                daily_budget * 0.04,
            ) * multiplier,
            2,
        )

    return 0


def estimate_activity_price(
    place: dict,
):
    text = category_text(place)

    country = country_text(place)

    country_multiplier = {
        "switzerland": 1.60,
        "norway": 1.50,
        "iceland": 1.60,
        "denmark": 1.35,
        "sweden": 1.30,
        "united states": 1.35,
        "canada": 1.30,
        "united kingdom": 1.25,
        "france": 1.20,
        "italy": 1.10,
        "spain": 1.00,
        "greece": 0.90,
        "croatia": 0.90,
        "portugal": 0.90,
        "turkey": 0.75,
        "japan": 1.20,
        "south korea": 1.15,
        "thailand": 0.65,
        "indonesia": 0.60,
        "vietnam": 0.55,
        "india": 0.50,
        "mexico": 0.70,
        "egypt": 0.65,
        "morocco": 0.65,
    }

    multiplier = country_multiplier.get(
        country,
        1.0,
    )

    # -----------------------------------
    # Cruises
    # -----------------------------------

    if any(
        x in text
        for x in [
            "cruise",
            "ferry",
        ]
    ):
        return round(
            70 * multiplier,
            2,
        )

    # -----------------------------------
    # Boat tours
    # -----------------------------------

    if any(
        x in text
        for x in [
            "boat",
            "sailing",
            "catamaran",
            "yacht",
        ]
    ):
        return round(
            55 * multiplier,
            2,
        )

    # -----------------------------------
    # Guided tours
    # -----------------------------------

    if any(
        x in text
        for x in [
            "tour",
            "guided",
            "excursion",
        ]
    ):
        return round(
            40 * multiplier,
            2,
        )

    # -----------------------------------
    # Wine tasting
    # -----------------------------------

    if any(
        x in text
        for x in [
            "wine",
            "vineyard",
            "winery",
        ]
    ):
        return round(
            35 * multiplier,
            2,
        )

    # -----------------------------------
    # Cooking classes
    # -----------------------------------

    if any(
        x in text
        for x in [
            "cooking",
            "culinary",
            "food experience",
        ]
    ):
        return round(
            60 * multiplier,
            2,
        )

    # -----------------------------------
    # Adventure activities
    # -----------------------------------

    if any(
        x in text
        for x in [
            "kayak",
            "rafting",
            "diving",
            "snorkeling",
            "paragliding",
            "surf",
            "zipline",
            "ski",
            "snowboard",
        ]
    ):
        return round(
            75 * multiplier,
            2,
        )

    # -----------------------------------
    # Theme parks
    # -----------------------------------

    if any(
        x in text
        for x in [
            "theme",
            "water_park",
            "water park",
            "amusement",
        ]
    ):
        return round(
            60 * multiplier,
            2,
        )

    # -----------------------------------
    # Observation decks / towers
    # -----------------------------------

    if any(
        x in text
        for x in [
            "observation",
            "tower",
            "viewpoint",
            "skydeck",
        ]
    ):
        return round(
            20 * multiplier,
            2,
        )

    return 0


# =====================================================
# HOTEL
# =====================================================

def estimate_hotel_price(
    daily_budget: float,
):
    """
    Generic fallback.

    Later:
    Amadeus Hotel Search API
    """

    if daily_budget < 80:
        return 45
    
    if daily_budget < 140:
        return 80
    
    if daily_budget < 220:
        return 130
    
    return round(
        daily_budget * 0.55,
        2,
    )


# =====================================================
# BUDGET FIT
# =====================================================

def budget_fit_score(
    cost: float,
    daily_budget: float,
):

    cost = safe_float(cost)
    daily_budget = safe_float(daily_budget)

    if daily_budget <= 0:
        return 50

    ratio = cost / max(
        daily_budget,
        1,
    )

    if ratio <= 0.10:
        return 100

    if ratio <= 0.25:
        return 90

    if ratio <= 0.40:
        return 80

    if ratio <= 0.60:
        return 65

    if ratio <= 0.80:
        return 50
    
    if ratio <= 0.05:
        return 100
    
    if ratio <= 0.15:
        return 95
        
    return 30


# =====================================================
# MAIN API
# =====================================================

def get_place_pricing(
    place: dict,
    daily_budget: float = 120,
) -> Dict:

    ticket_price = estimate_ticket_price(place)

    food_price = estimate_food_price(
        place,
        daily_budget=daily_budget,
    )

    activity_price = estimate_activity_price(
        place,
    )

    hotel_price = 0

    categories = category_text(place)

    if (
        "hotel" in categories
        or "accommodation" in categories
    ):
        hotel_price = estimate_hotel_price(
            daily_budget,
        )

    transport_price = safe_float(
        place.get(
            "transport_cost",
            0,
        ),
        0,
    )

    total = round(
        ticket_price
        + food_price
        + activity_price
        + hotel_price
        + transport_price,
        2,
    )

    return {

        # -----------------------------
        # Main estimated prices
        # -----------------------------

        "estimated_ticket_price": round(
            ticket_price,
            2,
        ),

        "estimated_food_price": round(
            food_price,
            2,
        ),

        "estimated_activity_price": round(
            activity_price,
            2,
        ),

        "estimated_hotel_price": round(
            hotel_price,
            2,
        ),

        "estimated_transport_price": round(
            transport_price,
            2,
        ),

        "estimated_total_price": total,

        # -----------------------------
        # Requirements
        # -----------------------------

        "ticket_required": ticket_required(
            place,
        ),

        "reservation_required": reservation_required(
            place,
        ),

        # -----------------------------
        # Budget
        # -----------------------------

        "budget_fit_score": budget_fit_score(
            total,
            daily_budget,
        ),

        # -----------------------------
        # Pricing metadata
        # -----------------------------

        "currency": "EUR",

        "pricing_source": "estimated",

        # -----------------------------
        # Legacy compatibility
        # -----------------------------

        "ticket_price": round(
            ticket_price,
            2,
        ),

        "food_price": round(
            food_price,
            2,
        ),

        "activity_price": round(
            activity_price,
            2,
        ),

        "hotel_price": round(
            hotel_price,
            2,
        ),

        "transport_price": round(
            transport_price,
            2,
        ),
    }

# =====================================================
# FUTURE API HOOKS
# =====================================================

def get_viator_price(place):
    """
    Future implementation.
    """
    return None


def get_amadeus_activity_price(place):
    """
    Future implementation.
    """
    return None


def get_ticketmaster_price(place):
    """
    Future implementation.
    """
    return None


def get_yelp_price(place):
    """
    Future implementation.
    """
    return None