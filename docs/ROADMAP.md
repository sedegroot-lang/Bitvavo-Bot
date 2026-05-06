# 🗺️ MASTER ROADMAP — Bitvavo Bot

> **Live status tracker.** Updated automatically by Copilot per sprint.  
> Last update: 2026-05-06 (Plan B execution — backtest + portfolio Kelly)

## Legend
- ✅ DONE — shipped, tested, committed
- 🟡 IN PROGRESS — code in flight, may have known gaps
- ⏳ PLANNED — sprint defined, not started
- 🚫 BLOCKED — needs external resource (paid API, weeks of compute, etc.)
- 📦 ALREADY EXISTS — discovered during sprint scoping

---

## Niveau 1 — Operations & Reliability

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1.1 | Auto-recovery for bot/dashboard | 📦 EXISTS | `scripts/helpers/monitor.py` + `scripts/dashboard_v2_watchdog.py` |
| 1.2 | Weekly PnL report (Sunday 21:00) | ✅ DONE (#089) | [bot/weekly_report.py](bot/weekly_report.py) |
| 1.3 | Performance regression alerter (hourly) | ✅ DONE (#089) | [bot/regression_alerter.py](bot/regression_alerter.py) |
| 1.4 | Scheduler hooks for 1.2 + 1.3 | ✅ DONE (#089) | [scripts/automation/scheduler.py](scripts/automation/scheduler.py) |

## Niveau 2 — Backtesting & Validation

| # | Item | Status | Notes |
|---|------|--------|-------|
| 2.1 | Walk-forward (closed trades replay) | 📦 EXISTS | [backtest/walk_forward.py](backtest/walk_forward.py) |
| 2.2 | **Candle replay engine through signal pack** | ✅ DONE (#090) | [backtest/replay_engine.py](backtest/replay_engine.py) — new |
| 2.3 | A/B harness (config A vs B) | ✅ DONE (#090) | [backtest/ab_runner.py](backtest/ab_runner.py) |
| 2.4 | Per-market XGBoost feature importance | 📦 EXISTS | `ai/xgb_train_enhanced.py` outputs gain/cover already |
| 2.5 | Per-market signal weight profiles | ⏳ PLANNED | Sprint 2-3d, requires 2.2 baseline |

## Niveau 3 — Smarter Signals

| # | Item | Status | Notes |
|---|------|--------|-------|
| 3.1 | Multi-timeframe confluence | 📦 EXISTS | [core/mtf_confluence.py](core/mtf_confluence.py) |
| 3.2 | Order book imbalance signal | 📦 EXISTS | [core/orderbook_imbalance.py](core/orderbook_imbalance.py) |
| 3.3 | On-chain (Glassnode) | 🚫 BLOCKED | Needs €30/mo Glassnode subscription |
| 3.4 | News/Twitter sentiment | 🚫 BLOCKED | Needs paid Twitter/X API + NewsAPI |
| 3.5 | Cross-pair correlation gate | 📦 EXISTS | [core/correlation_shield.py](core/correlation_shield.py) |
| 3.6 | Markov regime model | 📦 EXISTS | [core/markov_regime.py](core/markov_regime.py) |

## Niveau 4 — Adaptive Intelligence

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.1 | RL agent for trailing-stop tuning | 🚫 BLOCKED | 2-3w training; needs realistic simulator (covered by 2.2) + GPU |
| 4.2 | Per-trade Kelly + Vol Parity | 📦 EXISTS | [core/kelly_sizing.py](core/kelly_sizing.py) |
| 4.3 | **Portfolio-level Kelly (cross-market allocation)** | ✅ DONE (#090) | [core/portfolio_optimizer.py](core/portfolio_optimizer.py) — new |
| 4.4 | Bayesian fusion / meta-learner | 📦 EXISTS | `core/bayesian_fusion.py`, `core/meta_learner.py` |
| 4.5 | Adaptive exit / Avellaneda-Stoikov | 📦 EXISTS | `core/adaptive_exit.py`, `core/avellaneda_stoikov.py` |

---

## What's actually NEW from this batch (FIX #090)

### 1. Candle replay engine ([backtest/replay_engine.py](backtest/replay_engine.py))
Replays historical 1m candles through the live signal stack and simulates the
trailing-stop trade lifecycle deterministically. Outputs equity curve + summary.

### 2. A/B harness ([backtest/ab_runner.py](backtest/ab_runner.py))
Runs the replay engine twice with two configs and produces a diff report.

### 3. Portfolio Kelly optimizer ([core/portfolio_optimizer.py](core/portfolio_optimizer.py))
Cross-market capital allocation: combines per-market Kelly (from 4.2) with
inverse-correlation weighting and a portfolio-wide volatility budget. Returns
target weights consumed by `bot/orders_impl.py` at entry.

---

## What is genuinely BLOCKED and why

| Item | Blocker | Estimated cost / time |
|------|---------|------------------------|
| 3.3 On-chain | Glassnode subscription | ~€30/month + signup |
| 3.4 Sentiment | Twitter/X API v2 | ~$100/month basic tier |
| 4.1 RL agent | Compute + simulator | 2-3 weeks GPU training, only worth it after 2.2 stabilizes |

These three items are **explicitly de-scoped** from this batch — they require
spending money or weeks of compute the user has not authorized.

---

## How to consume this roadmap

When the user says *"doe sprint X.Y"*, Copilot:
1. Reads this entry
2. Confirms scope (rejects if too big)
3. Implements + tests + commits + pushes + telegram
4. Updates this row to ✅ DONE with FIX_LOG ref
5. Adds anything discovered as 📦 EXISTS rows
