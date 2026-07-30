# Phase 2 — Real-Data Services

## What was added

| File | Purpose |
|---|---|
| `app/utils/http_client.py` | Shared async HTTP client: retry with exponential backoff + jitter, `Retry-After` handling on 429, consistent `ApiError`. Injectable transport makes every service testable offline. |
| `app/services/cache_service.py` | (Was an empty file.) Two-tier cache: in-memory TTL + persistent `api_cache` PostgreSQL table. `@api_cache.cached(namespace, ttl)` decorator. `None` results are never cached. |
| `app/services/amadeus_service.py` | Real flights and hotels. OAuth2 token management with auto-refresh on 401, flight offers with **cheapest / fastest / best** labels (transparent weighted rule, not a black box), hotels near a coordinate, live hotel prices via Hotel Search v3, city→IATA resolution. |
| `app/services/currency_service.py` | Real exchange rates. Provider chain: OpenExchangeRates (key) → Frankfurter/ECB (keyless) → open.er-api.com (keyless). Works with zero keys. |
| `app/services/cost_service.py` | Real cost of living via Numbeo (meal, cappuccino, beer, taxi, public transport). Converts to any currency using real FX rates. **Returns `None` + a reason when data is unavailable — never estimates.** |
| `app/db/models.py` | New `ApiCache` table with index on `expires_at`. |
| `app/db/database.py` | **Fixed:** credentials were hardcoded (`agent:123456789@localhost`). Now reads `DB_URL` from `.env`, adds connection pooling + `pool_pre_ping`, and wires the cache's persistent tier at startup. |
| `app/utils/config.py` | New keys: `AMADEUS_ENV`, `OPENEXCHANGERATES_API_KEY`, `NUMBEO_API_KEY`. |
| `.env.example` | Template for all keys with sign-up links. |
| `tests/` | 18 offline tests (`httpx.MockTransport`) covering caching, retry/fallback chains, token refresh, offer parsing/labeling, and the no-estimates policy. |
| `requirements.txt` | Fixed the bare `Nicegui` line merged after numpy → `nicegui>=2.0.0`. |

## The "no fake values" contract

Every Phase 2 function follows one rule: **real data or nothing.**

- Amadeus not configured → `[]` (UI shows "flight data unavailable")
- All currency providers down → `None`
- No Numbeo key → `None`, and `cost_service.unavailable_reason()` gives the UI a human-readable explanation

This is the replacement pattern for `pricing_service.py`'s `estimate_*`
functions and `booking_service.py`'s keyword-guessed booking info. Those
files are untouched (nothing removed), but new UI work should call the
new services and stop calling `get_place_pricing()`.

## Setup

```bash
cp .env.example .env        # fill in DB_URL and any keys you have
pip install -r requirements.txt
python3 - <<'PY'
from app.db.database import engine
from app.db.models import Base
Base.metadata.create_all(engine)   # creates the new api_cache table
PY
pytest -q                   # 18 tests, no network needed
```

Amadeus: free self-service keys at https://developers.amadeus.com —
start with `AMADEUS_ENV=test` (sandbox has limited but real inventory),
switch to `production` once your app is approved.

## Usage examples

```python
from app.services.amadeus_service import amadeus_service
from app.services.currency_service import currency_service
from app.services.cost_service import cost_service

offers = await amadeus_service.search_flights("ATH", "CDG", "2026-09-14")
# offers[0]["labels"] -> ["cheapest"] etc., offers[0]["source"] == "amadeus"

hotels = await amadeus_service.hotels_near(48.8566, 2.3522, radius_km=5)
prices = await amadeus_service.hotel_offers(
    [h["hotel_id"] for h in hotels[:10]], "2026-09-14", "2026-09-17"
)

fx = await currency_service.convert(180, "USD", "EUR")

costs = await cost_service.city_costs("Athens", "Greece",
                                      target_currency="USD")
if costs is None:
    reason = cost_service.unavailable_reason()  # show this, don't estimate
```

## Suggested next steps (Phase 2.5 before Phase 3)

1. Replace `estimate_*` call sites in `pages.py` / `recommendation_service.py`
   with the new services, rendering "unavailable" badges where data is `None`.
2. Add a periodic cleanup job (APScheduler is already in requirements)
   deleting expired `api_cache` rows.
3. Alembic migration instead of `create_all` once Phase 1 (full schema
   redesign) lands.
