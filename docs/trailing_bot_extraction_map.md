# trailing_bot.py — Comprehensive Extraction Map

**File:** `trailing_bot.py` (6785 lines)  
**Generated:** 2026-02-15  
**Purpose:** Safe function extraction reference for modularization

---

## 1. IMPORT STATEMENTS (Lines 3–109)

### Standard Library (Lines 3–21)
```
asyncio, copy, json, logging, math, os, random, shutil, socket,
statistics, sys, threading, time, datetime, Decimal/ROUND_DOWN,
deque, TYPE_CHECKING/Any/Dict/List/Optional/Tuple, Path, atexit
```

### Third-party (Line 22, 79)
```
dotenv (load_dotenv), numpy (np)
```

### Internal modules (Lines 26–109)
```
modules.config.load_config
core.reservation_manager.ReservationManager
modules.logging_utils (file_lock, log, locked_write_json)
modules.json_compat.write_json_compat
modules.trading (ARCHIVE_FILE, MAX_CLOSED, TRADE_LOG, bitvavo)
modules.metrics (MetricsCollector, configure, get_collector)
modules.trade_archive.archive_trade
modules.trading_dca (DCAContext, DCASettings, DCAManager)
modules.ml.predict_ensemble
modules.trading_liquidation (LiquidationContext, LiquidationManager)
modules.trading_monitoring (MonitoringContext, MonitoringManager)
modules.trading_risk (RiskContext, RiskManager, segment_for_market)
modules.trading_sync (SyncContext, TradingSynchronizer)
modules.trade_store (load_snapshot, save_snapshot)
modules.signals (SignalContext, evaluate_signal_pack)
modules.cost_basis.derive_cost_basis
modules.trade_block_reasons.collect_and_record
modules.external_trades.is_market_claimed
core.indicators (close_prices, highs, lows, volumes, sma, ema, ema_series,
                  rsi, macd, atr, bollinger_bands, stochastic,
                  calculate_momentum_score)
modules.event_hooks.EventState (optional)
modules.perf_monitor.PerfSampler (optional, L306)
```

---

## 2. MODULE-LEVEL GLOBALS

### Core Config & Paths
| Line(s) | Name | Type | Notes |
|---------|------|------|-------|
| 29 | `CONFIG` | `dict` | Master config dict, loaded from `load_config()` |
| 68 | `PROJECT_ROOT` | `Path` | `Path(__file__).resolve().parent` |
| 69 | `HEALTH_CHECK_INTERVAL_SECONDS` | `int` | From CONFIG |
| 70 | `_LAST_HEALTH_CHECK_TS` | `float` | Mutable, written by `_run_runtime_health_checks` |
| 71 | `BOT_HEALTH_PATH` | `Path` | `PROJECT_ROOT / 'data' / 'bot_health.json'` |
| 319 | `write_json_locked` | `function` | Alias for `locked_write_json` |
| 320 | `json_write_compat` | `function` | Alias for `write_json_compat` |
| 322 | `TRADE_LOG` | `str` | From CONFIG |
| 323 | `ARCHIVE_FILE` | `str` | From CONFIG |
| 324 | `MAX_CLOSED` | `int` | From CONFIG |
| 325 | `TRADE_PNL_HISTORY_FILE` | `str` | From CONFIG |
| 327 | `bitvavo` | object | Bitvavo API client (alias of `_base_bitvavo`) |
| 329 | `RUNNING` | `bool` | Bot loop control flag |
| 331 | `_reservation_manager` | `ReservationManager` | Thread-safe market reservation |

### Trade State (CRITICAL — shared mutable state)
| Line(s) | Name | Type | Notes |
|---------|------|------|-------|
| 353 | `open_trades` | `Dict[str, Any]` | **MUTABLE**, protected by `trades_lock` |
| 354 | `closed_trades` | `List[Dict]` | **MUTABLE**, protected by `trades_lock` |
| 355 | `market_profits` | `Dict[str, float]` | **MUTABLE**, protected by `trades_lock` |
| 358 | `trades_lock` | `threading.RLock` | Lock for trade state |
| 359 | `market_performance` | `Dict[str, Any]` | **MUTABLE**, protected by `MARKET_PERFORMANCE_LOCK` |
| 360 | `MARKET_PERFORMANCE_FILE` | `str` | From CONFIG |
| 361 | `MARKET_PERFORMANCE_LOCK` | `threading.Lock` | Lock for market_performance |
| 1563 | `scan_offset` | `int` | Block scan counter |
| 1563 | `open_trades, closed_trades, market_profits` | re-assigned | `{}, [], {}` (overwrite at L1563) |

### Market Performance Config
| Line(s) | Name | Type |
|---------|------|------|
| 362 | `MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS` | `int` |
| 363 | `MARKET_PERFORMANCE_MIN_TRADES` | `int` |
| 364 | `MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR` | `float` |
| 365-368 | `MARKET_PERFORMANCE_TARGET_EXPECTANCY_EUR` | `float` |
| 369 | `MARKET_PERFORMANCE_MAX_CONSEC_LOSSES` | `int` |
| 370 | `MARKET_PERFORMANCE_FILTER_ENABLED` | `bool` |
| 371 | `MARKET_PERFORMANCE_SIZE_BIAS_ENABLED` | `bool` |
| 372 | `MARKET_PERFORMANCE_SIZE_MIN_MULT` | `float` |
| 373-375 | `MARKET_PERFORMANCE_SIZE_MAX_MULT` | `float` |
| 376 | `MARKET_PERFORMANCE_SMOOTHING` | `float` |
| 377 | `MARKET_PERFORMANCE_FILTER_LOG_INTERVAL` | `int` |
| 378 | `MARKET_PERFORMANCE_PROBATION_DAYS` | `int` |
| 379 | `_MARKET_PERF_FILTER_LOG` | `Dict[str, float]` |
| 380 | `_MARKET_PERF_BLOCK_TIMESTAMPS` | `Dict[str, float]` |
| 381 | `_LAST_MARKET_PERFORMANCE_SAVE` | `float` |

### AI Regime
| Line(s) | Name | Type |
|---------|------|------|
| 382-388 | `AI_REGIME_*` constants | `int/float` |
| 403 | `_AI_REGIME_CACHE` | `Dict[str, Any]` |

### Manager Singletons
| Line(s) | Name | Type |
|---------|------|------|
| 404 | `dca_manager` | `Optional[DCAManager]` |
| 405 | `dca_settings` | `Optional[DCASettings]` |
| 406 | `liquidation_manager` | `Optional[LiquidationManager]` |
| 407 | `monitoring_manager` | `Optional[MonitoringManager]` |
| 408 | `synchronizer` | `Optional[TradingSynchronizer]` |
| 409 | `_auto_sync_thread` | `Optional[threading.Thread]` |
| 410 | `_managers_initialized` | `bool` |
| 411 | `_monitor_threads_started` | `bool` |
| 413 | `perf_sampler` | `Optional[PerfSampler]` |
| 414 | `risk_manager` | `Optional[RiskManager]` |
| 415 | `metrics_collector` | `Optional[MetricsCollector]` |
| 418 | `EVENT_STATE` | `Optional[EventState]` |
| 421 | `_EVENT_PAUSE_CACHE` | `Dict[str, bool]` |

### Trading Config Constants
| Line(s) | Name | Type |
|---------|------|------|
| 1159 | `FLOODGUARD` | `dict` |
| 1160-1165 | `SALDO_FORCE_*` | various |
| 1167 | `SYNC_REMOVED_CACHE` | `str` |
| 1169 | `EXCLUDED_MARKETS` | `set` |
| 1170 | `TEST_MODE` | `bool` |
| 1171 | `LIVE_TRADING` | `bool` |
| 1172 | `STOP_AFTER_SECONDS` | `int` |
| 1174-1183 | `SMA_SHORT, SMA_LONG, MACD_FAST, MACD_SLOW, MACD_SIGNAL, BREAKOUT_LOOKBACK, MIN_SCORE_TO_BUY` | various |
| 1184-1191 | `TAKE_PROFIT_ENABLED, PARTIAL_TP_LEVELS` | `bool, List[Tuple]` |
| 1207-1213 | `ATR_WINDOW_1M, ATR_MULTIPLIER, HARD_SL_ALT_PCT, HARD_SL_BTCETH_PCT` | various |
| 1215 | `DEFAULT_TRAILING` | `float` |
| 1216 | `TRAILING_ACTIVATION_PCT` | `float` |
| 1217 | `MIN_AVG_VOLUME_1M` | from CONFIG |
| 1218 | `MAX_SPREAD_PCT` | from CONFIG |
| 1221-1228 | `RSI_MIN_BUY, RSI_MAX_BUY, FEE_MAKER, FEE_TAKER, SLIPPAGE_PCT, SLEEP_SECONDS, MAX_OPEN_TRADES` | various |
| 1229-1230 | `MAX_CLUSTER_*` | `int/float` |
| 1231-1245 | `BASE_AMOUNT_EUR, MIN_ORDER_EUR, DUST_*, MAX_TOTAL_EXPOSURE_EUR, MIN_BALANCE_EUR` | various |
| 1246-1252 | `EXPECTANCY_FILE, EXPECTANCY_HISTORY_FILE, PORTFOLIO_SNAPSHOT_FILE, PARTIAL_TP_*_FILE, ACCOUNT_OVERVIEW_FILE` | `Path` |
| 1253-1258 | `_PARTIAL_TP_STATS_LOCK, _PARTIAL_TP_STATS` | `Lock, Dict` |
| 1456-1462 | `REINVEST_*, ORDER_TYPE, AUTO_USE_FULL_BALANCE, FULL_BALANCE_*` | various |
| 1468-1470 | `OPERATOR_ID, PLACE_ORDERS_ENABLED` | `Optional[int], bool` |
| 1480-1492 | `DCA_ENABLED, DCA_DYNAMIC, DCA_MAX_BUYS, DCA_DROP_PCT, DCA_STEP_MULTIPLIER, DCA_AMOUNT_EUR, DCA_SIZE_MULTIPLIER` | various |
| 1495-1496 | `RESET_TRAILING_ON_DCA*` | `bool, float` |
| 1498-1503 | `EXIT_MODE, STOP_LOSS_ENABLED, OPEN_TRADE_COOLDOWN_SECONDS, MIN_PRICE_EUR, MAX_PRICE_EUR, MIN_DAILY_VOLUME_EUR` | various |
| 1505-1506 | `SYNC_ENABLED, SYNC_INTERVAL_SECONDS` | `bool, int` |
| 1508-1519 | `BITVAVO_RATE_LIMIT_*, BITVAVO_ENDPOINT_LIMITS, BITVAVO_CACHE_TTLS` | various |
| 1521-1523 | `MAX_MARKETS_PER_SCAN, SCAN_WATCHDOG_SECONDS` | `int` |
| 1565-1573 | `HEARTBEAT_FILE, AI_HEARTBEAT_FILE, AI_HEARTBEAT_STALE_SECONDS, ALERT_WEBHOOK, TELEGRAM_WEBHOOK, ALERT_STALE_SECONDS, ALERT_DEDUPE_SECONDS, _last_alert` | various |
| 1395-1397 | `_EUR_BALANCE_CACHE, _EUR_BALANCE_CACHE_TTL` | `dict, int` |
| 1452 | `_LAST_MARKET_PERF_SAVE_TIME, _MARKET_PERF_SAVE_INTERVAL` | `float, int` |
| 1818 | `_LAST_ML_OPTIMIZER_RUN` | `float` |
| 3387-3389 | `_price_cache, _price_cache_ttl, PRICE_CACHE_FILE` | `dict, int, str` |

### Rate Limiting / Caching Internals
| Line(s) | Name | Type |
|---------|------|------|
| 1937-1938 | `_RATE_LIMIT_ENABLED` | `bool` |
| 1939 | `_rate_limit_lock` | `threading.Lock` |
| 1940 | `_rate_buckets` | `Dict[str, deque]` |
| 1941 | `_cache_lock` | `threading.Lock` |
| 1942 | `_cache_store` | `Dict[Tuple, Tuple]` |
| 1943 | `_DUST_SWEEP_TS` | `Dict[str, float]` |
| 2056-2067 | `_API_ERROR_LOG_SUPPRESS, _TRANSIENT_ERROR_PATTERNS, _NAME_RESOLUTION_PATTERNS` | various |
| 4261-4262 | `_signal_cache, _cache_ttl` | `dict, int` |
| 52-53 | `_ml_signal_history, _ml_veto_alert_threshold` | `deque, float` |
| 3651-3652 | `_MARKET_INFO_CACHE, _MARKET_INFO_TTL_SEC` | `dict, int` |
| 6496 | `DISABLE_DASHBOARD` | `bool` |
| 6507 | `BALANCE_API_FAILURE_TS` | `float` (implicit via `global`) |

---

## 3. FUNCTION GROUPS

---

### GROUP A — API/Cache Functions

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `safe_call` | 2093-2228 | `func, *args, **kwargs` | `CONFIG, BITVAVO_CACHE_TTLS, _cache_store, _rate_buckets, _RATE_LIMIT_ENABLED, risk_manager, metrics_collector` | `_CB_STATE (via globals()), _cache_store, _rate_buckets` |
| `_acquire_rate_slot` | 1963-2010 | `endpoint` | `_RATE_LIMIT_ENABLED, BITVAVO_RATE_LIMIT_CALLS, BITVAVO_RATE_LIMIT_WINDOW, BITVAVO_RATE_LIMIT_LOG_THRESHOLD, _rate_limit_lock, _rate_buckets, BITVAVO_ENDPOINT_LIMITS` | `_rate_buckets` |
| `_endpoint_limit` | 1945-1960 | `endpoint` | `BITVAVO_ENDPOINT_LIMITS, BITVAVO_RATE_LIMIT_CALLS, BITVAVO_RATE_LIMIT_WINDOW` | — |
| `_build_cache_key` | 2013-2024 | `name, args, kwargs` | — | — |
| `_cache_get` | 2027-2036 | `cache_key` | `_cache_lock, _cache_store` | `_cache_store` |
| `_cache_set` | 2039-2042 | `cache_key, ttl, payload` | `_cache_lock, _cache_store` | `_cache_store` |
| `_cache_invalidate` | 2045-2047 | `cache_key` | `_cache_lock, _cache_store` | `_cache_store` |
| `_emit_api_metric` | 2084-2095 | `api_name, duration_ms, result, code=None` | `metrics_collector` | — |
| `_should_log_api_error` | 2078-2082 | `signature, cooldown` | `_API_ERROR_LOG_SUPPRESS` | `_API_ERROR_LOG_SUPPRESS` |
| `get_candles` | 3171-3178 | `market, interval, limit, start, end` | `bitvavo` | — (calls `safe_call`) |
| `get_current_price` | 3395-3441 | `market, force_refresh=False` | `_price_cache, _price_cache_ttl, PRICE_CACHE_FILE, bitvavo, CONFIG` | `_price_cache`, disk `PRICE_CACHE_FILE` |
| `_fetch_price_once` | 3391-3396 | `market` | `bitvavo` | — (calls `safe_call`) |
| `get_eur_balance` | 1398-1436 | `force_refresh=False` | `_EUR_BALANCE_CACHE, _EUR_BALANCE_CACHE_TTL, bitvavo` | `_EUR_BALANCE_CACHE` |
| `get_ticker_best_bid_ask` | 3636-3641 | `m` | `bitvavo` | — (calls `safe_call`) |
| `spread_ok` | 3643-3647 | `m` | `MAX_SPREAD_PCT` | — |
| `get_market_info` | 3659-3669 | `market` | `_MARKET_INFO_CACHE, _MARKET_INFO_TTL_SEC, bitvavo` | `_MARKET_INFO_CACHE` |
| `get_supported_markets` | 2912-2917 | none | `bitvavo` | — (calls `safe_call`) |
| `get_24h_volume_eur` | 3106-3126 | `market` | `bitvavo` | — (calls `safe_call`) |
| `normalize_amount` | 1670-1695 | `market, amount` | — (calls `get_amount_step`, `get_amount_precision`) | — |
| `normalize_price` | 1697-1710 | `market, price` | — (calls `get_price_step`, `get_price_precision`) | — |
| `get_min_order_size` | 1597-1603 | `market` | `bitvavo` | — (calls `safe_call`) |
| `get_amount_precision` | 1605-1619 | `market` | — (calls `get_market_info`) | — |
| `get_price_precision` | 1621-1637 | `market` | — (calls `get_market_info`) | — |
| `get_amount_step` | 1639-1647 | `market` | — (calls `get_market_info`, `get_amount_precision`) | — |
| `get_price_step` | 1649-1657 | `market` | — (calls `get_market_info`, `get_price_precision`) | — |
| `get_expected_slippage` | 1718-1745 | `market, amount_eur, entry_price` | `bitvavo` | — (calls `safe_call`) |
| `get_expected_slippage_sell` | 1747-1771 | `market, amount_base, ref_price` | `bitvavo` | — (calls `safe_call`) |
| `sanitize_balance_payload` | 2230-2262 | `payload, *, source` | — | — |
| `_has_endpoint_limits` | 1913-1925 | none | `BITVAVO_ENDPOINT_LIMITS` | — |
| `_decimals_from_str_num` | 3671-3681 | `s` | — | — |
| `_now_ts` | 3654-3657 | none | — | — |
| `_iso_to_ms` | 3148-3170 | `val` | — | — |

### GROUP B — Signal Functions

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `signal_strength` | 4483-4530 | `m` | `_signal_cache, _cache_ttl` | `_signal_cache` |
| `_signal_strength_impl` | 4269-4481 | `m` | `CONFIG, SMA_SHORT, SMA_LONG, MACD_FAST, MACD_SLOW, MACD_SIGNAL, BREAKOUT_LOOKBACK, MIN_AVG_VOLUME_1M, RSI_MIN_BUY, RSI_MAX_BUY, _ml_signal_history, _ml_veto_alert_threshold` | `_ml_signal_history` |

**Dependencies:** Calls `get_candles` (Group A), `spread_ok` (Group A), all `core.indicators` functions, `modules.ml.predict_ensemble`, `modules.signals.evaluate_signal_pack`

### GROUP C — Trailing/Stop Functions

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `calculate_stop_levels` | 4532-4843 | `m, buy, high` | `open_trades, HARD_SL_BTCETH_PCT, HARD_SL_ALT_PCT, DEFAULT_TRAILING, TRAILING_ACTIVATION_PCT, ATR_MULTIPLIER, ATR_WINDOW_1M, SMA_SHORT, SMA_LONG, CONFIG, MAX_SPREAD_PCT` | Modifies `trade` dict in-place (trailing activation fields) |
| `check_stop_loss` | 3298-3332 | `market, trade, current_price, enabled=False` | — | — |
| `check_advanced_exit_strategies` | 3896-3983 | `trade, current_price` | `TAKE_PROFIT_ENABLED, PARTIAL_TP_LEVELS, FEE_TAKER` | Modifies `trade` dict in-place (`time_tighten`) |
| `_ensure_tp_flags` | 641-654 | `trade` | `PARTIAL_TP_LEVELS` | Modifies `trade` dict in-place |
| `_record_partial_tp_event` | 656-746 | `market, trade, level_idx, target_pct, sell_pct, configured_pct, sell_amount, sell_price, profit_eur, remaining_amount` | `PARTIAL_TP_HISTORY_FILE, PARTIAL_TP_STATS_FILE, _PARTIAL_TP_STATS_LOCK, _PARTIAL_TP_STATS` | `_PARTIAL_TP_STATS`, writes to files |
| `calculate_adaptive_tp` | 3180-3208 | `market, entry_price, volatility=None, trend_strength=None` | — | — |
| `get_partial_tp_stats` | 748-750 | none | `_PARTIAL_TP_STATS_LOCK, _PARTIAL_TP_STATS` | — |

**Dependencies:** Group C calls `get_candles`, `get_expected_slippage_sell`, `spread_ok` (Group A), and `core.indicators` functions

### GROUP D — Trade Execution

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `place_buy` | 3694-3839 | `market, eur_amount, entry_price, order_type=None` | `open_trades, CONFIG, MAX_OPEN_TRADES, DUST_TRADE_THRESHOLD_EUR, MAX_CLUSTER_*, TEST_MODE, LIVE_TRADING, ORDER_TYPE, OPERATOR_ID, PLACE_ORDERS_ENABLED, AUTO_USE_FULL_BALANCE, FULL_BALANCE_*, bitvavo, MIN_ORDER_EUR, FEE_MAKER` | `open_trades` (global keyword, but doesn't actually modify here) |
| `place_sell` | 3989-4136 | `market, amount_base, *, skip_dust=False` | `TEST_MODE, LIVE_TRADING, bitvavo, open_trades, closed_trades, trades_lock, PLACE_ORDERS_ENABLED, OPERATOR_ID, MAX_SPREAD_PCT, DUST_SWEEP_ENABLED, DUST_THRESHOLD_EUR, FEE_TAKER, BALANCE_API_FAILURE_TS` | `open_trades, closed_trades, BALANCE_API_FAILURE_TS` |
| `safe_sell` | 3885-3895 | `market, amount_base, precision` | — | — (delegates to `place_sell`) |
| `is_order_success` | 3867-3882 | `resp` | — | — |
| `cancel_open_buys_if_capped` | 2919-2985 | none | `CONFIG, DUST_TRADE_THRESHOLD_EUR, open_trades, bitvavo, OPERATOR_ID, metrics_collector` | — |
| `cancel_open_buys_by_age` | 2987-3075 | none | `CONFIG, open_trades, bitvavo, OPERATOR_ID, metrics_collector` | — |
| `should_execute_smart_dca` | 3210-3275 | `market, trade, current_price` | `CONFIG` | — |
| `sweep_all_dust_positions` | 4156-4206 | none | `DUST_SWEEP_ENABLED, DUST_THRESHOLD_EUR, TEST_MODE, LIVE_TRADING, bitvavo, open_trades` | — |
| `_cleanup_market_dust` | 4138-4154 | `market` | `DUST_SWEEP_ENABLED, DUST_THRESHOLD_EUR, TEST_MODE, LIVE_TRADING, _DUST_SWEEP_TS, open_trades, bitvavo` | `_DUST_SWEEP_TS` |
| `realized_profit` | 4845-4870 | `buy_price, sell_price, amount, buy_fee_pct=None, sell_fee_pct=None` | `FEE_TAKER` | — |
| `safety_buy` (async) | 6478-6493 | `m, amt_eur, entry_price` | — | — (calls `place_buy`) |

**Dependencies:** Group D extensively calls Group A functions (`safe_call`, `get_ticker_best_bid_ask`, `get_current_price`, `normalize_amount`, `get_min_order_size`, etc.)

### GROUP E — State Management

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `save_trades` | 2318-2484 | none | `open_trades, closed_trades, market_profits, trades_lock, TRADE_LOG, ARCHIVE_FILE, MAX_CLOSED, HEARTBEAT_FILE, AI_HEARTBEAT_FILE, DUST_TRADE_THRESHOLD_EUR, CONFIG, REINVEST_*, BASE_AMOUNT_EUR` | `closed_trades` (via archive), writes to disk |
| `load_trades` | 2486-2543 | none | `TRADE_LOG, CONFIG, DCA_MAX_BUYS, trades_lock` | `open_trades, closed_trades, market_profits` (global) |
| `sync_with_bitvavo` | 2569-2895 | none | `bitvavo, open_trades, closed_trades, market_profits, trades_lock, CONFIG, DCA_MAX_BUYS, DCA_DROP_PCT` | `open_trades, closed_trades`, writes to disk |
| `build_account_overview` | 885-965 | `*, balances, snapshot, eur_balance` | `DUST_TRADE_THRESHOLD_EUR` | — |
| `write_account_overview` | 967-981 | `*, balances, snapshot, eur_balance` | `ACCOUNT_OVERVIEW_FILE` | writes to disk |
| `build_portfolio_snapshot` | 840-870 | none | `open_trades` | — |
| `write_portfolio_snapshot` | 872-878 | none | `PORTFOLIO_SNAPSHOT_FILE` | writes to disk |
| `record_trade_performance` | 522-588 | `market, profit_eur, invested_eur, opened_ts, closed_ts, reason=None` | `MARKET_PERFORMANCE_LOCK, market_performance` | `market_performance` |
| `_record_market_stats_for_close` | 590-639 | `market, closed_entry, open_entry=None` | — | — (delegates to `record_trade_performance`) |
| `load_market_performance` | 476-490 | none | `MARKET_PERFORMANCE_FILE, MARKET_PERFORMANCE_LOCK` | `market_performance` (global) |
| `save_market_performance` | 492-516 | `force=False` | `_LAST_MARKET_PERFORMANCE_SAVE, MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS, MARKET_PERFORMANCE_FILE, MARKET_PERFORMANCE_LOCK, market_performance` | `_LAST_MARKET_PERFORMANCE_SAVE` |
| `publish_expectancy_metrics` | 773-835 | none | `closed_trades, CONFIG, EXPECTANCY_FILE, EXPECTANCY_HISTORY_FILE, DUST_TRADE_THRESHOLD_EUR` | writes to disk |
| `cleanup_trades` | 1897-1908 | none | `closed_trades, trades_lock, MAX_CLOSED, ARCHIVE_FILE` | `closed_trades` |
| `analyse_trades` | 3355-3371 | `trades` | — | — |
| `start_auto_sync` | 2264-2299 | `*, interval=60` | `synchronizer, SYNC_INTERVAL_SECONDS, _auto_sync_thread, trades_lock, open_trades, closed_trades, market_profits` | `_auto_sync_thread` (global) |
| `load_saldo_quarantine` | 2545-2578 | none | `CONFIG, TRADE_LOG` | — |
| `validate_and_repair_trades` | 1320-1392 | none | `open_trades, CONFIG` | `open_trades` entries |
| `validate_config` | 1278-1317 | none | `CONFIG` | — |
| `register_saldo_error` | 1859-1880 | `market, bitvavo_balance, trade_snapshot` | `CONFIG, file_lock` | writes to disk |
| `apply_dynamic_performance_tweaks` | 1773-1815 | none | `TRADE_LOG, CONFIG` | `CONFIG` |

### GROUP F — Bot Loop

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `bot_loop` (async) | 4875-5999 | none | Nearly ALL globals. Key: `RUNNING, STOP_AFTER_SECONDS, SLEEP_SECONDS, CONFIG, open_trades, closed_trades, TRADE_LOG, HEARTBEAT_FILE, AI_HEARTBEAT_FILE, DUST_TRADE_THRESHOLD_EUR, EXIT_MODE, STOP_LOSS_ENABLED, TRAILING_ACTIVATION_PCT, FEE_TAKER, MIN_ORDER_EUR, DCA_DROP_PCT, PARTIAL_TP_LEVELS, MAX_MARKETS_PER_SCAN, SCAN_WATCHDOG_SECONDS, MIN_SCORE_TO_BUY` | `scan_offset, open_trades, closed_trades, market_profits` |
| `open_trade_async` (async) | 6007-6475 | `score, m, price_now, s_short, eur_balance` | `CONFIG, open_trades, trades_lock, DUST_TRADE_THRESHOLD_EUR, OPERATOR_ID, bitvavo, risk_manager, TRADE_LOG, DCA_*, DEFAULT_TRAILING, TRAILING_ACTIVATION_PCT, FEE_TAKER, FEE_MAKER, ORDER_TYPE, SLIPPAGE_PCT, MAX_SPREAD_PCT, MIN_ORDER_EUR, BASE_AMOUNT_EUR` | `open_trades, LAST_OPEN_TRADE_TS, CONFIG._cb_*` |
| `open_trades_async` (async) | 5989-6005 | `scored, eur_balance` | `CONFIG, MIN_SCORE_TO_BUY, DUST_TRADE_THRESHOLD_EUR, MIN_PRICE_EUR, MAX_PRICE_EUR, MIN_DAILY_VOLUME_EUR, open_trades` | `LAST_OPEN_TRADE_TS` |
| `initialize_managers` | 6600-6774 | `force=False` | `CONFIG, bitvavo, TRADE_LOG, safe_call, log, etc.` | `dca_manager, dca_settings, liquidation_manager, monitoring_manager, synchronizer, risk_manager, metrics_collector, _auto_sync_thread, _managers_initialized, _monitor_threads_started` (all global) |

### GROUP G — Dashboard

| Function | Lines | Parameters | Globals READ | Globals WRITTEN |
|----------|-------|------------|-------------|-----------------|
| `start_dashboard` | 6498-6590 | `port=5000` | `DISABLE_DASHBOARD, HEARTBEAT_FILE, open_trades, closed_trades, trades_lock, bitvavo, DUST_TRADE_THRESHOLD_EUR` | — (starts Flask in thread) |

### UTILITY / HELPER FUNCTIONS (no group)

| Function | Lines | Parameters | Notes |
|----------|-------|------------|-------|
| `_as_bool` | 114-116 | `value, default` | **Delegates to `bot.helpers.as_bool`** |
| `_as_int` | 119-121 | `value, default` | **Delegates to `bot.helpers.as_int`** |
| `_as_float` | 138-140 | `value, default` | **Delegates to `bot.helpers.as_float`** |
| `_clamp` | 1712-1714 | `val, lo, hi` | **Delegates to `bot.helpers.clamp`** |
| `safe_mul` | 3443-3445 | `a, b` | **Delegates to `bot.helpers.safe_mul`** |
| `_coerce_positive_float` | 3448-3450 | `value` | **Delegates to `bot.helpers.coerce_positive_float`** |
| `_log_throttled` | 147-152 | `key, msg, interval, level` | `_log_throttle_ts` |
| `_call_with_timeout` | 155-174 | `func, args, timeout_seconds` | — |
| `_ensure_parent_dir` | 176-180 | `path` | — |
| `_resolve_path` | 249-252 | `path_like` | `PROJECT_ROOT` |
| `_run_runtime_health_checks` | 254-303 | none | `_LAST_HEALTH_CHECK_TS, CONFIG, HEALTH_CHECK_INTERVAL_SECONDS, TRADE_LOG, HEARTBEAT_FILE, BOT_HEALTH_PATH, bitvavo` | `_LAST_HEALTH_CHECK_TS` |
| `_get_watchlist_runtime_settings` | 33-42 | none | `CONFIG` | — |
| `is_watchlist_market` | 45-49 | `market` | `CONFIG` | — |
| `_prioritize_watchlist_markets` | 56-65 | `markets` | — | — |
| `_update_rl_after_trade` | 124-131 | `closed_entry` | — | — |
| `archive_trade` | 134-138 | `**closed_entry` | — | — |
| `_append_trade_pnl_jsonl` | 208-244 | `closed_entry` | `TRADE_PNL_HISTORY_FILE` | writes to disk |
| `_event_hooks_paused` | 424-440 | `market` | `EVENT_STATE, _EVENT_PAUSE_CACHE` | `_EVENT_PAUSE_CACHE` |
| `_event_hook_status_payload` | 442-462 | none | `EVENT_STATE` | — |
| `_get_market_performance_snapshot` | 983-989 | `market` | `MARKET_PERFORMANCE_LOCK, market_performance` | — |
| `_filter_markets_by_performance` | 1002-1068 | `markets` | `MARKET_PERFORMANCE_FILTER_ENABLED, market_performance, MARKET_PERFORMANCE_*` | `_MARKET_PERF_FILTER_LOG, _MARKET_PERF_BLOCK_TIMESTAMPS` |
| `get_market_position_size_multiplier` | 1071-1098 | `market, stats=None` | `MARKET_PERFORMANCE_SIZE_BIAS_ENABLED, MARKET_PERFORMANCE_*` | — |
| `get_ai_regime_bias` | 1100-1144 | none | `_AI_REGIME_CACHE, AI_REGIME_*, AI_HEARTBEAT_FILE, AI_HEARTBEAT_STALE_SECONDS` | `_AI_REGIME_CACHE` |
| `_init_perf_sampler` | 1146-1163 | none | `_PerfSampler, CONFIG` | — |
| `maybe_save_market_performance` | 1442-1449 | none | `_LAST_MARKET_PERF_SAVE_TIME, _MARKET_PERF_SAVE_INTERVAL` | `_LAST_MARKET_PERF_SAVE_TIME` |
| `send_alert` | 1575-1593 | `msg` | `_last_alert, TELEGRAM_WEBHOOK, ALERT_WEBHOOK, ALERT_DEDUPE_SECONDS` | `_last_alert` |
| `_start_heartbeat_monitor` | 1595-1600 | none | `monitoring_manager, ALERT_STALE_SECONDS` | — |
| `_start_heartbeat_writer` | 1602-1614 | `interval=30` | `monitoring_manager, open_trades, DUST_TRADE_THRESHOLD_EUR, CONFIG` | — |
| `_start_reservation_watchdog` | 1616-1620 | `interval=30` | `monitoring_manager` | — |
| `get_markets_to_trade` | 3077-3104 | none | `CONFIG, EXCLUDED_MARKETS` | — |
| `get_active_grid_markets` | 2897-2911 | none | — | — |
| `_resolve_dust_threshold` | 3403-3410 | `override=None` | `DUST_TRADE_THRESHOLD_EUR` | — |
| `_compute_trade_value_eur` | 3413-3448 | `market, trade, *, price_cache` | — | — |
| `_iter_trade_values` | 3451-3457 | `price_cache=None` | `open_trades` | — |
| `get_true_invested_eur` | 3460-3509 | `trade, market=''` | — | Modifies `trade` dict in-place |
| `is_dust_trade` | 3512-3524 | `market, *, threshold, price_cache` | `open_trades` | — |
| `count_active_open_trades` | 3527-3537 | `threshold=None, *, price_cache` | — | — |
| `get_pending_bitvavo_orders` | 3540-3574 | none | `bitvavo, open_trades` | — |
| `count_pending_bitvavo_orders` | 3577-3578 | none | — | — |
| `count_total_trade_slots_used` | 3581-3585 | none | `DUST_TRADE_THRESHOLD_EUR` | — |
| `count_dust_trades` | 3587-3596 | `threshold=None` | — | — |
| `current_open_exposure_eur` | 3601-3609 | `include_dust=False` | — | — |
| `estimate_max_eur_per_trade` | 3612-3617 | none | `BASE_AMOUNT_EUR, AUTO_USE_FULL_BALANCE, FULL_BALANCE_MAX_EUR` | — |
| `estimate_max_total_eur` | 3620-3624 | none | `CONFIG, MAX_TOTAL_EXPOSURE_EUR` | — |
| `_compute_win_loss_streaks` | 752-770 | `series` | — | — |
| `saldo_flood_guard` | 1889-1892 | none | `liquidation_manager, open_trades, closed_trades, market_profits` | — |
| `free_capacity_if_needed` | 1894-1900 | none | `liquidation_manager, open_trades, closed_trades, market_profits` | — |
| `maybe_run_ml_optimizer` (async) | 1820-1837 | none | `_LAST_ML_OPTIMIZER_RUN, CONFIG` | `_LAST_ML_OPTIMIZER_RUN` |
| `_load_partial_tp_stats_cache` | 1260-1271 | none | `PARTIAL_TP_STATS_FILE, _PARTIAL_TP_STATS_LOCK, _PARTIAL_TP_STATS` | `_PARTIAL_TP_STATS` |
| Market reservation helpers (4 fns) | 334-351 | `market` or none | `_reservation_manager` | — |
| `_get_pending_markets_dict` | 353-355 | none | `_reservation_manager` | — |
| `_get_pending_saldo_count` | 1843-1849 | none | — | — |

---

## 4. INTER-GROUP DEPENDENCIES

```
GROUP A (API/Cache)
  └─ No group dependencies (foundational layer)
  └─ Uses: bitvavo client, CONFIG, rate-limit/cache internals

GROUP B (Signals)
  └─ Depends on: GROUP A (get_candles, spread_ok)
  └─ Uses: core.indicators, modules.ml, modules.signals

GROUP C (Trailing/Stop)
  └─ Depends on: GROUP A (get_candles, get_expected_slippage_sell)
  └─ Uses: core.indicators, open_trades (read), PARTIAL_TP_* globals

GROUP D (Trade Execution)
  └─ Depends on: GROUP A (safe_call, get_ticker_best_bid_ask, get_current_price,
                          normalize_amount, get_min_order_size, sanitize_balance_payload)
  └─ Depends on: GROUP C (_ensure_tp_flags — called by place_sell close logic)
  └─ Depends on: GROUP E (save_trades, cleanup_trades — called after trade close)
  └─ Uses: open_trades, closed_trades (read+write), bitvavo client

GROUP E (State Management)
  └─ Depends on: GROUP A (safe_call, get_current_price — in sync_with_bitvavo)
  └─ Depends on: GROUP D (place_buy — indirect via manager contexts)
  └─ Uses: open_trades, closed_trades, market_profits (read+write)
  └─ Disk I/O: TRADE_LOG, ARCHIVE_FILE, various JSON files

GROUP F (Bot Loop)
  └─ Depends on: ALL GROUPS (A, B, C, D, E)
  └─ Orchestrates: signal scanning, trade management, exit logic

GROUP G (Dashboard)
  └─ Depends on: GROUP A (get_current_price), GROUP E (open_trades, closed_trades)
  └─ Read-only access to trade state
```

---

## 5. FUNCTIONS DELEGATING TO bot.helpers (Phase 1 Extractions)

| Wrapper in trailing_bot.py | Delegates to | Line |
|---------------------------|-------------|------|
| `_as_bool(value, default)` | `bot.helpers.as_bool` | 114-116 |
| `_as_int(value, default)` | `bot.helpers.as_int` | 119-121 |
| `_as_float(value, default)` | `bot.helpers.as_float` | 138-140 |
| `_clamp(val, lo, hi)` | `bot.helpers.clamp` | 1712-1714 |
| `safe_mul(a, b)` | `bot.helpers.safe_mul` | 3443-3445 |
| `_coerce_positive_float(value)` | `bot.helpers.coerce_positive_float` | 3448-3450 |

All 6 wrappers use lazy `from bot.helpers import X` inside the function body.

---

## 6. MODULE-LEVEL EXECUTION (Side Effects at Import)

| Line(s) | What happens |
|---------|-------------|
| 23-24 | `load_dotenv()` |
| 26-29 | `CONFIG = load_config() or {}` |
| 79 | `import numpy as np` |
| 306-311 | `_PerfSampler` import attempt |
| 416-420 | `EVENT_STATE = EventState()` attempt |
| 1157 | `perf_sampler = _init_perf_sampler()` |
| 1160-1161 | `load_market_performance()` |
| 1271 | `_load_partial_tp_stats_cache()` |
| 6780-6781 | `initialize_managers()` — initializes ALL manager singletons |

---

## 7. EXTRACTION RISK NOTES

### HIGH RISK (shared mutable state)
- `open_trades`, `closed_trades`, `market_profits` — used by Groups D, E, F, G
- `trades_lock` — must be accessible to all modules touching trade state
- `CONFIG` — read by virtually everything, written by `apply_dynamic_performance_tweaks`, `save_trades`
- `_reservation_manager` — used by bot_loop and open_trade_async

### MEDIUM RISK (module-level caches)
- `_price_cache`, `_MARKET_INFO_CACHE`, `_signal_cache` — if functions are moved, caches must stay shared
- `_cache_store` (rate limit cache) — tied to `safe_call`
- `_PARTIAL_TP_STATS` — written by Group C, read by Group E

### LOW RISK (pure functions, safe to extract)
- All `bot.helpers` delegates (already extracted)
- `analyse_trades`, `_compute_win_loss_streaks`, `realized_profit`
- `_decimals_from_str_num`, `_iso_to_ms`, `_resolve_path`, `_ensure_parent_dir`
- `sanitize_balance_payload`, `is_order_success`
- `normalize_amount`, `normalize_price` (depend on Group A but through well-defined calls)
