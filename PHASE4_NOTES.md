# Phase 4 — New UI: Travel Intelligence Platform

## Approach

The original `app/ui/pages.py` (2,174 lines) is untouched and still
runnable — `LEGACY_UI=true python3 -m app.main`. The new default UI is
component-based:

```
app/ui/
  theme.py                  design tokens, dark/light, glassmorphism,
                            hover motion, fade-in, skeleton CSS
  format.py                 PURE display helpers (no NiceGUI) — the
                            "no fake values" rule enforced at render
  components/
    layout.py               glass header + nav sidebar + theme toggle
    cards.py                destination cards, badges, skeletons
    score_panel.py          per-dimension bars with WHY explanations
    chat_panel.py           provider select + streaming chat + memory
    settings_panel.py       encrypted keys: save / validate / health
  pages_v2.py               routes: / , /destination/{id}, /chat,
                            /settings
```

## What the pages do

**Explore (/):** gradient hero with the natural-language search box
("romantic quiet island in Europe with wine tasting under $180/day"
parses live and fills the filters), a glass filter sidebar (continent,
budget slider, month, interest chips), and a responsive card grid.
Cards render instantly, then real badges stream in asynchronously
(Numbeo meal price, Open-Meteo month climate) behind skeletons. The AI
score is computed on demand per card and always carries its coverage
("AI score 82/100 · 69% data").

**Destination (/destination/{id}):** hero, Leaflet map with marker
(or an honest "no coordinates stored"), the real Numbeo price table
with contributor count and source line, and the full score panel —
one bar per dimension, each with its WHY sentence; unavailable
dimensions state their reason in italics instead of showing a bar.

**AI Copilot (/chat):** provider dropdown built from
`available_providers()` (only providers with a working key appear;
Ollama always local), model field auto-fills defaults, responses
stream token-by-token into the chat, and every exchange persists to
`ai_conversations` for cross-turn memory. "New chat" starts a fresh
conversation row.

**Settings (/settings):** the key-manager UI — per-provider status
icon (valid / invalid / unvalidated / unconfigured), source shown as
"db (encrypted)" vs "env", password-masked input to store a key
encrypted, per-provider Validate (one real API call), error tooltips,
and a one-click health check across all configured providers.

## The honesty layer

`format.py` is where "no fake values" is enforced for rendering:
badge builders return `None` (badge simply not shown) when there's no
real data; `fmt_money(None) == "—"`; the AI badge says "insufficient
data" rather than a number. All of it is pure-Python and covered by
`tests/test_ui_format.py`.

## Design system

Dark + light mode (auto by default, toggle persisted per browser via
`app.storage.browser`), glassmorphism cards (`.tv-glass`), hover lift
(`.tv-card`), hero gradient, pill badges, fade-in transitions, and
skeleton loaders — defined once in `theme.py` as CSS custom properties
that flip with the `.dark` class.

## Run it

```bash
python3 -m app.main                # v2 UI on :8086
LEGACY_UI=true python3 -m app.main # original UI, unchanged
```

Set `APP_SECRET_KEY` in `.env` — it doubles as NiceGUI's
`storage_secret` for the per-browser theme persistence.

## Honest limitations

- I could not execute NiceGUI in the build sandbox (no network for
  pip), so the UI is compile-checked and its logic layer is
  unit-tested, but the pages themselves need one visual pass on your
  machine. NiceGUI ≥ 2.0 is targeted (`ui.leaflet`, `ui.navigate`,
  `app.storage.browser`); if you're pinned older, tell me and I'll
  adjust.
- Flight/hotel badges on cards are wired through `format.py` but the
  Explore page doesn't yet ask for origin airport + dates; adding a
  "trip context" bar that unlocks Amadeus badges is the natural next
  increment.
- Charts (price history, weather timeline) and the admin dashboard
  belong to Phase 5 alongside auth.

## Test suite

70 offline tests total after this phase (`pytest -q`).
