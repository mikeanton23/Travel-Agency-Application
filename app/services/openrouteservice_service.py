# -*- coding: utf-8 -*-

import requests

from app.utils.config import (
    OPENROUTESERVICE_API_KEY,
)


BASE_URL = (
    "https://api.openrouteservice.org/v2/directions"
)

REQUEST_TIMEOUT = 20


TRANSPORT_PROFILES = {
    "walk": "foot-walking",
    "walking": "foot-walking",

    "car": "driving-car",
    "drive": "driving-car",
    "driving": "driving-car",

    "bike": "cycling-regular",
    "bicycle": "cycling-regular",
    "cycling": "cycling-regular",

    "hike": "foot-hiking",
    "hiking": "foot-hiking",
}


# =====================================================
# SAFE HELPERS
# =====================================================

def safe_float(
    value,
    default=0.0,
):
    try:
        return float(value)
    except Exception:
        return default


def safe_text(
    value,
    default="",
):
    value = str(
        value or ""
    ).strip()

    return value if value else default


def api_available():
    return bool(
        safe_text(
            OPENROUTESERVICE_API_KEY
        )
    )


# =====================================================
# PROFILE
# =====================================================

def normalize_profile(
    profile="car",
):
    profile = safe_text(
        profile,
        "car",
    ).lower()

    return TRANSPORT_PROFILES.get(
        profile,
        "driving-car",
    )


# =====================================================
# TRANSPORT COST ESTIMATION
# =====================================================

def estimate_transport_cost(
    distance_km,
    profile,
):
    distance_km = safe_float(
        distance_km,
        0,
    )

    profile = normalize_profile(
        profile
    )

    if profile == "foot-walking":
        return 0

    if profile == "foot-hiking":
        return 0

    if profile == "cycling-regular":
        return round(
            distance_km * 0.05,
            2,
        )

    if profile == "driving-car":
        return round(
            distance_km * 0.18,
            2,
        )

    return 0


# =====================================================
# MAIN API
# =====================================================

def get_route_info(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
    profile="car",
):
    if not api_available():
        return {
            "success": False,
            "distance_km": 0,
            "duration_minutes": 0,
            "transport_cost": 0,
            "profile": profile,
            "geometry": [],
        }

    ors_profile = normalize_profile(
        profile
    )

    url = (
        f"{BASE_URL}/{ors_profile}"
    )

    payload = {
        "coordinates": [
            [
                safe_float(start_lon),
                safe_float(start_lat),
            ],
            [
                safe_float(end_lon),
                safe_float(end_lat),
            ],
        ]
    }

    try:

        response = requests.post(
            url,
            headers={
                "Authorization":
                    OPENROUTESERVICE_API_KEY,
                "Content-Type":
                    "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        routes = data.get(
            "routes",
            [],
        )

        if not routes:
            raise Exception(
                "No route returned"
            )

        route = routes[0]

        summary = route.get(
            "summary",
            {},
        )

        distance_km = round(
            safe_float(
                summary.get(
                    "distance",
                    0,
                )
            ) / 1000,
            2,
        )

        duration_minutes = round(
            safe_float(
                summary.get(
                    "duration",
                    0,
                )
            ) / 60,
            1,
        )

        geometry = (
            route.get(
                "geometry",
                {}
            )
            .get(
                "coordinates",
                []
            )
        )

        transport_cost = (
            estimate_transport_cost(
                distance_km,
                ors_profile,
            )
        )

        return {
            "success": True,

            "profile":
                ors_profile,

            "distance_km":
                distance_km,

            "duration_minutes":
                duration_minutes,

            "transport_cost":
                transport_cost,

            "geometry":
                geometry,

            "raw":
                data,
        }

    except Exception as e:

        print(
            f"[ORS ERROR] {e}"
        )

        return {
            "success": False,

            "profile":
                ors_profile,

            "distance_km": 0,

            "duration_minutes": 0,

            "transport_cost": 0,

            "geometry": [],

            "error":
                str(e),
        }


# =====================================================
# SMART MODE SELECTION
# =====================================================

def recommend_transport_mode(
    distance_km,
):
    distance_km = safe_float(
        distance_km,
        0,
    )

    if distance_km <= 1:
        return "walk"

    if distance_km <= 5:
        return "bike"

    if distance_km <= 20:
        return "car"

    return "car"


# =====================================================
# SMART ROUTING
# =====================================================

def get_smart_route(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
):
    car_route = get_route_info(
        start_lat,
        start_lon,
        end_lat,
        end_lon,
        profile="car",
    )

    recommended = recommend_transport_mode(
        car_route.get(
            "distance_km",
            0,
        )
    )

    route = get_route_info(
        start_lat,
        start_lon,
        end_lat,
        end_lon,
        profile=recommended,
    )

    route[
        "recommended_mode"
    ] = recommended

    return route