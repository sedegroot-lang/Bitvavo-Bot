# Strategy Logic Documentation

## Entry Signals (Score-Based)

The bot uses a **composite signal scoring system** (`MIN_SCORE_TO_BUY = 10`):

| Signal | Weight | Description |
|--------|--------|-------------|
| SMA Cross | 1.5 | Short SMA(7) crosses above Long SMA(25) |
| Price > SMA | 1.0 | Price above SMA long |
| RSI OK | 1.0 | RSI(14) between 35-58 (buy zone) |
| MACD OK | 1.2 | MACD histogram positive / crossover |
| EMA OK | 1.0 | Price above EMA(34) |
| BB Breakout | 1.2 | Bollinger Band breakout signal |
| Stochastic | 0.8 | Stochastic oscillator confirmation |
| Mean Reversion | 1.0+ | Z-score < -1.5 + RSI < 50 |
| Volume Breakout | 1.0+ | ATR breakout + volume spike > 2x |
| Range Detection | 1.0+ | RSI + lookback range filter |

**Filters applied before entry:**
- Momentum filter: 24h change > -12%
- Spread check: < 2% spread
- Liquidity guard: orderbook depth > €1000 both sides
- RSI max buy: reject if RSI > 58

## Exit Strategy (Multi-Layer)

### 1. Trailing Take-Profit
- **Activation**: Price must rise ≥4.5% above entry (TRAILING_ACTIVATION_PCT)
- **Stepped trailing** tightens as profit grows:

| Profit Level | Trail Distance | Min Profit Lock |
|-------------|----------------|-----------------|
| +2% | 1.2% | +0.8% |
| +4% | 1.0% | +3.0% |
| +6% | 0.8% | +5.2% |
| +8% | 0.7% | +7.3% |
| +12% | 0.6% | +11.4% |
| +18% | 0.5% | +17.5% |
| +25% | 0.4% | +24.6% |
| +35% | 0.3% | +34.7% |

- **ATR-adaptive**: `max(ATR_MULT * ATR, high * trail_pct * 0.5)`
- **Trend adjustment**: tight in uptrend (0.6x), wide in downtrend (1.4x)
- **Profit velocity**: fast movers get wider trail (1.3x), slow get tighter (0.8x)
- **Safety checks**: sell blocked if real_profit <= 0

### 2. Breakeven Lock
- Activates at +3% profit
- Locks stop at buy_price * 1.006 (covers fees + 0.1%)
- Overrides trailing stop if higher

### 3. Hard Stop Loss
- ALT coins: -12% (HARD_SL_ALT_PCT)
- BTC/ETH: -10% (HARD_SL_BTCETH_PCT)
- DCA protection: preserves original hard stop from first buy

### 4. Time-Based Stop
- After 5 days: triggers at -3.5% loss (STOP_LOSS_TIME_DAYS/PCT)

## Position Sizing

### Kelly Criterion (Half-Kelly)
```
kelly_pct = win_rate - (1 - win_rate) / avg_win_loss_ratio
position = base_amount * kelly_pct * kelly_fraction(0.5)
```
- Uses last 50 trades for statistics
- Minimum €5, maximum €25
- Fallback to BASE_AMOUNT_EUR (€12) if insufficient history

### Portfolio Limits
- MAX_OPEN_TRADES: 5
- MAX_TOTAL_EXPOSURE_EUR: €9999
- Circuit breaker: halt at €50 unrealized loss
- Daily loss limit: €25

## DCA Strategy (Hybrid Mode)

### Standard DCA (Dip Buying)
- Trigger: price drops ≥6% from entry (DCA_DROP_PCT)
- Amount: €5 per DCA buy (DCA_AMOUNT_EUR)
- Max buys: 3 (DCA_MAX_BUYS)
- RSI filter: only buy when RSI < 45

### Pyramid-Up DCA (Winner Adding)
- Trigger: position is ≥3% in profit (DCA_PYRAMID_MIN_PROFIT_PCT)
- Scale-down: each add is 0.7x previous (DCA_PYRAMID_SCALE_DOWN)
- Max pyramid adds: 2 (DCA_PYRAMID_MAX_ADDS)
- Preserves trailing activation on DCA

## Risk Management Layers

1. **Pre-trade**: score threshold, momentum filter, spread check, liquidity guard
2. **Position**: Kelly sizing, max exposure, correlation awareness
3. **In-trade**: trailing stop, breakeven lock, hard SL, time SL
4. **Portfolio**: circuit breaker (€50), daily loss limit (€25)
5. **Operational**: watchdog auto-restart, graceful shutdown, Telegram alerts

## Configuration Validation

Cross-validation rules enforce:
- TRAILING_ACTIVATION_PCT > DEFAULT_TRAILING
- DCA_PYRAMID_MIN_PROFIT_PCT ≥ TRAILING_ACTIVATION_PCT (no DCA in trailing zone)
- BUDGET_RESERVATION sums to 100%
- GRID_TRADING nested structure validation
- All numeric ranges checked against min/max bounds
