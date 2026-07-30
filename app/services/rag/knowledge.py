# -*- coding: utf-8 -*-

"""
Fetch real destination knowledge: Wikipedia and Wikivoyage full text
via the MediaWiki API (plaintext extracts), plus chunking.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from app.services.cache_service import api_cache
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

KNOWLEDGE_TTL = 30 * 86400

API_HOSTS = {
    "wikipedia": "https://{lang}.wikipedia.org/w/api.php",
    "wikivoyage": "https://{lang}.wikivoyage.org/w/api.php",
}
PAGE_HOSTS = {
    "wikipedia": "https://{lang}.wikipedia.org/wiki/{title}",
    "wikivoyage": "https://{lang}.wikivoyage.org/wiki/{title}",
}


@dataclass
class SourceDocument:
    source: str
    title: str
    url: str
    language: str
    text: str


class KnowledgeFetcher:
    def __init__(self, http: Optional[HttpJsonClient] = None) -> None:
        self.http = http or HttpJsonClient()

    async def fetch(
        self, source: str, title: str, language: str = "en"
    ) -> Optional[SourceDocument]:
        """Full plaintext of a page, or ``None`` if it doesn't exist."""
        if source not in API_HOSTS:
            raise ValueError(f"Unknown knowledge source '{source}'")

        @api_cache.cached(f"kb:{source}", ttl=KNOWLEDGE_TTL)
        async def _fetch(t: str, lang: str) -> Optional[dict]:
            url = API_HOSTS[source].format(lang=lang)
            try:
                payload = await self.http.arequest_json(
                    "GET", url,
                    params={
                        "action": "query", "prop": "extracts",
                        "explaintext": 1, "redirects": 1,
                        "format": "json", "titles": t,
                    },
                )
            except ApiError as exc:
                logger.warning("%s fetch failed for %s: %s",
                               source, t, exc)
                return None
            pages = ((payload or {}).get("query") or {}).get("pages", {})
            for page_id, page in pages.items():
                if page_id == "-1" or "extract" not in page:
                    continue
                return {"title": page.get("title", t),
                        "extract": page["extract"]}
            return None

        result = await _fetch(title.strip(), language)
        if not result or not result["extract"].strip():
            return None
        resolved = result["title"]
        return SourceDocument(
            source=source,
            title=resolved,
            url=PAGE_HOSTS[source].format(
                lang=language, title=resolved.replace(" ", "_")
            ),
            language=language,
            text=result["extract"],
        )


def chunk_text(
    text: str, max_chars: int = 1200, overlap: int = 150
) -> List[str]:
    """Split text on paragraph boundaries into ~max_chars chunks with
    overlap, so retrieval keeps local context."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}".strip()
        # A single paragraph longer than max_chars: hard-split it.
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars - overlap:]
    if current.strip():
        chunks.append(current.strip())
    return chunks
