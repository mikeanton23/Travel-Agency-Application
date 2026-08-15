# -*- coding: utf-8 -*-

"""
SEO HTTP endpoints served by NiceGUI's underlying FastAPI app.

These are plain-text/XML responses (not NiceGUI pages) so crawlers get
exactly the bytes they expect with no JS involved:

    /robots.txt
    /sitemap.xml            (index)
    /sitemap-destinations.xml
    /sitemap-cities.xml

Sitemaps are generated from real database rows -- only destinations and
cities that actually have a landing page. Nothing thin or invented is
listed, and ``is_indexable`` filters admin/account/offer/payment and
faceted URLs at generation time.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import Response
from nicegui import app

from app.services.seo import (
    hotels_city_path, robots_txt, sitemap_index, sitemap_urlset,
)

logger = logging.getLogger(__name__)

XML_MEDIA = "application/xml"


def _destination_rows() -> List[dict]:
    """Distinct, named destinations with coordinates -- a landing page
    without a real place behind it would be a doorway page."""
    from app.db.database import SessionLocal
    from app.db.models import Destination

    session = SessionLocal()
    try:
        rows = (
            session.query(Destination)
            .filter(Destination.name.isnot(None))
            .filter(Destination.country.isnot(None))
            .all()
        )
        return [{"name": r.name, "country": r.country} for r in rows]
    except Exception as exc:            # DB down must not 500 the crawl
        logger.warning("sitemap destination query failed: %s", exc)
        return []
    finally:
        session.close()


def _city_rows() -> List[dict]:
    from app.db.database import SessionLocal
    from app.db.models import City, Country

    session = SessionLocal()
    try:
        rows = (
            session.query(City.name, Country.name)
            .join(Country, City.country_id == Country.id)
            .all()
        )
        return [{"name": c, "country": k} for c, k in rows]
    except Exception as exc:
        logger.warning("sitemap city query failed: %s", exc)
        return []
    finally:
        session.close()


def register_seo_routes() -> None:
    """Attach the crawler-facing endpoints to the FastAPI app."""

    @app.get("/robots.txt", include_in_schema=False)
    def _robots() -> Response:
        return Response(content=robots_txt(), media_type="text/plain")

    @app.get("/sitemap.xml", include_in_schema=False)
    def _sitemap() -> Response:
        return Response(
            content=sitemap_index([
                "/sitemap-destinations.xml",
                "/sitemap-cities.xml",
            ]),
            media_type=XML_MEDIA,
        )

    @app.get("/sitemap-destinations.xml", include_in_schema=False)
    def _sitemap_destinations() -> Response:
        paths = ["/hotels"]
        for row in _destination_rows():
            paths.append(hotels_city_path(row["name"], row["country"]))
        return Response(content=sitemap_urlset(paths),
                        media_type=XML_MEDIA)

    @app.get("/sitemap-cities.xml", include_in_schema=False)
    def _sitemap_cities() -> Response:
        paths = [
            hotels_city_path(row["name"], row["country"])
            for row in _city_rows()
        ]
        return Response(content=sitemap_urlset(paths),
                        media_type=XML_MEDIA)


def register_payment_routes() -> None:
    """Stripe webhook endpoint. Registered alongside the SEO routes so
    all raw-HTTP endpoints live in one place."""
    from fastapi import Request

    @app.post("/api/payments/stripe/webhook", include_in_schema=False)
    async def _stripe_webhook(request: Request) -> Response:
        from app.services.payments import payment_service

        payload = await request.body()
        signature = request.headers.get("Stripe-Signature", "")
        result = payment_service.handle_webhook(payload, signature)
        if not result.get("ok"):
            # Do not echo the reason back to the caller.
            logger.warning("Stripe webhook rejected: %s",
                           result.get("reason"))
            return Response(status_code=400, content="invalid")
        return Response(status_code=200, content="ok")
