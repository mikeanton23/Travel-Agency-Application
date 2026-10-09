# -*- coding: utf-8 -*-

"""
Who may see and change what.

Each agent keeps their own client book: another agent cannot read it.
Managers and admins see the whole office. These checks are centralised
so the rule is defined once and every query and page uses the same
definition.

Two rules this module exists to enforce, both of which failed open
before:

* A registered customer is not staff. ``users.role`` defaults to
  ``customer``; anything unrecognised is treated as a customer too, so
  a typo or a new role added elsewhere locks someone out rather than
  letting them in.
* Being signed in is not a permission. Every agency page goes through
  :func:`is_staff`, and every scoped query that cannot be scoped
  returns nothing rather than everything.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import false as _sql_false

CUSTOMER = "customer"
AGENT = "agent"
MANAGER = "manager"
ADMIN = "admin"

#: Every role the application understands.
ROLES = (CUSTOMER, AGENT, MANAGER, ADMIN)

#: The roles that belong to the office. Everything else is the public.
STAFF_ROLES = (AGENT, MANAGER, ADMIN)


def role_of(user: Any) -> str:
    """The effective role, tolerating older rows with only is_admin.

    Unknown, missing or empty roles resolve to :data:`CUSTOMER`. This
    is deliberate: the previous default was ``agent``, which meant a
    row with no role - or anybody at all, since the column defaulted to
    ``agent`` - was treated as office staff.
    """
    if user is None:
        return CUSTOMER
    role = (getattr(user, "role", None) or "").strip().lower()
    if role in ROLES:
        return role
    return ADMIN if getattr(user, "is_admin", False) else CUSTOMER


def is_staff(user: Any) -> bool:
    """True for anyone who works the desk.

    The single gate for the agency back office. Signing in is not
    enough; the public site and the office share one user table.
    """
    return role_of(user) in STAFF_ROLES


def sees_whole_office(user: Any) -> bool:
    return role_of(user) in (MANAGER, ADMIN)


def may_view_client(user: Any, client: Any) -> bool:
    """An agent sees only their own clients; managers see all."""
    if user is None or client is None or not is_staff(user):
        return False
    if sees_whole_office(user):
        return True
    return getattr(client, "owner_agent_id", None) == getattr(
        user, "id", None)


def may_edit_client(user: Any, client: Any) -> bool:
    # Same rule as viewing: whoever owns the relationship edits it.
    return may_view_client(user, client)


def may_reassign_client(user: Any) -> bool:
    """Moving a client between agents is a management action."""
    return sees_whole_office(user)


def may_view_quote(user: Any, quote: Any) -> bool:
    if user is None or quote is None or not is_staff(user):
        return False
    if sees_whole_office(user):
        return True
    return getattr(quote, "agent_id", None) == getattr(user, "id", None)


def may_edit_quote(user: Any, quote: Any) -> bool:
    """A sent or accepted quote is a record, not a draft.

    Agents may keep editing their own drafts; changing anything later
    is a management action so the trail stays honest.
    """
    if not may_view_quote(user, quote):
        return False
    status = (getattr(quote, "status", "") or "").lower()
    if status in ("draft", "pending"):
        return True
    return sees_whole_office(user)


def may_view_office_cash(user: Any) -> bool:
    """Every agent pays into the office account, so every agent may
    see their own movements; only managers see the office balance."""
    return sees_whole_office(user)


def visible_client_filter(user: Any, query, client_model):
    """Apply the ownership rule to a SQLAlchemy query.

    A non-staff caller gets a query that matches nothing. Returning the
    unfiltered query here would hand the whole client book - passport
    numbers included - to anyone who reached the call.
    """
    if not is_staff(user):
        return query.filter(_sql_false())
    if sees_whole_office(user):
        return query
    return query.filter(
        client_model.owner_agent_id == getattr(user, "id", None))


def visible_quote_filter(user: Any, query, quote_model):
    if not is_staff(user):
        return query.filter(_sql_false())
    if sees_whole_office(user):
        return query
    return query.filter(
        quote_model.agent_id == getattr(user, "id", None))
