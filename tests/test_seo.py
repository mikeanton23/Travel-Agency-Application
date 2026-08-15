# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone

import pytest

from app.services.hotels.offers import NormalizedOffer
from app.services.seo import (
    PageMeta, breadcrumb_jsonld, city_meta, hotel_jsonld, hotel_path,
    hotels_city_path, is_indexable, robots_txt, sitemap_index,
    sitemap_urlset, slugify,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    from app.utils import settings as settings_module
    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("APP_BASE_URL", "https://aevyra.example")
    monkeypatch.setenv("APP_ENV", "production")
    yield
    settings_module.get_settings.cache_clear()


def test_slugify_handles_accents_and_spaces():
    assert slugify("Bacevici") == "bacevici"
    assert slugify("Chania Spartoulia") == "chania-spartoulia"
    assert slugify("Paris, France!") == "paris-france"


def test_clean_url_builders():
    assert hotels_city_path("Paris", "France") == "/hotels/paris/france"
    assert hotels_city_path("Athens") == "/hotels/athens"
    assert hotel_path("Hotel Grande Bretagne", "Athens") == \
        "/hotel/hotel-grande-bretagne/athens"


def test_private_and_faceted_routes_are_not_indexable():
    assert is_indexable("/hotels/paris")
    assert not is_indexable("/admin")
    assert not is_indexable("/offer/abc123")
    assert not is_indexable("/pay/session")
    assert not is_indexable("/account")
    assert not is_indexable("/hotels/paris?checkin=2026-09-01")


def test_faceted_page_canonicalises_to_clean_parent():
    meta = PageMeta(
        "Paris hotels 2 guests", "desc",
        path="/hotels/paris?guests=2",
        canonical_path="/hotels/paris",
    )
    assert meta.canonical_url == "https://aevyra.example/hotels/paris"
    assert meta.noindex is True
    assert 'content="noindex, follow"' in meta.to_html()


def test_city_meta_is_unique_and_indexable():
    paris = city_meta("Paris", "France", hotel_count=128)
    athens = city_meta("Athens", "Greece", hotel_count=64)
    assert paris.title != athens.title
    assert paris.description != athens.description
    assert paris.noindex is False
    html = paris.to_html()
    assert "<title>" in html and 'rel="canonical"' in html
    assert 'property="og:title"' in html
    assert 'name="twitter:card"' in html
    assert 'content="index, follow"' in html


def test_hotel_jsonld_omits_offers_without_a_real_quote():
    data = hotel_jsonld({"name": "Hotel Test", "city": "Paris",
                         "country": "France"})
    assert data["@type"] == "Hotel"
    assert "offers" not in data          # nothing to show -> nothing claimed
    assert "aggregateRating" not in data


def test_hotel_jsonld_includes_only_live_offers():
    offer = NormalizedOffer(
        hotel_id=1, supplier="amadeus", total_price=210.0,
        currency="EUR", check_in="2026-09-01", check_out="2026-09-04",
        retrieved_at=NOW, expires_at=NOW + timedelta(minutes=30),
    )
    data = hotel_jsonld({"name": "H", "url": "https://x/hotel/h"},
                        offer=offer, now=NOW)
    assert data["offers"]["price"] == "210.00"
    assert data["offers"]["priceCurrency"] == "EUR"

    stale = hotel_jsonld({"name": "H"}, offer=offer,
                         now=NOW + timedelta(hours=2))
    assert "offers" not in stale         # expired price never published


def test_rating_needs_a_real_review_count():
    assert "aggregateRating" not in hotel_jsonld(
        {"name": "H", "rating": 4.6})
    assert "aggregateRating" in hotel_jsonld(
        {"name": "H", "rating": 4.6, "review_count": 812})


def test_breadcrumbs_are_ordered_absolute_urls():
    data = breadcrumb_jsonld([("Hotels", "/hotels"),
                              ("Paris", "/hotels/paris")])
    items = data["itemListElement"]
    assert [i["position"] for i in items] == [1, 2]
    assert items[1]["item"] == "https://aevyra.example/hotels/paris"


def test_sitemap_excludes_private_and_faceted_urls():
    xml = sitemap_urlset([
        "/hotels", "/hotels/paris", "/admin", "/offer/tok",
        "/hotels/paris?guests=2", "/hotels/paris",  # duplicate
    ])
    assert xml.count("<url>") == 2
    assert "/hotels/paris" in xml
    assert "/admin" not in xml and "/offer/" not in xml
    assert "guests=2" not in xml


def test_robots_production_vs_staging(monkeypatch):
    from app.utils import settings as settings_module
    text = robots_txt()
    assert "Sitemap: https://aevyra.example/sitemap.xml" in text
    assert "Disallow: /admin" in text

    settings_module.get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "development")
    staging = robots_txt()
    assert staging.strip().endswith("Disallow: /")   # no staging indexing


def test_sitemap_index_lists_children():
    xml = sitemap_index(["/sitemap-hotels.xml", "/sitemap-cities.xml"])
    assert xml.count("<sitemap>") == 2
    assert "sitemap-hotels.xml" in xml
