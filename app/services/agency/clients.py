# -*- coding: utf-8 -*-

"""
Client book.

Each agent owns their own clients; managers and admins see the whole
office. Ownership is enforced through
:mod:`app.services.agency.access` so one rule governs every query.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.access import (
    may_edit_client, may_reassign_client, may_view_client,
    sees_whole_office,
)

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ClientError(Exception):
    """A user-safe problem with a client record."""


class ClientService:
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

    def create(self, agency_id: int, agent_id: int,
               full_name: str, **fields: Any) -> Dict[str, Any]:
        from app.db.models import Client

        name = (full_name or "").strip()
        if len(name) < 2:
            raise ClientError("A client needs a name.")
        email = (fields.get("email") or "").strip().lower()
        if email and not EMAIL_RE.match(email):
            raise ClientError("That email address is not valid.")

        session = self._sessions()()
        try:
            client = Client(
                agency_id=agency_id, owner_agent_id=agent_id,
                full_name=name[:200],
                company_name=fields.get("company_name"),
                email=email or None,
                phone=fields.get("phone"),
                vat_number=fields.get("vat_number"),
                tax_office=fields.get("tax_office"),
                address=fields.get("address"),
                passport_number=fields.get("passport_number"),
                passport_expiry=fields.get("passport_expiry"),
                date_of_birth=fields.get("date_of_birth"),
                nationality=fields.get("nationality"),
                notes=fields.get("notes"),
                consent_marketing=bool(
                    fields.get("consent_marketing", False)),
            )
            session.add(client)
            session.commit()
            return self._as_dict(client)
        finally:
            session.close()

    def get(self, user: Any, client_id: int) -> Optional[Dict[str, Any]]:
        """Returns None when the client is not this agent's to see."""
        from app.db.models import Client

        session = self._sessions()()
        try:
            client = session.get(Client, client_id)
            if client is None or not may_view_client(user, client):
                return None
            return self._as_dict(client)
        finally:
            session.close()

    def search(self, user: Any, agency_id: int, term: str = "",
               limit: int = 100) -> List[Dict[str, Any]]:
        from app.db.models import Client

        session = self._sessions()()
        try:
            query = (session.query(Client)
                     .filter(Client.agency_id == agency_id))
            if not sees_whole_office(user):
                query = query.filter(
                    Client.owner_agent_id == getattr(user, "id", None))
            term = (term or "").strip()
            if term:
                like = f"%{term}%"
                query = query.filter(
                    Client.full_name.ilike(like)
                    | Client.email.ilike(like)
                    | Client.phone.ilike(like)
                    | Client.company_name.ilike(like))
            rows = (query.order_by(Client.full_name).limit(limit).all())
            return [self._as_dict(row) for row in rows]
        finally:
            session.close()

    def update(self, user: Any, client_id: int,
               **fields: Any) -> bool:
        from app.db.models import Client

        editable = {
            "full_name", "company_name", "email", "phone",
            "vat_number", "tax_office", "address", "passport_number",
            "passport_expiry", "date_of_birth", "nationality",
            "notes", "consent_marketing",
        }
        session = self._sessions()()
        try:
            client = session.get(Client, client_id)
            if client is None or not may_edit_client(user, client):
                return False
            for key, value in fields.items():
                if key in editable:
                    setattr(client, key, value)
            session.commit()
            return True
        finally:
            session.close()

    def reassign(self, user: Any, client_id: int,
                 new_agent_id: int) -> bool:
        """Moving a client between agents is a management action."""
        from app.db.models import Client

        if not may_reassign_client(user):
            raise ClientError(
                "Only a manager can move a client to another agent.")
        session = self._sessions()()
        try:
            client = session.get(Client, client_id)
            if client is None:
                return False
            client.owner_agent_id = new_agent_id
            session.commit()
            return True
        finally:
            session.close()

    def add_note(self, user: Any, client_id: int, body: str) -> bool:
        from app.db.models import Client, ClientNote

        if not (body or "").strip():
            return False
        session = self._sessions()()
        try:
            client = session.get(Client, client_id)
            if client is None or not may_view_client(user, client):
                return False
            session.add(ClientNote(client_id=client_id,
                                   author_id=getattr(user, "id", None),
                                   body=body.strip()))
            session.commit()
            return True
        finally:
            session.close()

    def notes(self, user: Any, client_id: int,
              limit: int = 50) -> List[Dict[str, Any]]:
        from app.db.models import Client, ClientNote

        session = self._sessions()()
        try:
            client = session.get(Client, client_id)
            if client is None or not may_view_client(user, client):
                return []
            rows = (session.query(ClientNote)
                    .filter(ClientNote.client_id == client_id)
                    .order_by(ClientNote.id.desc()).limit(limit).all())
            return [{"id": r.id, "body": r.body,
                     "author_id": r.author_id,
                     "created_at": (r.created_at.isoformat()
                                    if r.created_at else None)}
                    for r in rows]
        finally:
            session.close()

    @staticmethod
    def _as_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": row.id, "agency_id": row.agency_id,
            "owner_agent_id": row.owner_agent_id,
            "full_name": row.full_name,
            "company_name": row.company_name,
            "email": row.email, "phone": row.phone,
            "vat_number": row.vat_number,
            "tax_office": row.tax_office,
            "address": row.address,
            "passport_number": row.passport_number,
            "passport_expiry": row.passport_expiry,
            "date_of_birth": row.date_of_birth,
            "nationality": row.nationality,
            "notes": row.notes,
            "consent_marketing": row.consent_marketing,
            "created_at": (row.created_at.isoformat()
                           if row.created_at else None),
        }


client_service = ClientService()
