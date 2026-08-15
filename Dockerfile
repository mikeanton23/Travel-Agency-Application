# Aevyra production image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build deps for psycopg2 and friends, removed after install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y

COPY . .

# The entrypoint must survive a copy through Windows: strip any CRLF
# line endings and restore the executable bit. Without this the
# container exits immediately with no output ("bad interpreter").
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

# Run as a non-root user.
RUN useradd --create-home --uid 10001 aevyra \
    && chown -R aevyra:aevyra /app
USER aevyra

# Render/Fly inject PORT at runtime; this is only documentation.
EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8086}/robots.txt" || exit 1

CMD ["sh", "./start.sh"]
