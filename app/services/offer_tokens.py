# -*- coding: utf-8 -*-

"""
Secure customer offer links.

A token is a 256-bit URL-safe random string shown to the customer
exactly once (in their email). Only its SHA-256 hash is stored, so a
database leak cannot be replayed into valid offer links.

Tokens are unguessable, expirable, revocable and single-purpose:
they resolve to one CustomerOffer and nothing else. Database IDs never
appear in customer URLs.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

TOKEN_BYTES = 32


def generate_token() -> Tuple[str, str]:
    """Return ``(plaintext_token, token_hash)``."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), stored_hash)


class OfferTokenService:
    def __init__(
        self, session_factory: Optional[Callable[[], Any]] = None
    ) -> None:
        self._session_factory = session_factory

    def _sessions(self) -> Callable[[], Any]:
        if self._session_factory is None:
            from app.db.database import SessionLocal
            self._session_factory = SessionLocal
        return self._session_factory

    def resolve(self, token: str) -> Tuple[Optional[Any], str]:
        """Look up an offer by token.

        Returns ``(offer_or_None, reason)`` where reason is one of
        ``ok``, ``not_found``, ``revoked``, ``expired``. The same
        generic handling should be shown to the customer for
        not_found/revoked so links can't be probed.
        """
        from app.db.models import CustomerOffer

        if not token or len(token) < 20:
            return None, "not_found"
        digest = hash_token(token)
        session = self._sessions()()
        try:
            offer = (
                session.query(CustomerOffer)
                .filter(CustomerOffer.token_hash == digest)
                .one_or_none()
            )
            if offer is None:
                return None, "not_found"
            if offer.revoked_at is not None:
                return None, "revoked"
            expires = offer.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                return None, "expired"
            session.expunge(offer)
            return offer, "ok"
        finally:
            session.close()

    def mark_opened(self, token: str) -> None:
        from app.db.models import CustomerOffer, OfferEvent

        digest = hash_token(token)
        session = self._sessions()()
        try:
            offer = (
                session.query(CustomerOffer)
                .filter(CustomerOffer.token_hash == digest)
                .one_or_none()
            )
            if offer is None:
                return
            if offer.opened_at is None:
                offer.opened_at = datetime.now(timezone.utc)
                if offer.status == "sent":
                    offer.status = "opened"
            session.add(OfferEvent(offer_id=offer.id,
                                   request_id=offer.request_id,
                                   event="offer_page_opened"))
            session.commit()
        finally:
            session.close()

    def revoke(self, offer_id: int) -> bool:
        from app.db.models import CustomerOffer

        session = self._sessions()()
        try:
            offer = session.get(CustomerOffer, offer_id)
            if offer is None:
                return False
            offer.revoked_at = datetime.now(timezone.utc)
            offer.status = "cancelled"
            session.commit()
            return True
        finally:
            session.close()


offer_token_service = OfferTokenService()
