# -*- coding: utf-8 -*-

import hashlib


ADMIN_NAME_WORDS = [
    "municipal unit",
    "municipality",
    "regional unit",
    "district",
    "administration",
    "department",
    "province",
    "prefecture",
    "county",
    "state",
    "region of",
    "community",
    "commune",
]

GENERIC_BAD_NAMES = [
    "park",
    "road",
    "street",
    "area",
    "beach",
    "hotel",
    "restaurant",
    "cafe",
    "bar",
    "museum",
    "airport",
    "station",
    "center",
    "centre",
    "place",
    "locality",
    "unnamed",
]

STRONG_PLACE_WORDS = [
    "city",
    "town",
    "village",
    "island",
    "old town",
    "harbour",
    "harbor",
    "port",
    "lake",
    "mountain",
    "bay",
    "cape",
    "valley",
]


def _safe_text(value, default="N/A") -> str:
    value = str(value or "").strip()
    return value if value else default


def _normalize(value) -> str:
    return str(value or "").lower().strip()


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


def _get(dest, attr, default=None):
    try:
        return getattr(dest, attr, default)
    except Exception:
        return default


def _format_cost(value) -> str:
    cost = _safe_float(value, 0)

    if cost <= 0 or cost >= 999999:
        return "Unknown"

    return f"{round(cost)} EUR/day"


def _score_label(score) -> str:
    score = _safe_float(score, 0)

    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Very good"
    if score >= 55:
        return "Good"
    if score >= 40:
        return "Average"

    return "Weak"


def _stable_variation(name: str, country: str, scale: float = 3.5) -> float:
    key = f"{name}|{country}".encode("utf-8")
    digest = hashlib.md5(key).hexdigest()
    value = int(digest[:6], 16) % 1000
    return (value / 1000.0) * scale


def _is_admin_destination(name: str) -> bool:
    text = _normalize(name)
    return any(word in text for word in ADMIN_NAME_WORDS)


def _is_generic_bad_name(name: str) -> bool:
    text = _normalize(name)
    words = text.split()

    if not text:
        return True

    if text in GENERIC_BAD_NAMES:
        return True

    if len(words) <= 2 and any(word in GENERIC_BAD_NAMES for word in words):
        return True

    return False


def _destination_name_quality(name: str) -> float:
    text = _normalize(name)

    if not text:
        return -25

    score = 0

    if _is_generic_bad_name(text):
        score -= 28

    if _is_admin_destination(text):
        score -= 18

    if any(word in text for word in STRONG_PLACE_WORDS):
        score += 5

    word_count = len(text.split())

    if 2 <= word_count <= 4:
        score += 4

    if word_count >= 6:
        score -= 6

    return score


def _clean_level(value, default="Medium") -> str:
    value = _safe_text(value, default)

    allowed = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "unknown": "Unknown",
    }

    return allowed.get(value.lower(), default)


def _clean_tourist_trap_risk(dest) -> str:
    name = _normalize(_get(dest, "name", ""))
    crowd = _clean_level(_get(dest, "crowd_level", "Medium"))
    hidden = _safe_float(_get(dest, "hidden_gem_score", 0), 0)
    raw = _clean_level(_get(dest, "tourist_trap_risk", "Medium"))

    if _is_generic_bad_name(name) or _is_admin_destination(name):
        return "Medium"

    if crowd == "Low" and hidden >= 65:
        return "Low"

    if crowd == "High" and hidden < 60:
        return "High"

    return raw if raw in ["Low", "Medium", "High"] else "Medium"


def _risk_level(item: dict) -> str:
    risk_flags = item.get("risk_flags", []) or []
    tourist_trap_risk = item.get("tourist_trap_risk", "Medium")

    if item.get("is_generic_bad_name"):
        return "High"

    if tourist_trap_risk == "High" or len(risk_flags) >= 3:
        return "High"

    if tourist_trap_risk == "Medium" or len(risk_flags) >= 1:
        return "Medium"

    return "Low"


def _budget_score(raw_cost: float) -> float:
    raw_cost = _safe_float(raw_cost, 0)

    if raw_cost <= 0 or raw_cost >= 999999:
        return 45

    if raw_cost <= 60:
        return 95
    if raw_cost <= 90:
        return 85
    if raw_cost <= 120:
        return 75
    if raw_cost <= 170:
        return 60

    return 45


def _risk_penalty(item: dict) -> float:
    penalty = 0

    if item.get("risk_level") == "High":
        penalty += 12
    elif item.get("risk_level") == "Medium":
        penalty += 5

    if item.get("tourist_trap_risk") == "High":
        penalty += 8

    if item.get("crowd_level") == "High":
        penalty += 5

    if item.get("walking_difficulty") == "High":
        penalty += 3

    if item.get("is_admin_destination"):
        penalty += 8

    if item.get("is_generic_bad_name"):
        penalty += 18

    return penalty


def _decision_score_from_item(item: dict) -> float:
    ai = _safe_float(item.get("ai_score"), 0)
    twin = _safe_float(item.get("travel_dna_match"), 0)
    hidden = _safe_float(item.get("hidden_gem_score"), 0)
    local = _safe_float(item.get("local_authenticity_score"), 0)
    budget = _budget_score(item.get("raw_cost", 0))
    name_quality = _destination_name_quality(item.get("name", ""))

    score = (
        ai * 0.32
        + twin * 0.22
        + hidden * 0.16
        + local * 0.12
        + budget * 0.10
        + name_quality
    )

    score -= _risk_penalty(item)
    score += _stable_variation(item.get("name", ""), item.get("country", ""))

    return round(max(0, min(100, score)), 1)


def _winner_by_decision(items: list):
    if not items:
        return None

    return sorted(
        items,
        key=lambda item: (
            item.get("decision_score", 0),
            not item.get("is_generic_bad_name"),
            not item.get("is_admin_destination"),
            item.get("travel_dna_match", 0),
            item.get("hidden_gem_score", 0),
            item.get("local_authenticity_score", 0),
            -item.get("raw_cost", 0) if item.get("raw_cost", 0) > 0 else 0,
        ),
        reverse=True,
    )[0]


def _winner_by_number(items: list, attr: str, higher_is_better=True):
    valid = []

    for item in items:
        value = _safe_float(item.get(attr), None)

        if value is not None:
            valid.append((item, value))

    if not valid:
        return None

    valid.sort(key=lambda pair: pair[1], reverse=higher_is_better)
    return valid[0][0]


def _build_avoid_if(dest, item: dict) -> str:
    existing = _safe_text(_get(dest, "avoid_if", ""), "")

    if existing:
        return existing

    if item.get("is_generic_bad_name"):
        return "you want a precise, named travel destination instead of a generic place"

    if item.get("is_admin_destination"):
        return "you want a specific named resort, island, town, or old town"

    if item.get("tourist_trap_risk") == "High":
        return "you dislike tourist-heavy areas"

    if item.get("walking_difficulty") == "High":
        return "you want minimal walking or very easy routes"

    if item.get("crowd_level") == "High":
        return "you strongly prefer quiet places"

    return "you want only famous mainstream destinations"


def _build_ai_tip(dest, item: dict) -> str:
    existing = _safe_text(_get(dest, "ai_tip", ""), "")

    if existing:
        return existing

    if item.get("is_generic_bad_name"):
        return "Refine this result into a real nearby town, beach area, old town, village, or attraction cluster before booking."

    if item.get("is_admin_destination"):
        return "Use this as a wider base, then refine the itinerary into nearby towns, villages, sights, and food stops."

    if item.get("hidden_gem_score", 0) >= 75:
        return "Keep one flexible day for nearby villages, viewpoints, and local food discoveries."

    if item.get("crowd_level") == "High":
        return "Visit the busiest sights early morning or late afternoon."

    return "Group nearby places by distance to avoid wasting time between stops."


def _build_comparison_reason(item: dict) -> str:
    strengths = []

    if item.get("travel_dna_match", 0) >= 75:
        strengths.append("strong AI Trip Twin match")

    if item.get("hidden_gem_score", 0) >= 70:
        strengths.append("high hidden-gem potential")

    if item.get("local_authenticity_score", 0) >= 70:
        strengths.append("authentic local feel")

    if item.get("raw_cost", 0) > 0 and item.get("raw_cost", 0) <= 90:
        strengths.append("good budget value")

    if item.get("crowd_level") == "Low":
        strengths.append("lower crowd pressure")

    if not strengths:
        return "balanced overall profile"

    return ", ".join(strengths)


def build_destination_comparison(destinations: list) -> dict:
    destinations = [d for d in destinations if d]

    if not destinations:
        return {
            "items": [],
            "winner": None,
            "summary": "No destinations selected for comparison.",
        }

    items = []

    for dest in destinations:
        name = _safe_text(_get(dest, "name", ""))
        country = _safe_text(_get(dest, "country", ""))

        ai_score = _safe_float(_get(dest, "ai_score", 0), 0)
        twin_score = _safe_float(_get(dest, "travel_dna_match", 0), 0)
        hidden_score = _safe_float(_get(dest, "hidden_gem_score", 0), 0)
        local_score = _safe_float(_get(dest, "local_authenticity_score", 0), 0)
        raw_cost = _safe_float(_get(dest, "avg_cost_per_day", 0), 0)

        tourist_trap_risk = _clean_tourist_trap_risk(dest)

        item = {
            "id": _get(dest, "id", None),
            "name": name,
            "country": country,
            "continent": _safe_text(_get(dest, "continent", "")),
            "description": _safe_text(_get(dest, "description", ""), ""),

            "avg_cost_per_day": _format_cost(raw_cost),
            "raw_cost": raw_cost,

            "ai_score": round(ai_score, 1),
            "ai_score_label": _score_label(ai_score),

            "travel_dna_match": _safe_int(twin_score),
            "travel_dna_label": _score_label(twin_score),

            "hidden_gem_score": _safe_int(hidden_score),
            "local_authenticity_score": _safe_int(local_score),

            "crowd_level": _clean_level(_get(dest, "crowd_level", "Medium")),
            "budget_realism": _safe_text(_get(dest, "budget_realism", "Unknown")),
            "walking_difficulty": _clean_level(_get(dest, "walking_difficulty", "Medium")),
            "tourist_trap_risk": tourist_trap_risk,

            "trip_mood": _safe_text(_get(dest, "trip_mood", "Balanced")),
            "daily_energy_level": _safe_text(_get(dest, "daily_energy_level", "Balanced")),
            "trip_twin_label": _safe_text(_get(dest, "trip_twin_label", "Balanced Twin")),

            "best_for": _safe_text(_get(dest, "best_for", ""), ""),
            "smart_timing_tip": _safe_text(_get(dest, "smart_timing_tip", ""), ""),
            "budget_reality_check": _safe_text(_get(dest, "budget_reality_check", ""), ""),

            "risk_flags": _get(dest, "risk_flags", []) or [],
            "regret_predictor": _get(dest, "regret_predictor", []) or [],

            "is_admin_destination": _is_admin_destination(name),
            "is_generic_bad_name": _is_generic_bad_name(name),
            "destination_quality_penalty": _destination_name_quality(name),
        }

        item["risk_level"] = _risk_level(item)
        item["avoid_if"] = _build_avoid_if(dest, item)
        item["ai_tip"] = _build_ai_tip(dest, item)
        item["decision_score"] = _decision_score_from_item(item)
        item["decision_score_label"] = _score_label(item["decision_score"])
        item["comparison_reason"] = _build_comparison_reason(item)

        items.append(item)

    items.sort(
        key=lambda item: (
            item.get("decision_score", 0),
            not item.get("is_generic_bad_name"),
            not item.get("is_admin_destination"),
            item.get("travel_dna_match", 0),
            item.get("hidden_gem_score", 0),
            item.get("local_authenticity_score", 0),
            -item.get("raw_cost", 0) if item.get("raw_cost", 0) > 0 else 0,
        ),
        reverse=True,
    )

    best_overall = _winner_by_decision(items)
    best_twin = _winner_by_number(items, "travel_dna_match", True)
    best_hidden = _winner_by_number(items, "hidden_gem_score", True)
    best_local = _winner_by_number(items, "local_authenticity_score", True)

    cost_items = [item for item in items if item.get("raw_cost", 0) > 0]
    cheapest = _winner_by_number(cost_items, "raw_cost", False) if cost_items else None

    winner = {
        "best_overall": best_overall["name"] if best_overall else None,
        "best_overall_country": best_overall["country"] if best_overall else None,
        "best_overall_score": best_overall["decision_score"] if best_overall else None,
        "best_trip_twin": best_twin["name"] if best_twin else None,
        "best_hidden_gem": best_hidden["name"] if best_hidden else None,
        "most_local": best_local["name"] if best_local else None,
        "cheapest": cheapest["name"] if cheapest else None,
    }

    return {
        "items": items,
        "winner": winner,
        "summary": build_comparison_summary(items, winner),
    }


def build_comparison_summary(items: list, winner: dict) -> str:
    if not items:
        return "No comparison available."

    winner = winner or {}

    best = winner.get("best_overall")
    best_score = winner.get("best_overall_score")
    twin = winner.get("best_trip_twin")
    hidden = winner.get("best_hidden_gem")
    cheapest = winner.get("cheapest")

    parts = []

    if best:
        parts.append(
            f"{best} is the strongest overall choice with a final decision score of {best_score} / 100."
        )

    if twin and twin != best:
        parts.append(f"{twin} is the closest AI Trip Twin match.")

    if hidden and hidden not in [best, twin]:
        parts.append(f"{hidden} has the strongest hidden-gem potential.")

    if cheapest and cheapest not in [best, twin, hidden]:
        parts.append(f"{cheapest} is the most budget-friendly option.")

    generic_count = sum(1 for item in items if item.get("is_generic_bad_name"))
    admin_count = sum(1 for item in items if item.get("is_admin_destination"))

    if generic_count:
        parts.append(
            "Some options are too generic, so they should be refined into real named towns, beaches, old towns, villages, or attraction clusters."
        )

    if admin_count:
        parts.append(
            "Some options are broad administrative areas, so they should be refined before final booking."
        )

    return " ".join(parts) if parts else (
        "The selected destinations are close matches, so the final choice depends on pace, budget, walking level, and crowd tolerance."
    )


def compare_two_destinations(dest_a, dest_b) -> dict:
    comparison = build_destination_comparison([dest_a, dest_b])
    items = comparison.get("items", [])

    if len(items) < 2:
        return comparison

    a, b = items[0], items[1]
    verdicts = []

    if a["decision_score"] > b["decision_score"]:
        verdicts.append(f"{a['name']} is the better overall decision.")
    elif b["decision_score"] > a["decision_score"]:
        verdicts.append(f"{b['name']} is the better overall decision.")
    else:
        verdicts.append("Both destinations are almost equal overall.")

    if a["travel_dna_match"] > b["travel_dna_match"]:
        verdicts.append(f"{a['name']} fits your AI Trip Twin better.")
    elif b["travel_dna_match"] > a["travel_dna_match"]:
        verdicts.append(f"{b['name']} fits your AI Trip Twin better.")

    if a["raw_cost"] and b["raw_cost"]:
        if a["raw_cost"] < b["raw_cost"]:
            verdicts.append(f"{a['name']} is more budget-friendly.")
        elif b["raw_cost"] < a["raw_cost"]:
            verdicts.append(f"{b['name']} is more budget-friendly.")

    if a["tourist_trap_risk"] != b["tourist_trap_risk"]:
        risk_order = {"Low": 0, "Medium": 1, "High": 2}
        safer = (
            a
            if risk_order.get(a["tourist_trap_risk"], 1)
            < risk_order.get(b["tourist_trap_risk"], 1)
            else b
        )
        verdicts.append(f"{safer['name']} has lower tourist-trap risk.")

    comparison["quick_verdict"] = " ".join(verdicts)

    return comparison