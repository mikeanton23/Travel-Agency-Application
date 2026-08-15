#!/bin/sh
# Container entrypoint: ensure schema, seed if needed, then serve.

# Creates any missing tables from the models and stamps Alembic at
# head. Safe and idempotent: it exits immediately when the schema is
# already present.
echo "Checking database schema..."
python3 -u -m app.db.bootstrap || true

# Normal migration path for subsequent schema changes.
echo "Applying database migrations..."
if ! alembic upgrade head; then
    echo "WARNING: alembic upgrade reported a problem - see above."
fi

echo "Starting Aevyra on port ${PORT:-8086}..."
exec python3 -u -m app.main
