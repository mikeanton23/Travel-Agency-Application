# -*- coding: utf-8 -*-

import requests

from app.utils.config import OLLAMA_MODEL


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TIMEOUT = 240


def _safe_text(value, default="") -> str:
    value = str(value or "").strip()
    return value if value else default


def _safe_number(value, default=0):
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=5):
    try:
        value = int(float(value))
        return max(1, min(value, 30))
    except Exception:
        return default


def _destination_name(destination) -> str:
    return _safe_text(getattr(destination, "name", ""), "Selected destination")


def _destination_country(destination) -> str:
    return _safe_text(getattr(destination, "country", ""), "Unknown country")


def _get_attr(destination, attr: str, default=""):
    try:
        return getattr(destination, attr, default)
    except Exception:
        return default


def _format_list(values) -> str:
    if not values:
        return "None"

    if isinstance(values, str):
        return _safe_text(values, "None")

    try:
        clean = [str(v).strip() for v in values if str(v).strip()]
        return ", ".join(clean) if clean else "None"
    except Exception:
        return "None"


def _clean_markdown(text: str) -> str:
    text = _safe_text(text)

    if not text:
        return ""

    lowered = text.lower()

    for prefix in ["```markdown", "```md", "```"]:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    if text.endswith("```"):
        text = text[:-3].strip()

    return text


def _destination_intelligence_context(destination) -> str:
    hidden_gem_score = _get_attr(destination, "hidden_gem_score", None)
    crowd_level = _get_attr(destination, "crowd_level", None)
    budget_realism = _get_attr(destination, "budget_realism", None)
    risk_flags = _get_attr(destination, "risk_flags", [])
    travel_dna_match = _get_attr(destination, "travel_dna_match", None)
    local_authenticity_score = _get_attr(destination, "local_authenticity_score", None)
    walking_difficulty = _get_attr(destination, "walking_difficulty", None)
    tourist_trap_risk = _get_attr(destination, "tourist_trap_risk", None)
    trip_mood = _get_attr(destination, "trip_mood", None)
    daily_energy_level = _get_attr(destination, "daily_energy_level", None)
    budget_reality_check = _get_attr(destination, "budget_reality_check", None)
    regret_predictor = _get_attr(destination, "regret_predictor", [])
    smart_timing_tip = _get_attr(destination, "smart_timing_tip", None)
    trip_twin_label = _get_attr(destination, "trip_twin_label", None)

    return f"""
Destination Intelligence:
- Hidden-gem score: {hidden_gem_score if hidden_gem_score is not None else "Unknown"}/100
- AI Trip Twin match: {travel_dna_match if travel_dna_match is not None else "Unknown"}/100
- Trip Twin label: {trip_twin_label or "Unknown"}
- Trip mood: {trip_mood or "Unknown"}
- Daily energy level: {daily_energy_level or "Unknown"}
- Crowd level: {crowd_level or "Unknown"}
- Budget realism: {budget_realism or "Unknown"}
- Budget reality check: {budget_reality_check or "Unknown"}
- Local authenticity score: {local_authenticity_score if local_authenticity_score is not None else "Unknown"}/100
- Walking difficulty: {walking_difficulty or "Unknown"}
- Tourist-trap risk: {tourist_trap_risk or "Unknown"}
- Risk flags: {_format_list(risk_flags)}
- Regret predictor: {_format_list(regret_predictor)}
- Smart timing tip: {smart_timing_tip or "Unknown"}
""".strip()

def _itinerary_budget_context(itinerary=None) -> str:
    if not itinerary:
        return ""

    total_budget = _safe_number(
        itinerary.get("budget", 0)
    ) * _safe_int(
        itinerary.get("days_count", 0),
        0,
    )

    estimated_trip_cost = _safe_number(
        itinerary.get(
            "estimated_trip_cost",
            0,
        )
    )

    remaining_budget = _safe_number(
        itinerary.get(
            "remaining_budget_estimate",
            0,
        )
    )

    budget_usage = 0

    if total_budget > 0:
        budget_usage = round(
            (
                estimated_trip_cost
                / total_budget
            ) * 100,
            1,
        )

    return f"""
Budget Intelligence:
- Total budget: {total_budget}
- Estimated trip cost: {estimated_trip_cost}
- Remaining budget: {remaining_budget}
- Budget usage: {budget_usage}
""".strip()


def _itinerary_booking_context(itinerary=None) -> str:
    if not itinerary:
        return ""

    tickets_required = 0
    reservations_required = 0
    booking_links_available = 0

    for place in itinerary.get(
        "places",
        [],
    ):
        if place.get(
            "ticket_required",
            False,
        ):
            tickets_required += 1

        if place.get(
            "reservation_required",
            False,
        ):
            reservations_required += 1

        if place.get(
            "booking_url",
            "",
        ):
            booking_links_available += 1

    return f"""
Booking Intelligence:
- Ticketed attractions: {tickets_required}
- Reservations recommended: {reservations_required}
- Booking links available: {booking_links_available}
""".strip()


def _itinerary_transport_context(itinerary=None) -> str:
    if not itinerary:
        return ""

    transport_modes = []

    for place in itinerary.get(
        "places",
        [],
    ):
        mode = _safe_text(
            place.get(
                "transport_mode",
                "",
            )
        )

        if mode:
            transport_modes.append(mode)

    if not transport_modes:
        return ""

    unique_modes = sorted(
        set(transport_modes)
    )

    return f"""
Transport Intelligence:
- Common transport modes: {', '.join(unique_modes)}
- Transport planning has already been estimated for itinerary locations.
""".strip()

def _is_bad_ai_response(text: str) -> bool:
    value = _safe_text(text).lower()

    if not value:
        return True

    bad_markers = [
        "ai plan error",
        "no ai response generated",
        "error:",
        "exception",
        "traceback",
        "ollama is not running",
        "took too long",
    ]

    return any(marker in value for marker in bad_markers)


def _fallback_plan(
    destination,
    itinerary_markdown="",
    user_text="",
    travelers="",
    month="",
    budget=0,
    days=5,
    itinerary=None,
):
    name = _destination_name(destination)
    country = _destination_country(destination)
    days = _safe_int(days, 5)
    itinerary_markdown = _clean_markdown(itinerary_markdown)

    return f"""# {name}, {country} Travel Plan

## Why this trip fits you

This trip is designed around your preferences, travel month, budget, travel style, and destination intelligence signals.

## AI Trip Twin Summary

- Destination: {name}, {country}
- Travelers: {_safe_text(travelers, "Not specified")}
- Month: {_safe_text(month, "Not specified")}
- Budget: {_safe_number(budget):.0f} EUR/day
- Duration: {days} days

## Destination Intelligence Card

{_destination_intelligence_context(destination)}

{_itinerary_budget_context(itinerary)}

{_itinerary_booking_context(itinerary)}

{_itinerary_transport_context(itinerary)}

## Day-by-day plan

{itinerary_markdown or "Use the selected destination as the base and plan each day around nearby sights, food spots, walking areas, relaxing experiences, and flexible discovery time."}

## Smart travel strategy

- Start popular places early in the morning.
- Keep afternoons flexible for cafes, viewpoints, beaches, or local neighborhoods.
- Avoid overloading the itinerary with too many distant places in one day.
- Choose local restaurants instead of tourist-heavy streets.

## Budget strategy

- Prioritize local food, walking routes, and public transport.
- Keep one low-cost discovery day.
- Use the budget for one memorable experience instead of many average ones.

## Things to avoid

- Planning every hour too tightly.
- Choosing only famous attractions.
- Ignoring transport time between places.
- Eating only in the most tourist-heavy areas.
"""


def generate_travel_plan(destination, user_text, travelers, month, budget, days=5):
    name = _destination_name(destination)
    country = _destination_country(destination)
    days = _safe_int(days, 5)

    prompt = f"""
You are a premium travel planner for an innovative travel application.

Create a practical, beautiful, realistic, and personalized travel plan.

Critical rules:
- Return only Markdown.
- Do not wrap the answer in code fences.
- Do not invent impossible logistics.
- Keep the plan realistic for the budget.
- Prefer authentic, local, memorable experiences.
- Include hidden-gem style ideas when relevant.
- Include smart crowd-avoidance and tourist-trap avoidance.
- Include an "AI Trip Twin" section.
- Include a "Destination Intelligence Card" section.
- Do not mention that you are an AI.
- Do not mention internal scoring systems as exact facts unless provided below.
- If data is unknown, write practical flexible advice instead of pretending certainty.

Destination:
{name}, {country}

Month:
{_safe_text(month, "Not specified")}

Travelers:
{_safe_text(travelers, "Not specified")}

Budget per day:
{_safe_number(budget):.0f} EUR

Trip duration:
{days} days

User preferences:
{_safe_text(user_text, "No extra preferences provided.")}

{_destination_intelligence_context(destination)}

Return exactly this Markdown structure:

# {name}, {country} Travel Plan

## Destination Summary

## AI Trip Twin

## Destination Intelligence Card

## Why It Matches

## Day-by-Day Itinerary

## Hidden-Gem Experiences

## Local Taste Map

## Smart Timing & Crowd Strategy

## Tourist-Trap Avoidance

## Budget Strategy

## Flexible Alternatives

## Things To Avoid
""".strip()

    result = _call_ollama(prompt)

    if _is_bad_ai_response(result):
        return _fallback_plan(
            destination=destination,
            user_text=user_text,
            travelers=travelers,
            month=month,
            budget=budget,
            days=days,
        )

    return _clean_markdown(result)


def enhance_itinerary_with_ai(
    destination,
    itinerary_markdown,
    user_text,
    travelers,
    month,
    budget,
    days=5,
    itinerary=None,
):
    name = _destination_name(destination)
    country = _destination_country(destination)
    days = _safe_int(days, 5)
    itinerary_markdown = _clean_markdown(itinerary_markdown)

    prompt = f"""
You are a premium travel planner for an innovative travel application.

Your job:
Improve the following real itinerary and make it feel like a high-end travel product.

Critical rules:
- Return only Markdown.
- Do not wrap the answer in code fences.
- Do NOT invent fake place names.
- Keep and reuse the real places from the provided itinerary.
- Do not remove real places.
- If the itinerary has limited places, say that some parts should stay flexible.
- Keep the plan realistic for the user's budget.
- Make it practical, beautiful, human, and easy to read.
- Add smart timing, crowd-avoidance, pacing, local experience, and budget advice.
- Add AI Trip Twin and Destination Intelligence Card sections.
- Add tourist-trap avoidance.
- Do not mention Geoapify.
- Do not mention that you are an AI.
- If the real itinerary has weak or generic places, improve the pacing but do not invent named replacements.
- Mention ticket requirements when relevant.
- Mention reservation recommendations when relevant.
- Mention booking opportunities when available.
- Mention transport practicality.
- Mention transport recommendations when useful.
- Mention budget health if budget usage exceeds 85%.
- Mention expensive attractions if they significantly affect the budget.
- Do not invent ticket prices.
- Do not invent booking links.

Destination:
{name}, {country}

Month:
{_safe_text(month, "Not specified")}

Travelers:
{_safe_text(travelers, "Not specified")}

Budget per day:
{_safe_number(budget):.0f} EUR

Trip duration:
{days} days

User preferences:
{_safe_text(user_text, "No extra preferences provided.")}

{_destination_intelligence_context(destination)}

{_itinerary_budget_context(itinerary)}

{_itinerary_booking_context(itinerary)}

{_itinerary_transport_context(itinerary)}

Real itinerary:
{itinerary_markdown}

Return exactly this Markdown structure:

# {name}, {country} Travel Plan

## Why this trip fits you

## AI Trip Twin

## Destination Intelligence Card

## Trip personality

## Day-by-day plan

## Hidden-gem angle

## Best moments to experience

## Food & cafe suggestions

## Crowd-avoidance strategy

## Tourist-trap avoidance

## Budget strategy

## Flexible alternatives

## Things to avoid
""".strip()

    result = _call_ollama(prompt)

    if _is_bad_ai_response(result):
        return _fallback_plan(
            destination=destination,
            itinerary_markdown=itinerary_markdown,
            user_text=user_text,
            travelers=travelers,
            month=month,
            budget=budget,
            days=days,
            itinerary=itinerary,
        )

    return _clean_markdown(result)


def _call_ollama(prompt: str):
    prompt = _safe_text(prompt)

    if not prompt:
        return "AI plan error: Empty prompt."

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.58,
                    "top_p": 0.9,
                    "num_ctx": 8192,
                    "repeat_penalty": 1.1,
                },
            },
            timeout=OLLAMA_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()
        result = _safe_text(data.get("response"))

        if not result:
            return "No AI response generated."

        return _clean_markdown(result)

    except requests.exceptions.ConnectionError:
        return (
            "AI plan error: Ollama is not running. "
            "Start it with `ollama serve` and make sure the selected model is installed."
        )

    except requests.exceptions.Timeout:
        return "AI plan error: Ollama took too long to respond."

    except Exception as e:
        return f"AI plan error: {str(e)}"