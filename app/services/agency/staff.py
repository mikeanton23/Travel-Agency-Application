# -*- coding: utf-8 -*-

"""
Who works here: listing office staff and changing their role.

Hiring and firing is the one administrative act that can lock the office
out of its own system, so every rule lives here rather than in the page:

* Only a manager or admin may see this list or change anything.
* Nobody may change their own role. Self-promotion is the obvious abuse;
  self-demotion is the more common accident, and it locks the only
  manager out of reports and staff administration at once.
* Only an admin may grant or revoke admin. A manager can run the office
  without being able to mint someone above themselves.
* The last manager or admin cannot be demoted. There is no recovery path
  from an office with nobody able to administer it except a database
  client, which is exactly what this page exists to avoid.

Changing a role takes effect immediately - ``current_agent`` re-reads it
from the database on every page load - so a demoted agent loses access
on their next click rather than at their next sign-in.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.access import (
    ADMIN,
    AGENT,
    CUSTOMER,
    MANAGER,
    STAFF_ROLES,
    is_staff,
    role_of,
    sees_whole_office,
)

logger = logging.getLogger(__name__)


class StaffError(Exception):
    """A refusal the page can show the user verbatim."""


#: Roles a manager may assign. Admin is deliberately absent.
ASSIGNABLE_BY_MANAGER = (CUSTOMER, AGENT, MANAGER)

#: Roles an admin may assign.
ASSIGNABLE_BY_ADMIN = (CUSTOMER, AGENT, MANAGER, ADMIN)

ROLE_LABELS: Dict[str, str] = {
    CUSTOMER: "Customer - public site only",
    AGENT: "Agent - own clients, quotes and bookings",
    MANAGER: "Manager - whole office, including reports",
    ADMIN: "Admin - manager plus system administration",
}


class StaffService:
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
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _require_manager(user: Any) -> None:
        if not sees_whole_office(user):
            raise StaffError(
                "Only the office manager can view or change staff roles.")

    def assignable_roles(self, user: Any) -> List[str]:
        """The roles this user is allowed to hand out."""
        if role_of(user) == ADMIN:
            return list(ASSIGNABLE_BY_ADMIN)
        if sees_whole_office(user):
            return list(ASSIGNABLE_BY_MANAGER)
        return []

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def list_people(self, user: Any, agency_id: int) -> List[Dict[str, Any]]:
        """Everyone in this office, plus unassigned new registrations.

        A brand-new signup has no ``agency_id`` until their first visit
        to the desk, so they would be invisible here exactly when you
        need to find them. They are listed as "not yet in the office".
        """
        self._require_manager(user)
        from app.db.models import User

        session = self._sessions()()
        try:
            rows = (session.query(User)
                    .filter((User.agency_id == agency_id)
                            | (User.agency_id.is_(None)))
                    .order_by(User.id)
                    .all())
            me = getattr(user, "id", None)
            out = []
            for row in rows:
                role = role_of(row)
                out.append({
                    "id": row.id,
                    "email": row.email,
                    "display_name": row.display_name or row.email,
                    "role": role,
                    "is_staff": role in STAFF_ROLES,
                    "is_admin": bool(row.is_admin),
                    "in_office": row.agency_id == agency_id,
                    "is_self": row.id == me,
                    "created_at": (row.created_at.isoformat()
                                   if row.created_at else None),
                    "last_login_at": (row.last_login_at.isoformat()
                                      if row.last_login_at else None),
                })
            return out
        finally:
            session.close()

    def count_administrators(self, agency_id: int) -> int:
        """How many people can still administer this office."""
        from app.db.models import User

        session = self._sessions()()
        try:
            return (session.query(User)
                    .filter(User.agency_id == agency_id,
                            User.role.in_((MANAGER, ADMIN)))
                    .count())
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def set_role(
        self, user: Any, agency_id: int, target_user_id: int, new_role: str
    ) -> Dict[str, Any]:
        """Change someone's role. Raises :class:`StaffError` on refusal."""
        self._require_manager(user)
        from app.db.models import User

        new_role = (new_role or "").strip().lower()
        if new_role not in self.assignable_roles(user):
            raise StaffError(
                f"You are not able to assign the role '{new_role}'.")

        if target_user_id == getattr(user, "id", None):
            raise StaffError(
                "You cannot change your own role. Ask another manager.")

        session = self._sessions()()
        try:
            row = session.get(User, target_user_id)
            if row is None:
                raise StaffError("That account no longer exists.")
            if row.agency_id not in (None, agency_id):
                raise StaffError("That account belongs to another office.")

            old_role = role_of(row)
            if old_role == new_role:
                return {"id": row.id, "email": row.email,
                        "role": old_role, "changed": False}

            if old_role == ADMIN and role_of(user) != ADMIN:
                raise StaffError(
                    "Only an admin can change another admin's role.")

            # Lockout guard: never remove the last person who can
            # administer the office.
            if old_role in (MANAGER, ADMIN) and new_role not in (MANAGER, ADMIN):
                remaining = (session.query(User)
                             .filter(User.agency_id == agency_id,
                                     User.role.in_((MANAGER, ADMIN)),
                                     User.id != row.id)
                             .count())
                if remaining == 0:
                    raise StaffError(
                        "This is the office's only manager. Promote "
                        "someone else first, or nobody will be able to "
                        "administer the office.")

            row.role = new_role
            # Joining the office: give them the agency so they do not
            # land on an empty desk.
            if new_role in STAFF_ROLES and row.agency_id is None:
                row.agency_id = agency_id
            # Leaving it: keep the agency link so their past quotes and
            # bookings still resolve to a name.
            if new_role == ADMIN:
                row.is_admin = True
            elif old_role == ADMIN:
                row.is_admin = False

            session.commit()
            logger.info("role change: user %s %s -> %s by user %s",
                        row.id, old_role, new_role, getattr(user, "id", None))
            return {"id": row.id, "email": row.email,
                    "role": new_role, "changed": True}
        except StaffError:
            session.rollback()
            raise
        except Exception as exc:
            session.rollback()
            logger.exception("role change failed")
            raise StaffError(
                f"Could not save the change ({type(exc).__name__}).") from exc
        finally:
            session.close()


staff_service = StaffService()

__all__ = [
    "ASSIGNABLE_BY_ADMIN",
    "ASSIGNABLE_BY_MANAGER",
    "ROLE_LABELS",
    "StaffError",
    "StaffService",
    "staff_service",
]
