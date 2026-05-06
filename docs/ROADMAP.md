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

## Niveau 4 — Adaptive Intelligence

| # | Item | Status | Notes |
|---|------|--------|-------|
| 4.1 | RL agent for trailing-stop tuning | 🚫 BLOCKED | 2-3w training; needs realistic simulator (covered by 2.2) + GPU |


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
