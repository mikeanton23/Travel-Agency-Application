# -*- coding: utf-8 -*-

"""
Aevyra entry point.

Default: the v2 Travel Intelligence Platform UI.
Set LEGACY_UI=true to load the original single-page UI instead --
kept intact per the "never remove functionality" rule.
"""

import os

from nicegui import ui

if os.getenv("LEGACY_UI", "").strip().lower() in ("1", "true", "yes"):
    from app.ui.pages import home_page
    home_page()
else:
    import app.ui.pages_v2  # noqa: F401  (registers @ui.page routes)

from app.utils.settings import get_settings

_secret = (get_settings().app_secret_key or "").strip()
if not _secret:
    import secrets
    _secret = secrets.token_urlsafe(32)
    print(
        "WARNING: APP_SECRET_KEY is not set in .env -- using an "
        "ephemeral secret. Logins and theme preference will reset "
        "on every restart, and encrypted API-key storage is disabled."
    )

_production = (
    get_settings().app_env.strip().lower() == "production"
)

ui.run(
    title="Aevyra - Travel Intelligence Platform",
    host="0.0.0.0",          # reachable from the reverse proxy
    port=int(os.getenv("PORT", "8086")),
    show=False,              # no browser on a server / WSL
    reload=not _production,  # never hot-reload in production
    storage_secret=_secret,
)
