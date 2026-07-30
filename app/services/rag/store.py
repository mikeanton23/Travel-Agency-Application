# -*- coding: utf-8 -*-

"""
Vector store over the ``kb_documents`` / ``kb_chunks`` tables.

Similarity is exact cosine over JSON-stored vectors — correct and fast
enough for per-destination corpora (hundreds of chunks). The interface
is the seam for a pgvector or FAISS backend later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class RetrievedChunk:
    content: str
    score: float
    source: str
    title: str
    url: Optional[str]
    chunk_index: int


class VectorStore:
    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self._sessions = session_factory

    def upsert_document(
        self,
        source: str,
        title: str,
        url: Optional[str],
        language: str,
        chunks: List[str],
        embeddings: List[List[float]],
        embedding_model: str,
        destination_id: Optional[int] = None,
    ) -> int:
        """Replace a document's chunks atomically; returns document id."""
        from app.db.models import KbChunk, KbDocument

        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        session = self._sessions()
        try:
            doc = (
                session.query(KbDocument)
                .filter_by(source=source, title=title, language=language)
                .one_or_none()
            )
            if doc is None:
                doc = KbDocument(source=source, title=title,
                                 language=language)
                session.add(doc)
                session.flush()
            doc.url = url
            doc.destination_id = destination_id
            session.query(KbChunk).filter(
                KbChunk.document_id == doc.id
            ).delete()
            for index, (content, vector) in enumerate(
                zip(chunks, embeddings)
            ):
                session.add(KbChunk(
                    document_id=doc.id, chunk_index=index,
                    content=content, embedding=vector,
                    embedding_model=embedding_model,
                ))
            session.commit()
            return doc.id
        finally:
            session.close()

    def search(
        self,
        query_vector: Sequence[float],
        top_k: int = 5,
        destination_id: Optional[int] = None,
        min_score: float = 0.15,
    ) -> List[RetrievedChunk]:
        from app.db.models import KbChunk, KbDocument

        session = self._sessions()
        try:
            q = (
                session.query(KbChunk, KbDocument)
                .join(KbDocument, KbChunk.document_id == KbDocument.id)
                .filter(KbChunk.embedding.isnot(None))
            )
            if destination_id is not None:
                q = q.filter(KbDocument.destination_id == destination_id)
            scored = []
            for chunk, doc in q.all():
                score = cosine(query_vector, chunk.embedding)
                if score >= min_score:
                    scored.append(RetrievedChunk(
                        content=chunk.content, score=score,
                        source=doc.source, title=doc.title,
                        url=doc.url, chunk_index=chunk.chunk_index,
                    ))
            scored.sort(key=lambda c: c.score, reverse=True)
            return scored[:top_k]
        finally:
            session.close()
