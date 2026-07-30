# -*- coding: utf-8 -*-

"""
Repository pattern base class.

Data access goes through repositories so services never build queries
inline; sessions are injected (dependency injection) which makes every
repository testable against in-memory SQLite.
"""

from __future__ import annotations

from typing import Generic, List, Optional, Type, TypeVar

from sqlalchemy.orm import Session

T = TypeVar("T")


class BaseRepository(Generic[T]):
    model: Type[T]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: int) -> Optional[T]:
        return self.session.get(self.model, entity_id)

    def list(self, limit: int = 100, offset: int = 0) -> List[T]:
        return (
            self.session.query(self.model)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def add(self, entity: T) -> T:
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        self.session.delete(entity)
        self.session.flush()

    def count(self) -> int:
        return self.session.query(self.model).count()
