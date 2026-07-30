# -*- coding: utf-8 -*-

"""
Destination images from real photo APIs.

Chain: destination's own stored image_urls -> Pexels search (key
already validated in this install) -> None (the UI renders a styled
gradient placeholder — no broken image boxes, no fake photos of the
wrong place claimed as the right one).

Results cache for 30 days per destination, so the Pexels quota is
touched once per place.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.cache_service import api_cache
from app.utils import config
from app.utils.http_client import ApiError, HttpJsonClient

logger = logging.getLogger(__name__)

IMAGE_TTL = 30 * 86400


class ImageService:
    def __init__(self, http: Optional[HttpJsonClient] = None) -> None:
        self.http = http or HttpJsonClient()

    async def destination_image(
        self, name: str, country: Optional[str] = None,
        stored_urls: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Best available real image URL for a destination."""
        if stored_urls:
            return stored_urls[0]
        return await self._pexels_search(name, country)

    async def destination_gallery(
        self, name: str, country: Optional[str] = None, count: int = 6,
    ) -> List[str]:
        result = await self._pexels_photos(name, country, count)
        return result or []

    # ------------------------------------------------------------------

    async def _pexels_search(
        self, name: str, country: Optional[str]
    ) -> Optional[str]:
        photos = await self._pexels_photos(name, country, 3)
        return photos[0] if photos else None

    async def _pexels_photos(
        self, name: str, country: Optional[str], count: int
    ) -> Optional[List[str]]:
        if not config.PEXELS_API_KEY:
            return None

        @api_cache.cached("images:pexels", ttl=IMAGE_TTL)
        async def _search(q: str, n: int) -> Optional[List[str]]:
            try:
                payload = await self.http.arequest_json(
                    "GET", "https://api.pexels.com/v1/search",
                    params={
                        "query": q, "per_page": n,
                        "orientation": "landscape", "size": "large",
                    },
                    headers={"Authorization": config.PEXELS_API_KEY},
                )
            except ApiError as exc:
                logger.warning("Pexels search failed for %s: %s", q, exc)
                return None
            urls: List[str] = []
            for photo in (payload or {}).get("photos", []):
                src: Dict[str, Any] = photo.get("src", {})
                url = src.get("large2x") or src.get("large") \
                    or src.get("original")
                if url:
                    urls.append(url)
            return urls or None

        query = f"{name} {country} travel" if country else f"{name} travel"
        result = await _search(query, count)
        if result:
            return result
        # Fall back to a broader query (small towns often have no
        # exact-name photos; the country's scenery is still real).
        if country:
            return await _search(f"{country} landscape travel", count)
        return None


image_service = ImageService()
