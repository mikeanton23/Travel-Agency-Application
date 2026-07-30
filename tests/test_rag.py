# -*- coding: utf-8 -*-

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, KbChunk, KbDocument
from app.services.llm.base import Message
from app.services.llm.providers import OpenAIProvider
from app.services.llm.service import LLMService
from app.services.rag.embeddings import EmbeddingProvider
from app.services.rag.knowledge import KnowledgeFetcher, chunk_text
from app.services.rag.rag_service import RagService
from app.services.rag.store import VectorStore, cosine
from app.utils.http_client import HttpJsonClient


class StubEmbeddings(EmbeddingProvider):
    """Deterministic vectors: direction encodes topic keywords."""

    name = "stub"
    model = "unit"

    async def embed(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            vectors.append([
                float(lower.count("beach")),
                float(lower.count("museum")),
                float(lower.count("food") + lower.count("restaurant")),
                1.0,  # bias so no vector is all-zero
            ])
        return vectors


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_cosine_basics():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_chunk_text_respects_size_and_overlap():
    text = "\n\n".join(f"Paragraph {i} " + "x" * 300 for i in range(10))
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    joined = " ".join(chunks)
    for i in range(10):
        assert f"Paragraph {i}" in joined  # nothing lost


@pytest.mark.asyncio
async def test_fetcher_parses_mediawiki_extract(fresh_cache):
    def handler(request):
        assert "wikivoyage.org" in str(request.url)
        return httpx.Response(200, json={"query": {"pages": {
            "123": {"title": "Santorini",
                    "extract": "Santorini is a volcanic island."},
        }}})

    fetcher = KnowledgeFetcher(
        http=HttpJsonClient(transport=httpx.MockTransport(handler))
    )
    doc = await fetcher.fetch("wikivoyage", "Santorini")
    assert doc.title == "Santorini"
    assert "volcanic" in doc.text
    assert doc.url == "https://en.wikivoyage.org/wiki/Santorini"


@pytest.mark.asyncio
async def test_fetcher_missing_page_returns_none(fresh_cache):
    def handler(request):
        return httpx.Response(200, json={"query": {"pages": {
            "-1": {"missing": ""},
        }}})

    fetcher = KnowledgeFetcher(
        http=HttpJsonClient(transport=httpx.MockTransport(handler))
    )
    assert await fetcher.fetch("wikipedia", "Nope") is None


@pytest.mark.asyncio
async def test_store_upsert_replaces_and_search_ranks(factory):
    store = VectorStore(factory)
    emb = StubEmbeddings()
    chunks = [
        "The beach beach beach is stunning.",
        "The museum holds ancient art.",
        "Great food and restaurant scene.",
    ]
    vectors = await emb.embed(chunks)
    doc_id = store.upsert_document(
        "wikivoyage", "TestTown", "http://x", "en",
        chunks, vectors, "stub:unit", destination_id=7,
    )
    # Upsert again -> replaces, not duplicates
    store.upsert_document(
        "wikivoyage", "TestTown", "http://x", "en",
        chunks, vectors, "stub:unit", destination_id=7,
    )
    session = factory()
    assert session.query(KbDocument).count() == 1
    assert session.query(KbChunk).count() == 3
    session.close()

    query_vec = (await emb.embed(["sandy beach day"]))[0]
    results = store.search(query_vec, top_k=2, destination_id=7)
    assert results[0].content.startswith("The beach")
    assert results[0].score >= results[-1].score
    assert store.search(query_vec, destination_id=99) == []


@pytest.mark.asyncio
async def test_rag_answer_grounds_in_sources(factory, fresh_cache):
    def wiki_handler(request):
        return httpx.Response(200, json={"query": {"pages": {
            "1": {"title": "TestTown",
                  "extract": "TestTown has a famous museum of history."
                             "\n\nThe beach is quiet in May."},
        }}})

    def llm_handler(request):
        import json
        body = json.loads(request.content)
        prompt = body["messages"][-1]["content"]
        assert "Sources:" in prompt and "museum" in prompt
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": "Per [1], TestTown's museum covers history."
            }}], "usage": {},
        })

    llm = LLMService(
        key_resolver=lambda p: "sk-test",
        provider_overrides={"openai": OpenAIProvider(
            api_key="sk-test",
            transport=httpx.MockTransport(llm_handler),
        )},
    )
    rag = RagService(
        session_factory=factory,
        embeddings=StubEmbeddings(),
        llm=llm,
        fetcher=KnowledgeFetcher(http=HttpJsonClient(
            transport=httpx.MockTransport(wiki_handler)
        )),
    )
    indexed = await rag.index_destination(
        "TestTown", destination_id=1, sources=("wikipedia",)
    )
    assert indexed >= 1

    answer = await rag.answer("Tell me about the museum",
                              provider="openai", destination_id=1)
    assert "[1]" in answer.text
    assert answer.sources and answer.sources[0].title == "TestTown"


@pytest.mark.asyncio
async def test_rag_answer_without_index_admits_it(factory):
    rag = RagService(
        session_factory=factory, embeddings=StubEmbeddings(),
        llm=LLMService(key_resolver=lambda p: "sk"),
    )
    answer = await rag.answer("anything", provider="openai")
    assert "don't have indexed knowledge" in answer.text
    assert answer.sources == []
