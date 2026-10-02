# -*- coding: utf-8 -*-

"""
Quotes: multi-service itineraries built by an agent for a client.

A quote holds any mix of the five services (hotel, ticket, transfer,
car rental, tour) as ordered lines. Totals always come from
:mod:`app.services.agency.pricing`, so the figure on screen, on the
invoice and in the reports is computed once.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.pricing import (
    SERVICE_TYPES, price_quote,
)

logger = logging.getLogger(__name__)

STATUSES = ("draft", "sent", "accepted", "rejected", "expired",
            "booked", "cancelled")


class QuoteError(Exception):
    """A user-safe problem with a quote."""


def new_reference(prefix: str = "Q") -> str:
    """Short, unguessable, human-readable quote reference."""
    stamp = datetime.now(timezone.utc).strftime("%y%m")
    return f"{prefix}{stamp}-{secrets.token_hex(3).upper()}"


class QuoteService:
    def __init__(
        self, session_factory: Optional[Callable[[], Any]] = None
    ) -> None:
        self._session_factory = session_factory

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    # ------------------------------------------------------------------

    def create(
        self, agency_id: int, agent_id: int,
        client_id: Optional[int] = None, title: str = "",
        currency: str = "EUR", valid_days: int = 7,
        pax_adults: int = 1, pax_children: int = 0,
        travel_start: Optional[str] = None,
        travel_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.db.models import Quote

        session = self._sessions()()
        try:
            quote = Quote(
                agency_id=agency_id, agent_id=agent_id,
                client_id=client_id,
                reference=new_reference(),
                title=(title or "Itinerary").strip()[:250],
                currency=currency.upper()[:3],
                pax_adults=max(1, int(pax_adults or 1)),
                pax_children=max(0, int(pax_children or 0)),
                travel_start=travel_start, travel_end=travel_end,
                status="draft",
                valid_until=datetime.now(timezone.utc)
                + timedelta(days=max(1, valid_days)),
            )
            session.add(quote)
            session.commit()
            return {"id": quote.id, "reference": quote.reference}
        finally:
            session.close()

    def add_item(
        self, quote_id: int, service_type: str, title: str,
        net_cost: float = 0.0, service_charge: float = 0.0,
        quantity: int = 1, is_domestic: bool = False,
        vat_rate: float = 24.0, supplier: Optional[str] = None,
        supplier_reference: Optional[str] = None,
        starts_on: Optional[str] = None,
        ends_on: Optional[str] = None,
        pax: Optional[int] = None,
        description: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Dict[str, Any]:
        from app.db.models import QuoteItem

        service_type = (service_type or "").strip().lower()
        if service_type not in SERVICE_TYPES:
            raise QuoteError(
                f"Unknown service '{service_type}'. Use one of: "
                + ", ".join(SERVICE_TYPES))
        if not (title or "").strip():
            raise QuoteError("Every line needs a description.")

        session = self._sessions()()
        try:
            position = (session.query(QuoteItem)
                        .filter(QuoteItem.quote_id == quote_id)
                        .count())
            item = QuoteItem(
                quote_id=quote_id, position=position,
                service_type=service_type, title=title.strip()[:250],
                description=description, supplier=supplier,
                supplier_reference=supplier_reference,
                starts_on=starts_on, ends_on=ends_on,
                quantity=max(1, int(quantity or 1)),
                pax=pax, net_cost=float(net_cost or 0),
                service_charge=float(service_charge or 0),
                vat_rate=float(vat_rate or 0),
                is_domestic=bool(is_domestic),
                details=details,
            )
            session.add(item)
            session.commit()
            return {"id": item.id, "position": item.position}
        finally:
            session.close()

    def remove_item(self, item_id: int) -> bool:
        from app.db.models import QuoteItem

        session = self._sessions()()
        try:
            item = session.get(QuoteItem, item_id)
            if item is None:
                return False
            session.delete(item)
            session.commit()
            return True
        finally:
            session.close()

    # ------------------------------------------------------------------

    def get(self, quote_id: int) -> Optional[Dict[str, Any]]:
        """A quote with its lines and freshly computed totals."""
        from app.db.models import Quote

        session = self._sessions()()
        try:
            quote = session.get(Quote, quote_id)
            if quote is None:
                return None
            items = [{
                "id": item.id,
                "position": item.position,
                "service_type": item.service_type,
                "title": item.title,
                "description": item.description,
                "supplier": item.supplier,
                "supplier_reference": item.supplier_reference,
                "starts_on": item.starts_on,
                "ends_on": item.ends_on,
                "quantity": item.quantity,
                "pax": item.pax,
                "net_cost": item.net_cost,
                "service_charge": item.service_charge,
                "vat_rate": item.vat_rate,
                "is_domestic": item.is_domestic,
                "details": item.details,
            } for item in quote.items]
            payload = {
                "id": quote.id,
                "reference": quote.reference,
                "title": quote.title,
                "status": quote.status,
                "currency": quote.currency,
                "client_id": quote.client_id,
                "agent_id": quote.agent_id,
                "agency_id": quote.agency_id,
                "travel_start": quote.travel_start,
                "travel_end": quote.travel_end,
                "pax_adults": quote.pax_adults,
                "pax_children": quote.pax_children,
                "notes": quote.notes,
                "valid_until": (quote.valid_until.isoformat()
                                if quote.valid_until else None),
                "items": items,
            }
        finally:
            session.close()

        payload["totals"] = price_quote(
            items, currency=payload["currency"]).to_dict()
        return payload

    def set_status(self, quote_id: int, status: str) -> bool:
        from app.db.models import Quote

        status = (status or "").strip().lower()
        if status not in STATUSES:
            raise QuoteError(f"Unknown status '{status}'.")
        session = self._sessions()()
        try:
            quote = session.get(Quote, quote_id)
            if quote is None:
                return False
            quote.status = status
            session.commit()
            return True
        finally:
            session.close()

    def list_for(
        self, agency_id: int, agent_id: Optional[int] = None,
        client_id: Optional[int] = None, status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Quotes visible to one agent, or the whole office."""
        from app.db.models import Quote

        session = self._sessions()()
        try:
            query = (session.query(Quote)
                     .filter(Quote.agency_id == agency_id))
            if agent_id is not None:
                query = query.filter(Quote.agent_id == agent_id)
            if client_id is not None:
                query = query.filter(Quote.client_id == client_id)
            if status:
                query = query.filter(Quote.status == status)
            rows = (query.order_by(Quote.id.desc()).limit(limit).all())
            return [{
                "id": q.id, "reference": q.reference,
                "title": q.title, "status": q.status,
                "client_id": q.client_id, "agent_id": q.agent_id,
                "currency": q.currency,
                "travel_start": q.travel_start,
                "created_at": (q.created_at.isoformat()
                               if q.created_at else None),
                "total": float(price_quote(
                    [{
                        "net_cost": i.net_cost,
                        "service_charge": i.service_charge,
                        "quantity": i.quantity,
                        "is_domestic": i.is_domestic,
                        "vat_rate": i.vat_rate,
                        "service_type": i.service_type,
                    } for i in q.items],
                    currency=q.currency).total),
            } for q in rows]
        finally:
            session.close()


quote_service = QuoteService()
