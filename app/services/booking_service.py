# -*- coding: utf-8 -*-

"""
Aevyra Booking Service

Purpose:
- Ticket requirements
- Reservation requirements
- Advance booking recommendations
- Booking provider suggestions
- Booking confidence scoring

Future Integrations:
- Viator
- GetYourGuide
- Ticketmaster
- Amadeus
- OpenTable
- Booking.com
"""

from typing import Dict
from urllib.parse import quote_plus
from datetime import datetime
from app.services.ticketmaster_service import (
    search_events,
)

# =====================================================
# SAFE HELPERS
# =====================================================

def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


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
# TICKET REQUIREMENTS
# =====================================================

def ticket_required(place: dict) -> bool:
    # --------------------------------------------------
    # Live booking information (highest priority)
    # --------------------------------------------------

    if place.get("live_ticket_required") is True:
        return True

    if place.get("ticket_required") is True:
        return True

    if place.get("booking_provider") in {
        "Ticketmaster",
        "Viator",
        "GetYourGuide",
    }:
        return True

    # --------------------------------------------------
    # Category fallback
    # --------------------------------------------------

    return has_category(
        place,
        [
            "museum",
            "gallery",
            "attraction",
            "castle",
            "monument",
            "aquarium",
            "zoo",
            "theme",
            "archaeological",
            "heritage",
            "historic",
            "ruins",
            "fort",
            "palace",
            "tower",
            "tour",
            "guided",
            "cruise",
            "boat",
            "wine",
            "vineyard",
            "winery",
            "adventure",
            "kayak",
            "rafting",
            "diving",
            "snorkeling",
            "paragliding",
            "ski",
            "snowboard",
            "festival",
            "concert",
            "show",
            "theatre",
            "opera",
            "arena",
            "stadium",
            "event",
            "water_park",
            "water park",
            "amusement",
            "observation",
            "skydeck",
        ],
    )


# =====================================================
# RESERVATION REQUIREMENTS
# =====================================================

def reservation_required(place: dict) -> bool:
    # --------------------------------------------------
    # Live booking information (highest priority)
    # --------------------------------------------------

    if place.get("live_reservation_required") is True:
        return True

    if place.get("reservation_required") is True:
        return True

    # --------------------------------------------------
    # Provider-based detection
    # --------------------------------------------------

    provider = safe_text(
        place.get("booking_provider")
    )

    if provider in {
        "OpenTable",
        "Booking.com",
        "Viator",
        "GetYourGuide",
        "Ticketmaster",
    }:
        return True

    # --------------------------------------------------
    # Category fallback
    # --------------------------------------------------

    return has_category(
        place,
        [
            # Restaurants
            "restaurant",
            "fine_dining",
            "fine dining",
            "michelin",
            "rooftop",
            "wine_bar",
            "wine bar",

            # Tours
            "tour",
            "guided",
            "excursion",
            "activity",

            # Cruises
            "cruise",
            "boat",
            "sailing",
            "catamaran",
            "yacht",

            # Food experiences
            "wine",
            "vineyard",
            "winery",
            "cooking",
            "culinary",

            # Adventure
            "kayak",
            "rafting",
            "diving",
            "snorkeling",
            "paragliding",
            "ski",
            "snowboard",

            # Events
            "event",
            "concert",
            "festival",
            "show",
            "theatre",
            "opera",
            "arena",
            "stadium",
            "sports",

            # Hotels
            "hotel",
            "accommodation",
            "resort",

            # Attractions with limited capacity
            "theme",
            "water_park",
            "water park",
            "observation",
            "skydeck",
        ],
    )


# =====================================================
# ADVANCE BOOKING
# =====================================================

def advance_booking_days(place: dict) -> int:
    # --------------------------------------------------
    # Live booking information (highest priority)
    # --------------------------------------------------

    live_days = place.get("advance_booking_days")

    try:
        if live_days is not None:
            live_days = int(live_days)

            if live_days >= 0:
                return live_days
    except Exception:
        pass

    text = category_text(place)

    # --------------------------------------------------
    # Major events
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "festival",
            "music festival",
            "formula",
            "olympic",
            "world cup",
        ]
    ):
        return 90

    # --------------------------------------------------
    # Concerts / Theatre
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "concert",
            "show",
            "theatre",
            "opera",
            "arena",
            "stadium",
        ]
    ):
        return 45

    # --------------------------------------------------
    # Events
    # --------------------------------------------------

    if "event" in text:
        return 30

    # --------------------------------------------------
    # Cruises
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "cruise",
            "boat",
            "catamaran",
            "yacht",
        ]
    ):
        return 21

    # --------------------------------------------------
    # Guided tours
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "tour",
            "guided",
            "excursion",
        ]
    ):
        return 7

    # --------------------------------------------------
    # Museums / Attractions
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "museum",
            "gallery",
            "castle",
            "monument",
            "archaeological",
            "theme",
            "aquarium",
            "zoo",
        ]
    ):
        return 3

    # --------------------------------------------------
    # Fine dining
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "fine_dining",
            "fine dining",
            "michelin",
        ]
    ):
        return 14

    # --------------------------------------------------
    # Restaurants
    # --------------------------------------------------

    if "restaurant" in text:
        return 2

    # --------------------------------------------------
    # Hotels
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "hotel",
            "accommodation",
            "resort",
        ]
    ):
        return 14

    # --------------------------------------------------
    # Adventure activities
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "diving",
            "snorkeling",
            "rafting",
            "kayak",
            "paragliding",
            "ski",
            "snowboard",
        ]
    ):
        return 5

    # --------------------------------------------------
    # Generic ticketed attraction
    # --------------------------------------------------

    if ticket_required(place):
        return 2

    # --------------------------------------------------
    # Walk-in
    # --------------------------------------------------

    return 0


# =====================================================
# BOOKING STATUS
# =====================================================

def booking_status(place: dict) -> str:

    # --------------------------------------------------
    # Live booking status from provider
    # --------------------------------------------------

    live_status = safe_text(
        place.get(
            "live_booking_status"
        )
    )

    if live_status:
        return live_status

    # --------------------------------------------------
    # Availability from provider
    # --------------------------------------------------

    availability = safe_text(
        place.get(
            "availability"
        )
    ).lower()

    if availability in {
        "sold out",
        "fully booked",
        "unavailable",
    }:
        return "Sold Out"

    if availability in {
        "limited",
        "limited availability",
    }:
        return "Limited Availability"

    # --------------------------------------------------
    # Live event dates from Ticketmaster
    # --------------------------------------------------

    event_date = safe_text(
        place.get(
            "event_date"
        )
    )

    if event_date:

        try:

            # Ticketmaster normally returns YYYY-MM-DD
            event_dt = datetime.strptime(
                event_date[:10],
                "%Y-%m-%d",
            ).replace(
                tzinfo=timezone.utc
            )

            now = datetime.now(
                timezone.utc
            )

            days_until = (
                event_dt - now
            ).days

            if days_until < 0:
                return "Event Finished"

            if days_until == 0:
                return "Happening Today"

            if days_until <= 2:
                return (
                    f"Happening in {days_until} days "
                    "- Book Immediately"
                )

            if days_until <= 7:
                return (
                    f"Happening in {days_until} days "
                    "- Very Limited Availability"
                )

            if days_until <= 30:
                return (
                    f"Happening in {days_until} days "
                    "- Book Soon"
                )

            return (
                f"Happening in {days_until} days "
                "- Tickets Available"
            )

        except Exception:
            pass

    # --------------------------------------------------
    # Availability reported as available
    # --------------------------------------------------

    if availability in {
        "available",
        "available now",
    }:
        return "Available"

    # --------------------------------------------------
    # Reservation recommendations
    # --------------------------------------------------

    if reservation_required(place):

        days = advance_booking_days(
            place
        )

        if days >= 90:
            return (
                "Book Several Months Ahead"
            )

        if days >= 60:
            return (
                "Book At Least Two Months Ahead"
            )

        if days >= 30:
            return (
                "Book At Least One Month Ahead"
            )

        if days >= 14:
            return (
                "Advance Reservation Required"
            )

        if days >= 7:
            return (
                "Reservation Strongly Recommended"
            )

        if days >= 2:
            return (
                "Reservation Recommended"
            )

        return (
            "Booking Recommended"
        )

    # --------------------------------------------------
    # Ticketed attractions
    # --------------------------------------------------

    if ticket_required(place):

        if safe_text(
            place.get(
                "booking_url"
            )
        ):
            return (
                "Online Ticket Available"
            )

        return (
            "Ticket Required"
        )

    # --------------------------------------------------
    # Walk-in places
    # --------------------------------------------------

    return "Walk-in Friendly"


# =====================================================
# BOOKING PROVIDER
# =====================================================

def suggested_provider(place: dict) -> str:

    # --------------------------------------------------
    # Existing provider from API
    # --------------------------------------------------

    live_provider = safe_text(
        place.get(
            "booking_provider"
        )
    )

    if live_provider:
        return live_provider

    # --------------------------------------------------
    # Ticketmaster event already found
    # --------------------------------------------------

    if safe_text(
        place.get(
            "event_name"
        )
    ):
        return "Ticketmaster"

    text = category_text(place)

    name = safe_text(
        place.get(
            "name"
        )
    ).lower()

    # --------------------------------------------------
    # Hotels / Accommodation
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "hotel",
            "accommodation",
            "hostel",
            "resort",
            "guest_house",
            "guest house",
            "apartment",
            "villa",
            "room",
            "motel",
            "bnb",
            "airbnb",
            "lodging",
        ]
    ):
        return "Booking.com"

    # --------------------------------------------------
    # Flights
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "airport",
            "flight",
            "airline",
            "terminal",
            "departure",
            "arrival",
        ]
    ):
        return "Amadeus"

    # --------------------------------------------------
    # Restaurants requiring reservations
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "restaurant",
            "fine_dining",
            "fine dining",
            "michelin",
            "rooftop",
            "steakhouse",
            "seafood",
            "sushi",
            "bistro",
            "brasserie",
            "taverna",
            "grill",
        ]
    ):
        return "OpenTable"

    # --------------------------------------------------
    # Cafes and bars
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "cafe",
            "coffee",
            "bar",
            "wine_bar",
            "wine bar",
            "cocktail",
            "pub",
            "brewery",
        ]
    ):
        return "Google Places"

    # --------------------------------------------------
    # Tours and experiences
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "tour",
            "guided",
            "activity",
            "excursion",
            "experience",
            "cruise",
            "boat",
            "catamaran",
            "sailing",
            "yacht",
            "kayak",
            "rafting",
            "snorkeling",
            "diving",
            "paragliding",
            "ski",
            "snowboard",
            "surf",
            "hiking",
            "trekking",
            "wine",
            "vineyard",
            "winery",
            "cooking",
            "adventure",
        ]
    ):
        return "Viator"

    # --------------------------------------------------
    # Events and entertainment
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "concert",
            "festival",
            "event",
            "music",
            "show",
            "theatre",
            "opera",
            "arena",
            "stadium",
            "sports",
            "match",
            "game",
            "basketball",
            "football",
            "soccer",
            "tennis",
            "formula",
            "motogp",
            "f1",
        ]
    ):
        return "Ticketmaster"

    # --------------------------------------------------
    # Museums and ticketed attractions
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "museum",
            "gallery",
            "castle",
            "monument",
            "archaeological",
            "heritage",
            "historic",
            "historic_site",
            "historic site",
            "ruins",
            "tower",
            "palace",
            "theme",
            "theme_park",
            "theme park",
            "aquarium",
            "zoo",
            "observation",
            "skydeck",
            "viewpoint",
        ]
    ):
        return "Official Website"

    # --------------------------------------------------
    # Natural locations
    # --------------------------------------------------

    if any(
        x in text
        for x in [
            "beach",
            "park",
            "forest",
            "mountain",
            "lake",
            "waterfall",
            "nature",
        ]
    ):
        return "Direct Visit"

    # --------------------------------------------------
    # Name heuristics
    # --------------------------------------------------

    if any(
        x in name
        for x in [
            "hotel",
            "resort",
            "hostel",
            "suites",
        ]
    ):
        return "Booking.com"

    if any(
        x in name
        for x in [
            "museum",
            "gallery",
        ]
    ):
        return "Official Website"

    if any(
        x in name
        for x in [
            "airport",
        ]
    ):
        return "Amadeus"

    # --------------------------------------------------
    # Coordinates available but unknown type
    # --------------------------------------------------

    if (
        place.get("lat") is not None
        and place.get("lon") is not None
    ):
        return "Google Places"

    # --------------------------------------------------
    # Last fallback
    # --------------------------------------------------

    return "Direct Visit"


# =====================================================
# BOOKING CONFIDENCE
# =====================================================

def booking_confidence(place: dict) -> int:

    # --------------------------------------------------
    # Explicit live confidence from APIs
    # --------------------------------------------------

    live_confidence = place.get(
        "booking_confidence"
    )

    try:
        if live_confidence is not None:

            live_confidence = int(
                live_confidence
            )

            if 0 <= live_confidence <= 100:
                return live_confidence

    except Exception:
        pass

    provider = safe_text(
        place.get(
            "booking_provider"
        )
    )

    website = safe_text(
        place.get(
            "website"
        )
    )

    booking_url = safe_text(
        place.get(
            "booking_url"
        )
    )

    availability = safe_text(
        place.get(
            "availability"
        )
    )

    event_name = safe_text(
        place.get(
            "event_name"
        )
    )

    provider_data = place.get(
        "provider_data",
        {},
    ) or {}

    match_score = provider_data.get(
        "match_score",
        0,
    )

    score = 20

    # --------------------------------------------------
    # Provider reliability table
    # --------------------------------------------------

    provider_scores = {

        # Official ticket providers
        "Ticketmaster": 45,
        "Eventbrite": 44,

        # Hotels
        "Booking.com": 44,
        "Hotels.com": 43,
        "Expedia": 43,

        # Activities
        "Viator": 42,
        "GetYourGuide": 42,

        # Restaurants
        "OpenTable": 40,

        # Flights
        "Amadeus": 40,

        # Mapping providers
        "Google Places": 30,
        "Google Maps": 30,

        # Official sources
        "Official Website": 28,

        # Generic source
        "Direct Visit": 15,
    }

    score += provider_scores.get(
        provider,
        10,
    )

    # --------------------------------------------------
    # Booking URL exists
    # --------------------------------------------------

    if booking_url:
        score += 10

    # --------------------------------------------------
    # Official website exists
    # --------------------------------------------------

    if website:
        score += 5

    # --------------------------------------------------
    # Ticket requirement detected
    # --------------------------------------------------

    if ticket_required(place):
        score += 4

    # --------------------------------------------------
    # Reservation requirement detected
    # --------------------------------------------------

    if reservation_required(place):
        score += 4

    # --------------------------------------------------
    # Event detected
    # --------------------------------------------------

    if event_name:
        score += 8

    # --------------------------------------------------
    # Event date exists
    # --------------------------------------------------

    if safe_text(
        place.get(
            "event_date"
        )
    ):
        score += 5

    # --------------------------------------------------
    # Availability exists
    # --------------------------------------------------

    if availability:

        if availability.lower() in {
            "available",
            "available now",
        }:
            score += 6

        elif availability.lower() in {
            "limited availability",
            "limited",
        }:
            score += 4

        elif availability.lower() in {
            "sold out",
            "fully booked",
        }:
            score += 3

        else:
            score += 2

    # --------------------------------------------------
    # Pricing exists
    # --------------------------------------------------

    if place.get("price") is not None:
        score += 4

    if place.get("price_min") is not None:
        score += 2

    if place.get("price_max") is not None:
        score += 2

    # --------------------------------------------------
    # Coordinates increase confidence
    # --------------------------------------------------

    if (
        place.get("lat") is not None
        and place.get("lon") is not None
    ):
        score += 3

    # --------------------------------------------------
    # Exact place id exists
    # --------------------------------------------------

    if safe_text(
        place.get(
            "place_id"
        )
    ):
        score += 3

    # --------------------------------------------------
    # Ticketmaster relevance match
    # --------------------------------------------------

    try:
        match_score = int(
            match_score
        )

        score += min(
            10,
            match_score // 10,
        )

    except Exception:
        pass

    # --------------------------------------------------
    # Confidence bounds
    # --------------------------------------------------

    return max(
        0,
        min(
            int(score),
            100,
        ),
    )


# =====================================================
# BOOKING URL
# =====================================================

def booking_url(place: dict) -> str:
    # --------------------------------------------------
    # Live booking URL (highest priority)
    # --------------------------------------------------

    live_url = safe_text(
        place.get(
            "live_booking_url"
        )
    )

    if live_url:
        return live_url

    # --------------------------------------------------
    # Booking.com
    # --------------------------------------------------

    booking_com = safe_text(
        place.get(
            "bookingcom_url"
        )
    )

    if booking_com:
        return booking_com

    # --------------------------------------------------
    # Viator
    # --------------------------------------------------

    viator = safe_text(
        place.get(
            "viator_url"
        )
    )

    if viator:
        return viator

    # --------------------------------------------------
    # GetYourGuide
    # --------------------------------------------------

    gyg = safe_text(
        place.get(
            "getyourguide_url"
        )
    )

    if gyg:
        return gyg

    # --------------------------------------------------
    # OpenTable
    # --------------------------------------------------

    opentable = safe_text(
        place.get(
            "opentable_url"
        )
    )

    if opentable:
        return opentable

    # --------------------------------------------------
    # Ticketmaster
    # --------------------------------------------------

    ticketmaster = safe_text(
        place.get(
            "ticketmaster_url"
        )
    )

    if ticketmaster:
        return ticketmaster

    # --------------------------------------------------
    # Official Website
    # --------------------------------------------------

    website = safe_text(
        place.get(
            "website"
        )
    )

    if website:
        return website

    # --------------------------------------------------
    # Google Maps
    # --------------------------------------------------

    lat = place.get("lat")
    lon = place.get("lon")

    if lat and lon:
        return (
            "https://www.google.com/maps/search/?api=1"
            f"&query={lat},{lon}"
        )
    
    query = quote_plus(
        safe_text(place.get("name"))
    )
    
    if query:
        return (
            "https://www.google.com/maps/search/?api=1"
            f"&query={query}"
        )

    # --------------------------------------------------
    # Nothing available
    # --------------------------------------------------

    return ""


# =====================================================
# MAIN API
# =====================================================

def get_booking_info(place: dict) -> Dict:

    info = {
        "ticket_required": ticket_required(place),

        "reservation_required": reservation_required(place),

        "advance_booking_days": advance_booking_days(place),

        "booking_status": booking_status(place),

        "booking_provider": suggested_provider(place),

        "booking_url": booking_url(place),

        "booking_confidence": booking_confidence(place),

        "event_name": "",

        "event_date": "",

        "event_time": "",

        "price": None,

        "price_min": None,

        "price_max": None,

        "currency": "EUR",

        "availability": "",

        "provider_data": {},
    }

    # --------------------------------------------------
    # Real-time providers priority
    # --------------------------------------------------

    provider_search_functions = {
        "Ticketmaster": search_ticketmaster_booking,
        "Booking.com": search_bookingcom_booking,
        "OpenTable": search_opentable_booking,
        "Viator": search_viator_booking,
        "GetYourGuide": search_getyourguide_booking,
    }

    provider_confidence = {
        "Ticketmaster": 99,
        "Booking.com": 98,
        "OpenTable": 97,
        "Viator": 96,
        "GetYourGuide": 95,
        "Google Places": 90,
        "Official Website": 88,
        "Direct Visit": 60,
    }

    # --------------------------------------------------
    # Try Ticketmaster first because it is real API data
    # --------------------------------------------------

    try:

        ticketmaster_data = search_ticketmaster_booking(
            place
        )

        if ticketmaster_data:

            info.update(
                ticketmaster_data
            )

            info["booking_provider"] = (
                "Ticketmaster"
            )

            info["booking_confidence"] = 99

    except Exception as e:

        print(
            "[BOOKING SERVICE] "
            f"Ticketmaster lookup failed: {e}"
        )

    # --------------------------------------------------
    # Provider-specific lookup
    # --------------------------------------------------

    provider = info.get(
        "booking_provider"
    )

    search_function = (
        provider_search_functions.get(
            provider
        )
    )

    if (
        search_function
        and provider != "Ticketmaster"
    ):

        try:

            data = search_function(
                place
            )

            if data:

                info.update(
                    data
                )

                info[
                    "booking_provider"
                ] = provider

                info[
                    "booking_confidence"
                ] = provider_confidence.get(
                    provider,
                    90,
                )

        except Exception as e:

            print(
                "[BOOKING SERVICE] "
                f"{provider} lookup failed: {e}"
            )

    # --------------------------------------------------
    # Official website fallback
    # --------------------------------------------------

    if info.get(
        "booking_url"
    ):

        info[
            "booking_confidence"
        ] = max(
            info[
                "booking_confidence"
            ],
            85,
        )

    # --------------------------------------------------
    # Final consistency checks
    # --------------------------------------------------

    merged_place = {
        **place,
        **info,
    }

    info[
        "ticket_required"
    ] = ticket_required(
        merged_place
    )

    info[
        "reservation_required"
    ] = reservation_required(
        merged_place
    )

    info[
        "advance_booking_days"
    ] = advance_booking_days(
        merged_place
    )

    info[
        "booking_status"
    ] = booking_status(
        merged_place
    )

    info[
        "booking_provider"
    ] = suggested_provider(
        merged_place
    )

    info[
        "booking_url"
    ] = booking_url(
        merged_place
    )

    info[
        "booking_confidence"
    ] = booking_confidence(
        merged_place
    )

    return info


# =====================================================
# FUTURE API INTEGRATIONS
# =====================================================


def search_viator_booking(place):
    """
    Search for a matching activity on Viator.

    Current implementation:
    - Generates a Viator search URL
    - Estimates booking availability
    - Returns structured booking information

    Future:
    Replace this with the official Viator Partner API.
    """

    try:

        name = safe_text(place.get("name"))
        address = safe_text(place.get("address"))
        country = safe_text(place.get("country"))

        if not name:
            return None

        search_query = " ".join(
            part for part in [name, address, country] if part
        )

        search_url = (
            "https://www.viator.com/searchResults/all?"
            f"text={quote_plus(search_query)}"
        )

        return {

            "ticket_required": True,

            "reservation_required": True,

            "booking_url": search_url,

            "booking_provider": "Viator",

            "booking_status": "Book online",

            "availability": "Check live availability",

            "event_name": name,

            "event_date": "",

            "price": None,

            "currency": "EUR",

            "provider_data": {
                "provider": "Viator",
                "query": search_query,
            },
        }

    except Exception as e:

        print("[BOOKING SERVICE] Viator error:", e)

        return None


def search_bookingcom_booking(place):
    """
    Search for accommodation on Booking.com.

    Current implementation:
    - Generates a Booking.com search URL
    - Returns booking metadata

    Future:
    Replace with the official Booking.com API.
    """

    try:

        name = safe_text(place.get("name"))
        address = safe_text(place.get("address"))
        country = safe_text(place.get("country"))

        text = category_text(place)

        if (
            "hotel" not in text
            and "accommodation" not in text
            and "hostel" not in text
            and "resort" not in text
            and "apartment" not in text
        ):
            return None

        search_query = " ".join(
            part for part in [name, address, country] if part
        ).strip()

        booking_url = (
            "https://www.booking.com/searchresults.html?ss="
            + quote_plus(search_query)
        )

        return {

            "ticket_required": False,

            "reservation_required": True,

            "booking_provider": "Booking.com",

            "booking_status": "Book online",

            "booking_url": booking_url,

            "booking_confidence": 95,

            "availability": "Check live availability",

            "hotel_name": name,

            "check_in": "",

            "check_out": "",

            "price_per_night": None,

            "currency": "EUR",

            "provider_data": {
                "provider": "Booking.com",
                "query": search_query,
            },
        }

    except Exception as e:

        print("[BOOKING SERVICE] Booking.com error:", e)

        return None


def search_ticketmaster_booking(place):

    try:

        place_name = safe_text(
            place.get("name")
        )

        country = safe_text(
            place.get("country")
        )

        city = safe_text(
            place.get("city")
        )

        categories = category_text(
            place
        )

        # ---------------------------------------------
        # Ticketmaster only makes sense for events
        # ---------------------------------------------

        valid_keywords = [
            "concert",
            "festival",
            "event",
            "show",
            "theatre",
            "opera",
            "arena",
            "stadium",
            "sports",
            "music",
            "tour",
            "performance",
            "exhibition",
        ]

        if not any(
            keyword in categories
            for keyword in valid_keywords
        ):
            return None

        if not place_name:
            return None

        keyword = place_name

        if city:
            keyword += f" {city}"

        if country:
            keyword += f" {country}"

        events = search_events(
            keyword=keyword,
            size=15,
        )

        if not events:
            return None

        # ---------------------------------------------
        # Relevance scoring
        # ---------------------------------------------

        best_event = None
        best_score = -1

        for event in events:

            score = 0

            event_name = safe_text(
                event.get("name")
            ).lower()

            venue_name = safe_text(
                event.get("venue")
            ).lower()

            if place_name.lower() in event_name:
                score += 60

            if city.lower() and city.lower() in event_name:
                score += 15

            if city.lower() and city.lower() in venue_name:
                score += 10

            if country.lower() and country.lower() in event_name:
                score += 5

            if score > best_score:
                best_score = score
                best_event = event

        if best_event is None:
            return None

        # ---------------------------------------------
        # Venue extraction
        # ---------------------------------------------

        venue = ""

        if isinstance(
            best_event.get("venue"),
            dict,
        ):
            venue = safe_text(
                best_event["venue"].get(
                    "name"
                )
            )
        else:
            venue = safe_text(
                best_event.get(
                    "venue"
                )
            )

        # ---------------------------------------------
        # Booking urgency
        # ---------------------------------------------

        advance_days = 30

        try:

            event_date = safe_text(
                best_event.get(
                    "date"
                )
            )

            if event_date:

                event_dt = datetime.fromisoformat(
                    event_date.replace(
                        "Z",
                        "+00:00"
                    )
                )

                remaining_days = (
                    event_dt.date()
                    - datetime.utcnow().date()
                ).days

                if remaining_days > 90:
                    advance_days = 90
                elif remaining_days > 30:
                    advance_days = 30
                elif remaining_days > 14:
                    advance_days = 14
                elif remaining_days > 7:
                    advance_days = 7
                else:
                    advance_days = 2

        except Exception:
            pass

        return {

            "ticket_required": True,

            "reservation_required": True,

            "booking_provider": "Ticketmaster",

            "booking_status": "Live Event Available",

            "booking_url": safe_text(
                best_event.get(
                    "url"
                )
            ),

            "booking_confidence": min(
                99,
                70 + best_score
            ),

            "advance_booking_days": advance_days,

            "availability": safe_text(
                best_event.get(
                    "availability",
                    "Check live availability",
                )
            ),

            "event_name": safe_text(
                best_event.get(
                    "name"
                )
            ),

            "event_date": safe_text(
                best_event.get(
                    "date"
                )
            ),

            "event_time": safe_text(
                best_event.get(
                    "time"
                )
            ),

            "venue": venue,

            "price_min": best_event.get(
                "price_min"
            ),

            "price_max": best_event.get(
                "price_max"
            ),

            "currency": safe_text(
                best_event.get(
                    "currency",
                    "EUR",
                )
            ),

            "provider_data": {
                "provider": "Ticketmaster",
                "event_id": best_event.get(
                    "id"
                ),
                "match_score": best_score,
            },
        }

    except Exception as e:

        print(
            "[BOOKING SERVICE] "
            f"Ticketmaster error: {e}"
        )

        return None


def search_opentable_booking(place):
    """
    Search for restaurant reservations on OpenTable.

    Current implementation:
    - Generates an OpenTable search URL
    - Returns structured reservation information

    Future:
    Replace with the official OpenTable API.
    """

    try:

        name = safe_text(place.get("name"))
        address = safe_text(place.get("address"))
        country = safe_text(place.get("country"))

        text = category_text(place)

        if not any(
            x in text
            for x in [
                "restaurant",
                "fine_dining",
                "steakhouse",
                "seafood",
                "sushi",
                "italian",
                "greek",
                "french",
                "bistro",
                "brasserie",
                "taverna",
            ]
        ):
            return None

        search_query = " ".join(
            part for part in [name, address, country]
            if part
        ).strip()

        opentable_url = (
            "https://www.opentable.com/s?term="
            + quote_plus(search_query)
        )

        return {

            "ticket_required": False,

            "reservation_required": True,

            "booking_provider": "OpenTable",

            "booking_status": "Reserve online",

            "booking_url": opentable_url,

            "booking_confidence": 95,

            "advance_booking_days": 3,

            "restaurant_name": name,

            "availability": "Check live availability",

            "price_level": None,

            "rating": None,

            "provider_data": {
                "provider": "OpenTable",
                "query": search_query,
            },
        }

    except Exception as e:

        print("[BOOKING SERVICE] OpenTable error:", e)

        return None

