# -*- coding: utf-8 -*-

"""
Design system v3 — "Flight deck".

Identity: ink-navy instrument panel + porcelain daylight surfaces.
Display type: Fraunces (editorial serif, headlines only).
Body: Plus Jakarta Sans. Data: IBM Plex Mono — every number, price,
badge and coordinate reads as instrumentation.
Signature: the hero is a dark departure board with drifting
cartographic contour lines and a live data ticker.
"""

from nicegui import ui

GLOBAL_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..600,0..1,0" rel="stylesheet">
<style>
:root {
  --tv-ink: #0B1526;
  --tv-ink-2: #101E33;
  --tv-paper: #F4F7F8;
  --tv-surface: #FFFFFF;
  --tv-teal: #0FA3A3;
  --tv-amber: #FFB454;
  --tv-data: #7BE0C8;
  --tv-line: rgba(15, 40, 70, 0.12);
  --tv-muted: rgba(20, 35, 60, 0.62);
  --tv-radius: 16px;
  --tv-shadow: 0 10px 30px rgba(11, 21, 38, 0.10);
  --tv-shadow-hover: 0 22px 48px rgba(15, 163, 163, 0.22);
  --tv-placeholder: linear-gradient(150deg, #0FA3A3 0%, #16608A 55%, #0B1526 100%);
}
.dark {
  --tv-paper: #0A111F;
  --tv-surface: #101A2E;
  --tv-line: rgba(160, 200, 230, 0.12);
  --tv-muted: rgba(200, 220, 240, 0.60);
  --tv-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  --tv-shadow-hover: 0 22px 48px rgba(15, 163, 163, 0.30);
}

body {
  font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
  background: var(--tv-paper);
}
.body--dark { background: var(--tv-paper); }

.tv-display {
  font-family: 'Fraunces', Georgia, serif;
  letter-spacing: -0.01em;
}
.tv-mono {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  letter-spacing: 0.02em;
}

/* ---------- surfaces ---------- */
.tv-glass {
  background: var(--tv-surface);
  border: 1px solid var(--tv-line);
  border-radius: var(--tv-radius);
  box-shadow: var(--tv-shadow);
}
.tv-card {
  overflow: hidden;
  transition: transform .3s cubic-bezier(.2,.8,.2,1), box-shadow .3s ease;
}
.tv-card:hover {
  transform: translateY(-5px);
  box-shadow: var(--tv-shadow-hover);
}
.tv-muted { color: var(--tv-muted); }

/* ---------- destination media (unchanged behaviour) ---------- */
.tv-media {
  position: relative; width: 100%; height: 11rem;
  overflow: hidden;
}
.tv-zoom { transition: transform .5s cubic-bezier(.2,.8,.2,1); }
.tv-card:hover .tv-zoom { transform: scale(1.07); }
.tv-img-overlay {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(0,0,0,0) 35%,
              rgba(6, 10, 22, 0.80) 100%);
  pointer-events: none;
}
.tv-placeholder {
  position: absolute; inset: 0;
  background: var(--tv-placeholder);
  display: flex; align-items: center; justify-content: center;
}
.tv-placeholder .tv-initial {
  font-family: 'Fraunces', serif;
  font-size: 3.2rem; font-weight: 700; color: rgba(255,255,255,.85);
  text-shadow: 0 4px 24px rgba(0,0,0,.3);
}

/* ---------- badges ---------- */
.tv-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; font-weight: 500; letter-spacing: 0.03em;
  border-radius: 8px; padding: 3px 10px;
  background: var(--tv-paper);
  border: 1px solid var(--tv-line);
  white-space: nowrap;
}
.tv-badge-onimg {
  background: rgba(6, 10, 22, 0.62);
  border-color: rgba(255,255,255,0.22);
  color: var(--tv-data);
  backdrop-filter: blur(8px);
}

/* ---------- HERO: the departure board ---------- */
.tv-hero {
  position: relative;
  background: var(--tv-ink);
  border-radius: var(--tv-radius);
  overflow: hidden;
  box-shadow: var(--tv-shadow);
  color: #fff;
}
.tv-hero::before {          /* drifting cartographic contours */
  content: ""; position: absolute; inset: -40%;
  background:
    repeating-radial-gradient(circle at 30% 40%,
      transparent 0 46px, rgba(123, 224, 200, 0.10) 46px 47px),
    repeating-radial-gradient(circle at 75% 65%,
      transparent 0 64px, rgba(255, 180, 84, 0.08) 64px 65px),
    radial-gradient(60% 80% at 70% 20%,
      rgba(15, 163, 163, 0.28), transparent 60%);
  animation: tvDrift 40s linear infinite;
  pointer-events: none;
}
@keyframes tvDrift {
  from { transform: translate3d(0,0,0) rotate(0deg); }
  to   { transform: translate3d(2%, -2%, 0) rotate(1.2deg); }
}
.tv-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; letter-spacing: 0.28em; font-weight: 600;
  color: var(--tv-data); text-transform: uppercase;
}
.tv-hero-input {
  background: rgba(255,255,255,0.96);
  border-radius: 12px;
}

/* ticker strip */
.tv-ticker {
  position: relative; overflow: hidden;
  border-top: 1px solid rgba(123, 224, 200, 0.25);
  background: rgba(6, 10, 22, 0.55);
}
.tv-ticker-track {
  display: inline-block; white-space: nowrap;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px; letter-spacing: 0.14em; font-weight: 500;
  color: var(--tv-data);
  padding: 8px 0;
  animation: tvTicker 36s linear infinite;
}
@keyframes tvTicker {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}

/* ---------- nav ---------- */
.tv-nav-item {
  border-radius: 10px;
  transition: background .2s ease, transform .2s ease;
}
.tv-nav-item:hover { transform: translateX(3px); }

/* ---------- polish ---------- */
.tv-fade-in { animation: tvFade .45s cubic-bezier(.2,.8,.2,1) both; }
@keyframes tvFade {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
.tv-shimmer {
  position: relative; overflow: hidden;
  background: rgba(127,140,170,.14);
}
.tv-shimmer::after {
  content: ""; position: absolute; inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent,
              rgba(255,255,255,.35), transparent);
  animation: tvShimmer 1.4s infinite;
}
@keyframes tvShimmer { 100% { transform: translateX(100%); } }

*:focus-visible {
  outline: 2px solid var(--tv-teal); outline-offset: 2px;
  border-radius: 6px;
}
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb {
  background: rgba(15, 163, 163, .35); border-radius: 8px;
}
@media (prefers-reduced-motion: reduce) {
  .tv-hero::before, .tv-ticker-track,
  .tv-fade-in, .tv-shimmer::after { animation: none !important; }
  .tv-card, .tv-zoom, .tv-nav-item { transition: none !important; }
}
</style>
"""


def apply_theme() -> ui.dark_mode:
    ui.add_head_html(GLOBAL_CSS)
    ui.colors(primary="#0FA3A3", secondary="#16608A", accent="#FFB454")
    from nicegui import app
    try:
        stored = app.storage.user.get("tv_dark")
    except RuntimeError:
        stored = None
    dark = ui.dark_mode(value=stored if stored is not None else None)
    return dark


def theme_toggle(dark: ui.dark_mode) -> None:
    from nicegui import app

    def flip() -> None:
        new_value = not bool(dark.value)
        dark.set_value(new_value)
        try:
            app.storage.user["tv_dark"] = new_value
        except (RuntimeError, TypeError):
            pass
        button.props(
            f"icon={'sym_r_light_mode' if new_value else 'sym_r_dark_mode'}"
        )

    button = ui.button(on_click=flip).props(
        "flat round icon=sym_r_dark_mode"
    ).tooltip("Switch between day and night mode")
