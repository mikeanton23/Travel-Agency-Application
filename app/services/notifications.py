# -*- coding: utf-8 -*-

"""
In-app notifications.

A notification is the desk-side half of every message the system sends:
when a customer asks us to beat a price, the agent gets an email *and* a
row here. Email can be delayed, filtered or ignored; the bell in the
header cannot. Neither is trusted alone.

Writes are best-effort by design. A failure to record a notification
must never lose the lead that caused it, so :meth:`notify_staff` logs
and returns 0 rather than raising into the caller's transaction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import or_

logger = logging.getLogger(__name__)

#: Roles that belong to the office rather than the public site.
STAFF_ROLES: Sequence[str] = ("agent", "manager", "admin")

#: Notification kinds, used for the icon and colour in the bell menu.
KIND_ICONS: Dict[str, str] = {
    "offer_request": "sym_r_local_offer",
    "offer_sent": "sym_r_outgoing_mail",
    "booking": "sym_r_confirmation_number",
    "payment": "sym_r_payments",
    "warning": "sym_r_warning",
    "info": "sym_r_info",
}


class NotificationService:
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
    # Writing
    # ------------------------------------------------------------------

    def create(
        self,
        user_id: int,
        title: str,
        body: Optional[str] = None,
        kind: str = "info",
        link: Optional[str] = None,
    ) -> Optional[int]:
        """Record one notification. Returns its id, or None on failure."""
        ids = self.broadcast([user_id], title, body, kind, link)
        return ids[0] if ids else None

    def broadcast(
        self,
        user_ids: Iterable[int],
        title: str,
        body: Optional[str] = None,
        kind: str = "info",
        link: Optional[str] = None,
    ) -> List[int]:
        """Record the same notification for several people, in one commit."""
        from app.db.models import Notification

        targets = [int(u) for u in dict.fromkeys(user_ids) if u]
        if not targets:
            return []

        session = self._sessions()()
        try:
            rows = [
                Notification(
                    user_id=uid,
                    kind=kind[:30],
                    title=title[:250],
                    body=body,
                    link=(link[:250] if link else None),
                )
                for uid in targets
            ]
            session.add_all(rows)
            session.commit()
            return [r.id for r in rows]
        except Exception as exc:
            session.rollback()
            # Never let a bell failure cost us the lead that triggered it.
            logger.warning("notification write failed (kind=%s): %s",
                           kind, exc)
            return []
        finally:
            session.close()

    def notify_staff(
        self,
        title: str,
        body: Optional[str] = None,
        kind: str = "info",
        link: Optional[str] = None,
        agency_id: Optional[int] = None,
    ) -> int:
        """Notify everyone who works the desk. Returns how many were told."""
        ids = self.broadcast(self.staff_user_ids(agency_id),
                             title, body, kind, link)
        if not ids:
            logger.warning(
                "no staff notified for %r - is any user marked as staff?",
                title)
        return len(ids)

    # ------------------------------------------------------------------
    # Who counts as staff
    # ------------------------------------------------------------------

    def staff_user_ids(self, agency_id: Optional[int] = None) -> List[int]:
        """Users who should see desk notifications.

        Defined as an explicit staff role, or the admin flag. This is the
        one place to change if the office later separates counter staff
        from registered customers - every caller goes through here.

        Note: if ``users.role`` defaults to a staff value for ordinary
        customers, this returns far too many people. Check with::

            SELECT role, is_admin, count(*) FROM users GROUP BY 1, 2;
        """
        from app.db.models import User

        session = self._sessions()()
        try:
            query = session.query(User.id).filter(
                or_(User.is_admin.is_(True),
                    User.role.in_(tuple(STAFF_ROLES)))
            )
            if agency_id is not None and hasattr(User, "agency_id"):
                query = query.filter(User.agency_id == agency_id)
            return [row[0] for row in query.all()]
        except Exception as exc:
            logger.warning("could not resolve staff users: %s", exc)
            return []
        finally:
            session.close()

    def user_id_for_email(self, email: str) -> Optional[int]:
        """The account id behind an email address, if one exists.

        Used to give a customer who already has a login the same
        notification the email carries.
        """
        from app.db.models import User

        if not email:
            return None
        session = self._sessions()()
        try:
            row = (session.query(User.id)
                   .filter(User.email == email.strip().lower())
                   .first())
            return row[0] if row else None
        except Exception as exc:
            logger.debug("user lookup by email failed: %s", exc)
            return None
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def unread_count(self, user_id: int) -> int:
        from app.db.models import Notification

        if not user_id:
            return 0
        session = self._sessions()()
        try:
            return (session.query(Notification)
                    .filter(Notification.user_id == user_id,
                            Notification.read_at.is_(None))
                    .count())
        except Exception as exc:
            logger.debug("unread count failed: %s", exc)
            return 0
        finally:
            session.close()

    def list_for(
        self, user_id: int, limit: int = 20, unread_only: bool = False
    ) -> List[Dict[str, Any]]:
        from app.db.models import Notification

        if not user_id:
            return []
        session = self._sessions()()
        try:
            query = (session.query(Notification)
                     .filter(Notification.user_id == user_id))
            if unread_only:
                query = query.filter(Notification.read_at.is_(None))
            rows = (query.order_by(Notification.id.desc())
                    .limit(limit).all())
            return [{
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "body": r.body,
                "link": getattr(r, "link", None),
                "read": r.read_at is not None,
                "created_at": (r.created_at.isoformat()
                               if r.created_at else None),
            } for r in rows]
        except Exception as exc:
            logger.warning("notification list failed: %s", exc)
            return []
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Marking
    # ------------------------------------------------------------------

    def mark_read(self, notification_id: int, user_id: int) -> bool:
        """Mark one as read. Scoped by user so an id cannot be guessed."""
        from app.db.models import Notification

        session = self._sessions()()
        try:
            row = (session.query(Notification)
                   .filter(Notification.id == notification_id,
                           Notification.user_id == user_id)
                   .first())
            if row is None:
                return False
            if row.read_at is None:
                row.read_at = datetime.now(timezone.utc)
                session.commit()
            return True
        except Exception as exc:
            session.rollback()
            logger.warning("mark_read failed: %s", exc)
            return False
        finally:
            session.close()

    def mark_all_read(self, user_id: int) -> int:
        from app.db.models import Notification

        session = self._sessions()()
        try:
            count = (session.query(Notification)
                     .filter(Notification.user_id == user_id,
                             Notification.read_at.is_(None))
                     .update({"read_at": datetime.now(timezone.utc)},
                             synchronize_session=False))
            session.commit()
            return int(count or 0)
        except Exception as exc:
            session.rollback()
            logger.warning("mark_all_read failed: %s", exc)
            return 0
        finally:
            session.close()


notification_service = NotificationService()

__all__ = [
    "KIND_ICONS",
    "STAFF_ROLES",
    "NotificationService",
    "notification_service",
]
