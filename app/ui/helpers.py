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
