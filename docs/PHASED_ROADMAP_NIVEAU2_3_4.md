# Phased Roadmap — Niveau 2, 3, 4

> Status: PLAN  
> Generated: 2026 (autonomous Plan A delivery)  
> Owner: pick a sprint, ping Copilot, ship.

This document captures the work that was **deferred** when you asked for
"alles uit niveau 1: 2,3,4 + niveau 2 alles + niveau 3 alles + niveau 4 punt 3".
Niveau 1 (auto-recovery, weekly PnL report, regression alerter) is **shipped**
and live in the scheduler. Everything else is broken into deliverable sprints
below so you can pick them one at a time.

Each sprint includes:
- **Goal** — what success looks like
- **Estimate** — calendar days (assuming 1 dev, focused work)
- **Touch points** — files/modules likely to change
- **Risks** — what can go wrong
- **Acceptance** — how we know it's done

Pick a sprint by saying: *"Doe sprint X"*.

---

## Niveau 1 — DONE ✅
- Auto-recovery: `scripts/helpers/monitor.py` + `scripts/dashboard_v2_watchdog.py` (already existed; kept as-is)
- Weekly PnL report: [bot/weekly_report.py](bot/weekly_report.py) — Sunday 21:00, snapshot + Telegram
- Performance regression alerter: [bot/regression_alerter.py](bot/regression_alerter.py) — hourly, throttled

---

## Niveau 2 — Backtesting & Validation

### Sprint 2.1 — Backtest framework rewrite (3-4d)
- **Goal**: A reproducible offline backtest that replays Bitvavo candle data through the *real* signal/regime/Kelly stack (not the legacy `full_backtest.py`).
- **Touch points**: `backtest/walk_forward.py`, new `backtest/replay_engine.py`, `core/`, `bot/signals.py`.
- **Risks**: real bot has shared state — needs a "headless mode" without writing trade_log.
- **Acceptance**: `python -m backtest.replay_engine --market BTC-EUR --days 90` produces equity curve JSON + summary stats.

### Sprint 2.2 — A/B harness + walk-forward (3d)
- **Goal**: Compare two config presets on the same historical window and report PnL/Sharpe/MaxDD diff.
- **Touch points**: `backtest/walk_forward.py`, new `scripts/automation/ab_runner.py`.
- **Risks**: data leakage between train/validate windows.
- **Acceptance**: `ab_runner --base config_a.json --challenger config_b.json --weeks 12` writes a markdown report.

### Sprint 2.3 — Feature importance & per-market profiles (2d)
- **Goal**: Per-market XGBoost feature importance + auto-tuned signal weights.
- **Touch points**: `ai/xgb_train_enhanced.py`, new `ai/per_market_profiles.json`.
- **Risks**: overfit on low-volume markets.
- **Acceptance**: `python ai/per_market_profile_builder.py` produces profile JSON consumed by `bot.signals` at runtime.

---

## Niveau 3 — Smarter Signals

### Sprint 3.1 — Multi-timeframe confirmation (2d)
- **Goal**: Require 5m + 15m + 1h alignment before entry on weak 1m signals.
- **Touch points**: `modules/signals/`, new `modules/signals/mtf_confirm.py`.
- **Acceptance**: New provider in `PROVIDERS` list; tests in `tests/test_mtf_confirm.py`.

### Sprint 3.2 — Order book imbalance (2d)
- **Goal**: Use Bitvavo L2 orderbook (bid/ask depth ratio) as scoring boost.
- **Touch points**: `core/orderbook.py` (extend), `modules/signals/orderbook_imbalance.py` (new).
- **Risks**: rate-limit pressure on `getBook`.
- **Acceptance**: Imbalance >= configurable threshold adds N points to score.

### Sprint 3.3 — On-chain & sentiment (3d, requires API keys)
- **Goal**: Pull Glassnode/Santiment metrics + Twitter sentiment, gate entries.
- **Touch points**: new `modules/external/onchain.py`, `modules/external/sentiment.py`.
- **Risks**: API costs; data freshness.
- **Acceptance**: Sentiment score is part of the signal pack `details`.

### Sprint 3.4 — Cross-pair correlation gate (2d)
- **Goal**: Avoid opening 3 highly-correlated alts when BTC dumps.
- **Touch points**: new `core/correlation.py`, `bot/signals.py` (entry gate).
- **Acceptance**: At most K positions in the same correlation cluster.

---

## Niveau 4 — Adaptive Intelligence

### Sprint 4.1 — RL agent for trailing-stop tuning (2-3w)
- **Goal**: Replace fixed trailing levels with a small RL policy (PPO or DQN).
- **Touch points**: new `ai/rl/trailing_agent.py`, `bot/trailing.py` (gated rollout).
- **Risks**: training stability; needs realistic simulator.
- **Acceptance**: Shadow-mode RL beats baseline trailing on backtest by ≥5% PnL with similar Sharpe.

### Sprint 4.2 — Portfolio-level Kelly + risk parity (2-3d) ← *user picked this one*
- **Goal**: Allocate capital across markets via mean-variance + half-Kelly *jointly*, not per-trade.
- **Touch points**: `core/kelly_sizing.py`, new `core/portfolio_optimizer.py`, `bot/orders_impl.py`.
- **Risks**: covariance estimation noise on small trade samples.
- **Acceptance**:
  - New `compute_portfolio_weights(open_trades, candidates)` returns target allocation.
  - Buy size respects portfolio weight × Kelly cap.
  - Dashboard shows current vs target weights.
  - Unit tests with synthetic returns.

---

## How to execute a sprint
1. Open this file, pick a sprint.
2. Tell Copilot: *"Doe sprint X.Y"*.
3. Copilot will:
   - Read this entry + relevant code
   - Confirm scope (or push back if too big)
   - Implement + test + commit + push + Telegram
   - Add a FIX_LOG entry
   - Mark the sprint ✅ in this doc

## Why this exists
You asked for ~14 features at once. That's 2-4 months of solid work. Splitting
it gives you:
- **Visible progress** every sprint (1-3 days each).
- **Rollback safety** — each sprint is independent.
- **Testable changes** — a 14-feature mega-PR is impossible to QA.
- **Optionality** — you may decide RL is not worth 3 weeks once you see backtest results.
