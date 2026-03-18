# Copilot Instructions — Bitvavo Trading Bot

## Project Overview

A Python-based cryptocurrency trailing-stop trading bot for the Bitvavo exchange. The main entry point is `trailing_bot.py` (~4300 lines monolith). The codebase is progressively being refactored into extracted modules under `bot/`, `core/`, and `modules/`.

**Python version**: 3.13 | **Platform**: Windows-first (OneDrive paths, thread-based timeouts)  
**Key dependencies**: `python_bitvavo_api`, `numpy`, `pandas`, `scikit-learn`, `xgboost`, `Flask` + `Flask-SocketIO` (dashboard), `tinydb`, `schedule`, `python-dotenv`, `pytest`

### Architecture & Data Flow

```
Bitvavo REST API → bot/api.py (rate limit, cache, circuit breaker)
    → core/indicators.py (SMA, RSI, MACD, ATR, Bollinger)
    → bot/signals.py + modules/signals/ (signal scoring, plugin providers)
    → modules/ml.py (XGBoost + optional LSTM + RL ensemble gating)
    → core/regime_engine.py (4 regimes: TRENDING_UP, RANGING, HIGH_VOLATILITY, BEARISH)
    → core/kelly_sizing.py (half-Kelly + volatility parity position sizing)
    → bot/orders_impl.py (buy/sell execution)
    → bot/trailing.py (7-level stepped trailing stops, partial TP, adaptive exit)
    → bot/trade_lifecycle.py (persistence, archival)
```

| Package | Purpose |
|---------|---------|
| `bot/` | Extracted bot logic (API wrapper, signals, trailing, trade lifecycle, portfolio, sync) |
| `core/` | Pure computation — no bot state (indicators, regime engine, Kelly sizing, orderbook) |
| `modules/` | Infrastructure (config, logging, trading execution, signals plugin, dashboard, metrics) |
| `ai/` | ML pipeline (XGBoost train/retrain, AI supervisor daemon, market analysis, RL agent) |
| `scripts/` | Automation (scheduler, backup, monitoring, startup helpers) |

The **main loop** (`bot_loop()` in `trailing_bot.py`) runs every ~25s: hot-reloads config → syncs with exchange → scans markets for entries → manages open trades (trailing stops, DCA, partial TP) → persists state.

### Dashboard & Deployment
- **Flask dashboard** on port 5001 (`tools/dashboard_flask/`) — real-time portfolio, trades, AI, analytics
- **Docker**: multi-stage build (`python:3.11-slim`), `docker-compose.yml` with persistent volumes for `data/`, `logs/`, `config/`
- **CI**: `.github/workflows/python-tests.yml` (Python 3.11 + 3.12), `release.yml` (version tags → GitHub Release ZIP)

---

## 1. Config Access Pattern

Config lives in `config/bot_config.json` and is loaded by `modules/config.py`.

```python
from modules.config import load_config, save_config, CONFIG
```

- `load_config()` → returns a plain `dict` merged from 3 layers (last wins):
  1. `config/bot_config.json` (base defaults, synced via OneDrive — **DO NOT edit for settings changes**)
  2. `config/bot_config_overrides.json` (legacy overrides, also on OneDrive — **DO NOT edit for settings changes**)
  3. **`%LOCALAPPDATA%/BotConfig/bot_config_local.json`** (machine-local overrides, **OUTSIDE OneDrive** — **THIS is where ALL config changes go**)
- **Layer 3 wins over everything.** OneDrive regularly reverts layers 1 and 2. Layer 3 is immune to OneDrive sync.
- Runtime state keys (e.g. `LAST_REINVEST_TS`) are stored separately in `data/bot_state.json` and merged in at load time.
- `CONFIG` is a **module-level dict** exported from `modules/config.py` — many modules import it directly.
- `save_config()` writes atomically via tmp+replace, strips runtime state keys, and auto-syncs the overrides file.
- Config keys are **UPPER_SNAKE_CASE** strings. Values are accessed via `dict.get()` with defaults:
  ```python
  max_retries = int(CONFIG.get('SAFE_CALL_MAX_RETRIES', 5))
  ```
- Config is validated against a schema (`modules/config_schema.py`) at load time; errors are logged but don't block startup.

### CRITICAL: Where to change config values
**ALWAYS edit `%LOCALAPPDATA%/BotConfig/bot_config_local.json`** (typically `C:\Users\Sedeg\AppData\Local\BotConfig\bot_config_local.json`).
- This file loads LAST and wins over all other config files.
- It is OUTSIDE OneDrive and will NEVER be reverted by sync.
- NEVER edit `config/bot_config.json` or `config/bot_config_overrides.json` for settings changes — OneDrive will revert them.
- To read the local config path from code: `modules.config.LOCAL_OVERRIDE_PATH`
- To edit from PowerShell:
  ```powershell
  $localPath = Join-Path $env:LOCALAPPDATA "BotConfig\bot_config_local.json"
  notepad $localPath
  ```

### Gotcha
- Never store runtime state (timestamps, circuit-breaker flags) in `bot_config.json` — use the `RUNTIME_STATE_KEYS` set or `data/bot_state.json`.
- Config is a **mutable shared dict** — modules hold a reference to the same object. Changes are visible everywhere.

---

## 2. Shared State Pattern (Singleton)

`bot/shared.py` defines a `_SharedState` class with a module-level singleton `state`.

```python
from bot.shared import state

state.open_trades      # Dict[str, Any] — market→trade dict
state.CONFIG           # the config dict
state.bitvavo          # Bitvavo API client
state.log(...)         # log function
state.trades_lock      # threading.RLock for trade state
```

- `trailing_bot.py` populates the singleton at startup via `init(**kwargs)`.
- All attributes have **safe defaults** (empty dicts, no-op functions) so import-time access before init doesn't crash.
- Extracted `bot/` modules (trade_lifecycle, trailing, signals, portfolio, etc.) access all shared state via `state` — **never import globals from trailing_bot.py directly**.
- Function references (e.g. `state.save_trades_fn`, `state.get_current_price`) are injected at init, not imported.

### Gotcha
- Always acquire `state.trades_lock` (RLock) before reading/writing `state.open_trades`, `state.closed_trades`, or `state.market_profits`.
- Some modules use a lazy import pattern: `def _get_state(): from bot.shared import state; return state` to avoid circular imports.

---

## 3. Error Handling Convention

### API calls: `safe_call()` wrapper
All Bitvavo API calls go through `bot.api.safe_call(func, *args, **kwargs)`:
- Automatic **retry with exponential backoff** (configurable max retries, base delay)
- **Circuit breaker** per endpoint (opens after N failures, auto-resets after timeout)
- **Rate limiting** with per-endpoint token buckets
- **Response caching** with configurable TTLs per endpoint
- **Hard 10s timeout** per API call (thread-based, Windows-compatible)
- Transient errors (rate limit, timeout, DNS, connection) are retried; others fail immediately
- Error logging is **suppressed/throttled** to avoid log spam for repeated transient failures
- Returns `None` on total failure (callers must handle `None`)

### General error handling
- Wrap risky operations in `try/except Exception` — **never let an exception crash the bot**.
- Log errors via `log(msg, level='error')` from `modules.logging_utils`.
- Use throttled logging (`_log_throttled(key, msg, interval)`) for high-frequency code paths.
- Log messages are often in **Dutch** (this is intentional — the developer is Dutch).

---

## 4. Trade Data Structure

Trades are plain `dict` objects stored in `state.open_trades[market_name]` with ~30 fields. Key groups:

- **Core**: `buy_price`, `amount`, `invested_eur`, `initial_invested_eur` (immutable ground truth), `total_invested_eur`, `highest_price` (trailing high-water mark), `partial_tp_returned_eur`
- **DCA**: `dca_buys`, `dca_events`, `dca_drop_pct`, `dca_amount_eur`, `dca_max`
- **Timestamps**: `opened_ts` (`time.time()`), `timestamp`
- **Trailing**: `trailing_activation_pct`, `base_trailing_pct`, `cost_buffer_pct`
- **AI metadata at entry**: `score`, `volatility_at_entry`, `opened_regime` (`'defensive'|'aggressive'|'unknown'`), `rsi_at_entry`, `macd_at_entry`, `volume_24h_eur`
- **Close info**: `sell_price`, `profit`, `profit_pct`, `reason` (`'trailing_stop'|'stop_loss'|'saldo_error'|...`)

### Gotcha
- **Cost basis**: use `initial_invested_eur` (immutable). Use `derive_cost_basis(trade)` helper for reliable value. Never rely on `invested_eur` (mutable).
- Persisted to `data/trade_log.json`, archived to `data/trade_archive.json`. Save is **debounced** (min 2s).

---

## 5. Signal Provider Pattern (Plugin System)

Signal providers live in `modules/signals/` and follow a Protocol-based plugin pattern.

### Contract
```python
# modules/signals/base.py
class SignalProvider(Protocol):
    def __call__(self, ctx: SignalContext) -> SignalResult: ...

@dataclass(slots=True)
class SignalContext:
    market: str
    candles_1m: Sequence[Sequence[Any]]
    closes_1m: Sequence[float]
    highs_1m: Sequence[float]
    lows_1m: Sequence[float]
    volumes_1m: Sequence[float]
    config: MutableMapping[str, Any]

@dataclass(slots=True)
class SignalResult:
    name: str
    score: float = 0.0
    active: bool = False
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
```

### Registration
Providers are registered in `modules/signals/__init__.py` as a simple list:
```python
PROVIDERS: List[SignalProvider] = [
    range_signal,
    volatility_breakout_signal,
    mean_reversion_signal,
    mean_reversion_scalper_signal,
    ta_confirmation_signal,
]
```

Call `evaluate_signal_pack(ctx)` to run all providers and get a `SignalPackResult` with `total_score` and per-provider results.

### Adding a new signal provider
1. Create `modules/signals/my_signal.py`
2. Implement a function matching `SignalProvider` protocol (takes `SignalContext`, returns `SignalResult`)
3. Use `_safe_cfg_float/int/bool` from `.base` for config access
4. Add to `PROVIDERS` list in `modules/signals/__init__.py`
5. Use relative imports within the signals package (e.g. `from .base import ...`)

---

## 6. Testing Conventions

- **Framework**: `pytest` (9.x)
- **Config**: `tests/conftest.py` adds project root to `sys.path` — that's it, no shared fixtures.
- **Per-test setup**: Tests use `@pytest.fixture(autouse=True)` for module initialization (e.g. calling `_api.init(mock_bv, cfg)` and clearing caches).
- **Mocking**: `unittest.mock.MagicMock` and `patch` are the standard. Mock the Bitvavo client, not the wrapper functions.
- **Test style**: Class-based grouping (`class TestSpreadOk:`) with method-per-case. Some tests use plain functions.
- **Assertions**: `pytest.approx()` for floats, direct `assert` statements (no `assertEqual`).
- **Naming**: Files are `test_<module>.py`, classes are `Test<Feature>`, methods are `test_<scenario>`.
- **Helper factories**: Tests define local helpers like `_make_candles(closes)` for test data — no shared fixture library.

### Running tests
```powershell
pytest tests/ -v
```

---

## 7. Import Conventions

### Absolute imports from project root
All imports use **absolute paths from the project root** — no relative imports except within packages.

```python
# Correct patterns:
from modules.config import load_config, CONFIG
from modules.logging_utils import log, file_lock, locked_write_json
from bot.helpers import as_float, as_int, as_bool
from core.indicators import close_prices, sma, ema, rsi, macd
from core.reservation_manager import ReservationManager
import bot.api as _api
import bot.signals as _signals

# Within a package (e.g. modules/signals/), relative imports are used:
from .base import SignalContext, SignalResult
from .indicators import atr, rolling_vwap
```

### Import naming conventions
- `bot.api` is imported as `_api` (underscore prefix = module alias convention)
- `bot.performance` as `_perf`, `bot.signals` as `_signals`, `bot.trailing` as `_trail`
- Lazy/deferred imports inside functions to avoid circular dependencies:
  ```python
  def some_function():
      from bot.portfolio import analyse_trades  # deferred to avoid circular
  ```

### Package structure
| Package | Purpose |
|---------|---------|
| `bot/` | Extracted bot logic (API wrapper, signals, trailing, trade lifecycle, portfolio) |
| `core/` | Pure computation (indicators, regime engine, Kelly sizing, order book analysis) |
| `modules/` | Infrastructure (config, logging, trading execution, signals plugin, metrics, storage) |
| `ai/` | ML/AI components (XGBoost training, market analysis, auto-retrain, supervisor) |
| `scripts/` | Automation scripts (scheduler, backup, monitoring, startup helpers) |

---

## 8. Linting & Formatting

Pre-commit hooks are configured in `.pre-commit-config.yaml`:

| Tool | Config |
|------|--------|
| **Black** | `--line-length=120` |
| **isort** | `--profile=black --line-length=120` |
| **flake8** | `--max-line-length=120 --extend-ignore=E203,E501,W503` |
| **mypy** | `--ignore-missing-imports --no-strict-optional` (excludes tests/) |
| **bandit** | Security checks, `--skip=B101` (assert OK) |

Also: trailing-whitespace, end-of-file-fixer, check-yaml, check-json, detect-private-key.

### Key style rules
- **Line length**: 120 characters
- **Quotes**: No enforced style (mix of single and double quotes exists)
- **Type hints**: Used extensively (`from __future__ import annotations` at top of extracted modules)
- **Dataclasses**: Use `@dataclass(slots=True)` for data carriers
- **Docstrings**: Module-level docstrings present. Function docstrings are sparse — brief one-liners when present.

---

## 9. File I/O Conventions

- **Atomic writes**: Always use tmp file + `os.replace()` pattern for JSON writes to prevent corruption.
- **Encoding**: Always specify `encoding='utf-8'` (or `'utf-8-sig'` for files that may have BOM).
- **File locking**: Use `file_lock` (threading.Lock) from `modules.logging_utils` for config file operations.
- **JSON persistence**: Use `write_json_locked()` or `json_write_compat()` from shared state for trade data.
- **JSONL format**: Append-only logs use `.jsonl` (one JSON object per line) — e.g. `data/trade_pnl_history.jsonl`.
- **Path resolution**: Use `pathlib.Path` with `PROJECT_ROOT` for relative-to-project paths.

---

## 10. Threading Model

- The bot is **multi-threaded** (not async). Main loop in `trailing_bot.py`, background threads for WebSocket, scheduling, health checks.
- **RLock** (`state.trades_lock`) protects all trade state mutations.
- Debouncing with timestamps + locks prevents rapid duplicate operations.
- `ReservationManager` (core) handles market slot reservations with expiry (thread-safe).

---

## 11. Key Gotchas & Patterns

1. **None-safety**: API calls via `safe_call()` return `None` on failure. Always check: `if result is None: return`.
2. **Dutch log messages**: Many log strings are in Dutch — preserve this convention in existing modules but English is fine for new code.
3. **Config value coercion**: Use `as_float()`, `as_int()`, `as_bool()` from `bot.helpers` — never trust config values to be the right type.
4. **Circular import avoidance**: Use deferred imports inside functions, not at module top level, when `bot/` ↔ `modules/` cross-references exist.
5. **OneDrive sync conflicts**: OneDrive frequently reverts `config/bot_config.json` and `config/bot_config_overrides.json` to older versions. **ALL config changes MUST go to `%LOCALAPPDATA%/BotConfig/bot_config_local.json`** which is outside OneDrive and loads last (wins over everything). Never edit the OneDrive config files for settings changes. Never remove the 3-layer merge logic in `modules/config.py`.
6. **Monolith reference**: `trailing_bot.py` is the legacy monolith (~4300 lines). New code should go into `bot/`, `core/`, or `modules/` packages, not into trailing_bot.py.
7. **Trade cost basis**: Always use `initial_invested_eur` (immutable) as ground truth, not `invested_eur` (mutable).
8. **Metrics are non-blocking**: Metrics emission must never raise or block trading operations — wrap in `try/except: pass`.
9. **Startup order matters**: `bot.api.init()` must be called before any API function. `bot.shared.init()` must be called before any extracted module accesses state.
10. **Windows-first**: The bot runs on Windows. Use `os.replace()` not `os.rename()`. Use thread-based timeouts, not signals. Paths may contain spaces (OneDrive).
11. **GitHub push on bug fixes**: After fixing any bug (code changes in `.py` files), always commit and push the changes to the GitHub repository. Use a descriptive commit message like `fix: <short description>`. This ensures the production bot stays in sync with the repo and fixes are not lost.
12. **MAX_OPEN_TRADES minimum is 3**: The `MAX_OPEN_TRADES` config value must NEVER be set below 3. This is enforced in `ai/ai_supervisor.py` (clamped to 3) and `ai/suggest_rules.py` (floor of 3 in all suggestions). When changing MAX_OPEN_TRADES or any other config value, **edit ONLY `%LOCALAPPDATA%/BotConfig/bot_config_local.json`** — this file loads last and wins over everything. Do NOT edit `config/bot_config.json` or `config/bot_config_overrides.json` (OneDrive reverts them). The AI suggest rules use `max(3, ...)` as floor, never `max(2, ...)`.
