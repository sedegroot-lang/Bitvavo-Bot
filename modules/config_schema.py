"""modules.config_schema – Typed config validation for bot_config.json.

Validates config keys on load, logs warnings for invalid values,
and coerces to safe defaults when possible. No external dependencies.

Usage:
    from modules.config_schema import validate_config
    issues = validate_config(config_dict)
    # issues = [{'key': ..., 'issue': ..., 'severity': 'warning'|'error'}, ...]
"""

from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Schema definition — each key mapped to (type, default, min, max, description)
# ---------------------------------------------------------------------------

_SCHEMA: Dict[str, Dict[str, Any]] = {
    # === Core trading ===
    "BASE_AMOUNT_EUR": {"type": "float", "default": 6.0, "min": 5.0, "max": 500.0, "desc": "EUR per trade"},
    "MAX_OPEN_TRADES": {"type": "int", "default": 10, "min": 1, "max": 50, "desc": "Max simultaneous trades"},
    "MAX_TOTAL_EXPOSURE_EUR": {
        "type": "float",
        "default": 200.0,
        "min": 10.0,
        "max": 10000.0,
        "desc": "Max total EUR in trades",
    },
    "MIN_BALANCE_EUR": {"type": "float", "default": 10.0, "min": 0.0, "max": 1000.0, "desc": "EUR to keep as reserve"},
    "MIN_ORDER_EUR": {"type": "float", "default": 5.0, "min": 5.0, "max": 100.0, "desc": "Minimum order size EUR"},
    "SLEEP_SECONDS": {"type": "int", "default": 60, "min": 10, "max": 600, "desc": "Seconds between scan cycles"},
    # === Signal scoring ===
    "SMA_SHORT": {"type": "int", "default": 20, "min": 3, "max": 100, "desc": "Short SMA period"},
    "SMA_LONG": {"type": "int", "default": 50, "min": 10, "max": 500, "desc": "Long SMA period"},
    "MACD_FAST": {"type": "int", "default": 12, "min": 2, "max": 50, "desc": "MACD fast period"},
    "MACD_SLOW": {"type": "int", "default": 26, "min": 5, "max": 100, "desc": "MACD slow period"},
    "MACD_SIGNAL": {"type": "int", "default": 9, "min": 2, "max": 50, "desc": "MACD signal period"},
    "BREAKOUT_LOOKBACK": {"type": "int", "default": 50, "min": 5, "max": 200, "desc": "Breakout lookback candles"},
    "MIN_SCORE_TO_BUY": {
        "type": "float",
        "default": 7.0,
        "min": 0.0,
        "max": 15.0,
        "desc": "Min signal score to open trade",
    },
    "MIN_AVG_VOLUME_1M": {
        "type": "float",
        "default": 500.0,
        "min": 0.0,
        "max": 100000.0,
        "desc": "Min avg volume EUR/1m candle",
    },
    "RSI_MIN_BUY": {"type": "float", "default": 35.0, "min": 0.0, "max": 100.0, "desc": "Min RSI for entry"},
    "RSI_MAX_BUY": {"type": "float", "default": 65.0, "min": 0.0, "max": 100.0, "desc": "Max RSI for entry"},
    "RSI_DCA_THRESHOLD": {
        "type": "float",
        "default": 100.0,
        "min": 50.0,
        "max": 100.0,
        "desc": "RSI drempel voor DCA (100=altijd DCA)",
    },
    "DCA_SYNC_COOLDOWN_SEC": {
        "type": "float",
        "default": 300.0,
        "min": 0.0,
        "max": 1800.0,
        "desc": "Seconden DCA-pauze na sync",
    },
    # === Trailing stop ===
    "DEFAULT_TRAILING": {
        "type": "float",
        "default": 0.032,
        "min": 0.001,
        "max": 0.50,
        "desc": "Default trailing stop %",
    },
    "TRAILING_ACTIVATION_PCT": {
        "type": "float",
        "default": 0.045,
        "min": 0.001,
        "max": 0.20,
        "desc": "Trailing activation threshold",
    },
    "ATR_MULTIPLIER": {"type": "float", "default": 2.0, "min": 0.1, "max": 10.0, "desc": "ATR multiplier for stops"},
    "ATR_WINDOW_1M": {"type": "int", "default": 14, "min": 5, "max": 60, "desc": "ATR window (1m candles)"},
    "HARD_SL_ALT_PCT": {"type": "float", "default": 0.10, "min": 0.01, "max": 0.50, "desc": "Hard SL for altcoins"},
    "HARD_SL_BTCETH_PCT": {"type": "float", "default": 0.10, "min": 0.01, "max": 0.50, "desc": "Hard SL for BTC/ETH"},
    "MAX_SPREAD_PCT": {
        "type": "float",
        "default": 0.005,
        "min": 0.001,
        "max": 0.05,
        "desc": "Max spread to enter trade",
    },
    # === Fees ===
    "FEE_MAKER": {"type": "float", "default": 0.0015, "min": 0.0, "max": 0.01, "desc": "Maker fee %"},
    "FEE_TAKER": {"type": "float", "default": 0.0025, "min": 0.0, "max": 0.01, "desc": "Taker fee %"},
    "SLIPPAGE_PCT": {"type": "float", "default": 0.001, "min": 0.0, "max": 0.05, "desc": "Expected slippage %"},
    # === Take profit ===
    "TAKE_PROFIT_ENABLED": {"type": "bool", "default": True, "desc": "Enable partial TP"},
    # === DCA ===
    "DCA_ENABLED": {"type": "bool", "default": False, "desc": "Enable DCA"},
    "DCA_MAX_BUYS": {"type": "int", "default": 6, "min": 1, "max": 20, "desc": "Max DCA entries"},
    "DCA_HYBRID": {"type": "bool", "default": False, "desc": "Hybrid DCA: avg-down in loss, pyramid in profit"},
    "DCA_PYRAMID_UP": {"type": "bool", "default": False, "desc": "Enable pyramid-up DCA"},
    "DCA_PYRAMID_MIN_PROFIT_PCT": {
        "type": "float",
        "default": 0.03,
        "min": 0.01,
        "max": 0.20,
        "desc": "Min profit % for pyramid",
    },
    "DCA_PYRAMID_SCALE_DOWN": {
        "type": "float",
        "default": 0.7,
        "min": 0.1,
        "max": 1.0,
        "desc": "Scale factor per pyramid add",
    },
    "DCA_PYRAMID_MAX_ADDS": {
        "type": "int",
        "default": 2,
        "min": 0,
        "max": 10,
        "desc": "Max pyramid additions",
    },  # 0 = disabled
    "DCA_DROP_PCT": {
        "type": "float",
        "default": 0.06,
        "min": 0.01,
        "max": 0.30,
        "desc": "Price drop % for DCA trigger",
    },
    "DCA_AMOUNT_EUR": {"type": "float", "default": 5.0, "min": 5.0, "max": 100.0, "desc": "EUR per DCA buy"},
    # === Risk management ===
    "RISK_CIRCUIT_BREAKER_EUR": {
        "type": "float",
        "default": 50.0,
        "min": 10.0,
        "max": 1000.0,
        "desc": "Portfolio drawdown circuit breaker EUR",
    },
    "RISK_DAILY_LOSS_LIMIT_EUR": {
        "type": "float",
        "default": 25.0,
        "min": 5.0,
        "max": 500.0,
        "desc": "Max daily loss EUR",
    },
    "RISK_KELLY_ENABLED": {"type": "bool", "default": True, "desc": "Enable Kelly position sizing"},
    "RISK_KELLY_FRACTION": {
        "type": "float",
        "default": 0.5,
        "min": 0.1,
        "max": 1.0,
        "desc": "Fraction of Kelly to use",
    },
    # === Dust / cleanup ===
    "DUST_SWEEP_ENABLED": {"type": "bool", "default": True, "desc": "Enable dust sweeping"},
    "DUST_THRESHOLD_EUR": {"type": "float", "default": 1.0, "min": 0.0, "max": 10.0, "desc": "EUR threshold for dust"},
    "DUST_TRADE_THRESHOLD_EUR": {
        "type": "float",
        "default": 5.0,
        "min": 0.1,
        "max": 50.0,
        "desc": "EUR threshold for dust trade",
    },
    # === Modes ===
    "TEST_MODE": {"type": "bool", "default": False, "desc": "Test mode (no real orders)"},
    "LIVE_TRADING": {"type": "bool", "default": True, "desc": "Enable live trading"},
    # === Sync ===
    "SYNC_ENABLED": {"type": "bool", "default": True, "desc": "Enable sync validation"},
    "SYNC_INTERVAL_SECONDS": {"type": "int", "default": 60, "min": 5, "max": 600, "desc": "Sync check interval"},
    # === Lists ===
    "WHITELIST_MARKETS": {"type": "list", "default": [], "desc": "Markets to trade"},
    "EXCLUDED_MARKETS": {"type": "list", "default": [], "desc": "Markets to exclude"},
}


# ---------------------------------------------------------------------------
# Cross-field validation rules
# ---------------------------------------------------------------------------


def _cross_validate(cfg: dict) -> List[Dict[str, str]]:
    """Check logical consistency between related config keys."""
    issues: List[Dict[str, str]] = []

    def _num(key: str, default: float) -> float:
        try:
            return float(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    # SMA_SHORT must be < SMA_LONG
    sma_s = _num("SMA_SHORT", 20)
    sma_l = _num("SMA_LONG", 50)
    if sma_s >= sma_l:
        issues.append(
            {
                "key": "SMA_SHORT/SMA_LONG",
                "issue": f"SMA_SHORT ({sma_s}) >= SMA_LONG ({sma_l}) — crossing logic broken",
                "severity": "error",
            }
        )

    # MACD_FAST must be < MACD_SLOW
    macd_f = _num("MACD_FAST", 12)
    macd_s = _num("MACD_SLOW", 26)
    if macd_f >= macd_s:
        issues.append(
            {
                "key": "MACD_FAST/MACD_SLOW",
                "issue": f"MACD_FAST ({macd_f}) >= MACD_SLOW ({macd_s}) — MACD broken",
                "severity": "error",
            }
        )

    # BASE_AMOUNT_EUR should be >= MIN_ORDER_EUR
    base = _num("BASE_AMOUNT_EUR", 6.0)
    min_order = _num("MIN_ORDER_EUR", 5.0)
    if base < min_order:
        issues.append(
            {
                "key": "BASE_AMOUNT_EUR",
                "issue": f"BASE_AMOUNT_EUR ({base}) < MIN_ORDER_EUR ({min_order}) — trades will fail",
                "severity": "error",
            }
        )

    # MAX_TOTAL_EXPOSURE must be >= BASE_AMOUNT_EUR
    max_exp = _num("MAX_TOTAL_EXPOSURE_EUR", 200.0)
    if max_exp < base:
        issues.append(
            {
                "key": "MAX_TOTAL_EXPOSURE_EUR",
                "issue": f"MAX_TOTAL_EXPOSURE_EUR ({max_exp}) < BASE_AMOUNT_EUR ({base})",
                "severity": "error",
            }
        )

    # RSI_MIN_BUY must be < RSI_MAX_BUY
    rsi_min = _num("RSI_MIN_BUY", 35.0)
    rsi_max = _num("RSI_MAX_BUY", 65.0)
    if rsi_min >= rsi_max:
        issues.append(
            {
                "key": "RSI_MIN_BUY/RSI_MAX_BUY",
                "issue": f"RSI_MIN_BUY ({rsi_min}) >= RSI_MAX_BUY ({rsi_max}) — no valid RSI range",
                "severity": "warning",
            }
        )

    # TEST_MODE and LIVE_TRADING shouldn't both be True
    test_mode = cfg.get("TEST_MODE", False)
    live = cfg.get("LIVE_TRADING", True)
    if test_mode and live:
        issues.append(
            {
                "key": "TEST_MODE/LIVE_TRADING",
                "issue": "Both TEST_MODE and LIVE_TRADING are True — TEST_MODE takes precedence",
                "severity": "warning",
            }
        )

    # TRAILING_ACTIVATION_PCT vs DEFAULT_TRAILING sanity check
    # With stepped trailing, activation < trail is valid (activate early, trail wide,
    # then tighten). The real protection comes from breakeven lock + cost_buffer.
    # Only flag if trail is unreasonably large relative to activation.
    trail_act = _num("TRAILING_ACTIVATION_PCT", 0.025)
    trail_pct = _num("DEFAULT_TRAILING", 0.04)
    _has_trail = "TRAILING_ACTIVATION_PCT" in cfg or "DEFAULT_TRAILING" in cfg
    if _has_trail and trail_act > 0 and trail_pct > 0 and trail_pct > 3 * trail_act:
        issues.append(
            {
                "key": "TRAILING_ACTIVATION_PCT/DEFAULT_TRAILING",
                "issue": f"DEFAULT_TRAILING ({trail_pct}) > 3× TRAILING_ACTIVATION_PCT ({trail_act}) — trail distance may be too wide relative to activation",
                "severity": "warning",
            }
        )

    # DCA_PYRAMID_MIN_PROFIT_PCT should be reasonable
    if cfg.get("DCA_PYRAMID_UP") and cfg.get("DCA_ENABLED"):
        pyr_min = _num("DCA_PYRAMID_MIN_PROFIT_PCT", 0.03)
        if pyr_min < 0.01:
            issues.append(
                {
                    "key": "DCA_PYRAMID_MIN_PROFIT_PCT",
                    "issue": f"Pyramid min profit {pyr_min * 100:.1f}% is very low — risk of pyramiding into reversal",
                    "severity": "warning",
                }
            )

    # GRID_TRADING validation (nested object)
    grid_cfg = cfg.get("GRID_TRADING", {})
    if isinstance(grid_cfg, dict) and grid_cfg.get("enabled"):
        grid_inv = float(grid_cfg.get("investment_per_grid", 50) or 50)
        grid_max = int(grid_cfg.get("max_grids", 2) or 2)
        if grid_inv < 10:
            issues.append(
                {
                    "key": "GRID_TRADING.investment_per_grid",
                    "issue": f"Grid investment €{grid_inv} < €10 minimum",
                    "severity": "error",
                }
            )
        if grid_max > 5:
            issues.append(
                {
                    "key": "GRID_TRADING.max_grids",
                    "issue": f"max_grids={grid_max} > 5 — excessive grid exposure",
                    "severity": "warning",
                }
            )

    # BUDGET_RESERVATION validation (nested object)
    budget_cfg = cfg.get("BUDGET_RESERVATION", {})
    if isinstance(budget_cfg, dict) and budget_cfg.get("enabled"):
        _g = budget_cfg.get("grid_pct")
        grid_pct = float(_g if _g is not None else 20)
        _t = budget_cfg.get("trailing_pct")
        trail_pct_b = float(_t if _t is not None else 55)
        _r = budget_cfg.get("reserve_pct")
        reserve = float(_r if _r is not None else 25)
        total = grid_pct + trail_pct_b + reserve
        if abs(total - 100) > 1:
            issues.append(
                {
                    "key": "BUDGET_RESERVATION",
                    "issue": f"Budget allocation sums to {total}% (expected 100%)",
                    "severity": "error",
                }
            )

    return issues


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------


def validate_config(cfg: dict, *, coerce: bool = False) -> List[Dict[str, str]]:
    """Validate a config dict against the schema.

    Parameters
    ----------
    cfg : dict
        The configuration dictionary to validate.
    coerce : bool
        If True, fix invalid values in-place with defaults. Default False.

    Returns
    -------
    list of dict
        Each dict has keys: 'key', 'issue', 'severity' ('warning' | 'error').
    """
    issues: List[Dict[str, str]] = []

    for key, spec in _SCHEMA.items():
        if key not in cfg:
            continue  # Missing keys are OK — defaults are used elsewhere

        value = cfg[key]
        expected_type = spec["type"]

        # Type check
        if expected_type == "float":
            try:
                val = float(value)
            except (TypeError, ValueError):
                issues.append(
                    {"key": key, "issue": f"Expected float, got {type(value).__name__}: {value!r}", "severity": "error"}
                )
                if coerce:
                    cfg[key] = spec["default"]
                continue
            # Range check
            if "min" in spec and val < spec["min"]:
                issues.append({"key": key, "issue": f"Value {val} < min {spec['min']}", "severity": "warning"})
                if coerce:
                    cfg[key] = max(spec["min"], val)
            if "max" in spec and val > spec["max"]:
                issues.append({"key": key, "issue": f"Value {val} > max {spec['max']}", "severity": "warning"})
                if coerce:
                    cfg[key] = min(spec["max"], val)

        elif expected_type == "int":
            try:
                val = int(value)
            except (TypeError, ValueError):
                issues.append(
                    {"key": key, "issue": f"Expected int, got {type(value).__name__}: {value!r}", "severity": "error"}
                )
                if coerce:
                    cfg[key] = spec["default"]
                continue
            if "min" in spec and val < spec["min"]:
                issues.append({"key": key, "issue": f"Value {val} < min {spec['min']}", "severity": "warning"})
                if coerce:
                    cfg[key] = max(spec["min"], val)
            if "max" in spec and val > spec["max"]:
                issues.append({"key": key, "issue": f"Value {val} > max {spec['max']}", "severity": "warning"})
                if coerce:
                    cfg[key] = min(spec["max"], val)

        elif expected_type == "bool":
            if not isinstance(value, bool):
                # Accept string booleans
                if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
                    pass  # OK — _as_bool handles this
                else:
                    issues.append(
                        {
                            "key": key,
                            "issue": f"Expected bool, got {type(value).__name__}: {value!r}",
                            "severity": "warning",
                        }
                    )

        elif expected_type == "list":
            if not isinstance(value, list):
                issues.append({"key": key, "issue": f"Expected list, got {type(value).__name__}", "severity": "error"})
                if coerce:
                    cfg[key] = spec["default"]

    # Cross-field validation
    issues.extend(_cross_validate(cfg))

    return issues


def get_schema() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the config schema for introspection."""
    return dict(_SCHEMA)
