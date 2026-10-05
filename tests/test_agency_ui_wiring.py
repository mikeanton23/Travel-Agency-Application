# -*- coding: utf-8 -*-

"""The agency pages must call the service layer correctly.

NiceGUI pages cannot be rendered headlessly here, so these tests check
the contract between the UI and the services: that every function the
pages call exists with the parameters they pass, and that no route
collides with the public site.
"""

import ast
import inspect

import pytest


def _module_source(path):
    return ast.parse(open(path).read())


def test_agency_routes_do_not_collide_with_public_pages():
    import glob
    import re

    routes = {}
    for path in glob.glob("app/ui/*.py"):
        try:
            source = open(path, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue      # a stray non-UTF8 file is not a route module
        for match in re.finditer(r'@ui\.page\("([^"]+)"\)', source):
            route = match.group(1)
            assert route not in routes, (
                f"{route} registered twice: {routes.get(route)} "
                f"and {path}")
            routes[route] = path

    for expected in ("/agency", "/agency/clients", "/agency/quotes",
                     "/agency/bookings", "/agency/cash"):
        assert expected in routes, f"{expected} is not registered"


def test_services_expose_everything_the_ui_calls():
    from app.services.agency.bookings import booking_service
    from app.services.agency.cash import cash_service
    from app.services.agency.clients import client_service
    from app.services.agency.documents import document_service
    from app.services.agency.invoicing import invoice_service
    from app.services.agency.quotes import quote_service

    expected = [
        (client_service, "create"), (client_service, "search"),
        (client_service, "get"), (client_service, "add_note"),
        (client_service, "notes"),
        (quote_service, "create"), (quote_service, "add_item"),
        (quote_service, "remove_item"), (quote_service, "get"),
        (quote_service, "set_status"), (quote_service, "list_for"),
        (booking_service, "create_from_quote"),
        (booking_service, "confirm_item"),
        (booking_service, "confirm_via_supplier"),
        (booking_service, "record_payment"),
        (booking_service, "get"), (booking_service, "list_for"),
        (cash_service, "ensure_account"), (cash_service, "record"),
        (cash_service, "reverse"), (cash_service, "balance"),
        (cash_service, "movements"),
        (cash_service, "totals_by_method"),
        (invoice_service, "issue_for_booking"),
        (document_service, "voucher"),
        (document_service, "travel_pack"),
    ]
    for service, name in expected:
        assert callable(getattr(service, name, None)), (
            f"{type(service).__name__}.{name} is missing")


def test_quote_add_item_accepts_the_positional_order_the_ui_uses():
    """The builder passes these positionally; a reorder would silently
    put the service charge into the wrong field."""
    from app.services.agency.quotes import QuoteService

    params = list(inspect.signature(
        QuoteService.add_item).parameters)
    assert params[:10] == [
        "self", "quote_id", "service_type", "title", "net_cost",
        "service_charge", "quantity", "is_domestic", "vat_rate",
        "supplier",
    ]


def test_cash_record_accepts_the_positional_order_the_ui_uses():
    from app.services.agency.cash import CashService

    params = list(inspect.signature(CashService.record).parameters)
    assert params[:6] == [
        "self", "account_id", "amount", "method", "agent_id",
        "direction",
    ]


def test_every_agency_page_requires_a_signed_in_agent():
    """No agency screen may render for an anonymous visitor."""
    import glob
    import re

    for path in ("app/ui/pages_agency.py",
                 "app/ui/pages_agency_quotes.py",
                 "app/ui/pages_agency_ops.py"):
        source = open(path).read()
        pages = re.findall(
            r'@ui\.page\("[^"]+"\)\ndef (\w+)\([^)]*\) -> None:\n'
            r'(.*?)(?=\n@ui\.page|\Z)', source, re.S)
        assert pages, f"no pages found in {path}"
        for name, body in pages:
            assert "require_agent()" in body, (
                f"{name} in {path} does not guard access")
            assert "noindex" in body, (
                f"{name} in {path} is not marked noindex")


def test_documents_are_streamed_not_filesystem_paths():
    """The service returns base64 content; downloading a path would
    always fail."""
    source = open("app/ui/pages_agency_ops.py").read()
    assert "base64.b64decode" in source
    assert 'document.get("content")' in source
