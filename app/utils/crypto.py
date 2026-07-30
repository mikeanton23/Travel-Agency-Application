# -*- coding: utf-8 -*-

"""
Symmetric encryption for secrets at rest (API keys in PostgreSQL).

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from
``APP_SECRET_KEY`` via SHA-256. Rotating ``APP_SECRET_KEY`` invalidates
stored keys — users re-enter them in Settings, which is the safe
failure mode.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret_key: str) -> None:
        if not secret_key or len(secret_key) < 16:
            raise ValueError(
                "APP_SECRET_KEY must be set (min 16 chars) to store "
                "encrypted API keys. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> Optional[str]:
        """Return the plaintext, or ``None`` if the token is invalid
        (wrong key after rotation, or corrupted data)."""
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None
