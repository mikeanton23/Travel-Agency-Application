# -*- coding: utf-8 -*-

"""
RAG orchestration: index destination knowledge, semantic search, and
grounded answers with citations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from app.services.llm.base import Message
from app.services.llm.service import LLMService
from app.services.rag.embeddings import EmbeddingProvider, default_embeddings
from app.services.rag.knowledge import KnowledgeFetcher, chunk_text
from app.services.rag.store import RetrievedChunk, VectorStore

logger = logging.getLogger(__name__)

ANSWER_SYSTEM_PROMPT = (
    "You are a travel research assistant. Answer strictly from the "
    "provided sources. If the sources don't contain the answer, say so "
    "plainly — never invent facts, prices, or availability. Cite the "
    "sources you used by their [number]."
)


@dataclass
class RagAnswer:
    text: str
    sources: List[RetrievedChunk] = field(default_factory=list)


class RagService:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        embeddings: Optional[EmbeddingProvider] = None,
        llm: Optional[LLMService] = None,
        fetcher: Optional[KnowledgeFetcher] = None,
    ) -> None:
        self.store = VectorStore(session_factory)
        self.embeddings = embeddings or default_embeddings()
        self.llm = llm or LLMService(session_factory=session_factory)
        self.fetcher = fetcher or KnowledgeFetcher()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_destination(
        self,
        page_title: str,
        destination_id: Optional[int] = None,
        language: str = "en",
        sources: tuple = ("wikipedia", "wikivoyage"),
    ) -> int:
        """Fetch, chunk, embed and store knowledge for a destination.
        Returns the number of chunks indexed."""
        total = 0
        for source in sources:
            doc = await self.fetcher.fetch(source, page_title, language)
            if doc is None:
                logger.info("No %s page for %s", source, page_title)
                continue
            chunks = chunk_text(doc.text)
            if not chunks:
                continue
            vectors = await self.embeddings.embed(chunks)
            self.store.upsert_document(
                source=doc.source, title=doc.title, url=doc.url,
                language=doc.language, chunks=chunks, embeddings=vectors,
                embedding_model=(
                    f"{self.embeddings.name}:{self.embeddings.model}"
                ),
                destination_id=destination_id,
            )
            total += len(chunks)
        return total

    # ------------------------------------------------------------------
    # Retrieval + answering
    # ------------------------------------------------------------------

    async def search(
        self, query: str, top_k: int = 5,
        destination_id: Optional[int] = None,
    ) -> List[RetrievedChunk]:
        vector = (await self.embeddings.embed([query]))[0]
        return self.store.search(vector, top_k=top_k,
                                 destination_id=destination_id)

    async def answer(
        self,
        question: str,
        provider: str,
        model: Optional[str] = None,
        destination_id: Optional[int] = None,
        top_k: int = 5,
    ) -> RagAnswer:
        chunks = await self.search(question, top_k=top_k,
                                   destination_id=destination_id)
        if not chunks:
            return RagAnswer(
                text="I don't have indexed knowledge to answer this yet. "
                     "Index the destination first, or ask something else.",
                sources=[],
            )
        context = "\n\n".join(
            f"[{i + 1}] ({c.source}: {c.title})\n{c.content}"
            for i, c in enumerate(chunks)
        )
        completion = await self.llm.chat(
            [
                Message("system", ANSWER_SYSTEM_PROMPT),
                Message("user",
                        f"Sources:\n{context}\n\nQuestion: {question}"),
            ],
            provider=provider, model=model,
        )
        return RagAnswer(text=completion.text, sources=chunks)
