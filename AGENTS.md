# AGENTS.md — Bitvavo Trading Bot

> Cross-tool agent guidance (Copilot CLI, Copilot coding agent, OpenAI Codex, Cursor, etc.). Mirrors `.github/copilot-instructions.md` for non-VS-Code surfaces.

## Project at a glance
Python 3.13 cryptocurrency trailing-stop trading bot for Bitvavo. Windows-first. Multi-threaded. Main loop in `trailing_bot.py` (~4300-line monolith being progressively extracted into `bot/`, `core/`, `modules/`, `ai/`).

## Setup
```powershell
.\setup.bat                 # one-shot venv + deps
.\.venv\Scripts\python.exe trailing_bot.py    # run bot
.\.venv\Scripts\python.exe -m pytest tests/ -v   # run tests
.\.venv\Scripts\python.exe scripts/helpers/ai_health_check.py   # health check
```

## ⚠️ Mandatory pre-flight before ANY change
1. **Bug fix?** Read [docs/FIX_LOG.md](docs/FIX_LOG.md) first. Many issues have prior fixes you must not undo.
2. **Config change?** Edit ONLY `%LOCALAPPDATA%/BotConfig/bot_config_local.json`. Never edit `config/bot_config.json` or `config/bot_config_overrides.json` (OneDrive reverts them).
3. **Cost basis touched?** Read [/memories/repo/cost_basis_rules.md](/memories/repo/cost_basis_rules.md). `derive_cost_basis()` MUST always fetch full order history (no `opened_ts` filter). `invested_eur` is derived from history — never `buy_price * amount`.

## Hard floors
- `MAX_OPEN_TRADES >= 3` (clamped in `ai/ai_supervisor.py` and `ai/suggest_rules.py`).
- `MIN_SCORE_TO_BUY = 7.0` (locked across all roadmap phases).
- 15% EUR cash reserve maintained.

## Architecture summary
```
Bitvavo REST → bot/api.py (rate limit, cache, circuit breaker, retry)
  → core/indicators.py (SMA, RSI, MACD, ATR, Bollinger)
  → bot/signals.py + modules/signals/ (plugin providers)
  → modules/ml.py + ai/ (XGBoost, supervisor, conformal)
  → core/regime_engine.py (TRENDING_UP, RANGING, HIGH_VOLATILITY, BEARISH)
  → core/kelly_sizing.py (half-Kelly + vol parity)
  → bot/orders_impl.py (buy/sell)
  → bot/trailing.py (7-level stepped trailing, partial TP)
  → bot/trade_lifecycle.py (persist + archive)
```

| Package | Purpose |
|---------|---------|
| `bot/` | Extracted bot logic (uses `bot.shared.state` singleton) |
| `core/` | Pure computation — no I/O, no bot state |
| `modules/` | Infrastructure (config, logging, signals plugin, dashboard, metrics) |
| `ai/` | ML pipeline + supervisor |
| `scripts/` | Automation (scheduler, backup, monitoring) |

## Testing
- Framework: `pytest`. Class grouping `TestFeature` + method-per-case.
- Mock the Bitvavo client (`MagicMock`), not `safe_call`.
- Floats via `pytest.approx`. Plain `assert`, never `assertEqual`.
- Run subset: `pytest tests/test_<module>.py -v -k <keyword>`.

## Code style
- Black + isort + ruff (line length 120). Pre-commit hooks active.
- Type hints on public APIs. `@dataclass(slots=True)` for data carriers.
- Absolute imports from project root. Lazy/deferred imports inside functions to break cycles.
- Dutch log messages OK in legacy modules (preserve), English fine for new code.

## API call discipline
- Every Bitvavo call goes through `bot.api.safe_call(fn, *args, **kwargs)`.
- Returns `None` on failure → caller MUST handle.
- Never bypass for retry/cache/rate-limit reasons.

## Config access
- `from modules.config import CONFIG, load_config, save_config`.
- Coerce values: use `as_float`, `as_int`, `as_bool` from `bot.helpers`.
- Never store runtime state in `bot_config.json` — use `data/bot_state.json`.

## Persistence
- Atomic writes: tmp file + `os.replace()` (Windows-safe).
- Always `encoding='utf-8'` (or `'utf-8-sig'`).
- JSON with `file_lock` from `modules.logging_utils`.
- Append-only logs use `.jsonl` (one JSON object per line).

## Threading
- Multi-threaded, not async. `state.trades_lock` (RLock) protects all trade state.
- `ReservationManager` (in `core/`) is thread-safe.

## After ANY code change
1. Run relevant tests: `python -m pytest tests/<file> -v`.
2. Health check: `python scripts/helpers/ai_health_check.py`.
3. Commit + push with descriptive message: `fix: ...`, `feat: ...`, `chore: ...`.
4. For bug fixes: append entry to `docs/FIX_LOG.md` using the template at the bottom of that file.

## Where things live
- Trade data: `data/trade_log.json` (open) + `data/trade_archive.json` (closed).
- Bot runtime state: `data/bot_state.json`.
- Logs: `logs/`. AI logs: `ai/logs/`.
- Models: `models/`, `ai/*.json`.
- Roadmap: `docs/PORTFOLIO_ROADMAP_V2.md`.
- Fix log: `docs/FIX_LOG.md`.

## What NOT to do
- ❌ Edit `config/bot_config*.json` for settings (OneDrive reverts).
- ❌ Set `invested_eur = buy_price * amount` (must derive from order history with fees).
- ❌ Lower `MAX_OPEN_TRADES` below 3 or `MIN_SCORE_TO_BUY` below 7.0.
- ❌ Bypass `safe_call()` for direct Bitvavo client access.
- ❌ Block trading paths with metrics/telemetry — wrap in `try/except: pass`.
- ❌ Add features beyond the explicit request — follow the implementation discipline rule in `.github/copilot-instructions.md`.
