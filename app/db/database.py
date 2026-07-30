# -*- coding: utf-8 -*-

"""
Database engine and session factory.

The connection URL comes from the ``DB_URL`` environment variable
(loaded by ``app.utils.config``) — credentials are never hardcoded.
On import this module also binds the session factory into the
API cache service so cached API responses persist across restarts.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.utils import config

if not config.DB_URL:
    raise RuntimeError(
        "DB_URL is not set. Copy .env.example to .env and configure "
        "your PostgreSQL connection string."
    )

engine = create_engine(
    config.DB_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # drop dead connections instead of erroring
    pool_recycle=1800,
)

SessionLocal = sessionmaker(bind=engine)


def _wire_services() -> None:
    """Bind DB-backed tiers: persistent cache + API usage metrics."""
    from app.services.cache_service import api_cache
    from app.services.metrics import metrics

    api_cache.bind_session_factory(SessionLocal)
    metrics.bind_session_factory(SessionLocal)


_wire_services()
