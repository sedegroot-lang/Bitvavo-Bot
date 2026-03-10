

import asyncio
import copy
import json
import logging
import math
import os
import random
import shutil
import signal
import socket
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from collections import deque
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from pathlib import Path
import atexit

from dotenv import load_dotenv
load_dotenv()

from modules.config import load_config
from core.reservation_manager import ReservationManager
import bot.api as _api
import bot.performance as _perf
import bot.signals as _signals
import bot.trailing as _trail

CONFIG = load_config() or {}
if not isinstance(CONFIG, dict):
    CONFIG = {}

def _get_watchlist_runtime_settings() -> Dict[str, Any]:
    settings = CONFIG.get('WATCHLIST_SETTINGS') or {}
    mode = str(settings.get('mode', 'micro') or 'micro').lower()
    return {
        'enabled': bool(settings.get('enabled', True)),
        'mode': mode,
        'paper_only': bool(settings.get('paper_only', mode == 'paper')),
        'micro_trade_amount_eur': float(settings.get('micro_trade_amount_eur', 5.0)),
        'max_parallel': max(0, int(settings.get('max_parallel', 3))),
        'disable_dca': bool(settings.get('disable_dca', True)),
    }


def is_watchlist_market(market: str) -> bool:
    try:
        return market in (CONFIG.get('WATCHLIST_MARKETS') or [])
    except Exception:
        return False

# ML Veto Tracking (for retrain trigger detection)
_ml_signal_history = deque(maxlen=100)  # Track last 100 ML signals
_ml_veto_alert_threshold = 0.8  # Alert when >80% HOLD signals


def _prioritize_watchlist_markets(markets: List[str]) -> List[str]:
    ranked: List[Tuple[float, str]] = []
    for market in markets:
        stats = _perf.get_snapshot(market)
        avg_profit = 0.0
        if stats:
            try:
                avg_profit = float(stats.get('avg_profit', 0.0) or 0.0)
            except Exception:
                avg_profit = 0.0
        ranked.append((avg_profit, market))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in ranked]

PROJECT_ROOT = Path(__file__).resolve().parent

# Operator ID: env var overrides config value
_env_operator_id = os.getenv('BITVAVO_OPERATOR_ID')
if _env_operator_id:
    CONFIG['OPERATOR_ID'] = _env_operator_id

import numpy as np

from modules.logging_utils import file_lock, log, locked_write_json
from modules.json_compat import write_json_compat
from modules.trading import (
    ARCHIVE_FILE as _DEFAULT_ARCHIVE_FILE,
    MAX_CLOSED as _DEFAULT_MAX_CLOSED,
    TRADE_LOG as _DEFAULT_TRADE_LOG,
    bitvavo as _base_bitvavo,
)
from modules.metrics import (
    MetricsCollector,
    configure as configure_metrics,
    get_collector as get_metrics_collector,
)
from modules.trade_archive import archive_trade as _archive_trade_original
from modules.trading_dca import DCAContext, DCASettings, DCAManager
from modules.ml import predict_ensemble
from modules.trading_liquidation import LiquidationContext, LiquidationManager
from modules.trading_monitoring import MonitoringContext, MonitoringManager
from modules.trading_risk import RiskContext, RiskManager, segment_for_market
from modules.trading_sync import SyncContext, TradingSynchronizer
from modules.trade_store import (
    load_snapshot as load_trade_snapshot,
    save_snapshot as save_trade_snapshot,
)
from modules.signals import SignalContext, evaluate_signal_pack
from modules.cost_basis import derive_cost_basis
from modules.trade_block_reasons import collect_and_record as collect_block_reasons
from modules.external_trades import is_market_claimed as is_external_trade
from core.indicators import (
    close_prices, highs, lows, volumes, sma, ema, ema_series,
    rsi, macd, atr, bollinger_bands, stochastic,
    calculate_momentum_score,
)

try:  # optional event hooks integration
    from modules.event_hooks import EventState
except Exception:  # pragma: no cover - optional dependency
    EventState = None  # type: ignore


def _as_bool(value: Any, default: bool = False) -> bool:
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import as_bool
    return as_bool(value, default)


def _as_int(value: Any, default: int = 0) -> int:
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import as_int
    return as_int(value, default)


def _update_rl_after_trade(closed_entry: dict):
    """Update RL agent with trade outcome for continuous learning"""
    try:
        from modules.ml import update_rl_agent
        market = closed_entry.get('market')
        profit_pct = closed_entry.get('profit_pct', 0.0)
        update_rl_agent(market, profit_pct)
        log(f"[RL] Updated agent for {market}: reward={profit_pct:.2f}%", level='debug')
    except Exception as e:
        log(f"[ERROR] RL agent update failed: {e}", level='debug')


def archive_trade(**closed_entry):
    """Wrapper for archive_trade that also updates RL agent for continuous learning"""
    result = _archive_trade_original(**closed_entry)
    _update_rl_after_trade(closed_entry)
    _append_trade_pnl_jsonl(closed_entry)
    return result


def _finalize_close_trade(
    market: str,
    trade: Dict[str, Any],
    closed_entry: Dict[str, Any],
    *,
    update_market_profits: bool = False,
    profit_for_market: Optional[float] = None,
    do_save: bool = True,
    do_cleanup: bool = True,
) -> None:
    """Unified close-trade sequence: archive → append → record stats → remove → save.

    Callers build *closed_entry* with whatever fields they need; this function
    handles the repetitive bookkeeping that was copy-pasted 7× throughout the
    codebase.
    """
    # Compute max_profit_pct from trade price tracking
    if trade and not closed_entry.get('max_profit_pct'):
        _hp = trade.get('highest_price', 0)
        _bp = trade.get('buy_price', 0)
        if _hp > 0 and _bp > 0:
            closed_entry['max_profit_pct'] = round((_hp - _bp) / _bp * 100, 2)
    # Carry forward useful metadata from open trade
    for _meta_key in ('score', 'rsi_at_entry', 'volume_24h_eur', 'volatility_at_entry',
                      'opened_regime', 'macd_at_entry', 'sma_short_at_entry', 'sma_long_at_entry',
                      'dca_buys', 'tp_levels_done'):
        if _meta_key not in closed_entry and trade and _meta_key in trade:
            closed_entry[_meta_key] = trade[_meta_key]
    archive_trade(**closed_entry)
    closed_trades.append(closed_entry)
    _record_market_stats_for_close(market, closed_entry, trade)
    if update_market_profits:
        p = profit_for_market if profit_for_market is not None else closed_entry.get('profit', 0.0)
        market_profits[market] = market_profits.get(market, 0.0) + p
    if market in open_trades:
        del open_trades[market]
    if do_save:
        save_trades()
    if do_cleanup:
        cleanup_trades()


def _get_true_total_invested(trade: Dict[str, Any]) -> float:
    """Return the most reliable total investment cost for a trade.

    Prefers initial_invested_eur (immutable) as ground truth.
    Falls back to total_invested_eur, then invested_eur, then buy_price*amount.
    Ensures total_invested is never less than initial_invested (would indicate corruption).
    """
    _init = float(trade.get('initial_invested_eur', 0) or 0)
    _total = float(trade.get('total_invested_eur', 0) or 0)
    _current = float(trade.get('invested_eur', 0) or 0)
    _bp = float(trade.get('buy_price', 0) or 0)
    _amt = float(trade.get('amount', 0) or 0)
    _computed = round(_bp * _amt, 4) if _bp > 0 and _amt > 0 else 0.0

    # Best source: initial + DCA amounts via total_invested_eur
    result = _total if _total > 0 else (_current if _current > 0 else _computed)

    # Sanity: total should never be less than initial (means it was corrupted)
    if _init > 0 and result < _init:
        result = _init

    return result


def _as_float(value: Any, default: float = 0.0) -> float:
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import as_float
    return as_float(value, default)


# Throttled logging - replaces random.random() gated logging with deterministic time-based throttle
_log_throttle_ts: Dict[str, float] = {}

def _log_throttled(key: str, msg: str, interval: float = 60.0, level: str = 'info') -> None:
    """Log a message at most once per `interval` seconds for a given key."""
    now = time.time()
    last = _log_throttle_ts.get(key, 0.0)
    if now - last >= interval:
        _log_throttle_ts[key] = now
        log(msg, level=level)

# FIX #4: save_trades() debound globals
_SAVE_TRADES_LOCK = threading.Lock()
_SAVE_TRADES_DEBOUNCE_TS = 0.0
_SAVE_TRADES_MIN_INTERVAL = 2.0  # seconds
def _ensure_parent_dir(path: str) -> None:
    try:
        parent = Path(path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"[ERROR] Failed to create parent directory for {path}: {e}", level='error')


def _append_trade_pnl_jsonl(closed_entry: dict) -> None:
    """Persist per-trade PnL to JSONL for PF/winrate analysis."""
    try:
        path = _resolve_path(TRADE_PNL_HISTORY_FILE)
        _ensure_parent_dir(path)

        opened_ts = closed_entry.get('opened_ts') or closed_entry.get('timestamp_open')
        closed_ts = closed_entry.get('timestamp') or closed_entry.get('closed_ts')
        hold_seconds = None
        try:
            if opened_ts is not None and closed_ts is not None:
                hold_seconds = max(0.0, float(closed_ts) - float(opened_ts))
        except Exception:
            hold_seconds = None

        record = {
            'ts': time.time(),
            'market': closed_entry.get('market'),
            'profit_eur': closed_entry.get('profit'),
            'profit_pct': closed_entry.get('profit_pct'),
            'invested_eur': closed_entry.get('invested_eur'),
            'amount': closed_entry.get('amount'),
            'buy_price': closed_entry.get('buy_price'),
            'sell_price': closed_entry.get('sell_price'),
            'opened_ts': opened_ts,
            'closed_ts': closed_ts,
            'hold_seconds': hold_seconds,
            'reason': closed_entry.get('reason'),
            'trailing_used': closed_entry.get('trailing_used'),
            'dca_buys': closed_entry.get('dca_buys'),
        }

        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=True) + '\n')
    except Exception as e:
        log(f"PnL export failed: {e}", level='debug')


def _resolve_path(path_like: str | Path) -> Path:
    path_obj = Path(path_like)
    if not path_obj.is_absolute():
        path_obj = PROJECT_ROOT / path_obj
    return path_obj


# Note: load_dotenv() and CONFIG already loaded at module start (lines 23-30)
# Removed duplicate load here to prevent race conditions

write_json_locked = locked_write_json
json_write_compat = write_json_compat

TRADE_LOG = CONFIG.get('TRADE_LOG', _DEFAULT_TRADE_LOG)
ARCHIVE_FILE = CONFIG.get('ARCHIVE_FILE', _DEFAULT_ARCHIVE_FILE)
MAX_CLOSED = int(CONFIG.get('MAX_CLOSED', _DEFAULT_MAX_CLOSED))
TRADE_PNL_HISTORY_FILE = CONFIG.get('TRADE_PNL_HISTORY_FILE', 'data/trade_pnl_history.jsonl')

bitvavo = _base_bitvavo

RUNNING = True
# Thread-safe market reservation manager (replaces old dict-based approach)
_reservation_manager = ReservationManager(default_timeout=300.0)  # 5 min expiry


def _get_pending_count() -> int:
    """Get count of pending market reservations (thread-safe)."""
    return _reservation_manager.count()


def _is_market_reserved(market: str) -> bool:
    """Check if a market is currently reserved (thread-safe)."""
    return _reservation_manager.is_reserved(market)


def _reserve_market(market: str) -> bool:
    """Reserve a market slot (thread-safe). Returns True if successful."""
    return _reservation_manager.reserve(market)


def _release_market(market: str) -> bool:
    """Release a market reservation (thread-safe). Returns True if was reserved."""
    return _reservation_manager.release(market)


# Legacy dict for backward compatibility in status/debugging (read-only view)
def _get_pending_markets_dict() -> Dict[str, float]:
    """Get dict view of pending reservations for status displays."""
    return _reservation_manager.active_reservations()


open_trades: Dict[str, Any] = {}
closed_trades: List[Dict[str, Any]] = []
market_profits: Dict[str, float] = {}
# Lock for protecting in-memory trade state (open_trades, closed_trades, market_profits)
# Must be acquired for ALL reads/writes to these dicts from any thread
trades_lock = threading.RLock()
market_performance: Dict[str, Any] = {}
MARKET_PERFORMANCE_FILE = CONFIG.get('MARKET_PERFORMANCE_FILE', os.path.join('data', 'market_metrics.json'))
MARKET_PERFORMANCE_LOCK = threading.Lock()
MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS = max(5, int(CONFIG.get('MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS', 30)))
MARKET_PERFORMANCE_MIN_TRADES = max(1, int(CONFIG.get('MARKET_PERFORMANCE_MIN_TRADES', 5)))
MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR = float(CONFIG.get('MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR', 0.0))
MARKET_PERFORMANCE_TARGET_EXPECTANCY_EUR = max(
    MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR + 0.01,
    float(CONFIG.get('MARKET_PERFORMANCE_TARGET_EXPECTANCY_EUR', 1.0)),
)
MARKET_PERFORMANCE_MAX_CONSEC_LOSSES = max(1, int(CONFIG.get('MARKET_PERFORMANCE_MAX_CONSEC_LOSSES', 3)))
MARKET_PERFORMANCE_FILTER_ENABLED = _as_bool(CONFIG.get('MARKET_PERFORMANCE_FILTER_ENABLED'), True)
MARKET_PERFORMANCE_SIZE_BIAS_ENABLED = _as_bool(CONFIG.get('MARKET_PERFORMANCE_SIZE_BIAS_ENABLED'), True)
MARKET_PERFORMANCE_SIZE_MIN_MULT = max(0.1, float(CONFIG.get('MARKET_PERFORMANCE_SIZE_MIN_MULTIPLIER', 0.5)))
MARKET_PERFORMANCE_SIZE_MAX_MULT = max(
    MARKET_PERFORMANCE_SIZE_MIN_MULT,
    float(CONFIG.get('MARKET_PERFORMANCE_SIZE_MAX_MULTIPLIER', 1.5)),
)
MARKET_PERFORMANCE_SMOOTHING = min(1.0, max(0.0, float(CONFIG.get('MARKET_PERFORMANCE_SMOOTHING', 0.2))))
MARKET_PERFORMANCE_FILTER_LOG_INTERVAL = max(60, int(CONFIG.get('MARKET_PERFORMANCE_FILTER_LOG_INTERVAL', 1800)))
MARKET_PERFORMANCE_PROBATION_DAYS = max(1, int(CONFIG.get('MARKET_PERFORMANCE_PROBATION_DAYS', 7)))
_MARKET_PERF_FILTER_LOG: Dict[str, float] = {}
_MARKET_PERF_BLOCK_TIMESTAMPS: Dict[str, float] = {}  # Track when markets first blocked for probation
_LAST_MARKET_PERFORMANCE_SAVE = 0.0
AI_REGIME_DEFENSIVE_CRITICAL_COUNT = max(0, int(CONFIG.get('AI_REGIME_DEFENSIVE_CRITICAL_COUNT', 1)))
AI_REGIME_HALT_CRITICAL_COUNT = max(
    AI_REGIME_DEFENSIVE_CRITICAL_COUNT,
    int(CONFIG.get('AI_REGIME_HALT_CRITICAL_COUNT', 3)),
)
AI_REGIME_NEUTRAL_SIZE_MULT = float(CONFIG.get('AI_REGIME_NEUTRAL_SIZE_MULTIPLIER', 1.0))
AI_REGIME_DEFENSIVE_SIZE_MULT = float(CONFIG.get('AI_REGIME_DEFENSIVE_SIZE_MULTIPLIER', 0.6))
AI_REGIME_HALT_SIZE_MULT = float(CONFIG.get('AI_REGIME_HALT_SIZE_MULTIPLIER', 0.0))
AI_REGIME_AGGRESSIVE_SIZE_MULT = float(CONFIG.get('AI_REGIME_AGGRESSIVE_SIZE_MULTIPLIER', 1.2))
AI_REGIME_CACHE_SECONDS = max(10, int(CONFIG.get('AI_REGIME_CACHE_SECONDS', 60)))
_AI_REGIME_CACHE: Dict[str, Any] = {'ts': 0.0, 'value': ('neutral', AI_REGIME_NEUTRAL_SIZE_MULT)}
dca_manager: Optional[DCAManager] = None
dca_settings: Optional[DCASettings] = None
liquidation_manager: Optional[LiquidationManager] = None
monitoring_manager: Optional[MonitoringManager] = None
synchronizer: Optional[TradingSynchronizer] = None
_auto_sync_thread: Optional[threading.Thread] = None
_managers_initialized = False
_monitor_threads_started = False

try:
    from modules.perf_monitor import PerfSampler as _PerfSampler
except Exception:
    _PerfSampler = None

if TYPE_CHECKING:
    from modules.perf_monitor import PerfSampler

perf_sampler: Optional["PerfSampler"] = None
risk_manager: Optional[RiskManager] = None
metrics_collector: Optional[MetricsCollector] = None

try:
    EVENT_STATE = EventState() if EventState else None
except Exception:
    EVENT_STATE = None

_EVENT_PAUSE_CACHE: Dict[str, bool] = {}


def _event_hooks_paused(market: str) -> bool:
    """Return True if a market (or global) pause is active via event hooks."""
    if not EVENT_STATE or not getattr(EVENT_STATE, "enabled", False):
        if _EVENT_PAUSE_CACHE.get(market):
            _EVENT_PAUSE_CACHE[market] = False
        return False
    try:
        paused = EVENT_STATE.market_paused(market)
    except Exception as exc:
        log(f"[event_hooks] Kon pausestatus niet ophalen voor {market}: {exc}", level='warning')
        return False
    previous = _EVENT_PAUSE_CACHE.get(market)
    if paused and previous is not True:
        log(f"[event_hooks] Pauze actief voor {market} -> nieuwe entries geblokkeerd", level='info')
    elif not paused and previous:
        log(f"[event_hooks] Pauze opgeheven voor {market}", level='info')
    _EVENT_PAUSE_CACHE[market] = paused
    return paused


def _event_hook_status_payload() -> Dict[str, Any]:
    if not EVENT_STATE:
        return {"enabled": False}
    try:
        records = EVENT_STATE.active_actions()
    except Exception as exc:
        log(f"[event_hooks] Status opvragen mislukt: {exc}", level='debug')
        return {"enabled": getattr(EVENT_STATE, "enabled", False)}
    formatted = [
        {
            "market": rec.market or "GLOBAL",
            "action": rec.action,
            "message": rec.message,
            "expires_ts": rec.expires_ts,
        }
        for rec in records
    ]
    return {
        "enabled": getattr(EVENT_STATE, "enabled", False),
        "active": formatted,
        "last_refresh": time.time(),
    }


def load_market_performance() -> Dict[str, Any]:
    """Delegate → bot.performance."""
    return _perf.load_market_performance()


def save_market_performance(force: bool = False) -> None:
    """Delegate → bot.performance."""
    _perf.save_market_performance(force=force)


def record_trade_performance(market, profit_eur, invested_eur, opened_ts, closed_ts, reason=None):
    """Delegate → bot.performance."""
    _perf.record_trade_performance(market, profit_eur, invested_eur, opened_ts, closed_ts, reason)


def _record_market_stats_for_close(market, closed_entry, open_entry=None):
    """Delegate → bot.performance."""
    _perf.record_market_stats_for_close(market, closed_entry, open_entry)


def _ensure_tp_flags(trade: Dict[str, Any]) -> List[bool]:
    return _trail._ensure_tp_flags(trade)


def _record_partial_tp_event(
    market: str,
    trade: Dict[str, Any],
    level_idx: int,
    target_pct: float,
    sell_pct: float,
    configured_pct: Optional[float],
    sell_amount: float,
    sell_price: float,
    profit_eur: float,
    remaining_amount: float,
) -> None:
    return _trail._record_partial_tp_event(market, trade, level_idx, target_pct, sell_pct, configured_pct, sell_amount, sell_price, profit_eur, remaining_amount)


def get_partial_tp_stats() -> Dict[str, Any]:
    return _trail.get_partial_tp_stats()


def _compute_win_loss_streaks(series: List[float]) -> Dict[str, Any]:
    """Delegate → bot.performance."""
    return _perf._compute_win_loss_streaks(series)


def publish_expectancy_metrics() -> None:
    """Delegate → bot.performance."""
    _perf.publish_expectancy_metrics()


def build_portfolio_snapshot() -> Dict[str, Any]:
    from bot.portfolio import build_portfolio_snapshot as _impl
    return _impl()
def write_portfolio_snapshot() -> Optional[Dict[str, Any]]:
    from bot.portfolio import write_portfolio_snapshot as _impl
    return _impl()
def build_account_overview(
    *,
    balances: Optional[List[Dict[str, Any]]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    eur_balance: Optional[float] = None,
) -> Dict[str, Any]:
    from bot.portfolio import build_account_overview as _impl
    return _impl(balances=balances, snapshot=snapshot, eur_balance=eur_balance)


def write_account_overview(
    *,
    balances: Optional[List[Dict[str, Any]]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    eur_balance: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    from bot.portfolio import write_account_overview as _impl
    return _impl(balances=balances, snapshot=snapshot, eur_balance=eur_balance)




def get_ai_regime_bias() -> Tuple[str, float]:
    now = time.time()
    cached = _AI_REGIME_CACHE.get('value') if isinstance(_AI_REGIME_CACHE, dict) else None
    if cached and (now - float(_AI_REGIME_CACHE.get('ts', 0.0))) < AI_REGIME_CACHE_SECONDS:
        return cached  # type: ignore[return-value]
    regime = 'neutral'
    multiplier = AI_REGIME_NEUTRAL_SIZE_MULT
    try:
        path = Path(AI_HEARTBEAT_FILE)
        data: Dict[str, Any] = {}
        if path.exists():
            with path.open('r', encoding='utf-8') as fh:
                loaded = json.load(fh) or {}
                data = loaded if isinstance(loaded, dict) else {}
        ts = float(data.get('ts', 0) or 0)
        stale = not ts or (now - ts) > AI_HEARTBEAT_STALE_SECONDS
        critical = int(data.get('critical_suggestions', 0) or 0)
        declared_regime = str(data.get('regime') or '').lower()
        if critical >= AI_REGIME_HALT_CRITICAL_COUNT:
            regime = 'halt'
            multiplier = AI_REGIME_HALT_SIZE_MULT
        elif critical >= AI_REGIME_DEFENSIVE_CRITICAL_COUNT:
            regime = 'defensive'
            multiplier = AI_REGIME_DEFENSIVE_SIZE_MULT
        elif declared_regime == 'aggressive':
            regime = 'aggressive'
            multiplier = AI_REGIME_AGGRESSIVE_SIZE_MULT
        else:
            regime = declared_regime or 'neutral'
            multiplier = AI_REGIME_NEUTRAL_SIZE_MULT
        if stale and regime != 'halt':
            regime = 'neutral'
            multiplier = AI_REGIME_NEUTRAL_SIZE_MULT
            try:
                log(f"AI regime fallback to neutral (stale heartbeat: {int(now - ts)}s old)", level='debug')
            except Exception as e:
                log(f"log failed: {e}", level='warning')
    except Exception:
        regime = 'halt'
        multiplier = AI_REGIME_HALT_SIZE_MULT
    _AI_REGIME_CACHE['value'] = (regime, multiplier)
    _AI_REGIME_CACHE['ts'] = now
    return regime, multiplier


def _init_perf_sampler() -> Optional["PerfSampler"]:
    sampler_cls = _PerfSampler
    if sampler_cls is None:
        return None
    enabled = _as_bool(CONFIG.get('PERF_MONITOR_ENABLED'), False)
    if not enabled:
        return None
    sample_seconds = float(CONFIG.get('PERF_SAMPLE_SECONDS', 120))
    history_size = int(CONFIG.get('PERF_SAMPLE_HISTORY', 600))
    metrics_file = CONFIG.get('PERF_METRICS_FILE', 'logs/perf_metrics.jsonl')
    try:
        return sampler_cls(
            name='trailing_bot',
            sample_interval=sample_seconds,
            history_size=history_size,
            log_fn=lambda msg: log(msg, level='debug'),
            metrics_file=metrics_file,
        )
    except Exception as exc:
        log(f"Perf monitor niet gestart: {exc}", level='warning')
        return None


perf_sampler = _init_perf_sampler()

# Init performance module (loads market_performance from disk)
# Use lambdas for late-bound references to functions defined further below
_perf.init(
    CONFIG,
    closed_trades_ref=closed_trades,
    get_partial_tp_stats_fn=lambda: get_partial_tp_stats(),
    count_active_fn=lambda **kw: count_active_open_trades(**kw),
)
# Keep local alias pointing at authoritative dict inside _perf
market_performance = _perf.market_performance


FLOODGUARD = CONFIG.get('FLOODGUARD', {})
SALDO_FORCE_MAX_LOSS_PCT = float(FLOODGUARD.get('max_loss_pct', 0.25))
SALDO_FORCE_MAX_LOSS_EUR = float(FLOODGUARD.get('max_loss_eur', 50.0))
SALDO_FORCE_MAX_API_FAILURES = int(FLOODGUARD.get('max_api_failures', 3))
SALDO_FORCE_SLEEP_SECONDS = float(FLOODGUARD.get('sleep_seconds', 1.0))
SALDO_ERROR_MAX_LOG = int(FLOODGUARD.get('error_max_log', 200))

SYNC_REMOVED_CACHE = CONFIG.get('SYNC_REMOVED_CACHE') or 'data/sync_removed_cache.json'
SYNC_REMOVED_CACHE_MAX_AGE = float(CONFIG.get('SYNC_REMOVED_CACHE_MAX_AGE', 3600))
EXCLUDED_MARKETS = set(str(m) for m in CONFIG.get('EXCLUDED_MARKETS', []))
TEST_MODE = _as_bool(CONFIG.get('TEST_MODE'), False)
LIVE_TRADING = _as_bool(CONFIG.get('LIVE_TRADING'), not TEST_MODE)
STOP_AFTER_SECONDS = _as_int(CONFIG.get('STOP_AFTER_SECONDS'), 0)

SMA_SHORT = CONFIG["SMA_SHORT"]
SMA_LONG = CONFIG["SMA_LONG"]
MACD_FAST = CONFIG["MACD_FAST"]
MACD_SLOW = CONFIG["MACD_SLOW"]
MACD_SIGNAL = CONFIG["MACD_SIGNAL"]
BREAKOUT_LOOKBACK = CONFIG["BREAKOUT_LOOKBACK"]
MIN_SCORE_TO_BUY = float(CONFIG["MIN_SCORE_TO_BUY"])  # Use config value directly (removed hardcoded 7.0 minimum)
TAKE_PROFIT_ENABLED = _as_bool(CONFIG.get('TAKE_PROFIT_ENABLED'), True)
_TP_TARGETS = CONFIG.get('TAKE_PROFIT_TARGETS') or []
_TP_PCTS = CONFIG.get('TAKE_PROFIT_PERCENTAGES') or []
PARTIAL_TP_LEVELS: List[Tuple[float, float]] = []
for target, pct in zip(_TP_TARGETS, _TP_PCTS):
    try:
        target_pct = float(target)
        sell_pct = float(pct)
    except Exception:
        continue
    if target_pct <= 0 or sell_pct <= 0:
        continue
    PARTIAL_TP_LEVELS.append((target_pct, min(1.0, sell_pct)))

# Define ATR variables first (needed for fallback)
ATR_WINDOW_1M = CONFIG["ATR_WINDOW_1M"]
ATR_MULTIPLIER = CONFIG["ATR_MULTIPLIER"]

# Fallback ATR-based partial TP levels when config not provided
if not PARTIAL_TP_LEVELS:
    PARTIAL_TP_LEVELS = [
        (max(0.015, 1.0 * (ATR_MULTIPLIER / 10)), 0.30),
        (max(0.025, 1.8 * (ATR_MULTIPLIER / 10)), 0.30),
        (max(0.035, 2.5 * (ATR_MULTIPLIER / 10)), 0.40),
    ]
HARD_SL_ALT_PCT = CONFIG.get("HARD_SL_ALT_PCT", 0.10)
HARD_SL_BTCETH_PCT = CONFIG.get("HARD_SL_BTCETH_PCT", 0.10)
# Use only default trailing; ignore per-market map
DEFAULT_TRAILING = CONFIG.get("DEFAULT_TRAILING", 0.10)
TRAILING_ACTIVATION_PCT = CONFIG.get("TRAILING_ACTIVATION_PCT", 0.02)
MIN_AVG_VOLUME_1M = CONFIG["MIN_AVG_VOLUME_1M"]
MAX_SPREAD_PCT = CONFIG["MAX_SPREAD_PCT"]

# RSI thresholds for entry filtering
RSI_MIN_BUY = CONFIG.get("RSI_MIN_BUY", 35.0)
RSI_MAX_BUY = CONFIG.get("RSI_MAX_BUY", 65.0)
FEE_MAKER = float(CONFIG.get('FEE_MAKER', 0.0015))  # Bitvavo maker fee (limit orders)
FEE_TAKER = float(CONFIG.get('FEE_TAKER', 0.0025))  # Bitvavo taker fee (market orders)
SLIPPAGE_PCT = float(CONFIG.get('SLIPPAGE_PCT', 0.001))  # slippage estimate
SLEEP_SECONDS = CONFIG["SLEEP_SECONDS"]
MAX_OPEN_TRADES = CONFIG["MAX_OPEN_TRADES"]
MAX_CLUSTER_TRADES_PER_BASE = int(CONFIG.get('MAX_CLUSTER_TRADES_PER_BASE', max(1, MAX_OPEN_TRADES // 2)))
MAX_CLUSTER_EXPOSURE_EUR = float(CONFIG.get('MAX_CLUSTER_EXPOSURE_EUR', CONFIG.get('MAX_TOTAL_EXPOSURE_EUR', 300.0)))
BASE_AMOUNT_EUR = CONFIG["BASE_AMOUNT_EUR"]
MIN_ORDER_EUR = float(CONFIG.get('MIN_ORDER_EUR', 5.0))
DUST_TRADE_THRESHOLD_EUR = float(CONFIG.get('DUST_TRADE_THRESHOLD_EUR', MIN_ORDER_EUR))
DUST_THRESHOLD_EUR = float(CONFIG.get('DUST_THRESHOLD_EUR', 1.0))
DUST_SWEEP_ENABLED = _as_bool(CONFIG.get('DUST_SWEEP_ENABLED', True), True)
_DUST_SWEEP_TS: Dict[str, float] = {}
MAX_TOTAL_EXPOSURE_EUR = CONFIG["MAX_TOTAL_EXPOSURE_EUR"]
MIN_BALANCE_EUR = CONFIG["MIN_BALANCE_EUR"]
EXPECTANCY_FILE = Path(CONFIG.get('EXPECTANCY_FILE', 'data/expectancy_stats.json'))
EXPECTANCY_HISTORY_FILE = Path(CONFIG.get('EXPECTANCY_HISTORY_FILE', 'data/expectancy_history.jsonl'))
PORTFOLIO_SNAPSHOT_FILE = Path(CONFIG.get('PORTFOLIO_SNAPSHOT_FILE', 'data/portfolio_snapshot.json'))
PARTIAL_TP_HISTORY_FILE = Path(CONFIG.get('PARTIAL_TP_HISTORY_FILE', 'data/partial_tp_events.jsonl'))
PARTIAL_TP_STATS_FILE = Path(CONFIG.get('PARTIAL_TP_STATS_FILE', 'data/partial_tp_stats.json'))
ACCOUNT_OVERVIEW_FILE = Path(CONFIG.get('ACCOUNT_OVERVIEW_FILE', 'data/account_overview.json'))


# ========================================
# CONFIG VALIDATION (Issue #9)
# ========================================
def validate_config():
    """
    Validate CONFIG for contradictions & nonsensical combinations
    Log warnings if detected
    """
    issues = []
    
    # 1. Whitelist + Blacklist overlap
    wl = set(CONFIG.get('WHITELIST', []))
    bl = set(CONFIG.get('BLACKLIST', []))
    overlap = wl & bl
    if overlap:
        issues.append(f"CONFIG: Markets in both WHITELIST and BLACKLIST: {overlap}")
    
    # 2. TP_PCT_MIN > TP_PCT_MAX
    tp_min = _as_float(CONFIG.get('TP_PCT_MIN'), 0.01)
    tp_max = _as_float(CONFIG.get('TP_PCT_MAX'), 0.05)
    if tp_min > tp_max:
        issues.append(f"CONFIG: TP_PCT_MIN ({tp_min}) > TP_PCT_MAX ({tp_max})")
    
    # 3. TIERS max_buy < min_buy
    tiers = CONFIG.get('TIERS', [])
    for idx, tier in enumerate(tiers):
        min_buy = _as_float(tier.get('min_buy'), 0)
        max_buy = _as_float(tier.get('max_buy'), 9999)
        if min_buy > max_buy:
            issues.append(f"CONFIG: TIERS[{idx}] min_buy ({min_buy}) > max_buy ({max_buy})")
    
    # 4. DCA_MAX_BUYS < 1
    dca_max = _as_int(CONFIG.get('DCA_MAX_BUYS'), 3)
    if dca_max < 1:
        issues.append(f"CONFIG: DCA_MAX_BUYS ({dca_max}) < 1")
    
    # 5. AI config contradictions
    if _as_bool(CONFIG.get('AI_ENABLED'), False):
        ai_min = _as_float(CONFIG.get('AI_MIN_CONFIDENCE'), 0.6)
        ai_max = _as_float(CONFIG.get('AI_MAX_CONFIDENCE'), 1.0)
        if ai_min > ai_max:
            issues.append(f"CONFIG: AI_MIN_CONFIDENCE ({ai_min}) > AI_MAX_CONFIDENCE ({ai_max})")
    
    # 6. SESSION2: Risk limits sanity checks
    max_exp = _as_float(CONFIG.get('MAX_TOTAL_EXPOSURE_EUR'), 9999)
    base_amt = _as_float(CONFIG.get('BASE_AMOUNT_EUR'), 6)
    max_trades = _as_int(CONFIG.get('MAX_OPEN_TRADES'), 5)
    if max_exp >= 9000:
        issues.append(f"CONFIG: MAX_TOTAL_EXPOSURE_EUR={max_exp} is effectively DISABLED (set to a real limit!)")
    elif max_exp < base_amt * max_trades:
        issues.append(f"CONFIG: MAX_TOTAL_EXPOSURE_EUR={max_exp} < BASE_AMOUNT_EUR*MAX_OPEN_TRADES ({base_amt*max_trades})")
    daily_loss = _as_float(CONFIG.get('RISK_MAX_DAILY_LOSS'), 9999)
    weekly_loss = _as_float(CONFIG.get('RISK_MAX_WEEKLY_LOSS'), 9999)
    if daily_loss >= 9000:
        issues.append(f"CONFIG: RISK_MAX_DAILY_LOSS={daily_loss} is effectively DISABLED")
    if weekly_loss >= 9000:
        issues.append(f"CONFIG: RISK_MAX_WEEKLY_LOSS={weekly_loss} is effectively DISABLED")
    if daily_loss < 9000 and weekly_loss < 9000 and daily_loss > weekly_loss:
        issues.append(f"CONFIG: RISK_MAX_DAILY_LOSS ({daily_loss}) > RISK_MAX_WEEKLY_LOSS ({weekly_loss})")
    
    if issues:
        log("[CONFIG] Validation warnings:", level='warning')
        for issue in issues:
            log(f"  - {issue}", level='warning')
    else:
        log("[CONFIG] Validation passed: no contradictions found")


# ========================================
# TRADE DATA INTEGRITY CHECK (Anti-corruption guard)
# ========================================
def validate_and_repair_trades():
    """
    Periodic sanity check to detect and repair corrupted trade data.
    Runs on bot startup and periodically during runtime.
    
    Guards against:
    - dca_buys exceeding dca_max
    - Negative invested_eur values
    - Absurdly high total_invested_eur (> 10x BASE_AMOUNT_EUR)
    - Missing required fields
    """
    repairs_made = 0
    base_amount = float(CONFIG.get('BASE_AMOUNT_EUR', 8))
    dca_max_global = int(CONFIG.get('DCA_MAX_BUYS', 3))
    max_reasonable_invested = base_amount * (dca_max_global + 1) * 3  # 3x safety margin
    
    for market, trade in list(open_trades.items()):
        try:
            # Get trade-specific dca_max or use global
            dca_max_local = int(trade.get('dca_max') or dca_max_global)
            dca_buys = int(trade.get('dca_buys', 0) or 0)
            invested = float(trade.get('invested_eur', 0) or 0)
            total_invested = float(trade.get('total_invested_eur', invested) or invested)
            
            # GUARD 1: dca_buys > dca_max
            if dca_buys > dca_max_local:
                log(f"⚠️ REPAIR [{market}]: dca_buys {dca_buys} > dca_max {dca_max_local}, resetting to {dca_max_local}", level='warning')
                trade['dca_buys'] = dca_max_local
                repairs_made += 1
            
            # GUARD 2: Negative invested_eur — delegate to TradeInvestment module
            if invested < 0:
                from core.trade_investment import repair_negative as _ti_repair
                if _ti_repair(trade, market):
                    repairs_made += 1
            
            # GUARD 3: Absurdly high total_invested_eur
            if total_invested > max_reasonable_invested:
                reasonable_value = base_amount * (1 + min(dca_buys, dca_max_local))
                log(f"⚠️ REPAIR [{market}]: total_invested_eur {total_invested:.2f} unreasonably high (max {max_reasonable_invested:.2f}), resetting invested_eur to {reasonable_value:.2f}", level='warning')
                # Only reset invested_eur (current exposure), keep total_invested_eur
                # as-is if it reflects cumulative DCAs. Only reset total if it's also
                # clearly wrong relative to initial_invested + dca amounts.
                trade['invested_eur'] = reasonable_value
                # Only reset total if absurdly higher than reasonable (>5x)
                if total_invested > reasonable_value * 5:
                    trade['total_invested_eur'] = reasonable_value
                repairs_made += 1
            
            # GUARD 4: Missing required fields
            if 'dca_buys' not in trade:
                trade['dca_buys'] = 0
                repairs_made += 1
            if 'dca_max' not in trade:
                trade['dca_max'] = dca_max_global
                repairs_made += 1
                
        except Exception as e:
            log(f"⚠️ REPAIR [{market}]: Error during validation: {e}", level='warning')
    
    if repairs_made > 0:
        save_trades()
        log(f"✅ Trade integrity check complete: {repairs_made} repairs made", level='warning')
    else:
        log(f"✅ Trade integrity check complete: all trades valid", level='info')
    
    return repairs_made


# ========================================
# EUR BALANCE CACHING (Issue #8)
# ========================================
def get_eur_balance(force_refresh=False):
    """Get EUR balance with caching (5 min TTL)."""
    return _api.get_eur_balance(force_refresh=force_refresh)


# ========================================
# MARKET PERFORMANCE PERIODIC SAVES (Issue #10)
# ========================================

def maybe_save_market_performance():
    """Delegate → bot.performance."""
    _perf.maybe_save_market_performance()


REINVEST_ENABLED = _as_bool(CONFIG.get('REINVEST_ENABLED'), True)
REINVEST_MIN_TRADES = _as_int(CONFIG.get('REINVEST_MIN_TRADES'), 10)
REINVEST_MIN_PROFIT = _as_float(CONFIG.get('REINVEST_MIN_PROFIT'), 0.0)
REINVEST_PORTION = _as_float(CONFIG.get('REINVEST_PORTION'), 0.2)
REINVEST_MAX_INCREASE_PCT = _as_float(CONFIG.get('REINVEST_MAX_INCREASE_PCT'), 0.5)
REINVEST_CAP = _as_float(CONFIG.get('REINVEST_CAP'), 500.0)

ORDER_TYPE = CONFIG.get('ORDER_TYPE', 'auto') or 'auto'
AUTO_USE_FULL_BALANCE = _as_bool(CONFIG.get('AUTO_USE_FULL_BALANCE'), False)
FULL_BALANCE_PORTION = _as_float(CONFIG.get('FULL_BALANCE_PORTION'), 0.25)
FULL_BALANCE_MAX_EUR = _as_float(CONFIG.get('FULL_BALANCE_MAX_EUR'), 250.0)
OPERATOR_ID = CONFIG.get('OPERATOR_ID')
try:
    # allow operator id from env or config; normalize to int when possible
    OPERATOR_ID = int(OPERATOR_ID) if OPERATOR_ID is not None else None
except (TypeError, ValueError):
    OPERATOR_ID = None

# If operator id is missing, disable placing live orders and make this explicit in the logs.
# This prevents repeated Bitvavo API errors (203 operatorId required) when the env/config is not set.
PLACE_ORDERS_ENABLED = True if OPERATOR_ID is not None else False
if not PLACE_ORDERS_ENABLED and LIVE_TRADING:
    # Critical: user is running in live mode but operator id is not set
    log("CRITICAL: BITVAVO_OPERATOR_ID / CONFIG['OPERATOR_ID'] not set. Live order placement is disabled until operatorId is configured.", level='error')
    log("To fix: set BITVAVO_OPERATOR_ID=<your operator id> in .env or add 'OPERATOR_ID' to bot_config.json and restart the bot.")

DCA_ENABLED = _as_bool(CONFIG.get('DCA_ENABLED'), True)
DCA_DYNAMIC = _as_bool(CONFIG.get('DCA_DYNAMIC'), False)
DCA_MAX_BUYS = _as_int(CONFIG.get('DCA_MAX_BUYS'), 3)
DCA_DROP_PCT = _as_float(CONFIG.get('DCA_DROP_PCT'), 0.02)

# ── DCA/SL conflict guard ──────────────────────────────────────────────────
# If the deepest DCA level would overlap the stop-loss, automatically WIDEN
# the SL instead of capping DCA_MAX_BUYS — this respects the user's DCA intent.
# Formula: min_safe_sl = DCA_DROP_PCT * DCA_MAX_BUYS + DCA_SL_BUFFER_PCT
# Override buffer via config key DCA_SL_BUFFER_PCT (default 1.5%).
# Example: 3 DCA adds × 6% drop + 1.5% buffer → SL must be at least 19.5%
_dca_sl_buffer = _as_float(CONFIG.get('DCA_SL_BUFFER_PCT', 0.015))
if DCA_ENABLED and DCA_DROP_PCT > 0 and DCA_MAX_BUYS > 0:
    _min_safe_sl = DCA_DROP_PCT * DCA_MAX_BUYS + _dca_sl_buffer
    if HARD_SL_ALT_PCT < _min_safe_sl:
        log(
            f"[DCA-SL AutoFix] HARD_SL_ALT_PCT={HARD_SL_ALT_PCT:.1%} too tight for "
            f"{DCA_MAX_BUYS} DCA adds at -{DCA_DROP_PCT:.1%} each "
            f"(deepest DCA at -{DCA_DROP_PCT * DCA_MAX_BUYS:.1%}, buffer={_dca_sl_buffer:.1%}) "
            f"→ auto-widened SL to {_min_safe_sl:.1%}. "
            f"Set HARD_SL_ALT_PCT>={_min_safe_sl:.1%} in config to suppress this warning.",
            level='warning'
        )
        HARD_SL_ALT_PCT = _min_safe_sl
    if HARD_SL_BTCETH_PCT < _min_safe_sl:
        HARD_SL_BTCETH_PCT = _min_safe_sl
# ──────────────────────────────────────────────────────────────────────────

DCA_STEP_MULTIPLIER = _as_float(CONFIG.get('DCA_STEP_MULTIPLIER'), 1.0)
_dca_ratio_raw = CONFIG.get('DCA_AMOUNT_RATIO')
_dca_ratio = _as_float(_dca_ratio_raw, 0.0) if _dca_ratio_raw is not None else None
DCA_AMOUNT_EUR = float(BASE_AMOUNT_EUR) * _dca_ratio if _dca_ratio is not None else _as_float(CONFIG.get('DCA_AMOUNT_EUR'), float(BASE_AMOUNT_EUR))
DCA_SIZE_MULTIPLIER = _as_float(CONFIG.get('DCA_SIZE_MULTIPLIER'), 1.0)

# Option B: conditional reset trailing on DCA when buy_price increases by more than threshold
RESET_TRAILING_ON_DCA = _as_bool(CONFIG.get('RESET_TRAILING_ON_DCA'), False)
RESET_TRAILING_ON_DCA_IF_BUY_INCREASE_PCT = _as_float(CONFIG.get('RESET_TRAILING_ON_DCA_IF_BUY_INCREASE_PCT'), 0.0)

EXIT_MODE = CONFIG.get('EXIT_MODE', 'trailing_and_hard') or 'trailing_and_hard'
STOP_LOSS_ENABLED = _as_bool(CONFIG.get('STOP_LOSS_ENABLED'), True)
OPEN_TRADE_COOLDOWN_SECONDS = _as_int(CONFIG.get('OPEN_TRADE_COOLDOWN_SECONDS'), 0)
MIN_PRICE_EUR = _as_float(CONFIG.get('MIN_PRICE_EUR'), 0.0)
MAX_PRICE_EUR = _as_float(CONFIG.get('MAX_PRICE_EUR'), 0.0)
MIN_DAILY_VOLUME_EUR = _as_float(CONFIG.get('MIN_DAILY_VOLUME_EUR'), 0.0)

SYNC_ENABLED = _as_bool(CONFIG.get('SYNC_ENABLED'), True)
SYNC_INTERVAL_SECONDS = max(5, _as_int(CONFIG.get('SYNC_INTERVAL_SECONDS'), 60))

MAX_MARKETS_PER_SCAN = _as_int(CONFIG.get('MAX_MARKETS_PER_SCAN'), 50)
SCAN_WATCHDOG_SECONDS = max(30, _as_int(CONFIG.get('SCAN_WATCHDOG_SECONDS'), 60))
scan_offset = 0
open_trades, closed_trades, market_profits = {}, [], {}
HEARTBEAT_FILE = CONFIG.get('HEARTBEAT_FILE', 'data/heartbeat.json')
AI_HEARTBEAT_FILE = CONFIG.get('AI_HEARTBEAT_FILE', 'data/ai_heartbeat.json')
AI_HEARTBEAT_STALE_SECONDS = max(60, _as_int(CONFIG.get('AI_HEARTBEAT_STALE_SECONDS'), 900))
ALERT_WEBHOOK = CONFIG.get('ALERT_WEBHOOK')
TELEGRAM_WEBHOOK = CONFIG.get('TELEGRAM_WEBHOOK')
ALERT_STALE_SECONDS = CONFIG.get('ALERT_STALE_SECONDS', 180)
ALERT_DEDUPE_SECONDS = CONFIG.get('ALERT_DEDUPE_SECONDS', 600)
_last_alert = {'msg': None, 'ts': 0}

# Initialiseer Telegram handler bij opstarten
try:
    from modules import telegram_handler as _tg_handler
    _tg_handler.init(CONFIG)
except Exception as _tg_init_err:
    log(f"[Telegram] Init mislukt: {_tg_init_err}", level='warning')
    _tg_handler = None  # type: ignore


def send_alert(msg):
    try:
        now = time.time()
        if _last_alert['msg'] == msg and (now - _last_alert['ts']) < ALERT_DEDUPE_SECONDS:
            # dedupe same alert
            return
        _last_alert['msg'] = msg
        _last_alert['ts'] = now
        # Telegram Bot API (primair)
        if _tg_handler is not None:
            try:
                _tg_handler.notify(msg)
            except Exception as e:
                log(f"[ERROR] Telegram notify failed: {e}", level='error')
        # Fallback: oude webhook
        elif TELEGRAM_WEBHOOK:
            try:
                import requests
                requests.post(TELEGRAM_WEBHOOK, json={'text': msg}, timeout=5)
            except Exception as e:
                log(f"[ERROR] Telegram webhook failed: {e}", level='error')
        if ALERT_WEBHOOK:
            try:
                import requests
                requests.post(ALERT_WEBHOOK, json={'message': msg}, timeout=5)
            except Exception as e:
                log(f"[ERROR] Alert webhook failed: {e}", level='error')
    except Exception as e:
        log(f"[ERROR] send_alert failed: {e}", level='error')

def _start_heartbeat_monitor():
    if monitoring_manager is None:
        return
    monitoring_manager.start_heartbeat_monitor(
        send_alert,
        alert_stale_seconds=ALERT_STALE_SECONDS,
        interval=60,
    )


def _start_heartbeat_writer(interval=30):
    """Daemon thread that periodically writes HEARTBEAT_FILE with timestamp and summary info.

    Uses atomic write (tmp -> replace) to avoid partial files.
    """
    if monitoring_manager is None:
        return
    monitoring_manager.start_heartbeat_writer(
        lambda: dict(open_trades),  # Return snapshot copy to avoid race conditions
        _get_pending_markets_dict,
        interval=interval,
        dust_threshold_eur=DUST_TRADE_THRESHOLD_EUR,
        scan_stats_provider=lambda: CONFIG.get('LAST_SCAN_STATS', {}),
    )

def _start_reservation_watchdog(interval=30):
    if monitoring_manager is None:
        return
    monitoring_manager.start_reservation_watchdog(
        _get_pending_markets_dict,
        interval=interval,
    )

# =========================
# UTILS
# =========================

# Minimum ordergrootte per coin ophalen
def get_market_info(market):
    return _api.get_market_info(market)

def get_min_order_size(market):
    return _api.get_min_order_size(market)

def get_amount_precision(market):
    return _api.get_amount_precision(market)

def get_price_precision(market):
    return _api.get_price_precision(market)

def get_amount_step(market):
    return _api.get_amount_step(market)

def get_price_step(market):
    return _api.get_price_step(market)

def normalize_amount(market, amount):
    return _api.normalize_amount(market, amount)

def normalize_price(market, price):
    return _api.normalize_price(market, price)

def _clamp(val: float, lo: float, hi: float) -> float:
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import clamp
    return clamp(val, lo, hi)

def get_expected_slippage(market, amount_eur, entry_price):
    """Estimate slippage using shallow orderbook depth (asks side for buy)."""
    return _api.get_expected_slippage(market, amount_eur, entry_price)

def get_expected_slippage_sell(market, amount_base, ref_price):
    """Estimate slippage on sell using bids side."""
    return _api.get_expected_slippage_sell(market, amount_base, ref_price)


def apply_dynamic_performance_tweaks() -> None:
    """Adjust key config knobs based on recent trading performance."""
    updated = False  # Ensure defined even if we exit early
    try:
        data = load_trade_snapshot(TRADE_LOG)
    except Exception as exc:
        log(f"Dynamische analyse trade-log mislukt: {exc}", level='warning')
        return

    closed = data.get('closed', []) if isinstance(data, dict) else []
    if not closed:
        return

    pnl_list = [t.get('profit', 0) for t in closed if isinstance(t, dict)]
    if not pnl_list:
        return

    avg_pnl = statistics.mean(pnl_list)
    win_rate = sum(1 for p in pnl_list if p > 0) / len(pnl_list)

    # NOTE: Dynamic risk scaling of BASE_AMOUNT_EUR disabled — AI supervisor handles this via auto-apply

    # Dynamische score drempel op basis van gemiddelde winst per trade
    # Scores komen uit signal_strength() met max ~15, dus drempel moet 5-9 zijn
    min_score = float(CONFIG.get('MIN_SCORE_TO_BUY', 7))
    if avg_pnl < -0.5:  # Alleen bij significant verlies verhogen
        new_score = min(min_score + 0.5, 9.0)  # Max 9, niet hoger
    elif avg_pnl > 0.5:
        new_score = max(min_score - 0.5, 5.0)  # Min 5, niet lager
    else:
        new_score = min_score
    if abs(new_score - min_score) > 0.01:
        CONFIG['MIN_SCORE_TO_BUY'] = new_score
        updated = True
        log(f"MIN_SCORE_TO_BUY aangepast naar {new_score:.1f} (gemiddelde winst {avg_pnl:.2f} EUR).")

    if updated:
        payload = {'MIN_SCORE_TO_BUY': CONFIG.get('MIN_SCORE_TO_BUY')}
        if 'BASE_AMOUNT_EUR' in CONFIG:
            payload['BASE_AMOUNT_EUR'] = CONFIG['BASE_AMOUNT_EUR']
        try:
            with open('param_log.txt', 'a', encoding='utf-8') as fh:
                fh.write(f"{datetime.now()} | {json.dumps(payload)}\n")
        except Exception as e:
            log(f"encoding failed: {e}", level='warning')


_LAST_ML_OPTIMIZER_RUN = 0.0


async def maybe_run_ml_optimizer() -> None:
    """Run the ML optimizer at most once per configured interval."""
    global _LAST_ML_OPTIMIZER_RUN
    interval = float(CONFIG.get('ML_OPTIMIZER_INTERVAL_SECONDS', 86400))
    if interval <= 0:
        return
    now = time.time()
    if (now - _LAST_ML_OPTIMIZER_RUN) < interval:
        return
    try:
        from ai import ml_optimizer  # Fixed: was 'import ml_optimizer'
        log("Start ML-optimalisatie van parameters...")
        if hasattr(ml_optimizer, 'optimize_ml_parameters_async'):
            await ml_optimizer.optimize_ml_parameters_async()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, ml_optimizer.optimize_ml_parameters)
        _LAST_ML_OPTIMIZER_RUN = now
    except Exception as exc:
        log(f"ML-optimalisatie mislukt: {exc}", level='error')
def register_saldo_error(market: str, bitvavo_balance: Optional[dict], trade_snapshot: Optional[dict]) -> None:
    """Log saldo errors for later inspection and flood detection."""
    entry = {
        'market': market,
        'timestamp': time.time(),
        'bitvavo_balance': bitvavo_balance,
        'trade_snapshot': trade_snapshot,
    }
    max_entries = int(CONFIG.get('SALDO_ERROR_MAX_LOG', 200))
    try:
        with file_lock:
            try:
                with open('data/pending_saldo.json', 'r', encoding='utf-8') as fh:
                    pending = json.load(fh)
                if not isinstance(pending, list):
                    pending = []
            except Exception:
                pending = []
            pending.append(entry)
            if max_entries > 0:
                pending = pending[-max_entries:]
            json_write_compat('data/pending_saldo.json', pending, indent=2)
    except Exception as exc:
        log(f"Fout bij registreren saldo_error voor {market}: {exc}", level='error')


def saldo_flood_guard() -> None:
    if liquidation_manager is None:
        return
    liquidation_manager.saldo_flood_guard(open_trades, closed_trades, market_profits)


def free_capacity_if_needed() -> None:
    if liquidation_manager is None:
        return
    liquidation_manager.free_capacity_if_needed(
        open_trades,
        closed_trades,
        market_profits,
    )


def cleanup_trades():
    from bot.trade_lifecycle import cleanup_trades as _impl
    return _impl()
def safe_call(func, *args, **kwargs):
    """Bitvavo API wrapper met retry, circuit breaker, rate limiting en optionele caching."""
    return _api.safe_call(func, *args, **kwargs)


def sanitize_balance_payload(payload, *, source: str = 'bitvavo.balance') -> List[Dict[str, Any]]:
    """Return een lijst met geldige balance dicts en log alles wat onjuist is."""
    return _api.sanitize_balance_payload(payload, source=source)


def start_auto_sync(*, interval: int = 60) -> None:
    global _auto_sync_thread
    # Always start the auto-sync thread; the running thread will consult
    # the shared CONFIG at runtime to determine whether syncing should occur.
    # This makes the dashboard/config hot-reload effective without restarting.
    if synchronizer is None:
        log("Auto-sync niet gestart: synchronizer ontbreekt.", level='debug')
        return
    if interval <= 0:
        interval = SYNC_INTERVAL_SECONDS
    if interval <= 0:
        interval = 60
    if _auto_sync_thread and _auto_sync_thread.is_alive():
        return

    def state_provider():
        with trades_lock:
            return dict(open_trades), list(closed_trades), dict(market_profits)

    def state_consumer(new_open, new_closed, new_profits):
        with trades_lock:
            open_trades.clear()
            open_trades.update(new_open)
            closed_trades[:] = list(new_closed)
            market_profits.clear()
            market_profits.update(new_profits)

    _auto_sync_thread = synchronizer.start_auto_sync(
        state_provider,
        state_consumer,
        interval=interval,
    )
    log(f"Auto-sync thread gestart (interval={interval}s).", level='info')


def optimize_parameters(trades: List[Dict[str, Any]]) -> None:
    """Placeholder for parameter optimization based on trade history.
    
    Can be extended to:
    - Analyze win/loss patterns
    - Adjust MIN_SCORE_TO_BUY dynamically
    - Optimize position sizing
    - Fine-tune trailing parameters
    """
    try:
        if not trades or len(trades) < 5:
            return  # Not enough data to optimize
        
        # Basic analysis already covered by apply_dynamic_performance_tweaks()
        # This is a hook for future optimization logic
        log(f"[OPTIMIZE] Analyzed {len(trades)} trades for parameter optimization", level='debug')
    except Exception as e:
        log(f"[ERROR] Parameter optimization failed: {e}", level='warning')


def save_trades(force: bool = False):
    """Save trades with debouncing to prevent excessive writes and file corruption.
    
    Args:
        force: If True, bypass debounce timer (use for critical saves)
    """
    from bot.trade_lifecycle import save_trades as _impl
    return _impl(force)
def load_trades():
    from bot.trade_lifecycle import load_trades as _impl
    return _impl()
def load_saldo_quarantine():
    """Return a set of markets that exceeded SALDO_QUARANTINE_THRESHOLD within window days.
    Counts both pending_saldo.json entries and recent closed trades.
    """
    from bot.trade_lifecycle import load_saldo_quarantine as _impl
    return _impl()
def sync_with_bitvavo():
    """Safe sync: fetch balances from Bitvavo and reconcile in-memory open_trades.
    Only writes trade_log.json when changes are detected. Uses file_lock to avoid races.
    """
    from bot.sync_engine import sync_with_bitvavo as _impl
    return _impl()
def get_active_grid_markets() -> set:
    """Get set of markets that are currently active in grid trading.
    
    These markets should be excluded from trailing bot and HODL trading
    to prevent conflicts.
    """
    grid_markets = set()
    try:
        from modules.grid_trading import get_grid_manager
        grid_manager = get_grid_manager()
        for grid_summary in grid_manager.get_all_grids_summary():
            if grid_summary.get('status') in ('running', 'paused', 'initialized'):
                grid_markets.add(grid_summary.get('market'))
    except ImportError as e:
        log(f"get_grid_manager failed: {e}", level='warning')
    except Exception as e:
        log(f"get_grid_manager failed: {e}", level='warning')
    return grid_markets


def get_supported_markets():
    return _api.get_supported_markets()

def cancel_open_buys_if_capped():
    """Proactively cancel outstanding open BUY orders when (open+reserved+pending) >= MAX_OPEN_TRADES.

    Only cancels orders for markets not yet present in open_trades to avoid interfering
    with DCA or partial fills. Skips grid trading orders. Best-effort: logs and continues on errors.
    """
    try:
        max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
        current = count_active_open_trades(threshold=DUST_TRADE_THRESHOLD_EUR)
        reserved = _get_pending_count()
        pending_orders = count_pending_bitvavo_orders()
        total_slots = current + reserved + pending_orders
        if total_slots < max_trades:
            return
        # Get grid markets + order IDs to protect from cancellation
        grid_markets = get_active_grid_markets()
        grid_order_ids = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_order_ids = gm.get_grid_order_ids()
        except Exception:
            pass
        # fetch open orders
        orders = safe_call(bitvavo.ordersOpen, {}) or []
        # Identify markets to cancel: buy side, not in open_trades, NOT grid orders
        to_cancel = []
        success = 0
        failed = 0
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in open_trades:
                    continue
                # CRITICAL: Skip grid trading orders
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = o.get('status', '').lower()
                if status not in ('new', 'open', 'partiallyfilled', 'partially filled'):
                    continue
                to_cancel.append((o.get('orderId'), market))
            except Exception:
                continue
        # Cancel them
        for orderId, market in to_cancel:
            try:
                # CRITICAL: Include operatorId for order cancellation
                if OPERATOR_ID:
                    res = bitvavo.cancelOrder(market, orderId, operatorId=str(OPERATOR_ID))
                else:
                    res = safe_call(bitvavo.cancelOrder, market, orderId)
                log(f"Canceled open BUY order {orderId} for {market} due to cap reached: {res}", level='warning')
                success += 1
            except Exception as e:
                log(f"Failed to cancel order {orderId} for {market}: {e}", level='error')
                failed += 1

        try:
            if metrics_collector and (success or failed):
                metrics_collector.publish(
                    {
                        'cancel_if_capped_attempts': float(len(to_cancel)),
                        'cancel_if_capped_success': float(success),
                        'cancel_if_capped_fail': float(failed),
                    },
                    labels={'source': 'cancel_if_capped'},
                )
        except Exception as e:
            log(f"and failed: {e}", level='warning')
    except Exception as e:
        log(f"cancel_open_buys_if_capped error: {e}", level='error')


def cancel_open_buys_by_age():
    """Cancel outstanding BUY limit orders older than LIMIT_ORDER_TIMEOUT_SECONDS.

    Behavior:
    - Only considers buy side orders with status new/open/partiallyfilled
    - Skips markets already present in `open_trades` (avoid DCA/partial-fill interference)
    - Uses order field `created` (Bitvavo milliseconds epoch) when available; skips orders without timestamp
    - Honors LIMIT_ORDER_CANCEL_BEHAVIOR, but currently only implements 'cancel_only'
    """
    try:
        timeout = int(CONFIG.get('LIMIT_ORDER_TIMEOUT_SECONDS', 0) or 0)
        if timeout <= 0:
            return
        behavior = str(CONFIG.get('LIMIT_ORDER_CANCEL_BEHAVIOR', 'cancel_only') or 'cancel_only')

        # Get grid markets + order IDs to protect from cancellation
        grid_markets = get_active_grid_markets()
        grid_order_ids = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_order_ids = gm.get_grid_order_ids()
        except Exception:
            pass

        orders = safe_call(bitvavo.ordersOpen, {}) or []
        now = time.time()
        to_cancel = []
        success = 0
        failed = 0
        ages: List[float] = []
        status_allowlist = {
            'new', 'open', 'partiallyfilled', 'partially filled', 'partiallyfilled', 'awaitingtrigger',
        }
        timestamp_keys = ('created', 'createdAt', 'timestamp', 'ts', 'time', 'lastUpdate', 'lastUpdated')
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in open_trades:
                    continue
                # CRITICAL: Skip grid trading orders
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = str(o.get('status', '')).lower().replace('_', '').replace('-', '').strip()
                if status not in status_allowlist:
                    continue

                # Limit orders only (skip any stop/market artifacts)
                order_type = str(o.get('type', '')).lower()
                if order_type and order_type != 'limit':
                    continue

                # Bitvavo returns 'created' in milliseconds; fallback checks for other keys
                created_ms = None
                for key in timestamp_keys:
                    if o.get(key) is not None:
                        try:
                            created_ms = int(o.get(key))
                            break
                        except Exception:
                            try:
                                created_ms = int(float(o.get(key)))
                                break
                            except Exception:
                                continue
                if not created_ms:
                    # Cannot determine age reliably; log once per run to aid debugging
                    if not getattr(cancel_open_buys_by_age, "_missing_ts_logged", False):
                        log(f"Skip cancel_open_buys_by_age: no timestamp for order {o.get('orderId')} ({market})", level='debug')
                        cancel_open_buys_by_age._missing_ts_logged = True
                    continue

                created_ts = created_ms / 1000.0
                age = now - created_ts
                if age >= timeout:
                    to_cancel.append((o.get('orderId'), market, age))
            except Exception:
                continue

        for orderId, market, age in to_cancel:
            try:
                # CRITICAL: Include operatorId for order cancellation
                if OPERATOR_ID:
                    res = bitvavo.cancelOrder(market, orderId, operatorId=str(OPERATOR_ID))
                else:
                    res = safe_call(bitvavo.cancelOrder, market, orderId)
                log(f"Canceled open BUY order {orderId} for {market} due to timeout ({int(age)}s >= {timeout}s): {res}", level='warning')
                success += 1
                ages.append(float(age))
            except Exception as e:
                log(f"Failed to cancel order {orderId} for {market}: {e}", level='error')
                failed += 1

        try:
            if metrics_collector and (success or failed):
                metrics_payload = {
                    'cancel_age_attempts': float(len(to_cancel)),
                    'cancel_age_success': float(success),
                    'cancel_age_fail': float(failed),
                }
                if ages:
                    metrics_payload['cancel_age_avg_s'] = float(statistics.mean(ages))
                    metrics_payload['cancel_age_max_s'] = float(max(ages))
                metrics_collector.publish(metrics_payload, labels={'source': 'cancel_by_age'})
        except Exception as e:
            log(f"and failed: {e}", level='warning')
    except Exception as e:
        log(f"cancel_open_buys_by_age error: {e}", level='error')

def get_markets_to_trade():
    whitelist = CONFIG.get('WHITELIST_MARKETS', [])
    supported = get_supported_markets()
    try:
        if CONFIG.get('SALDO_QUARANTINE_ENABLED'):
            quarantined = load_saldo_quarantine()
        else:
            quarantined = set()
    except Exception:
        quarantined = set()
    if quarantined:
        log(f"Quarantined markets: {sorted(list(quarantined))}. Review periodically and remove resolved ones from config.", level='info')
    
    # Exclude markets that are active in grid trading
    grid_markets = get_active_grid_markets()
    if grid_markets:
        log(f"Excluding grid trading markets from trailing bot: {sorted(grid_markets)}", level='info')
    
    # Trade only whitelisted markets, minus excluded/quarantined/grid
    candidates = [m for m in whitelist if m in supported and m not in EXCLUDED_MARKETS and m not in quarantined and m not in grid_markets]

    # Allow watchlist markets to run in micro mode before full promotion
    watch_cfg = _get_watchlist_runtime_settings()
    if watch_cfg['enabled'] and not watch_cfg['paper_only']:
        watchlist = [m for m in (CONFIG.get('WATCHLIST_MARKETS') or []) if m in supported and m not in EXCLUDED_MARKETS and m not in quarantined and m not in candidates]
        if watchlist:
            open_watch = [m for m in open_trades if is_watchlist_market(m)]
            pending_dict = _get_pending_markets_dict()
            reserved_watch = [m for m in pending_dict if is_watchlist_market(m)]
            slots = max(0, watch_cfg['max_parallel'] - len(open_watch) - len(reserved_watch))
            if slots > 0:
                ordered = _prioritize_watchlist_markets(watchlist)
                candidates.extend(ordered[:slots])

    return _perf.filter_markets_by_performance(candidates)


def get_24h_volume_eur(market: str) -> Optional[float]:
    """Fetch 24h volume for a market in EUR."""
    return _api.get_24h_volume_eur(market)

def _iso_to_ms(val):
    return _api._iso_to_ms(val)


def get_candles(market, interval='1m', limit=120, start=None, end=None):
    return _api.get_candles(market, interval, limit, start, end)

def calculate_adaptive_tp(market, entry_price, volatility=None, trend_strength=None):
    """Calculate adaptive take profit levels based on market conditions."""
    return _trail.calculate_adaptive_tp(market, entry_price, volatility, trend_strength)
def check_stop_loss(market, trade, current_price, enabled=False):
    """Hard stop-loss override for trailing logic (DISABLED by default)."""
    return _trail.check_stop_loss(market, trade, current_price, enabled)

def analyse_trades(trades):
    """Return (win_ratio, avg_win, avg_loss, avg_profit) as floats.
    Always returns four numeric floats even on errors or empty input.
    """
    from bot.portfolio import analyse_trades as _impl
    return _impl(trades)
def get_current_price(market, force_refresh=False):
    return _api.get_current_price(market, force_refresh=force_refresh)


def safe_mul(a, b):
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import safe_mul as _safe_mul
    return _safe_mul(a, b)


def _coerce_positive_float(value: Any) -> Optional[float]:
    # Delegated to bot.helpers (Fase 3 extraction)
    from bot.helpers import coerce_positive_float
    return coerce_positive_float(value)


def _resolve_dust_threshold(override: Optional[float] = None) -> Optional[float]:
    from bot.portfolio import resolve_dust_threshold as _impl
    return _impl(override)
def _compute_trade_value_eur(
    market: str,
    trade: Dict[str, Any],
    *,
    price_cache: Optional[Dict[str, Optional[float]]] = None,
) -> Tuple[Optional[float], Optional[float]]:
    from bot.portfolio import compute_trade_value_eur as _impl
    return _impl(market, trade, price_cache=price_cache)


def _iter_trade_values(price_cache: Optional[Dict[str, Optional[float]]]=None):
    from bot.portfolio import iter_trade_values as _impl
    yield from _impl(price_cache)
def get_true_invested_eur(trade: Dict[str, Any], market: str = '') -> float:
    """BULLETPROOF invested_eur calculation.
    
    Returns the TRUE current invested EUR for a trade.
    Cross-checks stored invested_eur against buy_price * amount.
    If they diverge by >20%, uses buy_price * amount (always correct).
    
    This is the ONLY function that should be used to get invested_eur
    for profit calculations, sell decisions, and logging.
    """
    buy_price = float(trade.get('buy_price', 0) or 0)
    amount = float(trade.get('amount', 0) or 0)
    stored_invested = float(trade.get('invested_eur', 0) or 0)
    total_invested = float(trade.get('total_invested_eur', 0) or 0)
    
    # Ground truth: what the position is actually worth at cost basis
    computed = round(buy_price * amount, 4) if buy_price > 0 and amount > 0 else 0.0
    
    if stored_invested <= 0 and total_invested > 0:
        stored_invested = total_invested
    
    if stored_invested <= 0 and computed > 0:
        # No stored value at all — use computed
        log(f"[INVESTED FIX] {market}: No stored invested_eur, using computed €{computed:.2f}", level='warning')
        trade['invested_eur'] = computed
        # Only set total/initial if they are also missing
        if total_invested <= 0:
            trade['total_invested_eur'] = computed
        if float(trade.get('initial_invested_eur', 0) or 0) <= 0:
            trade['initial_invested_eur'] = computed
        return computed
    
    if stored_invested > 0 and computed > 0:
        # Cross-check: if >20% divergence, the stored invested_eur is wrong
        divergence = abs(computed - stored_invested) / max(stored_invested, 0.01)
        if divergence > 0.20:
            log(f"[INVESTED FIX] {market}: stored invested €{stored_invested:.2f} vs computed €{computed:.2f} (divergence {divergence:.0%}) — CORRECTING invested_eur to computed", level='warning')
            trade['invested_eur'] = computed
            # CRITICAL: Do NOT overwrite total_invested_eur here!
            # total_invested_eur tracks cumulative cost (initial + DCAs) and must
            # never be reduced by partial TP or recalculation. It is the base for
            # final profit calculation: profit = (proceeds + partial_tp_revenue) - total_invested.
            # Only fix total/initial if they are clearly unset/zero.
            if total_invested <= 0:
                trade['total_invested_eur'] = computed
            init_inv = float(trade.get('initial_invested_eur', 0) or 0)
            if init_inv <= 0:
                trade['initial_invested_eur'] = computed
            return computed
    
    # Stored value is reasonable
    return stored_invested if stored_invested > 0 else computed
def count_active_open_trades(
    threshold: Optional[float] = None,
    *,
    price_cache: Optional[Dict[str, Optional[float]]] = None,
) -> int:
    from bot.portfolio import count_active_open_trades as _impl
    return _impl(threshold, price_cache=price_cache)


def get_pending_bitvavo_orders() -> List[Dict[str, Any]]:
    """Get list of pending BUY orders from Bitvavo that are NOT yet in open_trades.
    
    These orders count towards MAX_OPEN_TRADES to prevent over-allocation.
    Excludes grid trading orders to avoid conflicts.
    """
    try:
        # Get grid markets + order IDs to exclude
        grid_markets = get_active_grid_markets()
        grid_order_ids = set()
        try:
            from modules.grid_trading import get_grid_manager
            gm = get_grid_manager()
            grid_order_ids = gm.get_grid_order_ids()
        except Exception:
            pass

        orders = safe_call(bitvavo.ordersOpen, {}) or []
        pending = []
        for o in orders:
            try:
                if o.get('side') != 'buy':
                    continue
                market = o.get('market') or o.get('symbol')
                if not market or market in open_trades:
                    continue
                # CRITICAL: Skip grid trading orders
                if market in grid_markets or o.get('orderId') in grid_order_ids:
                    continue
                status = str(o.get('status', '')).lower().replace('_', '').replace('-', '').strip()
                if status not in {'new', 'open', 'partiallyfilled', 'partially filled', 'awaitingtrigger'}:
                    continue
                # Add to pending list
                created_ms = o.get('created', 0)
                age_sec = (time.time() * 1000 - created_ms) / 1000 if created_ms else 0
                pending.append({
                    'market': market,
                    'orderId': o.get('orderId'),
                    'amount': float(o.get('amount', 0) or 0),
                    'price': float(o.get('price', 0) or 0),
                    'status': o.get('status'),
                    'created': created_ms,
                    'age_seconds': age_sec,
                })
            except Exception:
                continue
        return pending
    except Exception as e:
        log(f"Error getting pending Bitvavo orders: {e}", level='debug')
        return []


def count_pending_bitvavo_orders() -> int:
    """Count pending BUY orders not yet in open_trades."""
    return len(get_pending_bitvavo_orders())
def count_dust_trades(threshold: Optional[float] = None) -> int:
    from bot.portfolio import count_dust_trades as _impl
    return _impl(threshold)
def current_open_exposure_eur(include_dust: bool = False) -> float:
    from bot.portfolio import current_open_exposure_eur as _impl
    return _impl(include_dust)
def estimate_max_eur_per_trade() -> Optional[float]:
    from bot.portfolio import estimate_max_eur_per_trade as _impl
    return _impl()
def estimate_max_total_eur() -> Optional[float]:
    from bot.portfolio import estimate_max_total_eur as _impl
    return _impl()
def get_ticker_best_bid_ask(m):
    return _api.get_ticker_best_bid_ask(m)

def spread_ok(m):
    return _api.spread_ok(m)

# =========================
# MARKET INFO / PRECISION CACHE
# =========================
def _decimals_from_str_num(s):
    return _api._decimals_from_str_num(s)

# =========================
# LIVE ORDER FUNCTIES
# =========================
def place_buy(market, eur_amount, entry_price, order_type=None):
    if TEST_MODE or not LIVE_TRADING:
        log(f"(SIM) BUY {market} €{eur_amount:.2f} @ {entry_price} [TEST_MODE]")
        return {"simulated": True}
    from bot.orders_impl import place_buy as _impl
    return _impl(market, eur_amount, entry_price, order_type)
def is_order_success(resp):
    """Return True if a Bitvavo order response indicates success.

    Heuristics:
    - resp must be a dict
    - no 'error' or 'errorCode' present
    - status must not be 'rejected' or 'expired'
    - simulated orders (TEST_MODE) are treated as success
    """
    from bot.orders_impl import is_order_success as _impl
    return _impl(resp)
def _verify_sell_response(sell_response: dict, market: str, expected_amount: float) -> tuple:
    """FIX #3: Verify sell response and handle chunked sells properly.
    
    Returns:
        (success: bool, order_ids: list, remaining_amount: float, actual_price: float or None)
    """
    from bot.orders_impl import _verify_sell_response as _impl
    return _impl(sell_response, market, expected_amount)
def safe_sell(market, amount_base, precision):
    """Attempt to sell even for tiny positions by rounding to allowed precision."""
    from bot.orders_impl import safe_sell as _impl
    return _impl(market, amount_base, precision)
def check_advanced_exit_strategies(trade, current_price):
    """Advanced exit: partial TP, time-based, volatility spike."""
    return _trail.check_advanced_exit_strategies(trade, current_price)


def place_sell(market, amount_base, *, skip_dust: bool = False):
    if TEST_MODE or not LIVE_TRADING:
        log(f"(SIM) SELL {market} amount={amount_base:.8f} [TEST_MODE]")
        return {"simulated": True}
    from bot.orders_impl import place_sell as _impl
    return _impl(market, amount_base, skip_dust=skip_dust)
def _cleanup_market_dust(market: str) -> None:
    from bot.orders_impl import _cleanup_market_dust as _impl
    return _impl(market)
def sweep_all_dust_positions() -> dict:
    """Sweep all dust positions from Bitvavo account that are below DUST_THRESHOLD_EUR.
    
    This function scans ALL balances and sells any positions worth less than threshold.
    Useful for cleaning up orphan dust that wasn't tracked by the bot.
    
    Returns:
        dict with 'swept' (list of markets swept) and 'errors' (list of failed markets)
    """
    from bot.orders_impl import sweep_all_dust_positions as _impl
    return _impl()
import signal as sig
import threading

def signal_strength(m):
    """Wrapper with timeout to prevent scan hanging"""
    return _signals.signal_strength(m)

def calculate_stop_levels(m, buy, high):
    """Calculate trailing stop, hard stop, and trend strength for a market."""
    _trail._open_trades = open_trades  # ensure ref is always current
    return _trail.calculate_stop_levels(m, buy, high)

def realized_profit(buy_price, sell_price, amount, buy_fee_pct=None, sell_fee_pct=None):
    """Calculate realized profit including trading fees."""
    return _trail.realized_profit(buy_price, sell_price, amount, buy_fee_pct, sell_fee_pct)

# =========================
# MAIN LOOP
# =========================
async def bot_loop():
    global scan_offset
    load_trades()
    log("🚀 Pro bot gestart en draait nu...")
    
    # SYNC VALIDATION: Check bot data matches Bitvavo on startup
    try:
        from pathlib import Path as PathLib
        from modules.sync_validator import SyncValidator
        trade_log_path = PathLib(TRADE_LOG)
        validator = SyncValidator(bitvavo, trade_log_path, logger=logging.getLogger(__name__))
        is_synced, issues = validator.validate_sync()
        if not is_synced:
            log(f"⚠️ DESYNC DETECTED on startup: {len(issues)} issues", level='warning')
            for issue in issues:
                log(f"  {issue}", level='warning')
            # Auto-fix desyncs
            log("Attempting auto-fix...", level='warning')
            fixed = validator.auto_fix_phantom_positions(dry_run=False)
            added = validator.auto_add_missing_positions(dry_run=False)
            log(f"Auto-fix: removed {fixed} phantoms, added {added} missing positions", level='warning')
            # Reload trades after fix
            if fixed > 0 or added > 0:
                load_trades()
                log("Trades reloaded after sync fix", level='warning')
    except Exception as sync_err:
        log(f"Sync validation failed: {sync_err}", level='error')
    
    start_time = time.time()
    last_config_reload = start_time
    last_sync_check = start_time  # Track last sync validation
    last_trade_integrity_check = start_time  # Track trade data validation

    while RUNNING:
        # Auto-stop for dry-run sanity tests
        if STOP_AFTER_SECONDS and (time.time() - start_time) >= STOP_AFTER_SECONDS:
            log(f"⏱️ STOP_AFTER_SECONDS reached ({STOP_AFTER_SECONDS}s), stopping bot loop.")
            break
        start_ts = time.time()
        # Config hot-reload (optional)
        try:
            reload_sec = int(CONFIG.get('CONFIG_HOT_RELOAD_SECONDS', 0) or 0)
            if reload_sec > 0 and (time.time() - last_config_reload) >= reload_sec:
                last_config_reload = time.time()
                from modules.config import load_config as _reload_cfg
                new_cfg = _reload_cfg()
                important_keys = (
                    'MAX_TOTAL_EXPOSURE_EUR',
                    'MAX_OPEN_TRADES',
                    'BASE_AMOUNT_EUR',
                )
                before_snapshot = {k: CONFIG.get(k) for k in important_keys}
                for k, v in new_cfg.items():
                    CONFIG[k] = v
                after_snapshot = {k: CONFIG.get(k) for k in important_keys}
                delta_bits = []
                for key in important_keys:
                    before_val = before_snapshot.get(key)
                    after_val = after_snapshot.get(key)
                    if before_val != after_val:
                        delta_bits.append(f"{key} {before_val}->{after_val}")
                if delta_bits:
                    log("Config hot-reload applied: " + ", ".join(delta_bits))
                else:
                    log(
                        "Config hot-reload applied: guardrail keys unchanged "
                        f"({', '.join(f'{k}={after_snapshot.get(k)}' for k in important_keys)})"
                    )
        except Exception as e:
            log(f"[ERROR] Config hot-reload failed: {e}", level='error')
        
        # EXTERNAL SELL DETECTION: Check for manual sells every 6 hours
        try:
            external_sell_check_interval = 6 * 3600  # 6 hours
            if (time.time() - last_sync_check) >= external_sell_check_interval:
                last_sync_check = time.time()
                log("[EXTERNAL_SELL] Checking for manual sells outside bot...", level='debug')
                from modules.external_sell_detector import detect_external_sells, apply_external_sell_resets
                from pathlib import Path
                
                # Get all open markets
                open_markets = list(open_trades.keys())
                if open_markets:
                    resets = detect_external_sells(bitvavo, Path(TRADE_LOG), open_markets)
                    if resets:
                        log(f"[EXTERNAL_SELL] Found {len(resets)} trades needing reset after manual sells", level='warning')
                        count = apply_external_sell_resets(Path(TRADE_LOG), resets)
                        log(f"[EXTERNAL_SELL] Reset {count} trades to current position (cleared old DCA history)", level='warning')
                        # Reload trades after reset
                        load_trades()
                    else:
                        log("[EXTERNAL_SELL] No external sells detected", level='debug')
        except Exception as ext_sell_err:
            log(f"[EXTERNAL_SELL] Check failed: {ext_sell_err}", level='error')
        
        # TRADE INTEGRITY CHECK: Validate and repair corrupt data every hour
        try:
            trade_integrity_interval = 3600  # 1 hour
            if (time.time() - last_trade_integrity_check) >= trade_integrity_interval:
                last_trade_integrity_check = time.time()
                validate_and_repair_trades()
        except Exception as integrity_err:
            log(f"[INTEGRITY] Check failed: {integrity_err}", level='warning')
        
        # Heartbeat: update last alive timestamp and periodic log for monitoring
        try:
            CONFIG['LAST_HEARTBEAT_TS'] = int(time.time())
        except Exception as e:
            log(f"[ERROR] Heartbeat TS update failed: {e}", level='error')
        # Log a lightweight heartbeat every ~6 loops to avoid noisy logs
        if not hasattr(bot_loop, 'hb_counter'):
            bot_loop.hb_counter = 0
        bot_loop.hb_counter += 1
        if bot_loop.hb_counter >= 6:
            bot_loop.hb_counter = 0
            active_trades = count_active_open_trades(threshold=DUST_TRADE_THRESHOLD_EUR)
            dust_count = count_dust_trades()
            hb_msg = (
                f"Heartbeat: bot is alive. Open trades={active_trades}, dust={dust_count}, "
                f"EUR balance check at {datetime.utcnow().isoformat()}Z"
            )
            log(hb_msg)
            try:
                with open(HEARTBEAT_FILE, 'a', encoding='utf-8') as fh:
                    fh.write(
                        json.dumps(
                            {
                                'ts': int(time.time()),
                                'open_trades': active_trades,
                                'open_trades_including_dust': len(open_trades),
                                'dust_trade_count': dust_count,
                                'eur_balance': eur_balance if 'eur_balance' in locals() else None,
                            }
                        )
                        + '\n'
                    )
            except Exception as e:
                log(f"encoding failed: {e}", level='error')
            try:
                bot_loop.last_portfolio_snapshot = write_portfolio_snapshot()
            except Exception:
                bot_loop.last_portfolio_snapshot = None
            try:
                balances_for_overview = getattr(bot_loop, 'last_balances', None)
                eur_for_overview = getattr(bot_loop, 'last_eur_balance', None)
                bot_loop.last_account_overview = write_account_overview(
                    balances=balances_for_overview,
                    snapshot=bot_loop.last_portfolio_snapshot,
                    eur_balance=eur_for_overview,
                )
            except Exception:
                bot_loop.last_account_overview = None
        # Emergency and adaptive controls before market scans
        saldo_flood_guard()
        free_capacity_if_needed()
        if not hasattr(bot_loop, 'tuning_counter'):
            bot_loop.tuning_counter = 0
        bot_loop.tuning_counter += 1
        tuning_every = int(CONFIG.get('PERF_TUNING_INTERVAL_LOOPS', 12) or 12)
        if tuning_every <= 0:
            tuning_every = 12
        if bot_loop.tuning_counter >= tuning_every:
            bot_loop.tuning_counter = 0
            apply_dynamic_performance_tweaks()
            await maybe_run_ml_optimizer()
        
        # === GRID TRADING: Fully automated grid bot ===
        try:
            grid_cfg = CONFIG.get('GRID_TRADING', {})
            grid_enabled = grid_cfg.get('enabled', False)
            if not hasattr(bot_loop, 'grid_counter'):
                bot_loop.grid_counter = 9999  # Trigger immediately on first loop
            if grid_enabled:
                bot_loop.grid_counter += SLEEP_SECONDS
                # Run grid manager every 45 seconds (starts immediately)
                grid_interval = 45
                if bot_loop.grid_counter >= grid_interval:
                    bot_loop.grid_counter = 0
                    log(f"[Grid] Triggering auto_manage...", level='info')
                    from modules.grid_trading import get_grid_manager
                    grid_mgr = get_grid_manager(bitvavo, CONFIG)
                    grid_result = grid_mgr.auto_manage()
                    log(f"[Grid] Auto-manage result: {grid_result}", level='info')
            else:
                if bot_loop.grid_counter == 9999:
                    log(f"[Grid] DISABLED in config (GRID_TRADING.enabled={grid_enabled})", level='warning')
                    bot_loop.grid_counter = 0  # Only log once
        except Exception as grid_err:
            import traceback
            log(f"[Grid] Auto-manage error: {grid_err}\n{traceback.format_exc()}", level='error')

        # Periodic dust sweep: clean up small orphan balances
        if not hasattr(bot_loop, 'dust_sweep_counter'):
            bot_loop.dust_sweep_counter = 0
        bot_loop.dust_sweep_counter += SLEEP_SECONDS
        dust_sweep_interval = int(CONFIG.get('DUST_SWEEP_INTERVAL_SECONDS', 3600) or 3600)  # Default: 1 hour
        if dust_sweep_interval > 0 and bot_loop.dust_sweep_counter >= dust_sweep_interval:
            bot_loop.dust_sweep_counter = 0
            try:
                result = sweep_all_dust_positions()
                if result.get('swept'):
                    log(f"[dust_sweep] Periodic sweep: {len(result['swept'])} positions cleaned", level='info')
            except Exception as exc:
                log(f"[dust_sweep] Periodic sweep failed: {exc}", level='debug')
        
        # Optional safety: proactively cancel open buy orders when cap reached
        try:
            if CONFIG.get('CANCEL_OPEN_BUYS_WHEN_CAPPED', True):
                cancel_open_buys_if_capped()
        except Exception as e:
            log(f"[ERROR] cancel_open_buys_if_capped failed: {e}", level='error')
        # Periodic: cancel old limit buy orders based on configured timeout
        try:
            cancel_open_buys_by_age()
        except Exception as e:
            log(f"[ERROR] cancel_open_buys_by_age failed: {e}", level='error')
        # Periodic sync from Bitvavo if enabled in config
        try:
            # Forceer SYNC_ENABLED en SYNC_INTERVAL_SECONDS opstart
            CONFIG['SYNC_ENABLED'] = True
            CONFIG['SYNC_INTERVAL_SECONDS'] = 300  # 5 minuten
            if CONFIG.get('SYNC_ENABLED'):
                if not hasattr(bot_loop, 'sync_counter'):
                    bot_loop.sync_counter = 0
                bot_loop.sync_counter += SLEEP_SECONDS
                if bot_loop.sync_counter >= CONFIG.get('SYNC_INTERVAL_SECONDS', 300):
                    bot_loop.sync_counter = 0
                    # run sync in a background thread to avoid blocking the async loop
                    try:
                        await asyncio.to_thread(sync_with_bitvavo)
                    except Exception as e:
                        log(f"Periodic sync failed: {e}", level='error')
        except Exception:
            # don't let sync errors stop the main loop
            pass
        
        # PERIODIC SYNC VALIDATION: Check every 10 minutes for faster manual coin detection
        try:
            sync_check_interval = 600  # 10 minutes (was 30 min)
            if (time.time() - last_sync_check) >= sync_check_interval:
                last_sync_check = time.time()
                log("Running periodic sync validation...")
                from pathlib import Path as PathLib
                from modules.sync_validator import SyncValidator
                trade_log_path = PathLib(TRADE_LOG)
                validator = SyncValidator(bitvavo, trade_log_path, logger=logging.getLogger(__name__))
                is_synced, issues = validator.validate_sync()
                if not is_synced:
                    log(f"⚠️ DESYNC DETECTED: {len(issues)} issues - attempting auto-fix", level='warning')
                    fixed = validator.auto_fix_phantom_positions(dry_run=False)
                    added = validator.auto_add_missing_positions(dry_run=False)
                    if fixed > 0 or added > 0:
                        load_trades()
                        log(f"Sync restored: removed {fixed} phantoms, added {added} missing", level='warning')
                
                # INVESTED_EUR SYNC: Ensure cost basis is accurate with Bitvavo API
                if CONFIG.get('INVESTED_EUR_SYNC_ENABLED', True):
                    try:
                        from modules.invested_sync import sync_invested_eur
                        invested_fixes = sync_invested_eur(bitvavo, open_trades, force=False, silent=False)
                        if invested_fixes > 0:
                            save_trades()
                            log(f"[InvestedSync] Updated {invested_fixes} trades with accurate cost basis")
                    except Exception as inv_sync_err:
                        log(f"[InvestedSync] Failed: {inv_sync_err}", level='debug')
        except Exception as sync_val_err:
            log(f"Periodic sync validation failed: {sync_val_err}", level='error')
        
        all_markets = get_markets_to_trade()
        total = len(all_markets)

        # blok-scan patch
        if total > MAX_MARKETS_PER_SCAN:
            start = scan_offset % total
            end = start + MAX_MARKETS_PER_SCAN
            if end <= total:
                MARKETS = all_markets[start:end]
            else:
                MARKETS = all_markets[start:] + all_markets[:end - total]
            scan_offset = (scan_offset + MAX_MARKETS_PER_SCAN) % total
        else:
            MARKETS = all_markets

        _log_throttled('scan_start', f"Nieuwe scan gestart: {len(MARKETS)} markten (totaal {total})")

        log(f"[DEBUG-MANAGE] Starting manage loop. Open trades: {len(open_trades)}", level='debug')

        # === Manage open trades ===
        
        # Build set of HODL markets to skip in trailing/stoploss
        hodl_markets_set = set()
        try:
            hodl_cfg = CONFIG.get('HODL_SCHEDULER') or {}
            for sched in (hodl_cfg.get('schedules') or []):
                market = sched.get('market', '')
                if market:
                    hodl_markets_set.add(market.upper())
        except Exception as e:
            log(f"[ERROR] HODL markets config parse failed: {e}", level='error')

        # Initialize correlation shield flags before per-trade loop
        # (full evaluation happens later, but flags are referenced in stop-loss checks)
        if '_corr_tighten_stops' not in dir() or not isinstance(_corr_tighten_stops, bool):
            _corr_tighten_stops = False
        if '_corr_block_entries' not in dir() or not isinstance(_corr_block_entries, bool):
            _corr_block_entries = False

        for m in list(open_trades.keys()):
            # Skip HODL assets entirely - they should not be managed by trailing bot
            if m.upper() in hodl_markets_set:
                continue
            
            t = open_trades.get(m)
            if not isinstance(t, dict):
                continue
            # CRITICAL: Force fresh price for open trades to catch peaks
            cp = get_current_price(m, force_refresh=True)
            if not cp:
                continue
            
            # Log price check for debugging highest_price tracking
            try:
                current_hp = t.get('highest_price')
                buy_price = t.get('buy_price')
                hp_str = f"{current_hp:.8f}" if isinstance(current_hp, (int, float)) else 'None'
                bp_str = f"{buy_price:.8f}" if isinstance(buy_price, (int, float)) else 'None'
                log(f"[PRICE_CHECK] {m}: cp={cp:.8f}, highest={hp_str}, buy={bp_str}", level='debug')
            except Exception as e:
                log(f"[PRICE_CHECK] {m}: Error logging price check: {e}", level='debug')
            
            # Ensure common fields exist with safe defaults to avoid KeyError/TypeError
            try:
                t.setdefault('amount', 0.0)
                t.setdefault('buy_price', float(cp))
                t.setdefault('highest_price', float(cp))
                _ensure_tp_flags(t)
                t.setdefault('dca_buys', 0)
                # safe default for next DCA price: compute if missing or non-positive
                dca_prices_changed = False
                try:
                    existing_next = t.get('dca_next_price')
                    if not isinstance(existing_next, (int, float)) or existing_next <= 0:
                        new_dca_next = float(t.get('buy_price', cp)) * (1 - DCA_DROP_PCT)
                        t['dca_next_price'] = new_dca_next
                        log(f"[DCA] {m}: dca_next_price initialized to {new_dca_next:.8f}", level='debug')
                        dca_prices_changed = True
                except Exception as e:
                    log(f"[ERROR] Failed to calculate dca_next_price for {m}: {e}", level='error')
                    try:
                        t['dca_next_price'] = float(cp)
                        dca_prices_changed = True
                    except Exception:
                        t['dca_next_price'] = 0.0
                        dca_prices_changed = True
                t.setdefault('tp_last_time', 0.0)
                # ensure last_dca_price defaults to buy_price when missing or falsy
                try:
                    existing_last = t.get('last_dca_price')
                    if not isinstance(existing_last, (int, float)) or existing_last <= 0:
                        new_last_dca = float(t.get('buy_price', cp))
                        t['last_dca_price'] = new_last_dca
                        log(f"[DCA] {m}: last_dca_price initialized to {new_last_dca:.8f}", level='debug')
                        dca_prices_changed = True
                except Exception as e:
                    log(f"[ERROR] Failed to set last_dca_price for {m}: {e}", level='error')
                    t.setdefault('last_dca_price', t.get('buy_price'))
                    dca_prices_changed = True
                
                # CRITICAL FIX #4: Save DCA prices immediately after initialization
                if dca_prices_changed:
                    save_trades()
                # record when this trade was opened
                t.setdefault('opened_ts', t.get('timestamp', time.time()))
            except Exception as e:
                log(f"[ERROR] Trade init fields failed for {m}: {e}", level='error')
            # FIX #2: Check if sell is already in progress for this trade
            if t.get('_sell_in_progress'):
                log(f"[GUARD] Sell already in progress for {m}, skipping", level='debug')
                continue
            
            # Ensure highest_price is numeric before comparing — avoid TypeError when it's None
            try:
                hp = t.get('highest_price') if isinstance(t, dict) else None
            except Exception:
                hp = None
            if hp is None or (isinstance(hp, (int, float)) and cp > float(hp)):
                try:
                    old_hp = hp
                    t['highest_price'] = float(cp)
                    log(f"[PRICE_TRACK] {m}: highest_price updated {old_hp} -> {cp}", level='info')
                    # CRITICAL FIX: Save immediately after highest_price update
                    save_trades()
                except Exception:
                    t['highest_price'] = cp
                    save_trades()

            # === Fail-safe exits: max age and max drawdown ===
            try:
                # Max age in hours
                max_age_h = float(CONFIG.get('MAX_TRADE_AGE_HOURS', 0) or 0)
                if max_age_h > 0:
                    opened_ts = float(t.get('opened_ts', t.get('timestamp', time.time())))
                    if (time.time() - opened_ts) >= max_age_h * 3600:
                        amt = float(t.get('amount', 0.0) or 0.0)
                        if amt > 0:
                            # PROTECTION: Never sell at a loss for max_age — only stop-loss may sell at loss
                            cp_check = float(cp) if cp else 0
                            bp_check = float(t.get('buy_price', 0) or 0)
                            if bp_check > 0 and cp_check < bp_check:
                                log(f"🛑 Max age exit BLOCKED for {m}: position in loss ({((cp_check/bp_check)-1)*100:.1f}%). Only stop-loss may sell at loss.", level='warning')
                                continue
                            log(f"Max trade age reached for {m} (>{max_age_h}h), forcing exit.", level='warning')
                            
                            # FIX #2: Order verification with actual price
                            sell_response = place_sell(m, amt)
                            
                            success, order_ids, remaining, actual_sell_price = _verify_sell_response(sell_response, m, amt)
                            if not success:
                                error_msg = sell_response.get('error', 'Sell verification failed') if sell_response else 'No response'
                                log(f"❌ MAX AGE SELL FAILED for {m}: {error_msg} - Trade NOT closed", level='error')
                                continue
                            
                            final_sell_price = actual_sell_price if actual_sell_price else cp
                            sell_order_id = order_ids[0] if order_ids else None
                            # Fee-aware P&L: use invested_eur-based calculation (consistent with trailing/SL)
                            current_invested = get_true_invested_eur(t, market=m)
                            gross_sell = float(final_sell_price) * amt
                            sell_fee = gross_sell * FEE_TAKER
                            net_proceeds = gross_sell - sell_fee
                            profit = net_proceeds - current_invested
                            
                            # FIX #3: Add order ID tracking
                            closed_entry = {
                                'market': m,
                                'buy_price': t.get('buy_price', 0.0),
                                'buy_order_id': t.get('buy_order_id'),
                                'sell_price': final_sell_price,
                                'sell_order_id': sell_order_id,
                                'sell_order_ids': order_ids,
                                'amount': amt,
                                'invested_eur': current_invested,
                                'gross_sell': round(gross_sell, 4),
                                'sell_fee': round(sell_fee, 4),
                                'profit': round(profit, 4),
                                'timestamp': time.time(),
                                'reason': 'max_age',
                            }
                            _finalize_close_trade(m, t, closed_entry)
                            log(f"✅ Max age exit successful: {m} - Profit: €{profit:.2f} (Order ID: {sell_order_id})", level='info')
                            continue
            except Exception as e:
                log(f"operation failed: {e}", level='debug')
            try:
                dd_pct = float(CONFIG.get('MAX_DRAWDOWN_SL_PCT', 0) or 0)
                if dd_pct > 0:
                    bp = float(t.get('buy_price', cp) or cp)
                    if bp > 0 and cp <= bp * (1 - dd_pct):
                        # STALE BUY_PRICE GUARD for drawdown SL
                        _dd_loss_pct = (bp - cp) / bp if bp > 0 else 0
                        if _dd_loss_pct > 0.40:
                            log(f"⚠️ STALE GUARD: {m} drawdown SL would trigger with {_dd_loss_pct*100:.1f}% loss (bp={bp:.6f}, cp={cp:.6f}). Skipping — buy_price may be stale.", level='error')
                            t['_stale_bp_flagged'] = True
                            continue
                        amt = float(t.get('amount', 0.0) or 0.0)
                        if amt > 0:
                            log(f"Drawdown stop hit for {m} (>{dd_pct*100:.1f}% down), forcing exit.", level='warning')
                            
                            # FIX #2: Order verification with actual price
                            sell_response = place_sell(m, amt)
                            
                            success, order_ids, remaining, actual_sell_price = _verify_sell_response(sell_response, m, amt)
                            if not success:
                                error_msg = sell_response.get('error', 'Sell verification failed') if sell_response else 'No response'
                                log(f"❌ MAX DRAWDOWN SELL FAILED for {m}: {error_msg} - Trade NOT closed", level='error')
                                continue
                            
                            final_sell_price = actual_sell_price if actual_sell_price else cp
                            sell_order_id = order_ids[0] if order_ids else None
                            # Fee-aware P&L: use invested_eur-based calculation (consistent with trailing/SL)
                            current_invested = get_true_invested_eur(t, market=m)
                            gross_sell = float(final_sell_price) * amt
                            sell_fee = gross_sell * FEE_TAKER
                            net_proceeds = gross_sell - sell_fee
                            profit = net_proceeds - current_invested
                            
                            # FIX #3: Add order ID tracking
                            closed_entry = {
                                'market': m,
                                'buy_price': bp,
                                'buy_order_id': t.get('buy_order_id'),
                                'sell_price': final_sell_price,
                                'sell_order_id': sell_order_id,
                                'sell_order_ids': order_ids,
                                'amount': amt,
                                'invested_eur': current_invested,
                                'gross_sell': round(gross_sell, 4),
                                'sell_fee': round(sell_fee, 4),
                                'profit': round(profit, 4),
                                'timestamp': time.time(),
                                'reason': 'max_drawdown',
                            }
                            _finalize_close_trade(m, t, closed_entry)
                            continue
            except Exception as e:
                log(f"operation failed: {e}", level='debug')

            # === DCA/Safety Order Logic ===
            if dca_manager and dca_settings:
                # capture old buy_price to detect changes after DCA
                try:
                    old_buy = float(t.get('buy_price') or 0.0)
                except Exception:
                    old_buy = 0.0
                dca_manager.handle_trade(
                    m,
                    t,
                    cp,
                    dca_settings,
                    partial_tp_levels=PARTIAL_TP_LEVELS,
                )
                # After DCA, optionally reset trailing activation when average buy increased
                try:
                    new_buy = float(t.get('buy_price') or 0.0)
                    if RESET_TRAILING_ON_DCA and new_buy > 0 and old_buy > 0:
                        pct_inc = (new_buy - old_buy) / old_buy
                        if pct_inc >= float(RESET_TRAILING_ON_DCA_IF_BUY_INCREASE_PCT or 0.0):
                            # Reset trailing activation metadata
                            t['trailing_activated'] = False
                            t['activation_price'] = None
                            t['highest_since_activation'] = None
                            log(f"Trailing reset on DCA for {m}: buy {old_buy:.8f} -> {new_buy:.8f} (+{pct_inc:.2%}), threshold={RESET_TRAILING_ON_DCA_IF_BUY_INCREASE_PCT}")
                except Exception as e:
                    log(f"[ERROR] Trailing reset on DCA failed for {m}: {e}", level='error')

            # === TP logic removed: only trailing and hard stop-loss exits are allowed ===

            # If all amount sold, close trade
            if t.get('amount', 0.0) <= 0.00001:
                log(f"Trade volledig gesloten voor {m} na trailing TP.")
                if m in open_trades:
                    del open_trades[m]
                continue

            # Ensure trailing activation fields exist (persist across DCA events)
            t.setdefault('trailing_activated', False)
            t.setdefault('activation_price', None)
            t.setdefault('highest_since_activation', None)
            
            # === ADVANCED EXIT STRATEGIES (before trailing/hard stop) ===
            advanced_exit, exit_portion, exit_reason = check_advanced_exit_strategies(t, cp)
            if advanced_exit and exit_portion > 0:
                amt = t.get('amount', 0.0)
                sell_amount = amt * exit_portion
                
                # FIX: If partial sell amount is below Bitvavo minimum order, sell 100% instead
                partial_sell_eur = cp * sell_amount
                if partial_sell_eur < MIN_ORDER_EUR and exit_portion < 1.0:
                    log(f"⚡ Partial TP for {m}: €{partial_sell_eur:.2f} below min €{MIN_ORDER_EUR:.0f}, upgrading to 100% sell", level='info')
                    exit_portion = 1.0
                    sell_amount = amt
                
                # FIX: Normalize sell_amount to market precision BEFORE sending
                sell_amount = normalize_amount(m, sell_amount)
                if sell_amount <= 0:
                    log(f"⚠️ Sell amount for {m} normalized to 0, skipping exit", level='warning')
                    continue
                
                profit = realized_profit(t.get('buy_price', 0.0), cp, sell_amount)
                
                # CRITICAL SAFETY CHECK: Verify against actual invested amount (accounts for DCA)
                # Use get_true_invested_eur() — ALWAYS cross-checks against buy_price * amount
                current_invested = get_true_invested_eur(t, market=m)
                total_invested = float(t.get('total_invested_eur', current_invested) or current_invested)
                proportional_invested = current_invested * exit_portion
                gross_sell = cp * sell_amount
                sell_fee = gross_sell * FEE_TAKER
                net_proceeds = gross_sell - sell_fee
                real_profit = net_proceeds - proportional_invested
                
                tp_level_idx: Optional[int] = None
                tp_target_pct: Optional[float] = None
                tp_config_pct: Optional[float] = None
                if exit_reason and exit_reason.startswith('partial_tp_'):
                    try:
                        tp_level_idx = int(exit_reason.split('_')[-1]) - 1
                    except Exception:
                        tp_level_idx = None
                    if tp_level_idx is not None and 0 <= tp_level_idx < len(PARTIAL_TP_LEVELS):
                        tp_target_pct, tp_config_pct = PARTIAL_TP_LEVELS[tp_level_idx]
                    else:
                        tp_level_idx = None
                
                if real_profit > 0:  # Only execute if REALLY profitable (accounts for DCA)
                    log(f"Advanced exit: {exit_reason} for {m} - Selling {exit_portion*100:.0f}% for €{real_profit:.2f} real profit (calc: €{profit:.2f})")
                    
                    # FIX #2: Mark sell in progress
                    t['_sell_in_progress'] = True
                    
                    # FIX #2: Order verification - check if sell succeeds
                    sell_response = place_sell(m, sell_amount)
                    
                    # FIX #3: Verify sell response properly (handles chunked sells)
                    success, order_ids, remaining, actual_sell_price = _verify_sell_response(sell_response, m, sell_amount)
                    
                    # Clear sell in progress flag
                    t.pop('_sell_in_progress', None)
                    
                    if not success:
                        error_msg = sell_response.get('error', 'Sell verification failed') if sell_response else 'No response'
                        log(f"❌ SELL FAILED for {m}: {error_msg} - Trade NOT closed", level='error')
                        continue  # Skip closing trade if sell failed
                    
                    # FIX #5: Use actual execution price if available
                    final_sell_price = actual_sell_price if actual_sell_price else cp
                    if actual_sell_price and abs(actual_sell_price - cp) / cp > 0.01:  # >1% diff
                        log(f"Price slippage for {m}: expected {cp:.8f}, executed {actual_sell_price:.8f} ({(actual_sell_price-cp)/cp*100:+.2f}%)", level='warning')
                    
                    # Recalculate profit with actual execution price
                    if actual_sell_price:
                        gross_sell = actual_sell_price * sell_amount
                        sell_fee = gross_sell * FEE_TAKER
                        net_proceeds = gross_sell - sell_fee
                        real_profit = net_proceeds - proportional_invested
                    
                    # Extract primary order ID
                    sell_order_id = order_ids[0] if order_ids else None
                    
                    if tp_level_idx is not None and tp_target_pct is not None:
                        _record_partial_tp_event(
                            market=m,
                            trade=t,
                            level_idx=tp_level_idx,
                            target_pct=tp_target_pct,
                            sell_pct=exit_portion,
                            configured_pct=tp_config_pct,
                            sell_amount=sell_amount,
                            sell_price=final_sell_price,
                            profit_eur=real_profit,  # Use REAL profit
                            remaining_amount=max(0.0, float(amt or 0.0) - float(sell_amount)),
                        )
                    
                    # Update trade or close completely
                    if exit_portion >= 1.0:
                        # Full exit
                        closed_entry = {
                            'market': m,
                            'buy_price': t.get('buy_price', 0.0),
                            'buy_order_id': t.get('buy_order_id'),
                            'sell_price': final_sell_price,
                            'sell_order_id': sell_order_id,
                            'sell_order_ids': order_ids,  # All order IDs for chunked sells
                            'amount': sell_amount,
                            'profit': round(real_profit, 4),
                            'profit_calculated': round(profit, 4),
                            'proportional_invested': round(proportional_invested, 4),
                            'timestamp': time.time(),
                            'reason': exit_reason,
                        }
                        _finalize_close_trade(m, t, closed_entry, update_market_profits=True, profit_for_market=real_profit)
                        log(f"✅ Trade closed: {m} - Real Profit: €{real_profit:.2f} @ €{final_sell_price:.8f} (Order ID: {sell_order_id})", level='info')
                        continue  # Skip other exit checks
                    else:
                        # FIX #2: Partial exit - update trade amount with lock
                        with trades_lock:
                            t['amount'] = amt - sell_amount
                            # Use TradeInvestment module for invested_eur reduction
                            from core.trade_investment import reduce_partial_tp
                            reduce_partial_tp(t, exit_portion, source="partial_tp_sell")
                            # Track partial TP revenue for correct final profit calculation
                            t['partial_tp_returned_eur'] = float(t.get('partial_tp_returned_eur', 0)) + net_proceeds
                            flags = _ensure_tp_flags(t)
                            if tp_level_idx is not None and 0 <= tp_level_idx < len(flags):
                                flags[tp_level_idx] = True
                        save_trades(force=True)  # Force save after partial TP
                        log(f"✅ Partial sell: {m} - Sold {exit_portion*100:.0f}%, Real Profit: €{real_profit:.2f}, Returned: €{net_proceeds:.2f} @ €{final_sell_price:.8f} (Order ID: {sell_order_id})", level='info')
                        try:
                            _ptp_msg = (
                                f"💰 <b>Partial TP: {m}</b>\n"
                                f"Verkocht: {exit_portion*100:.0f}% ({sell_amount:.6f})\n"
                                f"Prijs: €{final_sell_price:.4f}\n"
                                f"Winst: €{real_profit:+.2f}\n"
                                f"Terug: €{net_proceeds:.2f}\n"
                                f"Resterend: {max(0.0, float(amt or 0) - float(sell_amount)):.6f}"
                            )
                            send_alert(_ptp_msg)
                        except Exception:
                            pass

            # Prefer preserved high-water mark when trailing was activated; otherwise use current highest_price
            try:
                hp_current = float(t.get('highest_price', 0.0) or 0.0)
            except Exception:
                hp_current = 0.0
            try:
                bp_current = float(t.get('buy_price', 0.0) or 0.0)
            except Exception:
                bp_current = 0.0

            if t.get('trailing_activated'):
                try:
                    prev_hw = float(t.get('highest_since_activation') or hp_current)
                except Exception:
                    prev_hw = hp_current
                t['highest_since_activation'] = max(prev_hw, hp_current)
                hw = t['highest_since_activation']
            else:
                hw = hp_current

            result = calculate_stop_levels(m, bp_current, hw)
            # Safe unpacking: always 4 values
            if not isinstance(result, (list, tuple)):
                result = (0, 0, 0, 0)
            if len(result) < 4:
                result = tuple(list(result) + [0] * (4 - len(result)))
            try:
                stop, trailing, hard, trend_strength = result
            except Exception as e:
                log(f"[ERROR] Fout bij unpacking calculate_stop_levels voor {m}: {e}", level='error')
                stop, trailing, hard, trend_strength = 0, 0, 0, 0

            # ── Correlation Shield: tighten stops during cascade events ──
            if _corr_tighten_stops and hard > 0:
                try:
                    from core.correlation_shield import get_tightened_sl_pct
                    _orig_hard = hard
                    _cascade_level = 1  # default cascade level
                    _hard_sl_pct = (bp_current - hard) / bp_current if bp_current > 0 else 0.05
                    _tight_sl_pct = get_tightened_sl_pct(_hard_sl_pct, _cascade_level)
                    hard = bp_current * (1 - _tight_sl_pct)
                    if hard != _orig_hard:
                        _log_throttled(f'corr_tighten_{m}', f"[CORR_SHIELD] {m}: SL tightened {_hard_sl_pct:.2%} → {_tight_sl_pct:.2%} (cascade active)", level='info')
                except Exception as _ct_err:
                    log(f"[CORR_SHIELD] {m}: Tighten error: {_ct_err}", level='debug')
            # Store trailing stop price in trade for dashboard display
            if trailing and trailing > 0 and t.get('trailing_activated'):
                old_ts = t.get('trailing_stop')
                t['trailing_stop'] = round(trailing, 8)
                if old_ts != t['trailing_stop']:
                    _log_throttled(f'trail_stop_{m}', f"[TRAIL_STOP] {m}: stop={trailing:.8f} (highest={hw})", level='debug')
            elif t.get('trailing_activated') and (not trailing or trailing <= 0):
                _log_throttled(f'trail_stop_zero_{m}', f"[TRAIL_STOP] {m}: trailing=0 from calculate_stop_levels (buy={bp_current}, hw={hw})", level='debug')
            # Smart stoploss: move closer in strong uptrend
            custom_stop = None
            if trend_strength > 0.04:
                custom_stop = max(trailing, hard, t.get('buy_price', 0.0) * 0.995)
                log(f"Smart stoploss: {m} trend {trend_strength:.3f}, stop verplaatst naar {custom_stop:.6f}")
                _log_throttled(f'trail_{m}', f"{m}: prijs {cp:.6f}, trailing {trailing:.6f}, hard {hard:.6f}, stop {stop:.6f}, trend {trend_strength:.3f}", level='debug')
            risk_stop_price = None
            try:
                rsp = t.get('risk_stop_price')
                risk_stop_price = float(rsp) if rsp is not None else None
            except Exception:
                risk_stop_price = None
            final_stop_candidates = [
                value
                for value in (custom_stop, stop, risk_stop_price)
                if isinstance(value, (int, float)) and value > 0
            ]
            final_stop = min(final_stop_candidates) if final_stop_candidates else stop
            
            # === BREAKEVEN LOCK ===
            # Lock in breakeven when price is +3% or higher to protect capital
            # Lock at +0.6% to cover fees (0.25% buy + 0.25% sell + slippage)
            try:
                bp = float(t.get('buy_price', 0.0) or 0.0)
                if bp > 0 and cp >= bp * 1.03:  # +3% threshold
                    breakeven_price = bp * 1.006  # Cover fees + small profit (0.6%)
                    if breakeven_price > final_stop:
                        final_stop = breakeven_price
                        if not t.get('breakeven_locked'):
                            t['breakeven_locked'] = True
                            log(f"{m}: Breakeven lock activated at {breakeven_price:.6f} (entry: {bp:.6f})")
                            save_trades()  # CRITICAL FIX #6: Save breakeven lock immediately
            except Exception as e:
                log(f"[ERROR] Breakeven lock calculation failed for {m}: {e}", level='error')
            
            # Trailing take-profit exit can be enabled even when STOP_LOSS_ENABLED is False.
            # Only trigger trailing after activation (price moved sufficiently above average)
            # Activation logic: persist activation so later DCA updates won't cancel an active trailing
            activation_ok = False
            try:
                bp = float(t.get('buy_price', 0.0) or 0.0)
                hp = float(t.get('highest_price', bp) or bp)
                newly_activated = (hp >= bp * (1 + float(TRAILING_ACTIVATION_PCT)))
                if newly_activated and not t.get('trailing_activated'):
                    t['trailing_activated'] = True
                    t['activation_price'] = bp
                    t['highest_since_activation'] = hp
                    log(f"[TRAIL_ACT] {m}: Trailing activated at buy={bp:.8f}, hp={hp:.8f}", level='info')
                    save_trades()  # CRITICAL FIX #5: Persist activation immediately
                    activation_ok = True
                else:
                    if t.get('trailing_activated'):
                        activation_ok = True
                        try:
                            old_hw = t.get('highest_since_activation')
                            new_hw = max(float(old_hw or hp), hp)
                            if old_hw != new_hw:
                                t['highest_since_activation'] = new_hw
                                log(f"[TRAIL_ACT] {m}: highest_since_activation updated {old_hw} -> {new_hw}", level='debug')
                                save_trades()  # CRITICAL FIX #2: Save immediately
                            else:
                                t['highest_since_activation'] = new_hw
                        except Exception as e:
                            log(f"[ERROR] Failed to update highest_since_activation for {m}: {e}", level='error')
                            t['highest_since_activation'] = hp
                            save_trades()
                    else:
                        activation_ok = newly_activated
            except Exception:
                activation_ok = False

            did_exit = False

            # ── OBI Sell-Side: delay trailing sell if orderbook is strongly bullish ──
            _obi_delay_sell = False
            if CONFIG.get('ORDERBOOK_IMBALANCE_ENABLED', True) and activation_ok and cp <= trailing and cp > t.get('buy_price', 0.0):
                try:
                    from core.orderbook_imbalance import get_orderbook_signal as _get_obi_sell
                    _book_sell = bitvavo_client.book(m, {'depth': 25})
                    if _book_sell and 'bids' in _book_sell:
                        _obi_sell = _get_obi_sell(m, _book_sell, cp)
                        if _obi_sell.get('should_delay_sell'):
                            _obi_delay_sell = True
                            _log_throttled(f'obi_delay_sell_{m}', f"[OBI] {m}: Bullish orderbook (OBI={_obi_sell.get('obi', 0):.3f}) – delaying trailing sell", level='info')
                except Exception as _obi_sell_err:
                    log(f"[OBI] {m}: Sell-side check error: {_obi_sell_err}", level='debug')

            if not _obi_delay_sell and (EXIT_MODE in ('trailing_only', 'trailing_and_hard') or not STOP_LOSS_ENABLED) and activation_ok and cp <= trailing and cp > t.get('buy_price', 0.0):
                amt = t.get('amount', 0.0)
                profit = realized_profit(t.get('buy_price', 0.0), cp, amt)
                
                # CRITICAL SAFETY CHECK: Verify against actual invested amount (accounts for DCA)
                # Use get_true_invested_eur() — ALWAYS cross-checks against buy_price * amount
                current_invested = get_true_invested_eur(t, market=m)
                gross_sell = cp * amt
                sell_fee = gross_sell * FEE_TAKER
                net_proceeds = gross_sell - sell_fee
                # Real profit on remaining position = proceeds - current exposure
                real_profit = net_proceeds - current_invested
                # Total trade profit includes partial TP revenue already returned
                partial_tp_revenue = float(t.get('partial_tp_returned_eur', 0))
                _true_total_inv = _get_true_total_invested(t)
                total_trade_profit = (net_proceeds + partial_tp_revenue) - _true_total_inv
                
                # Block sells that would result in actual loss
                # Use real_profit as primary check — it accounts for DCA costs and fees.
                # The old AND condition (requires all three to be negative) was too permissive:
                # price_profit_pct could be positive while real_profit is negative (fees/DCA).
                price_profit_pct = (cp - t.get('buy_price', 0.0)) / t.get('buy_price', 1.0) if t.get('buy_price', 0.0) > 0 else 0
                if real_profit <= 0:
                    log(f"🛑 TRAILING SELL BLOCKED for {m}: Would cause LOSS! Real profit: €{real_profit:.2f} (calculated: €{profit:.2f}), Price vs buy: {price_profit_pct*100:.1f}%, Invested: €{current_invested:.2f}, Sell proceeds: €{net_proceeds:.2f}", level='warning')
                else:
                    log(f"Trailing TP: trade gesloten voor {m}. Winst: {profit:.4f} EUR")
                    
                    # FIX #2: Mark sell in progress
                    t['_sell_in_progress'] = True
                    
                    # FIX #2: Order verification - check if sell succeeds
                    sell_response = place_sell(m, amt)
                    
                    # FIX #3: Verify sell response properly
                    success, order_ids, remaining, actual_sell_price = _verify_sell_response(sell_response, m, amt)
                    
                    # Clear sell in progress flag
                    t.pop('_sell_in_progress', None)
                    
                    if not success:
                        error_msg = sell_response.get('error', 'Sell verification failed') if sell_response else 'No response'
                        log(f"❌ TRAILING TP SELL FAILED for {m}: {error_msg} - Trade NOT closed", level='error')
                        continue  # Skip closing trade if sell failed
                    
                    # FIX #5: Use actual execution price
                    final_sell_price = actual_sell_price if actual_sell_price else cp
                    if actual_sell_price and abs(actual_sell_price - cp) / cp > 0.01:
                        log(f"Price slippage for {m}: expected {cp:.8f}, executed {actual_sell_price:.8f} ({(actual_sell_price-cp)/cp*100:+.2f}%)", level='warning')
                        # Recalculate profits with actual price
                        gross_sell = actual_sell_price * amt
                        sell_fee = gross_sell * FEE_TAKER
                        net_proceeds = gross_sell - sell_fee
                        real_profit = net_proceeds - current_invested
                        total_trade_profit = (net_proceeds + partial_tp_revenue) - _true_total_inv
                    
                    # Extract primary order ID
                    sell_order_id = order_ids[0] if order_ids else None
                    
                    # FIX #3: Add order ID tracking + REAL profit tracking
                    closed_entry = {
                        'market': m,
                        'buy_price': t.get('buy_price', 0.0),
                        'buy_order_id': t.get('buy_order_id'),
                        'sell_price': final_sell_price,
                        'sell_order_id': sell_order_id,
                        'sell_order_ids': order_ids,
                        'amount': amt,
                        'profit': round(total_trade_profit, 4),  # Total P&L including partial TPs
                        'profit_remaining': round(real_profit, 4),  # P&L on remaining position only
                        'profit_calculated': round(profit, 4),  # Old formula for reference
                        'total_invested_eur': round(_true_total_inv, 4),
                        'invested_eur': round(current_invested, 4),
                        'initial_invested_eur': round(float(t.get('initial_invested_eur', 0) or 0), 4),
                        'partial_tp_returned_eur': round(partial_tp_revenue, 4),
                        'timestamp': time.time(),
                        'reason': 'trailing_tp',
                        'dca_buys': int(t.get('dca_buys', 0) or 0),  # Preserve DCA count in history
                    }
                    _finalize_close_trade(m, t, closed_entry, update_market_profits=True, profit_for_market=total_trade_profit)
                    log(f"✅ Trailing TP closed successfully: {m} - Real Profit: €{real_profit:.2f} @ €{final_sell_price:.8f} (Order ID: {sell_order_id})", level='info')
                    did_exit = True

            # Hard/stop-loss exit (only if enabled and not already exited by trailing)
            risk_stop_hit = risk_stop_price is not None and cp <= risk_stop_price
            if not did_exit and STOP_LOSS_ENABLED and EXIT_MODE in ('hard_only', 'trailing_and_hard') and cp <= final_stop:
                # STALE BUY_PRICE GUARD: If buy_price implies >40% loss but ticker is close to buy_price,
                # the buy_price is probably stale. Skip this SL trigger and log a warning.
                _sl_bp = float(t.get('buy_price', 0) or 0)
                if _sl_bp > 0 and cp > 0:
                    _sl_loss_pct = (_sl_bp - cp) / _sl_bp
                    if _sl_loss_pct > 0.40:
                        log(f"⚠️ STALE GUARD: {m} SL would trigger with {_sl_loss_pct*100:.1f}% loss (bp={_sl_bp:.6f}, cp={cp:.6f}). Skipping SL — buy_price may be stale. Will re-derive on next sync.", level='error')
                        # Force the stale flag so next sync will fix it
                        t['_stale_bp_flagged'] = True
                        continue
                
                amt = t.get('amount', 0.0)
                profit = realized_profit(t.get('buy_price', 0.0), cp, amt)
                
                # CRITICAL SAFETY CHECK: Verify against actual invested amount (accounts for DCA)
                # Use get_true_invested_eur() — ALWAYS cross-checks against buy_price * amount
                current_invested = get_true_invested_eur(t, market=m)
                gross_sell = cp * amt
                sell_fee = gross_sell * FEE_TAKER
                net_proceeds = gross_sell - sell_fee
                real_profit = net_proceeds - current_invested
                # Total trade profit includes partial TP revenue already returned
                partial_tp_revenue = float(t.get('partial_tp_returned_eur', 0))
                _true_total_inv = _get_true_total_invested(t)
                total_trade_profit = (net_proceeds + partial_tp_revenue) - _true_total_inv
                
                reason = 'risk_stop' if risk_stop_hit and final_stop == risk_stop_price else 'stop'
                log(f"⚠️ STOP LOSS TRIGGERED for {m}. Total P&L: €{total_trade_profit:.2f} (remaining: €{real_profit:.2f}), Invested: €{current_invested:.2f}, Sell proceeds: €{net_proceeds:.2f} (reden: {reason})", level='warning')

                # FIX #2: Order verification - check if sell succeeds
                sell_response = place_sell(m, amt)
                
                # FIX: Use _verify_sell_response for actual execution price
                success, order_ids, remaining, actual_sell_price = _verify_sell_response(sell_response, m, amt)
                
                if not success:
                    error_msg = sell_response.get('error', 'Sell verification failed') if sell_response else 'No response'
                    log(f"❌ STOP LOSS SELL FAILED for {m}: {error_msg} - Trade NOT closed", level='error')
                    continue  # Skip closing trade if sell failed
                
                # Use actual execution price if available
                final_sell_price = actual_sell_price if actual_sell_price else cp
                if actual_sell_price and abs(actual_sell_price - cp) / max(cp, 1e-12) > 0.001:
                    log(f"SL price correction for {m}: ticker {cp:.8f} → actual {actual_sell_price:.8f} ({(actual_sell_price-cp)/cp*100:+.2f}%)", level='info')
                    # Recalculate profits with actual price
                    gross_sell = actual_sell_price * amt
                    sell_fee = gross_sell * FEE_TAKER
                    net_proceeds = gross_sell - sell_fee
                    real_profit = net_proceeds - current_invested
                    total_trade_profit = (net_proceeds + partial_tp_revenue) - _true_total_inv
                
                # Extract primary order ID
                sell_order_id = order_ids[0] if order_ids else None

                # FIX #3: Add order ID tracking
                closed_entry = {
                    'market': m,
                    'buy_price': t.get('buy_price', 0.0),
                    'buy_order_id': t.get('buy_order_id'),
                    'sell_price': final_sell_price,
                    'sell_order_id': sell_order_id,
                    'sell_order_ids': order_ids,
                    'amount': amt,
                    'profit': round(total_trade_profit, 4),  # Total P&L including partial TPs
                    'profit_remaining': round(real_profit, 4),  # P&L on remaining position only
                    'profit_calculated': round(profit, 4),  # Old formula for reference
                    'total_invested_eur': round(float(t.get('total_invested_eur', current_invested) or current_invested), 4),
                    'invested_eur': round(current_invested, 4),
                    'initial_invested_eur': round(float(t.get('initial_invested_eur', 0) or 0), 4),
                    'partial_tp_returned_eur': round(partial_tp_revenue, 4),
                    'timestamp': time.time(),
                    'reason': reason,
                }
                _finalize_close_trade(m, t, closed_entry, update_market_profits=True, profit_for_market=total_trade_profit)
                log(f"✅ Stop loss closed: {m} - Total P&L: €{total_trade_profit:.2f} (remaining: €{real_profit:.2f}) (Order ID: {sell_order_id})", level='info')
                
                # Force EUR balance refresh after sell (Issue #8)
                get_eur_balance(force_refresh=True)

        log(f"[DEBUG-MANAGE] Finished manage loop. Proceeding to new trade scan...", level='debug')

        # === Nieuwe trades ===
        # Use cached EUR balance (Issue #8 fix) - only refresh on balance-changing events
        eur_balance = get_eur_balance(force_refresh=False)
        _log_throttled('eur_balance', f"Huidige EUR balans: {eur_balance:.2f} EUR (cached)")
        try:
            # Fetch full balances for overview (less frequent)
            eur = sanitize_balance_payload(safe_call(bitvavo.balance, {}), source='bot_loop.eur_balance')
            bot_loop.last_balances = eur
            bot_loop.last_eur_balance = eur_balance
            bot_loop.last_account_overview = write_account_overview(
                balances=eur,
                snapshot=getattr(bot_loop, 'last_portfolio_snapshot', None),
                eur_balance=eur_balance,
            )
        except Exception as e:
            log(f"[ERROR] Failed to write account overview: {e}", level='error')
            bot_loop.last_account_overview = None
        
        # Periodic market performance save (Issue #10)
        maybe_save_market_performance()

        scored = []
        markets_evaluated = 0
        markets_skipped = 0
        scan_started_ts = time.time()

        # Always pull the latest threshold from CONFIG so dashboard/hot-reloads take effect
        min_score_threshold = float(CONFIG.get('MIN_SCORE_TO_BUY', MIN_SCORE_TO_BUY))

        # ── BOCPD Regime Engine: detect market regime from BTC multi-timeframe data ──
        _regime_result = None
        _regime_adj = {}
        if CONFIG.get('REGIME_ENGINE_ENABLED', True):
            try:
                from core.regime_engine import detect_regime, get_regime_adjustments
                _btc_1m = get_candles('BTC-EUR', '1m', 200)
                _btc_5m = get_candles('BTC-EUR', '5m', 100)
                _btc_1h = get_candles('BTC-EUR', '1h', 48)
                _regime_result = detect_regime(_btc_1m, _btc_5m, _btc_1h, market='BTC-EUR')
                _regime_adj = get_regime_adjustments(_regime_result)
                _regime_name = _regime_adj.get('regime', 'ranging')
                # Store in CONFIG for access by open_trade_async and other functions
                CONFIG['_REGIME_ADJ'] = _regime_adj
                CONFIG['_REGIME_RESULT'] = {'regime': _regime_name, 'confidence': _regime_adj.get('confidence', 0.5)}
                # Apply regime adjustments to score threshold
                _score_adj = float(_regime_adj.get('min_score_adj', 0.0))
                if _score_adj != 0:
                    min_score_threshold += _score_adj
                    log(f"[REGIME] Score threshold adjusted: {min_score_threshold:.1f} ({_score_adj:+.1f} from {_regime_name})", level='info')
                # Block new buys in bearish regime
                if _regime_adj.get('base_amount_mult', 1.0) <= 0:
                    log(f"[REGIME] 🔴 BEARISH regime – all new entries BLOCKED", level='warning')
            except Exception as _regime_err:
                log(f"[REGIME] Error: {_regime_err}", level='debug')

        # ── Cascade Correlation Shield: check portfolio correlation risk ──
        _corr_block_entries = False
        _corr_tighten_stops = False
        if CONFIG.get('CORRELATION_SHIELD_ENABLED', True) and len(open_trades) >= 2:
            try:
                from core.correlation_shield import check_cascade_risk
                _corr_candles = {}
                _corr_prices = {}
                for _cm in list(open_trades.keys()):
                    try:
                        _corr_candles[_cm] = get_candles(_cm, '1m', 60)
                        _cp = get_current_price(_cm)
                        if _cp and _cp > 0:
                            _corr_prices[_cm] = _cp
                    except Exception:
                        pass
                if _corr_candles:
                    _cascade = check_cascade_risk(_corr_candles, open_trades, _corr_prices)
                    _corr_block_entries = _cascade.get('should_block_new_entries', False)
                    _corr_tighten_stops = _cascade.get('should_tighten_stops', False)
                    if _cascade.get('cascade_alert'):
                        log(f"[CORR_SHIELD] 🔴 CASCADE: avg_corr={_cascade['avg_correlation']:.2%}, PnL={_cascade['portfolio_pnl_pct']:.2%}", level='error')
                    elif _corr_block_entries:
                        log(f"[CORR_SHIELD] ⚠️ High correlation detected – blocking new entries", level='warning')
            except Exception as _corr_err:
                log(f"[CORR_SHIELD] Error: {_corr_err}", level='debug')

        # ── BTC Momentum Cascade: update BTC state once per cycle ──
        _btc_cascade_5m = None
        if CONFIG.get('MOMENTUM_CASCADE_ENABLED', True):
            try:
                from core.momentum_cascade import update_btc_momentum, get_btc_state
                _btc_cascade_5m = get_candles('BTC-EUR', '5m', 30)
                if _btc_cascade_5m:
                    _btc_state = update_btc_momentum(_btc_cascade_5m)
                    if _btc_state.get('burst_active'):
                        _dir = "PUMP" if _btc_state['burst_direction'] > 0 else "DUMP"
                        log(f"[BTC-CASCADE] BTC {_dir}: ROC_5m={_btc_state['roc_5m']:+.3f}%, "
                            f"ROC_15m={_btc_state['roc_15m']:+.3f}%", level='info')
            except Exception as _mc_err:
                log(f"[BTC-CASCADE] Error: {_mc_err}", level='debug')

        log(
            f"[DEBUG-SCAN] Starting market scan loop. MARKETS count: {len(MARKETS)}, "
            f"CONFIG MIN_SCORE_TO_BUY: {min_score_threshold}",
            level='debug'
        )

        for m in MARKETS:
            elapsed = time.time() - scan_started_ts
            if elapsed >= SCAN_WATCHDOG_SECONDS:
                log(
                    f"[SCAN WATCHDOG] Aborting scan after {markets_evaluated} markets / {len(MARKETS)} (elapsed {elapsed:.1f}s)",
                    level='warning'
                )
                break
            try:
                if m in open_trades:
                    markets_skipped += 1
                    continue
                
                # Skip markets claimed by external sources (grid trading, manual, etc.)
                if is_external_trade(m):
                    markets_skipped += 1
                    try:
                        block_context = {
                            'signal_score': 0,
                            'min_score_threshold': float(CONFIG.get('MIN_SCORE_TO_BUY', MIN_SCORE_TO_BUY)),
                            'is_external_trade': True,
                        }
                        collect_block_reasons(m, block_context)
                    except Exception as e:
                        log(f"block_context failed: {e}", level='error')
                    continue
                
                if _event_hooks_paused(m):
                    log(f"[event_hooks] Markt {m} overgeslagen door pauze", level='debug')
                    markets_skipped += 1
                    continue
                markets_evaluated += 1
                
                # ALWAYS log which market we're evaluating to track hangs
                log(f"[SCAN] Evaluating {m} ({markets_evaluated}/{len(MARKETS) - markets_skipped})...", level='info')
                
                # Momentum filter: Skip markets with strong negative momentum
                try:
                    candles_momentum = get_candles(m, '1m', 20)
                    if candles_momentum:
                        momentum = calculate_momentum_score(candles_momentum)
                        if momentum < -2:  # Strong bearish momentum
                            log(f"[MOMENTUM_FILTER] {m}: Negative momentum {momentum}, skipping", level='info')
                            markets_skipped += 1
                            continue
                        elif momentum > 3:  # Strong bullish momentum
                            log(f"[MOMENTUM_FILTER] {m}: Positive momentum {momentum}, proceeding", level='debug')
                except Exception as mom_err:
                    log(f"[MOMENTUM_FILTER] Error for {m}: {mom_err}", level='debug')
                
                # ── Funding Rate Oracle: contrarian signal from Binance futures ──
                _funding_score_mod = 0.0
                try:
                    from core.funding_rate_oracle import get_market_signal as _get_funding_signal
                    _fr = _get_funding_signal(m)
                    if _fr.get('should_skip'):
                        log(f"[FUNDING_ORACLE] {m}: SKIP – {_fr['signal']} (rate={_fr.get('rate_pct', '?')}%)", level='info')
                        markets_skipped += 1
                        continue
                    _funding_score_mod = _fr.get('score_modifier', 0.0)
                    if abs(_funding_score_mod) > 0.5:
                        log(f"[FUNDING_ORACLE] {m}: {_fr['signal']} (rate={_fr.get('rate_pct', '?')}%, mod={_funding_score_mod:+.1f})", level='info')
                except Exception as _fr_err:
                    log(f"[FUNDING_ORACLE] {m}: Error: {_fr_err}", level='debug')
                
                result = signal_strength(m)
                # Safe unpacking: now 4 values (score, price, sma_short, ml_info)
                if not isinstance(result, (list, tuple)):
                    result = (0, None, None, {})
                if len(result) < 4:
                    result = tuple(list(result) + [None] * (4 - len(result)))
                try:
                    score, price_now, s_short, ml_info = result
                    if not isinstance(ml_info, dict):
                        ml_info = {}
                except Exception as e:
                    log(f"[ERROR] Fout bij unpacking signal_strength voor {m}: {e}", level='error')
                    score, price_now, s_short, ml_info = 0, None, None, {}
                
                # ── Binance Lead-Lag: skip buy if Binance trending down ──
                try:
                    from core.binance_lead_lag import detect_lead_signal as _detect_lead
                    if price_now and price_now > 0:
                        _ll = _detect_lead(m, price_now)
                        if _ll.get('should_delay_buy'):
                            log(f"[LEAD_LAG] {m}: Binance trending DOWN "
                                f"(trend={_ll['binance_trend_pct']:.3f}%) – delaying buy", level='info')
                            markets_skipped += 1
                            continue
                        elif _ll.get('direction') == 'up' and score > 0:
                            # Binance trending up → Bitvavo will follow → slight score boost
                            score += 0.5
                            log(f"[LEAD_LAG] {m}: Binance UP (trend={_ll['binance_trend_pct']:.3f}%) +0.5 score", level='debug')
                except Exception as _ll_err:
                    log(f"[LEAD_LAG] {m}: Error: {_ll_err}", level='debug')
                
                # ── Order Book Imbalance: directional signal from Bitvavo book ──
                _obi_score_mod = 0.0
                if CONFIG.get('ORDERBOOK_IMBALANCE_ENABLED', True):
                    try:
                        from core.orderbook_imbalance import get_orderbook_signal as _get_obi
                        _book = safe_call(bitvavo.book, m, {'depth': 25})
                        if _book and price_now and price_now > 0:
                            _obi = _get_obi(m, _book, price_now)
                            if _obi.get('should_delay_buy'):
                                log(f"[OBI] {m}: Bearish orderbook (OBI={_obi.get('obi', 0):.3f}) – delaying buy", level='info')
                                markets_skipped += 1
                                continue
                            _obi_score_mod = _obi.get('score_modifier', 0.0)
                            if abs(_obi_score_mod) > 0.3:
                                score += _obi_score_mod
                                log(f"[OBI] {m}: {_obi['signal']} (OBI={_obi.get('obi', 0):.3f}, mod={_obi_score_mod:+.1f})", level='debug')
                    except Exception as _obi_err:
                        log(f"[OBI] {m}: Error: {_obi_err}", level='debug')
                
                # ── Multi-Timeframe Confluence: score bonus from 15m/1h/4h alignment ──
                if CONFIG.get('MTF_CONFLUENCE_ENABLED', True):
                    try:
                        from core.mtf_confluence import mtf_score_bonus
                        _mtf_bonus, _mtf_details = mtf_score_bonus(m, get_candles)
                        if _mtf_bonus != 0:
                            score += _mtf_bonus
                            log(f"[MTF] {m}: {_mtf_bonus:+.1f} ({_mtf_details.get('reason', '')})", level='debug')
                    except Exception as _mtf_err:
                        log(f"[MTF] {m}: Error: {_mtf_err}", level='debug')

                # ── Volume Profile / VWAP: score modifier from price vs VWAP ──
                if CONFIG.get('VWAP_SCORING_ENABLED', True):
                    try:
                        from core.volume_profile import vwap_score_modifier
                        _vwap_candles = get_candles(m, '1m', 120)
                        if _vwap_candles and len(_vwap_candles) >= 30:
                            from core.indicators import close_prices as _cp, highs as _hi, lows as _lo, volumes as _vo
                            _vc = _cp(_vwap_candles)
                            _vh = _hi(_vwap_candles)
                            _vl = _lo(_vwap_candles)
                            _vv = _vo(_vwap_candles)
                            if _vc and _vh and _vl and _vv:
                                _vwap_mod, _vwap_det = vwap_score_modifier(_vc, _vh, _vl, _vv)
                                if _vwap_mod != 0:
                                    score += _vwap_mod
                                    log(f"[VWAP] {m}: {_vwap_mod:+.1f} ({', '.join(_vwap_det.get('reasons', []))})", level='debug')
                    except Exception as _vwap_err:
                        log(f"[VWAP] {m}: Error: {_vwap_err}", level='debug')

                # ── BTC Momentum Cascade: per-alt bonus from BTC momentum lag ──
                if CONFIG.get('MOMENTUM_CASCADE_ENABLED', True) and _btc_cascade_5m:
                    try:
                        from core.momentum_cascade import cascade_score_bonus
                        _alt_5m = get_candles(m, '5m', 30)
                        if _alt_5m:
                            _casc_bonus, _casc_det = cascade_score_bonus(m, _alt_5m, _btc_cascade_5m)
                            if _casc_bonus != 0:
                                score += _casc_bonus
                                log(f"[BTC-CASCADE] {m}: {_casc_bonus:+.1f} ({', '.join(_casc_det.get('reasons', []))})", level='debug')
                    except Exception as _casc_err:
                        log(f"[BTC-CASCADE] {m}: Error: {_casc_err}", level='debug')

                # ── Regime Engine: block buys in bearish regime ──
                if _regime_adj.get('base_amount_mult', 1.0) <= 0:
                    log(f"[REGIME] {m}: Entry blocked (bearish regime)", level='info')
                    markets_skipped += 1
                    continue
                
                # ── Correlation Shield: block if portfolio is too correlated ──
                if _corr_block_entries:
                    try:
                        from core.correlation_shield import should_allow_new_position
                        _corr_candles_for_m = {**{_cm: get_candles(_cm, '1m', 60) for _cm in list(open_trades.keys())[:4]}, m: get_candles(m, '1m', 60)}
                        _allowed, _reason = should_allow_new_position(m, _corr_candles_for_m, list(open_trades.keys()))
                        if not _allowed:
                            log(f"[CORR_SHIELD] {m}: Blocked – {_reason}", level='info')
                            markets_skipped += 1
                            continue
                    except Exception as _cs_err:
                        log(f"[CORR_SHIELD] {m}: Check error: {_cs_err}", level='debug')
                
                # Collect trade block reasons if score is below threshold
                if score < min_score_threshold:
                    try:
                        # ENHANCED LOGGING: Detail ALL reasons for trade block
                        candles = get_candles(m, '1m', 60)
                        prices = close_prices(candles)
                        rsi_val = rsi(prices, 14) if prices else None
                        rsi_min = float(CONFIG.get('RSI_MIN_BUY', 26))
                        rsi_max = float(CONFIG.get('RSI_MAX_BUY', 74))
                        
                        # Build detailed block reason log
                        reasons = []
                        reasons.append(f"Score {score:.2f} < threshold {min_score_threshold:.2f}")
                        if rsi_val:
                            if rsi_val < rsi_min:
                                reasons.append(f"RSI {rsi_val:.1f} < min {rsi_min}")
                            elif rsi_val > rsi_max:
                                reasons.append(f"RSI {rsi_val:.1f} > max {rsi_max}")
                            else:
                                reasons.append(f"RSI {rsi_val:.1f} OK ({rsi_min}-{rsi_max})")
                        
                        # Detect ML veto: score was good before ML penalty pulled it below threshold
                        ml_veto_detected = False
                        if ml_info:
                            score_before_ml = ml_info.get('score_before_ml', score)
                            ml_signal = ml_info.get('ml_signal', 0)
                            ml_conf = ml_info.get('ml_confidence', 0.0)
                            if score_before_ml >= min_score_threshold and ml_signal == 0:
                                ml_veto_detected = True
                                reasons.append(f"ML VETO: {score_before_ml:.2f}→{score:.2f} (signal={ml_signal}, conf={ml_conf:.2f})")
                            elif ml_info:
                                reasons.append(f"ML: signal={ml_signal}, conf={ml_conf:.2f}")
                        
                        # Log complete reasoning
                        log(f"[ENTRY BLOCKED] {m}: {' | '.join(reasons)}", level='info')
                        
                        block_context = {
                            'signal_score': score,
                            'min_score_threshold': min_score_threshold,
                            'rsi': rsi_val,
                            'rsi_min': rsi_min,
                            'rsi_max': rsi_max,
                            'balance_eur': eur_balance,
                            'order_amount': float(CONFIG.get('BASE_AMOUNT_EUR', 35)),
                            'min_order_size': MIN_ORDER_EUR,
                            'has_operator_id': bool(CONFIG.get('OPERATOR_ID')),
                            'performance_filter_blocked': False,  # Updated later if filtered
                            'test_mode': TEST_MODE,
                            # ML veto tracking
                            'ml_veto': ml_veto_detected,
                            'ml_signal': ml_info.get('ml_signal', 0) if ml_info else 0,
                            'ml_confidence': ml_info.get('ml_confidence', 0.0) if ml_info else 0.0,
                            'score_before_ml': ml_info.get('score_before_ml', score) if ml_info else score,
                        }
                        collect_block_reasons(m, block_context)
                    except Exception as block_err:
                        log(f"[DEBUG] Failed to collect block reasons for {m}: {block_err}", level='debug')
                
                # Apply funding rate modifier to final score
                score += _funding_score_mod
                if score >= min_score_threshold:
                    scored.append((score, m, price_now, s_short, ml_info))
            except Exception as scan_err:
                log(f"[SCAN ERROR] {m}: {scan_err}", level='error')
                continue
        scored.sort(reverse=True)
        
        # Store scan statistics for heartbeat/dashboard
        CONFIG['LAST_SCAN_STATS'] = {
            'total_markets': len(MARKETS),
            'evaluated': markets_evaluated,
            'skipped': markets_skipped,
            'passed_min_score': len(scored),
            'min_score_threshold': min_score_threshold,
            'timestamp': time.time(),
        }
        
        # ALWAYS log scan summary for debugging (not just when SIGNALS_DEBUG_LOGGING)
        scan_elapsed = time.time() - scan_started_ts
        markets_per_second = markets_evaluated / scan_elapsed if scan_elapsed > 0 else 0
        log(
            f"[SCAN SUMMARY] {len(MARKETS)} markets, {markets_evaluated} evaluated, "
            f"{markets_skipped} skipped, {len(scored)} passed MIN_SCORE {min_score_threshold}, "
            f"elapsed {scan_elapsed:.1f}s ({markets_per_second:.2f} markets/s)",
            level='info'
        )


        # Trades openen via async
        await open_trades_async(scored, eur_balance)
        
        # CRITICAL: Sleep tussen scans om rate limits te voorkomen
        await asyncio.sleep(SLEEP_SECONDS)


async def open_trades_async(scored, eur_balance):
    # HARD STOP: Immediately bail if already at max open trades
    try:
        _hard_max = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
        _hard_current = count_active_open_trades(threshold=DUST_TRADE_THRESHOLD_EUR)
        _hard_reserved = _get_pending_count()
        try:
            _hard_pending = len(get_pending_bitvavo_orders())
        except Exception:
            _hard_pending = 0
        _hard_total = _hard_current + _hard_reserved + _hard_pending
        if _hard_total >= _hard_max:
            log(f"[TRADE EXEC] HARD STOP: already at max trades ({_hard_current}+{_hard_reserved}+{_hard_pending}/{_hard_max}), skipping ALL {len(scored)} scored markets", level='info')
            return
    except Exception as _hard_err:
        log(f"[ERROR] Hard stop check failed: {_hard_err} — blocking all new trades (fail-closed)", level='error')
        return

    # Saldo reserveren en updaten na elke koop
    saldo = eur_balance
    # Diversificatie parameters
    MAX_TRADES_PER_COIN = CONFIG.get('MAX_TRADES_PER_COIN', 1)
    MAX_EXPOSURE_PER_COIN = CONFIG.get('MAX_EXPOSURE_PER_COIN', 0.3)  # 30% van totale exposure
    global LAST_OPEN_TRADE_TS
    if 'LAST_OPEN_TRADE_TS' not in globals():
        LAST_OPEN_TRADE_TS = 0
    dust_threshold = _resolve_dust_threshold()
    
    # Track processing for debugging
    total_scored = len(scored)
    processed_count = 0
    trades_opened_this_cycle = 0
    max_per_cycle = int(CONFIG.get('MAX_TRADES_PER_SCAN_CYCLE', 1))
    
    for _scored_item in scored:
        # Support both old 4-tuple and new 5-tuple format
        if len(_scored_item) >= 5:
            score, m, price_now, s_short, _scored_ml_info = _scored_item
        else:
            score, m, price_now, s_short = _scored_item[:4]
            _scored_ml_info = {}
        processed_count += 1
        log(f"[TRADE EXEC] Processing scored market {processed_count}/{total_scored}: {m} score {score:.2f}", level='debug')
        price_cache: Dict[str, Optional[float]] = {}
        # Global cap: block new markets when cap reached
        # Also count pending limit orders on exchange as they WILL become trades
        try:
            max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
            current = count_active_open_trades(dust_threshold, price_cache=price_cache)
            reserved = _get_pending_count()
            # Count pending buy orders on exchange that aren't yet in open_trades
            try:
                _pending_exchange = len(get_pending_bitvavo_orders())
            except Exception:
                _pending_exchange = 0
            total_slots_used = current + reserved + _pending_exchange
            if total_slots_used >= max_trades and m not in open_trades:
                log(f"[SKIP] {m}: Max trades reached ({current}+{reserved}+{_pending_exchange}/{max_trades})", level='info')
                # Collect block reason
                try:
                    block_context = {
                        'signal_score': score,
                        'min_score_threshold': float(CONFIG.get('MIN_SCORE_TO_BUY', MIN_SCORE_TO_BUY)),
                        'max_trades_reached': True,
                        'balance_eur': saldo,
                    }
                    collect_block_reasons(m, block_context)
                except Exception as e:
                    log(f"[ERROR] collect_block_reasons failed for {m}: {e}", level='error')
                continue
        except Exception as e:
            log(f"[ERROR] Max trades check failed for {m}: {e} — SKIPPING trade (fail-closed)", level='error')
            continue  # CRITICAL FIX: fail-closed — never allow trade on check failure
        if _event_hooks_paused(m):
            log(f"[event_hooks] Entry voor {m} geblokkeerd tijdens pauze", level='info')
            continue
        # Cooldown between new trades
        if OPEN_TRADE_COOLDOWN_SECONDS > 0 and time.time() - LAST_OPEN_TRADE_TS < OPEN_TRADE_COOLDOWN_SECONDS:
            remaining = OPEN_TRADE_COOLDOWN_SECONDS - (time.time() - LAST_OPEN_TRADE_TS)
            log(f"[SKIP] {m}: Cooldown active ({remaining:.0f}s remaining) - stopping scan cycle", level='info')
            break  # No more trades possible until cooldown expires
        # Price range filters
        if MIN_PRICE_EUR and price_now and price_now < MIN_PRICE_EUR:
            log(f"[SKIP] {m}: Price {price_now:.4f} < MIN_PRICE_EUR {MIN_PRICE_EUR:.2f}", level='info')
            continue
        if MAX_PRICE_EUR and price_now and price_now > MAX_PRICE_EUR:
            log(f"[SKIP] {m}: Price {price_now:.4f} > MAX_PRICE_EUR {MAX_PRICE_EUR:.2f}", level='info')
            continue
        # 24h volume filter in EUR
        try:
            vol_eur = get_24h_volume_eur(m)
            if vol_eur is not None and MIN_DAILY_VOLUME_EUR and vol_eur < MIN_DAILY_VOLUME_EUR:
                log(f"[SKIP] {m}: 24h volume {vol_eur:.0f} EUR < minimum {MIN_DAILY_VOLUME_EUR:.0f}", level='info')
                continue
        except Exception as e:
            log(f"[ERROR] Volume filter check failed for {m}: {e}", level='error')
        # Diversificatie: check aantal trades per coin
        coin = m.split('-')[0]
        total_exposure = 0.0
        coin_exposure = 0.0
        coin_trade_count = 0
        for key, trade in (open_trades or {}).items():
            exposure, _ = _compute_trade_value_eur(key, trade, price_cache=price_cache)
            if exposure is None:
                continue
            if dust_threshold is not None and exposure < dust_threshold:
                continue
            total_exposure += exposure
            if key.startswith(coin):
                coin_exposure += exposure
                coin_trade_count += 1
        if coin_trade_count >= MAX_TRADES_PER_COIN:
            log(f"[SKIP] {m}: Max trades per coin reached for {coin} ({coin_trade_count}/{MAX_TRADES_PER_COIN})", level='info')
            continue
        if total_exposure > 0 and (coin_exposure / total_exposure) > MAX_EXPOSURE_PER_COIN:
            exposure_pct = (coin_exposure / total_exposure) * 100
            log(f"[SKIP] {m}: Max exposure for {coin} reached ({exposure_pct:.1f}% > {MAX_EXPOSURE_PER_COIN*100}%)", level='info')
            continue
        if saldo < MIN_ORDER_EUR:
            log(f"[SKIP] {m}: EUR balance {saldo:.2f} < minimum {MIN_ORDER_EUR:.2f}", level='info')
            continue
        result = await open_trade_async(score, m, price_now, s_short, saldo, ml_info=_scored_ml_info)
        if result and isinstance(result, dict) and (result.get('buy_executed') or result.get('order_pending')):
            # Count BOTH filled buys AND pending limit orders against cycle limit
            # This prevents burst-buying when limit orders aren't immediately filled
            if result.get('buy_executed'):
                saldo -= result.get('eur_used', 0)
            else:
                # Pending order: reserve estimated EUR from available saldo
                saldo -= result.get('eur_reserved', float(CONFIG.get('BASE_AMOUNT_EUR', 25)))
                log(f"[TRADE EXEC] Pending limit order for {m} counts against cycle limit", level='info')
            LAST_OPEN_TRADE_TS = time.time()
            trades_opened_this_cycle += 1
            if trades_opened_this_cycle >= max_per_cycle:
                log(f"[TRADE EXEC] Max {max_per_cycle} trade(s) per cycle reached - stopping", level='info')
                break  # Enforce max 1 trade per scan cycle

async def open_trade_async(score, m, price_now, s_short, eur_balance, ml_info=None):
    if ml_info is None:
        ml_info = {}
    # Circuit breaker: pause new entries on poor recent performance
    # Grace period prevents deadlock: after cooldown expires, allow GRACE trades
    # before re-evaluating (otherwise same bad stats re-trigger immediately).
    def _circuit_breaker_active() -> tuple[bool, str]:
        cfg = CONFIG
        min_wr = float(cfg.get('CIRCUIT_BREAKER_MIN_WIN_RATE', 0) or 0)
        min_pf = float(cfg.get('CIRCUIT_BREAKER_MIN_PROFIT_FACTOR', 0) or 0)
        cooldown_min = int(cfg.get('CIRCUIT_BREAKER_COOLDOWN_MINUTES', 0) or 0)
        grace_trades = int(cfg.get('CIRCUIT_BREAKER_GRACE_TRADES', 5) or 5)
        if min_wr <= 0 and min_pf <= 0:
            return False, ''
        now = time.time()
        until = cfg.get('_circuit_breaker_until_ts', 0)
        if until and now < until:
            return True, f"cooldown_until={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until))}"
        # Cooldown just expired — enter grace period
        if until and now >= until:
            trades_since = cfg.get('_cb_trades_since_reset', 0)
            if trades_since < grace_trades:
                # Grace period: allow trading, don't re-check yet
                if trades_since == 0:
                    log(f"[CIRCUIT BREAKER] Cooldown expired, grace period: {grace_trades} trades allowed before re-check", level='info')
                return False, ''
            # Grace period over — clear state and re-evaluate below
            cfg.pop('_circuit_breaker_until_ts', None)
            cfg.pop('_cb_trades_since_reset', None)
        trade_log_path = TRADE_LOG
        try:
            with open(trade_log_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            closed = data.get('closed', []) if isinstance(data, dict) else []
            recent = closed[-20:] if len(closed) > 20 else closed
            if not recent:
                return False, ''
            # CRITICAL FIX: Don't activate circuit breaker with too few trades
            # With only 1-4 trades, win_rate is too noisy to be meaningful
            min_trades_for_cb = max(5, grace_trades)
            if len(recent) < min_trades_for_cb:
                return False, ''
            wins = [t for t in recent if t.get('profit', 0) > 0]
            losses = [t for t in recent if t.get('profit', 0) < 0]
            win_rate = len(wins) / len(recent)
            total_win = sum(t.get('profit', 0) for t in wins)
            total_loss = abs(sum(t.get('profit', 0) for t in losses))
            profit_factor = (total_win / total_loss) if total_loss > 0 else float('inf') if total_win > 0 else 0.0
            if (min_wr > 0 and win_rate < min_wr) or (min_pf > 0 and profit_factor < min_pf):
                if cooldown_min > 0:
                    cfg['_circuit_breaker_until_ts'] = now + cooldown_min * 60
                    cfg['_cb_trades_since_reset'] = 0
                log(f"[CIRCUIT BREAKER] Active: win_rate={win_rate:.2%} (min {min_wr:.2%}), pf={profit_factor:.2f} (min {min_pf:.2f})", level='warning')
                return True, f"win_rate={win_rate:.2f}, pf={profit_factor:.2f}"
        except Exception:
            return False, ''
        return False, ''

    if m in open_trades:
        # Allow overwrite if existing position is dust (stale entry with near-zero value)
        _existing_amt = float(open_trades[m].get('amount', 0) or 0)
        _existing_bp = float(open_trades[m].get('buy_price', 0) or 0)
        _existing_val_eur = _existing_amt * _existing_bp if _existing_bp > 0 else _existing_amt
        # Only treat as dust when amount is explicitly present and very small
        if _existing_amt > 0 and _existing_val_eur < DUST_TRADE_THRESHOLD_EUR:
            log(f"⚠️ {m}: Stale dust entry (€{_existing_val_eur:.2f} < dust threshold), allowing overwrite", level='warning')
            with trades_lock:
                del open_trades[m]
        else:
            log(f"[SKIP] {m}: Trade already open", level='debug')
            return {'buy_executed': False}
    
    # Circuit breaker check
    cb_active, cb_reason = _circuit_breaker_active()
    if cb_active:
        log(f"[SKIP] {m}: Circuit breaker active ({cb_reason})", level='info')
        return {'buy_executed': False, 'reason': 'circuit_breaker'}
    
    # Block HODL markets from being traded by trailing bot
    try:
        hodl_cfg = CONFIG.get('HODL_SCHEDULER') or {}
        hodl_markets = set()
        for sched in (hodl_cfg.get('schedules') or []):
            market = sched.get('market', '')
            if market:
                hodl_markets.add(market.upper())
        if m.upper() in hodl_markets:
            log(f"[SKIP] {m}: HODL asset - not traded by trailing bot", level='info')
            return {'buy_executed': False, 'reason': 'hodl_asset'}
    except Exception as e:
        log(f"[ERROR] HODL check failed for {m}: {e}", level='error')
    
    if _event_hooks_paused(m):
        log(f"[event_hooks] Trade voor {m} geblokkeerd (pauze actief)", level='warning')
        return {'buy_executed': False, 'reason': 'event_pause'}

    # Guard cap before attempting to buy (includes pending exchange orders)
    try:
        max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
        current = count_active_open_trades(threshold=DUST_TRADE_THRESHOLD_EUR)
        reserved = _get_pending_count()
        try:
            _pending_exch = len(get_pending_bitvavo_orders())
        except Exception:
            _pending_exch = 0
        if (current + reserved + _pending_exch) >= max_trades:
            log(f"Max open trades limiet bereikt ({current}+{reserved}+{_pending_exch}/{max_trades}), sla {m} over.")
            return {'buy_executed': False}
    except Exception as e:
        log(f"[ERROR] Max trades guard failed for {m}: {e} — BLOCKING trade (fail-closed)", level='error')
        _release_market(m)
        return {'buy_executed': False}  # CRITICAL FIX: fail-closed on exception
    
    # Check if there's already an open limit order for this market on the exchange
    # This prevents duplicate orders when AUTO order type places limit orders
    try:
        existing_orders = safe_call(bitvavo.ordersOpen, {'market': m}) or []
        buy_orders = [o for o in existing_orders if o.get('side') == 'buy']
        if buy_orders:
            log(f"Sla {m} over: er is al een openstaande BUY order ({len(buy_orders)} order(s))", level='info')
            return {'buy_executed': False, 'reason': 'pending_order_exists'}
    except Exception as e:
        log(f"Kon openstaande orders niet checken voor {m}: {e}", level='warning')
    
    # Reserve a slot for this market before placing orders to avoid races (thread-safe)
    if m not in open_trades and not _is_market_reserved(m):
        if not _reserve_market(m):
            log(f"Kon {m} niet reserveren (al gereserveerd door andere thread)", level='debug')
            return {'buy_executed': False, 'reason': 'reservation_failed'}
    # === Dynamic Position Sizing (OPTIMIZED) ===
    # Gebruik BASE_AMOUNT_EUR uit config (geoptimaliseerd door AI)
    base_amt_eur = float(CONFIG.get('BASE_AMOUNT_EUR', 15))
    perf_stats = _perf.get_snapshot(m)
    market_size_mult = _perf.get_position_size_multiplier(m, perf_stats)
    regime, regime_mult = get_ai_regime_bias()
    
    # ── Kelly + Volatility Parity: advanced per-coin position sizing ──
    if CONFIG.get('KELLY_VOLPARITY_ENABLED', True):
        try:
            from core.kelly_sizing import calculate_position_size as _kelly_vp_size
            _kvp = _kelly_vp_size(
                market=m,
                base_amount_eur=base_amt_eur,
                candles=get_candles(m, '1m', 60),
                trade_log_path=str(TRADE_LOG),
                kelly_fraction_mult=float(CONFIG.get('POSITION_KELLY_FACTOR', 0.3)),
                budget_eur=float(CONFIG.get('BUDGET_RESERVATION', {}).get('trailing_bot_max_eur', 300.0)),
            )
            _kvp_amt = _kvp.get('amount_eur', base_amt_eur)
            _kelly_f = _kvp.get('kelly_fraction', 0.0)
            if _kelly_f > 0 and abs(_kvp_amt - base_amt_eur) > 1.0:
                log(f"[KELLY+VP] {m}: €{base_amt_eur:.0f} → €{_kvp_amt:.0f} (kelly_f={_kelly_f:.3f})", level='debug')
                base_amt_eur = _kvp_amt
        except Exception as _kvp_err:
            log(f"[KELLY+VP] {m}: Fallback to base sizing: {_kvp_err}", level='debug')
    
    # ── Regime Engine: apply base_amount multiplier ──
    try:
        _regime_adj = CONFIG.get('_REGIME_ADJ', {})
        if _regime_adj and _regime_adj.get('base_amount_mult', 1.0) != 1.0:
            _r_mult = _regime_adj['base_amount_mult']
            _old_base = base_amt_eur
            base_amt_eur = base_amt_eur * _r_mult
            log(f"[REGIME] {m}: Base €{_old_base:.0f} × {_r_mult:.2f} = €{base_amt_eur:.0f} ({_regime_adj.get('regime', '')})", level='debug')
    except Exception:
        pass
    
    # Enhanced volatility calculation using ATR for better risk adjustment
    c1 = get_candles(m, '1m', 60)
    p1 = close_prices(c1)
    h1 = highs(c1)
    l1 = lows(c1)
    
    # Calculate ATR for volatility measurement
    vol = 0.0
    try:
        if p1 and h1 and l1 and len(p1) >= 20:
            tr_list = []
            for i in range(1, min(20, len(p1))):
                tr = max(
                    h1[i] - l1[i],
                    abs(h1[i] - p1[i-1]),
                    abs(l1[i] - p1[i-1])
                )
                tr_list.append(tr)
            if tr_list:
                atr = np.mean(tr_list)
                avg_price = np.mean(p1[-20:])
                vol = float(atr / avg_price) if avg_price > 0 else 0.0
    except Exception:
        # Fallback to simple std dev
        vol = float(np.std(p1[-10:]) / np.mean(p1[-10:])) if p1 and len(p1) >= 10 and np.mean(p1[-10:]) > 0 else 0.0
    
    # Score-based sizing: reward high-conviction setups
    score_boost = 1.0 + max(0.0, min((score - 4.5) * 0.2, 0.6))  # Up to 60% boost for high scores
    
    # Volatility adjustment: reduce size in high volatility to control risk
    vol_penalty = 1.0 / (1.0 + vol * 3.0)  # Higher vol = smaller size
    
    # Combined sizing multiplier
    size_mult = score_boost * vol_penalty * market_size_mult * regime_mult

    # Kelly-lite: gebruik expectancy als edge, geschaald door configurabele factor en capped
    edge = 0.0
    win_rate = 0.0
    try:
        if perf_stats:
            avg_profit = float(perf_stats.get('avg_profit', 0.0) or 0.0)
            avg_loss = abs(float(perf_stats.get('avg_loss', 0.0) or 0.0))
            win_rate = float(perf_stats.get('win_rate', 0.0) or 0.0)
            if avg_loss > 0 and win_rate > 0:
                # Kelly formula: (win_rate * avg_profit - (1-win_rate) * avg_loss) / avg_loss
                edge = max(0.0, (win_rate * avg_profit - (1-win_rate) * avg_loss) / avg_loss)
    except Exception:
        edge = 0.0
    
    total_exposure = current_open_exposure_eur(include_dust=False)
    equity = eur_balance + total_exposure
    kelly_factor = float(CONFIG.get('POSITION_KELLY_FACTOR', 0.25) or 0.25)
    risk_frac = _clamp(kelly_factor * edge, 0.005, 0.03)  # 0.5% - 3% of equity
    kelly_size = equity * risk_frac if equity > 0 and edge > 0 else base_amt_eur

    # Final position size: min of multiplier-adjusted base and Kelly size
    amt_eur = min(base_amt_eur * size_mult, kelly_size)
    # Profit Recycling: voeg 20% van gerealiseerde winst toe
    total_profit = 0.0
    try:
        data = load_trade_snapshot(TRADE_LOG)
        closed = data.get('closed', []) if isinstance(data, dict) else []
        total_profit = sum(t.get('profit', 0) for t in closed)
    except Exception as e:
        log(f"load_trade_snapshot failed: {e}", level='error')
    # Profit recycling DISABLED — was causing oversized entries
    # Previously added 20% of total profit to every trade, ballooning far above BASE_AMOUNT_EUR
    recycle_amt = 0.0
    if perf_stats and market_size_mult != 1.0:
        _log_throttled(f'size_bias_{m}',
            f"Size bias voor {m}: multiplier {market_size_mult:.2f} (avg_profit={float(perf_stats.get('avg_profit', 0.0) or 0.0):.2f} EUR, trades={perf_stats.get('trades', 0)})",
            level='debug',
        )
    # NOTE: regime_mult is already included in size_mult above — do NOT apply again!
    if regime_mult != 1.0:
        _log_throttled('regime_mult', f"AI-regime {regime} past globale multiplier {regime_mult:.2f} toe (already in size_mult)", level='debug')
    watch_cfg = _get_watchlist_runtime_settings()
    if watch_cfg['enabled'] and is_watchlist_market(m):
        if watch_cfg['paper_only']:
            log(f"Watchlist mode=paper, skip live entry for {m}", level='info')
            _release_market(m)
            return {'buy_executed': False, 'reason': 'watchlist-paper'}
        micro_cap = max(0.0, watch_cfg['micro_trade_amount_eur'])
        if micro_cap > 0:
            scaled_amt = min(amt_eur, micro_cap)
            if scaled_amt < amt_eur:
                log(f"Watchlist micro sizing {m}: {amt_eur:.2f} -> {scaled_amt:.2f} EUR", level='info')
            amt_eur = scaled_amt

    # HARDCODED: Clamp final entry size — NEVER exceed 2x BASE_AMOUNT_EUR
    hard_max_entry_eur = base_amt_eur * 2.0  # HARDCODED CAP — ignore config MAX_ENTRY_EUR
    min_entry_eur = float(CONFIG.get('MIN_ENTRY_EUR', MIN_ORDER_EUR) or MIN_ORDER_EUR)
    unclamped_amt = amt_eur
    amt_eur = max(min_entry_eur, min(amt_eur, hard_max_entry_eur))
    if not math.isclose(unclamped_amt, amt_eur, rel_tol=1e-6):
        log(f"Sizing clamp voor {m}: {unclamped_amt:.2f} -> {amt_eur:.2f} EUR (min={min_entry_eur:.2f}, HARD max={hard_max_entry_eur:.2f})", level='info')

    if regime_mult <= 0:
        log(f"AI-regime '{regime}' blokkeert nieuwe trades; {m} wordt overgeslagen.", level='warning')
        _release_market(m)
        return {'buy_executed': False}
    amt_eur = min(amt_eur, eur_balance)
    if amt_eur < MIN_ORDER_EUR:
        log(
            f"Positiegrootte {amt_eur:.2f} EUR < minimum {MIN_ORDER_EUR:.2f}; {m} wordt niet geopend.",
            level='info',
        )
        _release_market(m)
        return {'buy_executed': False, 'reason': 'below_min_order'}
    if amt_eur <= 0:
        log(f"Positiegrootte voor {m} viel naar 0 EUR (regime={regime}, perf_mult={market_size_mult:.2f}); overslaan.", level='warning')
        _release_market(m)
        return {'buy_executed': False}
    if eur_balance < amt_eur:
        _release_market(m)
        return {'buy_executed': False}
    entry_price = _coerce_positive_float(price_now)
    if entry_price is None:
        fallback_price = _coerce_positive_float(get_current_price(m))
        if fallback_price is not None:
            entry_price = fallback_price
            log(f"Fallback prijs gebruikt voor {m}: {entry_price:.6f}", level='warning')
    if entry_price is None:
        log(f"[ERROR] Geen geldige prijs voor {m}; trade wordt overgeslagen.", level='error')
        _release_market(m)
        return {'buy_executed': False}

    if risk_manager:
        # Risk-based sizing: scale down entries during drawdowns to protect capital
        try:
            metrics = risk_manager.metrics
            dd = float(metrics.global_current_drawdown or 0.0)
            dd_limit = float(CONFIG.get('RISK_DRAWDOWN_SIZE_LIMIT_EUR', 0) or 0)
            if dd_limit <= 0:
                dd_limit = float(CONFIG.get('RISK_BLOCK_DRAWNDOWN_EUR', 0) or 0)
            if dd_limit <= 0:
                dd_limit = float(CONFIG.get('RISK_MAX_GLOBAL_DRAWDOWN_EUR', 0) or 0)
            if dd_limit > 0 and dd > 0:
                max_reduction = float(CONFIG.get('RISK_DRAWDOWN_MAX_REDUCTION', 0.6) or 0.6)
                min_mult = float(CONFIG.get('RISK_DRAWDOWN_MIN_SIZE_MULT', 0.4) or 0.4)
                ratio = min(1.0, dd / dd_limit)
                scale = max(min_mult, 1.0 - (ratio * max_reduction))
                if scale < 0.999:
                    scaled_amt = amt_eur * scale
                    log(f"Risk sizing: drawdown {dd:.2f}/{dd_limit:.2f} EUR -> {amt_eur:.2f} => {scaled_amt:.2f} EUR", level='info')
                    amt_eur = scaled_amt
        except Exception as exc:
            log(f"Risk sizing faalde voor {m}: {exc}", level='warning')

    if risk_manager:
        try:
            decision = risk_manager.assess_new_trade(
                m,
                float(amt_eur),
                entry_price=float(entry_price),
                score=float(score) if score is not None else None,
            )
        except Exception as exc:
            log(f"Risk guard kon {m} niet beoordelen: {exc}", level='warning')
            decision = None
        if decision and not decision.allowed:
            log(f"Risk guard blokkeert trade {m}: {decision.reason}", level='warning')
            _release_market(m)
            return {'buy_executed': False}

    # Trailing Entry: wacht op pullback, schaalbaar met volatiliteit
    pullback_pct = _clamp(0.01 + vol * 1.5, 0.01, 0.03)
    orig_price = entry_price
    for _ in range(10):
        await asyncio.sleep(2)
        new_price = _coerce_positive_float(get_current_price(m))
        if new_price is not None and new_price <= orig_price * (1 - pullback_pct):
            entry_price = new_price
            log(f"Trailing entry voor {m}: instap op pullback {entry_price:.6f}")
            break
    # Minimum ordergrootte check
    min_size = get_min_order_size(m)
    amount_base = amt_eur / entry_price
    if amount_base < min_size:
        log(f"⏭️ Ordergrootte te klein voor {m}: {amount_base:.8f} < min {min_size}")
        _release_market(m)
        return {'buy_executed': False}

    # Spread + slippage + fee-informed activation/trailing
    book = get_ticker_best_bid_ask(m)
    spread_pct = None
    if book and book.get('ask') and book.get('bid'):
        try:
            spread_pct = (book['ask'] - book['bid']) / ((book['ask'] + book['bid']) / 2)
        except Exception:
            spread_pct = None
    slippage = get_expected_slippage(m, amt_eur, entry_price)
    est_slippage = slippage if slippage is not None else SLIPPAGE_PCT
    max_slippage = float(CONFIG.get('MAX_SLIPPAGE_PCT', 0.05))
    if slippage is not None and slippage > max_slippage:
        log(f"⏭️ Slippage te groot voor {m}: {slippage*100:.2f}% (max {max_slippage*100:.1f}%)")
        _release_market(m)
        return {'buy_executed': False}
    if spread_pct is not None and spread_pct > MAX_SPREAD_PCT * 1.5:
        log(f"⏭️ Spread te groot voor {m}: {spread_pct*100:.2f}%")
        _release_market(m)
        return {'buy_executed': False}

    fee_component = FEE_TAKER if ORDER_TYPE == 'market' else FEE_MAKER
    total_cost_pct = fee_component + est_slippage
    if spread_pct is not None:
        total_cost_pct += spread_pct * 0.5  # half-spread as expected cost

    activation_pct = max(TRAILING_ACTIVATION_PCT, total_cost_pct + 0.002)
    dynamic_trailing_pct = _clamp(DEFAULT_TRAILING * (1 + vol * 2), 0.015, 0.09)

    # Liquidity guard using orderbook depth (EUR)
    book_full = None
    try:
        book_full = safe_call(bitvavo.book, m, {'depth': 5})
        if book_full and book_full.get('asks') and book_full.get('bids'):
            ask_vol = sum(float(a[0]) * float(a[1]) for a in book_full['asks'])
            bid_vol = sum(float(b[0]) * float(b[1]) for b in book_full['bids'])
            min_depth = float(CONFIG.get('MIN_ORDERBOOK_DEPTH_EUR', 1000.0))
            if ask_vol < min_depth or bid_vol < min_depth:
                log(f"⏭️ Liquidity te laag voor {m}: ask_vol={ask_vol:.0f}, bid_vol={bid_vol:.0f} < {min_depth}")
                _release_market(m)
                return {'buy_executed': False}
    except Exception as e:
        log(f"safe_call failed: {e}", level='error')

    # ── Smart Execution: optimize limit order price via orderbook depth ──
    _smart_exec_price = None
    if CONFIG.get('SMART_EXECUTION_ENABLED', True):
        try:
            from core.smart_execution import optimal_limit_price, calculate_urgency, should_use_limit_order
            _se_book = safe_call(bitvavo.book, m, {'depth': 10}) if not book_full else book_full
            if _se_book and _se_book.get('asks') and _se_book.get('bids'):
                _regime_adj_se = CONFIG.get('_REGIME_ADJ', {})
                _se_regime = _regime_adj_se.get('regime', 'unknown') if _regime_adj_se else 'unknown'
                _btc_burst = False
                try:
                    _btc_st = CONFIG.get('_btc_momentum_state', {})
                    _btc_burst = _btc_st.get('burst_active', False) if _btc_st else False
                except Exception:
                    pass
                _se_urgency = calculate_urgency(score, float(CONFIG.get('MIN_SCORE_TO_BUY', 7)), _btc_burst, _se_regime)
                if should_use_limit_order(spread_pct or 0.0, _se_urgency, score, float(CONFIG.get('MIN_SCORE_TO_BUY', 7))):
                    _smart_exec_price, _se_details = optimal_limit_price(_se_book, 'buy', _se_urgency, amt_eur)
                    if _smart_exec_price and _smart_exec_price < entry_price:
                        _saved_bps = (entry_price - _smart_exec_price) / entry_price * 10000
                        log(f"[SMART-EXEC] {m}: limit @ {_smart_exec_price:.6f} vs market {entry_price:.6f} "
                            f"(save {_saved_bps:.1f}bps, urgency={_se_urgency:.2f})", level='info')
                        entry_price = _smart_exec_price
        except Exception as _se_err:
            log(f"[SMART-EXEC] {m}: Error: {_se_err}", level='debug')

    # PRE-BUY LOCK CHECK: Final slot verification under lock before committing real money
    # This prevents TOCTOU race where conditions change between initial check and buy
    try:
        with trades_lock:
            _prebuy_max = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
            _prebuy_current = sum(
                1 for mk, t in open_trades.items()
                if _compute_trade_value_eur(mk, t)[0] is not None
                and _compute_trade_value_eur(mk, t)[0] >= (DUST_TRADE_THRESHOLD_EUR or 0)
            )
            _prebuy_reserved = _get_pending_count()
            _prebuy_total = _prebuy_current + _prebuy_reserved
            if _prebuy_total >= _prebuy_max and m not in open_trades:
                log(f"🚫 PRE-BUY LOCK CHECK: cap bereikt ({_prebuy_current}+{_prebuy_reserved}/{_prebuy_max}), "
                    f"trade {m} NIET plaatsen", level='warning')
                _release_market(m)
                return {'buy_executed': False}
    except Exception as _prebuy_err:
        log(f"[ERROR] Pre-buy lock check failed for {m}: {_prebuy_err} — BLOCKING (fail-closed)", level='error')
        _release_market(m)
        return {'buy_executed': False}

    # Live koop met safety buy via async helper
    buy_result, entry_price = await safety_buy(m, amt_eur, entry_price)
    if not is_order_success(buy_result):
        _release_market(m)
        return {'buy_executed': False}
    
    # FIX #1: CRITICAL - Verify order is actually FILLED before opening trade
    if isinstance(buy_result, dict):
        status = str(buy_result.get('status', '')).lower()
        filled_amount = float(buy_result.get('filledAmount', 0) or 0)
        
        # Check if order is placed but NOT filled yet
        if status in ('new', 'awaitingtrigger') and filled_amount == 0:
            log(f"⏳ Limit order placed for {m} but not yet filled (orderId={buy_result.get('orderId')}). "
                f"Will be picked up by sync.", level='warning')
            # CRITICAL FIX: Do NOT release reservation — keep it so pending orders
            # count against MAX_OPEN_TRADES via _get_pending_count().
            # Reservation will auto-expire after 5 minutes if order is cancelled.
            return {'buy_executed': False, 'order_pending': True, 
                    'orderId': buy_result.get('orderId'),
                    'eur_reserved': amt_eur}
        
        # Check for partial fill
        expected_tokens = amt_eur / entry_price if entry_price and entry_price > 0 else 0
        if filled_amount > 0 and expected_tokens > 0 and filled_amount < expected_tokens * 0.95:
            log(f"⚠️ PARTIAL FILL for {m}: got {filled_amount:.8f} of ~{expected_tokens:.8f} requested "
                f"({filled_amount/expected_tokens*100:.1f}%)", level='warning')
            # Continue with partial fill - use actual filled amount below
    
    entry_price = _coerce_positive_float(entry_price)
    if entry_price is None:
        log(f"[ERROR] Geen geldig entry_price na koop voor {m}; trade geannuleerd.", level='error')
        _release_market(m)
        return {'buy_executed': False}
    
    # FIX #1: Extract ACTUAL invested EUR and tokens from order response
    # This prevents float precision errors AND handles partial fills correctly
    actual_invested_eur = amt_eur  # Fallback to requested amount
    actual_tokens = amt_eur / entry_price  # Fallback calculation
    
    try:
        if isinstance(buy_result, dict):
            # Use filledAmountQuote (exact EUR spent) if available
            if 'filledAmountQuote' in buy_result:
                actual_invested_eur = float(buy_result['filledAmountQuote'])
                log(f"Using actual invested from order: €{actual_invested_eur:.2f}", level='debug')
            # Use filledAmount (exact tokens bought) if available  
            if 'filledAmount' in buy_result:
                actual_tokens = float(buy_result['filledAmount'])
                log(f"Using actual tokens from order: {actual_tokens:.8f}", level='debug')
            
            # FIX #1: Safety check - if amounts are zero, don't open trade
            if actual_tokens <= 0 or actual_invested_eur <= 0:
                log(f"❌ Order for {m} has zero filled amount - NOT opening trade", level='error')
                _release_market(m)
                return {'buy_executed': False}
    except Exception as e:
        log(f"Could not extract actual amounts from order response: {e}", level='warning')
    
    try:
        # Dynamic DCA profile per trade
        dca_drop_local = _clamp(DCA_DROP_PCT * (1 + vol * 1.5), 0.015, 0.08)
        try:
            if regime == 'defensive':
                dca_drop_local *= 1.2
            elif regime == 'aggressive':
                dca_drop_local *= 0.9
        except Exception as e:
            log(f"regime failed: {e}", level='error')
        # Dynamic DCA amount: percentage of actual base amount, floor at MIN_ORDER_EUR
        _dca_ratio = _as_float(CONFIG.get('DCA_AMOUNT_RATIO'), 0.45)
        _dca_floor = max(float(CONFIG.get('MIN_ORDER_EUR', 5.0)), 5.0)
        dca_amount_local = max(_dca_floor, amt_eur * _dca_ratio)
        dca_step_local = _clamp(DCA_STEP_MULTIPLIER * (1 + vol), 0.5, 2.5)
        dca_max_local = max(1, int(DCA_MAX_BUYS))
        try:
            if regime == 'defensive':
                dca_max_local = max(1, dca_max_local - 1)
            elif regime == 'aggressive':
                dca_max_local = dca_max_local + 1
        except Exception as e:
            log(f"regime failed: {e}", level='error')

        base_amount = float(actual_tokens)
        # Build trade dict — single source, no duplicate fallback
        new_trade = {
            'buy_price': float(entry_price),
            'highest_price': float(entry_price),
            'amount': base_amount,
            'partial_tp_returned_eur': 0.0,
            'dca_buys': 0,
            'dca_events': [],
            'opened_ts': time.time(),
            'timestamp': time.time(),
            'trailing_activation_pct': float(activation_pct),
            'base_trailing_pct': float(dynamic_trailing_pct),
            'cost_buffer_pct': float(total_cost_pct),
            'dca_drop_pct': float(dca_drop_local),
            'dca_amount_eur': float(dca_amount_local),
            'dca_step_mult': float(dca_step_local),
            'dca_max': int(dca_max_local),
            # ── Trade metadata for AI analysis ──
            'score': float(score) if score is not None else 0.0,
            'volatility_at_entry': round(float(vol), 4),
            'opened_regime': str(regime) if regime else 'unknown',
        }
        # Store indicator values from signal_strength (already computed, no extra API call)
        # ml_info contains real RSI, MACD, SMA, volume from bot/signals.py
        try:
            if isinstance(ml_info, dict):
                if ml_info.get('rsi') is not None:
                    new_trade['rsi_at_entry'] = ml_info['rsi']
                if ml_info.get('macd_histogram') is not None:
                    new_trade['macd_at_entry'] = ml_info['macd_histogram']
                if ml_info.get('macd_line') is not None:
                    new_trade['macd_line_at_entry'] = ml_info['macd_line']
                if ml_info.get('macd_signal') is not None:
                    new_trade['macd_signal_at_entry'] = ml_info['macd_signal']
                if ml_info.get('sma_short') is not None:
                    new_trade['sma_short_at_entry'] = ml_info['sma_short']
                if ml_info.get('sma_long') is not None:
                    new_trade['sma_long_at_entry'] = ml_info['sma_long']
                if ml_info.get('ema20') is not None:
                    new_trade['ema20_at_entry'] = ml_info['ema20']
                if ml_info.get('stochastic') is not None:
                    new_trade['stochastic_at_entry'] = ml_info['stochastic']
                if ml_info.get('bb_upper') is not None:
                    new_trade['bb_upper_at_entry'] = ml_info['bb_upper']
                if ml_info.get('bb_lower') is not None:
                    new_trade['bb_lower_at_entry'] = ml_info['bb_lower']
                if ml_info.get('avg_volume') is not None:
                    new_trade['volume_avg_at_entry'] = ml_info['avg_volume']
                log(f"[AI_META] {m}: RSI={ml_info.get('rsi')}, MACD={ml_info.get('macd_histogram')}, "
                    f"SMA_s={ml_info.get('sma_short')}, SMA_l={ml_info.get('sma_long')}, "
                    f"Vol={ml_info.get('avg_volume')}", level='debug')
            else:
                log(f"[AI_META] {m}: ml_info niet beschikbaar, indicators ontbreken", level='warning')
        except Exception as _meta_err:
            log(f"[AI_META] {m}: Fout bij opslaan indicators: {_meta_err}", level='warning')
        # 24h volume for AI metadata
        try:
            _vol_24h = get_24h_volume_eur(m)
            if _vol_24h is not None:
                new_trade['volume_24h_eur'] = round(float(_vol_24h), 0)
        except Exception:
            pass
        # ── Adaptive Exit: regime-aware TP/SL/trailing overrides ──
        if CONFIG.get('ADAPTIVE_EXIT_ENABLED', True):
            try:
                from core.adaptive_exit import calculate_adaptive_exits, apply_exit_overrides
                _ae_regime_adj = CONFIG.get('_REGIME_ADJ', {})
                _ae_regime = _ae_regime_adj.get('regime', 'unknown') if _ae_regime_adj else 'unknown'
                _ae_candles = get_candles(m, '1m', 120)
                if _ae_candles and len(_ae_candles) >= 30:
                    _ae_exits = calculate_adaptive_exits(m, float(entry_price), _ae_candles, _ae_regime)
                    if _ae_exits:
                        new_trade = apply_exit_overrides(new_trade, _ae_exits, CONFIG)
                        new_trade['adaptive_exit_applied'] = True
                        new_trade['adaptive_exit_regime'] = _ae_regime
                        log(f"[ADAPTIVE-EXIT] {m}: trail={_ae_exits.get('trailing_pct', 0):.3f}, "
                            f"SL={_ae_exits.get('hard_sl_pct', 0):.3f}, "
                            f"TP_levels={len(_ae_exits.get('tp_levels', []))} ({_ae_regime})", level='debug')
            except Exception as _ae_err:
                log(f"[ADAPTIVE-EXIT] {m}: Error: {_ae_err}", level='debug')
        # Use TradeInvestment module — single source of truth for invested_eur
        from core.trade_investment import set_initial as _ti_set_initial
        _ti_set_initial(new_trade, float(actual_invested_eur), source="initial_buy")
        with trades_lock:
            # ATOMIC race guard: re-check MAX_OPEN_TRADES while holding the lock
            # to prevent TOCTOU (time-of-check-time-of-use) race conditions.
            max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
            current_under_lock = sum(1 for mk, t in open_trades.items()
                                     if _compute_trade_value_eur(mk, t)[0] is not None
                                     and _compute_trade_value_eur(mk, t)[0] >= (DUST_TRADE_THRESHOLD_EUR or 0))
            reserved = _get_pending_count()
            if (current_under_lock + reserved) >= max_trades and m not in open_trades:
                log(f"🚫 ATOMIC race guard: cap bereikt na koop ({current_under_lock}+{reserved}/{max_trades}), trade {m} NIET toevoegen — CANCELLING order", level='warning')
                _release_market(m)
                # CRITICAL FIX: Cancel the buy order on exchange to prevent sync from re-adding
                try:
                    if isinstance(buy_result, dict) and buy_result.get('orderId'):
                        _cancel_order_id = buy_result['orderId']
                        safe_call(bitvavo.cancelOrder, m, _cancel_order_id)
                        log(f"🗑️ Cancelled orphan buy order {_cancel_order_id} for {m}", level='warning')
                except Exception as _cancel_err:
                    log(f"[ERROR] Could not cancel orphan order for {m}: {_cancel_err}", level='error')
                return {'buy_executed': False}
            open_trades[m] = new_trade
            try:
                if watch_cfg['enabled'] and is_watchlist_market(m):
                    open_trades[m]['watchlist_candidate'] = True
                    open_trades[m]['watchlist_mode'] = watch_cfg['mode']
            except Exception as wl_err:
                log(f"Watchlist flag kon niet gezet worden voor {m}: {wl_err}", level='debug')
    except Exception as trade_init_err:
        log(f"[ERROR] Trade initialisatie mislukt voor {m}: {trade_init_err}", level='error')
        _release_market(m)
        return {'buy_executed': False}
    try:
        if risk_manager and m in open_trades:
            risk_manager.apply_stop_profile(m, open_trades[m], entry_price=float(entry_price))
            risk_manager.attach_ai_target(open_trades[m], entry_price=float(entry_price), score=float(score) if score is not None else None)
    except Exception as exc:
        log(f"Risk manager kon profiel niet toepassen voor {m}: {exc}", level='warning')
    log(f"Trade geopend voor {m} op {entry_price:.6f} (score {score}, vol {vol:.3f}, winst {total_profit:.2f})")
    save_trades()
    cleanup_trades()
    
    # Force EUR balance refresh after buy (Issue #8)
    get_eur_balance(force_refresh=True)
    
    # Increment circuit breaker grace counter so it knows trades are flowing
    if CONFIG.get('_circuit_breaker_until_ts'):
        CONFIG['_cb_trades_since_reset'] = CONFIG.get('_cb_trades_since_reset', 0) + 1
    
    # Release reservation after successful trade open
    _release_market(m)
    return {'buy_executed': True, 'eur_used': amt_eur}
async def safety_buy(m, amt_eur, entry_price):
    buy_result = place_buy(m, amt_eur, entry_price)
    if not is_order_success(buy_result):
        log(f"⚠️ Eerste koop voor {m} mislukt, probeer safety buy (market order) na 2s...")
        await asyncio.sleep(2)
        buy_result = place_buy(m, amt_eur, None, order_type='market')
        if not is_order_success(buy_result):
            log(f"❌ Safety buy voor {m} ook mislukt, sla trade over.")
            return None, entry_price
    # Update entry_price if available in response
    try:
        if isinstance(buy_result, dict) and buy_result.get('price'):
            entry_price = float(buy_result.get('price'))
    except Exception as e:
        log(f"entry_price failed: {e}", level='error')
    return buy_result, entry_price

# =========================
# DASHBOARD (FLASK) - optional
# =========================
def initialize_managers(force: bool = False) -> None:
    global dca_manager, dca_settings, liquidation_manager, monitoring_manager, synchronizer, risk_manager, metrics_collector, _auto_sync_thread, _managers_initialized, _monitor_threads_started

    if _managers_initialized and not force:
        return

    # Initialize API module with shared references
    _api.init(bitvavo_client=bitvavo, config=CONFIG)
    _signals.init(CONFIG, ml_history=_ml_signal_history)
    _trail.init(CONFIG, open_trades_ref=open_trades)

    try:
        dca_context = DCAContext(
            config=CONFIG,
            safe_call=safe_call,
            bitvavo=bitvavo,
            log=log,
            current_open_exposure_eur=current_open_exposure_eur,
            get_min_order_size=get_min_order_size,
            place_buy=place_buy,
            is_order_success=is_order_success,
            save_trades=save_trades,
            get_candles=get_candles,
            close_prices=close_prices,
            rsi=rsi,
            trade_log_path=TRADE_LOG,
            get_market_perf_snapshot=_perf.get_snapshot,
            get_market_size_multiplier=_perf.get_position_size_multiplier,
            get_ai_regime_bias=get_ai_regime_bias,
            send_alert=send_alert,
        )
        dca_manager = DCAManager(dca_context)
        dca_settings = DCASettings(
            enabled=DCA_ENABLED,
            dynamic=DCA_DYNAMIC,
            max_buys=DCA_MAX_BUYS,
            max_buys_per_iteration=CONFIG.get('DCA_MAX_BUYS_PER_ITERATION', None),
            drop_pct=DCA_DROP_PCT,
            step_multiplier=DCA_STEP_MULTIPLIER,
            amount_eur=DCA_AMOUNT_EUR,
            size_multiplier=DCA_SIZE_MULTIPLIER,
        )
    except Exception as exc:
        dca_manager = None
        dca_settings = None
        log(f"Init DCA manager mislukt: {exc}", level='error')

    try:
        sync_context = SyncContext(
            config=CONFIG,
            safe_call=safe_call,
            bitvavo=bitvavo,
            log=log,
            write_json_locked=write_json_locked,
            file_lock=file_lock,
            save_trades=save_trades,
            trade_log_path=TRADE_LOG,
            pending_saldo_path='data/pending_saldo.json',
            sync_debug_path='data/sync_debug.json',
            sync_raw_balances_path='data/sync_raw_balances.json',
            sync_raw_markets_path='data/sync_raw_markets.json',
            sync_removed_cache_path='data/sync_removed_cache.json',
            pending_new_markets=_get_pending_markets_dict,  # Pass function for thread-safe access
        )
        synchronizer = TradingSynchronizer(sync_context)
    except Exception as exc:
        synchronizer = None
        log(f"Init synchronizer mislukt: {exc}", level='error')

    try:
        risk_context = RiskContext(
            config=CONFIG,
            log=log,
            load_trade_snapshot=lambda: load_trade_snapshot(TRADE_LOG),
            get_open_trades=lambda: open_trades,
            current_open_exposure_eur=current_open_exposure_eur,
        )
        risk_manager = RiskManager(risk_context)
    except Exception as exc:
        risk_manager = None
        log(f"Init risk manager mislukt: {exc}", level='error')

    try:
        metrics_collector = get_metrics_collector() or configure_metrics(CONFIG, log=log)
    except Exception as exc:
        metrics_collector = None
        log(f"Init metrics collector mislukt: {exc}", level='error')

    # Update API module with risk manager reference
    _api._risk_mgr = risk_manager

    try:
        liquidation_context = LiquidationContext(
            config=CONFIG,
            log=log,
            get_current_price=get_current_price,
            place_sell=place_sell,
            realized_profit=realized_profit,
            save_trades=save_trades,
            cleanup_trades=cleanup_trades,
            pending_saldo_path='data/pending_saldo.json',
            cancel_open_buys_fn=cancel_open_buys_if_capped,
            refresh_balance_fn=lambda: get_eur_balance(force_refresh=True),
        )
        liquidation_manager = LiquidationManager(liquidation_context)
    except Exception as exc:
        liquidation_manager = None
        log(f"Init liquidation manager mislukt: {exc}", level='error')

    try:
        monitoring_context = MonitoringContext(
            log=log,
            write_json_locked=write_json_locked,
            safe_call=safe_call,
            bitvavo=bitvavo,
            estimate_max_eur_per_trade=estimate_max_eur_per_trade,
            estimate_max_total_eur=estimate_max_total_eur,
            current_open_exposure_eur=current_open_exposure_eur,
            trade_log_path=TRADE_LOG,
            heartbeat_file=HEARTBEAT_FILE,
            ai_heartbeat_path=AI_HEARTBEAT_FILE,
            ai_heartbeat_stale_seconds=AI_HEARTBEAT_STALE_SECONDS,
            metrics_collector=metrics_collector,
            risk_metrics_provider=(lambda: risk_manager.metrics) if risk_manager else None,
            consume_api_error_count=risk_manager.consume_api_error_count if risk_manager else None,
            portfolio_snapshot_path=str(PORTFOLIO_SNAPSHOT_FILE),
            partial_tp_stats_provider=get_partial_tp_stats,
            event_hook_status_provider=_event_hook_status_payload if EVENT_STATE else None,
        )
        monitoring_manager = MonitoringManager(monitoring_context)
    except Exception as exc:
        monitoring_manager = None
        log(f"Init monitoring manager mislukt: {exc}", level='error')

    if not _monitor_threads_started and not CONFIG.get('TEST_MODE', False) and not os.environ.get('PYTEST_CURRENT_TEST'):
        try:
            _start_heartbeat_writer(interval=30)
            _start_heartbeat_monitor()
            _start_reservation_watchdog(interval=30)
            _monitor_threads_started = True
        except Exception as exc:
            log(f"Heartbeat/monitor threads konden niet starten: {exc}", level='error')

    try:
        start_auto_sync(interval=SYNC_INTERVAL_SECONDS)
    except Exception as exc:
        log(f"Auto-sync kon niet worden gestart: {exc}", level='error')

    _managers_initialized = True


try:
    initialize_managers()
except Exception as exc:
    log(f"Initialisatie van managers mislukt: {exc}", level='error')

# ── Populate shared state registry for extracted modules ────────────
def _init_shared_state():
    """Register all shared state into bot.shared for extracted modules."""
    from bot.shared import init as _init_shared
    _init_shared(
        open_trades=open_trades,
        closed_trades=closed_trades,
        market_profits=market_profits,
        trades_lock=trades_lock,
        CONFIG=CONFIG,
        RUNNING=RUNNING,
        bitvavo=bitvavo,
        TRADE_LOG=TRADE_LOG,
        ARCHIVE_FILE=ARCHIVE_FILE,
        TRADE_PNL_HISTORY_FILE=TRADE_PNL_HISTORY_FILE,
        PORTFOLIO_SNAPSHOT_FILE=PORTFOLIO_SNAPSHOT_FILE,
        ACCOUNT_OVERVIEW_FILE=ACCOUNT_OVERVIEW_FILE,
        HEARTBEAT_FILE=HEARTBEAT_FILE,
        AI_HEARTBEAT_FILE=AI_HEARTBEAT_FILE,
        MAX_CLOSED=MAX_CLOSED,
        MIN_ORDER_EUR=MIN_ORDER_EUR,
        DUST_TRADE_THRESHOLD_EUR=DUST_TRADE_THRESHOLD_EUR,
        FEE_MAKER=FEE_MAKER,
        FEE_TAKER=FEE_TAKER,
        SLIPPAGE_PCT=SLIPPAGE_PCT,
        MAX_SPREAD_PCT=MAX_SPREAD_PCT,
        ORDER_TYPE=ORDER_TYPE,
        TRAILING_ACTIVATION_PCT=TRAILING_ACTIVATION_PCT,
        DEFAULT_TRAILING=DEFAULT_TRAILING,
        SLEEP_SECONDS=SLEEP_SECONDS,
        PLACE_ORDERS_ENABLED=PLACE_ORDERS_ENABLED,
        BASE_AMOUNT_EUR=BASE_AMOUNT_EUR,
        MAX_TOTAL_EXPOSURE_EUR=MAX_TOTAL_EXPOSURE_EUR,
        AUTO_USE_FULL_BALANCE=AUTO_USE_FULL_BALANCE,
        FULL_BALANCE_MAX_EUR=FULL_BALANCE_MAX_EUR,
        FULL_BALANCE_PORTION=FULL_BALANCE_PORTION,
        REINVEST_ENABLED=REINVEST_ENABLED,
        REINVEST_MIN_TRADES=REINVEST_MIN_TRADES,
        REINVEST_MIN_PROFIT=REINVEST_MIN_PROFIT,
        REINVEST_PORTION=REINVEST_PORTION,
        REINVEST_MAX_INCREASE_PCT=REINVEST_MAX_INCREASE_PCT,
        REINVEST_CAP=REINVEST_CAP,
        LIVE_TRADING=LIVE_TRADING,
        TEST_MODE=TEST_MODE,
        OPERATOR_ID=OPERATOR_ID,
        DCA_MAX_BUYS=DCA_MAX_BUYS,
        DCA_DROP_PCT=DCA_DROP_PCT,
        DUST_SWEEP_ENABLED=DUST_SWEEP_ENABLED,
        DUST_THRESHOLD_EUR=DUST_THRESHOLD_EUR,
        log=log,
        safe_call=safe_call,
        get_candles=getattr(_api, 'get_candles', lambda *a, **kw: None),
        get_current_price=get_current_price,
        get_eur_balance=get_eur_balance,
        get_market_info=get_market_info,
        get_min_order_size=get_min_order_size,
        get_amount_precision=get_amount_precision,
        get_price_precision=get_price_precision,
        get_ticker_best_bid_ask=get_ticker_best_bid_ask,
        normalize_amount=normalize_amount,
        normalize_price=normalize_price,
        write_json_locked=write_json_locked,
        json_write_compat=json_write_compat,
        send_alert=send_alert,
        save_trades_fn=save_trades,
        load_trade_snapshot=load_trade_snapshot,
        save_trade_snapshot=save_trade_snapshot,
        sanitize_balance_payload=sanitize_balance_payload,
        cleanup_trades=cleanup_trades,
        optimize_parameters=optimize_parameters,
        analyse_trades=analyse_trades,
        count_active_open_trades=count_active_open_trades,
        count_dust_trades=count_dust_trades,
        _get_pending_count=_get_pending_count,
        _get_pending_markets_dict=_get_pending_markets_dict,
        _is_market_reserved=_is_market_reserved,
        _reserve_market=_reserve_market,
        _release_market=_release_market,
        count_pending_bitvavo_orders=count_pending_bitvavo_orders,
        get_pending_bitvavo_orders=get_pending_bitvavo_orders,
        current_open_exposure_eur=current_open_exposure_eur,
        is_watchlist_market=is_watchlist_market,
        _get_watchlist_runtime_settings=_get_watchlist_runtime_settings,
        get_active_grid_markets=get_active_grid_markets,
        archive_trade=archive_trade,
        _record_market_stats_for_close=_record_market_stats_for_close,
        _finalize_close_trade=_finalize_close_trade,
        load_market_performance=load_market_performance,
        save_market_performance=save_market_performance,
        _append_trade_pnl_jsonl=_append_trade_pnl_jsonl,
        derive_cost_basis=derive_cost_basis,
        spread_ok=spread_ok,
        risk_manager=risk_manager,
        dca_manager=dca_manager,
        synchronizer=synchronizer,
        metrics_collector=metrics_collector,
        _reservation_manager=_reservation_manager,
        _perf=_perf,
        _clamp=_clamp,
        _coerce_positive_float=_coerce_positive_float,
        _log_throttled=_log_throttled,
        get_true_invested_eur=get_true_invested_eur,
        register_saldo_error=register_saldo_error,
    )
    log("[INIT] Shared state registry populated for extracted modules")

try:
    _init_shared_state()
except Exception as _shared_err:
    log(f"[WARNING] Shared state init failed: {_shared_err}", level='warning')


# =========================
# ENTRY POINT
if __name__ == '__main__':
    # Config validation on startup (Issue #9)
    validate_config()
    
    # Trade data integrity check on startup (anti-corruption guard)
    try:
        validate_and_repair_trades()
    except Exception as e:
        log(f"⚠️ Trade validation failed on startup: {e}", level='warning')
    
    # Single-instance check via shared helper (best-effort)
    try:
        from scripts.helpers.single_instance import ensure_single_instance_or_exit  # type: ignore[import]
        ensure_single_instance_or_exit('trailing_bot.py', allow_claim=True)
    except SystemExit as se:
        # Log the singleton guard exit so it's visible in bot_log
        log(f"🛑 Singleton guard: trailing_bot.py kan niet starten (exit code {se.code})", level='error')
        raise
    except Exception:
        # Helper not available or import failed; continue without hard guard
        pass
    
    # --- Graceful shutdown signal handler ---
    def _graceful_shutdown(signum, frame):
        global RUNNING
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        log(f"🛑 Received {sig_name} — initiating graceful shutdown...", level='warning')
        RUNNING = False
        try:
            save_trades()
            log("✅ Trades saved during graceful shutdown")
        except Exception as e:
            log(f"Save failed during shutdown: {e}", level='error')
        try:
            # Notify via Telegram
            from modules.telegram_handler import send_message
            send_message(f"🛑 Bot graceful shutdown ({sig_name})")
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)
    if hasattr(signal, 'SIGBREAK'):  # Windows
        signal.signal(signal.SIGBREAK, _graceful_shutdown)
    log("✅ Graceful shutdown handlers registered (SIGTERM/SIGINT/SIGBREAK)")

    # Start documentation auto-updater (updates docs every 5 minutes)
    try:
        from scripts.helpers.doc_auto_updater import start_doc_updater
        start_doc_updater(update_interval_seconds=300)  # 5 minutes
        log("[DOC_SYNC] Documentation auto-updater started")
    except Exception as doc_err:
        log(f"[DOC_SYNC] Warning: Could not start doc updater: {doc_err}", level='debug')

    try:
        # If STOP_AFTER_SECONDS > 0, enforce a global timeout for sanity dry-runs
        if STOP_AFTER_SECONDS and STOP_AFTER_SECONDS > 0:
            try:
                asyncio.run(asyncio.wait_for(bot_loop(), timeout=STOP_AFTER_SECONDS + 10))
            except asyncio.TimeoutError:
                log(f"⏱️ Global timeout reached (~{STOP_AFTER_SECONDS}s), exiting.")
        else:
            asyncio.run(bot_loop())
    except KeyboardInterrupt:
        RUNNING = False
        save_trades()
        cleanup_trades()
        # Direct sync with Bitvavo to remove manually sold positions
        try:
            sync_with_bitvavo()
        except Exception as sync_err:
            log(f"Sync bij afsluiten faalde: {sync_err}", level='error')
        # Save trades and heartbeat after sync
        try:
            save_trades()
        except Exception as save_err:
            log(f"Opslaan na sync faalde: {save_err}", level='error')
        log("✅ Bot netjes afgesloten.")
    except SystemExit as se:
        # Catch sys.exit() from signal handlers or singleton guards so we log it
        log(f"🛑 Bot exit via SystemExit (code={se.code})", level='warning')
        raise
    except Exception as e:
        # Log full traceback for debugging
        logging.exception(f"Bot gestopt door fout: {type(e).__name__}: {e}")
        # Monitoring/notificatie (optioneel)
        try:
            import requests
            TELEGRAM_WEBHOOK = CONFIG.get('TELEGRAM_WEBHOOK')
            if TELEGRAM_WEBHOOK:
                requests.post(TELEGRAM_WEBHOOK, json={"text": f"Bot gestopt door fout: {type(e).__name__}: {e}"})
        except Exception as notify_err:
            logging.exception(f"Notificatie fout: {type(notify_err).__name__}: {notify_err}")
