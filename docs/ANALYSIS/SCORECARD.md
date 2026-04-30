# Scorecard

Cijfers per onderdeel (1 = onbruikbaar, 10 = exemplarisch). Zie
[COMPONENT_ANALYSIS.md](COMPONENT_ANALYSIS.md) voor onderbouwing.

| # | Onderdeel | Cijfer | Trend |
|---|---|---:|---|
| 1 | Architectuur & modularisatie | 6,5 | ↗ |
| 2 | `trailing_bot.py` monoliet | 4,5 | ↗ |
| 3 | Trade execution & lifecycle (`bot/orders_impl.py`, `bot/trade_lifecycle.py`) | 8,0 | → |
| 4 | Trailing stop logica (`bot/trailing.py`, `bot/per_market_trailing.py`) | 8,5 | → |
| 5 | DCA-systeem (event-sourced, `core/dca_state.py`) | 9,0 | ↗ |
| 6 | Signal providers (`modules/signals/`) | 8,0 | ↗ |
| 7 | ML-pijplijn (XGBoost / LSTM / RL / Conformal) | 7,5 | ↗ |
| 8 | AI-supervisor & auto-tuning (`ai/`) | 7,0 | → |
| 9 | Risk management (Kelly, drawdown shield, cooldown) | 8,0 | → |
| 10 | Sync engine met Bitvavo (twee systemen!) | 6,0 | ↗ |
| 11 | Configuratie (3-laags merge) | 8,5 | → |
| 12 | Logging & error handling (`safe_call`, throttling) | 8,0 | → |
| 13 | Dashboard V2 (FastAPI + PWA) | 7,5 | → |
| 14 | Tests (807 tests / 68 files) | 8,0 | → |
| 15 | Documentatie (`docs/`) | 7,5 | → |
| 16 | Code-/repo-hygiëne (root rommel, 274 backups, 5 GB log) | 4,0 | ↘ |
| 17 | Deployment (Docker, scripts, CI) | 7,0 | → |
| 18 | Security (env, OWASP, kill-switch) | 7,0 | → |
| 19 | Grid trading (`modules/grid_trading.py`) | 7,5 | → |
| 20 | Persistentie (JSON + JSONL + atomic write) | 7,5 | → |
| 21 | Backtesting (`backtest/`, `full_backtest.py`) | 6,0 | → |
| 22 | Metrics & observability (Prometheus) | 7,0 | → |

**Gewogen totaal: 7,4 / 10**

## Top-3 sterke punten

1. **DCA event-sourcing** (`core/dca_state.py`): één bron van waarheid, robuust.
2. **Testdekking**: 807 tests, fixture-discipline, FIX_LOG verbonden aan tests.
3. **Configlaag-architectuur**: 3-laags merge die OneDrive-sync overleeft.

## Top-3 verbeterpunten (urgent)

1. **Repo-hygiëne**: 5 GB `bot_log.txt.rotation.log`, 274 backup-mappen, en 9 ad-hoc
   `_*.py`/`*.txt` bestanden in de root verwijderen → zie [CLEANUP_PLAN.md](CLEANUP_PLAN.md).
2. **Monoliet afbreken**: `trailing_bot.py` (3.758 regels) verder splitsen — main loop,
   entry-scan en lifecycle hebben al modules; integratie afmaken.
3. **Twee sync-systemen consolideren**: `modules/trading_sync.py` ↔ `bot/sync_engine.py`
   — kies één, deprecate andere (zie repo-memory `bitvavo-bot-notes.md`).
