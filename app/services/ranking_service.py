# -*- coding: utf-8 -*-

import re
import hashlib


ADMIN_PLACE_TYPES = {
    "region", "county", "state", "municipality", "district",
    "province", "administrative",
}

WEAK_PLACE_TYPES = {
    "postcode", "street", "building", "house", "amenity", "address",
}

STRONG_PLACE_TYPES = {
    "city", "town", "village", "island", "locality",
    "suburb", "hamlet", "place", "resort",
}

WEAK_NAME_WORDS = [
    "administration", "regional unit", "municipal unit",
    "municipality of", "district", "postcode", "street",
    "department of", "province", "prefecture", "county",
    "state", "region of",
]

GENERIC_BAD_NAMES = {
    "park", "beach", "road", "street", "hotel", "restaurant",
    "cafe", "bar", "airport", "station", "center", "centre",
    "place", "area", "locality", "unnamed",
}


def _normalize_text(value: str) -> str:
    return str(value or "").lower().strip()


def _text_contains_any(text: str, words: list[str]) -> bool:
    text = _normalize_text(text)
    return any(str(word).lower() in text for word in words)


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def _extract_ui_value(user_text: str, label: str, default: str = "") -> str:
    pattern = rf"{re.escape(label)}\s*:\s*([^\n\.]+)"
    match = re.search(pattern, user_text or "", flags=re.IGNORECASE)
    return match.group(1).strip() if match else default


def _stable_variation(*values, scale: float = 2.5) -> float:
    key = "|".join(str(value or "") for value in values).encode("utf-8")
    digest = hashlib.md5(key).hexdigest()
    value = int(digest[:6], 16) % 1000
    return (value / 1000.0) * scale


def _unique_reasons(reasons: list[str], limit: int = 7) -> list[str]:
    clean = []
    seen = set()

    for reason in reasons:
        reason = str(reason or "").strip()
        key = _normalize_text(reason)

        if not key or key in seen:
            continue

        seen.add(key)
        clean.append(reason)

        if len(clean) >= limit:
            break

    return clean


def _is_generic_bad_name(destination_name: str) -> bool:
    text = _normalize_text(destination_name)
    words = text.split()

    if not text:
        return True

    if text in GENERIC_BAD_NAMES:
        return True

    if len(words) <= 2 and any(word in GENERIC_BAD_NAMES for word in words):
        return True

    return False


def _is_admin_name(destination_name: str) -> bool:
    text = _normalize_text(destination_name)
    return _text_contains_any(text, WEAK_NAME_WORDS)


def _destination_quality_score(destination_name: str, country: str, place_type: str):
    score = 0
    reasons = []

    name = _normalize_text(destination_name)
    country_key = _normalize_text(country)
    place_type_key = _normalize_text(place_type)

    if not name:
        return -40, ["missing destination name"]

    if _is_generic_bad_name(name):
        score -= 35
        reasons.append("generic destination name")

    if _is_admin_name(name):
        score -= 22
        reasons.append("broad administrative result")

    if country_key and name == country_key:
        score -= 18
        reasons.append("broad country-level result")

    if place_type_key in WEAK_PLACE_TYPES:
        score -= 30
        reasons.append("weak destination type")
    elif place_type_key in ADMIN_PLACE_TYPES:
        score -= 12
        reasons.append("broad area, needs itinerary refinement")
    elif place_type_key in STRONG_PLACE_TYPES:
        score += 12
        reasons.append(f"valid destination type: {place_type}")
    else:
        score += 3
        reasons.append("possible travel area")

    word_count = len(name.split())

    if word_count <= 3:
        score += 5

    if word_count >= 6:
        score -= 6
        reasons.append("less specific travel destination")

    return score, reasons


def _estimate_crowd_level(destination_name, user_text, place_type, nearby_count):
    text = _normalize_text(f"{destination_name} {user_text} {place_type}")

    quiet_words = [
        "village", "hidden", "underrated", "quiet", "peaceful",
        "nature", "mountain", "local", "authentic", "remote",
        "slow", "calm", "traditional", "rural", "hamlet",
    ]

    popular_words = [
        "capital", "city center", "old town", "resort", "famous",
        "popular", "party", "nightlife", "tourist", "main beach",
        "downtown", "central", "cruise", "port", "landmark",
    ]

    if _text_contains_any(text, quiet_words) and nearby_count < 18:
        return "Low"

    if _text_contains_any(text, popular_words) or nearby_count >= 24:
        return "High"

    return "Medium"


def _estimate_hidden_gem_score(destination_name, user_text, place_type, nearby_count):
    text = _normalize_text(f"{destination_name} {user_text} {place_type}")
    place_type = _normalize_text(place_type)

    score = 45

    if _text_contains_any(text, ["hidden", "underrated", "authentic", "local", "village", "nature", "remote"]):
        score += 30

    if _text_contains_any(text, ["quiet", "peaceful", "traditional", "slow", "non touristy", "non-touristy", "local food"]):
        score += 15

    if _text_contains_any(text, ["capital", "famous", "popular", "resort", "party", "tourist", "downtown"]):
        score -= 20

    if place_type in ["village", "island", "town", "locality", "place", "hamlet"]:
        score += 15

    if place_type in ADMIN_PLACE_TYPES:
        score -= 12

    if nearby_count >= 24:
        score -= 10
    elif nearby_count <= 5:
        score += 10

    return max(0, min(100, score))


def _estimate_local_authenticity_score(destination_name, user_text, place_type):
    text = _normalize_text(f"{destination_name} {user_text} {place_type}")
    score = 50

    if _text_contains_any(text, ["local", "authentic", "traditional", "village", "market", "old town", "culture"]):
        score += 25

    if _text_contains_any(text, ["food", "cafe", "restaurant", "history", "museum", "walking"]):
        score += 12

    if _text_contains_any(text, ["resort", "airport", "downtown", "tourist trap", "party"]):
        score -= 15

    if _normalize_text(place_type) in ADMIN_PLACE_TYPES:
        score -= 8

    return max(0, min(100, score))


def _estimate_walking_difficulty(destination_name, user_text, place_type):
    text = _normalize_text(f"{destination_name} {user_text} {place_type}")

    if _text_contains_any(text, ["mountain", "hiking", "trail", "cliff", "steep", "viewpoint"]):
        return "High"

    if _text_contains_any(text, ["old town", "walking", "village", "nature", "historic"]):
        return "Medium"

    if _text_contains_any(text, ["beach", "resort", "relax", "hotel", "cafe", "minimal walking"]):
        return "Low"

    return "Medium"


def _estimate_tourist_trap_risk(destination_name, user_text, place_type, crowd_level):
    text = _normalize_text(f"{destination_name} {user_text} {place_type}")

    if crowd_level == "High" and _text_contains_any(
        text,
        ["popular", "famous", "resort", "tourist", "downtown", "main beach", "cruise"],
    ):
        return "High"

    if _text_contains_any(text, ["hidden", "underrated", "authentic", "local", "village", "quiet"]):
        return "Low"

    return "Medium"


def _budget_realism_label(budget, estimated_cost):
    budget = _safe_float(budget, 0)
    estimated_cost = _safe_float(estimated_cost, 999999)

    if budget <= 0:
        return "Flexible"

    if estimated_cost <= 0 or estimated_cost >= 999999:
        return "Unknown"

    if estimated_cost <= budget * 0.85:
        return "Very realistic"

    if estimated_cost <= budget:
        return "Realistic"

    if estimated_cost <= budget * 1.25:
        return "Tight"

    return "Risky"


def _estimate_daily_energy_level(trip_pace, walking_difficulty, nearby_count, user_text):
    text = _normalize_text(user_text)
    trip_pace = _normalize_text(trip_pace)

    if "minimal walking" in trip_pace:
        return "Easy"

    if "full schedule" in trip_pace:
        return "Intense"

    if walking_difficulty == "High":
        return "Intense"

    if _text_contains_any(text, ["relax", "slow", "easy", "peaceful", "beach", "cafe"]):
        return "Easy"

    return "Balanced"


def _estimate_trip_mood(user_text, travelers, crowd_level, hidden_gem_score, local_authenticity_score, tourist_trap_risk):
    text = _normalize_text(f"{user_text} {travelers}")
    moods = []

    if _text_contains_any(text, ["romantic", "couple", "sunset", "cozy"]):
        moods.append("romantic")

    if _text_contains_any(text, ["relax", "slow", "peaceful", "quiet", "beach"]):
        moods.append("relaxed")

    if _text_contains_any(text, ["culture", "history", "museum", "old town", "architecture"]):
        moods.append("cultural")

    if _text_contains_any(text, ["food", "restaurant", "cafe", "wine", "local food"]):
        moods.append("food-focused")

    if _text_contains_any(text, ["hiking", "nature", "mountain", "adventure", "walking"]):
        moods.append("exploratory")

    if hidden_gem_score >= 70:
        moods.append("hidden-gem")

    if local_authenticity_score >= 70:
        moods.append("authentic")

    if crowd_level == "High":
        moods.append("lively")

    if tourist_trap_risk == "High":
        moods.append("touristy")

    if not moods:
        moods = ["balanced", "practical"]

    return ", ".join(moods[:4]).title()


def _budget_reality_check(budget, estimated_cost):
    budget = _safe_float(budget, 0)
    estimated_cost = _safe_float(estimated_cost, 999999)

    if budget <= 0:
        return "Flexible budget: no strict daily limit was applied."

    if estimated_cost <= 0 or estimated_cost >= 999999:
        return "Budget estimate is limited, so keep some flexibility."

    difference = estimated_cost - budget

    if estimated_cost <= budget * 0.85:
        return "Comfortable: you should have room for food, cafes, and extras."

    if estimated_cost <= budget:
        return "Realistic: this should fit your daily budget."

    if estimated_cost <= budget * 1.25:
        return f"Tight: you may need about +{round(difference)} EUR/day."

    return f"Risky: you may need about +{round(difference)} EUR/day or a cheaper plan."


def _regret_predictor(user_text, travelers, crowd_level, walking_difficulty, tourist_trap_risk, nearby_count, budget_realism):
    text = _normalize_text(f"{user_text} {travelers}")
    regrets = []

    if crowd_level == "High" and _text_contains_any(text, ["quiet", "peaceful", "relax", "avoid crowds"]):
        regrets.append("You may regret this if you strongly dislike crowds.")

    if walking_difficulty == "High" and _text_contains_any(text, ["minimal walking", "easy", "relax"]):
        regrets.append("You may regret this if you want very low walking effort.")

    if tourist_trap_risk == "High" and _text_contains_any(text, ["authentic", "local", "hidden", "non touristy", "non-touristy"]):
        regrets.append("You may regret this if you want a very local, non-touristy feeling.")

    if nearby_count < 4 and _text_contains_any(text, ["nightlife", "bars", "restaurants", "activities", "full schedule"]):
        regrets.append("You may regret this if you need many activity and nightlife options.")

    if budget_realism == "Risky":
        regrets.append("You may regret this if your daily budget is strict.")

    if not regrets:
        regrets.append("Low regret risk based on your current preferences.")

    return regrets[:3]


def _smart_timing_tip(crowd_level, trip_pace, user_text, nearby_count):
    text = _normalize_text(user_text)
    trip_pace = _normalize_text(trip_pace)

    if crowd_level == "High":
        return "Start early, keep lunch flexible, and avoid the busiest central areas in the evening."

    if "slow" in trip_pace or _text_contains_any(text, ["relax", "peaceful", "quiet"]):
        return "Plan one main activity per day and leave late afternoons open for cafes, sunsets, or walks."

    if "full schedule" in trip_pace or nearby_count >= 15:
        return "Group nearby places together and use mornings for sights, afternoons for food or local walks."

    return "Keep the first day light, then adjust the pace based on transport time and energy."


def _trip_twin_label(travel_dna_match, hidden_gem_score, budget_realism, crowd_level):
    if travel_dna_match >= 85:
        return "Strong Trip Twin"

    if hidden_gem_score >= 75 and crowd_level == "Low":
        return "Hidden-Gem Twin"

    if budget_realism in ["Very realistic", "Realistic"]:
        return "Budget-Smart Twin"

    if crowd_level == "Low":
        return "Quiet Twin"

    return "Balanced Twin"


def _estimate_trip_twin_match(
    user_text,
    travelers,
    destination_name,
    place_type,
    crowd_level,
    hidden_gem_score,
    budget_realism,
    nearby_count,
):
    score = 50
    text = _normalize_text(f"{user_text} {travelers} {destination_name} {place_type}")

    travel_dna = _normalize_text(_extract_ui_value(user_text, "AI Travel DNA", "Balanced"))
    crowd_strategy = _normalize_text(_extract_ui_value(user_text, "Crowd Strategy", "Normal"))
    trip_pace = _normalize_text(_extract_ui_value(user_text, "Trip Pace", "Balanced"))
    discovery_mode = _normalize_text(_extract_ui_value(user_text, "Discovery Mode", "Best Match"))

    if "romantic" in travel_dna and _text_contains_any(text, ["romantic", "couple", "sunset", "sea", "cozy"]):
        score += 18

    if "hidden" in travel_dna and hidden_gem_score >= 60:
        score += 18

    if "luxury" in travel_dna and _text_contains_any(text, ["luxury", "boutique", "resort", "spa", "relax"]):
        score += 15

    if ("food" in travel_dna or "culture" in travel_dna) and _text_contains_any(
        text, ["food", "restaurant", "cafe", "culture", "museum", "history", "old town"]
    ):
        score += 15

    if "nature" in travel_dna and _text_contains_any(text, ["nature", "mountain", "hiking", "lake", "forest", "view"]):
        score += 15

    if "avoid crowds" in crowd_strategy and crowd_level == "Low":
        score += 12

    if "only quiet" in crowd_strategy and crowd_level == "Low":
        score += 15

    if "popular but smart" in crowd_strategy and nearby_count >= 8:
        score += 8

    if "slow" in trip_pace and _text_contains_any(text, ["relax", "quiet", "walking", "cafe", "beach"]):
        score += 10

    if "full schedule" in trip_pace and nearby_count >= 10:
        score += 10

    if "minimal walking" in trip_pace and _text_contains_any(text, ["beach", "resort", "hotel", "relax"]):
        score += 8

    if "underrated" in discovery_mode and hidden_gem_score >= 60:
        score += 12

    if "budget maximizer" in discovery_mode and budget_realism in ["Very realistic", "Realistic"]:
        score += 12

    if "best match" in discovery_mode:
        score += 5

    return max(0, min(100, score))


def _risk_flags(
    budget,
    estimated_cost,
    crowd_level,
    nearby_count,
    place_type,
    user_text,
    walking_difficulty,
    tourist_trap_risk,
):
    risks = []
    text = _normalize_text(user_text)
    place_type = _normalize_text(place_type)

    if budget > 0 and estimated_cost > budget * 1.25:
        risks.append("Budget may be too tight")

    if crowd_level == "High" and _text_contains_any(text, ["quiet", "relax", "peaceful", "avoid crowds"]):
        risks.append("May feel too busy")

    if nearby_count < 3:
        risks.append("Limited nearby travel data")

    if place_type in ADMIN_PLACE_TYPES:
        risks.append("Broad area, itinerary may need refinement")

    if _text_contains_any(text, ["nightlife", "bars", "party"]) and nearby_count < 6:
        risks.append("Nightlife options may be limited")

    if walking_difficulty == "High" and _text_contains_any(text, ["minimal walking", "relax", "easy"]):
        risks.append("May require more walking than preferred")

    if tourist_trap_risk == "High":
        risks.append("Higher tourist-trap risk")

    return risks[:4]


def calculate_destination_score(
    destination_name: str,
    country: str,
    continent: str,
    selected_continent: str,
    budget: float,
    estimated_cost: float,
    user_text: str = "",
    travelers: str = "",
    place_type: str = "place",
    nearby_count: int = 0,
):
    score = 8
    reasons = []

    budget = _safe_float(budget, 0)
    estimated_cost = _safe_float(estimated_cost, 999999)
    nearby_count = _safe_int(nearby_count, 0)

    continent_key = _normalize_text(continent)
    selected_continent_key = _normalize_text(selected_continent)
    place_type_key = _normalize_text(place_type)

    text = _normalize_text(
        f"{user_text or ''} {travelers or ''} {place_type or ''} {destination_name or ''}"
    )

    travel_dna = _normalize_text(_extract_ui_value(user_text, "AI Travel DNA", "Balanced"))
    crowd_strategy = _normalize_text(_extract_ui_value(user_text, "Crowd Strategy", "Normal"))
    trip_pace = _normalize_text(_extract_ui_value(user_text, "Trip Pace", "Balanced"))
    discovery_mode = _normalize_text(_extract_ui_value(user_text, "Discovery Mode", "Best Match"))

    quality_score, quality_reasons = _destination_quality_score(
        destination_name=destination_name,
        country=country,
        place_type=place_type_key,
    )

    score += quality_score
    reasons.extend(quality_reasons)

    crowd_level = _estimate_crowd_level(destination_name, user_text, place_type_key, nearby_count)
    hidden_gem_score = _estimate_hidden_gem_score(destination_name, user_text, place_type_key, nearby_count)
    local_authenticity_score = _estimate_local_authenticity_score(destination_name, user_text, place_type_key)
    walking_difficulty = _estimate_walking_difficulty(destination_name, user_text, place_type_key)
    tourist_trap_risk = _estimate_tourist_trap_risk(destination_name, user_text, place_type_key, crowd_level)
    budget_realism = _budget_realism_label(budget, estimated_cost)

    travel_dna_match = _estimate_trip_twin_match(
        user_text=user_text,
        travelers=travelers,
        destination_name=destination_name,
        place_type=place_type_key,
        crowd_level=crowd_level,
        hidden_gem_score=hidden_gem_score,
        budget_realism=budget_realism,
        nearby_count=nearby_count,
    )

    daily_energy_level = _estimate_daily_energy_level(
        trip_pace=trip_pace,
        walking_difficulty=walking_difficulty,
        nearby_count=nearby_count,
        user_text=user_text,
    )

    trip_mood = _estimate_trip_mood(
        user_text=user_text,
        travelers=travelers,
        crowd_level=crowd_level,
        hidden_gem_score=hidden_gem_score,
        local_authenticity_score=local_authenticity_score,
        tourist_trap_risk=tourist_trap_risk,
    )

    budget_reality_check = _budget_reality_check(budget, estimated_cost)

    regret_predictor = _regret_predictor(
        user_text=user_text,
        travelers=travelers,
        crowd_level=crowd_level,
        walking_difficulty=walking_difficulty,
        tourist_trap_risk=tourist_trap_risk,
        nearby_count=nearby_count,
        budget_realism=budget_realism,
    )

    smart_timing_tip = _smart_timing_tip(
        crowd_level=crowd_level,
        trip_pace=trip_pace,
        user_text=user_text,
        nearby_count=nearby_count,
    )

    trip_twin_label = _trip_twin_label(
        travel_dna_match=travel_dna_match,
        hidden_gem_score=hidden_gem_score,
        budget_realism=budget_realism,
        crowd_level=crowd_level,
    )

    if budget <= 0:
        score += 12
        reasons.append("works with flexible budget")
    elif estimated_cost <= budget:
        score += 24
        reasons.append("fits your budget")
    elif estimated_cost <= budget * 1.15:
        score += 14
        reasons.append("slightly above budget")
    elif estimated_cost <= budget * 1.35:
        score += 6
        reasons.append("possible with careful spending")
    else:
        score -= 18
        reasons.append("over budget")

    if not selected_continent_key or selected_continent_key == "any":
        score += 18
        reasons.append("global search match")
    elif continent_key == selected_continent_key:
        score += 22
        reasons.append(f"matches {selected_continent}")
    else:
        score -= 35
        reasons.append("wrong continent")

    traveler_rules = {
        "couple": ("good for couples", ["romantic", "sunset", "sea", "views", "cozy", "relax"], 16, 6),
        "solo": ("good for solo travel", ["safe", "walk", "culture", "food", "cafes"], 14, 5),
        "family": ("family-friendly match", ["safe", "relax", "hotel", "nature", "walking"], 14, 5),
        "friends": ("good for friends", ["fun", "nightlife", "bars", "activities", "food"], 14, 5),
    }

    for traveler_key, rule in traveler_rules.items():
        reason, words, strong_points, weak_points = rule

        if traveler_key in text:
            score += strong_points if _text_contains_any(text, words) else weak_points
            reasons.append(reason)

    interest_groups = {
        "sea/beach": ["sea", "beach", "island", "coastal", "swim", "seaside", "sunset"],
        "food": ["food", "restaurant", "local food", "dinner", "wine", "cafe", "cafes"],
        "culture": ["culture", "museum", "history", "art", "old town", "historic", "architecture"],
        "nature": ["nature", "hiking", "mountain", "lake", "forest", "viewpoint", "walking"],
        "relaxation": ["relax", "quiet", "peaceful", "cozy", "calm", "slow"],
        "nightlife": ["nightlife", "bars", "club", "party", "evening"],
        "luxury": ["luxury", "boutique", "premium", "resort", "spa"],
        "budget value": ["cheap", "budget", "affordable", "value", "low cost"],
        "hidden gems": ["hidden", "underrated", "authentic", "local", "unique", "non touristy", "non-touristy"],
    }

    matched_interests = 0

    for label, words in interest_groups.items():
        if _text_contains_any(text, words):
            matched_interests += 1
            score += 5
            reasons.append(f"matches {label}")

    if matched_interests >= 4:
        score += 8
        reasons.append("strong multi-interest match")

    if "romantic" in travel_dna and _text_contains_any(text, ["romantic", "couple", "sunset", "sea", "cozy"]):
        score += 12
        reasons.append("matches romantic travel DNA")
    elif "hidden" in travel_dna and hidden_gem_score >= 60:
        score += 12
        reasons.append("matches hidden-gem travel DNA")
    elif "luxury" in travel_dna and _text_contains_any(text, ["luxury", "boutique", "resort", "spa", "sea views", "relaxing"]):
        score += 12
        reasons.append("matches luxury calm travel DNA")
    elif ("food" in travel_dna or "culture" in travel_dna) and _text_contains_any(
        text, ["food", "restaurant", "cafe", "culture", "museum", "old town", "history"]
    ):
        score += 12
        reasons.append("matches food and culture DNA")
    elif "nature" in travel_dna and _text_contains_any(text, ["nature", "mountain", "walking", "hiking", "view", "lake", "forest"]):
        score += 12
        reasons.append("matches nature escape DNA")
    elif "adventure" in travel_dna and _text_contains_any(text, ["activity", "hiking", "walking", "nature", "mountain", "coast"]):
        score += 10
        reasons.append("matches light adventure DNA")
    elif "balanced" in travel_dna:
        score += 6
        reasons.append("balanced travel match")

    if "avoid crowds" in crowd_strategy:
        if crowd_level == "Low":
            score += 14
            reasons.append("supports crowd avoidance")
        elif crowd_level == "High":
            score -= 8
            reasons.append("may be busier than preferred")

    elif "only quiet" in crowd_strategy:
        if crowd_level == "Low":
            score += 16
            reasons.append("quiet-place match")
        else:
            score -= 5
            reasons.append("not fully quiet")

    elif "popular but smart" in crowd_strategy:
        if nearby_count >= 8:
            score += 8
            reasons.append("enough options for smart timing")

    if "slow" in trip_pace:
        if _text_contains_any(text, ["relax", "quiet", "cozy", "walking", "cafes", "sea", "views"]):
            score += 10
            reasons.append("fits slow relaxed pace")

    elif "full schedule" in trip_pace:
        if nearby_count >= 10:
            score += 12
            reasons.append("supports full schedule")
        elif nearby_count < 3:
            score -= 5
            reasons.append("limited for full schedule")

    elif "minimal walking" in trip_pace:
        if _text_contains_any(text, ["hotel", "resort", "beach", "cafe", "relax"]):
            score += 8
            reasons.append("works for minimal walking")

    elif "balanced" in trip_pace:
        score += 5
        reasons.append("balanced pace match")

    if "surprise" in discovery_mode:
        score += 7
        reasons.append("surprise discovery candidate")

    elif "underrated" in discovery_mode:
        if hidden_gem_score >= 60:
            score += 14
            reasons.append("underrated-place potential")
        else:
            score += 4
            reasons.append("some underrated potential")

    elif "romantic hidden" in discovery_mode:
        if hidden_gem_score >= 55 and _text_contains_any(text, ["romantic", "sunset", "sea", "quiet", "village", "cozy"]):
            score += 14
            reasons.append("romantic hidden-gem potential")

    elif "budget maximizer" in discovery_mode:
        if budget > 0 and estimated_cost <= budget * 0.85:
            score += 14
            reasons.append("excellent budget value")
        elif budget > 0 and estimated_cost <= budget:
            score += 8
            reasons.append("good budget value")

    elif "best match" in discovery_mode:
        score += 5
        reasons.append("best-match candidate")

    if hidden_gem_score >= 75:
        score += 8
        reasons.append("high hidden-gem score")
    elif hidden_gem_score >= 60:
        score += 5
        reasons.append("good hidden-gem potential")

    if local_authenticity_score >= 75:
        score += 7
        reasons.append("high local authenticity")
    elif local_authenticity_score >= 60:
        score += 4
        reasons.append("good local authenticity")

    if travel_dna_match >= 80:
        score += 8
        reasons.append("excellent AI Trip Twin match")
    elif travel_dna_match >= 65:
        score += 5
        reasons.append("good AI Trip Twin match")

    if tourist_trap_risk == "Low":
        score += 5
        reasons.append("low tourist-trap risk")
    elif tourist_trap_risk == "High":
        score -= 6
        reasons.append("higher tourist-trap risk")

    if budget_realism == "Very realistic":
        score += 5
        reasons.append("very realistic budget")
    elif budget_realism == "Risky":
        score -= 6
        reasons.append("budget realism risk")

    if nearby_count >= 18:
        score += 18
        reasons.append("excellent nearby options")
    elif nearby_count >= 10:
        score += 15
        reasons.append("many nearby places found")
    elif nearby_count >= 5:
        score += 10
        reasons.append("good nearby options")
    elif nearby_count >= 1:
        score += 5
        reasons.append("some nearby options")
    else:
        score -= 4
        reasons.append("limited nearby data")

    score += _stable_variation(destination_name, country, place_type_key, scale=2.5)

    risk_flags = _risk_flags(
        budget=budget,
        estimated_cost=estimated_cost,
        crowd_level=crowd_level,
        nearby_count=nearby_count,
        place_type=place_type_key,
        user_text=user_text,
        walking_difficulty=walking_difficulty,
        tourist_trap_risk=tourist_trap_risk,
    )

    score = round(max(0, min(100, score)), 1)

    return {
        "score": score,
        "reasons": _unique_reasons(reasons, limit=7),
        "crowd_level": crowd_level,
        "hidden_gem_score": hidden_gem_score,
        "budget_realism": budget_realism,
        "risk_flags": risk_flags,
        "travel_dna_match": travel_dna_match,
        "local_authenticity_score": local_authenticity_score,
        "walking_difficulty": walking_difficulty,
        "tourist_trap_risk": tourist_trap_risk,
        "trip_mood": trip_mood,
        "daily_energy_level": daily_energy_level,
        "budget_reality_check": budget_reality_check,
        "regret_predictor": regret_predictor,
        "smart_timing_tip": smart_timing_tip,
        "trip_twin_label": trip_twin_label,
    }


def format_score_reason(reasons: list[str]) -> str:
    reasons = _unique_reasons(reasons, limit=4)

    if not reasons:
        return "Matched based on your preferences."

    negative_reasons = {
        "over budget",
        "wrong continent",
        "weak destination type",
        "limited nearby data",
        "less specific travel destination",
        "broad country-level result",
        "budget realism risk",
        "higher tourist-trap risk",
        "generic destination name",
        "broad administrative result",
        "broad area, needs itinerary refinement",
        "not fully quiet",
    }

    positive_reasons = [
        reason for reason in reasons
        if reason not in negative_reasons
    ]

    if not positive_reasons:
        positive_reasons = reasons

    return "Best because it " + ", ".join(positive_reasons[:4]) + "."