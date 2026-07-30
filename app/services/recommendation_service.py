# -*- coding: utf-8 -*-

import random

from sqlalchemy.orm import joinedload

from app.db.database import SessionLocal
from app.db.models import Destination
from app.services.place_discovery import (
    discover_places,
    extract_requested_countries,
)
from app.services.restcountries_service import get_country_continent
from app.services.image_service import get_image_for_destination
from app.services.recommendation_engine import rank_destinations


DEFAULT_RECOMMENDATION_LIMIT = 15
SOFT_BUDGET_MULTIPLIER = 1.8
DISCOVERY_BUDGET_MULTIPLIER = 2.4
DATABASE_FALLBACK_MULTIPLIER = 4


BAD_PLACE_TYPES = {
    "postcode",
    "street",
    "building",
    "house",
    "address",
    "amenity",
}

WEAK_TRAVEL_WORDS = {
    "regional unit",
    "municipal unit",
    "municipality",
    "province",
    "prefecture",
    "administration",
    "department",
    "district",
    "county",
    "state",
    "region of",
}

GENERIC_BAD_NAMES = {
    "park",
    "beach",
    "road",
    "street",
    "hotel",
    "restaurant",
    "cafe",
    "bar",
    "airport",
    "station",
    "center",
    "centre",
    "place",
    "area",
    "locality",
    "unnamed",
}

BAD_NAME_FRAGMENTS = {
    "territorial community",
    "industrial park",
    "industrial estate",
    "research station",
    "junction",
    "plantation",
    "reservation",
    "administrative",
    "municipality",
    "sector",
    "zone",
    "block",
    "phase",
}


COUNTRY_ALIASES = {
    "bangladesh": ["bangladesh", "people's republic of bangladesh"],
    "bulgaria": ["bulgaria", "republic of bulgaria"],
    "hong kong": [
        "hong kong",
        "hong kong s.a.r.",
        "hong kong sar",
        "hong kong special administrative region",
        "hong kong special administrative region of china",
    ],
    "oman": ["oman", "sultanate of oman"],
    "greece": ["greece", "hellas", "ellada", "greek republic"],
    "cyprus": ["cyprus", "republic of cyprus", "northern cyprus"],
    "united states": [
        "united states",
        "usa",
        "u.s.a.",
        "america",
        "united states of america",
    ],
    "united kingdom": [
        "united kingdom",
        "uk",
        "u.k.",
        "great britain",
        "britain",
        "england",
    ],
}


def normalize_text(value) -> str:
    return str(value or "").strip()


def normalize_key(value) -> str:
    return normalize_text(value).lower()


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def safe_text(value, default="") -> str:
    value = str(value or "").strip()
    return value if value else default
    
def safe_int(value, default=0) -> int:
    try:
        value = int(float(value or default))
        return value if value > 0 else default
    except Exception:
        return default


def text_contains_any(text: str, words: list[str] | set[str]) -> bool:
    text = normalize_key(text)
    return any(str(word).lower() in text for word in words)


def is_generic_bad_name(name: str) -> bool:
    text = normalize_key(name)
    words = text.split()

    if not text:
        return True

    if text in GENERIC_BAD_NAMES:
        return True

    if len(words) <= 2 and any(word in GENERIC_BAD_NAMES for word in words):
        return True

    return False


def is_admin_name(name: str) -> bool:
    text = normalize_key(name)
    return any(word in text for word in WEAK_TRAVEL_WORDS)


def is_low_quality_destination(dest) -> bool:
    name = normalize_text(
        getattr(dest, "name", "")
    )

    place_type = normalize_key(
        getattr(dest, "place_type", "")
    )

    if not name:
        return True

    if place_type in BAD_PLACE_TYPES:
        return True

    if is_generic_bad_name(name):
        return True

    if is_admin_name(name):
        return True

    if any(
        fragment in normalize_key(name)
        for fragment in BAD_NAME_FRAGMENTS
    ):
        return True

    country = normalize_key(
        getattr(
            dest,
            "country",
            "",
        )
    )

    if country and normalize_key(name) == country:
        return True

    if len(name.split()) <= 1 and country:
        if normalize_key(name) in {
            "italy",
            "france",
            "spain",
            "greece",
            "portugal",
            "croatia",
        }:
            return True

    return False


def get_aliases(country_name: str) -> set[str]:
    key = normalize_key(country_name)
    aliases = {key}

    if key in COUNTRY_ALIASES:
        aliases.update(COUNTRY_ALIASES[key])

    for main_country, values in COUNTRY_ALIASES.items():
        normalized_values = {normalize_key(value) for value in values}

        if key in normalized_values:
            aliases.add(main_country)
            aliases.update(normalized_values)

    return {normalize_key(alias) for alias in aliases if alias}


def soft_country_match(destination_country: str, requested_country: str) -> bool:
    dest = normalize_key(destination_country)
    req = normalize_key(requested_country)

    if not dest or not req:
        return False

    if dest == req:
        return True

    if req in dest or dest in req:
        return True

    return bool(get_aliases(dest).intersection(get_aliases(req)))


def destination_matches_continent(dest, continent: str) -> bool:
    if not continent or continent == "Any":
        return True

    selected = normalize_key(continent)
    detected = normalize_key(getattr(dest, "continent", ""))

    if detected and detected == selected:
        return True

    real_continent = get_country_continent(
        country_name=normalize_text(getattr(dest, "country", ""))
    )

    return normalize_key(real_continent) == selected


def destination_matches_requested_country(dest, requested_countries: list) -> bool:
    if not requested_countries:
        return True

    destination_country = normalize_text(getattr(dest, "country", ""))

    return any(
        soft_country_match(destination_country, requested_country)
        for requested_country in requested_countries
    )


def destination_matches_budget(dest, budget: float, soft_budget: float) -> bool:
    if budget <= 0:
        return True

    cost = safe_float(getattr(dest, "avg_cost_per_day", None), default=999999)

    if cost <= 0 or cost >= 999999:
        return True

    return cost <= soft_budget


def extract_ui_value(user_text: str, label: str, default: str = "") -> str:
    marker = f"{label}:"

    for line in (user_text or "").splitlines():
        clean_line = line.strip()

        if clean_line.lower().startswith(marker.lower()):
            return clean_line.split(":", 1)[1].replace(".", "").strip()

    return default


def build_user_text_with_country(user_text: str, country: str = "Any") -> str:
    if not country or country == "Any":
        return user_text or ""

    return (
        f"{user_text or ''}\n"
        f"Selected country: {country}. "
        f"Search only inside {country}. "
        f"Return many different real cities, islands, towns, villages, coastal places, nature areas, "
        f"historic places, underrated places, scenic areas, and real travel destinations from this country. "
        f"Do not recommend destinations from other countries. "
        f"Do not return generic places like Park, Beach, Hotel, Road, Street, Area, or administrative regions."
    )


def build_requested_countries(user_text: str, continent: str, country: str = "Any") -> list:
    if country and country != "Any":
        return [country]

    return extract_requested_countries(user_text, continent)


def _destination_text(dest, user_text: str = "") -> str:
    return normalize_key(
        f"{user_text} "
        f"{getattr(dest, 'name', '')} "
        f"{getattr(dest, 'country', '')} "
        f"{getattr(dest, 'continent', '')} "
        f"{getattr(dest, 'description', '')} "
        f"{getattr(dest, 'place_type', '')}"
    )


def estimate_hidden_gem_score(dest, user_text: str = "") -> int:
    score = 50
    text = _destination_text(dest, user_text)

    if text_contains_any(text, ["village", "hidden", "underrated", "authentic", "local", "quiet", "peaceful"]):
        score += 25

    if text_contains_any(text, ["nature", "mountain", "coastal", "island", "walking", "viewpoint", "scenic"]):
        score += 15

    if text_contains_any(text, ["capital", "airport", "downtown", "metropolitan", "very popular"]):
        score -= 15

    if text_contains_any(text, ["district", "postcode", "street", "building", "administration", "municipality"]):
        score -= 25

    return max(0, min(100, score))


def estimate_crowd_level(dest, user_text: str = "") -> str:
    text = _destination_text(dest, user_text)

    if text_contains_any(text, ["quiet", "peaceful", "hidden", "village", "nature", "underrated", "remote"]):
        return "Low"

    if text_contains_any(text, ["capital", "nightlife", "popular", "resort", "tourist", "downtown"]):
        return "High"

    return "Medium"


def estimate_budget_realism(dest, budget: float) -> str:
    cost = safe_float(getattr(dest, "avg_cost_per_day", None), default=999999)

    if budget <= 0:
        return "Flexible"

    if cost <= 0 or cost >= 999999:
        return "Unknown"

    if cost <= budget * 0.85:
        return "Very realistic"

    if cost <= budget:
        return "Realistic"

    if cost <= budget * 1.25:
        return "Tight"

    return "Risky"


def estimate_walking_difficulty(dest, user_text: str = "") -> str:
    text = _destination_text(dest, user_text)

    if text_contains_any(text, ["mountain", "hiking", "trail", "cliff", "steep"]):
        return "High"

    if text_contains_any(text, ["old town", "walking", "village", "nature", "viewpoint"]):
        return "Medium"

    if text_contains_any(text, ["beach", "resort", "relax", "hotel", "cafe"]):
        return "Low"

    return "Medium"


def estimate_local_authenticity_score(dest, user_text: str = "") -> int:
    score = 55
    text = _destination_text(dest, user_text)

    if text_contains_any(text, ["local", "authentic", "village", "traditional", "old town", "market", "culture"]):
        score += 25

    if text_contains_any(text, ["hidden", "underrated", "quiet", "non touristy", "non-touristy"]):
        score += 15

    if text_contains_any(text, ["resort", "airport", "capital", "tourist trap", "downtown"]):
        score -= 15

    return max(0, min(100, score))


def estimate_tourist_trap_risk(dest, user_text: str = "") -> str:
    text = _destination_text(dest, user_text)

    if text_contains_any(text, ["tourist trap", "very popular", "capital", "downtown", "resort"]):
        return "High"

    if text_contains_any(text, ["hidden", "underrated", "authentic", "local", "village", "quiet"]):
        return "Low"

    return "Medium"


def estimate_trip_twin_match(dest, user_text: str = "") -> int:
    score = 55

    travel_dna = normalize_key(extract_ui_value(user_text, "AI Travel DNA", "Balanced"))
    crowd_strategy = normalize_key(extract_ui_value(user_text, "Crowd Strategy", "Normal"))
    trip_pace = normalize_key(extract_ui_value(user_text, "Trip Pace", "Balanced"))
    discovery_mode = normalize_key(extract_ui_value(user_text, "Discovery Mode", "Best Match"))

    text = _destination_text(dest, user_text)

    if "romantic" in travel_dna and text_contains_any(text, ["romantic", "sunset", "sea", "cozy", "couple"]):
        score += 18

    if "hidden" in travel_dna and text_contains_any(text, ["hidden", "underrated", "village", "authentic", "quiet"]):
        score += 18

    if "luxury" in travel_dna and text_contains_any(text, ["luxury", "resort", "boutique", "spa", "sea view"]):
        score += 15

    if ("food" in travel_dna or "culture" in travel_dna) and text_contains_any(
        text, ["food", "restaurant", "cafe", "market", "culture", "museum", "history"]
    ):
        score += 15

    if "nature" in travel_dna and text_contains_any(text, ["nature", "mountain", "lake", "forest", "hiking"]):
        score += 15

    if "avoid crowds" in crowd_strategy and text_contains_any(text, ["quiet", "hidden", "peaceful", "village"]):
        score += 12

    if "only quiet" in crowd_strategy and text_contains_any(text, ["quiet", "peaceful", "remote", "village"]):
        score += 14

    if "slow" in trip_pace and text_contains_any(text, ["relax", "cozy", "cafe", "beach", "walking"]):
        score += 10

    if "full schedule" in trip_pace and text_contains_any(text, ["city", "museum", "restaurant", "activities", "old town"]):
        score += 8

    if "underrated" in discovery_mode and text_contains_any(text, ["underrated", "hidden", "authentic", "local"]):
        score += 12

    if "budget maximizer" in discovery_mode:
        score += 5

    return max(0, min(100, score))


def estimate_daily_energy_level(dest, user_text: str = "") -> str:
    trip_pace = normalize_key(extract_ui_value(user_text, "Trip Pace", "Balanced"))
    walking = estimate_walking_difficulty(dest, user_text)

    if "minimal walking" in trip_pace:
        return "Easy"

    if "full schedule" in trip_pace:
        return "Intense"

    if walking == "High":
        return "Intense"

    if walking == "Low":
        return "Easy"

    return "Balanced"


def build_trip_mood(dest, user_text: str = "") -> str:
    text = _destination_text(dest, user_text)
    moods = []

    if text_contains_any(text, ["romantic", "couple", "sunset", "cozy"]):
        moods.append("Romantic")

    if text_contains_any(text, ["relax", "slow", "peaceful", "quiet", "beach"]):
        moods.append("Relaxed")

    if text_contains_any(text, ["culture", "history", "museum", "old town", "architecture"]):
        moods.append("Cultural")

    if text_contains_any(text, ["food", "restaurant", "cafe", "wine", "local food"]):
        moods.append("Food-focused")

    if text_contains_any(text, ["hiking", "nature", "mountain", "adventure", "walking"]):
        moods.append("Exploratory")

    if estimate_hidden_gem_score(dest, user_text) >= 70:
        moods.append("Hidden-gem")

    if estimate_crowd_level(dest, user_text) == "High":
        moods.append("Lively")

    if not moods:
        moods = ["Balanced", "Practical"]

    return ", ".join(moods[:4])


def build_budget_reality_check(dest, budget: float) -> str:
    cost = safe_float(getattr(dest, "avg_cost_per_day", None), default=999999)

    if budget <= 0:
        return "Flexible budget: no strict daily limit was applied."

    if cost <= 0 or cost >= 999999:
        return "Budget estimate is limited, so keep some flexibility."

    difference = cost - budget

    if cost <= budget * 0.85:
        return "Comfortable: you should have room for food, cafes, and extras."

    if cost <= budget:
        return "Realistic: this should fit your daily budget."

    if cost <= budget * 1.25:
        return f"Tight: you may need about +{round(difference)} EUR/day."

    return f"Risky: you may need about +{round(difference)} EUR/day or a cheaper plan."


def build_regret_predictor(dest, budget: float, user_text: str = "") -> list:
    text = _destination_text(dest, user_text)
    regrets = []

    crowd = estimate_crowd_level(dest, user_text)
    walking = estimate_walking_difficulty(dest, user_text)
    trap = estimate_tourist_trap_risk(dest, user_text)
    budget_realism = estimate_budget_realism(dest, budget)

    if crowd == "High" and text_contains_any(text, ["quiet", "peaceful", "relax", "avoid crowds"]):
        regrets.append("You may regret this if you strongly dislike crowds.")

    if walking == "High" and text_contains_any(text, ["minimal walking", "easy", "relax"]):
        regrets.append("You may regret this if you want very low walking effort.")

    if trap == "High" and text_contains_any(text, ["authentic", "local", "hidden", "non touristy", "non-touristy"]):
        regrets.append("You may regret this if you want a very local, non-touristy feeling.")

    if budget_realism == "Risky":
        regrets.append("You may regret this if your daily budget is strict.")

    if not regrets:
        regrets.append("Low regret risk based on your current preferences.")

    return regrets[:3]


def build_smart_timing_tip(dest, user_text: str = "") -> str:
    crowd = estimate_crowd_level(dest, user_text)
    trip_pace = normalize_key(extract_ui_value(user_text, "Trip Pace", "Balanced"))
    text = _destination_text(dest, user_text)

    if crowd == "High":
        return "Start early, keep lunch flexible, and avoid the busiest central areas in the evening."

    if "slow" in trip_pace or text_contains_any(text, ["relax", "peaceful", "quiet"]):
        return "Plan one main activity per day and leave late afternoons open for cafes, sunsets, or walks."

    if "full schedule" in trip_pace:
        return "Group nearby places together and use mornings for sights, afternoons for food or local walks."

    return "Keep the first day light, then adjust the pace based on transport time and energy."


def build_trip_twin_label(dest, user_text: str = "", budget: float = 0) -> str:
    twin = estimate_trip_twin_match(dest, user_text)
    hidden = estimate_hidden_gem_score(dest, user_text)
    crowd = estimate_crowd_level(dest, user_text)
    budget_realism = estimate_budget_realism(dest, budget)

    if twin >= 85:
        return "Strong Trip Twin"

    if hidden >= 75 and crowd == "Low":
        return "Hidden-Gem Twin"

    if budget_realism in ["Very realistic", "Realistic"]:
        return "Budget-Smart Twin"

    if crowd == "Low":
        return "Quiet Twin"

    return "Balanced Twin"


def build_best_for(dest, user_text: str = "") -> str:
    text = normalize_key(user_text)

    if "romantic" in text or "couple" in text:
        return "couples, sunsets, slow evenings, scenic food stops"

    if "family" in text:
        return "families, relaxed days, safe walks, easy activities"

    if "solo" in text:
        return "solo travelers, culture, cafes, walkable discovery"

    if "friends" in text:
        return "friends, food, activities, nightlife, flexible exploring"

    return "balanced travelers, local discovery, flexible planning"


def build_avoid_if(dest, user_text: str = "", budget: float = 0) -> str:
    walking = estimate_walking_difficulty(dest, user_text)
    crowd = estimate_crowd_level(dest, user_text)
    budget_realism = estimate_budget_realism(dest, budget)

    if walking == "High":
        return "you want very low walking or no hills"

    if crowd == "High":
        return "you strongly dislike busy tourist areas"

    if budget_realism == "Risky":
        return "you need strict low-cost travel"

    return "you want only famous mainstream destinations"


def build_ai_tip(dest, user_text: str = "") -> str:
    crowd = estimate_crowd_level(dest, user_text)
    hidden = estimate_hidden_gem_score(dest, user_text)

    if crowd == "High":
        return "Visit early morning or late afternoon to avoid peak crowds."

    if hidden >= 75:
        return "Use this as a base for nearby small villages, viewpoints, and local food stops."

    return "Keep the schedule flexible and let the AI itinerary group nearby places by distance."


def build_risk_flags(dest, budget: float, user_text: str = "") -> list:
    flags = []

    cost = safe_float(getattr(dest, "avg_cost_per_day", None), default=999999)
    text = _destination_text(dest, user_text)

    if budget > 0 and cost > budget and cost < 999999:
        flags.append("May exceed daily budget")

    if text_contains_any(text, ["limited nearby data", "some nearby options"]):
        flags.append("Limited nearby data")

    if text_contains_any(text, ["busy", "popular", "capital", "nightlife", "downtown"]):
        flags.append("May be crowded")

    if text_contains_any(text, ["island", "remote", "mountain", "village"]):
        flags.append("Check transport access")

    if text_contains_any(text, ["summer", "august", "peak season"]):
        flags.append("Peak-season prices possible")

    return flags[:4]


def attach_destination_intelligence(
    dest,
    user_text: str,
    budget: float,
):
    try:

        # ------------------------------------------
        # AI scoring
        # ------------------------------------------

        dest.hidden_gem_score = estimate_hidden_gem_score(
            dest,
            user_text,
        )

        dest.crowd_level = estimate_crowd_level(
            dest,
            user_text,
        )

        dest.crowd_risk = dest.crowd_level

        dest.budget_realism = estimate_budget_realism(
            dest,
            budget,
        )

        dest.walking_difficulty = estimate_walking_difficulty(
            dest,
            user_text,
        )

        dest.local_authenticity_score = (
            estimate_local_authenticity_score(
                dest,
                user_text,
            )
        )

        dest.tourist_trap_risk = (
            estimate_tourist_trap_risk(
                dest,
                user_text,
            )
        )

        dest.travel_dna_match = estimate_trip_twin_match(
            dest,
            user_text,
        )


        # ------------------------------------------
        # Image enrichment disabled here.
        # Images are attached AFTER ranking
        # to avoid hundreds of Pexels requests.
        # ------------------------------------------
        
        dest.image_url = ""
        dest.thumbnail_url = ""
        dest.image_provider = ""
        dest.image_score = 0

        # ------------------------------------------
        # AI explanation fields
        # ------------------------------------------

        dest.trip_mood = build_trip_mood(
            dest,
            user_text,
        )

        dest.daily_energy_level = (
            estimate_daily_energy_level(
                dest,
                user_text,
            )
        )

        dest.budget_reality_check = (
            build_budget_reality_check(
                dest,
                budget,
            )
        )

        dest.regret_predictor = (
            build_regret_predictor(
                dest,
                budget,
                user_text,
            )
        )

        dest.smart_timing_tip = (
            build_smart_timing_tip(
                dest,
                user_text,
            )
        )

        dest.trip_twin_label = (
            build_trip_twin_label(
                dest,
                user_text,
                budget,
            )
        )

        dest.best_for = build_best_for(
            dest,
            user_text,
        )

        dest.avoid_if = build_avoid_if(
            dest,
            user_text,
            budget,
        )

        dest.ai_tip = build_ai_tip(
            dest,
            user_text,
        )

        dest.risk_flags = build_risk_flags(
            dest,
            budget,
            user_text,
        )

    except Exception as e:

        print(
            "[INTELLIGENCE ERROR] "
            f"Could not attach intelligence: {e}"
        )

        dest.hidden_gem_score = None
        dest.crowd_level = None
        dest.crowd_risk = None
        dest.budget_realism = None
        dest.walking_difficulty = None
        dest.local_authenticity_score = None
        dest.tourist_trap_risk = None
        dest.travel_dna_match = None

        dest.trip_mood = None
        dest.daily_energy_level = None
        dest.budget_reality_check = None
        dest.regret_predictor = []
        dest.smart_timing_tip = None
        dest.trip_twin_label = None

        dest.best_for = None
        dest.avoid_if = None
        dest.ai_tip = None
        dest.risk_flags = []

        dest.image_url = ""
        dest.thumbnail_url = ""
        dest.image_provider = None
        dest.image_score = 0

    return dest


def destination_sort_key(dest):
    ai_score = safe_float(
        getattr(
            dest,
            "ai_score",
            0,
        ),
        default=0,
    )

    travel_dna_match = safe_float(
        getattr(
            dest,
            "travel_dna_match",
            0,
        ),
        default=0,
    )

    hidden_gem_score = safe_float(
        getattr(
            dest,
            "hidden_gem_score",
            0,
        ),
        default=0,
    )

    local_authenticity_score = safe_float(
        getattr(
            dest,
            "local_authenticity_score",
            0,
        ),
        default=0,
    )

    image_score = safe_float(
        getattr(
            dest,
            "image_score",
            0,
        ),
        default=0,
    )

    average_cost = safe_float(
        getattr(
            dest,
            "avg_cost_per_day",
            999999,
        ),
        default=999999,
    )

    budget_realism_bonus = 0

    budget_realism = str(
        getattr(
            dest,
            "budget_realism",
            "",
        )
    ).lower()

    if budget_realism == "very realistic":
        budget_realism_bonus = 20

    elif budget_realism == "realistic":
        budget_realism_bonus = 15

    elif budget_realism == "tight":
        budget_realism_bonus = 5

    elif budget_realism == "risky":
        budget_realism_bonus = -20

    quality_penalty = (
        -1000
        if is_low_quality_destination(dest)
        else 0
    )

    return (
        quality_penalty,
        ai_score,
        travel_dna_match,
        local_authenticity_score,
        hidden_gem_score,
        image_score,
        budget_realism_bonus,
        -average_cost,
    )


def get_database_fallback_results(
    db,
    budget: float,
    soft_budget: float,
    requested_countries: list,
    continent: str,
    limit: int,
):
    query = (
        db.query(Destination)
        .options(
            joinedload(Destination.images),
            joinedload(Destination.seasons),
        )
    )

    if budget > 0:
        query = query.filter(Destination.avg_cost_per_day <= soft_budget)

    fallback_results = query.all()

    fallback_results = [
        dest for dest in fallback_results
        if not is_low_quality_destination(dest)
    ]

    if requested_countries:
        fallback_results = [
            dest for dest in fallback_results
            if destination_matches_requested_country(dest, requested_countries)
        ]

    if continent and continent != "Any":
        fallback_results = [
            dest for dest in fallback_results
            if destination_matches_continent(dest, continent)
        ]

    random.shuffle(fallback_results)

    return fallback_results[: max(limit * DATABASE_FALLBACK_MULTIPLIER, limit)]


def get_recommendations(
    budget_per_day: float,
    travel_month: str,
    user_preferences: str,
    travelers: str,
    continent: str = "Any",
    country: str = "Any",
    days: int = 5,

    limit: int = DEFAULT_RECOMMENDATION_LIMIT,

    travel_dna: str = "Balanced",
    crowd_strategy: str = "Normal",
    trip_pace: str = "Balanced",
    discovery_mode: str = "Best Match",
    walking_level: str = "Any",
    tourist_trap_sensitivity: str = "Normal",
    local_authenticity: str = "Balanced",
    comfort_adventure: str = "Balanced",

    include_weather: bool = True,
    include_events: bool = True,
    include_real_prices: bool = True,
    include_transport: bool = True,
    include_hotels: bool = True,
    include_images: bool = True,
    include_hidden_gems: bool = True,
    include_airport_accessibility: bool = True,
    include_crowd_estimation: bool = True,
    include_local_authenticity_score: bool = True,
    include_budget_realism: bool = True,
    include_ai_summary: bool = True,
):
    # --------------------------------------------------
    # Basic validation
    # --------------------------------------------------

    limit = safe_int(
        limit,
        DEFAULT_RECOMMENDATION_LIMIT,
    )
    
    days = max(
        1,
        min(
            safe_int(days, 5),
            60,
        ),
    )
    
    budget_per_day = safe_float(
        budget_per_day,
        default=0,
    )
    
    soft_budget = (
        budget_per_day * SOFT_BUDGET_MULTIPLIER
        if budget_per_day > 0
        else 0
    )
    
    budget = budget_per_day
    month = travel_month
    user_text = user_preferences
    
    continent = safe_text(
        continent,
        "Any",
    )
    
    country = safe_text(
        country,
        "Any",
    )
    
    travelers = safe_text(
        travelers,
        "Couple",
    )
    
    month = safe_text(
        month,
        "Jun",
    )
    
    user_text = safe_text(
        user_text,
        "",
    )
    
    enriched_user_text = build_user_text_with_country(
        user_text=user_text,
        country=country,
    )
    

    # --------------------------------------------------
    # Extract UI values if not explicitly supplied
    # --------------------------------------------------

    travel_dna = (
        travel_dna
        or extract_ui_value(
            enriched_user_text,
            "AI Travel DNA",
            "Balanced",
        )
    )

    crowd_strategy = (
        crowd_strategy
        or extract_ui_value(
            enriched_user_text,
            "Crowd Strategy",
            "Normal",
        )
    )

    trip_pace = (
        trip_pace
        or extract_ui_value(
            enriched_user_text,
            "Trip Pace",
            "Balanced",
        )
    )

    discovery_mode = (
        discovery_mode
        or extract_ui_value(
            enriched_user_text,
            "Discovery Mode",
            "Best Match",
        )
    )

    walking_level = (
        walking_level
        or extract_ui_value(
            enriched_user_text,
            "Walking Level",
            "Any",
        )
    )

    tourist_trap_sensitivity = (
        tourist_trap_sensitivity
        or extract_ui_value(
            enriched_user_text,
            "Tourist Trap Sensitivity",
            "Normal",
        )
    )

    local_authenticity = (
        local_authenticity
        or extract_ui_value(
            enriched_user_text,
            "Local Authenticity Preference",
            "Balanced",
        )
    )

    comfort_adventure = (
        comfort_adventure
        or extract_ui_value(
            enriched_user_text,
            "Comfort vs Adventure",
            "Balanced",
        )
    )

    requested_countries = build_requested_countries(
        user_text=enriched_user_text,
        continent=continent,
        country=country,
    )

    # --------------------------------------------------
    # Debug information
    # --------------------------------------------------

    print("\n==============================")
    print("NEW USER SEARCH")
    print("==============================")

    print(f"Budget: {budget}")
    print(f"Soft budget limit: {soft_budget}")
    print(f"Month: {month}")
    print(f"Travelers: {travelers}")
    print(f"Days: {days}")

    print(f"Continent: {continent}")
    print(f"Country: {country}")

    print(f"Limit: {limit}")
    print(f"Requested countries: {requested_countries}")

    print(f"Travel DNA: {travel_dna}")
    print(f"Crowd Strategy: {crowd_strategy}")
    print(f"Trip Pace: {trip_pace}")
    print(f"Discovery Mode: {discovery_mode}")
    print(f"Walking Level: {walking_level}")
    print(f"Tourist Trap Sensitivity: {tourist_trap_sensitivity}")
    print(f"Local Authenticity: {local_authenticity}")
    print(f"Comfort vs Adventure: {comfort_adventure}")

    print(f"Weather Enabled: {include_weather}")
    print(f"Events Enabled: {include_events}")
    print(f"Real Prices Enabled: {include_real_prices}")
    print(f"Transport Enabled: {include_transport}")
    print(f"Hotels Enabled: {include_hotels}")
    print(f"Images Enabled: {include_images}")
    print(f"Hidden Gems Enabled: {include_hidden_gems}")
    print(f"Airport Accessibility Enabled: {include_airport_accessibility}")
    print(f"Crowd Estimation Enabled: {include_crowd_estimation}")
    print(f"Local Authenticity Enabled: {include_local_authenticity_score}")
    print(f"Budget Realism Enabled: {include_budget_realism}")
    print(f"AI Summary Enabled: {include_ai_summary}")

    print("==============================\n")

    # -----------------------------------
    # Initialize result containers
    # -----------------------------------
    
    final_results = []
    seen = set()
    
    debug_counts = {
        "added": 0,
        "missing_name_country": 0,
        "low_quality_skip": 0,
        "country_skip": 0,
        "continent_skip": 0,
        "budget_skip": 0,
        "duplicate_skip": 0,
        "image_failures": 0,
        "weather_failures": 0,
        "events_failures": 0,
        "pricing_failures": 0,
        "transport_failures": 0,
    }
    
    # -----------------------------------
    # Destination processor
    # -----------------------------------
    
    def add_destination(
        dest,
        source="unknown",
    ):
        if not dest:
            return
    
        name = normalize_text(
            getattr(
                dest,
                "name",
                "",
            )
        )
    
        destination_country = normalize_text(
            getattr(
                dest,
                "country",
                "",
            )
        )
    
        # =====================================================
        # BASIC VALIDATION
        # =====================================================
    
        if not name:
            debug_counts[
                "missing_name_country"
            ] += 1
            return
    
        if (
            not destination_country
            and country
            and country != "Any"
        ):
            destination_country = normalize_text(
                country
            )
    
            try:
                dest.country = (
                    destination_country
                )
            except Exception:
                pass
    
        if not destination_country:
            debug_counts[
                "missing_name_country"
            ] += 1
            return
    
        # =====================================================
        # REMOVE COUNTRY RESULTS
        # Example:
        # Italy, Italy
        # Greece, Greece
        # France, France
        # =====================================================
    
        if (
            normalize_key(name)
            ==
            normalize_key(
                destination_country
            )
        ):
            debug_counts[
                "low_quality_skip"
            ] += 1
    
            print(
                f"[RECOMMENDER COUNTRY-AS-CITY SKIP] "
                f"{name}, "
                f"{destination_country}"
            )
            return
    
        # =====================================================
        # QUALITY FILTER
        # =====================================================
    
        if is_low_quality_destination(
            dest
        ):
            debug_counts[
                "low_quality_skip"
            ] += 1
    
            print(
                f"[RECOMMENDER QUALITY SKIP] "
                f"{name}, "
                f"{destination_country}, "
                f"source={source}"
            )
            return
    
        # =====================================================
        # COUNTRY FILTER
        # =====================================================
    
        if not destination_matches_requested_country(
            dest,
            requested_countries,
        ):
            debug_counts[
                "country_skip"
            ] += 1
    
            print(
                f"[RECOMMENDER COUNTRY SKIP] "
                f"{name}, "
                f"{destination_country} "
                f"source={source}, "
                f"requested={requested_countries}"
            )
            return
    
        # =====================================================
        # CONTINENT FILTER
        # =====================================================
    
        if not destination_matches_continent(
            dest,
            continent,
        ):
            debug_counts[
                "continent_skip"
            ] += 1
    
            print(
                f"[RECOMMENDER CONTINENT SKIP] "
                f"{name}, "
                f"{destination_country} "
                f"source={source}, "
                f"continent={continent}"
            )
            return
    
        # =====================================================
        # BUDGET FILTER
        # =====================================================
    
        effective_soft_budget = (
            budget
            * DISCOVERY_BUDGET_MULTIPLIER
            if source == "discovery"
            and budget > 0
            else soft_budget
        )
    
        if not destination_matches_budget(
            dest,
            budget,
            effective_soft_budget,
        ):
            debug_counts[
                "budget_skip"
            ] += 1
    
            cost = safe_float(
                getattr(
                    dest,
                    "avg_cost_per_day",
                    None,
                ),
                default=999999,
            )
    
            print(
                f"[RECOMMENDER BUDGET SKIP] "
                f"{name}, "
                f"{destination_country} "
                f"source={source}, "
                f"cost={cost}, "
                f"soft_budget={effective_soft_budget}"
            )
            return
    
        # =====================================================
        # DUPLICATE FILTER
        # =====================================================
    
        key = (
            normalize_key(name),
            normalize_key(
                destination_country
            ),
        )
    
        if key in seen:
            debug_counts[
                "duplicate_skip"
            ] += 1
            return
    
        seen.add(key)
    
        # =====================================================
        # FALLBACK PRICE ESTIMATION
        # Prevent random values such as:
        # Italy -> 107 EUR/day
        # Village -> 35 EUR/day
        # =====================================================
    
        try:
            current_cost = safe_float(
                getattr(
                    dest,
                    "avg_cost_per_day",
                    None,
                ),
                default=0,
            )
    
            if current_cost <= 0:
    
                if budget > 0:
                    estimated_cost = round(
                        budget * 0.85,
                        0,
                    )
                else:
                    estimated_cost = 90
    
                dest.avg_cost_per_day = (
                    estimated_cost
                )
    
        except Exception:
            pass
    
        # =====================================================
        # ATTACH AI INTELLIGENCE
        # =====================================================
    
        dest = attach_destination_intelligence(
            dest=dest,
            user_text=enriched_user_text,
            budget=budget,
        )
    
        # =====================================================
        # FINAL ADD
        # =====================================================
    
        final_results.append(
            dest
        )
    
        if debug_counts["added"] <= 20:
            print(
                f"[RECOMMENDER ADD] "
                f"{name}, "
                f"{destination_country}, "
                f"cost={getattr(dest, 'avg_cost_per_day', '?')}, "
                f"ai_score={getattr(dest, 'travel_dna_match', '?')}"
            )
        
    
    # -----------------------------------
    # Discovery phase
    # -----------------------------------
        
    try:
        discovered = discover_places(
            user_text=enriched_user_text,
            month=month,
            budget=budget,
            travelers=travelers,
            continent=continent,
            country=country,
            limit=min(limit, 40),
            force_fresh=True,
        ) or []
    
        print(
            f"[RECOMMENDER] Discovered "
            f"{len(discovered)} destinations"
        )
    
        for d in discovered:
            add_destination(
                d,
                source="discovery",
            )
    
    except Exception as e:
        print(
            f"[RECOMMENDER DISCOVERY ERROR] {e}"
        )
    
        discovered = []    


    # -----------------------------------
    # Database fallback phase
    # -----------------------------------
    
    try:
    
        db = SessionLocal()
    
        database_results = get_database_fallback_results(
            db=db,
            budget=budget,
            soft_budget=soft_budget,
            requested_countries=requested_countries,
            continent=continent,
            limit=limit,
        )
    
        print(
            f"[RECOMMENDER DATABASE] "
            f"{len(database_results)} destinations"
        )
    
        for d in database_results:
            add_destination(
                d,
                source="database",
            )
    
    except Exception as e:
    
        print(
            f"[RECOMMENDER DATABASE ERROR] {e}"
        )
    
    finally:
    
        try:
            db.close()
        except Exception:
            pass
            
    
    # -----------------------------------
    # Ranking phase
    # -----------------------------------
    
    try:
    
        final_results = (
            rank_destinations(
                destinations=final_results,
                user_budget=budget,
                continent=continent,
                user_text=enriched_user_text,
            )
            or final_results
        )
    
    except Exception as e:
    
        print(
            f"[RANKING ERROR] {e}"
        )
    
        final_results = sorted(
            final_results,
            key=destination_sort_key,
            reverse=True,
        )
    
    final_results = final_results[:limit]
    
    # ==========================================
    # Attach images only to final winners
    # ==========================================
    
    if include_images:
    
        print(
            "\n[IMAGE ENRICHMENT] "
            f"Loading images for "
            f"{len(final_results)} results"
        )
    
        for dest in final_results:
    
            try:
    
                image_data = (
                    get_image_for_destination(
                        dest
                    )
                    or {}
                )
    
                dest.image_url = image_data.get(
                    "image_url",
                    "",
                )
    
                dest.thumbnail_url = image_data.get(
                    "thumbnail",
                    "",
                )
    
                dest.image_provider = image_data.get(
                    "provider",
                    "",
                )
    
                dest.image_score = image_data.get(
                    "score",
                    0,
                )
    
            except Exception as e:
    
                print(
                    "[IMAGE ATTACH ERROR] "
                    f"{getattr(dest,'name','?')}: "
                    f"{e}"
                )
    
    print("\n==============================")
    print("[FINAL RESULTS]")
    print("==============================")
    print(f"Returned: {len(final_results)}")
    print(f"Added: {debug_counts['added']}")
    print(f"Duplicates: {debug_counts['duplicate_skip']}")
    print(f"Low quality: {debug_counts['low_quality_skip']}")
    print(f"Country skipped: {debug_counts['country_skip']}")
    print(f"Continent skipped: {debug_counts['continent_skip']}")
    print(f"Budget skipped: {debug_counts['budget_skip']}")
    print("==============================\n")
    
    return final_results