# -*- coding: utf-8 -*-

import random
import hashlib
from urllib.parse import quote

from sqlalchemy.orm import joinedload

from app.db.database import SessionLocal
from app.db.models import Destination, Season, Image
from app.services.geoapify_service import (
    geocode_location,
    search_places,
    get_categories_from_preferences,
)
from app.services.pexels_service import get_destination_image
from app.services.ranking_service import (
    calculate_destination_score,
    format_score_reason,
)
from app.services.restcountries_service import (
    get_countries_by_continent,
    get_country_continent,
    load_all_countries,
)


MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]

DEFAULT_RESULT_LIMIT = 25
MAX_COUNTRIES_PER_SEARCH = 8
MAX_QUERIES_PER_COUNTRY = 28
GEOAPIFY_GEOCODE_LIMIT = 40

NEARBY_LIMIT = 35
NEARBY_RADIUS = 90000
MIN_ACCEPTABLE_RESULTS = 10

BAD_PLACE_TYPES = {
    "postcode", "street", "building", "house",
    "address", "amenity",
}

ADMIN_PLACE_TYPES = {
    "county", "state", "region", "district",
    "municipality", "administrative",
}

GOOD_PLACE_TYPES = {
    "city",
    "town",
    "village",
    "island",
    "hamlet",
    "tourism",
    "attraction",
    "natural",
    "resort",
}

WEAK_TRAVEL_WORDS = {
    "regional unit", "municipal unit", "municipality",
    "province", "prefecture", "administration",
    "department", "district", "county", "state",
    "region of",
}

GENERIC_BAD_NAMES = {
    "park", "beach", "road", "street", "hotel",
    "restaurant", "cafe", "bar", "airport",
    "station", "center", "centre", "place",
    "area", "locality", "unnamed",
}

COUNTRY_ALIASES = {
    "greece": ["greece", "hellas", "ellada", "greek republic"],
    "bulgaria": ["bulgaria", "republic of bulgaria"],
    "cyprus": ["cyprus", "republic of cyprus", "northern cyprus"],
    "oman": ["oman", "sultanate of oman"],
    "bangladesh": ["bangladesh", "people's republic of bangladesh"],
    "french polynesia": ["french polynesia", "polynesie francaise"],
    "guam": ["guam"],
    "hong kong": [
        "hong kong",
        "hong kong sar",
        "hong kong s.a.r.",
        "hong kong special administrative region",
        "hong kong special administrative region of china",
    ],
    "united states": [
        "united states", "usa", "u.s.a.",
        "america", "united states of america",
    ],
    "united kingdom": [
        "united kingdom", "uk", "u.k.",
        "great britain", "britain", "england",
    ],
}


def clean_text(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split())


def normalize_key(value) -> str:
    return clean_text(value).lower()


def safe_string(value) -> str:
    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        return clean_text(" ".join(str(v) for v in value if v is not None))

    if isinstance(value, dict):
        return ""

    return clean_text(str(value))


def safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def stable_int(text: str, modulo: int) -> int:
    digest = hashlib.md5(str(text).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def normalize_continent(value: str) -> str:
    value = safe_string(value)

    mapping = {
        "europe": "Europe",
        "asia": "Asia",
        "africa": "Africa",
        "north america": "North America",
        "south america": "South America",
        "oceania": "Oceania",
        "antarctica": "Antarctica",
    }

    return mapping.get(normalize_key(value), value)


def is_generic_bad_name(name: str) -> bool:
    text = normalize_key(name)
    words = text.split()

    if not text:
        return True

    if text in GENERIC_BAD_NAMES:
        return True

    if len(words) <= 2 and any(w in GENERIC_BAD_NAMES for w in words):
        return True

    return False


def is_admin_name(name: str) -> bool:
    text = normalize_key(name)
    return any(w in text for w in WEAK_TRAVEL_WORDS)


def get_aliases(country_name: str) -> set:
    key = normalize_key(country_name)
    aliases = {key}

    if key in COUNTRY_ALIASES:
        aliases.update(COUNTRY_ALIASES[key])

    for canonical, values in COUNTRY_ALIASES.items():
        normalized_values = {normalize_key(v) for v in values}

        if key in normalized_values:
            aliases.add(canonical)
            aliases.update(normalized_values)

    return {normalize_key(a) for a in aliases if a}


def soft_country_match(found_country: str, requested_country: str) -> bool:
    found = normalize_key(found_country)
    requested = normalize_key(requested_country)

    if not found or not requested:
        return False

    if found == requested:
        return True

    if requested in found or found in requested:
        return True

    return bool(get_aliases(found).intersection(get_aliases(requested)))


def get_country_code(country_name: str = ""):
    if not country_name:
        return ""

    try:
        countries = load_all_countries()
    except Exception as e:
        print(f"[REST COUNTRIES ERROR] Could not load country code: {e}")
        return ""

    for country in countries:
        names = [
            country.get("name", ""),
            country.get("official_name", ""),
            country.get("common_name", ""),
        ]

        for name in names:
            if soft_country_match(name, country_name):
                return str(country.get("cca2") or "").lower()

    return ""


def extract_travel_intent(user_text: str, travelers: str = "") -> dict:
    text = normalize_key(f"{user_text or ''} {travelers or ''}")

    return {
        "romantic": any(w in text for w in ["romantic", "couple", "honeymoon"]),
        "sea": any(w in text for w in ["sea", "beach", "coast", "coastal", "island", "sunset", "seaside"]),
        "food": any(w in text for w in ["food", "restaurant", "local food", "dinner", "cafe", "wine"]),
        "culture": any(w in text for w in ["culture", "museum", "history", "art", "old town", "cultural"]),
        "nature": any(w in text for w in ["nature", "hiking", "mountain", "view", "views", "walking"]),
        "nightlife": any(w in text for w in ["nightlife", "club", "party", "bars"]),
        "relaxing": any(w in text for w in ["relaxing", "calm", "quiet", "safe", "cozy"]),
    }


def extract_requested_countries(user_text: str, continent: str = "Any"):
    text = normalize_key(user_text)

    if not text:
        return []

    all_countries = get_countries_by_continent("Any")

    if continent and continent != "Any":
        allowed_countries = set(get_countries_by_continent(continent))
    else:
        allowed_countries = set(all_countries)

    requested = []

    for canonical, aliases in COUNTRY_ALIASES.items():
        for alias in aliases:
            if normalize_key(alias) in text:
                for country in all_countries:
                    if soft_country_match(country, canonical) and country in allowed_countries:
                        requested.append(country)

    for country in all_countries:
        if normalize_key(country) in text and country in allowed_countries:
            requested.append(country)

    requested = list(dict.fromkeys(requested))

    if requested:
        print(f"[COUNTRY LOCK] User requested countries: {requested}")

    return requested


def get_country_pool(continent: str = "Any", user_text: str = "", country: str = "Any"):
    if country and country != "Any":
        print(f"[COUNTRY LOCK] Selected country dropdown: {country}")
        return [country]

    requested_countries = extract_requested_countries(user_text, continent)

    if requested_countries:
        print(f"[COUNTRY LOCK] Searching ONLY inside: {requested_countries}")
        return requested_countries

    countries = get_countries_by_continent(continent)
    random.shuffle(countries)

    return countries


def build_country_queries(country: str, intent: dict):
    queries = [
        f"{country} best travel destinations",
        f"{country} best cities to visit",
        f"{country} best towns to visit",
        f"{country} old towns",
        f"{country} coastal towns",
        f"{country} seaside villages",
        f"{country} islands",
        f"{country} beaches",
        f"{country} historic towns",
        f"{country} scenic towns",
        f"{country} romantic destinations",
        f"{country} honeymoon destinations",
        f"{country} underrated destinations",
        f"{country} hidden gems",
        f"{country} nature destinations",
        f"{country} mountain villages",
        f"{country} lake towns",
        f"{country} cultural destinations",
        f"{country} food destinations",
    ]

    if intent["sea"]:
        queries.extend([
            f"{country} beach towns",
            f"{country} coastal villages",
            f"{country} sunset destinations",
            f"{country} seaside towns",
        ])

    if intent["romantic"]:
        queries.extend([
            f"{country} romantic towns",
            f"{country} honeymoon places",
            f"{country} quiet romantic villages",
        ])

    if intent["culture"]:
        queries.extend([
            f"{country} historic cities",
            f"{country} old town destinations",
            f"{country} cultural towns",
        ])

    if intent["nature"]:
        queries.extend([
            f"{country} mountain towns",
            f"{country} nature parks",
            f"{country} scenic villages",
        ])

    queries = list(dict.fromkeys(clean_text(q) for q in queries if clean_text(q)))
    random.shuffle(queries)

    return queries[:MAX_QUERIES_PER_COUNTRY]


def build_destination_queries(user_text, travelers, continent="Any", country="Any"):
    intent = extract_travel_intent(user_text, travelers)

    countries = get_country_pool(
        continent=continent,
        user_text=user_text,
        country=country,
    )

    if not country or country == "Any":
        requested_countries = extract_requested_countries(user_text, continent)
        if not requested_countries:
            countries = countries[:MAX_COUNTRIES_PER_SEARCH]

    queries = []

    for c in countries:
        queries.extend(build_country_queries(c, intent))

    queries = list(dict.fromkeys(queries))
    random.shuffle(queries)

    print(f"[DISCOVERY] Dynamic country smart queries: {len(queries)}")
    return queries


def build_fallback_queries(continent="Any", user_text="", country="Any"):
    countries = get_country_pool(
        continent=continent,
        user_text=user_text,
        country=country,
    )

    if not country or country == "Any":
        requested_countries = extract_requested_countries(user_text, continent)
        if not requested_countries:
            countries = countries[:MAX_COUNTRIES_PER_SEARCH]

    queries = []

    for c in countries:
        queries.extend([
            f"{c} travel destinations",
            f"{c} best towns",
            f"{c} best cities",
            f"{c} villages",
            f"{c} islands",
            f"{c} coastal towns",
            f"{c} old towns",
            f"{c} hidden gems",
            f"{c} nature destinations",
        ])

    queries = list(dict.fromkeys(queries))
    random.shuffle(queries)

    return queries


def estimate_cost(
    name: str,
    country: str = "",
    place_type: str = "",
):
    place_type = normalize_key(place_type)

    country_costs = {
        "switzerland": 180,
        "norway": 170,
        "iceland": 170,
        "denmark": 160,
        "france": 135,
        "italy": 120,
        "spain": 105,
        "greece": 90,
        "croatia": 95,
        "portugal": 95,
        "turkey": 70,
        "thailand": 55,
        "indonesia": 50,
        "japan": 120,
        "united states": 160,
    }

    base = country_costs.get(
        normalize_key(country),
        100,
    )

    if place_type in {
        "village",
        "hamlet",
    }:
        base *= 0.85

    elif place_type in {
        "island",
        "resort",
    }:
        base *= 1.15

    elif place_type in {
        "capital",
        "city",
    }:
        base *= 1.10

    return round(base, 0)


def fallback_image_url(
    name: str,
    country: str,
) -> str:
    query = quote(
        f"{name}, {country}"
    )

    return (
        "https://source.unsplash.com/1200x800/?"
        f"{query}"
    )


def get_country_continent_from_api(country_code: str = "", country_name: str = ""):
    continent = get_country_continent(
        country_code=country_code,
        country_name=country_name,
    )

    continent = normalize_continent(continent)

    if continent:
        print(f"[REST COUNTRIES] {country_name or country_code} -> {continent}")
    else:
        print(f"[REST COUNTRIES] Could not detect continent for {country_name or country_code}")

    return continent


def normalize_destination_from_geocode(item):
    name = (
        item.get("city")
        or item.get("town")
        or item.get("village")
        or item.get("island")
        or item.get("name")
        or item.get("formatted", "").split(",")[0].strip()
    )

    country = item.get("country")
    lat = item.get("lat")
    lon = item.get("lon")
    place_type = item.get("result_type") or item.get("type") or "place"

    if not name or not country or lat is None or lon is None:
        return None

    name = safe_string(name)
    country = safe_string(country)
    place_type = safe_string(place_type) or "place"

    lower_type = normalize_key(place_type)

    if len(name) < 2 or len(country) < 2:
        return None

    if lower_type in BAD_PLACE_TYPES:
        return None

    if is_generic_bad_name(name):
        print(f"[GENERIC NAME SKIP] {name}, {country}")
        return None

    if is_admin_name(name):
        print(f"[ADMIN NAME SKIP] {name}, {country}")
        return None


    # -----------------------------------------
    # Reject country-level results
    # -----------------------------------------
    
    if normalize_key(name) == normalize_key(country):
        print(
            f"[COUNTRY RESULT SKIP] "
            f"{name}, {country}"
        )
        return None
    
    # -----------------------------------------
    # Reject one-word country names
    # -----------------------------------------
    
    bad_country_results = {
        "italy",
        "greece",
        "france",
        "spain",
        "portugal",
        "croatia",
        "turkey",
        "japan",
    }
    
    if normalize_key(name) in bad_country_results:
        print(
            f"[COUNTRY NAME SKIP] "
            f"{name}"
        )
        return None
        
    return {
        "name": name,
        "country": country,
        "country_code": item.get("country_code"),
        "latitude": safe_float(lat),
        "longitude": safe_float(lon),
        "place_type": place_type,
        "formatted": item.get("formatted"),
    }


def country_matches_requested_country(candidate: dict, requested_countries: list) -> bool:
    if not requested_countries:
        return True

    candidate_country = safe_string(candidate.get("country"))

    for requested_country in requested_countries:
        if soft_country_match(candidate_country, requested_country):
            return True

    print(
        f"[COUNTRY SKIP] {candidate.get('name')}, {candidate_country} "
        f"is not in requested countries {requested_countries}"
    )
    return False


def country_matches_continent(candidate: dict, selected_continent: str) -> bool:
    if not selected_continent or selected_continent == "Any":
        real_continent = get_country_continent_from_api(
            country_code=candidate.get("country_code"),
            country_name=candidate.get("country"),
        )
        candidate["detected_continent"] = real_continent or ""
        return True

    selected = normalize_continent(selected_continent)

    real_continent = get_country_continent_from_api(
        country_code=candidate.get("country_code"),
        country_name=candidate.get("country"),
    )

    real_continent = normalize_continent(real_continent)

    if real_continent != selected:
        print(
            f"[CONTINENT SKIP] {candidate.get('name')}, {candidate.get('country')} "
            f"is in {real_continent}, not {selected}"
        )
        return False

    candidate["detected_continent"] = real_continent
    return True


def is_candidate_relevant(candidate: dict, nearby_features: list) -> bool:
    place_type = normalize_key(candidate.get("place_type", ""))
    name = normalize_key(candidate.get("name", ""))

    if place_type in BAD_PLACE_TYPES:
        return False

    if is_generic_bad_name(name):
        return False

    if is_admin_name(name):
        return False

    if len(name) < 2:
        return False

    if place_type in ADMIN_PLACE_TYPES and len(nearby_features or []) < 10:
        return False

    if nearby_features:
        return True

    return place_type in GOOD_PLACE_TYPES


def summarize_place_features(features, max_items: int = 10):
    names = []
    seen = set()

    for feature in (features or [])[:max_items]:
        try:
            if not isinstance(feature, dict):
                continue

            props = feature.get("properties", {})
            if not isinstance(props, dict):
                continue

            raw_name = (
                props.get("name")
                or props.get("address_line1")
                or props.get("formatted")
            )

            name = safe_string(raw_name)

            if not name or name.isdigit() or is_generic_bad_name(name):
                continue

            key = normalize_key(name)

            if not key or key in seen:
                continue

            seen.add(key)
            names.append(str(name))

        except Exception:
            continue

    if names:
        return ", ".join(str(name) for name in names)

    return (
        "restaurants, cafes, viewpoints, walking areas, cultural attractions, "
        "hotels, beaches, nature spots, and local experiences"
    )


def build_rich_description(
    name,
    country,
    travelers,
    score_summary,
    place_type,
    destination_continent,
    highlights,
):
    return (
        f"{name}, {country} is recommended as a realistic travel destination. "
        f"It matches your preferences because {score_summary.lower()} "
        f"It can be suitable for {travelers or 'travelers'} looking for scenic areas, "
        f"local food, cultural places, walking routes, cafes, restaurants, hotels, and nearby activities. "
        f"Place type: {place_type}. "
        f"Matched continent: {destination_continent or 'Any'}. "
        f"Nearby highlights include: {highlights}."
    )


def attach_months(db, destination_id: int, requested_month: str):
    existing_months = {
        s.month for s in db.query(Season)
        .filter(Season.destination_id == destination_id)
        .all()
    }

    if requested_month and requested_month not in existing_months:
        db.add(Season(destination_id=destination_id, month=requested_month))
        existing_months.add(requested_month)

    for m in random.sample(MONTHS, 3):
        if m not in existing_months:
            db.add(Season(destination_id=destination_id, month=m))
            existing_months.add(m)


def replace_image(db, destination_id: int, name: str, country: str):
    db.query(Image).filter(Image.destination_id == destination_id).delete()

    real_image = get_destination_image(
        name,
        country,
    )
    
    if (
        not real_image
        or "pollinations" in str(real_image).lower()
    ):
        real_image = None
    
    final_image = real_image
    
    if not final_image:
        final_image = fallback_image_url(
            name,
            country,
        )

    db.add(Image(destination_id=destination_id, url=final_image))


def apply_score_to_destination(destination, score_data):
    summary = format_score_reason(score_data.get("reasons", []))

    destination.ai_score = float(score_data.get("score", 0) or 0)
    destination.score_summary = summary
    destination.score_reasons = score_data.get("reasons", [])

    destination.crowd_level = score_data.get("crowd_level")
    destination.hidden_gem_score = score_data.get("hidden_gem_score")
    destination.budget_realism = score_data.get("budget_realism")
    destination.risk_flags = score_data.get("risk_flags", [])

    destination.travel_dna_match = score_data.get("travel_dna_match")
    destination.local_authenticity_score = score_data.get("local_authenticity_score")
    destination.walking_difficulty = score_data.get("walking_difficulty")
    destination.tourist_trap_risk = score_data.get("tourist_trap_risk")

    destination.trip_mood = score_data.get("trip_mood")
    destination.daily_energy_level = score_data.get("daily_energy_level")
    destination.budget_reality_check = score_data.get("budget_reality_check")
    destination.regret_predictor = score_data.get("regret_predictor", [])
    destination.smart_timing_tip = score_data.get("smart_timing_tip")
    destination.trip_twin_label = score_data.get("trip_twin_label")

    return destination


def get_or_create_destination(
    db,
    candidate,
    month,
    user_text,
    travelers,
    budget,
    continent="Any",
    force_fresh=False,
):
    name = candidate["name"]
    country = candidate["country"]
    lat = candidate["latitude"]
    lon = candidate["longitude"]
    place_type = candidate.get("place_type", "place")

    if is_generic_bad_name(name) or is_admin_name(name):
        print(f"[QUALITY SKIP] {name}, {country}")
        return None

    budget = float(budget or 0)
    cost = estimate_cost(name=name, country=country, place_type=place_type)

    max_allowed_cost = budget * 2.2 if budget > 0 else 999999

    if cost > max_allowed_cost:
        print(f"[BUDGET SKIP] {name}, {country}: cost={cost}, max={max_allowed_cost}")
        return None

    categories = get_categories_from_preferences(user_text, travelers)

    for extra in [
        "tourism.sights",
        "tourism.attraction",
        "catering.restaurant",
        "catering.cafe",
        "catering.bar",
        "accommodation.hotel",
        "natural",
        "beach",
        "leisure.park",
        "entertainment",
    ]:
        if extra not in categories:
            categories.append(extra)

    try:
        nearby_features = search_places(
            lat=lat,
            lon=lon,
            categories=categories,
            radius=NEARBY_RADIUS,
            limit=NEARBY_LIMIT,
        )
    except Exception as e:
        print(f"[GEOAPIFY ERROR] Nearby search failed for {name}, {country}: {e}")
        nearby_features = []

    if not is_candidate_relevant(candidate, nearby_features):
        print(f"[RELEVANCE SKIP] {name}, {country}, type={place_type}")
        return None

    nearby_count = len(nearby_features)
    
    if nearby_count < 5:
        print(
            f"[LOW DATA SKIP] "
            f"{name}, "
            f"{country}"
        )
        return None
        
    highlights = summarize_place_features(nearby_features)

    destination_continent = normalize_continent(
        candidate.get("detected_continent")
        or get_country_continent_from_api(
            country_code=candidate.get("country_code"),
            country_name=country,
        )
        or continent
    )

    score_data = calculate_destination_score(
        destination_name=name,
        country=country,
        continent=destination_continent or "Any",
        selected_continent=continent,
        budget=budget,
        estimated_cost=cost,
        user_text=user_text,
        travelers=travelers,
        place_type=place_type,
        nearby_count=nearby_count,
    )

    score_summary = format_score_reason(score_data.get("reasons", []))

    description = build_rich_description(
        name=name,
        country=country,
        travelers=travelers,
        score_summary=score_summary,
        place_type=place_type,
        destination_continent=destination_continent,
        highlights=highlights,
    )

    existing = (
        db.query(Destination)
        .options(joinedload(Destination.images))
        .filter(Destination.name == name)
        .filter(Destination.country == country)
        .first()
    )

    if existing:
        existing.description = description
        existing.avg_cost_per_day = cost
        existing.latitude = lat
        existing.longitude = lon
        existing.continent = destination_continent
        existing.ai_score = float(score_data.get("score", 0) or 0)
        existing.score_summary = score_summary

        attach_months(db, existing.id, month)

        if force_fresh or not existing.images:
            replace_image(db, existing.id, name, country)

        db.flush()
        return apply_score_to_destination(existing, score_data)

    destination = Destination(
        name=name,
        country=country,
        continent=destination_continent,
        latitude=lat,
        longitude=lon,
        description=description,
        avg_cost_per_day=cost,
        ai_score=float(score_data.get("score", 0) or 0),
        score_summary=score_summary,
    )

    db.add(destination)
    db.flush()

    attach_months(db, destination.id, month)

    if force_fresh:
        replace_image(db, destination.id, name, country)
    else:
        db.add(Image(destination_id=destination.id, url=fallback_image_url(name, country)))

    db.flush()

    destination = (
        db.query(Destination)
        .options(joinedload(Destination.images))
        .filter(Destination.id == destination.id)
        .first()
    )

    return apply_score_to_destination(destination, score_data)


def run_discovery_queries(
    db,
    queries,
    discovered,
    seen,
    user_text,
    month,
    budget,
    travelers,
    continent,
    country="Any",
    limit=DEFAULT_RESULT_LIMIT,
    force_fresh=False,
):
    target_candidates = max(limit * 3, MIN_ACCEPTABLE_RESULTS)

    requested_countries = extract_requested_countries(user_text, continent)

    if country and country != "Any":
        requested_countries = [country]

    country_code = ""

    if len(requested_countries) == 1:
        country_code = get_country_code(requested_countries[0])
        print(f"[COUNTRY FILTER] {requested_countries[0]} -> {country_code or 'None'}")

    for query in queries:
        if len(discovered) >= target_candidates:
            return

        try:
            geo_results = geocode_location(
                query=query,
                limit=GEOAPIFY_GEOCODE_LIMIT,
                country_code=country_code,
                use_country_filter=bool(country_code),
            )

            print(f"[GEOAPIFY] Query='{query}' returned {len(geo_results)} candidates")

        except TypeError:
            geo_results = geocode_location(
                query=query,
                limit=GEOAPIFY_GEOCODE_LIMIT,
            )

            print(f"[GEOAPIFY] Query='{query}' returned {len(geo_results)} candidates")

        except Exception as e:
            print(f"[GEOAPIFY ERROR] Geocoding failed for '{query}': {e}")
            continue

        for item in geo_results:
            candidate = normalize_destination_from_geocode(item)

            if not candidate:
                continue

            if not country_matches_requested_country(candidate, requested_countries):
                continue

            if not country_matches_continent(candidate, continent):
                continue

            key = (
                normalize_key(candidate["name"]),
                normalize_key(candidate["country"]),
            )

            if key in seen:
                continue

            seen.add(key)

            destination = get_or_create_destination(
                db=db,
                candidate=candidate,
                month=month,
                user_text=user_text,
                travelers=travelers,
                budget=budget,
                continent=continent,
                force_fresh=force_fresh,
            )

            if destination:
                discovered.append(destination)

            if len(discovered) >= target_candidates:
                return


def discover_places(
    user_text: str,
    month: str,
    budget: float,
    travelers: str = "",
    continent: str = "Any",
    country: str = "Any",
    city: str = "Any",
    limit=DEFAULT_RESULT_LIMIT,
    force_fresh: bool = False,
):
    db = SessionLocal()
    discovered = []
    seen = set()

    limit = int(limit or DEFAULT_RESULT_LIMIT)
    limit = max(1, min(limit, 60))

    if country == "Any" and city and city != "Any":
        country = city

    try:
        print("\n[DISCOVERY] Starting DYNAMIC rich country-based discovery")
        print(
            f"[DISCOVERY] Month={month}, Budget={budget}, Travelers={travelers}, "
            f"Continent={continent}, Country={country}"
        )
        print(f"[DISCOVERY] User text={user_text}")
        print(f"[DISCOVERY] Limit={limit}")

        queries = build_destination_queries(
            user_text=user_text,
            travelers=travelers,
            continent=continent,
            country=country,
        )

        run_discovery_queries(
            db=db,
            queries=queries,
            discovered=discovered,
            seen=seen,
            user_text=user_text,
            month=month,
            budget=budget,
            travelers=travelers,
            continent=continent,
            country=country,
            limit=limit,
            force_fresh=force_fresh,
        )

        if len(discovered) < MIN_ACCEPTABLE_RESULTS:
            fallback_queries = build_fallback_queries(
                continent=continent,
                user_text=user_text,
                country=country,
            )

            run_discovery_queries(
                db=db,
                queries=fallback_queries,
                discovered=discovered,
                seen=seen,
                user_text=user_text,
                month=month,
                budget=budget,
                travelers=travelers,
                continent=continent,
                country=country,
                limit=limit,
                force_fresh=force_fresh,
            )

        discovered.sort(
            key=lambda d: (
                float(getattr(d, "ai_score", 0) or 0),
                float(getattr(d, "travel_dna_match", 0) or 0),
                float(getattr(d, "hidden_gem_score", 0) or 0),
                float(getattr(d, "local_authenticity_score", 0) or 0),
                -float(getattr(d, "avg_cost_per_day", 999999) or 999999),
            ),
            reverse=True,
        )

        discovered = discovered[:limit]

        db.commit()

        for d in discovered:
            _ = d.images

        print(f"[DISCOVERY] Returning {len(discovered)} ranked destinations")
        return discovered

    except Exception as e:
        db.rollback()
        print(f"[DISCOVERY ERROR] {e}")
        raise

    finally:
        db.close()