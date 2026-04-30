# Component Analyse — Detail

Per onderdeel: cijfer, waarom, en concrete verbeteracties.

---

## 1. Architectuur & modularisatie — **6,5 / 10**

**Goed**: Heldere scheiding `bot/` (botlogica), `core/` (pure berekeningen),
`modules/` (infrastructuur), `ai/` (ML). 42 + 26 + 53 + 13 = 134 Python-modules.
**Slecht**: `trailing_bot.py` is nog steeds 3.758 regels en bevat de main loop,
entry scan, en orchestratie. Dubbele "sync engines". Sommige cross-imports
gebruiken lazy-import als workaround voor circulaire imports.

**Verbeter**:
- Migreer resterende main-loop logica naar `bot/main_loop.py` (bestaat al, maar
  dunner dan zou moeten).
- Definieer een `bot/__init__.py` API-contract (exporteer alleen wat extern nodig is).
- Documenteer `core/` als "pure / no-side-effects" (lint via mypy of import-linter).

---

## 2. `trailing_bot.py` monoliet — **4,5 / 10**

**Goed**: Werkt al lang in productie, sync overleeft veel edge cases.
**Slecht**: 3.758 regels in één bestand. Test-isolatie is moeilijk; nieuwe
features riskeren regressie. README-instructies zeggen al "new code goes into
`bot/`/`core/`/`modules/`" — handhaving ontbreekt.

**Verbeter**:
- Splits in: `entry_scanner.py`, `loop_orchestrator.py`, `state_init.py`,
  `signal_runner.py`, `trade_manager_loop.py`.
- Voeg `pytest -k "monolith"` integratie-test toe op blokken vóór elke split.
- Doel: < 500 regels in `trailing_bot.py` (alleen entry-point + bootstrap).

---

## 3. Trade execution & lifecycle — **8,0 / 10**

**Goed**: `bot/orders_impl.py` + `bot/trade_lifecycle.py` + `bot/close_trade.py`
maken een nette pipeline. `derive_cost_basis()` is robuust (zie FIX_LOG #001).
**Slecht**: 30 velden per trade-dict zonder formele schema. Geen TypedDict.

**Verbeter**:
- Definieer `TradeRecord(TypedDict)` of `@dataclass`.
- Migreer `state.open_trades` naar typed model met validators.

---

## 4. Trailing stop logica — **8,5 / 10**

**Goed**: 7-staps stepped trailing, partial TP, adaptive exit, per-market
configuratie. Test-coverage in `test_bot_trailing.py`, `test_adaptive_score.py`.

**Verbeter**:
- Voeg property-based tests toe (Hypothesis) op `update_trailing_stop()`.

---

## 5. DCA-systeem — **9,0 / 10**

**Goed**: Event-sourced via `core/dca_state.py` (FIX #007). Single source of
truth. Voorkomt 6+ historische bugs. Hersteltool `scripts/repair_dca_events.py`.

**Verbeter**:
- Klein: snapshot-export voor audits (json schema).

---

## 6. Signal providers — **8,0 / 10**

**Goed**: Plugin-architectuur met `Protocol`/`@dataclass(slots=True)`.
5 providers actief. Tests per provider.

**Verbeter**:
- Auto-discovery via entry_points zou hardcoded `PROVIDERS` lijst vervangen.
- Per-provider weights configureerbaar via config.

---

## 7. ML-pijplijn (XGBoost / LSTM / RL / Conformal) — **7,5 / 10**

**Goed**: XGBoost basis + enhanced model, conformal prediction voor confidence,
LSTM optioneel, RL ensemble gating. `auto_retrain.py` schedulet retrain.
**Slecht**: Twee modelbestanden (`ai_xgb_model.json` + `_enhanced.json`) zonder
duidelijke selectielogica gedocumenteerd. Drift monitor nog niet automatisch
met retrain gekoppeld in alle gevallen.

**Verbeter**:
- Eén `model_registry.py` als bron van waarheid voor "actief" model.
- Drift-trigger → auto-retrain pipeline.

---

## 8. AI-supervisor & auto-tuning — **7,0 / 10**

**Goed**: `ai/ai_supervisor.py` past parameters dynamisch aan binnen veilige
clamps (MAX_OPEN_TRADES ≥ 3, MIN_SCORE_TO_BUY = 7.0).
**Slecht**: Veel suggestion-files in `ai/` zonder rotatie/archief.

**Verbeter**:
- Archiveer historische `ai_market_suggestions.json` per dag.
- Voeg human-in-the-loop dashboard pane toe (zie ai/process_ai_market_suggestions.py).

---

## 9. Risk management — **8,0 / 10**

**Goed**: Half-Kelly + volatility parity, BTC drawdown shield, post-loss
cooldown, decorrelation, reservation manager voor concurrency.
**Slecht**: Geen scenario-stresstest.

**Verbeter**:
- Monte-Carlo stresstest in `backtest/`.

---

## 10. Sync engine met Bitvavo — **6,0 / 10**

**Slecht**: Twee parallelle systemen — `modules/trading_sync.py` (background
thread) en `bot/sync_engine.py` (main loop + shutdown). Verschillende
debug-files, gedeeltelijk overlappende verantwoordelijkheden.

**Verbeter**:
- Beslis: behoud `bot/sync_engine.py` (modern, in main loop), markeer
  `modules/trading_sync.py` als deprecated en migreer functionaliteit.
- Eén `sync_debug.json` met versionering.

---

## 11. Configuratie (3-laags merge) — **8,5 / 10**

**Goed**: 3-laagse merge (`bot_config.json` < overrides < `%LOCALAPPDATA%`).
Gedocumenteerd, schema-validatie. OneDrive-veilig.

**Verbeter**:
- Voeg dry-run validator script toe: `python -m modules.config --validate`.

---

## 12. Logging & error handling — **8,0 / 10**

**Goed**: `safe_call()` met retry/circuit breaker/cache/timeouts. Throttled
logging tegen spam.
**Slecht**: Mix van Engels/Nederlands maakt log-grep lastig (bewust gekozen).
Rotation log eats disk (5 GB).

**Verbeter**:
- Zet logrotate-grootte op max ~50 MB per file, max 5 keep.
- Standaardiseer log-niveau-keys (info/warn/error/debug).

---

## 13. Dashboard V2 — **7,5 / 10**

**Goed**: FastAPI + PWA, real-time, Prometheus `/metrics`, kill-switch.
Watchdog draait apart.
**Slecht**: Veel `tools/dashboard*` historische versies.

**Verbeter**:
- Verwijder oude `tools/dashboard/` als V2 stabiel is.

---

## 14. Tests — **8,0 / 10**

**Goed**: 807 tests / 68 files. FIX_LOG koppelt regressies aan testen.
**Slecht**: Geen coverage-rapport in CI? Geen mutatietests.

**Verbeter**:
- Voeg `pytest --cov=bot --cov=core --cov=modules --cov-report=xml` toe in CI.
- Coverage badge in README.

---

## 15. Documentatie — **7,5 / 10**

**Goed**: 23 docs (architecture, strategy, troubleshooting, fix log, roadmap).
**Slecht**: Veel `claude_opus_*_prompt.md` files lijken eenmalige prompts.

**Verbeter**:
- Verplaats `claude_opus_*` naar `docs/archive/`.
- Index `docs/README.md` aanmaken.

---

## 16. Code-/repo-hygiëne — **4,0 / 10** (urgent)

**Slecht**:
- `logs/bot_log.txt.rotation.log` = **5.099 MB**.
- 274 backup-mappen in `backups/`.
- Root: `_align_enj.py`, `_backtest_atr_trailing.py`, `_diag_btceth.py`,
  `_diag_out.txt`, `testout.txt`, `param_log.txt`, `start_automated.ps1.old`,
  `start_bot.log`, `trade_features.csv`.
- 8 `scripts/_*.py` ad-hoc onderzoeksscripts (oud, nu mogelijk irrelevant).

Zie [CLEANUP_PLAN.md](CLEANUP_PLAN.md).

---

## 17. Deployment — **7,0 / 10**

**Goed**: Multi-stage Dockerfile, docker-compose met volumes, GitHub Actions CI.
**Slecht**: Veel `start_*.bat`/`.ps1` varianten in root + scripts/startup/.

**Verbeter**:
- Eén canonical `start_automated.ps1`, verwijder `.old` versie.

---

## 18. Security — **7,0 / 10**

**Goed**: `.env` met `python-dotenv`, kill-switch endpoint, bandit in pre-commit.
**Slecht**: `bot_config_local.SAMPLE.json` mag geen secret bevatten (verifieer).

**Verbeter**:
- Pre-commit hook `detect-secrets`.

---

## 19. Grid trading — **7,5 / 10**

**Goed**: Recente FIX #021 (juiste Bitvavo API field names). Tests aanwezig.
**Slecht**: Twee state-locaties (OneDrive + LocalAppData) — fragile maar
gedocumenteerd in repo memory.

**Verbeter**:
- Migreer state volledig naar LocalAppData (consistent met config).

---

## 20. Persistentie — **7,5 / 10**

**Goed**: Atomic writes (tmp + os.replace), JSONL voor append-only logs,
file-locks via threading.Lock.
**Slecht**: Mix van JSON, JSONL en TinyDB zonder duidelijke heuristiek.

**Verbeter**:
- Documenteer "wanneer JSON / JSONL / TinyDB" in `docs/ARCHITECTURE.md`.

---

## 21. Backtesting — **6,0 / 10**

**Goed**: `backtest/walk_forward.py`, `full_backtest.py`, `_backtest_atr_trailing.py`.
**Slecht**: Drie ingangen (root + folder + ad-hoc), geen unified CLI.

**Verbeter**:
- `python -m backtest <strategy>` als unified CLI.
- Verwijder `_backtest_atr_trailing.py` uit root (verplaats naar `backtest/experiments/`).

---

## 22. Metrics & observability — **7,0 / 10**

**Goed**: Prometheus endpoint, perf_monitor, advanced_metrics module.
**Slecht**: Geen Grafana-dashboards in repo (alleen `docs/grafana/` als referentie).

**Verbeter**:
- Voeg `docs/grafana/dashboards/*.json` toe voor import.
