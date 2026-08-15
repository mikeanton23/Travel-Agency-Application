# -*- coding: utf-8 -*-

"""
SEO infrastructure: slugs, canonical URLs, page metadata, JSON-LD,
robots.txt and dynamic sitemaps.

Two rules are enforced structurally rather than left to discipline:

1. **Structured data may only describe what the page actually shows.**
   ``hotel_jsonld`` accepts an offer *only* when a real, non-stale
   supplier quote is passed in; otherwise the Hotel node is emitted
   with no ``offers`` key at all.
2. **Only curated, canonical pages are indexable.** Faceted search
   URLs (dates, guests, filters, sorting) are noindex + canonicalised
   to the clean destination page, and never enter the sitemap -- which
   also excludes admin, account, offer-token and payment routes.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from xml.sax.saxutils import escape

from app.utils.settings import get_settings

# Routes that must never be indexed or appear in a sitemap.
DISALLOWED_PREFIXES = (
    "/admin", "/account", "/login", "/offer/", "/pay/", "/api/",
    "/settings", "/chat",
)


def slugify(value: str) -> str:
    """ASCII, lowercase, hyphenated slug. 'Bacevici' -> 'bacevici'."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def base_url() -> str:
    return get_settings().app_base_url.rstrip("/")


def canonical(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url()}{path}"


def hotels_city_path(city: str, country: Optional[str] = None) -> str:
    city_slug = slugify(city)
    if country:
        return f"/hotels/{city_slug}/{slugify(country)}"
    return f"/hotels/{city_slug}"


def hotel_path(hotel_name: str, city: Optional[str] = None) -> str:
    if city:
        return f"/hotel/{slugify(hotel_name)}/{slugify(city)}"
    return f"/hotel/{slugify(hotel_name)}"


def is_indexable(path: str) -> bool:
    """Curated pages only; faceted/private routes excluded."""
    if any(path.startswith(p) for p in DISALLOWED_PREFIXES):
        return False
    if "?" in path:          # faceted search combination
        return False
    return True


# ----------------------------------------------------------------------
# Page metadata
# ----------------------------------------------------------------------

class PageMeta:
    """Unique title/description/canonical plus OG and Twitter cards."""

    def __init__(
        self,
        title: str,
        description: str,
        path: str,
        image: Optional[str] = None,
        noindex: bool = False,
        canonical_path: Optional[str] = None,
    ) -> None:
        self.title = title.strip()
        self.description = description.strip()
        self.path = path
        self.image = image
        # Faceted pages point at their clean parent.
        self.canonical_url = canonical(canonical_path or path)
        self.noindex = noindex or not is_indexable(path)

    def to_html(self) -> str:
        s = get_settings()
        parts = [
            f"<title>{escape(self.title)}</title>",
            f'<meta name="description" content='
            f'"{escape(self.description)}">',
            f'<link rel="canonical" href="{escape(self.canonical_url)}">',
            '<meta name="viewport" content="width=device-width, '
            'initial-scale=1">',
            f'<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content='
            f'"{escape(s.site_name)}">',
            f'<meta property="og:title" content="{escape(self.title)}">',
            f'<meta property="og:description" content='
            f'"{escape(self.description)}">',
            f'<meta property="og:url" content='
            f'"{escape(self.canonical_url)}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{escape(self.title)}">',
            f'<meta name="twitter:description" content='
            f'"{escape(self.description)}">',
        ]
        if self.image:
            parts.append(f'<meta property="og:image" content='
                         f'"{escape(self.image)}">')
            parts.append(f'<meta name="twitter:image" content='
                         f'"{escape(self.image)}">')
        parts.append(
            '<meta name="robots" content="noindex, follow">'
            if self.noindex else
            '<meta name="robots" content="index, follow">'
        )
        return "\n".join(parts)


def city_meta(city: str, country: Optional[str],
              hotel_count: Optional[int] = None) -> PageMeta:
    where = f"{city}, {country}" if country else city
    count = (f"Browse {hotel_count} hotels" if hotel_count
             else "Browse hotels")
    return PageMeta(
        title=f"Hotels in {where} -- real availability and prices",
        description=(
            f"{count} in {where} with live supplier availability, "
            f"transparent totals including taxes, and the option to "
            f"request a personalised direct offer from our travel team."
        ),
        path=hotels_city_path(city, country),
    )


# ----------------------------------------------------------------------
# JSON-LD
# ----------------------------------------------------------------------

def organization_jsonld() -> Dict[str, Any]:
    s = get_settings()
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": s.site_name,
        "url": base_url(),
    }


def website_jsonld() -> Dict[str, Any]:
    s = get_settings()
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": s.site_name,
        "url": base_url(),
    }


def breadcrumb_jsonld(crumbs: List[tuple]) -> Dict[str, Any]:
    """``crumbs`` = [(name, path), ...] in order."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index + 1,
                "name": name,
                "item": canonical(path),
            }
            for index, (name, path) in enumerate(crumbs)
        ],
    }


def hotel_jsonld(
    hotel: Dict[str, Any],
    offer: Optional[Any] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Hotel node. An ``offers`` block is included **only** for a real,
    available, non-stale quote whose price is displayed on the page.

    Ratings are emitted only when a genuine review count exists -- never
    a fabricated aggregate.
    """
    data: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Hotel",
        "name": hotel.get("name"),
    }
    if hotel.get("url"):
        data["url"] = hotel["url"]
    address = {
        k: v for k, v in {
            "@type": "PostalAddress",
            "streetAddress": hotel.get("address"),
            "addressLocality": hotel.get("city"),
            "addressCountry": hotel.get("country"),
        }.items() if v
    }
    if len(address) > 1:
        data["address"] = address
    if hotel.get("latitude") is not None \
            and hotel.get("longitude") is not None:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": hotel["latitude"],
            "longitude": hotel["longitude"],
        }
    if hotel.get("image"):
        data["image"] = hotel["image"]
    rating = hotel.get("rating")
    review_count = hotel.get("review_count")
    if rating is not None and review_count:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": rating,
            "reviewCount": review_count,
        }

    if offer is not None and getattr(offer, "availability", False) \
            and not offer.is_stale(now):
        data["offers"] = {
            "@type": "Offer",
            "price": f"{offer.total_price:.2f}",
            "priceCurrency": offer.currency,
            "availability": "https://schema.org/InStock",
            "url": hotel.get("url") or base_url(),
            "priceValidUntil": offer.expires_at.date().isoformat(),
        }
    return data


# ----------------------------------------------------------------------
# robots.txt / sitemaps
# ----------------------------------------------------------------------

def robots_txt() -> str:
    s = get_settings()
    lines = ["User-agent: *"]
    if s.app_env.strip().lower() != "production":
        # Never let a staging deployment get indexed.
        lines.append("Disallow: /")
        return "\n".join(lines) + "\n"
    for prefix in DISALLOWED_PREFIXES:
        lines.append(f"Disallow: {prefix}")
    lines.append("Disallow: /*?")     # faceted combinations
    lines.append("")
    lines.append(f"Sitemap: {canonical('/sitemap.xml')}")
    return "\n".join(lines) + "\n"


def _url_entry(path: str, lastmod: Optional[str] = None,
               changefreq: str = "weekly",
               priority: str = "0.7") -> str:
    parts = [f"    <loc>{escape(canonical(path))}</loc>"]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
    parts.append(f"    <changefreq>{changefreq}</changefreq>")
    parts.append(f"    <priority>{priority}</priority>")
    body = "\n".join(parts)
    return f"  <url>\n{body}\n  </url>"


def sitemap_urlset(paths: Iterable[str],
                   lastmod: Optional[str] = None) -> str:
    """Only indexable paths are emitted; the rest are dropped."""
    today = lastmod or datetime.now(timezone.utc).date().isoformat()
    entries = [
        _url_entry(path, today)
        for path in dict.fromkeys(paths)      # dedupe, keep order
        if is_indexable(path)
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def sitemap_index(sitemap_paths: Iterable[str]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    entries = [
        f"  <sitemap>\n    <loc>{escape(canonical(p))}</loc>\n"
        f"    <lastmod>{today}</lastmod>\n  </sitemap>"
        for p in sitemap_paths
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex '
        'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</sitemapindex>\n"
    )
