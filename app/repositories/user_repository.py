# -*- coding: utf-8 -*-

"""User-domain data access: favorites, trips, notifications, and the
admin user list — repository pattern per Phase 1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.db.models import (
    Destination, Favorite, Notification, Trip, TripItem, User,
)
from app.repositories.base import BaseRepository


class FavoriteRepository(BaseRepository[Favorite]):
    model = Favorite

    def toggle(self, user_id: int, destination_id: int) -> bool:
        """Add/remove; returns True if now favorited."""
        existing = (
            self.session.query(Favorite)
            .filter_by(user_id=user_id, destination_id=destination_id)
            .one_or_none()
        )
        if existing is not None:
            self.session.delete(existing)
            self.session.flush()
            return False
        self.session.add(Favorite(user_id=user_id,
                                  destination_id=destination_id))
        self.session.flush()
        return True

    def is_favorite(self, user_id: int, destination_id: int) -> bool:
        return (
            self.session.query(Favorite)
            .filter_by(user_id=user_id, destination_id=destination_id)
            .count() > 0
        )

    def destinations_for(self, user_id: int) -> List[Destination]:
        return (
            self.session.query(Destination)
            .join(Favorite, Favorite.destination_id == Destination.id)
            .filter(Favorite.user_id == user_id)
            .order_by(Favorite.created_at.desc())
            .all()
        )


class TripRepository(BaseRepository[Trip]):
    model = Trip

    def for_user(self, user_id: int) -> List[Trip]:
        return (
            self.session.query(Trip)
            .filter(Trip.user_id == user_id)
            .order_by(Trip.created_at.desc())
            .all()
        )

    def create(
        self, user_id: int, title: str,
        destination_id: Optional[int] = None,
        currency: str = "EUR",
    ) -> Trip:
        trip = Trip(user_id=user_id, title=title.strip(),
                    destination_id=destination_id, currency=currency)
        self.session.add(trip)
        self.session.flush()
        return trip

    def add_item(
        self, trip_id: int, kind: str, title: str,
        reference: Optional[dict] = None,
        price_total: Optional[float] = None,
        currency: Optional[str] = None,
    ) -> TripItem:
        position = (
            self.session.query(TripItem)
            .filter(TripItem.trip_id == trip_id).count()
        )
        item = TripItem(
            trip_id=trip_id, position=position, kind=kind,
            title=title.strip(), reference=reference,
            price_total=price_total, currency=currency,
        )
        self.session.add(item)
        self.session.flush()
        return item


class NotificationRepository(BaseRepository[Notification]):
    model = Notification

    def notify(self, user_id: int, title: str, body: str = "",
               kind: str = "info") -> Notification:
        note = Notification(user_id=user_id, title=title,
                            body=body or None, kind=kind)
        self.session.add(note)
        self.session.flush()
        return note

    def unread_count(self, user_id: int) -> int:
        return (
            self.session.query(Notification)
            .filter(Notification.user_id == user_id,
                    Notification.read_at.is_(None))
            .count()
        )

    def for_user(self, user_id: int, limit: int = 50
                 ) -> List[Notification]:
        return (
            self.session.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit).all()
        )

    def mark_read(self, user_id: int, notification_id: int) -> bool:
        note = (
            self.session.query(Notification)
            .filter_by(id=notification_id, user_id=user_id)
            .one_or_none()
        )
        if note is None:
            return False
        note.read_at = datetime.now(timezone.utc)
        self.session.flush()
        return True


class UserAdminRepository(BaseRepository[User]):
    model = User

    def all_users(self) -> List[User]:
        return self.session.query(User).order_by(User.id).all()

    def set_active(self, user_id: int, active: bool) -> bool:
        user = self.session.get(User, user_id)
        if user is None:
            return False
        user.is_active = active
        self.session.flush()
        return True

    def set_admin(self, user_id: int, admin: bool) -> bool:
        user = self.session.get(User, user_id)
        if user is None:
            return False
        user.is_admin = admin
        self.session.flush()
        return True
