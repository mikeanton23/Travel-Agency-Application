# -*- coding: utf-8 -*-

"""
Aevyra setup doctor — run ``python3 -m app.doctor``.

Checks, in order:
1. .env presence and required values (DB_URL, APP_SECRET_KEY)
2. Database connectivity and which tables exist
3. Which providers are configured, validating each with one real
   minimal API call, and where to sign up for the missing ones

Exit code 0 when the core (env + DB) is healthy.
"""

from __future__ import annotations

import asyncio
import sys

OK = "\033[92m✔\033[0m"
WARN = "\033[93m⚠\033[0m"
FAIL = "\033[91m✘\033[0m"


def check_env() -> bool:
    from app.utils.settings import ENV_PATH, get_settings

    print("— Environment —")
    healthy = True
    if ENV_PATH.exists():
        print(f"{OK} .env found at {ENV_PATH}")
    else:
        print(f"{WARN} no .env file — using process environment only")
    s = get_settings()
    if s.db_url:
        print(f"{OK} DB_URL is set")
    else:
        print(f"{FAIL} DB_URL is missing — the app cannot start")
        healthy = False
    if s.app_secret_key and len(s.app_secret_key) >= 16:
        print(f"{OK} APP_SECRET_KEY is set")
    else:
        print(f"{WARN} APP_SECRET_KEY missing/short — logins won't "
              f"persist and encrypted key storage is disabled")
    return healthy


def check_database() -> bool:
    print("\n— Database —")
    try:
        from sqlalchemy import inspect, text
        from app.db.database import engine
        from app.db.models import Base
    except Exception as exc:
        print(f"{FAIL} cannot initialise database layer: {exc}")
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"{OK} connected")
    except Exception as exc:
        print(f"{FAIL} connection failed: {str(exc)[:200]}")
        print("   Is PostgreSQL running and DB_URL correct?")
        return False
    expected = set(Base.metadata.tables)
    existing = set(inspect(engine).get_table_names())
    missing = sorted(expected - existing)
    if not missing:
        print(f"{OK} all {len(expected)} tables present")
    else:
        print(f"{WARN} {len(missing)} tables missing: "
              f"{', '.join(missing[:6])}"
              + ("…" if len(missing) > 6 else ""))
        print("   Run: alembic revision --autogenerate -m baseline "
              "&& alembic upgrade head")
    return True


async def check_providers() -> None:
    from app.services.key_manager import KeyManager, PROVIDER_INFO

    print("\n— Providers —")
    manager = KeyManager()
    entries = manager.list_keys()
    configured = [e for e in entries if e["configured"]]
    unconfigured = [e for e in entries if not e["configured"]]

    if configured:
        print(f"Validating {len(configured)} configured provider(s) "
              f"with real API calls…")
        results = await asyncio.gather(*[
            manager.validate(e["provider"]) for e in configured
        ])
        for result in results:
            provider = result["provider"]
            if result["is_valid"]:
                print(f"{OK} {provider}: key works")
            else:
                print(f"{FAIL} {provider}: {result['error']}")
    for entry in unconfigured:
        info = PROVIDER_INFO.get(entry["provider"], {})
        note = info.get("tier", "")
        signup = info.get("signup", "")
        print(f"{WARN} {entry['provider']}: not configured"
              + (f" — {note}" if note else "")
              + (f"\n   sign up: {signup}" if signup else ""))
    print("\nProviders can also be added at runtime in Settings "
          "(stored encrypted).")


def main() -> int:
    env_ok = check_env()
    db_ok = check_database() if env_ok else False
    if env_ok:
        try:
            asyncio.run(check_providers())
        except Exception as exc:
            print(f"{WARN} provider checks skipped: {exc}")
    print("\n" + ("All core checks passed — run: python3 -m app.main"
                  if env_ok and db_ok
                  else "Fix the items marked above, then re-run "
                       "python3 -m app.doctor"))
    return 0 if env_ok and db_ok else 1


if __name__ == "__main__":
    sys.exit(main())
