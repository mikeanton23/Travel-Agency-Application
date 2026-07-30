# Phase 1 — Database, Architecture, API-Key System

## What was added

### 1. Normalized schema (`app/db/models.py`) — 22 models
New tables, all additive (the original 4 are untouched, so no existing
code breaks):

- **Geo hierarchy:** `countries` (unique ISO2/ISO3) → `regions` → `cities`
  (lat/lon index, IATA city code). `destinations` gained *nullable*
  `country_id` / `city_id` FKs so existing rows keep working while new
  code links into the hierarchy.
- **Inventory:** `hotels` (unique per source+external_id, last real
  quote fields), `attractions`, `events` (indexed by destination+date).
- **Users:** `users`, `user_preferences` (1:1), `trips` → `trip_items`
  (ordered, stores the raw real-API offer in `reference`), `favorites`
  (unique per user+destination), `reviews`, `search_history`.
- **Infrastructure:** `weather_cache` (structured, indexed lookup),
  `api_keys` (encrypted), `ai_conversations` → `ai_messages`.
- **Bug fixed:** `seed.py` used `tags`, `best_months`, `image_urls` —
  columns that didn't exist, so seeding crashed. They're now real JSON
  columns on `Destination`.

Embeddings/vector tables are deliberately deferred to Phase 3 (RAG),
where the pgvector-vs-FAISS decision belongs.

### 2. Alembic migrations
`alembic.ini` + `migrations/env.py` wired to the app's metadata and
`.env` (`DB_URL` is injected at runtime — never stored in the ini).

```bash
# Fresh database:
alembic revision --autogenerate -m "phase1 baseline"
alembic upgrade head

# Existing database that already has the old 4 tables:
# generate the revision, REVIEW it (autogenerate will try to create
# the old tables too — delete those ops), then upgrade.
```

### 3. Typed settings (`app/utils/settings.py`)
Pydantic-settings model as the single source of truth. `config.py` is
now a thin backward-compatible shim re-exporting every historical name
(`GEOAPIFY_API_KEY`, `OLLAMA_MODEL`, …) — verified against every import
site in the codebase. The noisy startup prints are gone unless
`DEBUG=true`.

### 4. Encrypted API-key manager (`app/services/key_manager.py`)
The backend the Settings page will call in Phase 4:

- Keys encrypted at rest with Fernet (`app/utils/crypto.py`); the key
  derives from `APP_SECRET_KEY`. Wrong/rotated secret → clean `None`,
  fallback to env, never garbage.
- Resolution precedence: **DB override → environment variable.**
- `validate(provider)` proves a key works with one real minimal API
  call (registry covers Geoapify, Pexels, Ticketmaster,
  OpenRouteService, OpenWeather, OpenExchangeRates, Numbeo, OpenAI,
  Anthropic, and Amadeus via its OAuth token endpoint) and persists
  `is_valid` / `last_validated_at` / `last_error`.
- `health()` validates all configured providers concurrently — ready
  for the admin dashboard.
- `list_keys()` never exposes key values.

### 5. Repository layer (`app/repositories/`)
`BaseRepository` (generic CRUD, injected session) +
`DestinationRepository` (search with filters, score-ordered) as the
reference pattern. Migrating the 24 existing services onto it is
incremental follow-up work, not a big-bang rewrite.

## Setup

```bash
pip install -r requirements.txt          # adds cryptography
# .env: set APP_SECRET_KEY (see .env.example for the generator one-liner)
pytest -q                                # 36 tests, all offline
```

## Test coverage added (18 new tests)
- Settings env parsing + safe defaults
- Fernet roundtrip, wrong-key behavior, weak-secret rejection
- Encryption at rest, DB-over-env precedence, deletion, value redaction
- Validation success/failure persistence, Amadeus composite flow,
  missing-key path
- Full 22-model schema creation on SQLite, repository filters/ordering,
  unique constraints (favorites, country ISO)

## Known follow-ups
- `pages.py` still instantiates services directly; wiring them through
  repositories + DI happens as Phase 4 rebuilds each page.
- Add a `users` auth service (password hashing, sessions) in Phase 5 —
  the schema is ready for it.
