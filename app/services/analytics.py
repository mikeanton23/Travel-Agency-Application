# -*- coding: utf-8 -*-

"""
Privacy-conscious funnel analytics.

Events are written to ``search_events`` with a salted session hash --
never an IP, email, or name. A provider abstraction lets an external
analytics backend be added later without touching call sites.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

EVENTS = [
    "landing_page_visit", "hotel_search", "hotel_impression",
    "hotel_view", "hotel_click", "offer_comparison",
    "better_offer_clicked", "email_submitted", "email_capture",
    "offer_request_created", "offer_email_sent", "offer_email_opened",
    "offer_page_opened", "checkout_started", "payment_started",
    "payment_completed", "payment_failed", "payment_success",
    "payment_failure",
]


class AnalyticsSink(ABC):
    name = "base"

    @abstractmethod
    def emit(self, event: str, payload: Dict[str, Any]) -> None: ...


class DatabaseSink(AnalyticsSink):
    name = "database"

    def __init__(self, session_factory: Optional[Callable] = None):
        self._session_factory = session_factory

    def _sessions(self):
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        from app.db.models import SearchEvent

        session = self._sessions()()
        try:
            session.add(SearchEvent(
                event=event,
                destination=payload.get("destination"),
                hotel_id=payload.get("hotel_id"),
                session_hash=payload.get("session_hash"),
                attributes=payload.get("attributes"),
            ))
            session.commit()
        finally:
            session.close()


class NullSink(AnalyticsSink):
    name = "null"

    def emit(self, event, payload) -> None:
        logger.debug("[analytics:null] %s %s", event, payload)


class Analytics:
    def __init__(self, sink: Optional[AnalyticsSink] = None) -> None:
        self._sink = sink

    def sink(self) -> AnalyticsSink:
        if self._sink is None:
            self._sink = DatabaseSink()
        return self._sink

    def track(self, event: str, **payload: Any) -> None:
        """Never raises: analytics must not break a customer flow."""
        if event not in EVENTS:
            logger.debug("Unknown analytics event '%s'", event)
        try:
            self.sink().emit(event, payload)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("analytics emit skipped: %s", exc)

    def funnel_counts(self, session_factory=None) -> List[Dict[str, Any]]:
        from sqlalchemy import func as sql_func
        from app.db.models import SearchEvent

        if session_factory is None:
            from app.db.database import SessionLocal
            session_factory = SessionLocal
        session = session_factory()
        try:
            rows = (
                session.query(SearchEvent.event,
                              sql_func.count(SearchEvent.id))
                .group_by(SearchEvent.event).all()
            )
            return [{"event": e, "count": c} for e, c in rows]
        finally:
            session.close()


analytics = Analytics()
