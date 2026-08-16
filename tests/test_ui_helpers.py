# -*- coding: utf-8 -*-

from app.ui.helpers import client_gone


def test_disconnect_is_recognised():
    assert client_gone(
        RuntimeError("The client this element belongs to has been "
                     "deleted."))
    assert client_gone(RuntimeError("Client has disconnected"))


def test_real_errors_are_not_swallowed():
    """A genuine bug must still surface; only disconnects are quiet."""
    assert not client_gone(RuntimeError("database is locked"))
    assert not client_gone(ValueError("bad value"))
    assert not client_gone(KeyError("missing"))
    assert not client_gone(
        RuntimeError("client_id must be provided"))
