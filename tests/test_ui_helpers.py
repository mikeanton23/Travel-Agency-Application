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


class _FakeClient:
    def __init__(self, elements=None, connected=True):
        self.elements = elements if elements is not None else {}
        self.has_socket_connection = connected


class _FakeElement:
    def __init__(self, client=None, element_id=1, raises=False):
        self._client = client
        self.id = element_id
        self._raises = raises
        self.cleared = False

    @property
    def client(self):
        if self._raises:
            raise RuntimeError(
                "The client this element belongs to has been deleted.")
        return self._client

    def clear(self):
        self.cleared = True


def test_element_alive_detects_a_deleted_page():
    from app.ui.helpers import element_alive

    assert not element_alive(_FakeElement(raises=True))
    assert not element_alive(None)


def test_element_alive_detects_a_detached_element():
    """NiceGUI only logs when a detached element is touched, so the
    check must notice the element is no longer registered."""
    from app.ui.helpers import element_alive

    client = _FakeClient(elements={})          # element not registered
    assert not element_alive(_FakeElement(client, element_id=7))

    client = _FakeClient(elements={7: object()})
    assert element_alive(_FakeElement(client, element_id=7))


def test_element_alive_detects_a_closed_socket():
    from app.ui.helpers import element_alive

    client = _FakeClient(elements={7: object()}, connected=False)
    assert not element_alive(_FakeElement(client, element_id=7))


def test_safe_clear_only_clears_live_elements():
    from app.ui.helpers import safe_clear

    dead = _FakeElement(raises=True)
    assert safe_clear(dead) is False
    assert dead.cleared is False

    live = _FakeElement(_FakeClient(elements={7: object()}),
                        element_id=7)
    assert safe_clear(live) is True
    assert live.cleared is True
