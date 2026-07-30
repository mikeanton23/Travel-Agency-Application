# -*- coding: utf-8 -*-

import time
from typing import Any

import requests

from app.utils.config import GEOAPIFY_API_KEY


GEOAPIFY_BASE_URL = "https://api.geoapify.com/v2"
GEOAPIFY_V1_URL = "https://api.geoapify.com/v1"

DEFAULT_TIMEOUT = 25
MAX_RADIUS_METERS = 100000


CATEGORY_ALIASES = {
    "beach": "beach",
    "natural": "natural",
    "tourism": "tourism",
    "tourism.attraction": "tourism.attraction",
    "tourism.sights": "tourism.sights",
    "catering.restaurant": "catering.restaurant",
    "catering.cafe": "catering.cafe",
    "catering.bar": "catering.bar",
    "entertainment": "entertainment",
    "entertainment.museum": "entertainment.museum",
    "leisure.park": "leisure.park",
    "accommodation.hotel": "accommodation.hotel",
}

VALID_PLACE_TYPES = {
    "city",
    "town",
    "village",
    "island",
    "municipality",
    "hamlet",
}

BAD_PLACE_TYPES = {
    "road",
    "street",
    "postcode",
    "county",
    "district",
    "state",
    "suburb",
    "locality",
    "neighbourhood",
    "administrative",
    "country",
}


def _check_api_key():
    if not GEOAPIFY_API_KEY:
        raise ValueError(
            "Missing GEOAPIFY_API_KEY in .env file. "
            "Add: GEOAPIFY_API_KEY=your_geoapify_key_here"
        )


def _safe_key_status():
    return f"loaded ({len(GEOAPIFY_API_KEY)} chars)" if GEOAPIFY_API_KEY else "missing"


def _safe_text(value, default="") -> str:
    value = str(value or "").strip()
    return value if value else default


def _safe_int(value, default=0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _mask_url(url: str) -> str:
    url = str(url or "")

    if "apiKey=" in url:
        return url.split("apiKey=")[0] + "apiKey=***"

    return url


def _normalize_country_code(country_code: str = "") -> str:
    value = _safe_text(country_code).lower()
    return value[:2] if len(value) >= 2 else value


def _normalize_categories(categories) -> list[str]:
    if not categories:
        return []

    clean = []

    for category in categories:
        value = _safe_text(category).lower()

        if not value:
            continue

        value = CATEGORY_ALIASES.get(value, value)

        if value not in clean:
            clean.append(value)

    return clean


def _request_get(
    url: str,
    params: dict,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 2,
    retry_sleep: float = 0.8,
):
    _check_api_key()

    last_error = None

    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)

            print(f"[GEOAPIFY] Request URL: {_mask_url(response.url)}")
            print(f"[GEOAPIFY] Status code: {response.status_code}")

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                wait = retry_sleep * (attempt + 1)
                print(f"[GEOAPIFY] Retrying in {wait:.1f}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            last_error = e
            print(f"[GEOAPIFY ERROR] HTTP error: {e}")

            if e.response is not None:
                print(f"[GEOAPIFY ERROR] Response: {e.response.text[:500]}")

            if attempt < retries and e.response is not None and e.response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(retry_sleep * (attempt + 1))
                continue

            raise

        except requests.exceptions.Timeout as e:
            last_error = e
            print("[GEOAPIFY ERROR] Request timed out")

            if attempt < retries:
                time.sleep(retry_sleep * (attempt + 1))
                continue

            raise

        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"[GEOAPIFY ERROR] Request failed: {e}")

            if attempt < retries:
                time.sleep(retry_sleep * (attempt + 1))
                continue

            raise

    raise last_error


def geocode_location(
    query: str,
    limit: int = 12,
    country_code: str = "",
    use_country_filter: bool = True,
):
    clean_query = _safe_text(query)
    normalized_country_code = _normalize_country_code(country_code)

    if not clean_query:
        return []

    print("\n[GEOAPIFY] Geocoding")
    print(f"[GEOAPIFY] API key: {_safe_key_status()}")
    print(f"[GEOAPIFY] Query: {clean_query}")
    print(f"[GEOAPIFY] Country code: {normalized_country_code or 'None'}")
    print(f"[GEOAPIFY] Country filter: {use_country_filter}")

    url = f"{GEOAPIFY_V1_URL}/geocode/search"

    params = {
        "text": clean_query,
        "apiKey": GEOAPIFY_API_KEY,
        "limit": max(1, min(_safe_int(limit, 12), 100)),
        "format": "json",
        "lang": "en",
    
        "type": "city",
    }

    if normalized_country_code:
        params["bias"] = f"countrycode:{normalized_country_code}"

        if use_country_filter:
            params["filter"] = f"countrycode:{normalized_country_code}"

    data = _request_get(url, params=params, timeout=25)
    results = data.get("results", []) or []

    print(f"[GEOAPIFY] Geocoding results: {len(results)}")
    return results


def geocode_country_destinations(
    country: str,
    country_code: str = "",
    limit: int = 50,
):
    country = _safe_text(country)

    if not country:
        return []

    queries = [
        f"cities in {country}",
        f"towns in {country}",
        f"islands in {country}",
        f"tourist destinations in {country}",
        f"best places to visit in {country}",
        f"coastal towns in {country}",
        f"historic towns in {country}",
        f"beautiful destinations in {country}",
    ]

    results = []
    seen = set()

    target_limit = max(1, min(_safe_int(limit, 50), 100))
    per_query_limit = max(10, min(25, target_limit))

    for query in queries:
        try:
            items = geocode_location(
                query=query,
                limit=per_query_limit,
                country_code=country_code,
                use_country_filter=bool(country_code),
            )
        except Exception as e:
            print(f"[GEOAPIFY ERROR] Destination query failed '{query}': {e}")
            continue

        for item in items:
            name = (
                item.get("city")
                or item.get("town")
                or item.get("village")
                or item.get("island")
                or item.get("municipality")
                or item.get("name")
                or _safe_text(item.get("formatted")).split(",")[0].strip()
            )

            item_country = item.get("country")
            
            if (
                name
                and item_country
                and name.lower() == item_country.lower()
            ):
                continue
                
            lat = item.get("lat")
            lon = item.get("lon")
            place_type = (
                item.get("result_type")
                or item.get("type")
                or ""
            ).lower()
            
            if place_type in BAD_PLACE_TYPES:
                continue
            
            if place_type not in VALID_PLACE_TYPES:
                continue

            if not name or not item_country or lat is None or lon is None:
                continue

            key = (
                _safe_text(name).lower(),
                round(lat, 3),
                round(lon, 3),
            )

            if key in seen:
                continue

            seen.add(key)

            results.append({
                "name": _safe_text(name),
                "country": _safe_text(item_country),
                "country_code": item.get("country_code"),
                "latitude": lat,
                "longitude": lon,
                "place_type": place_type,
                "formatted": item.get("formatted"),
                "importance": item.get("rank", {}).get("importance", 0),
                "confidence": item.get("rank", {}).get("confidence", 0),
                "population": item.get("population", 0),
            })

            if len(results) >= target_limit:
                results.sort(
                    key=lambda x: (
                        x["importance"],
                        x["population"],
                        x["confidence"],
                    ),
                    reverse=True,
                )
                print(f"[GEOAPIFY] Country destinations returned: {len(results)}")
                return results

    print(f"[GEOAPIFY] Country destinations returned: {len(results)}")
    return results


def reverse_geocode(lat: float, lon: float):
    print("\n[GEOAPIFY] Reverse geocoding")
    print(f"[GEOAPIFY] Lat/Lon: {lat}, {lon}")

    url = f"{GEOAPIFY_V1_URL}/geocode/reverse"

    params = {
        "lat": lat,
        "lon": lon,
        "apiKey": GEOAPIFY_API_KEY,
        "format": "json",
        "lang": "en",
    }

    data = _request_get(url, params=params, timeout=25)
    results = data.get("results", []) or []

    print(f"[GEOAPIFY] Reverse results: {len(results)}")
    return results


def search_places(
    lat: float,
    lon: float,
    categories: list[str] | None = None,
    radius: int = 30000,
    limit: int = 20,
):
    lat = _safe_float(lat)
    lon = _safe_float(lon)

    if lat is None or lon is None:
        print("[GEOAPIFY] Missing lat/lon for places search")
        return []

    categories = _normalize_categories(categories)

    if not categories:
        categories = [
            "tourism.attraction",
            "tourism.sights",
            "catering.restaurant",
            "natural",
            "entertainment",
        ]

    radius = max(1000, min(_safe_int(radius, 30000), MAX_RADIUS_METERS))
    limit = max(1, min(_safe_int(limit, 20), 500))

    print("\n[GEOAPIFY] Places search")
    print(f"[GEOAPIFY] Lat/Lon: {lat}, {lon}")
    print(f"[GEOAPIFY] Radius: {radius}")
    print(f"[GEOAPIFY] Categories: {categories}")

    url = f"{GEOAPIFY_BASE_URL}/places"

    params = {
        "categories": ",".join(categories),
        "filter": f"circle:{lon},{lat},{radius}",
        "bias": f"proximity:{lon},{lat}",
        "limit": limit,
        "apiKey": GEOAPIFY_API_KEY,
        "lang": "en",
    }

    data = _request_get(url, params=params, timeout=30)
    features = data.get("features", []) or []
    
    def feature_score(feature):

        props = feature.get("properties", {})
        cats = props.get("categories", [])
        rank = props.get("rank", {})
    
        score = 0
    
        if "tourism.attraction" in cats:
            score += 120
    
        if "tourism.sights" in cats:
            score += 100
    
        if "entertainment.museum" in cats:
            score += 90
    
        if "natural" in cats:
            score += 80
    
        if "beach" in cats:
            score += 80
    
        score += rank.get("importance", 0) * 100
        score += rank.get("confidence", 0) * 50
    
        return score
    
    features.sort(
        key=feature_score,
        reverse=True,
    )
    
    filtered = []

    for feature in features:
    
        props = feature.get("properties", {})
    
        categories = props.get("categories", [])
    
        if any(
            x in categories
            for x in [
                "accommodation.hotel",
                "building",
                "commercial",
                "office",
                "parking",
            ]
        ):
            continue
    
        filtered.append(feature)
    
    features = filtered

    print(f"[GEOAPIFY] Places found: {len(features)}")
    return features


def search_places_by_text(
    text: str,
    categories: list[str] | None = None,
    limit: int = 20,
    country_code: str = "",
    radius: int = 30000,
):
    print("\n[GEOAPIFY] Search places by text")
    print(f"[GEOAPIFY] Text: {text}")
    print(f"[GEOAPIFY] Country code: {country_code or 'None'}")

    locations = geocode_location(
        query=text,
        limit=1,
        country_code=country_code,
        use_country_filter=bool(country_code),
    )

    if not locations:
        print("[GEOAPIFY] No geocoding result for text search")
        return []

    first = locations[0]
    lat = first.get("lat")
    lon = first.get("lon")

    if lat is None or lon is None:
        print("[GEOAPIFY] Missing lat/lon from geocoding result")
        return []

    return search_places(
        lat=lat,
        lon=lon,
        categories=categories,
        radius=radius,
        limit=limit,
    )


def get_place_details(place_id: str):
    place_id = _safe_text(place_id)

    print("\n[GEOAPIFY] Place details")
    print(f"[GEOAPIFY] Place ID: {place_id}")

    if not place_id:
        return {}

    url = f"{GEOAPIFY_BASE_URL}/place-details"

    params = {
        "id": place_id,
        "apiKey": GEOAPIFY_API_KEY,
        "lang": "en",
    }

    data = _request_get(url, params=params, timeout=25)

    print("[GEOAPIFY] Place details OK")
    return data


def get_static_map_url(
    lat: float,
    lon: float,
    zoom: int = 12,
    width: int = 900,
    height: int = 500,
):
    _check_api_key()

    zoom = max(1, min(_safe_int(zoom, 12), 20))
    width = max(200, min(_safe_int(width, 900), 2000))
    height = max(200, min(_safe_int(height, 500), 2000))

    return (
        f"https://maps.geoapify.com/v1/staticmap"
        f"?style=osm-bright"
        f"&width={width}"
        f"&height={height}"
        f"&center=lonlat:{lon},{lat}"
        f"&zoom={zoom}"
        f"&marker=lonlat:{lon},{lat};color:%23ff0000;size:medium"
        f"&apiKey={GEOAPIFY_API_KEY}"
    )


def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    mode: str = "walk",
):
    mode = _safe_text(mode, "walk").lower()

    allowed_modes = {
        "walk", "drive", "bicycle", "transit", "approximated_transit",
        "scooter", "motorcycle", "truck"
    }

    if mode not in allowed_modes:
        mode = "walk"

    print("\n[GEOAPIFY] Routing")
    print(f"[GEOAPIFY] From: {start_lat}, {start_lon}")
    print(f"[GEOAPIFY] To: {end_lat}, {end_lon}")
    print(f"[GEOAPIFY] Mode: {mode}")

    url = f"{GEOAPIFY_V1_URL}/routing"

    params = {
        "waypoints": f"{start_lat},{start_lon}|{end_lat},{end_lon}",
        "mode": mode,
        "apiKey": GEOAPIFY_API_KEY,
    }

    data = _request_get(url, params=params, timeout=30)

    print("[GEOAPIFY] Route OK")
    return data


def get_categories_from_preferences(user_text: str, travelers: str = ""):
    text = f"{user_text or ''} {travelers or ''}".lower()

    categories = set()

    # --------------------------------------------------
    # FOOD
    # --------------------------------------------------

    if any(word in text for word in [
        "food", "restaurant", "local food", "traditional",
        "dinner", "lunch", "breakfast", "brunch",
        "taverna", "cafe", "coffee", "dessert",
        "bakery", "street food", "gastronomy"
    ]):
        categories.update([
            "catering.restaurant",
            "catering.cafe",
        ])

    # --------------------------------------------------
    # BARS / NIGHTLIFE
    # --------------------------------------------------

    if any(word in text for word in [
        "bar", "bars", "cocktail",
        "nightlife", "club",
        "party", "pub",
        "wine", "wine bar",
        "beer"
    ]):
        categories.update([
            "catering.bar",
            "entertainment",
        ])

    # --------------------------------------------------
    # CULTURE
    # --------------------------------------------------

    if any(word in text for word in [
        "museum",
        "history",
        "historic",
        "culture",
        "art",
        "gallery",
        "architecture",
        "monument",
        "heritage",
        "castle",
        "ruins",
        "archaeological",
        "old town",
    ]):
        categories.update([
            "tourism.sights",
            "tourism.attraction",
            "entertainment.museum",
        ])

    # --------------------------------------------------
    # BEACH
    # --------------------------------------------------

    if any(word in text for word in [
        "beach",
        "sea",
        "coast",
        "coastal",
        "swim",
        "island",
        "sunset",
        "seaside",
        "ocean",
    ]):
        categories.update([
            "beach",
            "natural",
            "tourism.attraction",
        ])

    # --------------------------------------------------
    # NATURE
    # --------------------------------------------------

    if any(word in text for word in [
        "nature",
        "forest",
        "mountain",
        "park",
        "walking",
        "walk",
        "hiking",
        "trail",
        "lake",
        "waterfall",
        "viewpoint",
        "garden",
    ]):
        categories.update([
            "natural",
            "tourism.attraction",
            "leisure.park",
        ])

    # --------------------------------------------------
    # ROMANTIC
    # --------------------------------------------------

    if any(word in text for word in [
        "romantic",
        "honeymoon",
        "couple",
        "proposal",
        "anniversary",
    ]):
        categories.update([
            "tourism.attraction",
            "natural",
            "catering.restaurant",
            "catering.cafe",
        ])

    # --------------------------------------------------
    # FAMILY
    # --------------------------------------------------

    if any(word in text for word in [
        "family",
        "kids",
        "children",
        "child",
    ]):
        categories.update([
            "leisure.park",
            "tourism.attraction",
            "catering.restaurant",
        ])

    # --------------------------------------------------
    # SHOPPING
    # --------------------------------------------------

    if any(word in text for word in [
        "shopping",
        "mall",
        "market",
        "shopping center",
        "boutique",
        "souvenir",
    ]):
        categories.update([
            "commercial.shopping_mall",
            "commercial.marketplace",
        ])

    # --------------------------------------------------
    # PHOTOGRAPHY
    # --------------------------------------------------

    if any(word in text for word in [
        "photography",
        "instagram",
        "photo",
        "photos",
        "landmarks",
        "must see",
        "best views",
        "view",
    ]):
        categories.update([
            "tourism.attraction",
            "tourism.sights",
            "natural",
        ])

    # --------------------------------------------------
    # ADVENTURE
    # --------------------------------------------------

    if any(word in text for word in [
        "adventure",
        "kayak",
        "rafting",
        "diving",
        "snorkeling",
        "climbing",
        "ski",
        "surf",
        "boat",
        "cruise",
    ]):
        categories.update([
            "tourism.attraction",
            "natural",
            "entertainment",
        ])

    # --------------------------------------------------
    # LUXURY
    # --------------------------------------------------

    if any(word in text for word in [
        "luxury",
        "vip",
        "premium",
        "five star",
        "5 star",
    ]):
        categories.update([
            "accommodation.hotel",
            "catering.restaurant",
        ])

    # --------------------------------------------------
    # HOTEL
    # --------------------------------------------------

    if any(word in text for word in [
        "hotel",
        "hotels",
        "stay",
        "accommodation",
        "resort",
    ]):
        categories.add("accommodation.hotel")

    # --------------------------------------------------
    # WELLNESS
    # --------------------------------------------------

    if any(word in text for word in [
        "spa",
        "wellness",
        "massage",
        "relax",
        "thermal",
    ]):
        categories.update([
            "entertainment",
        ])

    # --------------------------------------------------
    # DEFAULT
    # --------------------------------------------------

    if not categories:
        categories.update([
            "tourism.attraction",
            "tourism.sights",
            "entertainment.museum",
            "catering.restaurant",
            "catering.cafe",
            "natural",
            "leisure.park",
        ])

    result = _normalize_categories(categories)

    print(f"[GEOAPIFY] Categories from preferences: {result}")

    return result
