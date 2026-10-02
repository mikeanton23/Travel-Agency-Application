# -*- coding: utf-8 -*-

"""
The office cash account.

Every receipt an agent takes - cash, card or IRIS transfer - is
recorded against one office account so the balance can be tracked
centrally, while still showing which agent took the money.

The ledger is append-only. A mistake is corrected by posting a
reversing movement that points at the original, never by editing or
deleting a row, so the balance can always be reconstructed and an
agent cannot quietly rewrite a receipt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from app.services.agency.pricing import money

logger = logging.getLogger(__name__)

PAYMENT_METHODS = ("cash", "card", "iris")
METHOD_LABELS = {
    "cash": "Cash",
    "card": "Credit / debit card",
    "iris": "Web banking transfer (IRIS)",
}

IN = "in"
OUT = "out"


class CashError(Exception):
    """A user-safe problem with a cash movement."""


class CashService:
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
    # Account
    # ------------------------------------------------------------------

    def ensure_account(self, agency_id: int,
                       currency: str = "EUR") -> int:
        """The office account, created on first use."""
        from app.db.models import CashAccount

        session = self._sessions()()
        try:
            account = (session.query(CashAccount)
                       .filter(CashAccount.agency_id == agency_id)
                       .order_by(CashAccount.id).first())
            if account is None:
                account = CashAccount(agency_id=agency_id,
                                      name="Office account",
                                      currency=currency.upper())
                session.add(account)
                session.commit()
            return account.id
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------

    def record(
        self,
        account_id: int,
        amount: Any,
        method: str,
        agent_id: Optional[int] = None,
        direction: str = IN,
        client_id: Optional[int] = None,
        quote_id: Optional[int] = None,
        reference: Optional[str] = None,
        description: Optional[str] = None,
        currency: str = "EUR",
    ) -> Dict[str, Any]:
        """Post a receipt or a payment out."""
        from app.db.models import CashMovement

        method = (method or "").strip().lower()
        if method not in PAYMENT_METHODS:
            raise CashError(
                f"Unknown payment method '{method}'. Use one of: "
                + ", ".join(PAYMENT_METHODS))
        if direction not in (IN, OUT):
            raise CashError("Direction must be 'in' or 'out'.")
        value = money(amount)
        if value <= 0:
            raise CashError("Amount must be greater than zero.")

        session = self._sessions()()
        try:
            movement = CashMovement(
                account_id=account_id, agent_id=agent_id,
                client_id=client_id, quote_id=quote_id,
                direction=direction, method=method,
                amount=float(value), currency=currency.upper(),
                reference=reference, description=description,
            )
            session.add(movement)
            session.commit()
            return self._as_dict(movement)
        finally:
            session.close()

    def reverse(self, movement_id: int, agent_id: Optional[int] = None,
                reason: str = "") -> Dict[str, Any]:
        """Correct a mistake by posting the opposite movement.

        The original row stays exactly as it was recorded.
        """
        from app.db.models import CashMovement

        session = self._sessions()()
        try:
            original = session.get(CashMovement, movement_id)
            if original is None:
                raise CashError("That movement does not exist.")
            already = (session.query(CashMovement)
                       .filter(CashMovement.reverses_id == movement_id)
                       .first())
            if already is not None:
                raise CashError("That movement is already reversed.")
            opposite = OUT if original.direction == IN else IN
            reversal = CashMovement(
                account_id=original.account_id,
                agent_id=agent_id or original.agent_id,
                client_id=original.client_id,
                quote_id=original.quote_id,
                direction=opposite,
                method=original.method,
                amount=original.amount,
                currency=original.currency,
                reference=original.reference,
                description=("Reversal of movement "
                             f"#{original.id}"
                             + (f": {reason}" if reason else "")),
                reverses_id=original.id,
            )
            session.add(reversal)
            session.commit()
            return self._as_dict(reversal)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def balance(self, account_id: int) -> Decimal:
        """Opening balance plus every movement, in order."""
        from app.db.models import CashAccount, CashMovement

        session = self._sessions()()
        try:
            account = session.get(CashAccount, account_id)
            total = money(account.opening_balance if account else 0)
            rows = (session.query(CashMovement)
                    .filter(CashMovement.account_id == account_id)
                    .all())
            for row in rows:
                amount = money(row.amount)
                total = total + amount if row.direction == IN \
                    else total - amount
            return total
        finally:
            session.close()

    def movements(
        self, account_id: int, limit: int = 200,
        agent_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        from app.db.models import CashMovement

        session = self._sessions()()
        try:
            query = (session.query(CashMovement)
                     .filter(CashMovement.account_id == account_id))
            if agent_id is not None:
                query = query.filter(CashMovement.agent_id == agent_id)
            rows = (query.order_by(CashMovement.id.desc())
                    .limit(limit).all())
            return [self._as_dict(row) for row in rows]
        finally:
            session.close()

    def totals_by_method(self, account_id: int) -> Dict[str, float]:
        """Useful for reconciling the till against card and IRIS."""
        from app.db.models import CashMovement

        session = self._sessions()()
        try:
            rows = (session.query(CashMovement)
                    .filter(CashMovement.account_id == account_id)
                    .all())
        finally:
            session.close()

        totals = {method: Decimal("0") for method in PAYMENT_METHODS}
        for row in rows:
            amount = money(row.amount)
            if row.direction == IN:
                totals[row.method] = totals.get(
                    row.method, Decimal("0")) + amount
            else:
                totals[row.method] = totals.get(
                    row.method, Decimal("0")) - amount
        return {k: float(v) for k, v in totals.items()}

    def totals_by_agent(self, account_id: int) -> List[Dict[str, Any]]:
        from app.db.models import CashMovement

        session = self._sessions()()
        try:
            rows = (session.query(CashMovement)
                    .filter(CashMovement.account_id == account_id)
                    .all())
        finally:
            session.close()

        totals: Dict[Optional[int], Decimal] = {}
        for row in rows:
            amount = money(row.amount)
            current = totals.get(row.agent_id, Decimal("0"))
            totals[row.agent_id] = (current + amount
                                    if row.direction == IN
                                    else current - amount)
        return [{"agent_id": agent, "total": float(value)}
                for agent, value in sorted(
                    totals.items(), key=lambda kv: -kv[1])]

    @staticmethod
    def _as_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": row.id,
            "account_id": row.account_id,
            "agent_id": row.agent_id,
            "client_id": row.client_id,
            "quote_id": row.quote_id,
            "direction": row.direction,
            "method": row.method,
            "method_label": METHOD_LABELS.get(row.method, row.method),
            "amount": row.amount,
            "currency": row.currency,
            "reference": row.reference,
            "description": row.description,
            "reverses_id": row.reverses_id,
            "created_at": (row.created_at.isoformat()
                           if row.created_at else None),
        }


cash_service = CashService()
