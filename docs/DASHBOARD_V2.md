# Bitvavo Bot — Dashboard V2

A modern, mobile-first PWA for monitoring the trading bot. Replaces the
legacy Flask dashboard (port 5001) with a faster, cached FastAPI backend
and a single-page Tailwind+Alpine+Chart.js frontend (no build step).

## Architecture

```
┌─────────────────────────────────────────┐
│  Browser / iOS / Android (PWA install)  │
└──────────────────┬──────────────────────┘
                   │ HTTPS
        ┌──────────▼─────────┐
        │ Cloudflare Tunnel  │  (optional, for remote access)
        └──────────┬─────────┘
                   │
        ┌──────────▼──────────────────┐
        │ FastAPI :5002               │
        │  /api/all       (composite) │
        │  /api/portfolio             │
        │  /api/trades                │
        │  /api/ai                    │
        │  /api/memory                │
        │  /api/shadow                │
        │  /api/regime                │
        │  /api/heartbeat             │
        │  static frontend            │
        └──────────┬──────────────────┘
                   │ TTL cache (5s)
        ┌──────────▼──────────────────┐
        │ data/*.json + *.jsonl       │
        └─────────────────────────────┘
```

## Run locally

```powershell
.\scripts\start_dashboard_v2.ps1
# → http://127.0.0.1:5002
```

## Tabs

| Tab | What you see |
|-----|-------------|
| **Overzicht** | Total capital, EUR free, in positions, open count, realised PnL, fees, daily/weekly charts, open positions table |
| **Trades** | Last 50 closed trades with PnL € and % |
| **AI** | Top market insights, supervisor suggestions, model metrics |
| **Geheugen** | BotMemory facts + suggestion log |
| **Shadow rotatie** | Hypothetical capital rotations (observation only — see below) |

## Shadow capital rotation (observation only)

The bot does *not* rotate positions, but the new
[bot/shadow_rotation.py](bot/shadow_rotation.py) module logs what it
*would* have done — closed which winning-but-stale position to free a
slot for a high-score candidate. Pure observation.

After ~2 weeks of data, decide whether to enable it for real.

Run periodically:
```powershell
.\.venv\Scripts\python.exe scripts\run_shadow_rotation.py
```
Schedule it via Task Scheduler every 5–15 min, or hook into the main loop.

Analyze:
```powershell
.\.venv\Scripts\python.exe -c "from bot.shadow_rotation import analyse; import json; print(json.dumps(analyse(14), indent=2))"
```

## Mobile / remote access

See [docs/DASHBOARD_V2_TUNNEL.md](docs/DASHBOARD_V2_TUNNEL.md) for
Cloudflare Tunnel setup. Once running, open the tunnel URL on your
phone, tap *Add to Home Screen*, and the PWA installs as a fullscreen
app with offline support.

## Why no Node / build step?

- Tailwind via CDN — instant. No `npm install`, no `tailwind.config.js`.
- Alpine.js — `x-data`/`x-show`/`x-text` directly in HTML.
- Chart.js — drop-in `<canvas>` charts.
- One `index.html` + `app.js` + `styles.css` + service worker.

Total frontend: < 30 KB of code, ~0 ms build time. Edit and reload.

## Coexistence with legacy Flask dashboard

- Legacy: port **5001**
- V2:     port **5002**

Both can run simultaneously. Migrate when comfortable, then turn off the
legacy process.
