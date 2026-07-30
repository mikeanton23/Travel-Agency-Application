# Phase 3 — AI Engine: Intelligence Score, Multi-LLM, RAG, NL Search

## 1. Travel Intelligence Score (`app/services/intelligence/`)

Thirteen match dimensions: Budget, Weather, Food, History, Nature,
Nightlife, Family, Adventure, Luxury, Hidden Gem, Safety, Crowd, Beach.

**The contract (score.py):**
- Every dimension computes only from real inputs in
  `DestinationSignals`. Missing data → `score=None` with an
  "insufficient data" reason. **No dimension ever invents a number** —
  e.g. Luxury requires real hotel ratings; Crowd requires visitor
  volume + population (no free global source exists, so it honestly
  reports unavailable unless you supply the data).
- Every score explains WHY with the actual values used
  (`reason` + `inputs_used`), e.g. *"Your budget 150 EUR/day vs a real
  daily basket of 121.40 (two budget meals 30.00, coffee 3.50, two
  transit tickets 2.40, median hotel night 85.50) — budget covers 124%
  of typical costs."*
- Overall = interest-weighted mean of *available* dimensions, reported
  with `coverage` and `kind="ai_score"` so the UI must label it as
  AI-derived.

**Real signal collection (signals.py):**
- Numbeo prices via Phase 2 `cost_service`; Numbeo indices → safety
- Open-Meteo Climate API (keyless) → monthly temperature normals,
  rainy days, sunshine
- Geoapify Places → POI counts per category (restaurants, museums,
  parks, beaches, playgrounds, bars, outdoor sports…)
- Amadeus hotel quotes → median nightly price, rating distribution
All cached with long TTLs (climate 30d, POIs 7d).

## 2. Multi-provider LLM (`app/services/llm/`)

- Providers: **OpenAI, Anthropic, Gemini, Ollama** (Mistral/Llama run
  as Ollama models — set the model name). Plain REST via httpx, so
  everything tests offline with `MockTransport`.
- Uniform `complete()` and **streaming** `stream()` (SSE for the
  hosted three, NDJSON for Ollama); system messages handled per
  provider's convention (Anthropic `system` field, Gemini
  `systemInstruction`).
- `LLMService`: selectable provider, keys via encrypted key manager →
  env fallback, `available_providers()` for the UI dropdown, and
  **conversation memory** persisted to the Phase 1
  `ai_conversations`/`ai_messages` tables — history is auto-prepended
  on every turn.
- New setting: `OLLAMA_HOST` (default `http://localhost:11434`).

## 3. RAG (`app/services/rag/` + 2 new tables)

- **Knowledge**: real page text from Wikipedia *and* Wikivoyage via the
  MediaWiki extracts API, cached 30 days; paragraph-aware chunking with
  overlap.
- **Embeddings**: OpenAI `text-embedding-3-small` when a key exists,
  otherwise local `sentence-transformers` (already in requirements —
  no key, no fake vectors).
- **Store**: `kb_documents` → `kb_chunks` (unique per position,
  embedding as JSON). Exact cosine search — correct for
  per-destination corpora; the `VectorStore` interface is the seam for
  pgvector/FAISS if the corpus grows.
- **Answers**: retrieval → grounded prompt with numbered sources →
  any LLM provider; the system prompt forbids inventing facts and the
  response carries its source chunks (title + URL) for UI citations.
  No index → the service says so instead of hallucinating.

## 4. Natural-language search (`app/services/nl_search.py`)

"romantic quiet island in Europe with wine tasting under $180/day" →
validated `TravelQuery` (budget 180 USD/day, Europe, island, quiet,
interests [romantic, wine]).

- LLM path: strict-JSON prompt → Pydantic validation → merged with
  deterministic extraction so explicit signals (an "$180/day") always
  survive.
- Fallback path: regex/keyword parser (budgets in symbols or words,
  months, continents, 13 interest groups) — fully deterministic, works
  with zero LLM configured, and extracts only what the user said.
- Feeds `DestinationRepository.search` + the score `UserProfile`.

## Setup & tests

```bash
alembic revision --autogenerate -m "phase3 kb tables"  # adds kb_documents/kb_chunks
alembic upgrade head
pytest -q        # 65 tests total, all offline
```

## Wiring example

```python
from app.db.database import SessionLocal
from app.services.intelligence.signals import signals_collector
from app.services.intelligence.score import compute_score, UserProfile
from app.services.nl_search import nl_search_parser
from app.services.rag.rag_service import RagService

q = await nl_search_parser.parse(user_text, provider="anthropic")
signals = await signals_collector.collect(
    "Santorini", "Greece", 36.39, 25.46, month=q.month or 9,
    currency=q.currency,
)
score = compute_score(signals, UserProfile(
    budget_per_day=q.budget_per_day, interests=q.interests,
    traveling_with_kids=q.traveling_with_kids,
))
# score.to_dict() -> per-dimension scores, reasons, coverage, kind="ai_score"

rag = RagService(session_factory=SessionLocal)
await rag.index_destination("Santorini", destination_id=1)
answer = await rag.answer("When is the quiet season?",
                          provider="anthropic", destination_id=1)
```

## Follow-ups
- Phase 4 renders dimension bars + "why" tooltips, streams chat, and
  shows RAG citations.
- Consider pgvector once the KB spans hundreds of destinations.
