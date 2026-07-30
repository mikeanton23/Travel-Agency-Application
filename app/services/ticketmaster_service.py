# -*- coding: utf-8 -*-

import requests
from datetime import datetime

from app.utils.config import (
    TICKETMASTER_API_KEY,
)

BASE_URL = (
    "https://app.ticketmaster.com"
    "/discovery/v2/events.json"
)

REQUEST_TIMEOUT = 20


# =====================================================
# SAFE HELPERS
# =====================================================

def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# =====================================================
# DATE HELPERS
# =====================================================

def iso_date(date_string):
    """
    Converts:
    2026-07-10

    into:

    2026-07-10T00:00:00Z
    """

    if not date_string:
        return None

    try:
        return (
            datetime.strptime(
                date_string,
                "%Y-%m-%d"
            )
            .strftime(
                "%Y-%m-%dT00:00:00Z"
            )
        )
    except Exception:
        return None


# =====================================================
# MAIN SEARCH
# =====================================================

def search_events(
    city=None,
    country_code=None,
    keyword=None,
    start_date=None,
    end_date=None,
    classification=None,
    size=20,
    sort="relevance,desc",
):
    if not TICKETMASTER_API_KEY:
        print(
            "[TICKETMASTER] Missing API key"
        )
        return []

    params = {
        "apikey": TICKETMASTER_API_KEY,
        "size": max(
            1,
            min(
                safe_int(size, 20),
                200,
            ),
        ),
        "sort": sort,
    }

    if city:
        params["city"] = city

    if country_code:
        params["countryCode"] = country_code

    if keyword:
        params["keyword"] = keyword

    if classification:
        params["classificationName"] = classification

    start_iso = iso_date(start_date)

    if start_iso:
        params["startDateTime"] = start_iso

    end_iso = iso_date(end_date)

    if end_iso:
        params["endDateTime"] = end_iso

    try:

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        events = (
            data.get(
                "_embedded",
                {}
            )
            .get(
                "events",
                []
            )
        )

        results = []

        for event in events:

            venue_name = ""
            venue_city = ""
            venue_country = ""

            venues = (
                event.get(
                    "_embedded",
                    {}
                )
                .get(
                    "venues",
                    []
                )
            )

            if venues:
                venue = venues[0]

                venue_name = safe_text(
                    venue.get(
                        "name"
                    )
                )

                venue_city = safe_text(
                    venue.get(
                        "city",
                        {}
                    ).get(
                        "name"
                    )
                )

                venue_country = safe_text(
                    venue.get(
                        "country",
                        {}
                    ).get(
                        "name"
                    )
                )

            image_url = ""

            images = event.get(
                "images",
                []
            )

            if images:
                images = sorted(
                    images,
                    key=lambda x:
                        x.get(
                            "width",
                            0,
                        ),
                    reverse=True,
                )

                image_url = safe_text(
                    images[0].get(
                        "url"
                    )
                )

            price_min = None
            price_max = None
            currency = ""

            price_ranges = event.get(
                "priceRanges",
                []
            )

            if price_ranges:
                price = price_ranges[0]

                price_min = safe_float(
                    price.get(
                        "min"
                    )
                )

                price_max = safe_float(
                    price.get(
                        "max"
                    )
                )

                currency = safe_text(
                    price.get(
                        "currency"
                    )
                )

            classifications = event.get(
                "classifications",
                []
            )

            genre = ""
            segment = ""

            if classifications:
                classification_data = classifications[0]

                genre = safe_text(
                    classification_data.get(
                        "genre",
                        {}
                    ).get(
                        "name"
                    )
                )

                segment = safe_text(
                    classification_data.get(
                        "segment",
                        {}
                    ).get(
                        "name"
                    )
                )

            results.append({

                "event_id":
                    safe_text(
                        event.get(
                            "id"
                        )
                    ),

                "event_name":
                    safe_text(
                        event.get(
                            "name"
                        )
                    ),

                "event_url":
                    safe_text(
                        event.get(
                            "url"
                        )
                    ),

                "event_date":
                    (
                        event.get(
                            "dates",
                            {}
                        )
                        .get(
                            "start",
                            {}
                        )
                        .get(
                            "localDate",
                            ""
                        )
                    ),

                "event_time":
                    (
                        event.get(
                            "dates",
                            {}
                        )
                        .get(
                            "start",
                            {}
                        )
                        .get(
                            "localTime",
                            ""
                        )
                    ),

                "status":
                    (
                        event.get(
                            "dates",
                            {}
                        )
                        .get(
                            "status",
                            {}
                        )
                        .get(
                            "code",
                            ""
                        )
                    ),

                "venue":
                    venue_name,

                "venue_city":
                    venue_city,

                "venue_country":
                    venue_country,

                "segment":
                    segment,

                "genre":
                    genre,

                "image_url":
                    image_url,

                "price_min":
                    price_min,

                "price_max":
                    price_max,

                "currency":
                    currency,

                "ticket_required":
                    True,

                "reservation_required":
                    True,

                "provider":
                    "Ticketmaster",

                "booking_url":
                    safe_text(
                        event.get(
                            "url"
                        )
                    ),
            })

        print(
            f"[TICKETMASTER] "
            f"Found {len(results)} events"
        )

        return results

    except requests.exceptions.HTTPError as e:
        print(
            "[TICKETMASTER HTTP ERROR]",
            e,
        )

    except requests.exceptions.Timeout:
        print(
            "[TICKETMASTER TIMEOUT]"
        )

    except requests.exceptions.RequestException as e:
        print(
            "[TICKETMASTER REQUEST ERROR]",
            e,
        )

    except Exception as e:
        print(
            "[TICKETMASTER ERROR]",
            e,
        )

    return []