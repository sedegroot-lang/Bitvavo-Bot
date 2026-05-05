"""AI Supervisor constants — extracted from ai_supervisor.py (Fase 5 refactor).

Contains: LIMITS, SECTOR_DEFINITIONS, CONFIG_VALIDATION_RULES, COOLDOWN_MINUTES.

Bounds calibrated for a ~€250 micro-account (2025-Q1).
Rule of thumb: no single parameter should risk more than 10% of account
in one shot, and total exposure is capped at ~80% of equity.
"""

# Bounds and deltas for parameter suggestions
LIMITS = {
    # Trailing & Exit parameters
    "DEFAULT_TRAILING": {"min": 0.005, "max": 0.10, "max_delta": 0.01},
    "TRAILING_ACTIVATION_PCT": {"min": 0.01, "max": 0.05, "max_delta": 0.005},
    "HARD_SL_ALT_PCT": {"min": 0.06, "max": 0.25, "max_delta": 0.015},
    "HARD_SL_BTCETH_PCT": {"min": 0.06, "max": 0.20, "max_delta": 0.015},
    # Take-Profit targets
    "TAKE_PROFIT_ENABLED": {"type": "bool"},
    "TAKE_PROFIT_TARGET_1": {"min": 0.02, "max": 0.06, "max_delta": 0.005},
    "TAKE_PROFIT_TARGET_2": {"min": 0.04, "max": 0.10, "max_delta": 0.01},
    "TAKE_PROFIT_TARGET_3": {"min": 0.06, "max": 0.15, "max_delta": 0.015},
    # Entry signals — RSI
    "RSI_MIN_BUY": {"min": 20, "max": 35, "max_delta": 2},
    "RSI_MAX_BUY": {"min": 55, "max": 75, "max_delta": 3},
    "RSI_DCA_THRESHOLD": {"min": 50, "max": 70, "max_delta": 5},
    # Volatility sizing
    "VOLATILITY_SIZING_ENABLED": {"type": "bool"},
    "VOLATILITY_WINDOW": {"min": 10, "max": 30, "max_delta": 5},
    "VOLATILITY_MULTIPLIER": {"min": 1.0, "max": 2.5, "max_delta": 0.25},
    # Enhanced entry filters
    "MIN_VOLUME_24H_EUR": {"min": 50000, "max": 200000, "max_delta": 25000},
    "MIN_PRICE_CHANGE_PCT": {"min": 0.005, "max": 0.03, "max_delta": 0.005},
    # DCA parameters — capped for micro-account
    "DCA_SIZE_MULTIPLIER": {"min": 0.5, "max": 1.5, "max_delta": 0.1},
    "DCA_MAX_BUYS": {"min": 1, "max": 3, "max_delta": 1},
    "DCA_STEP_MULTIPLIER": {"min": 0.5, "max": 2.0, "max_delta": 0.1},
    "DCA_MAX_BUYS_PER_ITERATION": {"min": 1, "max": 3, "max_delta": 1},
    "DCA_DROP_PCT": {"min": 0.03, "max": 0.15, "max_delta": 0.02},
    "DCA_AMOUNT_EUR": {"min": 3, "max": 15, "max_delta": 3},
    # Position sizing — micro-account safe
    "BASE_AMOUNT_EUR": {"min": 5, "max": 25, "max_delta": 3},
    "AUTO_USE_FULL_BALANCE": {"type": "bool"},
    # MAX_TOTAL_EXPOSURE_EUR: removed from AI control — managed manually at 9999
    # Trade management
    "MAX_OPEN_TRADES": {"min": 3, "max": 6, "max_delta": 1},  # FLOOR=3, never reduce below 3
    "MIN_SCORE_TO_BUY": {"min": 6.0, "max": 11.0, "max_delta": 0.5},
    "OPEN_TRADE_COOLDOWN_SECONDS": {"min": 0, "max": 3600, "max_delta": 600},
    # Technical indicators
    "SMA_SHORT": {"min": 5, "max": 15, "max_delta": 2},
    "SMA_LONG": {"min": 20, "max": 50, "max_delta": 5},
    "ATR_MULTIPLIER": {"min": 1.5, "max": 3.0, "max_delta": 0.2},
    # Risk management
    "MAX_SPREAD_PCT": {"min": 0.002, "max": 0.008, "max_delta": 0.001},
    "MIN_BALANCE_EUR": {"min": 5, "max": 50, "max_delta": 5},
    "MIN_AVG_VOLUME_1M": {"min": 100, "max": 300, "max_delta": 25},
    # Profit reinvestment — micro-account
    "REINVEST_PORTION": {"min": 0.3, "max": 0.9, "max_delta": 0.1},
    "REINVEST_CAP": {"min": 15, "max": 50, "max_delta": 5},
    # Partial Take-Profit sell percentages
    "PARTIAL_TP_SELL_PCT_1": {"min": 0.2, "max": 0.6, "max_delta": 0.05},
    "PARTIAL_TP_SELL_PCT_2": {"min": 0.2, "max": 0.5, "max_delta": 0.05},
    "PARTIAL_TP_SELL_PCT_3": {"min": 0.15, "max": 0.4, "max_delta": 0.05},
    # Trailing entry parameters
    "TRAILING_ENTRY_ENABLED": {"type": "bool"},
    "TRAILING_ENTRY_PULLBACK_PCT": {"min": 0.005, "max": 0.03, "max_delta": 0.005},
    "TRAILING_ENTRY_TIMEOUT_S": {"min": 30, "max": 300, "max_delta": 30},
    # Performance filter tuning (canonical MARKET_PERFORMANCE_* keys)
    # NOTE: both key variants are mapped so config aliases work correctly
    "MARKET_PERFORMANCE_MIN_TRADES": {"min": 3, "max": 10, "max_delta": 1},
    "PERFORMANCE_FILTER_MIN_TRADES": {"min": 3, "max": 10, "max_delta": 1},
    "PERFORMANCE_FILTER_MIN_WINRATE": {"min": 0.2, "max": 0.5, "max_delta": 0.05},
    "MARKET_PERFORMANCE_MAX_CONSEC_LOSSES": {"min": 2, "max": 6, "max_delta": 1},
    "PERFORMANCE_FILTER_MAX_CONSEC_LOSSES": {"min": 2, "max": 6, "max_delta": 1},
    # Watchlist sizing
    "WATCHLIST_MICRO_SIZE_EUR": {"min": 3, "max": 10, "max_delta": 1},
    "WATCHLIST_CONFIDENCE_THRESHOLD": {"min": 0.5, "max": 0.8, "max_delta": 0.05},
}

COOLDOWN_MINUTES = 90  # 1.5 hours

CONFIG_VALIDATION_RULES = {
    "DEFAULT_TRAILING": {"type": (int, float)},
    "TRAILING_ACTIVATION_PCT": {"type": (int, float)},
    "MAX_TOTAL_EXPOSURE_EUR": {"type": (int, float)},
    "BASE_AMOUNT_EUR": {"type": (int, float)},
    "MIN_SCORE_TO_BUY": {"type": (int, float)},
    "TAKE_PROFIT_TARGET_1": {"type": (int, float)},
    "TAKE_PROFIT_TARGET_2": {"type": (int, float)},
    "TAKE_PROFIT_TARGET_3": {"type": (int, float)},
    "VOLATILITY_WINDOW": {"type": int},
    "VOLATILITY_MULTIPLIER": {"type": (int, float)},
    "MIN_VOLUME_24H_EUR": {"type": (int, float)},
    "MIN_PRICE_CHANGE_PCT": {"type": (int, float)},
    "AI_REGIME_RECOMMENDATIONS": {"type": (bool,)},
    "AI_PORTFOLIO_ANALYSIS": {"type": (bool,)},
    "DCA_DYNAMIC": {"type": (bool,)},
    "DCA_STEP_MULTIPLIER": {"type": (int, float)},
    "DCA_MAX_BUYS_PER_ITERATION": {"type": int},
}

# Sector categorization for correlation management
SECTOR_DEFINITIONS = {
    "Layer1": [
        "BTC-EUR",
        "ETH-EUR",
        "XRP-EUR",
        "ADA-EUR",
        "LTC-EUR",
        "ALGO-EUR",
        "NEAR-EUR",
        "EGLD-EUR",
        "FLOW-EUR",
        "TRX-EUR",
        "XTZ-EUR",
        "EOS-EUR",
        "AVAX-EUR",
        "SOL-EUR",
    ],
    "DeFi": [
        "UNI-EUR",
        "AAVE-EUR",
        "LDO-EUR",
        "GMX-EUR",
        "CRV-EUR",
        "1INCH-EUR",
        "COMP-EUR",
        "YFI-EUR",
        "BAL-EUR",
        "SUSHI-EUR",
        "CAKE-EUR",
        "SNX-EUR",
    ],
    "Layer2": ["POL-EUR", "IMX-EUR", "LRC-EUR", "METIS-EUR", "ARB-EUR", "OP-EUR"],
    "Meme": ["DOGE-EUR", "SHIB-EUR", "PEPE-EUR"],
    "AI": ["FET-EUR", "AGIX-EUR", "OCEAN-EUR"],
    "Gaming": ["AXS-EUR", "SAND-EUR", "MANA-EUR", "ENJ-EUR", "GALA-EUR"],
}
