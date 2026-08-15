#!/bin/sh
# Container entrypoint: apply migrations, then serve.
echo "Applying database migrations..."
if ! alembic upgrade head; then
    echo "WARNING: alembic upgrade failed - the app will still start,"
    echo "but tables may be missing. Check DB_URL and the log above."
fi
# Optional one-time data bootstrap for hosts without shell access.
# Safe to leave enabled: it only acts when the table is empty.
python3 -u -m app.db.bootstrap || true

echo "Starting Aevyra on port ${PORT:-8086}..."
exec python3 -u -m app.main
