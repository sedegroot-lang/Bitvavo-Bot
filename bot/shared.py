# -*- coding: utf-8 -*-
"""
Shared mutable state registry for the trailing bot.

All extracted modules import from here instead of referencing
trailing_bot globals directly. trailing_bot.py populates these
at startup via ``init()``.

Usage in extracted modules::

    from bot.shared import state
    state.open_trades  # the live dict
    state.CONFIG       # the config dict
    state.log(...)     # the log function
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List


def _noop(*a: Any, **kw: Any) -> None:
    return None


class _SharedState:
    """Namespace object holding all shared bot state.

    Attributes are populated by ``trailing_bot.py`` at startup.
    Default values are safe no-ops / empty containers so that
    import-time access before init doesn't crash.
    """

    # ── Core state ──────────────────────────────────────────
    open_trades: Dict[str, Any] = {}
    closed_trades: List[Dict[str, Any]] = []
    market_profits: Dict[str, float] = {}
    trades_lock: threading.RLock = threading.RLock()
    CONFIG: Dict[str, Any] = {}
    RUNNING: bool = True

    # ── Bitvavo client ──────────────────────────────────────
    bitvavo: Any = None

    # ── Paths ───────────────────────────────────────────────
    TRADE_LOG: Any = "data/trade_log.json"
    ARCHIVE_FILE: Any = "data/trade_archive.json"
    TRADE_PNL_HISTORY_FILE: str = "data/trade_pnl_history.jsonl"
    PORTFOLIO_SNAPSHOT_FILE: Any = "data/portfolio_snapshot.json"
    ACCOUNT_OVERVIEW_FILE: Any = "data/account_overview.json"
    HEARTBEAT_FILE: str = "data/heartbeat.json"
    AI_HEARTBEAT_FILE: str = "data/ai_heartbeat.json"

    # ── Constants (populated from CONFIG at init) ───────────
    MAX_CLOSED: int = 500
    MIN_ORDER_EUR: float = 5.0
    DUST_TRADE_THRESHOLD_EUR: float = 5.0
    FEE_MAKER: float = 0.0015
    FEE_TAKER: float = 0.0025
    SLIPPAGE_PCT: float = 0.001
    MAX_SPREAD_PCT: float = 0.015
    ORDER_TYPE: str = "limit"
    TRAILING_ACTIVATION_PCT: float = 0.025
    DEFAULT_TRAILING: float = 0.04
    SLEEP_SECONDS: int = 30
    PLACE_ORDERS_ENABLED: bool = True
    BASE_AMOUNT_EUR: float = 25.0
    MAX_TOTAL_EXPOSURE_EUR: float = 9999.0
    AUTO_USE_FULL_BALANCE: bool = False
    FULL_BALANCE_MAX_EUR: float = 100.0
    FULL_BALANCE_PORTION: float = 0.9
    REINVEST_ENABLED: bool = True
    REINVEST_MIN_TRADES: int = 10
    REINVEST_MIN_PROFIT: float = 0.0
    REINVEST_PORTION: float = 0.2
    REINVEST_MAX_INCREASE_PCT: float = 0.5
    REINVEST_CAP: float = 500.0
    LIVE_TRADING: bool = False
    TEST_MODE: bool = False
    OPERATOR_ID: str = ""
    DCA_MAX_BUYS: int = 3
    DCA_DROP_PCT: float = 0.05
    MAX_CLUSTER_TRADES_PER_BASE: int = 2
    MAX_CLUSTER_EXPOSURE_EUR: float = 100.0
    MARKET_PERFORMANCE_FILE: str = "data/market_metrics.json"

    # Last computed signal score for the next entry attempt; used by
    # bot.sizing_floor for the high-conviction bypass. Updated by the
    # entry scanner just before calling place_buy.
    last_signal_score: float = 0.0

    # ── Function references ─────────────────────────────────
    log: Callable = staticmethod(print)
    safe_call: Callable = staticmethod(lambda fn, *a, **kw: fn(*a, **kw))
    get_candles: Callable = staticmethod(lambda *a, **kw: None)
    get_current_price: Callable = staticmethod(lambda *a, **kw: None)
    get_eur_balance: Callable = staticmethod(lambda *a, **kw: 0.0)
    get_market_info: Callable = staticmethod(lambda *a, **kw: {})
    get_min_order_size: Callable = staticmethod(lambda *a, **kw: 0.0)
    get_amount_precision: Callable = staticmethod(lambda *a, **kw: 8)
    get_price_precision: Callable = staticmethod(lambda *a, **kw: 8)
    get_ticker_best_bid_ask: Callable = staticmethod(lambda *a, **kw: None)
    get_expected_slippage: Callable = staticmethod(lambda *a, **kw: None)
    normalize_amount: Callable = staticmethod(lambda *a, **kw: 0.0)
    normalize_price: Callable = staticmethod(lambda *a, **kw: 0.0)
    write_json_locked: Callable = staticmethod(lambda *a, **kw: None)
    json_write_compat: Callable = staticmethod(lambda *a, **kw: None)
    send_alert: Callable = staticmethod(lambda *a, **kw: None)
    save_trades_fn: Callable = staticmethod(lambda *a, **kw: None)
    load_trade_snapshot: Callable = staticmethod(lambda *a, **kw: {})
    save_trade_snapshot: Callable = staticmethod(lambda *a, **kw: None)
    sanitize_balance_payload: Callable = staticmethod(lambda *a, **kw: [])

    # ── Callbacks to trailing_bot functions ──────────────────
    # (registered at init so extracted modules can call back)
    cleanup_trades: Callable = _noop
    optimize_parameters: Callable = _noop
    analyse_trades: Callable = staticmethod(lambda *a: (0.0, 0.0, 0.0, 0.0))
    count_active_open_trades: Callable = staticmethod(lambda **kw: 0)
    count_dust_trades: Callable = staticmethod(lambda **kw: 0)
    _get_pending_count: Callable = staticmethod(lambda: 0)
    _get_pending_markets_dict: Callable = staticmethod(lambda: {})
    _is_market_reserved: Callable = staticmethod(lambda m: False)
    _reserve_market: Callable = staticmethod(lambda m: False)
    _release_market: Callable = staticmethod(lambda m: False)
    count_pending_bitvavo_orders: Callable = staticmethod(lambda: 0)
    get_pending_bitvavo_orders: Callable = staticmethod(lambda: [])
    current_open_exposure_eur: Callable = staticmethod(lambda **kw: 0.0)
    is_watchlist_market: Callable = staticmethod(lambda m: False)
    _get_watchlist_runtime_settings: Callable = staticmethod(
        lambda: {
            "enabled": False,
            "mode": "micro",
            "paper_only": True,
            "micro_trade_amount_eur": 5.0,
            "max_parallel": 3,
            "disable_dca": True,
        }
    )
    get_active_grid_markets: Callable = staticmethod(lambda: set())
    archive_trade: Callable = _noop
    _record_market_stats_for_close: Callable = _noop
    _finalize_close_trade: Callable = _noop
    load_market_performance: Callable = _noop
    save_market_performance: Callable = _noop
    _append_trade_pnl_jsonl: Callable = _noop
    derive_cost_basis: Callable = staticmethod(lambda *a, **kw: None)
    spread_ok: Callable = staticmethod(lambda m: True)

    # ── Managers ────────────────────────────────────────────
    risk_manager: Any = None
    dca_manager: Any = None
    synchronizer: Any = None
    metrics_collector: Any = None
    monitoring_manager: Any = None
    liquidation_manager: Any = None
    _reservation_manager: Any = None

    # ── Performance ─────────────────────────────────────────
    _perf: Any = None

    # ── Helpers ─────────────────────────────────────────────
    _clamp: Callable = staticmethod(lambda v, lo, hi: max(lo, min(v, hi)))
    _coerce_positive_float: Callable = staticmethod(lambda v: float(v) if v and float(v) > 0 else None)
    _log_throttled: Callable = staticmethod(lambda *a, **kw: None)

    def __repr__(self) -> str:
        n_ot = len(self.open_trades) if self.open_trades else 0
        return f"<SharedState trades={n_ot} bitvavo={'ok' if self.bitvavo else 'N/A'}>"


# Singleton instance — imported by extracted modules
state = _SharedState()


def init(**kwargs: Any) -> None:
    """Populate shared state from trailing_bot.py globals.

    Called once at startup::

        from bot.shared import init as init_shared
        init_shared(
            open_trades=open_trades,
            CONFIG=CONFIG,
            bitvavo=bitvavo,
            ...
        )
    """
    for key, value in kwargs.items():
        setattr(state, key, value)
