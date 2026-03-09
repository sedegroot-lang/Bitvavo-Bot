# Configuration Reference

Complete reference for all `bot_config.json` parameters.

## 📊 Signal Parameters

### Moving Averages
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SMA_SHORT` | int | 10 | Short-term Simple Moving Average period |
| `SMA_LONG` | int | 30 | Long-term Simple Moving Average period |
| `MACD_FAST` | int | 12 | MACD fast EMA period |
| `MACD_SLOW` | int | 26 | MACD slow EMA period |
| `MACD_SIGNAL` | int | 9 | MACD signal line period |

### Signal Weights & Debug
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SIGNALS_GLOBAL_WEIGHT` | float | 1.0 | Global multiplier for all signal weights |
| `SIGNALS_DEBUG_LOGGING` | bool | false | Enable detailed signal logging |

### Range Signals
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SIGNALS_RANGE_ENABLED` | bool | true | Enable range-bound detection |
| `SIGNALS_RANGE_LOOKBACK` | int | 90 | Candles to analyze for range |
| `SIGNALS_RANGE_THRESHOLD` | float | 0.25 | Range threshold (% of price) |
| `SIGNALS_RANGE_RSI_PERIOD` | int | 14 | RSI period for range signals |
| `SIGNALS_RANGE_RSI_MAX` | int | 48 | Max RSI for range buy |

### Volatility Breakout Signals
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SIGNALS_VOL_BREAKOUT_ENABLED` | bool | true | Enable volatility breakout detection |
| `SIGNALS_VOL_ATR_WINDOW` | int | 14 | ATR calculation window |
| `SIGNALS_VOL_ATR_MULT` | float | 1.8 | ATR multiplier for breakout |
| `SIGNALS_VOL_VOLUME_WINDOW` | int | 60 | Volume analysis window |
| `SIGNALS_VOL_VOLUME_SPIKE` | float | 1.4 | Volume spike threshold |

### Mean Reversion Signals
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SIGNALS_MEAN_REV_ENABLED` | bool | true | Enable mean reversion signals |
| `SIGNALS_MEAN_REV_WINDOW` | int | 40 | Lookback window |
| `SIGNALS_MEAN_REV_Z` | float | -1.2 | Z-score threshold (negative = oversold) |
| `SIGNALS_MEAN_REV_RSI_MAX` | int | 50 | Max RSI for mean reversion |
| `SIGNALS_MEAN_REV_RSI_PERIOD` | int | 14 | RSI period |
| `SIGNALS_MEAN_REV_MA` | int | 20 | Moving average period |

### Technical Analysis Signals
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SIGNALS_TA_ENABLED` | bool | true | Enable TA signals |
| `SIGNALS_TA_SHORT_MA` | int | 9 | Short MA period |
| `SIGNALS_TA_LONG_MA` | int | 21 | Long MA period |
| `SIGNALS_TA_EMA` | int | 34 | EMA period |
| `SIGNALS_TA_RSI_PERIOD` | int | 14 | RSI period |

---

## 📈 Trading Parameters

### Entry Conditions
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `MIN_SCORE_TO_BUY` | int | 10 | Minimum signal score to open trade |
| `BREAKOUT_LOOKBACK` | int | 20 | Candles to check for breakout |
| `RSI_MIN_BUY` | float | 30.0 | Minimum RSI for buy |
| `RSI_MAX_BUY` | float | 45.0 | Maximum RSI for buy |
| `MIN_AVG_VOLUME_1M` | float | 100.0 | Minimum 1m average volume |
| `MAX_SPREAD_PCT` | float | 0.004 | Maximum bid-ask spread (0.4%) |

### Exit Conditions
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `DEFAULT_TRAILING` | float | 0.05 | Trailing stop percentage (5%) |
| `TRAILING_ACTIVATION_PCT` | float | 0.017 | Profit % to activate trailing (1.7%) |
| `ATR_WINDOW_1M` | int | 14 | ATR window for stop loss |
| `ATR_MULTIPLIER` | float | 2.0 | ATR multiplier for stop distance |
| `HARD_SL_ALT_PCT` | float | 0.04 | Hard stop loss for altcoins (4%) |
| `HARD_SL_BTCETH_PCT` | float | 0.035 | Hard stop loss for BTC/ETH (3.5%) |
| `EXIT_MODE` | string | "trailing_and_hard" | Exit strategy mode |

### Costs
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `FEE_TAKER` | float | 0.0025 | Taker fee (0.25%) |
| `SLIPPAGE_PCT` | float | 0.0015 | Expected slippage (0.15%) |

---

## 💰 Position Sizing

### Basic Sizing
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `BASE_AMOUNT_EUR` | float | 10.0 | Base trade size in EUR |
| `MAX_OPEN_TRADES` | int | 5 | Maximum concurrent positions |
| `MAX_TOTAL_EXPOSURE_EUR` | float | 999999.0 | Maximum total exposure |
| `MIN_BALANCE_EUR` | int | 10 | Minimum EUR balance to keep |
| `MIN_ORDER_EUR` | float | 5.0 | Minimum order size |

### Full Balance Mode
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `AUTO_USE_FULL_BALANCE` | bool | false | Use full available balance |
| `FULL_BALANCE_PORTION` | float | 0.95 | Portion of balance to use (95%) |
| `FULL_BALANCE_MAX_EUR` | float | 2000.0 | Maximum per-trade amount |

### Reinvestment
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `REINVEST_ENABLED` | bool | true | Enable profit reinvestment |
| `REINVEST_PORTION` | float | 0.5 | Portion of profits to reinvest |
| `REINVEST_MAX_INCREASE_PCT` | float | 0.2 | Max increase per reinvest (20%) |
| `REINVEST_MIN_TRADES` | int | 3 | Trades before reinvesting |
| `REINVEST_MIN_PROFIT` | float | 5.0 | Minimum profit to reinvest |
| `REINVEST_CAP` | float | 200.0 | Maximum reinvest amount |

---

## 🔄 DCA (Dollar Cost Averaging)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `DCA_ENABLED` | bool | true | Enable DCA |
| `DCA_DYNAMIC` | bool | true | Use dynamic DCA sizing |
| `DCA_MAX_BUYS` | int | 3 | Maximum DCA buys per trade |
| `DCA_MAX_BUYS_PER_ITERATION` | int | 1 | Max DCA buys per cycle |
| `DCA_DROP_PCT` | float | 0.06 | Price drop % to trigger DCA (6%) |
| `DCA_AMOUNT_EUR` | float | 10.0 | DCA buy amount |
| `DCA_SIZE_MULTIPLIER` | float | 1.5 | Size multiplier for each DCA |
| `DCA_STEP_MULTIPLIER` | float | 1.3 | Drop multiplier for each DCA |
| `RSI_DCA_THRESHOLD` | float | 62.0 | Max RSI for DCA buy |

---

## 🎯 Take Profit

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `TAKE_PROFIT_ENABLED` | bool | true | Enable partial take profit |
| `TAKE_PROFIT_TARGETS` | array | [0.025, 0.04, 0.065] | Profit targets (2.5%, 4%, 6.5%) |
| `TAKE_PROFIT_PERCENTAGES` | array | [0.4, 0.35, 0.25] | Position % to sell at each target |

---

## 🛡️ Risk Management

### Segment Limits
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `RISK_SEGMENT_BASE_LIMITS.alts` | int | 200 | Max EUR in altcoins |
| `RISK_SEGMENT_BASE_LIMITS.majors` | int | 150 | Max EUR in BTC/ETH |
| `RISK_SEGMENT_BASE_LIMITS.stable` | int | 50 | Max EUR in stablecoins |
| `RISK_SEGMENT_BASE_LIMITS.default` | int | 150 | Default segment limit |

### Loss Limits
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `RISK_MAX_DAILY_LOSS` | float | 50.0 | Max daily loss in EUR |
| `RISK_MAX_WEEKLY_LOSS` | float | 150.0 | Max weekly loss in EUR |
| `RISK_MAX_DRAWDOWN_PCT` | float | 20.0 | Max portfolio drawdown % |
| `RISK_MAX_PORTFOLIO_RISK` | float | 0.02 | Max portfolio risk (2%) |
| `RISK_KELLY_ENABLED` | bool | true | Enable Kelly criterion sizing |
| `RISK_EMERGENCY_STOP_ENABLED` | bool | true | Emergency stop on extreme loss |

---

## 🤖 AI & Machine Learning

### AI Supervisor
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `AI_AUTO_APPLY` | bool | true | Auto-apply AI suggestions |
| `AI_ALLOW_PARAMS` | array | [...] | Parameters AI can modify |
| `AI_APPLY_COOLDOWN_MIN` | int | 45 | Minutes between AI changes |
| `AI_REGIME_RECOMMENDATIONS` | bool | true | Enable regime-based suggestions |
| `AI_PORTFOLIO_ANALYSIS` | bool | true | Enable portfolio analysis |
| `AI_AUTO_WHITELIST` | bool | true | AI can suggest new markets |
| `AI_MARKET_SCOPE` | string | "guarded-auto" | Market selection mode |

### AI Guardrails
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `AI_GUARDRAILS.min_volume_24h_eur` | int | 10000 | Min 24h volume for AI markets |
| `AI_GUARDRAILS.max_spread_pct` | float | 0.01 | Max spread for AI markets |
| `AI_GUARDRAILS.max_position_pct_portfolio` | float | 0.05 | Max position size (5%) |
| `AI_GUARDRAILS.max_risk_score` | int | 65 | Max risk score for AI |
| `AI_GUARDRAILS.risk_window_days` | int | 14 | Days to evaluate risk |

### Auto Retrain
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `AI_AUTO_RETRAIN_ENABLED` | bool | true | Enable auto model retraining |
| `AI_RETRAIN_INTERVAL_DAYS` | int | 7 | Days between retrains |
| `AI_RETRAIN_UTC_HOUR` | string | "02:00" | UTC hour for retrain |

### ML Ensemble
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `USE_LSTM` | bool | true | Use LSTM model |
| `USE_RL_AGENT` | bool | true | Use RL agent |
| `ENSEMBLE_WEIGHTS.xgb` | float | 1.0 | XGBoost weight |
| `ENSEMBLE_WEIGHTS.lstm` | float | 0.9 | LSTM weight |
| `ENSEMBLE_WEIGHTS.rl` | float | 0.7 | RL agent weight |
| `ENSEMBLE_MIN_CONFIDENCE` | float | 0.65 | Min ensemble confidence |

### Reinforcement Learning
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `RL_ENABLED` | bool | true | Enable RL agent |
| `RL_LEARNING_RATE` | float | 0.15 | RL learning rate |
| `RL_DISCOUNT_FACTOR` | float | 0.98 | Future reward discount |
| `RL_EPSILON` | float | 0.05 | Exploration rate |
| `RL_EPSILON_MIN` | float | 0.01 | Minimum exploration |
| `RL_EPSILON_DECAY` | float | 0.995 | Exploration decay rate |

---

## 📋 Market Lists

### Whitelist
```json
"WHITELIST_MARKETS": ["BTC-EUR", "ETH-EUR", "SOL-EUR", ...]
```
Markets the bot is allowed to trade.

### Quarantine
```json
"QUARANTINE_MARKETS": ["MIRA-EUR", "OM-EUR", ...]
```
Markets temporarily banned from trading.

### Watchlist
```json
"WATCHLIST_MARKETS": ["S-EUR", "LDO-EUR", ...]
```
Markets being tested with small positions.

---

## 📊 Market Performance Filter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `MARKET_PERFORMANCE_FILTER_ENABLED` | bool | true | Enable performance filter |
| `MARKET_PERFORMANCE_MIN_TRADES` | int | 5 | Min trades to evaluate |
| `MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR` | float | -1.0 | Min expected value |
| `MARKET_PERFORMANCE_MAX_CONSEC_LOSSES` | int | 5 | Max consecutive losses |

---

## ⚙️ System Settings

### Timing
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `SLEEP_SECONDS` | int | 10 | Main loop sleep interval |
| `OPEN_TRADE_COOLDOWN_SECONDS` | int | 120 | Cooldown between trades |
| `CONFIG_HOT_RELOAD_SECONDS` | int | 60 | Config reload interval |
| `SYNC_INTERVAL_SECONDS` | int | 300 | Bitvavo sync interval |

### Logging
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `LOG_LEVEL` | string | "INFO" | Log level (DEBUG/INFO/WARNING/ERROR) |
| `LOG_MAX_BYTES` | int | 262144 | Max log file size (256KB) |
| `LOG_BACKUP_COUNT` | int | 2 | Number of log backups |
| `LOG_JSON_FORMAT` | bool | false | Enable JSON structured logging |
| `LOG_JSON_FILE` | string | "logs/bot_log.jsonl" | JSON log file path |

### Performance Monitoring
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `PERF_MONITOR_ENABLED` | bool | true | Enable performance monitoring |
| `PERF_SAMPLE_SECONDS` | int | 30 | Sample interval |
| `PERF_SAMPLE_HISTORY` | int | 600 | History to keep (samples) |

### Order Settings
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ORDER_TYPE` | string | "auto" | Order type (auto/market/limit) |
| `LIMIT_ORDER_TIMEOUT_SECONDS` | int | 1800 | Limit order timeout |
| `LIMIT_ORDER_PRICE_OFFSET_PCT` | float | 0.1 | Limit price offset |

---

## 🔔 Notifications

### Telegram
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `TELEGRAM_ENABLED` | bool | false | Enable Telegram notifications |
| `TELEGRAM_BOT_TOKEN` | string | "" | Telegram bot token |
| `TELEGRAM_CHAT_ID` | string | "" | Telegram chat ID |

### Notification Types
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `NOTIFY_TRADES` | bool | true | Notify on trade events |
| `NOTIFY_ERRORS` | bool | true | Notify on errors |
| `NOTIFY_DAILY_REPORT` | bool | true | Send daily report |
| `NOTIFY_RISK_ALERTS` | bool | true | Notify on risk events |

---

## 🧹 Dust & Cleanup

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `DUST_THRESHOLD_EUR` | float | 1.0 | Min value to keep position |
| `DUST_SWEEP_ENABLED` | bool | true | Auto-sell dust positions |
| `DUST_TRADE_THRESHOLD_EUR` | float | 5.0 | Min trade value |

---

## 📁 File Paths

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EXPECTANCY_FILE` | "data/expectancy_stats.json" | Expectancy statistics |
| `EXPECTANCY_HISTORY_FILE` | "data/expectancy_history.jsonl" | Expectancy history |
| `PORTFOLIO_SNAPSHOT_FILE` | "data/portfolio_snapshot.json" | Portfolio snapshot |
| `PARTIAL_TP_HISTORY_FILE` | "data/partial_tp_events.jsonl" | Take profit events |
| `ACCOUNT_OVERVIEW_FILE` | "data/account_overview.json" | Account overview |
| `PERF_METRICS_FILE` | "logs/perf_metrics.jsonl" | Performance metrics |

---

## 🔧 Advanced Features

### HODL Scheduler
Scheduled recurring buys:
```json
"HODL_SCHEDULER": {
  "enabled": true,
  "schedules": [
    {"market": "BTC-EUR", "amount_eur": 5.0, "interval_minutes": 10080}
  ]
}
```

### Pairs Arbitrage
Statistical arbitrage between correlated pairs:
```json
"PAIRS_ARBITRAGE": {
  "enabled": true,
  "max_parallel_pairs": 2,
  "default_z_entry": 2.0,
  "default_z_exit": 0.5
}
```

### Event Hooks
External event integration:
```json
"EVENT_HOOKS": {
  "enabled": true,
  "watch_dir": "data/event_hooks/inbox",
  "auto_pause_minutes": 30
}
```
