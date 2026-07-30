# -*- coding: utf-8 -*-

"""Embedding providers for the RAG pipeline.

* :class:`OpenAIEmbeddings` — hosted, via the embeddings REST API.
* :class:`LocalEmbeddings` — sentence-transformers, fully offline
  (already in requirements.txt; model downloads on first use).

Both return plain ``list[float]`` so vectors serialise straight into
the ``kb_chunks.embedding`` JSON column.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from app.utils import config
from app.utils.http_client import HttpJsonClient

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]: ...


class OpenAIEmbeddings(EmbeddingProvider):
    name = "openai"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        http: Optional[HttpJsonClient] = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else config.OPENAI_API_KEY
        )
        self.model = model
        self.http = http or HttpJsonClient()

    async def embed(self, texts: List[str]) -> List[List[float]]:
        payload = await self.http.arequest_json(
            "POST", "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        data = sorted((payload or {}).get("data", []),
                      key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]


class LocalEmbeddings(EmbeddingProvider):
    """sentence-transformers; runs on CPU, no API key, no network after
    the first model download."""

    name = "local"

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self.model = model
        self._st = None

    def _load(self):
        if self._st is None:
            from sentence_transformers import SentenceTransformer
            self._st = SentenceTransformer(self.model)
        return self._st

    async def embed(self, texts: List[str]) -> List[List[float]]:
        import asyncio
        st = self._load()
        vectors = await asyncio.to_thread(
            st.encode, texts, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]


def default_embeddings() -> EmbeddingProvider:
    """OpenAI if a key exists (fast, no local model), else local."""
    if config.OPENAI_API_KEY:
        return OpenAIEmbeddings()
    return LocalEmbeddings()
