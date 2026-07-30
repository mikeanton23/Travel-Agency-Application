# -*- coding: utf-8 -*-

"""
Destination data access — the reference implementation of the
repository pattern for this codebase. New repositories (hotels, trips,
events, users) should follow this shape.
"""

from __future__ import annotations

from typing import List, Optional

from app.db.models import Destination
from app.repositories.base import BaseRepository


class DestinationRepository(BaseRepository[Destination]):
    model = Destination

    def search(
        self,
        query: Optional[str] = None,
        country: Optional[str] = None,
        continent: Optional[str] = None,
        max_cost_per_day: Optional[float] = None,
        limit: int = 50,
    ) -> List[Destination]:
        q = self.session.query(Destination)
        if query:
            like = f"%{query.strip()}%"
            q = q.filter(Destination.name.ilike(like))
        if country:
            q = q.filter(Destination.country.ilike(country.strip()))
        if continent:
            q = q.filter(Destination.continent.ilike(continent.strip()))
        if max_cost_per_day is not None:
            q = q.filter(Destination.avg_cost_per_day <= max_cost_per_day)
        return q.order_by(Destination.ai_score.desc().nullslast()) \
                .limit(limit).all()

    def by_name_and_country(
        self, name: str, country: str
    ) -> Optional[Destination]:
        return (
            self.session.query(Destination)
            .filter(
                Destination.name.ilike(name.strip()),
                Destination.country.ilike(country.strip()),
            )
            .one_or_none()
        )
