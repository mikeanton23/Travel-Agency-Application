# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone

from app.services.hotels.offers import NormalizedOffer
from app.ui.pages_hotels import apply_filters

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def offer(total=300.0, board="breakfast", refundable=True,
          taxes_included=True, nights=3):
    return NormalizedOffer(
        hotel_id=None, supplier="liteapi", total_price=total,
        currency="EUR", check_in="2026-09-12",
        check_out="2026-09-15", occupancy=2, room_name="Deluxe",
        board_type=board, refundable=refundable,
        taxes_included=taxes_included, retrieved_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def pairs():
    return [
        ({"name": "Cheap Inn", "stars": 3.0, "rating": 6.4,
          "image": None},
         [offer(150.0, board="room_only", refundable=False)]),
        ({"name": "Mid Hotel", "stars": 4.0, "rating": 8.6,
          "image": "https://img/mid.jpg"},
         [offer(300.0), offer(360.0, board="half_board")]),
        ({"name": "Grand Palace", "stars": 5.0, "rating": 9.2,
          "image": "https://img/grand.jpg"},
         [offer(900.0, taxes_included=False)]),
    ]


def test_no_filters_sorts_by_price():
    result = apply_filters(pairs(), {})
    assert [h["name"] for h, _ in result] == \
        ["Cheap Inn", "Mid Hotel", "Grand Palace"]


def test_budget_range_is_uncapped_and_inclusive():
    result = apply_filters(pairs(), {"price_min": 200,
                                     "price_max": 400})
    assert [h["name"] for h, _ in result] == ["Mid Hotel"]
    # No upper cap: a very large budget keeps everything.
    assert len(apply_filters(pairs(), {"price_max": 100000})) == 3


def test_per_night_budget():
    # Mid Hotel is 100/night over 3 nights; Grand is 300/night.
    result = apply_filters(pairs(), {"per_night_max": 120})
    names = [h["name"] for h, _ in result]
    assert "Mid Hotel" in names and "Grand Palace" not in names


def test_board_filter_excludes_unstated_terms():
    result = apply_filters(pairs(), {"boards": ["breakfast"]})
    # Cheap Inn is room-only and drops out; the other two have a
    # breakfast rate each.
    assert [h["name"] for h, _ in result] == ["Mid Hotel",
                                              "Grand Palace"]
    # Within a kept hotel, only the matching rates survive.
    assert all(o.board_type == "breakfast" for _, rates in result
               for o in rates)


def test_refundable_only_rejects_unknown_terms():
    unknown = [({"name": "Mystery", "stars": 4.0, "rating": 8.0,
                 "image": "x"},
                [offer(200.0, refundable=None)])]
    assert apply_filters(unknown, {"refundable_only": True}) == []


def test_all_in_only_excludes_partial_totals():
    result = apply_filters(pairs(), {"taxes_included_only": True})
    assert "Grand Palace" not in [h["name"] for h, _ in result]


def test_star_and_photo_filters():
    assert [h["name"] for h, _ in
            apply_filters(pairs(), {"min_stars": 4})] == \
        ["Mid Hotel", "Grand Palace"]
    assert "Cheap Inn" not in [
        h["name"] for h, _ in
        apply_filters(pairs(), {"with_photo_only": True})]


def test_sort_options():
    high = apply_filters(pairs(), {"sort": "Price: high to low"})
    assert high[0][0]["name"] == "Grand Palace"
    rated = apply_filters(pairs(), {"sort": "Rating: high to low"})
    assert rated[0][0]["name"] == "Grand Palace"
    alpha = apply_filters(pairs(), {"sort": "Name: A to Z"})
    assert [h["name"] for h, _ in alpha][0] == "Cheap Inn"


def test_combined_filters_can_empty_the_list():
    result = apply_filters(pairs(), {"price_max": 100,
                                     "min_stars": 5})
    assert result == []



# ---------------------------------------------------------------
# Stars and guest score are different scales and must not be mixed.
# ---------------------------------------------------------------

def test_stars_and_guest_score_are_separate_filters():
    from app.ui.pages_hotels import apply_filters as af

    # 5 stars only: one property.
    assert [h["name"] for h, _ in af(pairs(), {"min_stars": 5})] == \
        ["Grand Palace"]
    # A guest score of 5 is low on a 0-10 scale and keeps everything -
    # if these were conflated, this would wrongly drop 3- and 4-star
    # hotels.
    assert len(af(pairs(), {"min_score": 5})) == 3
    assert [h["name"] for h, _ in af(pairs(), {"min_score": 9})] == \
        ["Grand Palace"]


def test_unstated_terms_can_be_included_deliberately():
    from app.ui.pages_hotels import apply_filters as af

    unstated = [({"name": "Mystery", "stars": 4.0, "image": "x"},
                 [offer(200.0, board="unknown", refundable=None)])]
    # Strict by default.
    assert af(unstated, {"boards": ["breakfast"]}) == []
    assert af(unstated, {"refundable_only": True}) == []
    # Opt in explicitly.
    assert len(af(unstated, {"boards": ["breakfast"],
                             "allow_unstated": True})) == 1
    assert len(af(unstated, {"refundable_only": True,
                             "allow_unstated": True})) == 1


def test_report_explains_an_empty_result():
    from app.ui.pages_hotels import filter_report, filter_with_report

    kept, reasons = filter_with_report(pairs(), {"price_max": 50})
    assert kept == []
    assert reasons["over_budget"] == 4
    text = filter_report(reasons)
    assert "above your budget" in text

    kept, reasons = filter_with_report(
        [({"name": "M", "image": "x"},
          [offer(100.0, board="unknown")])],
        {"boards": ["breakfast"]})
    assert kept == []
    assert "no meal plan stated" in filter_report(reasons)


def test_report_is_empty_when_nothing_was_removed():
    from app.ui.pages_hotels import filter_report, filter_with_report

    kept, reasons = filter_with_report(pairs(), {})
    assert len(kept) == 3
    assert filter_report(reasons) == ""
