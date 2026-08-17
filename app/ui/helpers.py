# -*- coding: utf-8 -*-

"""Shared UI helpers with no page dependencies.

Kept separate so pages can import it without creating a cycle:
pages_v2 imports pages_hotels to register its routes, so pages_hotels
must not import pages_v2.
"""

from __future__ import annotations


def client_gone(exc: Exception) -> bool:
    """Whether an exception means the browser simply went away.

    Background work (image loads, scores, a slow search) can finish
    after the user navigates away or a sleeping instance drops the
    connection. That is not an error worth raising, and certainly not
    one worth a traceback in the logs.
    """
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return ("client" in message and
            ("deleted" in message or "disconnected" in message
             or "no longer" in message))


def element_alive(element) -> bool:
    """Whether a UI element can still be safely updated.

    Newer NiceGUI does not raise when you touch a deleted element - it
    logs "An element has been deleted but is still being used" and
    carries on. Catching exceptions therefore misses it, so background
    work must ask before acting rather than apologise afterwards.
    """
    if element is None:
        return False
    try:
        client = element.client
    except RuntimeError:
        return False          # the whole page is gone
    except Exception:
        return False
    try:
        if getattr(client, "has_socket_connection", True) is False:
            return False
        elements = getattr(client, "elements", None)
        if elements is not None and element.id not in elements:
            return False
    except Exception:
        return False
    return True


def safe_clear(element) -> bool:
    """Clear a container only if it is still attached. Returns whether
    the caller should carry on and rebuild its contents."""
    if not element_alive(element):
        return False
    try:
        element.clear()
    except Exception as exc:
        return not client_gone(exc) and False
    return True


def name_tokens(value: str) -> set:
    """Comparable words from a place or property name.

    Chain names repeat filler ("hotel", "inn", "by", "the"), so those
    are dropped: matching on them would make every Hampton Inn look
    like every other one.
    """
    import re

    filler = {
        "hotel", "hotels", "inn", "suites", "suite", "resort", "the",
        "by", "and", "at", "of", "a", "an", "spa", "motel", "lodge",
        "house", "collection", "group", "hostel", "apartments",
        "apartment", "guesthouse", "residence", "plaza", "center",
        "centre",
    }
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    return {w for w in words if w not in filler and len(w) > 1}


def name_relevance(query: str, candidate: str) -> float:
    """How well a candidate name answers a query, from 0 to 1.

    Used to decide whether the user typed a property name rather than
    a city, and to surface that property first if so.
    """
    wanted = name_tokens(query)
    if not wanted:
        return 0.0
    found = name_tokens(candidate)
    if not found:
        return 0.0
    overlap = wanted & found
    return len(overlap) / len(wanted)


def looks_like_property_name(query: str) -> bool:
    """Whether a search term reads like a specific property.

    Two or more meaningful words plus a chain or property keyword is a
    strong hint the user wants one hotel, not a whole city.
    """
    import re

    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    if len(words) < 3:
        return False
    markers = {
        "hotel", "inn", "suites", "resort", "motel", "lodge", "hostel",
        "apartments", "guesthouse", "residence", "spa", "villa",
    }
    return bool(set(words) & markers)
