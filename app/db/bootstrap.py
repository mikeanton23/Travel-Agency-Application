# -*- coding: utf-8 -*-

"""
Startup bootstrap for hosts without shell access (e.g. Render free).

Runs from ``start.sh`` when ``SEED_ON_START=true``. It is deliberately
idempotent and conservative:

* seeds only when the destinations table is empty, so a restart can
  never duplicate rows or overwrite edited data;
* promotes ``ADMIN_EMAIL`` to admin if that user already exists - it
  never creates an account or sets a password, because provisioning
  credentials from an environment variable would be a bad idea;
* never raises: a bootstrap problem must not stop the web service
  from starting.

Run manually with:  python3 -m app.db.bootstrap
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="[bootstrap] %(message)s")
logger = logging.getLogger(__name__)


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def destinations_count() -> int:
    from app.db.database import SessionLocal
    from app.db.models import Destination

    session = SessionLocal()
    try:
        return session.query(Destination).count()
    finally:
        session.close()


def seed_if_empty() -> None:
    """Populate destinations only when there are none."""
    try:
        existing = destinations_count()
    except Exception as exc:
        logger.warning("Could not count destinations: %s", exc)
        return

    if existing:
        logger.info("%d destinations already present - not seeding",
                    existing)
        return

    # Note: seed() clears the destinations table first, which is
    # exactly why this only ever runs when the table is empty.
    logger.info("Destinations table is empty - seeding")
    try:
        from app.db import seed as seed_module
    except Exception as exc:
        logger.warning("Seed module unavailable: %s", exc)
        return

    try:
        entry = None
        for name in ("seed", "main", "run", "seed_database"):
            entry = getattr(seed_module, name, None)
            if callable(entry):
                entry()
                break
        else:
            # Importing the module is itself the seeding step in some
            # layouts; the import above already ran it.
            logger.info("Seed module executed on import")
        logger.info("Seeding finished: %d destinations",
                    destinations_count())
    except Exception as exc:
        logger.warning("Seeding failed: %s", exc)


def promote_admin() -> None:
    """Grant admin to ADMIN_EMAIL if that account exists already."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not email:
        return
    try:
        from app.db.database import SessionLocal
        from app.db.models import User

        session = SessionLocal()
        try:
            user = (session.query(User)
                    .filter(User.email == email).one_or_none())
            if user is None:
                logger.info(
                    "ADMIN_EMAIL %s has no account yet - register on "
                    "the site, then restart to be promoted", email)
                return
            if user.is_admin:
                logger.info("%s is already an admin", email)
                return
            user.is_admin = True
            session.commit()
            logger.info("Promoted %s to admin", email)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("Admin promotion skipped: %s", exc)


def main() -> int:
    if not _truthy(os.getenv("SEED_ON_START", "")):
        logger.info("SEED_ON_START not set - skipping bootstrap")
        return 0
    seed_if_empty()
    promote_admin()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never block startup
        logger.warning("Bootstrap aborted: %s", exc)
        sys.exit(0)
