# Advanced Features — Bitvavo Trading Bot

> Auto-generated from simulation + implementation session (2026-03-16)

---

## Simulation Results Summary

Ran 18 advanced trading concepts against 8000 synthetic multi-regime candles + 890 real historical trades.

### Impact Ranking (sorted by PnL improvement)

| Rank | Idea | PnL Impact | Status | Module |
|------|------|-----------|--------|--------|
| 1 | **Smart DCA (Volatility-Aware)** | +€203.84 | ✅ Implemented | `core/smart_dca.py` |
| 2 | **Trade DNA Fingerprinting** | +€177.15 | ✅ Implemented | `modules/signals/trade_dna.py` |
| 3 | **Shannon Entropy Gate** | +€149.40 | ✅ Implemented | `modules/signals/entropy_gate.py` |
| 4 | **Markov Regime Anticipation** | +€122.86 | ✅ Implemented | `core/markov_regime.py` |
| 5 | **Meta-Learning Strategy Selector** | +€107.64 | ✅ Implemented | `core/meta_learner.py` |
| 6 | **Time-of-Day Seasonality** | +€106.12 | ✅ Implemented | `modules/signals/time_of_day.py` |
| 7 | **Bayesian Signal Fusion** | +€38.90 | ✅ Implemented | `core/bayesian_fusion.py` |
| 8 | **VPIN Toxicity Filter** | +€27.23 | ✅ Implemented | `modules/signals/vpin_toxicity.py` |
| 9 | **Spread Regime Detector** | +€23.25 | ✅ Implemented | `modules/signals/spread_regime.py` |
| 10 | Transfer Entropy (Lead-Lag) | +€4.78 | 🔬 Simulated only | — |
| 11 | Cascade Profit Recycling | +€0.21 | 🔬 Marginal | — |
| 12 | Volatility Term Structure | -€0.12 | ❌ Not effective | — |
| 13 | Adversarial Stop-Loss | -€1.12 | ❌ Not effective | — |
| 14 | Reflexivity Loop Detector | -€29.61 | ❌ Negative | — |
| 15 | Hurst Exponent Regime | -€44.23 | ❌ Negative | — |
| 16 | Synthetic Pair Trading | -€76.12 | ❌ Negative (needs real corr data) | — |
| 17 | PCA Eigen-Portfolio | -€266.89 | ❌ Negative (needs more assets) | — |
| 18 | Multi-Horizon Allocation | -€428.26 | ❌ Strongly negative | — |

### Real Trade Analysis (890 historical trades)

| Filter | Trades | PnL | Win Rate |
|--------|--------|-----|----------|
| All trades (unfiltered) | 890 | -€841.03 | 46.3% |
| Score >= 7.0 | 22 | -€5.10 | **77.3%** |
| RSI 35-55 | 17 | -€4.33 | **76.5%** |
| High Volume | 11 | -€4.14 | **72.7%** |
| Combined (Score+RSI) | 17 | -€4.33 | **76.5%** |

**Key insight**: Trades with score >= 7.0 have 77.3% winrate vs 46.3% overall. The existing MIN_SCORE filter is already extremely effective. The new advanced filters improve on top of this.

---

## Implemented Features (9 modules)

### 1. Shannon Entropy Gate (`modules/signals/entropy_gate.py`)
**Impact**: +€149.40 simulated | **Type**: Signal Filter

Measures Shannon entropy of price returns to detect chaos vs order:
- Low entropy = predictable market → signals are reliable → bonus (+0.5)
- High entropy = chaotic noise → signals are random → penalty (-1.5)

**Config keys**:
- `ENTROPY_LOOKBACK` (default 60): candles to measure
- `ENTROPY_THRESHOLD` (default 0.70): max entropy ratio before penalty
- `ENTROPY_PENALTY` (default 1.5): score penalty on high entropy
- `ENTROPY_BONUS` (default 0.5): score bonus on low entropy

---

### 2. Trade DNA Fingerprinting (`modules/signals/trade_dna.py`)
**Impact**: +€177.15 simulated | **Type**: Pattern Matching Signal

Builds feature fingerprints of trade setups and compares to historical outcomes using K-nearest-neighbors. Only approves entries that match historically profitable profiles.

**Config keys**:
- `DNA_K_NEIGHBORS` (default 10): number of nearest neighbors
- `DNA_MIN_DB_SIZE` (default 20): minimum trades in DB
- `DNA_BONUS` (default 1.0): score for profitable match
- `DNA_PENALTY` (default 1.0): penalty for losing match

**Data**: Reads from `data/trade_archive.json`, reloads hourly.

---

### 3. Time-of-Day Seasonality (`modules/signals/time_of_day.py`)
**Impact**: +€106.12 simulated | **Type**: Signal Filter

Analyzes per-hour return statistics from candle data. Rewards entries during historically profitable hours, penalizes during losing hours.

**Config keys**:
- `TOD_LOOKBACK` (default 720): candles to analyze
- `TOD_BONUS` (default 0.6): bonus during good hours
- `TOD_PENALTY` (default 0.8): penalty during bad hours
- `TOD_MIN_SAMPLES` (default 10): min samples per hour

---

### 4. VPIN Toxicity Filter (`modules/signals/vpin_toxicity.py`)
**Impact**: +€27.23 simulated | **Type**: Risk Filter

Volume-Synchronized Probability of Informed Trading. Detects when "smart money" is active via buy/sell volume imbalance. High VPIN = informed traders → crash risk.

**Config keys**:
- `VPIN_LOOKBACK` (default 50): candles for calculation
- `VPIN_THRESHOLD` (default 0.40): toxicity threshold
- `VPIN_PENALTY` (default 1.0): score penalty when toxic
- `VPIN_SAFE_BONUS` (default 0.3): bonus when flow is clean

**Based on**: Easley, López de Prado & O'Hara (2012)

---

### 5. Spread Regime Detector (`modules/signals/spread_regime.py`)
**Impact**: +€23.25 simulated | **Type**: Risk Filter

Uses bid-ask spread (high-low proxy) z-score as risk signal. Wide spread = market maker uncertainty = reversal risk.

**Config keys**:
- `SPREAD_LOOKBACK` (default 50): z-score window
- `SPREAD_Z_THRESHOLD` (default 1.0): penalty threshold
- `SPREAD_PENALTY` (default 0.7): score penalty on wide spread
- `SPREAD_TIGHT_BONUS` (default 0.3): bonus on tight spread

---

### 6. Smart DCA Engine (`core/smart_dca.py`)
**Impact**: +€203.84 simulated (highest!) | **Type**: Core DCA Logic

Replaces fixed-drop DCA timing with volatility-aware Bollinger Band squeeze detection. Waits for selling exhaustion before DCA instead of buying at arbitrary drop levels.

**Functions**:
- `should_smart_dca(closes, price, buy_price, ...)` → (bool, reason)
- `smart_dca_score(closes, price, buy_price)` → quality score 0-100

**Integration point**: Replace standard DCA trigger in `trailing_bot.py` / `bot/trailing.py`

---

### 7. Bayesian Signal Fusion (`core/bayesian_fusion.py`)
**Impact**: +€38.90 simulated | **Type**: Core Weight Engine

Online Bayesian weight updating for signal providers. After each trade, signals that contributed to wins get upweighted; signals in losing trades get downweighted.

**Functions**:
- `update_from_trade_result(active_signals, profit)` → updated weights
- `weighted_total_score(signal_scores)` → weighted total
- `get_signal_weight(name)` → current weight

**Persistence**: `data/bayesian_signal_weights.json`

**Integration point**: Apply in `bot/signals.py` when computing final score. Call `update_from_trade_result()` in `bot/trade_lifecycle.py` after trade close.

---

### 8. Meta-Learning Strategy Selector (`core/meta_learner.py`)
**Impact**: +€107.64 simulated | **Type**: Capital Allocation

Dynamically weights momentum/mean-reversion/breakout strategy mix based on rolling Sharpe ratio. Auto-shifts capital to whichever strategy performs best in current conditions.

**Class**: `MetaLearner`
- `.classify_trade(rsi, sma_cross, bb_position)` → strategy name
- `.record_outcome(strategy, pnl)` → update history
- `.update_weights()` → recalculate allocations
- `.should_take_trade(strategy, score)` → score-adjusted entry decision

**Persistence**: `data/meta_learner_state.json`

---

### 9. Markov Regime Transition Predictor (`core/markov_regime.py`)
**Impact**: +€122.86 simulated | **Type**: Regime Anticipation

Builds a regime→regime transition probability matrix from observed data. Anticipates upcoming regime changes for pre-positioning.

**Class**: `MarkovRegimePredictor`
- `.record_regime(regime)` → track observations
- `.transition_probability(from, to)` → P(next|current)
- `.get_score_adjustment(current)` → MIN_SCORE delta
- `.should_anticipate_trend(current)` → bool

**Persistence**: `data/markov_regime.json`

---

## Testing

All features covered by 35 automated tests:

```
tests/test_advanced_signals.py::TestShannonEntropy        (3 tests)
tests/test_advanced_signals.py::TestEntropyGateSignal     (3 tests)
tests/test_advanced_signals.py::TestTradeDNA              (2 tests)
tests/test_advanced_signals.py::TestTimeOfDay             (2 tests)
tests/test_advanced_signals.py::TestVPIN                  (3 tests)
tests/test_advanced_signals.py::TestSpreadRegime          (3 tests)
tests/test_advanced_signals.py::TestSmartDCA              (2 tests)
tests/test_advanced_signals.py::TestBayesianFusion        (2 tests)
tests/test_advanced_signals.py::TestMetaLearner           (2 tests)
tests/test_advanced_signals.py::TestMarkovRegime          (2 tests)
```

Run: `pytest tests/test_advanced_signals.py -v`

Additional test classes (Round 2):
```
tests/test_advanced_signals.py::TestFractalDimension      (3 tests)
tests/test_advanced_signals.py::TestVolatilityCone         (2 tests)
tests/test_advanced_signals.py::TestMicrostructureMomentum (3 tests)
tests/test_advanced_signals.py::TestEntropyKelly           (3 tests)
```

---

## Integration Guide

### Signal providers (5 new) — ALREADY ACTIVE
The 5 new signal providers are registered in `modules/signals/__init__.py` and are automatically included in `evaluate_signal_pack()`. They run every bot loop cycle alongside existing signals. No manual integration needed.

### Core modules (4 new) — INTEGRATION POINTS

| Module | Integration Point | Action |
|--------|-------------------|--------|
| `core/smart_dca.py` | DCA trigger in `bot/trailing.py` | Call `should_smart_dca()` before DCA buy |
| `core/bayesian_fusion.py` | Score calc in `bot/signals.py` | Apply `weighted_total_score()` after signal pack |
| `core/meta_learner.py` | Entry decision in `trailing_bot.py` | Use `should_take_trade()` for final go/no-go |
| `core/markov_regime.py` | Bot loop in `trailing_bot.py` | Call `record_regime()` each cycle, use `get_score_adjustment()` |

---

## Simulation Script

Full simulation: `python scripts/simulate_advanced_ideas.py`

Results saved to: `data/advanced_ideas_simulation.json`

---

## Future Ideas (Not Yet Implemented)

### Potentially Promising (positive but marginal)
- **Transfer Entropy Lead-Lag** (+€4.78): Cross-asset causality analysis. Needs real multi-market data.
- **Cascade Profit Recycling** (+€0.21): Re-invest profits immediately. Marginal benefit.

### Needs Real Data
- **Pair Trading with Shorting**: Now possible on Bitvavo. Needs real correlation matrix from live prices.
- **Volatility Term Structure**: Needs multi-timeframe ATR with real candle data (5m + 1h).

### Ideas for Future Research
See "Novel Strategy Research" section below.

---

## Novel Strategy Research (Round 2)

### Implemented (Round 2)

### 10. Fractal Dimension Signal (`modules/signals/fractal_dimension.py`)
**Type**: Signal Filter | **Status**: ✅ Implemented + Registered

Uses Higuchi fractal dimension to classify market microstructure:
- D ≈ 1.0 → smooth trend → momentum bonus (+0.8)
- D ≈ 1.5 → random walk → penalty (-0.6, don't trade noise)
- D ≈ 2.0 → space-filling → mean reversion bonus (+0.5)

**Config keys**: `FRACTAL_LOOKBACK`, `FRACTAL_TREND_D`, `FRACTAL_RANDOM_LOW/HIGH`, `FRACTAL_MR_D`, `FRACTAL_TREND_BONUS`, `FRACTAL_RANDOM_PENALTY`, `FRACTAL_MR_BONUS`

**Based on**: Higuchi (1988) "Approach to an irregular time series"

---

### 11. Realized Volatility Cone (`modules/signals/volatility_cone.py`)
**Type**: Signal Filter | **Status**: ✅ Implemented + Registered

Builds a volatility cone from historical data. Detects abnormal volatility:
- Vol in bottom 15th percentile → expansion imminent → penalty
- Vol in top 85th percentile → contraction expected → bonus (vol crush opportunity)

**Config keys**: `VOLCONE_LOOKBACK`, `VOLCONE_SHORT_WIN`, `VOLCONE_MED_WIN`, `VOLCONE_LOW_PCT`, `VOLCONE_HIGH_PCT`, `VOLCONE_LOW_PENALTY`, `VOLCONE_HIGH_BONUS`

**Based on**: Natenberg, "Option Volatility" volatility cone concept

---

### 12. Microstructure Momentum (`modules/signals/microstructure_momentum.py`)
**Type**: Signal Provider | **Status**: ✅ Implemented + Registered

Detects hidden momentum from order flow microstructure using 3 metrics:
1. **Kaufman Efficiency Ratio** — trend quality (1.0 = straight line, 0.0 = chop)
2. **Volume-Weighted Acceleration** — price acceleration confirmed by volume
3. **Tick Imbalance** — hidden buying/selling pressure

Two of three must align for a signal.

**Config keys**: `MICRO_MOM_WINDOW`, `MICRO_MOM_EFF_THRESHOLD`, `MICRO_MOM_ACCEL_THRESHOLD`, `MICRO_MOM_IMBALANCE_THRESHOLD`, `MICRO_MOM_BONUS`, `MICRO_MOM_PENALTY`

**Based on**: Kyle (1985) Lambda estimation / Easley & O'Hara information models

---

### 13. Entropy-Weighted Kelly Sizing (`core/entropy_kelly.py`)
**Type**: Core Position Sizing | **Status**: ✅ Implemented (needs integration)

Information-theoretic position sizing:
- Low entropy → full half-Kelly fraction (market is predictable)
- High entropy → quarter-Kelly (market is chaotic, reduce exposure)

**Functions**: `entropy_kelly_fraction()`, `get_sizing_adjustment()`

**Config keys**: `ENTROPY_KELLY_WINDOW`, `KELLY_FRACTION`, `ENTROPY_KELLY_THRESHOLD`

**Integration point**: Apply in `core/kelly_sizing.py` or `trailing_bot.py` position sizing

---

### Ideas for Future Research (Not Yet Implemented)
Compare order book depth changes over time with price movement. If bids are growing but price is flat → accumulation → entry signal. Inverse for distribution. This is **Level 2 data analysis** that no retail bot does.

### 22. Entropy-Weighted Kelly Sizing
Combine Shannon Entropy Gate with Kelly Criterion: when entropy is low (predictable), use full Kelly fraction. When entropy is high, reduce to quarter-Kelly. This creates an **information-theoretic position sizing** method.

### 23. Realized Volatility Cone
Build a "volatility cone" from historical data — expected volatility ranges at different time horizons. When realized vol falls outside the cone, it's abnormal:
- Below cone → vol expansion imminent → reduce positions
- Above cone → vol contraction expected → increase positions

### 24. Fractal Dimension Signal
Compute the fractal dimension of price using box-counting method:
- D ≈ 1.0 → smooth trend → momentum strategy
- D ≈ 1.5 → random walk → don't trade
- D ≈ 2.0 → space-filling → mean reversion heaven

### 25. Wasserstein Distance Regime Detector
Instead of BOCPD, use Wasserstein (earth mover's) distance between rolling windows of return distributions. When the distance spikes, a regime change is occurring. More robust than changepoint detection.

### 26. Cross-Exchange Sentiment Proxy
Track bid-ask imbalance across time as a proxy for sentiment. Build a rolling sentiment index from order flow, then use it as an additional signal weight.

### 27. Adaptive Fee-Aware Exit
Factor in the fee tier into exit decisions: if selling at +2% but fees are 0.25%, wait for +2.5% to compensate. Sounds obvious but no bot does this dynamically with partial TP levels.

### 28. Regime-Conditional Correlation
The correlation between assets changes per regime. In bull markets BTC/ETH correlate 0.95, in bear markets only 0.70. Build regime-conditional correlation matrices for better pair selection.

### 29. Information Ratio Threshold
Only enter trades where the expected information ratio (alpha / tracking error vs benchmark) exceeds a threshold. This is how institutional PMs filter trades.

### 30. Synthetic Variance Swap
Simulate a variance swap by going long when realized vol < implied vol proxy (ATR), short when realized > implied. This captures the "variance risk premium" that exists in crypto.
