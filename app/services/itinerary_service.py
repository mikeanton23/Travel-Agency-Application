# -*- coding: utf-8 -*-

from app.services.geoapify_service import (
    search_places,
    get_categories_from_preferences,
)

from app.services.pricing_service import (
    get_place_pricing,
)

from app.services.transport_service import (
    get_transport_info,
)

from app.services.booking_service import (
    get_booking_info,
)

from app.services.weather_service import (
    WeatherService,
)


GENERIC_PLACE_NAMES = {
    "recommended place",
    "place",
    "unnamed",
    "restaurant",
    "cafe",
    "bar",
    "hotel",
    "museum",
    "park",
    "beach",
    "road",
    "street",
    "area",
    "station",
    "airport",
    "locality",
    "attraction",
    "tourist attraction",
}


def safe_text(value, default=""):
    value = str(value or "").strip()
    return value if value else default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def normalize_text(value):
    return safe_text(value).lower().strip()


def get_destination_name(destination):
    return safe_text(getattr(destination, "name", ""), "Selected destination")


def get_destination_country(destination):
    return safe_text(getattr(destination, "country", ""), "Unknown country")


def get_destination_continent(destination):
    return getattr(destination, "continent", None)


def get_feature_name(feature):
    props = feature.get("properties", {}) or {}

    name = (
        props.get("name")
        or props.get("address_line1")
        or props.get("formatted")
        or "Recommended place"
    )

    return safe_text(name, "Recommended place")


def get_feature_address(feature):
    props = feature.get("properties", {}) or {}
    return safe_text(
        props.get("formatted")
        or props.get("address_line2")
        or props.get("address_line1")
        or ""
    )


def get_feature_categories(feature):
    props = feature.get("properties", {}) or {}
    categories = props.get("categories", [])

    if not isinstance(categories, list):
        return []

    return [safe_text(c) for c in categories if safe_text(c)]


def is_generic_place_name(name):

    text = normalize_text(name)

    if not text:
        return True

    if text in GENERIC_PLACE_NAMES:
        return True

    if len(text) <= 4:
        return True

    if text.replace("-", "").replace(".", "").isdigit():
        return True

    if any(
        text.startswith(prefix)
        for prefix in [
            "m-",
            "a-",
            "e-",
            "d-",
            "n-",
        ]
    ):
        return True

    words = text.split()

    if len(words) <= 2 and any(
        word in GENERIC_PLACE_NAMES
        for word in words
    ):
        return True

    return False


def normalize_place(
    feature,
    daily_budget=120,
):
    props = feature.get("properties", {}) or {}
    geometry = feature.get("geometry", {}) or {}
    coords = geometry.get("coordinates", [])

    lon = coords[0] if len(coords) > 0 else None
    lat = coords[1] if len(coords) > 1 else None

    place = {
        "name": get_feature_name(feature),
        "address": get_feature_address(feature),
        "categories": get_feature_categories(feature),
        "lat": safe_float(lat),
        "lon": safe_float(lon),
        "place_id": safe_text(props.get("place_id")),
        "website": safe_text(props.get("website")),
        "phone": safe_text(props.get("phone")),
        "distance": safe_float(
            props.get("distance"),
            999999,
        ),
    }

    try:
        pricing = get_place_pricing(
            place=place,
            daily_budget=daily_budget,
        )
    except Exception:
        pricing = {}

    try:
        transport = get_transport_info(
            place=place,
        )
    except Exception:
        transport = {}

    try:
        booking = get_booking_info(
            place=place,
        )
    except Exception:
        booking = {}

    place["pricing"] = pricing
    place["transport"] = transport
    place["booking"] = booking

    place["ticket_required"] = booking.get(
        "ticket_required",
        pricing.get(
            "ticket_required",
            False,
        ),
    )

    place["reservation_required"] = booking.get(
        "reservation_required",
        False,
    )

    place["booking_provider"] = booking.get(
        "booking_provider",
        "",
    )
    
    place["booking_status"] = booking.get(
        "booking_status",
        "",
    )
    
    place["advance_booking_days"] = booking.get(
        "advance_booking_days",
        0,
    )
    
    place["booking_confidence"] = booking.get(
        "booking_confidence",
        0,
    )
    
    place["booking_url"] = booking.get(
        "booking_url",
        "",
    )
    
    place["event_name"] = booking.get(
        "event_name",
        "",
    )
    
    place["event_date"] = booking.get(
        "event_date",
        "",
    )
    
    place["website"] = safe_text(
        props.get("website")
    )
    
    place["opening_hours"] = safe_text(
        props.get("opening_hours")
    )
    
    place["rating"] = safe_float(
        props.get("rating"),
        0,
    )
    
    place["popularity"] = safe_float(
        props.get("rank", {}).get(
            "importance",
            0,
        ),
        0,
    )

    place["transport_mode"] = transport.get(
        "recommended_mode",
        "walk",
    )
    
    place["travel_time_minutes"] = transport.get(
        "travel_time_minutes",
        0,
    )

    ticket_cost = safe_float(
        pricing.get(
            "estimated_ticket_price",
            0,
        ),
        0,
    )

    food_cost = safe_float(
        pricing.get(
            "estimated_food_price",
            0,
        ),
        0,
    )

    transport_cost = safe_float(
        transport.get(
            "estimated_transport_cost",
            0,
        ),
        0,
    )
    
    place["estimated_total_cost"] = round(
        ticket_cost
        + food_cost
        + transport_cost,
        2,
    )
    
    place["transport_cost"] = round(
        transport_cost,
        2,
    )


    return place


def place_quality_score(place):

    name = safe_text(
        place.get("name")
    )

    address = safe_text(
        place.get("address")
    )

    categories = " ".join(
        str(c)
        for c in place.get(
            "categories",
            [],
        )
    ).lower()

    distance = safe_float(
        place.get(
            "distance",
            999999,
        ),
        999999,
    )

    score = 50

    # -----------------------------------
    # Basic information quality
    # -----------------------------------

    if is_generic_place_name(name):
        score -= 40

    if address:
        score += 8

    if (
        place.get("lat") is not None
        and place.get("lon") is not None
    ):
        score += 8

    # -----------------------------------
    # Category importance
    # -----------------------------------

    if any(
        x in categories
        for x in [
            "tourism",
            "sights",
            "attraction",
        ]
    ):
        score += 14

    if "museum" in categories:
        score += 10

    if any(
        x in categories
        for x in [
            "restaurant",
            "cafe",
            "bar",
        ]
    ):
        score += 8

    if any(
        x in categories
        for x in [
            "natural",
            "beach",
            "park",
            "viewpoint",
        ]
    ):
        score += 12

    if any(
        x in categories
        for x in [
            "hotel",
            "accommodation",
        ]
    ):
        score -= 15

    # -----------------------------------
    # Distance
    # -----------------------------------

    if distance <= 5000:
        score += 8

    elif distance <= 20000:
        score += 4

    elif distance >= 70000:
        score -= 8

    # -----------------------------------
    # Events
    # -----------------------------------

    if place.get("event_name"):
        score += 30

    # -----------------------------------
    # Booking quality
    # -----------------------------------

    if place.get("booking_url"):
        score += 10

    if place.get("website"):
        score += 8

    booking_confidence = safe_float(
        place.get(
            "booking_confidence",
            0,
        ),
        0,
    )

    if booking_confidence > 80:
        score += 8

    elif booking_confidence > 50:
        score += 4

    # -----------------------------------
    # Travel time
    # -----------------------------------

    travel_time = safe_float(
        place.get(
            "travel_time_minutes",
            0,
        ),
        0,
    )

    if travel_time <= 20:
        score += 12

    elif travel_time <= 40:
        score += 6

    elif travel_time >= 90:
        score -= 8

    # -----------------------------------
    # Ticketed attractions are often
    # more important landmarks
    # -----------------------------------

    if place.get("ticket_required"):
        score += 6

    # -----------------------------------
    # Ratings
    # -----------------------------------

    rating = safe_float(
        place.get(
            "rating",
            0,
        ),
        0,
    )

    if rating >= 4.8:
        score += 12

    elif rating >= 4.5:
        score += 8

    elif rating >= 4.0:
        score += 4

    elif 0 < rating < 3.0:
        score -= 10

    # -----------------------------------
    # Popularity score from Geoapify
    # -----------------------------------

    popularity = safe_float(
        place.get(
            "popularity",
            0,
        ),
        0,
    )

    if popularity > 0.9:
        score += 10

    elif popularity > 0.7:
        score += 6

    elif popularity > 0.5:
        score += 3

    # -----------------------------------
    # Final normalization
    # -----------------------------------

    return max(
        0,
        min(
            100,
            int(score),
        ),
    )


def unique_places(places):
    seen = set()
    result = []

    for place in places:
        name = safe_text(place.get("name"))
        address = safe_text(place.get("address"))

        if is_generic_place_name(name):
            continue

        key = (
            normalize_text(name),
            round(
                safe_float(
                    place.get("lat"),
                    0,
                ),
                4,
            ),
            round(
                safe_float(
                    place.get("lon"),
                    0,
                ),
                4,
            ),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(place)

    result.sort(
        key=lambda p: (
            place_quality_score(p),
            -safe_float(p.get("distance"), 999999),
        ),
        reverse=True,
    )

    return result


def classify_place(place):
    category_text = " ".join(str(c) for c in place.get("categories", [])).lower()

    if "restaurant" in category_text:
        return "restaurant"

    if "cafe" in category_text:
        return "cafe"

    if "bar" in category_text or "nightclub" in category_text:
        return "evening"

    if "hotel" in category_text or "accommodation" in category_text:
        return "hotel"

    if any(x in category_text for x in ["museum", "sights", "tourism", "attraction"]):
        return "attraction"

    if any(x in category_text for x in ["natural", "beach", "park", "viewpoint"]):
        return "nature"

    return "place"


def split_places_by_day(places, days):
    days = max(1, safe_int(days, 5))
    buckets = [[] for _ in range(days)]

    for index, place in enumerate(places or []):
        buckets[index % days].append(place)

    return buckets


def build_day_plan(day_number, day_places):

    # -----------------------------------
    # Sort by distance
    # -----------------------------------

    day_places = sorted(
        day_places,
        key=lambda p: (
    
            -place_quality_score(p),
    
            safe_float(
                p.get("travel_time_minutes"),
                9999,
            ),
    
            safe_float(
                p.get("distance"),
                999999,
            ),
    
        )
    )

    attractions = []
    food = []
    cafes = []
    evening = []
    events = []
    flexible = []

    for place in day_places:

        if place.get("event_name"):
            events.append(place)
            continue

        kind = classify_place(place)

        if kind in ["attraction", "nature"]:
            attractions.append(place)

        elif kind == "restaurant":
            food.append(place)

        elif kind == "cafe":
            cafes.append(place)

        elif kind == "evening":
            evening.append(place)

        elif kind == "hotel":
            continue

        else:
            flexible.append(place)

    morning = []
    afternoon = []
    night = []

    # -----------------------------------
    # Morning
    # -----------------------------------

    morning.extend(
        attractions[:2]
    )

    if not morning and flexible:
        morning.append(
            flexible.pop(0)
        )

    # -----------------------------------
    # Afternoon
    # -----------------------------------

    if cafes:
        afternoon.append(
            cafes[0]
        )

    afternoon.extend(
        attractions[2:5]
    )

    if food:
        afternoon.append(
            food[0]
        )

    if not afternoon and flexible:
        afternoon.append(
            flexible.pop(0)
        )

    # -----------------------------------
    # Evening
    # -----------------------------------

    if events:

        night.extend(
            events[:2]
        )

    elif evening:

        night.extend(
            evening[:2]
        )

    elif len(food) > 1:

        night.append(
            food[1]
        )

    elif flexible:

        night.append(
            flexible.pop(0)
        )

    # -----------------------------------
    # Fill gaps
    # -----------------------------------

    while len(morning) < 2 and flexible:
        morning.append(
            flexible.pop(0)
        )

    while len(afternoon) < 3 and flexible:
        afternoon.append(
            flexible.pop(0)
        )

    while len(night) < 2 and flexible:
        night.append(
            flexible.pop(0)
        )

    # -----------------------------------
    # Metrics
    # -----------------------------------

    day_cost = round(
        sum(
            safe_float(
                p.get(
                    "estimated_total_cost",
                    0,
                ),
                0,
            )
            for p in (
                morning
                + afternoon
                + night
            )
        ),
        2,
    )

    return {
        "day": day_number,

        "morning": morning[:2],

        "afternoon": afternoon[:3],

        "evening": night[:2],

        "estimated_day_cost": day_cost,

        "places_count": (
            len(morning)
            + len(afternoon)
            + len(night)
        ),

        "has_event": len(events) > 0,
    }


def fallback_day_plan(day_number):
    return {
        "day": day_number,
        "morning": [],
        "afternoon": [],
        "evening": [],
    }


async def create_itinerary(
    destination,
    days=5,
    user_text="",
    travelers="",
    budget=120,
):

    days = max(
        1,
        min(
            safe_int(days, 5),
            30,
        ),
    )

    name = get_destination_name(destination)
    country = get_destination_country(destination)
    continent = get_destination_continent(destination)

    lat = getattr(
        destination,
        "latitude",
        None,
    )

    lon = getattr(
        destination,
        "longitude",
        None,
    )

    places = []
    day_plans = []

    estimated_trip_cost = 0
    ticketed_places = 0
    reservation_places = 0
    bookable_places = 0

    total_budget = (
        safe_float(
            budget,
            0,
        ) * days
    )

    remaining_budget = total_budget
    budget_usage_percent = 0

    weather = None
    forecast = []

    # --------------------------------------------------
    # WEATHER
    # --------------------------------------------------

    if lat is not None and lon is not None:

        weather_service = WeatherService()

        try:

            weather = await weather_service.destination_weather(
                destination,
            )

            forecast = (
                await weather_service.destination_daily_forecast(
                    destination,
                    days=min(days, 7),
                )
            )

        except Exception as e:

            print(
                "[ITINERARY WEATHER ERROR]",
                e,
            )

        finally:

            await weather_service.close()

    # --------------------------------------------------
    # No coordinates -> return weather only
    # --------------------------------------------------

    if lat is None or lon is None:

        return {
            "destination": f"{name}, {country}",
            "country": country,
            "continent": continent,
            "budget": budget,
            "days_count": days,
            "total_budget": round(
                total_budget,
                2,
            ),
            "estimated_trip_cost": 0,
            "remaining_budget_estimate": round(
                total_budget,
                2,
            ),
            "budget_usage_percent": 0,
            "ticketed_places": 0,
            "reservation_places": 0,
            "bookable_places": 0,
            "places": [],
            "days": [],
            "weather": weather,
            "forecast": forecast,
            "summary": (
                f"Destination coordinates for "
                f"{name} could not be resolved."
            ),
        }

    # --------------------------------------------------
    # Preferences
    # --------------------------------------------------

    categories = (
        get_categories_from_preferences(
            user_text,
            travelers,
        )
        or []
    )

    extra_categories = [
        "tourism.attraction",
        "tourism.sights",
        "catering.restaurant",
        "catering.cafe",
        "catering.bar",
        "entertainment",
        "natural",
        "leisure.park",
        "beach",
    ]

    for category in extra_categories:

        if category not in categories:
            categories.append(category)

    print("\n[ITINERARY] Creating itinerary")
    print(f"[ITINERARY] Destination: {name}, {country}")
    print(f"[ITINERARY] Days: {days}")
    print(f"[ITINERARY] Categories: {categories}")

    # --------------------------------------------------
    # Search places
    # --------------------------------------------------

    try:

        features = search_places(
            lat=lat,
            lon=lon,
            categories=categories,
            radius=70000,
            limit=min(
                100,
                max(
                    35,
                    days * 14,
                ),
            ),
        )

    except Exception as e:

        print(
            f"[ITINERARY ERROR] "
            f"Geoapify places failed: {e}"
        )

        features = []

    # --------------------------------------------------
    # Normalize places
    # --------------------------------------------------

    places = [
        normalize_place(
            feature,
            daily_budget=budget,
        )
        for feature in features
    ]

    places = unique_places(places)

    places.sort(
        key=lambda p: (
            -place_quality_score(p),
            p.get("event_name") == "",
            safe_float(
                p.get(
                    "travel_time_minutes",
                    999,
                ),
                999,
            ),
            safe_float(
                p.get(
                    "estimated_total_cost",
                    99999,
                ),
                99999,
            ),
        )
    )

    if len(places) > days * 8:
        places = places[: days * 8]

    # --------------------------------------------------
    # Daily plans
    # --------------------------------------------------

    day_chunks = split_places_by_day(
        places,
        days,
    )

    for index, chunk in enumerate(
        day_chunks,
        start=1,
    ):

        if chunk:

            day_plans.append(
                build_day_plan(
                    index,
                    chunk,
                )
            )

        else:

            day_plans.append(
                fallback_day_plan(
                    index,
                )
            )

    # --------------------------------------------------
    # Cost debug
    # --------------------------------------------------

    print(
        "\n========== COST DEBUG =========="
    )

    for p in places[:15]:

        print(
            f"{p.get('name')} | "
            f"Cost={p.get('estimated_total_cost',0)} | "
            f"Ticket={p.get('ticket_required',False)} | "
            f"Reservation={p.get('reservation_required',False)}"
        )

    print(
        "================================\n"
    )

    # --------------------------------------------------
    # Statistics
    # --------------------------------------------------

    estimated_trip_cost = sum(
        safe_float(
            p.get(
                "estimated_total_cost",
                0,
            ),
            0,
        )
        for p in places
    )

    ticketed_places = sum(
        1
        for p in places
        if p.get(
            "ticket_required",
            False,
        )
    )

    reservation_places = sum(
        1
        for p in places
        if p.get(
            "reservation_required",
            False,
        )
    )

    bookable_places = sum(
        1
        for p in places
        if p.get(
            "booking_url",
            "",
        )
    )

    remaining_budget = (
        total_budget
        - estimated_trip_cost
    )

    budget_usage_percent = (
        (
            estimated_trip_cost
            / total_budget
        )
        * 100
        if total_budget > 0
        else 0
    )

    # --------------------------------------------------
    # Return
    # --------------------------------------------------

    return {

        "destination":
            f"{name}, {country}",

        "country":
            country,

        "continent":
            continent,

        "budget":
            budget,

        "days_count":
            days,

        "total_budget":
            round(
                total_budget,
                2,
            ),

        "estimated_trip_cost":
            round(
                estimated_trip_cost,
                2,
            ),

        "remaining_budget_estimate":
            round(
                remaining_budget,
                2,
            ),

        "budget_usage_percent":
            round(
                budget_usage_percent,
                1,
            ),

        "ticketed_places":
            ticketed_places,

        "reservation_places":
            reservation_places,

        "bookable_places":
            bookable_places,

        "places":
            places,

        "days":
            day_plans,

        "weather":
            weather,

        "forecast":
            forecast,

        "summary": (
            f"Generated from real nearby places "
            f"around {name}, balanced by attractions, "
            f"food stops, cafes, nature and evening "
            f"activities."
        ),
    }


def _place_markdown(place):
    lines = []

    lines.append(
        f"- **{safe_text(place.get('name'))}**"
    )

    address = safe_text(
        place.get("address")
    )

    if address:
        lines.append(
            f"  - {address}"
        )

    categories = place.get(
        "categories",
        [],
    )

    if categories:
        lines.append(
            f"  - Type: {', '.join(categories[:3])}"
        )

    cost = safe_float(
        place.get(
            "estimated_total_cost",
            0,
        ),
        0,
    )

    if cost > 0:
        lines.append(
            f"  - Estimated cost: {cost:.2f}"
        )

    if place.get("ticket_required"):
        ticket_price = (
            place.get("pricing", {})
            .get("estimated_ticket_price", 0)
        )
    
        lines.append(
            f"  - Ticket required (~{ticket_price:.2f})"
        )

    if place.get("reservation_required"):
        lines.append(
            "  - Reservation recommended"
        )
    
    booking_provider = safe_text(
        place.get(
            "booking_provider"
        )
    )
    
    if booking_provider:
        lines.append(
            f"  - Booking Provider: {booking_provider}"
        )
    
        
    rating = safe_float(
        place.get("rating"),
        0,
    )
    
    if rating > 0:
        lines.append(
            f"  - Rating: {rating:.1f}"
        )
    
    travel_time = safe_float(
        place.get(
            "travel_time_minutes",
            0,
        ),
        0,
    )
    
    if travel_time > 0:
        lines.append(
            f"  - Travel Time: {travel_time:.0f} min"
        ) 
    
    opening = safe_text(
        place.get(
            "opening_hours"
        )
    )
    
    if opening:
        lines.append(
            f"  - Opening Hours: {opening}"
        )
               
    event_name = safe_text(
        place.get(
            "event_name"
        )
    )
    
    if event_name:
        lines.append(
            f"  - Event: {event_name}"
        )
        
    event_date = safe_text(
        place.get(
            "event_date"
        )
    )
    
    if event_date:
        lines.append(
            f"  - Event Date: {event_date}"
        )
        
    transport = safe_text(
        place.get(
            "transport_mode"
        )
    )

    if transport:
        lines.append(
            f"  - Transport: {transport}"
        )
    
    transport_cost = safe_float(
        place.get(
            "transport_cost",
            0,
        ),
        0,
    )
    
    if transport_cost > 0:
        lines.append(
            f"  - Transport Cost: {transport_cost:.2f}"
        )
    
    booking_url = safe_text(
        place.get(
            "booking_url"
        )
    )

    if booking_url:
        lines.append(
            f"  - Booking Link: {booking_url}"
        )

    return lines


def itinerary_to_markdown(itinerary):
    if not itinerary or not itinerary.get("days"):
        return "No itinerary could be generated for this destination."

    lines = []

    lines.append(f"# {itinerary.get('destination')} Travel Plan")
    lines.append("")
    lines.append(safe_text(itinerary.get("summary")))
    lines.append("")
    lines.append(f"**Budget:** {itinerary.get('budget')} EUR/day")
    lines.append(f"**Estimated Trip Cost:** "f"{itinerary.get('estimated_trip_cost', 0):.2f}")
    lines.append(f"**Remaining Budget:** "f"{itinerary.get('remaining_budget_estimate', 0):.2f}")
    lines.append(f"**Total Budget:** "f"{itinerary.get('total_budget', 0):.2f}")
    lines.append(f"**Budget Usage:** "f"{itinerary.get('budget_usage_percent', 0):.1f}%")
    lines.append(f"**Ticketed Attractions:** "f"{itinerary.get('ticketed_places', 0)}")
    lines.append(f"**Reservations Recommended:** "f"{itinerary.get('reservation_places', 0)}")
    lines.append(f"**Booking Links Available:** "f"{itinerary.get('bookable_places', 0)}")
    lines.append(f"**Days:** {itinerary.get('days_count')}")
    lines.append("")

    for day in itinerary["days"]:
        lines.append(f"## Day {day['day']}")
        lines.append("")

        lines.append("### Morning")
        if day.get("morning"):
            for place in day["morning"]:
                lines.extend(_place_markdown(place))
        else:
            lines.append("- Relaxed breakfast, orientation walk, and flexible local discovery.")

        lines.append("")
        lines.append("### Afternoon")
        if day.get("afternoon"):
            for place in day["afternoon"]:
                lines.extend(_place_markdown(place))
        else:
            lines.append("- Explore nearby streets, cafes, viewpoints, or local food spots.")

        lines.append("")
        lines.append("### Evening")
        if day.get("evening"):
            for place in day["evening"]:
                lines.extend(_place_markdown(place))
        else:
            lines.append("- Dinner, sunset walk, or a relaxed evening near your base.")

        lines.append("")

    lines.append("## Smart Travel Notes")
    lines.append("")
    lines.append("- Keep the first day lighter if arrival time is late.")
    lines.append("- Group nearby places together to avoid unnecessary transport.")
    lines.append("- Use the itinerary as a realistic base, not a strict schedule.")
    lines.append("- If a place looks too far away, replace it with a closer cafe, viewpoint, or local walk.")

    return "\n".join(lines)