# -*- coding: utf-8 -*-

import random
import requests

from app.utils.config import PEXELS_API_KEY


PEXELS_BASE_URL = "https://api.pexels.com/v1/search"
REQUEST_TIMEOUT = 25

IMAGE_CACHE = {}


BAD_IMAGE_WORDS = {
    "map",
    "flag",
    "text",
    "sign",
    "logo",
    "poster",
    "menu",
    "airport",
    "airplane",
    "plane",
    "person",
    "people",
    "portrait",
}


def _check_api_key():
    if not PEXELS_API_KEY:
        raise ValueError(
            "Missing PEXELS_API_KEY in .env file. "
            "Add: PEXELS_API_KEY=your_pexels_key_here"
        )


def _safe_key_status():
    return f"loaded ({len(PEXELS_API_KEY)} chars)" if PEXELS_API_KEY else "missing"


def clean_query(query: str) -> str:
    return " ".join((query or "").replace("\n", " ").split()).strip()


def photo_score(photo: dict, destination_name: str = "", country: str = "") -> int:
    """
    Prefer landscape/travel-looking images and avoid weak generic images.
    """

    score = 0

    width = int(photo.get("width") or 0)
    height = int(photo.get("height") or 0)
    alt = str(photo.get("alt") or "").lower()
    url = str(photo.get("url") or "").lower()

    destination_name = str(destination_name or "").lower()
    country = str(country or "").lower()

    if width > height:
        score += 30

    if width >= 1200:
        score += 10

    if height >= 700:
        score += 10

    if destination_name and destination_name in alt:
        score += 40

    if country and country in alt:
        score += 25

    travel_words = [
        "travel",
        "landscape",
        "city",
        "town",
        "village",
        "island",
        "beach",
        "sea",
        "coast",
        "street",
        "old town",
        "architecture",
        "mountain",
        "sunset",
        "view",
        "harbor",
        "harbour",
    ]

    for word in travel_words:
        if word in alt or word in url:
            score += 5

    for bad_word in BAD_IMAGE_WORDS:
        if bad_word in alt or bad_word in url:
            score -= 25

    return score


def search_pexels_images(query: str, per_page: int = 8):
    """
    Search real destination/travel images from Pexels.
    """

    _check_api_key()

    clean = clean_query(query)

    if not clean:
        clean = "travel destination landscape"

    per_page = max(1, min(int(per_page or 8), 20))

    print("\n[PEXELS] Searching images")
    print(f"[PEXELS] API key: {_safe_key_status()}")
    print(f"[PEXELS] Query: {clean}")

    headers = {
        "Authorization": PEXELS_API_KEY,
    }

    params = {
        "query": clean,
        "per_page": per_page,
        "orientation": "landscape",
        "size": "large",
    }

    response = requests.get(
        PEXELS_BASE_URL,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    print(f"[PEXELS] Status code: {response.status_code}")

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"[PEXELS ERROR] HTTP error: {e}")
        print(f"[PEXELS ERROR] Response: {response.text[:500]}")
        raise

    data = response.json()
    photos = data.get("photos", [])

    print(f"[PEXELS] Images found: {len(photos)}")

    return photos


def extract_image_url(photo: dict):
    src = photo.get("src", {})

    return (
        src.get("large2x")
        or src.get("large")
        or src.get("medium")
        or src.get("original")
    )


def get_best_pexels_image(
    query: str,
    destination_name: str = "",
    country: str = "",
):
    """
    Return one high-quality image URL from Pexels.
    """

    cache_key = (
        clean_query(query).lower(),
        str(destination_name or "").lower(),
        str(country or "").lower(),
    )

    if cache_key in IMAGE_CACHE:
        return IMAGE_CACHE[cache_key]

    try:
        photos = search_pexels_images(query=query, per_page=10)

        if not photos:
            print("[PEXELS] No images found")
            IMAGE_CACHE[cache_key] = None
            return None

        ranked = sorted(
            photos,
            key=lambda p: photo_score(
                p,
                destination_name=destination_name,
                country=country,
            ),
            reverse=True,
        )

        best_photo = ranked[0]
        image_url = extract_image_url(best_photo)

        print(f"[PEXELS] Selected image: {image_url}")
        print(f"[PEXELS] Selected alt: {best_photo.get('alt')}")

        IMAGE_CACHE[cache_key] = image_url
        return image_url

    except Exception as e:
        print(f"[PEXELS ERROR] Failed to get image for '{query}': {e}")
        IMAGE_CACHE[cache_key] = None
        return None


def get_destination_image(name: str, country: str):
    """
    Destination-specific image search.

    Important:
    - First searches exact destination + country.
    - Then tries travel/location-specific fallback queries.
    - Avoids immediately using only country-level images,
      because that causes wrong generic Greece/Italy/etc images.
    """

    name = clean_query(name)
    country = clean_query(country)

    if not name and not country:
        return get_best_pexels_image("beautiful travel destination landscape")

    queries = []

    if name and country:
        queries.extend([
            f"{name} {country}",
            f"{name} {country} travel",
            f"{name} {country} landscape",
            f"{name} {country} old town",
            f"{name} {country} beach coast island",
        ])

    if name:
        queries.extend([
            f"{name} travel destination",
            f"{name} landscape",
        ])

    if country:
        queries.extend([
            f"{country} travel landscape",
            f"{country} island beach town",
        ])

    queries = list(dict.fromkeys(queries))

    for query in queries:
        image = get_best_pexels_image(
            query=query,
            destination_name=name,
            country=country,
        )

        if image:
            return image

    return None


def get_destination_gallery(name: str, country: str, limit: int = 6):
    """
    Return multiple image URLs for a destination gallery.
    """

    name = clean_query(name)
    country = clean_query(country)

    limit = max(1, min(int(limit or 6), 12))

    queries = [
        f"{name} {country}",
        f"{name} {country} travel",
        f"{name} {country} landscape",
    ]

    urls = []
    seen = set()

    for query in queries:
        try:
            photos = search_pexels_images(query=query, per_page=limit)

            ranked = sorted(
                photos,
                key=lambda p: photo_score(
                    p,
                    destination_name=name,
                    country=country,
                ),
                reverse=True,
            )

            for photo in ranked:
                image_url = extract_image_url(photo)

                if not image_url or image_url in seen:
                    continue

                seen.add(image_url)
                urls.append(image_url)

                if len(urls) >= limit:
                    print(f"[PEXELS] Gallery images returned: {len(urls)}")
                    return urls

        except Exception as e:
            print(f"[PEXELS ERROR] Gallery query failed for '{query}': {e}")

    print(f"[PEXELS] Gallery images returned: {len(urls)}")
    return urls