# -*- coding: utf-8 -*-

"""
Travel Intelligence Score — explainable, real-data-only scoring.

Replaces the heuristic ``recommendation_engine`` scoring with twelve
match dimensions. Contract:

* Every dimension is computed **only** from real inputs
  (:class:`DestinationSignals`). If the data needed for a dimension is
  missing, the dimension returns ``score=None`` with a
  "insufficient data" reason — it never invents a number.
* Every score explains WHY, citing the actual values used.
* The overall score is the interest-weighted mean of *available*
  dimensions, reported together with ``coverage`` (how much data
  backed it) and labeled ``kind="ai_score"`` for the UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------

@dataclass
class DestinationSignals:
    """Real measurements about a destination. All optional; scorers
    check for what they need. Populated by
    :mod:`app.services.intelligence.signals` from live APIs."""

    # Numbeo (cost_service) — average real prices in `currency`
    currency: Optional[str] = None
    meal_inexpensive: Optional[float] = None
    cappuccino: Optional[float] = None
    beer: Optional[float] = None
    transport_ticket: Optional[float] = None
    taxi_per_km: Optional[float] = None

    # Real hotel quotes (Amadeus) — median nightly total
    hotel_median_nightly: Optional[float] = None
    hotel_count: Optional[int] = None
    hotel_ratings: List[float] = field(default_factory=list)

    # Climate normals for the travel month (Open-Meteo climate API)
    month: Optional[int] = None
    temp_max_avg_c: Optional[float] = None
    rain_days: Optional[float] = None            # days with >=1mm in month
    sunshine_hours_per_day: Optional[float] = None

    # POI counts within the destination radius (Geoapify)
    poi: Dict[str, int] = field(default_factory=dict)
    # expected keys: restaurants, cafes, bars_clubs, museums, monuments,
    # parks, natural, beaches, playgrounds, theme_parks, sports_outdoor

    # Numbeo indices
    safety_index: Optional[float] = None         # 0..100

    # Crowd signals (no free global source — must be supplied)
    annual_visitors_millions: Optional[float] = None
    population: Optional[int] = None


@dataclass
class UserProfile:
    budget_per_day: Optional[float] = None       # in signals.currency
    month: Optional[int] = None
    preferred_temp_c: tuple = (18.0, 27.0)
    interests: List[str] = field(default_factory=list)
    # recognised interests: food, history, nature, nightlife, family,
    # adventure, luxury, hidden_gem, beach
    traveling_with_kids: bool = False


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    score: Optional[float]           # 0..100, or None = insufficient data
    reason: str
    inputs_used: Dict[str, object] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.score is not None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "score": None if self.score is None else round(self.score, 1),
            "reason": self.reason,
            "inputs_used": self.inputs_used,
            "available": self.available,
        }


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _density_score(count: Optional[int], saturation: int) -> Optional[float]:
    """Log-scaled 0..100 from a POI count; ``saturation`` = count that
    earns ~100. Real counts in, transparent scale out."""
    if count is None:
        return None
    if count <= 0:
        return 0.0
    return _clamp(100.0 * math.log1p(count) / math.log1p(saturation))


# ----------------------------------------------------------------------
# Dimension scorers
# ----------------------------------------------------------------------

def budget_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "budget_match"
    if u.budget_per_day is None:
        return DimensionScore(name, None,
                              "No daily budget provided by the user.")
    parts: Dict[str, float] = {}
    if s.meal_inexpensive is not None:
        parts["two budget meals"] = 2 * s.meal_inexpensive
    if s.cappuccino is not None:
        parts["coffee"] = s.cappuccino
    if s.transport_ticket is not None:
        parts["two transit tickets"] = 2 * s.transport_ticket
    if s.hotel_median_nightly is not None:
        parts["median hotel night"] = s.hotel_median_nightly
    if not parts or (s.meal_inexpensive is None):
        return DimensionScore(
            name, None,
            "Insufficient real price data (Numbeo/Amadeus) to compute a "
            "daily cost — showing no score rather than an estimate.",
        )
    daily_cost = sum(parts.values())
    ratio = u.budget_per_day / daily_cost
    # ratio 1.0 -> 70; 1.5+ -> ~100; 0.5 -> ~20 (smooth, transparent)
    score = _clamp(70.0 + 60.0 * (ratio - 1.0)) if ratio >= 1 \
        else _clamp(70.0 * ratio ** 1.5)
    basket = ", ".join(f"{k} {v:.2f}" for k, v in parts.items())
    hotel_note = "" if s.hotel_median_nightly is not None else \
        " (no live hotel quote included)"
    return DimensionScore(
        name, score,
        f"Your budget {u.budget_per_day:.0f} {s.currency or ''}/day vs a "
        f"real daily basket of {daily_cost:.2f} ({basket}){hotel_note} — "
        f"budget covers {ratio * 100:.0f}% of typical costs.",
        {"daily_cost": round(daily_cost, 2),
         "budget": u.budget_per_day, "basket": parts},
    )


def weather_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "weather_match"
    if s.temp_max_avg_c is None:
        return DimensionScore(
            name, None,
            "No climate normals available for the travel month.",
        )
    lo, hi = u.preferred_temp_c
    t = s.temp_max_avg_c
    if lo <= t <= hi:
        temp_score = 100.0
        temp_note = f"average daytime high {t:.0f}°C sits inside your " \
                    f"preferred {lo:.0f}–{hi:.0f}°C"
    else:
        distance = (lo - t) if t < lo else (t - hi)
        temp_score = _clamp(100.0 - 9.0 * distance)
        temp_note = f"average daytime high {t:.0f}°C is {distance:.0f}°C " \
                    f"outside your preferred {lo:.0f}–{hi:.0f}°C"
    rain_penalty = 0.0
    rain_note = "rain data unavailable"
    if s.rain_days is not None:
        rain_penalty = _clamp(s.rain_days * 2.5) * 0.3
        rain_note = f"{s.rain_days:.0f} rainy days expected that month"
    score = _clamp(temp_score - rain_penalty)
    return DimensionScore(
        name, score, f"{temp_note}; {rain_note}.",
        {"temp_max_avg_c": t, "rain_days": s.rain_days, "month": s.month},
    )


def food_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "food_match"
    restaurants = s.poi.get("restaurants")
    cafes = s.poi.get("cafes", 0)
    if restaurants is None:
        return DimensionScore(name, None,
                              "No place data for restaurants (Geoapify).")
    score = _density_score(restaurants + cafes, saturation=400)
    return DimensionScore(
        name, score,
        f"{restaurants} restaurants and {cafes} cafés mapped in the area.",
        {"restaurants": restaurants, "cafes": cafes},
    )


def history_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "history_match"
    museums = s.poi.get("museums")
    monuments = s.poi.get("monuments", 0)
    if museums is None:
        return DimensionScore(name, None,
                              "No place data for museums/monuments.")
    score = _density_score(museums + monuments, saturation=80)
    return DimensionScore(
        name, score,
        f"{museums} museums and {monuments} monuments/heritage sites "
        f"mapped nearby.",
        {"museums": museums, "monuments": monuments},
    )


def nature_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "nature_match"
    parks = s.poi.get("parks")
    natural = s.poi.get("natural", 0)
    beaches = s.poi.get("beaches", 0)
    if parks is None:
        return DimensionScore(name, None,
                              "No place data for parks/nature.")
    score = _density_score(parks + natural + beaches, saturation=60)
    return DimensionScore(
        name, score,
        f"{parks} parks, {natural} natural sites and {beaches} beaches "
        f"mapped nearby.",
        {"parks": parks, "natural": natural, "beaches": beaches},
    )


def nightlife_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "nightlife_match"
    bars = s.poi.get("bars_clubs")
    if bars is None:
        return DimensionScore(name, None,
                              "No place data for bars/clubs.")
    score = _density_score(bars, saturation=120)
    return DimensionScore(
        name, score, f"{bars} bars and clubs mapped in the area.",
        {"bars_clubs": bars},
    )


def family_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "family_match"
    play = s.poi.get("playgrounds")
    theme = s.poi.get("theme_parks", 0)
    if play is None and s.safety_index is None:
        return DimensionScore(
            name, None,
            "No family-relevant data (playgrounds, safety index).",
        )
    parts = []
    scores = []
    if play is not None:
        kid_score = _density_score(play + theme * 3, saturation=40)
        scores.append(kid_score)
        parts.append(f"{play} playgrounds and {theme} theme/water parks")
    if s.safety_index is not None:
        scores.append(s.safety_index)
        parts.append(f"Numbeo safety index {s.safety_index:.0f}/100")
    score = sum(scores) / len(scores)
    return DimensionScore(
        name, score, "Based on " + " and ".join(parts) + ".",
        {"playgrounds": play, "theme_parks": theme,
         "safety_index": s.safety_index},
    )


def adventure_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "adventure_match"
    sport = s.poi.get("sports_outdoor")
    if sport is None:
        return DimensionScore(name, None,
                              "No place data for outdoor/sport activities.")
    natural = s.poi.get("natural", 0)
    score = _density_score(sport + natural, saturation=100)
    return DimensionScore(
        name, score,
        f"{sport} outdoor/sport activity spots and {natural} natural "
        f"sites mapped nearby.",
        {"sports_outdoor": sport, "natural": natural},
    )


def luxury_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "luxury_match"
    if not s.hotel_ratings:
        return DimensionScore(
            name, None,
            "No real hotel rating data available — not estimating "
            "luxury level.",
        )
    high_end = sum(1 for r in s.hotel_ratings if r >= 4.0)
    share = high_end / len(s.hotel_ratings)
    score = _clamp(share * 130.0)
    return DimensionScore(
        name, score,
        f"{high_end} of {len(s.hotel_ratings)} rated hotels are 4★+ "
        f"({share * 100:.0f}%).",
        {"rated_hotels": len(s.hotel_ratings), "four_star_plus": high_end},
    )


def hidden_gem_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "hidden_gem_match"
    if s.annual_visitors_millions is None:
        return DimensionScore(
            name, None,
            "No visitor-volume data — hidden-gem status can't be "
            "measured honestly without it.",
        )
    attractions = (s.poi.get("museums", 0) + s.poi.get("monuments", 0)
                   + s.poi.get("natural", 0) + s.poi.get("beaches", 0))
    if attractions == 0:
        return DimensionScore(
            name, 10.0,
            "Low visitor volume but also few mapped attractions.",
            {"annual_visitors_millions": s.annual_visitors_millions},
        )
    quiet = _clamp(100.0 - 18.0 * s.annual_visitors_millions)
    substance = _density_score(attractions, saturation=60) or 0.0
    score = 0.6 * quiet + 0.4 * substance
    return DimensionScore(
        name, score,
        f"{s.annual_visitors_millions:.1f}M annual visitors vs "
        f"{attractions} mapped attractions — quieter than mainstream "
        f"spots with real things to see.",
        {"annual_visitors_millions": s.annual_visitors_millions,
         "attractions": attractions},
    )


def safety_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "safety_match"
    if s.safety_index is None:
        return DimensionScore(
            name, None,
            "No Numbeo safety index available for this city.",
        )
    return DimensionScore(
        name, _clamp(s.safety_index),
        f"Numbeo safety index {s.safety_index:.0f}/100 "
        f"(crowd-sourced from residents).",
        {"safety_index": s.safety_index},
    )


def crowd_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "crowd_match"
    if s.annual_visitors_millions is None or not s.population:
        return DimensionScore(
            name, None,
            "Crowd level needs visitor volume and population data; "
            "neither is available from a free real-time source, so no "
            "score is shown.",
        )
    ratio = (s.annual_visitors_millions * 1_000_000) / s.population
    score = _clamp(100.0 - 12.0 * ratio)
    return DimensionScore(
        name, score,
        f"~{ratio:.1f} visitors per resident per year "
        f"({s.annual_visitors_millions:.1f}M visitors, population "
        f"{s.population:,}) — lower ratio means fewer crowds.",
        {"visitors_per_resident": round(ratio, 2)},
    )


def beach_match(s: DestinationSignals, u: UserProfile) -> DimensionScore:
    name = "beach_match"
    beaches = s.poi.get("beaches")
    if beaches is None:
        return DimensionScore(name, None, "No beach place data.")
    score = _density_score(beaches, saturation=15)
    return DimensionScore(
        name, score, f"{beaches} beaches mapped nearby.",
        {"beaches": beaches},
    )


ALL_DIMENSIONS = [
    budget_match, weather_match, food_match, history_match, nature_match,
    nightlife_match, family_match, adventure_match, luxury_match,
    hidden_gem_match, safety_match, crowd_match, beach_match,
]

# Interest name -> dimension weight boost
INTEREST_WEIGHTS = {
    "food": "food_match", "history": "history_match",
    "nature": "nature_match", "nightlife": "nightlife_match",
    "family": "family_match", "adventure": "adventure_match",
    "luxury": "luxury_match", "hidden_gem": "hidden_gem_match",
    "beach": "beach_match",
}


@dataclass
class TravelIntelligenceScore:
    overall: Optional[float]
    coverage: float                      # share of dimensions with data
    dimensions: List[DimensionScore]
    kind: str = "ai_score"               # UI must label it as AI-derived

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "overall": None if self.overall is None
            else round(self.overall, 1),
            "coverage": round(self.coverage, 2),
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


def compute_score(
    signals: DestinationSignals, profile: UserProfile
) -> TravelIntelligenceScore:
    dims = [fn(signals, profile) for fn in ALL_DIMENSIONS]
    available = [d for d in dims if d.available]
    coverage = len(available) / len(dims)
    if not available:
        return TravelIntelligenceScore(None, 0.0, dims)

    boosted = {
        INTEREST_WEIGHTS[i] for i in profile.interests
        if i in INTEREST_WEIGHTS
    }
    if profile.traveling_with_kids:
        boosted.add("family_match")

    total_weight = 0.0
    weighted_sum = 0.0
    for d in available:
        weight = 2.0 if d.name in boosted else 1.0
        # Budget & safety always matter when available.
        if d.name in ("budget_match", "safety_match"):
            weight = max(weight, 1.5)
        weighted_sum += d.score * weight
        total_weight += weight
    return TravelIntelligenceScore(
        weighted_sum / total_weight, coverage, dims
    )
