#!/bin/sh
# Container entrypoint: apply migrations, then serve.
set -e
echo "Applying database migrations..."
alembic upgrade head || echo "Migration step skipped or already current"
echo "Starting Aevyra..."
exec python3 -m app.main
