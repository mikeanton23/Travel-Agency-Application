# -*- coding: utf-8 -*-

import httpx
import pytest

from app.services.llm.providers import OpenAIProvider
from app.services.llm.service import LLMService
from app.services.nl_search import NLSearchParser, TravelQuery


def test_rule_parser_extracts_budget_currency_and_traits():
    q = NLSearchParser.parse_rules(
        "I want a romantic quiet island in Europe with wine tasting "
        "under $180/day"
    )
    assert q.budget_per_day == 180.0
    assert q.currency == "USD"
    assert q.continent == "Europe"
    assert q.wants_island is True
    assert q.wants_quiet is True
    assert "romantic" in q.interests and "wine" in q.interests


def test_rule_parser_euro_words_and_month():
    q = NLSearchParser.parse_rules(
        "family beach trip in september, max 120 euros per day, "
        "kids friendly"
    )
    assert q.budget_per_day == 120.0
    assert q.currency == "EUR"
    assert q.month == 9
    assert q.traveling_with_kids is True
    assert "beach" in q.interests and "family" in q.interests


def test_rule_parser_no_signals_is_empty_not_invented():
    q = NLSearchParser.parse_rules("somewhere nice")
    assert q.budget_per_day is None
    assert q.continent is None
    assert q.month is None


def test_travelquery_validation_drops_unknown_interests():
    q = TravelQuery(interests=["food", "skydiving", "Wine", "food"])
    assert q.interests == ["food", "wine"]


@pytest.mark.asyncio
async def test_llm_parse_validated_and_merged():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content":
                '```json\n{"budget_per_day": null, "currency": null,'
                '"continent": "europe", "country": null, "month": null,'
                '"interests": ["romantic", "wine"],'
                '"traveling_with_kids": false,'
                '"wants_island": true, "wants_quiet": true}\n```'
            }}], "usage": {},
        })

    llm = LLMService(
        key_resolver=lambda p: "sk-test",
        provider_overrides={"openai": OpenAIProvider(
            api_key="sk-test", transport=httpx.MockTransport(handler)
        )},
    )
    parser = NLSearchParser(llm=llm)
    q = await parser.parse(
        "romantic quiet island in Europe with wine under $180/day",
        provider="openai",
    )
    assert q.continent == "Europe"
    assert q.budget_per_day == 180.0     # merged from rule extraction
    assert q.currency == "USD"
    assert q.wants_island is True


@pytest.mark.asyncio
async def test_llm_garbage_falls_back_to_rules():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "sorry, no json here"}}],
            "usage": {},
        })

    llm = LLMService(
        key_resolver=lambda p: "sk-test",
        provider_overrides={"openai": OpenAIProvider(
            api_key="sk-test", transport=httpx.MockTransport(handler)
        )},
    )
    parser = NLSearchParser(llm=llm)
    q = await parser.parse("beach trip under €90/day", provider="openai")
    assert q.budget_per_day == 90.0
    assert q.currency == "EUR"
    assert "beach" in q.interests
