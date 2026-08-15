# -*- coding: utf-8 -*-

"""
Hotel acquisition pages (Phase B).

Routes:
    /hotels                         hub of curated destinations
    /hotels/{city}                  city landing page
    /hotels/{city}/{country}        disambiguated city landing page
    /offer/{token}                  secure customer offer (noindex)

Design rules enforced here:
* Prices shown only from live supplier quotes, each labelled with its
  supplier and retrieval time; failures say so plainly.
* A "cheaper" claim is never rendered directly -- it comes only from
  ``compare_offers`` and only in its VERIFIED_LOWER branch.
* Every indexable page injects unique metadata plus JSON-LD that
  matches what is visible; /offer/* is noindex.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from nicegui import ui

from app.services.analytics import analytics
from app.services.hotels.search import hotel_search_service
from app.services.image_service import image_service
from app.services.leads import LeadError, lead_service, session_hash
from app.services.offer_tokens import offer_token_service
from app.services.seo import (
    PageMeta, breadcrumb_jsonld, city_meta, hotel_jsonld,
    hotels_city_path, organization_jsonld, slugify, website_jsonld,
)
from app.ui.components.layout import page_shell

CURATED = [
    ("Paris", "France"), ("Athens", "Greece"), ("Rome", "Italy"),
    ("Barcelona", "Spain"), ("Lisbon", "Portugal"),
    ("Amsterdam", "Netherlands"),
]

BOARD_LABELS = {
    "room_only": "Room only", "breakfast": "Breakfast included",
    "half_board": "Half board", "full_board": "Full board",
    "all_inclusive": "All inclusive", "unknown": "Board not stated",
}


# ----------------------------------------------------------------------
# Head injection
# ----------------------------------------------------------------------

def inject_seo(meta: PageMeta, *json_ld: Dict[str, Any]) -> None:
    ui.add_head_html(meta.to_html())
    for block in json_ld:
        ui.add_head_html(
            '<script type="application/ld+json">'
            + json.dumps(block, ensure_ascii=False)
            + "</script>"
        )


def _client_key() -> str:
    try:
        from nicegui import context
        request = context.client.request
        return request.client.host if request and request.client \
            else "unknown"
    except Exception:
        return "unknown"


def parse_date(value: Optional[str]):
    """Parse an ISO date from a date input; None when unusable."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _default_dates() -> tuple:
    start = date.today() + timedelta(days=30)
    return start.isoformat(), (start + timedelta(days=3)).isoformat()


# ----------------------------------------------------------------------
# Shared components
# ----------------------------------------------------------------------

def search_form(city: str, country: Optional[str], on_search) -> Dict:
    """Stay details plus travel filters. Budget is a free numeric
    range - no capped slider - and every filter is optional."""
    default_in, default_out = _default_dates()
    fields: Dict[str, Any] = {}

    with ui.card().classes("tv-glass w-full p-4 gap-3"):
        with ui.row().classes("w-full gap-3 items-end flex-wrap"):
            today = date.today().isoformat()
            with ui.column().classes("gap-0"):
                ui.label("Check-in").classes(
                    "tv-mono text-[10px] tv-muted uppercase")
                fields["check_in"] = ui.input(value=default_in).props(
                    f"dense outlined type=date min={today}").classes(
                    "w-40")
            with ui.column().classes("gap-0"):
                ui.label("Check-out").classes(
                    "tv-mono text-[10px] tv-muted uppercase")
                fields["check_out"] = ui.input(value=default_out).props(
                    f"dense outlined type=date min={today}").classes(
                    "w-40")
            nights_label = ui.label("").classes(
                "tv-mono text-[10px] tv-muted self-center")

            def _sync_dates() -> None:
                """Keep the stay valid: checkout must follow checkin."""
                start = parse_date(fields["check_in"].value)
                end = parse_date(fields["check_out"].value)
                if start is None:
                    nights_label.set_text("")
                    return
                if end is None or end <= start:
                    end = start + timedelta(days=1)
                    fields["check_out"].set_value(end.isoformat())
                nights = (end - start).days
                nights_label.set_text(
                    f"{nights} night" + ("s" if nights != 1 else ""))

            fields["check_in"].on_value_change(lambda _: _sync_dates())
            fields["check_out"].on_value_change(lambda _: _sync_dates())
            _sync_dates()
            with ui.column().classes("gap-0"):
                ui.label("Guests").classes(
                    "tv-mono text-[10px] tv-muted uppercase")
                fields["guests"] = ui.number(value=2, min=1,
                                             max=16).props(
                    "dense outlined").classes("w-24")
            with ui.column().classes("gap-0"):
                ui.label("Rooms").classes(
                    "tv-mono text-[10px] tv-muted uppercase")
                fields["rooms"] = ui.number(value=1, min=1,
                                            max=8).props(
                    "dense outlined").classes("w-24")
            with ui.column().classes("gap-0"):
                ui.label("Currency").classes(
                    "tv-mono text-[10px] tv-muted uppercase")
                fields["currency"] = ui.select(
                    ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD"],
                    value="EUR").props("dense outlined").classes("w-28")
            ui.button("Search hotels", on_click=on_search).props(
                "unelevated color=primary icon=sym_r_search no-caps")

        with ui.expansion("Filters", icon="sym_r_tune").classes(
            "w-full"
        ).props("dense"):
            with ui.column().classes("w-full gap-3 pt-2"):
                with ui.row().classes("w-full gap-3 items-end "
                                      "flex-wrap"):
                    with ui.column().classes("gap-0"):
                        ui.label("Budget from (total stay)").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["price_min"] = ui.number(
                            value=None, min=0, placeholder="any").props(
                            "dense outlined").classes("w-36")
                    with ui.column().classes("gap-0"):
                        ui.label("Budget to (total stay)").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["price_max"] = ui.number(
                            value=None, min=0, placeholder="any").props(
                            "dense outlined").classes("w-36")
                    with ui.column().classes("gap-0"):
                        ui.label("Max per night").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["per_night_max"] = ui.number(
                            value=None, min=0, placeholder="any").props(
                            "dense outlined").classes("w-36")
                    with ui.column().classes("gap-0"):
                        ui.label("Search radius (km)").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["radius_km"] = ui.number(
                            value=15, min=1, max=100).props(
                            "dense outlined").classes("w-32")

                with ui.row().classes("w-full gap-3 items-end "
                                      "flex-wrap"):
                    with ui.column().classes("gap-0"):
                        ui.label("Meal plan").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["boards"] = ui.select(
                            {k: v for k, v in BOARD_LABELS.items()},
                            multiple=True, value=[],
                        ).props("dense outlined use-chips").classes(
                            "w-64")
                    with ui.column().classes("gap-0"):
                        ui.label("Star rating (min)").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["min_stars"] = ui.select(
                            {0: "Any", 3: "3+", 4: "4+", 5: "5"},
                            value=0).props("dense outlined").classes(
                            "w-32")
                    with ui.column().classes("gap-0"):
                        ui.label("Sort by").classes(
                            "tv-mono text-[10px] tv-muted uppercase")
                        fields["sort"] = ui.select(
                            ["Price: low to high",
                             "Price: high to low",
                             "Rating: high to low",
                             "Name: A to Z"],
                            value="Price: low to high",
                        ).props("dense outlined").classes("w-52")

                with ui.row().classes("w-full gap-4 items-center "
                                      "flex-wrap"):
                    fields["refundable_only"] = ui.checkbox(
                        "Free cancellation only")
                    fields["taxes_included_only"] = ui.checkbox(
                        "All-in totals only")
                    fields["with_photo_only"] = ui.checkbox(
                        "Only properties with a photo")
                    ui.space()
                    ui.button("Apply filters", on_click=on_search).props(
                        "outline dense no-caps icon=sym_r_filter_alt")
                ui.label(
                    "Filters apply to live supplier results. Rates "
                    "whose terms the supplier did not state are "
                    "excluded by the strict filters rather than "
                    "assumed to qualify."
                ).classes("text-xs tv-muted")
    return fields


def apply_filters(grouped_items: list, fields: Dict[str, Any]) -> list:
    """Filter and sort (hotel_meta, rates) pairs from the widgets.

    Deliberately conservative: a rate that does not state its board or
    cancellation terms fails a strict filter instead of passing.
    """
    def raw(key, default=None):
        """Accept either a NiceGUI widget or a plain value.

        Unwrapping only widgets meant a plain value fell through to the
        default and the filter quietly did nothing.
        """
        if key not in fields:
            return default
        value = fields[key]
        if hasattr(value, "value"):      # NiceGUI widget
            value = value.value
        return default if value is None else value

    def num(key):
        value = raw(key)
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def flag(key):
        return bool(raw(key, False))

    def val(key, default=None):
        return raw(key, default)

    price_min = num("price_min")
    price_max = num("price_max")
    per_night_max = num("per_night_max")
    boards = val("boards", []) or []
    min_stars = val("min_stars", 0) or 0
    refundable_only = flag("refundable_only")
    all_in_only = flag("taxes_included_only")
    photo_only = flag("with_photo_only")
    sort_by = val("sort", "Price: low to high")

    def rate_ok(offer) -> bool:
        if price_min is not None and offer.total_price < price_min:
            return False
        if price_max is not None and offer.total_price > price_max:
            return False
        if per_night_max is not None:
            per_night = offer.price_per_night
            if per_night is None or per_night > per_night_max:
                return False
        if boards and offer.board_type not in boards:
            return False
        if refundable_only and offer.refundable is not True:
            return False
        if all_in_only and not offer.taxes_included:
            return False
        return True

    kept = []
    for hotel_meta, rates in grouped_items:
        surviving = [r for r in rates if rate_ok(r)]
        if not surviving:
            continue
        if photo_only and not hotel_meta.get("image"):
            continue
        try:
            stars = float(hotel_meta.get("rating") or 0)
        except (TypeError, ValueError):
            stars = 0.0
        if min_stars and stars < float(min_stars):
            continue
        kept.append((hotel_meta, surviving))

    if sort_by == "Price: high to low":
        kept.sort(key=lambda kv: kv[1][0].total_price, reverse=True)
    elif sort_by == "Rating: high to low":
        kept.sort(key=lambda kv: float(kv[0].get("rating") or 0),
                  reverse=True)
    elif sort_by == "Name: A to Z":
        kept.sort(key=lambda kv: (kv[0].get("name") or "").lower())
    else:
        kept.sort(key=lambda kv: kv[1][0].total_price)
    return kept


def hotel_offer_card(
    hotel: Dict[str, Any], offer, other_rates: int, on_request,
) -> None:
    """One property: real name, photo, and its cheapest live rate.

    Every figure is attributed to the supplier and stamped with the
    time it was retrieved; anything the supplier did not state is
    labelled as not stated rather than guessed.
    """
    name = hotel.get("name") or "Property name not provided"
    image = hotel.get("image")

    with ui.card().tight().classes("tv-glass tv-card w-full"):
        with ui.row().classes("w-full no-wrap items-stretch gap-0"):
            # --- photo ---
            with ui.element("div").classes(
                "relative w-44 shrink-0 hidden sm:block"
            ).style("min-height: 10rem"):
                with ui.element("div").classes("tv-placeholder"):
                    ui.label(name[:1].upper()).classes("tv-initial")
                if image:
                    ui.image(image).classes(
                        "tv-zoom absolute inset-0 w-full h-full"
                    ).props("fit=cover no-spinner")

            # --- detail ---
            with ui.column().classes("flex-grow p-4 gap-1"):
                ui.label(name).classes(
                    "tv-display text-lg font-semibold leading-tight")
                location = ", ".join(
                    p for p in (hotel.get("address"),
                                hotel.get("city")) if p)
                if location:
                    ui.label(location).classes("text-xs tv-muted")
                if hotel.get("rating"):
                    stars = f"{hotel['rating']}"
                    reviews = hotel.get("review_count")
                    ui.label(
                        f"Rated {stars}"
                        + (f" from {reviews} reviews" if reviews else "")
                        + " (supplier data)"
                    ).classes("text-xs tv-muted")
                ui.label(offer.room_name
                         or "Room type not stated").classes(
                    "text-sm pt-1")
                with ui.row().classes("gap-2 flex-wrap pt-1"):
                    ui.label(BOARD_LABELS.get(offer.board_type,
                                              "Board not stated")) \
                        .classes("tv-badge")
                    ui.label(
                        "Free cancellation" if offer.refundable is True
                        else "Non-refundable"
                        if offer.refundable is False
                        else "Cancellation terms not stated"
                    ).classes("tv-badge")
                    ui.label(f"{offer.nights} nights, "
                             f"{offer.occupancy} guests").classes(
                        "tv-badge")
                    if other_rates:
                        ui.label(f"+{other_rates} more rates").classes(
                            "tv-badge")
                stamp = offer.retrieved_at.strftime(
                    "%Y-%m-%d %H:%M UTC")
                expires_at = offer.expires_at
                if expires_at and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(
                        tzinfo=timezone.utc)
                valid_for = ""
                if expires_at:
                    mins = max(0, int(
                        (expires_at - datetime.now(timezone.utc))
                        .total_seconds() // 60))
                    valid_for = f", quote held ~{mins} min"
                ui.label(f"Retrieved {stamp}{valid_for}").classes(
                    "tv-mono text-[10px] tv-muted pt-1")

            # --- price ---
            with ui.column().classes(
                "items-end p-4 gap-0 shrink-0 justify-between"
            ):
                with ui.column().classes("items-end gap-0"):
                    ui.label(
                        f"{offer.total_price:.2f} {offer.currency}"
                    ).classes("tv-mono text-xl font-semibold")
                    if offer.price_per_night:
                        ui.label(f"{offer.price_per_night:.2f} "
                                 f"{offer.currency}/night").classes(
                            "tv-mono text-xs tv-muted")
                    ui.label(f"Price from {offer.supplier}").classes(
                        "tv-mono text-[10px] tv-muted")
                    ui.label("Total incl. taxes and fees"
                             if offer.taxes_included
                             else "Taxes/fees may be added at "
                                  "checkout").classes(
                        "tv-mono text-[10px] tv-muted")
                ui.button("Can you beat this price?",
                          on_click=lambda o=offer, n=name:
                              on_request(o, n)).props(
                    "outline dense no-caps icon=sym_r_gavel").classes(
                    "mt-2")


def rates_freshness_bar(result, on_refresh, auto_state: Dict) -> None:
    """Show how old the live quotes are and refresh them before they
    expire.

    Prices move minute to minute, so a figure on screen is only true
    as of the moment it was retrieved. This bar makes that explicit
    and re-queries the supplier rather than letting a stale number sit
    there looking current.
    """
    retrieved = result.retrieved_at or datetime.now(timezone.utc)
    # The earliest expiry across the displayed quotes governs the page.
    expiries = [o.expires_at for o in result.offers if o.expires_at]
    expires = min(expiries) if expiries else (
        retrieved + timedelta(minutes=30))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    with ui.row().classes(
        "w-full items-center gap-3 flex-wrap tv-glass p-3"
    ):
        ui.icon("sym_r_bolt").classes("text-primary")
        ui.label("Live supplier rates").classes(
            "tv-mono text-xs font-semibold")
        age_label = ui.label("").classes("tv-mono text-xs tv-muted")
        ui.space()
        auto_switch = ui.switch(
            "Auto-refresh", value=auto_state.get("on", True),
        ).props("dense").classes("text-xs")
        auto_switch.on_value_change(
            lambda e: auto_state.update(on=bool(e.value)))
        ui.button("Refresh now", on_click=on_refresh).props(
            "outline dense no-caps icon=sym_r_refresh")

    def tick() -> None:
        now = datetime.now(timezone.utc)
        age = int((now - retrieved).total_seconds())
        remaining = int((expires - now).total_seconds())
        if remaining <= 0:
            age_label.set_text(
                f"retrieved {age // 60}m {age % 60}s ago - quotes "
                f"expired, refreshing")
            age_label.classes(replace="tv-mono text-xs text-red-600")
            if auto_state.get("on", True) and not auto_state.get(
                    "refreshing"):
                auto_state["refreshing"] = True
                asyncio.create_task(on_refresh())
            return
        age_label.set_text(
            f"retrieved {age // 60}m {age % 60}s ago - valid for "
            f"another {remaining // 60}m {remaining % 60}s")
        age_label.classes(
            replace="tv-mono text-xs "
                    + ("text-amber-700" if remaining < 120
                       else "tv-muted"))

    tick()
    ui.timer(1.0, tick)


def unavailable_notice(result) -> None:
    with ui.card().classes("tv-glass w-full p-5 gap-2"):
        ui.icon("sym_r_info").classes("text-2xl text-primary")
        ui.label(result.message or
                 "Live hotel pricing is temporarily unavailable.") \
            .classes("font-medium")
        ui.label(
            "We don't show estimated prices. You can still tell us what "
            "you need and our team will check direct and partner rates."
        ).classes("text-sm tv-muted")


# ----------------------------------------------------------------------
# Better-offer dialog
# ----------------------------------------------------------------------


def request_offer_url(destination: str, hotel: Optional[str] = None,
                      check_in: Optional[str] = None,
                      check_out: Optional[str] = None,
                      guests: int = 2, rooms: int = 1,
                      provider: Optional[str] = None,
                      price: Optional[float] = None,
                      currency: Optional[str] = None,
                      room: Optional[str] = None,
                      board: Optional[str] = None) -> str:
    from urllib.parse import urlencode

    params = {"destination": destination, "guests": guests,
              "rooms": rooms}
    for key, value in (("hotel", hotel), ("check_in", check_in),
                       ("check_out", check_out), ("provider", provider),
                       ("price", price), ("currency", currency),
                       ("room", room), ("board", board)):
        if value not in (None, ""):
            params[key] = value
    return "/request-offer?" + urlencode(params)


@ui.page("/request-offer")
def request_offer_page(
    destination: str = "", hotel: str = "", check_in: str = "",
    check_out: str = "", guests: int = 2, rooms: int = 1,
    provider: str = "", price: float = None, currency: str = "EUR",
    room: str = "", board: str = "unknown",
) -> None:
    """Better-offer request form. Noindex: it is a lead form, not
    content, and indexing it would create faceted duplicates."""
    meta = PageMeta(
        title=f"Request a better offer -- {destination or 'your stay'}",
        description="Ask our travel team to check direct and partner "
                    "rates for your stay.",
        path="/request-offer", noindex=True,
    )
    ui.add_head_html(meta.to_html())
    analytics.track("better_offer_clicked", destination=destination,
                    session_hash=session_hash(_client_key()))

    with page_shell("Request a better offer"):
        with ui.row().classes("gap-1 items-center tv-mono text-xs"):
            ui.link("Hotels", "/hotels").classes("text-primary")
            if destination:
                ui.label("/").classes("tv-muted")
                ui.link(destination,
                        hotels_city_path(destination)).classes(
                    "text-primary")

        form_card = ui.card().classes(
            "tv-glass w-full max-w-3xl p-6 gap-3")
        with form_card:
            ui.label("Request a better offer").classes(
                "tv-display text-2xl font-semibold")
            ui.label(
                "Send us what you found and our travel team will check "
                "direct and partner rates. If we can't beat it, we'll "
                "say so -- we don't invent discounts."
            ).classes("text-sm tv-muted")

            with ui.row().classes("w-full gap-3"):
                name_in = ui.input("Your name *").props(
                    "dense outlined").classes("flex-grow")
                email_in = ui.input("Email *").props(
                    "dense outlined").classes("flex-grow")
            with ui.row().classes("w-full gap-3"):
                phone_in = ui.input("Phone (optional)").props(
                    "dense outlined").classes("flex-grow")
                hotel_in = ui.input("Hotel", value=hotel).props(
                    "dense outlined").classes("flex-grow")
            with ui.row().classes("w-full gap-3"):
                in_in = ui.input("Check-in", value=check_in).props(
                    "dense outlined type=date").classes("flex-grow")
                out_in = ui.input("Check-out", value=check_out).props(
                    "dense outlined type=date").classes("flex-grow")
                guests_in = ui.number("Guests", value=guests,
                                      min=1).props(
                    "dense outlined").classes("w-28")
                rooms_in = ui.number("Rooms", value=rooms, min=1).props(
                    "dense outlined").classes("w-28")
            with ui.row().classes("w-full gap-3"):
                provider_in = ui.input("Where did you find it?",
                                       value=provider).props(
                    "dense outlined").classes("flex-grow")
                price_in = ui.number("Their price (total)",
                                     value=price).props(
                    "dense outlined").classes("w-44")
                currency_in = ui.input("Currency",
                                       value=currency or "EUR").props(
                    "dense outlined").classes("w-28")
            with ui.row().classes("w-full gap-3"):
                room_in = ui.input("Room type", value=room).props(
                    "dense outlined").classes("flex-grow")
                board_in = ui.select(
                    list(BOARD_LABELS.keys()),
                    value=board if board in BOARD_LABELS else "unknown",
                    label="Meal plan",
                ).props("dense outlined").classes("w-52")
            url_in = ui.input(
                "Link to the offer you found (optional)").props(
                "dense outlined").classes("w-full")
            message_in = ui.textarea(
                "Anything else we should know?").props(
                "dense outlined").classes("w-full")
            consent = ui.checkbox(
                "You may contact me by email about this request. *")

            status = ui.label("").classes("text-sm")

            async def submit() -> None:
                status.classes(replace="text-sm tv-muted")
                status.set_text("Sending...")
                payload = {
                    "customer_name": name_in.value,
                    "customer_email": email_in.value,
                    "customer_phone": phone_in.value,
                    "destination": destination,
                    "hotel_name": hotel_in.value,
                    "check_in": in_in.value or None,
                    "check_out": out_in.value or None,
                    "guests": int(guests_in.value or 2),
                    "rooms": int(rooms_in.value or 1),
                    "room_type": room_in.value,
                    "meal_plan": board_in.value,
                    "current_provider": provider_in.value,
                    "competitor_price": price_in.value,
                    "currency": currency_in.value or "EUR",
                    "competitor_url": url_in.value,
                    "customer_message": message_in.value,
                    "consent": bool(consent.value),
                    "source_page": "/request-offer",
                }
                try:
                    lead = await asyncio.to_thread(
                        lead_service.create_request, payload,
                        _client_key())
                except LeadError as exc:
                    status.set_text(str(exc))
                    status.classes(replace="text-sm text-red-600")
                    return
                except Exception as exc:      # surface, never swallow
                    status.set_text(f"Something went wrong: {exc}")
                    status.classes(replace="text-sm text-red-600")
                    return
                analytics.track(
                    "email_submitted", destination=destination,
                    session_hash=session_hash(_client_key()))
                form_card.clear()
                with form_card:
                    ui.icon("sym_r_check_circle").classes(
                        "text-4xl text-primary")
                    ui.label(f"Request #{lead['id']} received").classes(
                        "tv-display text-2xl font-semibold")
                    ui.label(
                        "We've emailed you a confirmation. Our team "
                        "will check direct and partner rates and get "
                        "back to you."
                    ).classes("text-sm tv-muted")
                    ui.button(
                        "Back to hotels",
                        on_click=lambda: ui.navigate.to("/hotels"),
                    ).props("unelevated color=primary no-caps")

            with ui.row().classes("w-full justify-end gap-2 pt-1"):
                ui.button(
                    "Cancel",
                    on_click=lambda: ui.navigate.to(
                        hotels_city_path(destination) if destination
                        else "/hotels"),
                ).props("flat no-caps")
                ui.button("Send request", on_click=submit).props(
                    "unelevated color=primary no-caps icon=sym_r_send")


# ----------------------------------------------------------------------
# /hotels
# ----------------------------------------------------------------------

@ui.page("/hotels")
def hotels_hub() -> None:
    meta = PageMeta(
        title="Hotels -- real availability, transparent totals",
        description=(
            "Search hotels with live supplier availability and all-in "
            "totals, then ask our travel team to check direct and "
            "partner rates for a better offer."
        ),
        path="/hotels",
    )
    inject_seo(meta, organization_jsonld(), website_jsonld(),
               breadcrumb_jsonld([("Hotels", "/hotels")]))
    analytics.track("landing_page_visit",
                    session_hash=session_hash(_client_key()),
                    attributes={"page": "/hotels"})

    with page_shell("Hotels"):
        with ui.element("div").classes("tv-hero w-full"):
            with ui.column().classes(
                "w-full p-8 sm:p-12 gap-2 relative z-10"
            ):
                ui.label("HOTELS - LIVE SUPPLIER DATA").classes(
                    "tv-eyebrow")
                ui.label("Find the right hotel. Then let us find you "
                         "a better deal.").classes(
                    "tv-display text-3xl sm:text-5xl font-semibold "
                    "leading-tight")
                ui.label(
                    "Search real hotel offers and, when available, ask "
                    "our team to find a better direct or partner rate."
                ).classes("opacity-85")

        # Anywhere on earth: the destination is geocoded at search
        # time, so this is not limited to a curated list.
        with ui.card().classes("tv-glass w-full p-4 gap-2"):
            ui.label("Search any destination worldwide").classes(
                "tv-display text-xl font-semibold")
            with ui.row().classes("w-full gap-2 items-center"):
                place_in = ui.input(
                    placeholder="City, region or country - e.g. "
                                "Kyoto, Reykjavik, Cape Town"
                ).props("dense outlined clearable").classes(
                    "flex-grow")

                def go_anywhere() -> None:
                    value = (place_in.value or "").strip()
                    if not value:
                        ui.notify("Enter a destination first",
                                  type="warning")
                        return
                    parts = [p.strip() for p in value.split(",")
                             if p.strip()]
                    if len(parts) >= 2:
                        ui.navigate.to(
                            hotels_city_path(parts[0], parts[-1]))
                    else:
                        ui.navigate.to(hotels_city_path(parts[0]))

                place_in.on("keydown.enter", go_anywhere)
                ui.button("Find hotels", on_click=go_anywhere).props(
                    "unelevated color=primary no-caps "
                    "icon=sym_r_travel_explore")
            ui.label(
                "Any place with a real location works. Availability "
                "depends on live supplier coverage; where there is "
                "none we say so rather than estimating."
            ).classes("text-xs tv-muted")

        ui.label("Popular destinations").classes(
            "tv-display text-2xl font-semibold")
        with ui.element("div").classes(
            "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 w-full"
        ):
            for city, country in CURATED:
                with ui.card().classes(
                    "tv-glass tv-card w-full p-4 cursor-pointer"
                ).on("click", lambda c=city, k=country: ui.navigate.to(
                        hotels_city_path(c, k))):
                    ui.label(f"{city}").classes(
                        "tv-display text-xl font-semibold")
                    ui.label(country).classes("text-sm tv-muted")
                    ui.label("View hotels ->").classes(
                        "tv-mono text-xs text-primary pt-2")


# ----------------------------------------------------------------------
# /hotels/{city}[/{country}]
# ----------------------------------------------------------------------

@ui.page("/hotels/{city}")
def hotels_city(city: str) -> None:
    _render_city_page(city, None)


@ui.page("/hotels/{city}/{country}")
def hotels_city_country(city: str, country: str) -> None:
    _render_city_page(city, country)


def _titleize(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-"))


def _render_city_page(city_slug: str, country_slug: Optional[str]) -> None:
    city = _titleize(city_slug)
    country = _titleize(country_slug) if country_slug else None

    meta = city_meta(city, country)
    crumbs = [("Hotels", "/hotels"),
              (city, hotels_city_path(city, country))]
    inject_seo(meta, breadcrumb_jsonld(crumbs))
    analytics.track("landing_page_visit", destination=city,
                    session_hash=session_hash(_client_key()),
                    attributes={"page": meta.path})

    with page_shell(f"Hotels in {city}"):
        # Breadcrumb (visible, matching the JSON-LD)
        with ui.row().classes("gap-1 items-center tv-mono text-xs"):
            ui.link("Hotels", "/hotels").classes("text-primary")
            ui.label("/").classes("tv-muted")
            ui.label(city).classes("tv-muted")

        with ui.element("div").classes("tv-hero w-full"):
            with ui.column().classes(
                "w-full p-8 gap-2 relative z-10"
            ):
                ui.label(
                    f"{city.upper()} - REAL AVAILABILITY"
                ).classes("tv-eyebrow")
                ui.label(f"Hotels in {city}").classes(
                    "tv-display text-3xl sm:text-4xl font-semibold")
                ui.label(
                    "Live supplier availability and all-in totals. "
                    "Compare available offers, or request a "
                    "personalised direct offer."
                ).classes("opacity-85 text-sm")

        # Which place we actually searched. "Athens" matches Greece and
        # Georgia, USA, so the choice must be visible and correctable.
        place_bar = ui.row().classes("w-full items-center gap-2 "
                                     "flex-wrap")
        results = ui.column().classes("w-full gap-3")
        fields: Dict[str, Any] = {}
        auto_state: Dict[str, Any] = {"on": True, "refreshing": False}

        async def show_place_options() -> None:
            candidates = await hotel_search_service.place_candidates(
                city, country, limit=5)
            try:
                place_bar.clear()
            except RuntimeError:
                return
            if not candidates:
                return
            chosen = candidates[0]
            with place_bar:
                ui.icon("sym_r_location_on").classes("text-primary")
                ui.label(
                    "Searching " + (chosen.get("formatted")
                                    or chosen["name"])
                ).classes("tv-mono text-xs")
                others = [c for c in candidates[1:]
                          if c.get("country") != chosen.get("country")
                          or c.get("state") != chosen.get("state")][:3]
                if others:
                    ui.label("- did you mean").classes(
                        "tv-mono text-xs tv-muted")
                    for other in others:
                        label = ", ".join(
                            p for p in (other["name"],
                                        other.get("state"),
                                        other.get("country")) if p)
                        ui.button(
                            label,
                            on_click=lambda o=other: ui.navigate.to(
                                hotels_city_path(o["name"],
                                                 o.get("country"))),
                        ).props("flat dense no-caps size=sm")
        # Built once, at page-build time -- reliably openable later.


        async def run_search() -> None:
            auto_state["refreshing"] = False
            results.clear()
            with results:
                with ui.row().classes("items-center gap-2"):
                    ui.spinner(size="sm")
                    ui.label("Searching live availability...").classes(
                        "tv-mono text-sm tv-muted")
            check_in = fields["check_in"].value
            check_out = fields["check_out"].value
            guests = int(fields["guests"].value or 2)
            rooms = int(fields["rooms"].value or 1)
            currency = fields["currency"].value or "EUR"
            try:
                radius_km = int(fields["radius_km"].value or 15)
            except (TypeError, ValueError):
                radius_km = 15
            hotel_search_service.radius_m = max(
                1000, min(100000, radius_km * 1000))

            analytics.track("hotel_search", destination=city,
                            session_hash=session_hash(_client_key()),
                            attributes={"check_in": check_in,
                                        "check_out": check_out,
                                        "guests": guests,
                                        "rooms": rooms})
            result = await hotel_search_service.search(
                city, check_in, check_out, country=country,
                guests=guests, rooms=rooms, currency=currency,
            )
            try:
                results.clear()
            except RuntimeError:
                return
            with results:
                if not result.has_live_prices:
                    unavailable_notice(result)
                    checked = (", ".join(result.suppliers_tried)
                               or "no suppliers configured")
                    stamp = datetime.now(timezone.utc).strftime(
                        "%H:%M:%S UTC")
                    ui.label(
                        f"Checked {checked} at {stamp} - "
                        f"status: {result.status}"
                    ).classes("tv-mono text-[10px] tv-muted")
                    ui.button(
                        "Request a personalised offer",
                        on_click=lambda: ui.navigate.to(
                            request_offer_url(
                                city, check_in=check_in,
                                check_out=check_out, guests=guests,
                                rooms=rooms)),
                    ).props("unelevated color=primary no-caps "
                            "icon=sym_r_mail")
                    return

                rates_freshness_bar(result, run_search, auto_state)
                by_id = {h.get("hotel_id"): h
                         for h in result.hotels}

                # Group rates by property so the page lists hotels,
                # not thousands of individual room rates.
                grouped: Dict[str, list] = {}
                for offer in result.offers:
                    grouped.setdefault(offer.room_id or "", []).append(
                        offer)
                for rates in grouped.values():
                    rates.sort(key=lambda o: o.total_price)

                # Attach property metadata, then filter and sort.
                pairs = []
                for hotel_id, rates in grouped.items():
                    top = rates[0]
                    hotel_meta = dict(by_id.get(hotel_id) or {})
                    for key, value in (
                        ("name", top.hotel_name),
                        ("image", top.hotel_image),
                        ("rating", top.hotel_rating),
                        ("review_count", top.hotel_review_count),
                        ("address", top.hotel_address),
                    ):
                        if not hotel_meta.get(key) and value:
                            hotel_meta[key] = value
                    pairs.append((hotel_meta, rates))

                ranked = apply_filters(pairs, fields)
                total_rates = sum(len(r) for _, r in ranked)

                ui.label(
                    f"{len(ranked)} properties, {total_rates} live "
                    f"rates (of {len(result.offers)} returned) - "
                    f"prices from "
                    f"{', '.join(result.suppliers_tried)}"
                ).classes("tv-mono text-xs tv-muted")

                if not ranked:
                    ui.label(
                        "No live rates match these filters. Widen the "
                        "budget or clear a filter - we do not relax "
                        "them silently."
                    ).classes("text-sm tv-muted")

                for hotel_meta, rates in ranked:
                    top = rates[0]
                    # The offer carries its own property details when
                    # the supplier provided them.
                    for key, value in (
                        ("name", top.hotel_name),
                        ("image", top.hotel_image),
                        ("rating", top.hotel_rating),
                        ("review_count", top.hotel_review_count),
                        ("address", top.hotel_address),
                    ):
                        if not hotel_meta.get(key) and value:
                            hotel_meta[key] = value
                    analytics.track(
                        "hotel_impression", destination=city,
                        session_hash=session_hash(_client_key()))
                    hotel_offer_card(
                        hotel_meta, top, len(rates) - 1,
                        on_request=lambda o, n: ui.navigate.to(
                            request_offer_url(
                                city, hotel=n, check_in=check_in,
                                check_out=check_out, guests=guests,
                                rooms=rooms, provider=o.supplier,
                                price=o.total_price,
                                currency=o.currency, room=o.room_name,
                                board=o.board_type)),
                    )

        fields.update(search_form(city, country, run_search))

        with ui.card().classes("tv-glass w-full p-5 gap-2"):
            ui.label("Looking for a better price?").classes(
                "tv-display text-xl font-semibold")
            ui.label(
                "Send us the hotel you found and we'll check whether we "
                "can offer you a better deal. No obligation, and no "
                "invented discounts."
            ).classes("text-sm tv-muted")
            ui.button("Request a better offer",
                      on_click=lambda: ui.navigate.to(
                          request_offer_url(city))).props(
                "unelevated color=accent text-color=black no-caps "
                "icon=sym_r_gavel")

        ui.label(f"About staying in {city}").classes(
            "tv-display text-xl font-semibold pt-2")
        ui.label(
            f"{city} listings on this page come from live supplier "
            f"availability at the moment you search. Totals include "
            f"taxes and fees where the supplier reports them, and each "
            f"price shows which supplier it came from and when it was "
            f"retrieved. Where we cannot retrieve a live price, we say "
            f"so rather than showing an estimate."
        ).classes("text-sm tv-muted max-w-3xl")

        ui.timer(0.1, show_place_options, once=True)
        ui.timer(0.2, run_search, once=True)


# ----------------------------------------------------------------------
# /offer/{token}  -- private, noindex
# ----------------------------------------------------------------------

@ui.page("/offer/{token}")
def customer_offer_page(token: str) -> None:
    meta = PageMeta(
        title="Your personalised offer",
        description="Your personalised hotel offer.",
        path=f"/offer/{token}", noindex=True,
    )
    ui.add_head_html(meta.to_html())   # noindex; no JSON-LD on private pages

    offer, reason = offer_token_service.resolve(token)
    with page_shell("Your offer"):
        if offer is None:
            ui.label("This offer link is no longer valid").classes(
                "tv-display text-2xl font-semibold")
            ui.label(
                "It may have expired or been withdrawn. Request a new "
                "one and our team will pick it up."
                if reason == "expired" else
                "Please check the link in your email, or request a new "
                "offer and our team will pick it up."
            ).classes("text-sm tv-muted")
            ui.button("Request a new offer",
                      on_click=lambda: ui.navigate.to("/hotels")).props(
                "unelevated color=primary no-caps")
            return

        offer_token_service.mark_opened(token)
        analytics.track("offer_email_opened",
                        session_hash=session_hash(_client_key()))

        with ui.card().classes("tv-glass w-full max-w-3xl p-6 gap-3"):
            ui.label("Your personalised offer").classes("tv-eyebrow") \
                .style("color: var(--tv-teal)")
            ui.label(offer.hotel_name).classes(
                "tv-display text-3xl font-semibold")
            with ui.row().classes("gap-2 flex-wrap"):
                if offer.check_in and offer.check_out:
                    ui.label(f"{offer.check_in} -> {offer.check_out}") \
                        .classes("tv-badge")
                if offer.guests:
                    ui.label(f"{offer.guests} guests").classes("tv-badge")
                if offer.rooms:
                    ui.label(f"{offer.rooms} rooms").classes("tv-badge")
                if offer.board_type:
                    ui.label(BOARD_LABELS.get(offer.board_type,
                                              offer.board_type)) \
                        .classes("tv-badge")
            if offer.room_description:
                ui.label(offer.room_description).classes("text-sm")

            ui.separator()
            with ui.row().classes("w-full items-end gap-6"):
                with ui.column().classes("gap-0"):
                    ui.label("Our offer").classes(
                        "tv-mono text-xs tv-muted uppercase")
                    ui.label(
                        f"{offer.our_price:.2f} {offer.currency}"
                    ).classes("tv-mono text-3xl font-semibold")
                # A reference price is shown only when staff recorded a
                # verified comparable quote.
                if offer.reference_price:
                    saving = offer.reference_price - offer.our_price
                    if saving > 0:
                        with ui.column().classes("gap-0"):
                            ui.label("Reference price").classes(
                                "tv-mono text-xs tv-muted uppercase")
                            ui.label(
                                f"{offer.reference_price:.2f} "
                                f"{offer.currency}"
                            ).classes("tv-mono text-lg line-through "
                                      "tv-muted")
                        with ui.column().classes("gap-0"):
                            ui.label("You save").classes(
                                "tv-mono text-xs tv-muted uppercase")
                            ui.label(
                                f"{saving:.2f} {offer.currency}"
                            ).classes("tv-mono text-lg font-semibold "
                                      "text-primary")

            if offer.cancellation_policy:
                ui.label(f"Cancellation: {offer.cancellation_policy}") \
                    .classes("text-sm tv-muted")
            if offer.conditions:
                ui.label(offer.conditions).classes("text-sm tv-muted")

            expires = offer.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            ui.label(
                "This offer expires "
                + expires.strftime("%Y-%m-%d %H:%M UTC")
            ).classes("tv-mono text-xs tv-muted")

            async def start_checkout() -> None:
                from app.services.payments import (
                    PaymentError, payment_service,
                )
                if not payment_service.configured:
                    ui.notify(
                        "Card payment isn't enabled yet -- reply to your "
                        "offer email and we'll arrange payment with you.",
                        type="warning")
                    return
                try:
                    session_data = await \
                        payment_service.create_checkout_session(
                            offer.id)
                except PaymentError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                analytics.track(
                    "checkout_started",
                    session_hash=session_hash(_client_key()))
                ui.navigate.to(session_data["checkout_url"],
                               new_tab=False)

            ui.button("Continue to secure payment",
                      on_click=start_checkout).props(
                "unelevated color=primary no-caps size=lg "
                "icon=sym_r_lock")
            ui.label(
                "Payment is processed by our PCI-compliant payment "
                "provider. We never see or store your card details."
            ).classes("text-xs tv-muted")


@ui.page("/pay/success")
def payment_success(offer: Optional[int] = None) -> None:
    """Redirect landing page. Deliberately does NOT mark anything paid --
    only the signed Stripe webhook may change payment status."""
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    with page_shell("Payment"):
        with ui.card().classes("tv-glass w-full max-w-xl p-6 gap-2"):
            ui.icon("sym_r_check_circle").classes(
                "text-4xl text-primary")
            ui.label("Thank you -- your payment is being confirmed") \
                .classes("tv-display text-2xl font-semibold")
            ui.label(
                "We'll email your confirmation as soon as the payment "
                "provider confirms the transaction. If anything goes "
                "wrong, we'll contact you."
            ).classes("text-sm tv-muted")
            ui.button("Back to hotels",
                      on_click=lambda: ui.navigate.to("/hotels")).props(
                "unelevated color=primary no-caps")


@ui.page("/pay/cancelled")
def payment_cancelled(offer: Optional[int] = None) -> None:
    ui.add_head_html('<meta name="robots" content="noindex, nofollow">')
    with page_shell("Payment"):
        with ui.card().classes("tv-glass w-full max-w-xl p-6 gap-2"):
            ui.label("Payment cancelled").classes(
                "tv-display text-2xl font-semibold")
            ui.label(
                "Nothing has been charged. Your offer link stays valid "
                "until it expires, so you can come back to it."
            ).classes("text-sm tv-muted")
            ui.button("Back to hotels",
                      on_click=lambda: ui.navigate.to("/hotels")).props(
                "unelevated color=primary no-caps")
