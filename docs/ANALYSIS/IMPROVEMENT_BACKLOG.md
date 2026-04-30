# Improvement Backlog (geprioriteerd)

| # | Prio | Onderdeel | Actie | Effort |
|---|---|---|---|---|
| 1 | P0 | Repo-hygiëne | Voer [CLEANUP_PLAN.md](CLEANUP_PLAN.md) sectie A uit | XS |
| 2 | P0 | Logging | Logrotate cap op 50 MB / 5 files; verwijder rotation-of-rotation log | S |
| 3 | P0 | `.gitignore` | Aanvullen volgens CLEANUP_PLAN sectie E | XS |
| 4 | P1 | Sync engine | Consolideer `modules/trading_sync.py` ↔ `bot/sync_engine.py` | M |
| 5 | P1 | Monoliet | Verder splitsen `trailing_bot.py` → < 500 regels bootstrap | L |
| 6 | P1 | ML-registry | Eén actief model via `model_registry.py`, drift→retrain trigger | M |
| 7 | P2 | Trade-schema | `TypedDict`/`@dataclass` voor TradeRecord | M |
| 8 | P2 | CI coverage | `pytest --cov` + Codecov badge | S |
| 9 | P2 | Backups | Behoud laatste 14 dagen, oudere → maandelijkse zip | S |
| 10 | P2 | Docs | `docs/archive/` voor eenmalige prompts + `docs/README.md` index | S |
| 11 | P3 | Tests | Hypothesis property-tests voor trailing stop | M |
| 12 | P3 | Backtesting | Unified `python -m backtest` CLI | M |
| 13 | P3 | Grid state | Migreer state naar enkel LocalAppData (zoals config) | M |
| 14 | P3 | Config | `python -m modules.config --validate` dry-run script | S |
| 15 | P3 | Grafana | Voeg dashboard JSONs toe in `docs/grafana/dashboards/` | S |
| 16 | P3 | Security | Pre-commit `detect-secrets` hook | S |
| 17 | P3 | Signals | Per-provider weights via config; entry_points autodiscovery | M |
| 18 | P3 | AI suggestions | Dagelijkse archivering van `ai_market_suggestions.json` | XS |

## Legenda
- **Prio**: P0 = direct, P1 = volgende sprint, P2 = backlog, P3 = nice-to-have
- **Effort**: XS < 30 min, S < 2 h, M < 1 dag, L > 1 dag

## Architectuur-noord-ster

> Doel binnen 2 maanden: `trailing_bot.py` < 500 regels (alleen bootstrap),
> alle business logic in `bot/`/`core/`/`modules/`, één sync-systeem,
> coverage > 80 %, geen ad-hoc scripts in root.
