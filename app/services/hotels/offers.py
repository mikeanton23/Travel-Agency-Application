# -*- coding: utf-8 -*-

"""
Normalized hotel offers and the comparability engine.

This module is where the platform's central honesty rule lives: a
"cheaper than X" claim may only be shown when two offers are
*materially equivalent* -- same hotel, room class, occupancy, dates,
board, cancellation terms, currency, and an all-in total that includes
taxes and fees the same way.

Anything short of that returns a lower-strength verdict
(``COMPARE`` or ``REQUEST``) which the UI renders as "Compare our
offer" / "Request a personalized offer" -- never as a discount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

# Board plans, normalized. Anything unrecognised becomes UNKNOWN, which
# blocks a savings claim rather than guessing equivalence.
BOARD_ALIASES = {
    "room_only": {"room_only", "roomonly", "ro", "none", "no_meal",
                  "room only"},
    "breakfast": {"breakfast", "bb", "bed_and_breakfast",
                  "breakfast_included", "bed & breakfast"},
    "half_board": {"half_board", "hb", "halfboard", "dinner_bb"},
    "full_board": {"full_board", "fb", "fullboard"},
    "all_inclusive": {"all_inclusive", "ai", "allinclusive"},
}

REFUNDABLE_ALIASES = {
    True: {"free_cancellation", "refundable", "flexible",
           "free cancellation"},
    False: {"non_refundable", "nonrefundable", "no_refund",
            "non refundable"},
}

DEFAULT_TTL_MINUTES = 30


def normalize_board(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    text = str(value).strip().lower().replace("-", "_")
    for canonical, aliases in BOARD_ALIASES.items():
        if text == canonical or text in aliases:
            return canonical
    return "unknown"


def normalize_refundable(value: Any) -> Optional[bool]:
    """True/False when known, ``None`` when the supplier didn't say --
    unknown terms must never be treated as equivalent."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    for flag, aliases in REFUNDABLE_ALIASES.items():
        if text in aliases:
            return flag
    return None


def nights_between(check_in: str, check_out: str) -> int:
    start = datetime.strptime(check_in, "%Y-%m-%d").date()
    end = datetime.strptime(check_out, "%Y-%m-%d").date()
    return max(0, (end - start).days)


@dataclass
class NormalizedOffer:
    """A supplier quote in the platform's canonical shape.

    ``total_price`` is always the all-in figure the guest pays for the
    whole stay in ``currency``; ``taxes``/``fees`` are informational
    breakdowns, never added again on top.
    """

    hotel_id: Optional[int]
    supplier: str
    total_price: float
    currency: str
    check_in: str
    check_out: str
    occupancy: int = 2
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    # Property identity, kept separate from the room description so the
    # UI never shows a room type where a hotel name belongs.
    hotel_name: Optional[str] = None
    hotel_image: Optional[str] = None
    hotel_rating: Optional[float] = None
    hotel_review_count: Optional[int] = None
    hotel_address: Optional[str] = None
    board_type: str = "unknown"
    base_price: Optional[float] = None
    taxes: Optional[float] = None
    fees: Optional[float] = None
    cancellation_policy: Optional[str] = None
    refundable: Optional[bool] = None
    availability: bool = True
    deep_link: Optional[str] = None

    # Property description carried with the quote so the UI can show
    # the real hotel rather than the room name. Populated by whichever
    # provider has it; left None when the supplier does not say.
    hotel_name: Optional[str] = None
    hotel_image: Optional[str] = None
    hotel_rating: Optional[float] = None
    hotel_review_count: Optional[int] = None
    hotel_address: Optional[str] = None
    retrieved_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: Optional[datetime] = None
    taxes_included: bool = True

    def __post_init__(self) -> None:
        self.board_type = normalize_board(self.board_type)
        self.refundable = normalize_refundable(self.refundable)
        self.currency = (self.currency or "").upper()
        if self.expires_at is None:
            self.expires_at = self.retrieved_at + timedelta(
                minutes=DEFAULT_TTL_MINUTES
            )

    @property
    def nights(self) -> int:
        return nights_between(self.check_in, self.check_out)

    @property
    def price_per_night(self) -> Optional[float]:
        n = self.nights
        return round(self.total_price / n, 2) if n else None

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hotel_id": self.hotel_id,
            "supplier": self.supplier,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "hotel_name": self.hotel_name,
            "hotel_image": self.hotel_image,
            "hotel_rating": self.hotel_rating,
            "hotel_review_count": self.hotel_review_count,
            "hotel_address": self.hotel_address,
            "board_type": self.board_type,
            "occupancy": self.occupancy,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "nights": self.nights,
            "currency": self.currency,
            "base_price": self.base_price,
            "taxes": self.taxes,
            "fees": self.fees,
            "total_price": self.total_price,
            "price_per_night": self.price_per_night,
            "cancellation_policy": self.cancellation_policy,
            "refundable": self.refundable,
            "availability": self.availability,
            "deep_link": self.deep_link,
            "hotel_name": self.hotel_name,
            "hotel_image": self.hotel_image,
            "hotel_rating": self.hotel_rating,
            "hotel_review_count": self.hotel_review_count,
            "hotel_address": self.hotel_address,
            "retrieved_at": self.retrieved_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "stale": self.is_stale(),
        }


def from_amadeus_offer(
    raw: Dict[str, Any], hotel_id: Optional[int] = None
) -> Optional[NormalizedOffer]:
    """Adapt one entry from ``AmadeusService.hotel_offers``.

    Returns ``None`` for rows without a usable real price -- a missing
    price is never substituted.
    """
    price = raw.get("price_total")
    check_in = raw.get("check_in")
    check_out = raw.get("check_out")
    if price is None or not check_in or not check_out:
        return None
    return NormalizedOffer(
        hotel_id=hotel_id,
        supplier="amadeus",
        total_price=float(price),
        currency=raw.get("currency", "EUR"),
        check_in=check_in,
        check_out=check_out,
        occupancy=int(raw.get("adults") or 2),
        room_id=raw.get("hotel_id"),
        room_name=raw.get("room_type"),
        board_type=raw.get("board"),
        cancellation_policy=raw.get("cancellation_policy"),
        refundable=raw.get("refundable"),
        availability=bool(raw.get("available", True)),
    )


# ----------------------------------------------------------------------
# Comparability
# ----------------------------------------------------------------------

class Verdict(str, Enum):
    VERIFIED_LOWER = "verified_lower"   # we are cheaper, like-for-like
    NOT_LOWER = "not_lower"             # comparable, we are not cheaper
    COMPARE = "compare"                 # not comparable -> no claim
    REQUEST = "request"                 # nothing to compare against


@dataclass
class ComparisonResult:
    verdict: Verdict
    reasons: List[str] = field(default_factory=list)
    savings: Optional[float] = None
    savings_pct: Optional[float] = None
    currency: Optional[str] = None
    compared_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def may_claim_cheaper(self) -> bool:
        return self.verdict is Verdict.VERIFIED_LOWER

    def headline(self) -> str:
        """UI-safe wording. Only one branch may promise savings."""
        if self.verdict is Verdict.VERIFIED_LOWER:
            return (f"Verified lower direct offer -- you save "
                    f"{self.savings:.2f} {self.currency} "
                    f"({self.savings_pct:.0f}%)")
        if self.verdict is Verdict.NOT_LOWER:
            return "Compare our offer"
        if self.verdict is Verdict.COMPARE:
            return "Compare our offer"
        return "Request our best available offer"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "may_claim_cheaper": self.may_claim_cheaper,
            "headline": self.headline(),
            "reasons": self.reasons,
            "savings": self.savings,
            "savings_pct": self.savings_pct,
            "currency": self.currency,
            "compared_at": self.compared_at.isoformat(),
        }


def comparability_gaps(
    ours: NormalizedOffer, theirs: NormalizedOffer,
    now: Optional[datetime] = None,
) -> List[str]:
    """Every reason these two offers are not like-for-like."""
    gaps: List[str] = []
    if ours.hotel_id is not None and theirs.hotel_id is not None \
            and ours.hotel_id != theirs.hotel_id:
        gaps.append("different hotel")
    if (ours.check_in, ours.check_out) != \
            (theirs.check_in, theirs.check_out):
        gaps.append("different dates")
    if ours.occupancy != theirs.occupancy:
        gaps.append("different occupancy")
    if ours.currency != theirs.currency:
        gaps.append("different currency (convert first)")
    if ours.board_type != theirs.board_type:
        gaps.append("different meal plan")
    if "unknown" in (ours.board_type, theirs.board_type):
        gaps.append("meal plan not stated by one supplier")
    if ours.refundable is None or theirs.refundable is None:
        gaps.append("cancellation terms not stated by one supplier")
    elif ours.refundable != theirs.refundable:
        gaps.append("different cancellation terms")
    if not (ours.taxes_included and theirs.taxes_included):
        gaps.append("taxes/fees treated differently")
    if _room_class(ours.room_name) != _room_class(theirs.room_name):
        gaps.append("different room type")
    if ours.is_stale(now) or theirs.is_stale(now):
        gaps.append("a quote has expired")
    if not ours.availability or not theirs.availability:
        gaps.append("one offer is not available")
    return gaps


def _room_class(name: Optional[str]) -> str:
    """Coarse room class so 'Deluxe King' and 'DELUXE' match, while
    'Standard' and 'Suite' do not. Unknown names never match."""
    if not name:
        return "unknown"
    text = name.strip().lower()
    for token in ("presidential", "suite", "junior_suite", "deluxe",
                  "superior", "executive", "family", "standard",
                  "economy", "twin", "double", "single"):
        if token.replace("_", " ") in text:
            return token
    return "unknown"


def compare_offers(
    ours: Optional[NormalizedOffer],
    competitor: Optional[NormalizedOffer],
    now: Optional[datetime] = None,
) -> ComparisonResult:
    """The only sanctioned way to produce a savings claim."""
    if competitor is None or ours is None:
        return ComparisonResult(
            Verdict.REQUEST,
            ["no comparable supplier quote retrieved"],
        )
    gaps = comparability_gaps(ours, competitor, now=now)
    if gaps:
        return ComparisonResult(Verdict.COMPARE, gaps)
    if ours.total_price >= competitor.total_price:
        return ComparisonResult(
            Verdict.NOT_LOWER,
            ["comparable, but our total is not lower"],
            currency=ours.currency,
        )
    savings = round(competitor.total_price - ours.total_price, 2)
    pct = round(savings / competitor.total_price * 100, 1)
    return ComparisonResult(
        Verdict.VERIFIED_LOWER,
        ["like-for-like on hotel, room class, dates, occupancy, "
         "board, cancellation, currency and all-in total"],
        savings=savings, savings_pct=pct, currency=ours.currency,
    )


def best_offer(
    offers: List[NormalizedOffer], now: Optional[datetime] = None
) -> Optional[NormalizedOffer]:
    """Cheapest live, available offer. Stale quotes are excluded rather
    than shown as if current."""
    live = [o for o in offers
            if o.availability and not o.is_stale(now)]
    return min(live, key=lambda o: o.total_price) if live else None
