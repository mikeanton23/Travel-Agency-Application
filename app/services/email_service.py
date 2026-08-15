# -*- coding: utf-8 -*-

"""
Transactional email with pluggable transports.

Transports: ``smtp`` (stdlib, STARTTLS/SSL) and ``console`` (dev -- logs
instead of sending). Resend/SendGrid/SES can be added behind the same
``EmailTransport`` interface without touching callers.

Every attempt is written to ``email_log`` so a lead is never silently
lost. Credentials come from settings only -- never hardcoded, never
logged.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Callable, Dict, Optional

from app.utils.settings import get_settings

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value: str) -> bool:
    return bool(value and EMAIL_RE.match(value.strip()))


@dataclass
class EmailMessageData:
    to_email: str
    subject: str
    text_body: str
    html_body: Optional[str] = None
    kind: str = "generic"
    request_id: Optional[int] = None
    offer_id: Optional[int] = None


class EmailTransport(ABC):
    name = "base"

    @abstractmethod
    def send(self, message: EmailMessageData,
             from_email: str, from_name: str) -> None:
        """Send or raise."""


class ConsoleTransport(EmailTransport):
    """Development transport: logs subject and recipient only."""

    name = "console"

    def send(self, message, from_email, from_name) -> None:
        logger.info("[email:console] to=%s subject=%s kind=%s",
                    message.to_email, message.subject, message.kind)


class SmtpTransport(EmailTransport):
    name = "smtp"

    def __init__(self, host: str, port: int, username: str,
                 password: str, use_tls: bool = True) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def send(self, message, from_email, from_name) -> None:
        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = f"{from_name} <{from_email}>" if from_name \
            else from_email
        msg["To"] = message.to_email
        msg.set_content(message.text_body)
        if message.html_body:
            msg.add_alternative(message.html_body, subtype="html")

        if self.port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self.host, self.port,
                                  context=context, timeout=20) as server:
                if self.username:
                    server.login(self.username, self.password)
                server.send_message(msg)
            return
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            if self.use_tls:
                server.starttls(context=ssl.create_default_context())
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg)


class EmailService:
    def __init__(
        self,
        transport: Optional[EmailTransport] = None,
        session_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._transport = transport
        self._session_factory = session_factory

    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        s = get_settings()
        return bool(s.smtp_host and s.smtp_from_email)

    def transport(self) -> EmailTransport:
        if self._transport is not None:
            return self._transport
        s = get_settings()
        if s.smtp_host:
            return SmtpTransport(
                host=s.smtp_host, port=s.smtp_port,
                username=s.smtp_username, password=s.smtp_password,
                use_tls=s.smtp_use_tls,
            )
        return ConsoleTransport()

    def _sessions(self) -> Optional[Callable[[], Any]]:
        if self._session_factory is None:
            try:
                from app.db.database import SessionLocal
                self._session_factory = SessionLocal
            except Exception:  # pragma: no cover - defensive
                return None
        return self._session_factory

    # ------------------------------------------------------------------

    def send(self, message: EmailMessageData) -> Dict[str, Any]:
        """Send and log. Returns ``{"success": bool, "error": str|None}``
        -- callers should surface failure, never pretend delivery."""
        if not valid_email(message.to_email):
            return self._log(message, "invalid",
                             False, "invalid recipient address")
        s = get_settings()
        transport = self.transport()
        try:
            transport.send(message, s.smtp_from_email or "noreply@localhost",
                           s.smtp_from_name or "Aevyra")
        except Exception as exc:
            # Never log credentials or full message bodies.
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.warning("Email send failed (kind=%s): %s",
                           message.kind, error)
            return self._log(message, transport.name, False, error)
        return self._log(message, transport.name, True, None)

    def _log(self, message: EmailMessageData, provider: str,
             success: bool, error: Optional[str]) -> Dict[str, Any]:
        factory = self._sessions()
        if factory is not None:
            try:
                from app.db.models import EmailLog
                session = factory()
                try:
                    session.add(EmailLog(
                        to_email=message.to_email,
                        subject=message.subject[:300],
                        kind=message.kind,
                        request_id=message.request_id,
                        offer_id=message.offer_id,
                        provider=provider,
                        success=success,
                        error=error,
                    ))
                    session.commit()
                finally:
                    session.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("email_log write skipped: %s", exc)
        return {"success": success, "error": error, "provider": provider}


email_service = EmailService()
