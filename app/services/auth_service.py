# -*- coding: utf-8 -*-

"""
Authentication: registration and login backed by the Phase 1 ``users``
table.

Password hashing uses stdlib ``hashlib.scrypt`` (N=2^14, r=8, p=1) with
a per-user random salt, stored as
``scrypt$N$r$p$<salt_hex>$<hash_hex>`` — no external dependency, and
verification is constant-time. Login attempts are rate-limited.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from app.utils.rate_limit import login_limiter

logger = logging.getLogger(__name__)

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
HASH_BYTES = 32

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LOGIN_LIMIT = 5
LOGIN_WINDOW_S = 300.0


class AuthError(Exception):
    """User-safe authentication failure message."""


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=HASH_BYTES,
    )
    return (f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}$"
            f"{salt.hex()}${digest.hex()}")


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
            dklen=len(bytes.fromhex(hash_hex)),
        )
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


@dataclass
class AuthenticatedUser:
    id: int
    email: str
    display_name: Optional[str]
    is_admin: bool


class AuthService:
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

    def register(
        self, email: str, password: str,
        display_name: Optional[str] = None,
    ) -> AuthenticatedUser:
        from app.db.models import User

        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError("Please enter a valid email address.")
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        session = self._sessions()()
        try:
            exists = (
                session.query(User).filter(User.email == email)
                .one_or_none()
            )
            if exists is not None:
                raise AuthError("An account with this email exists.")
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name=(display_name or "").strip() or None,
            )
            session.add(user)
            session.commit()
            return AuthenticatedUser(
                id=user.id, email=user.email,
                display_name=user.display_name, is_admin=user.is_admin,
            )
        finally:
            session.close()

    def authenticate(
        self, email: str, password: str,
        client_key: str = "unknown",
    ) -> AuthenticatedUser:
        """Rate-limited login. Same error for wrong email vs wrong
        password (no account enumeration)."""
        from app.db.models import User

        allowed, retry_after = login_limiter.allow(
            f"login:{client_key}", LOGIN_LIMIT, LOGIN_WINDOW_S
        )
        if not allowed:
            raise AuthError(
                f"Too many attempts — try again in {retry_after:.0f}s."
            )

        email = email.strip().lower()
        session = self._sessions()()
        try:
            user = (
                session.query(User).filter(User.email == email)
                .one_or_none()
            )
            if user is None or not verify_password(
                password, user.password_hash
            ):
                raise AuthError("Invalid email or password.")
            if not user.is_active:
                raise AuthError("This account is disabled.")
            user.last_login_at = datetime.now(timezone.utc)
            session.commit()
            return AuthenticatedUser(
                id=user.id, email=user.email,
                display_name=user.display_name, is_admin=user.is_admin,
            )
        finally:
            session.close()

    def change_password(
        self, user_id: int, current: str, new: str
    ) -> None:
        from app.db.models import User

        if len(new) < 8:
            raise AuthError("Password must be at least 8 characters.")
        session = self._sessions()()
        try:
            user = session.get(User, user_id)
            if user is None or not verify_password(
                current, user.password_hash
            ):
                raise AuthError("Current password is incorrect.")
            user.password_hash = hash_password(new)
            session.commit()
        finally:
            session.close()


auth_service = AuthService()
