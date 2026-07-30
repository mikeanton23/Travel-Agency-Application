# -*- coding: utf-8 -*-

"""
Natural-language travel search.

Turns queries like
    "romantic quiet island in Europe with wine tasting under $180/day"
into a validated :class:`TravelQuery` that feeds
``DestinationRepository.search`` and the intelligence-score profile.

Two parsing paths:
1. **LLM parsing** (preferred): strict-JSON prompt to any configured
   provider, then Pydantic validation of the result.
2. **Rule-based fallback**: deterministic regex/keyword extraction —
   used when no LLM is configured or its output fails validation.
   This is parsing of the user's own words, not invented data.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.services.llm.base import LLMError, Message
from app.services.llm.service import LLMService

logger = logging.getLogger(__name__)

KNOWN_INTERESTS = [
    "food", "history", "nature", "nightlife", "family", "adventure",
    "luxury", "hidden_gem", "beach", "romantic", "quiet", "wine",
    "museums", "shopping", "island",
]

CONTINENTS = ["europe", "asia", "africa", "north america",
              "south america", "oceania"]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

CURRENCY_SIGNS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


class TravelQuery(BaseModel):
    """Structured search parameters extracted from free text."""

    budget_per_day: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = None
    continent: Optional[str] = None
    country: Optional[str] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    interests: List[str] = Field(default_factory=list)
    traveling_with_kids: bool = False
    wants_island: bool = False
    wants_quiet: bool = False

    @field_validator("interests")
    @classmethod
    def _known_interests_only(cls, value: List[str]) -> List[str]:
        cleaned = []
        for item in value:
            item = str(item).strip().lower().replace(" ", "_")
            if item in KNOWN_INTERESTS and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @field_validator("continent")
    @classmethod
    def _normalize_continent(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        return value.title() if value in CONTINENTS else None


PARSE_PROMPT = """Extract travel search parameters from the user's query.
Respond ONLY with a JSON object (no markdown, no prose) with keys:
budget_per_day (number|null), currency (ISO code|null),
continent (string|null), country (string|null), month (1-12|null),
interests (array from: {interests}),
traveling_with_kids (bool), wants_island (bool), wants_quiet (bool).
Only extract what the user actually said — never guess missing values.

Query: {query}"""


class NLSearchParser:
    # After a provider errors (quota, outage), skip it for a while so
    # searches respond instantly from the rule-based parser instead of
    # waiting out a doomed API call every time.
    PROVIDER_COOLDOWN_S = 300.0

    def __init__(self, llm: Optional[LLMService] = None) -> None:
        self.llm = llm or LLMService()
        self._provider_backoff: dict = {}

    async def parse(
        self, query: str, provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> TravelQuery:
        """LLM parse with validation; deterministic fallback on any
        failure. Always returns a valid TravelQuery."""
        import time
        if provider:
            until = self._provider_backoff.get(provider, 0.0)
            if time.monotonic() < until:
                logger.debug(
                    "%s in parse cooldown — using rule-based parser",
                    provider,
                )
            else:
                try:
                    return await self._parse_with_llm(
                        query, provider, model
                    )
                except (LLMError, ValidationError, ValueError,
                        json.JSONDecodeError) as exc:
                    self._provider_backoff[provider] = (
                        time.monotonic() + self.PROVIDER_COOLDOWN_S
                    )
                    logger.warning(
                        "LLM parse failed (%s) — using rule-based "
                        "parser and skipping %s for %.0fs",
                        exc, provider, self.PROVIDER_COOLDOWN_S,
                    )
        return self.parse_rules(query)

    async def _parse_with_llm(
        self, query: str, provider: str, model: Optional[str]
    ) -> TravelQuery:
        prompt = PARSE_PROMPT.format(
            interests=", ".join(KNOWN_INTERESTS), query=query
        )
        completion = await self.llm.chat(
            [Message("user", prompt)], provider=provider, model=model
        )
        text = completion.text.strip()
        # Strip accidental markdown fences.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        data = json.loads(text)
        parsed = TravelQuery.model_validate(data)
        # Merge in deterministic extraction so obvious signals (an
        # explicit "$180/day") survive a lazy LLM response.
        rules = self.parse_rules(query)
        if parsed.budget_per_day is None:
            parsed.budget_per_day = rules.budget_per_day
            parsed.currency = parsed.currency or rules.currency
        if parsed.month is None:
            parsed.month = rules.month
        for interest in rules.interests:
            if interest not in parsed.interests:
                parsed.interests.append(interest)
        parsed.wants_island = parsed.wants_island or rules.wants_island
        parsed.wants_quiet = parsed.wants_quiet or rules.wants_quiet
        return parsed

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    @staticmethod
    def parse_rules(query: str) -> TravelQuery:
        text = query.lower()

        budget = None
        currency = None
        money = re.search(
            r"(?:under|below|less than|max(?:imum)?|up to)?\s*"
            r"([$€£¥])\s?(\d+(?:[.,]\d+)?)\s*(?:/|per\s*)?(?:day|daily)?",
            text,
        )
        if money:
            currency = CURRENCY_SIGNS.get(money.group(1))
            budget = float(money.group(2).replace(",", "."))
        else:
            money = re.search(
                r"(\d+(?:[.,]\d+)?)\s*(usd|eur|gbp|jpy|dollars?|euros?|"
                r"pounds?)\s*(?:/|per\s*)?(?:day|daily)?",
                text,
            )
            if money:
                budget = float(money.group(1).replace(",", "."))
                unit = money.group(2)
                currency = {
                    "usd": "USD", "dollar": "USD", "dollars": "USD",
                    "eur": "EUR", "euro": "EUR", "euros": "EUR",
                    "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
                    "jpy": "JPY",
                }.get(unit, unit.upper() if len(unit) == 3 else None)

        continent = next(
            (c.title() for c in CONTINENTS if c in text), None
        )
        month = next(
            (num for name, num in MONTHS.items() if name in text), None
        )

        interests: List[str] = []
        keyword_map = {
            "food": ["food", "restaurant", "culinary", "cuisine",
                     "gastronomy"],
            "wine": ["wine", "vineyard", "winery"],
            "history": ["history", "historic", "ancient", "heritage"],
            "museums": ["museum", "gallery", "art"],
            "nature": ["nature", "hiking", "mountain", "forest",
                       "outdoors"],
            "beach": ["beach", "seaside", "coast"],
            "nightlife": ["nightlife", "clubbing", "party", "bars"],
            "romantic": ["romantic", "honeymoon", "couple"],
            "luxury": ["luxury", "luxurious", "5-star", "five star",
                       "boutique"],
            "adventure": ["adventure", "diving", "surfing", "climbing",
                          "kayak"],
            "family": ["family", "kids", "children", "child"],
            "hidden_gem": ["hidden gem", "off the beaten",
                           "undiscovered", "less touristy"],
            "shopping": ["shopping", "boutiques", "markets"],
        }
        for interest, keywords in keyword_map.items():
            if any(k in text for k in keywords):
                interests.append(interest)

        return TravelQuery(
            budget_per_day=budget,
            currency=currency,
            continent=continent,
            month=month,
            interests=interests,
            traveling_with_kids=any(
                k in text for k in ("kids", "children", "family")
            ),
            wants_island=("island" in text),
            wants_quiet=any(
                k in text for k in ("quiet", "peaceful", "calm",
                                    "relaxing", "tranquil")
            ),
        )


nl_search_parser = NLSearchParser()
