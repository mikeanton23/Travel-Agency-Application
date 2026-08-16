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
