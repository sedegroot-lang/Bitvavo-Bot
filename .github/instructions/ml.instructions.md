---
applyTo: "ai/**/*.py"
description: "ML/AI pipeline conventions — XGBoost, supervisor, market analysis"
---

# ai/ package conventions

## Files of record
- `ai_xgb_model.json` / `ai_xgb_model_enhanced.json` — trained XGBoost models (do not edit by hand).
- `ai_model_metrics.json` / `ai_model_metrics_enhanced.json` — last training metrics.
- `model_registry.py` — single source of truth for loading models. Always go through it; never `xgb.Booster.load_model(...)` ad-hoc.
- `ai_market_suggestions.json` — output of `market_analysis.py`, consumed by `process_ai_market_suggestions.py`.

## Suggestion floors
- `MAX_OPEN_TRADES` floor is **3**. `ai/suggest_rules.py` and `ai/ai_supervisor.py` both clamp via `max(3, value)`. Never lower.
- `MIN_SCORE_TO_BUY` is **locked at 7.0** for all phases. Do not alter unless the user explicitly requests.

## Training & retrain
- `xgb_train_enhanced.py` is the canonical trainer. `auto_retrain.py` schedules retrains; `ml_scheduler.py` orchestrates.
- Walk-forward validation lives in `xgb_walk_forward.py` and `backtest/walk_forward.py`. Use these — never train+test on the same window.

## Conformal prediction
- `conformal.py` produces `conformal_signalfilter.json` and `conformal_supervisor.json` with metadata sidecars (`*_meta.json`). Both files must always be updated together (atomic).

## AI Supervisor
- `ai_supervisor.py` runs as a daemon, observes bot state, and may suggest config changes via `suggest_rules.py`.
- Suggestions are written to `auto_updates/applied/` or `auto_updates/failed/`. Never apply config changes directly from supervisor — always go via the suggest → review → apply pipeline.

## Logging
- Use the standard project logger via `from modules.logging_utils import log`.
- AI logs go to `ai/logs/` — keep size bounded; rotate via the existing helper.

## Tests
- Place ML tests in `tests/test_ai_*.py`. Mock model loading; never load the real trained model in CI.
