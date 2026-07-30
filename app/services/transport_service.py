# -*- coding: utf-8 -*-

"""
TripVerse Transport Service

Purpose:
- Distance calculations
- Travel time estimation
- Transport cost estimation
- Best transport option
- Transport impact on budget

Future APIs:
- OpenRouteService
- Geoapify Routing
- Transitland
- Google Routes
"""

from math import radians, sin, cos, sqrt, atan2


# =====================================================
# SAFE HELPERS
# =====================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


# =====================================================
# DISTANCE
# =====================================================

def calculate_distance_km(
    lat1,
    lon1,
    lat2,
    lon2,
):
    """
    Haversine distance.
    """

    lat1 = safe_float(lat1)
    lon1 = safe_float(lon1)
    lat2 = safe_float(lat2)
    lon2 = safe_float(lon2)

    earth_radius = 6371

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(
        sqrt(a),
        sqrt(1 - a),
    )

    return round(
        earth_radius * c,
        2,
    )


# =====================================================
# TRAVEL TIME
# =====================================================

def estimate_walking_minutes(distance_km):

    return round(
        (safe_float(distance_km) / 5) * 60
    )


def estimate_bicycle_minutes(distance_km):

    return round(
        (safe_float(distance_km) / 15) * 60
    )


def estimate_public_transport_minutes(distance_km):

    return round(
        (safe_float(distance_km) / 22) * 60
    )


def estimate_car_minutes(distance_km):

    return round(
        (safe_float(distance_km) / 35) * 60
    )


# =====================================================
# COST ESTIMATION
# =====================================================

def estimate_walking_cost(distance_km):
    return 0.0


def estimate_public_transport_cost(distance_km):

    distance_km = safe_float(distance_km)

    if distance_km <= 2:
        return 1.20

    if distance_km <= 8:
        return 1.50

    if distance_km <= 20:
        return 2.50

    return round(
        2.5 + distance_km * 0.10,
        2,
    )


def estimate_taxi_cost(distance_km):

    distance_km = safe_float(distance_km)

    return round(
        4 + distance_km * 1.25,
        2,
    )


def estimate_rideshare_cost(distance_km):

    distance_km = safe_float(distance_km)

    return round(
        3 + distance_km * 1.05,
        2,
    )


# =====================================================
# TRANSPORT OPTIONS
# =====================================================

def build_transport_options(distance_km):

    return {
        "walk": {
            "cost": estimate_walking_cost(distance_km),
            "minutes": estimate_walking_minutes(distance_km),
        },

        "public_transport": {
            "cost": estimate_public_transport_cost(distance_km),
            "minutes": estimate_public_transport_minutes(distance_km),
        },

        "taxi": {
            "cost": estimate_taxi_cost(distance_km),
            "minutes": estimate_car_minutes(distance_km),
        },

        "rideshare": {
            "cost": estimate_rideshare_cost(distance_km),
            "minutes": estimate_car_minutes(distance_km),
        },
    }


# =====================================================
# BEST OPTION
# =====================================================

def best_transport_option(distance_km):

    options = build_transport_options(distance_km)

    if distance_km <= 1.5:
        return "walk"

    if distance_km <= 12:
        return "public_transport"

    return "rideshare"


# =====================================================
# ROUTE SUMMARY
# =====================================================

def build_route_summary(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):

    distance = calculate_distance_km(
        start_lat,
        start_lon,
        end_lat,
        end_lon,
    )

    options = build_transport_options(distance)

    recommended = best_transport_option(distance)

    return {
        "distance_km": distance,
        "recommended_option": recommended,
        "options": options,
    }


# =====================================================
# MAIN API
# =====================================================

def get_transport_info(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):

    route = build_route_summary(
        start_lat,
        start_lon,
        end_lat,
        end_lon,
    )

    recommended = route["recommended_option"]

    recommended_data = route["options"][recommended]

    return {
        **route,

        "estimated_transport_cost":
            recommended_data["cost"],

        "estimated_transport_minutes":
            recommended_data["minutes"],
    }


# =====================================================
# FUTURE API INTEGRATIONS
# =====================================================

def get_openrouteservice_route(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):
    """
    Future implementation.

    OpenRouteService API
    """
    return None


def get_geoapify_route(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):
    """
    Future implementation.

    Geoapify Routing API
    """
    return None


def get_transitland_route(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):
    """
    Future implementation.

    Transitland public transport.
    """
    return None