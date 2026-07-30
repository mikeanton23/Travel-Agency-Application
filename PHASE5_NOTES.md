# Phase 5 — Auth, Accounts, Admin, Security & Monitoring

## Authentication (`app/services/auth_service.py`)
- Password hashing: stdlib `hashlib.scrypt` (N=2^14, r=8, p=1),
  per-user random salt, constant-time verification — **zero new
  dependencies**. Stored as `scrypt$N$r$p$salt$hash`.
- Register (email validation, min 8-char password, normalized email),
  authenticate (identical error for unknown email vs wrong password —
  no account enumeration; disabled accounts blocked; `last_login_at`
  recorded), change_password.
- Login attempts rate-limited: 5 per 5 minutes per client key.

## Rate limiting (`app/utils/rate_limit.py`)
Thread-safe sliding-window limiter with `retry_after` reporting and
key pruning. Shared instances for login/search/LLM; the interface is
Redis-swappable for multi-worker deployments.

## Monitoring (`app/services/metrics.py` + instrumentation)
- `HttpJsonClient` now records **every outbound API call** (provider
  inferred from host, method, status, latency) into in-memory counters
  and, best-effort, the new `api_usage` table — so Amadeus, Numbeo,
  Geoapify, LLM and wiki traffic is all measured automatically with
  zero per-service code.
- Cache hit/miss/size stats added to `ApiCacheService.stats()`.
- Deliberate honesty call: the admin panel shows request counts,
  error rates and latency (real), **not monetary cost** — billing
  math without provider price sheets would be a fake value.

## User accounts (UI + repositories)
- `/login`: sign-in / create-account tabs; session in
  `app.storage.user` signed by `APP_SECRET_KEY`.
- `/account` (login-gated): favorites grid, trips with item counts +
  create-trip, notifications with unread badge and mark-read.
- Destination pages get a ♥ toggle for logged-in users; the header
  shows the session (name → account, admin shield when applicable,
  Sign in otherwise).
- Repositories: `FavoriteRepository` (toggle/list, unique per pair),
  `TripRepository` (ordered items carrying the raw real-API offer),
  `NotificationRepository`, `UserAdminRepository`.

## Admin dashboard (`/admin`, admin-gated)
- Database card (connectivity + row counts), cache card (hit rate,
  entries, tiers), API traffic card (per-provider counts/errors/avg
  latency this process).
- Recent API calls table from `api_usage` (persisted, newest first,
  failures highlighted).
- User management: enable/disable and promote/demote in place.
- One-click provider key health check (Phase 1 key manager).

## New tables
`api_usage` (indexed provider+created_at), `notifications` (indexed
user+created_at) → 26 models total. Migrate:

```bash
alembic revision --autogenerate -m "phase5 usage + notifications"
alembic upgrade head
```

## Bootstrap the first admin
```bash
python3 - <<'PY'
from app.db.database import SessionLocal
from app.db.models import User
s = SessionLocal()
s.query(User).filter_by(email="you@example.com").update({"is_admin": True})
s.commit()
PY
```

## Tests
88 offline tests total (`pytest -q`): hashing uniqueness/rejection,
full auth flows incl. enumeration resistance and rate-limited login,
limiter window mechanics, provider mapping, HTTP→metrics
instrumentation, cache stats, favorites/trips/notifications/admin
repositories.

## Remaining follow-ups (beyond the 5 phases)
- Trip planner UI depth (add flight/hotel offers to trips from search)
- Charts on admin + destination pages (echarts)
- Background workers (APScheduler): cache cleanup, notification jobs
- Redis-backed limiter/cache when moving to multiple workers

## Developer setup helpers (post-Phase-5 addition)
- `python3 -m app.doctor` — one-shot health check: .env values, DB
  connectivity, missing tables (with the exact alembic command), and a
  real validation call for every configured provider, plus signup URLs
  and free-tier notes for the missing ones.
- The Settings page now shows each provider's friendly name, its
  free/paid tier, and a "Get key" link when unconfigured.
