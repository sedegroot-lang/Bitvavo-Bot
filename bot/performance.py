"""bot.performance – Per-market performance tracking, expectancy, and filtering.

Tracks win/loss stats per market, publishes expectancy metrics,
and provides market filtering based on historical performance.

Usage:
    import bot.performance as _perf
    _perf.init(config)
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.logging_utils import log, locked_write_json

# ---------------------------------------------------------------------------
# Module state – set by init()
# ---------------------------------------------------------------------------
_cfg: dict = {}

# Performance data
market_performance: Dict[str, Any] = {}
_LOCK = threading.Lock()
_LAST_SAVE: float = 0.0
_FILTER_LOG: Dict[str, float] = {}
_BLOCK_TIMESTAMPS: Dict[str, float] = {}
_LAST_PERF_SAVE_TIME: float = 0.0

# References (injected)
_closed_trades_ref: list = []
_get_partial_tp_stats_fn = None
_count_active_fn = None


def _ensure_parent_dir(path: str) -> None:
    try:
        parent = Path(path).parent
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"[ERROR] Failed to create parent directory for {path}: {e}", level="error")


# ---------------------------------------------------------------------------
# Config accessors (read at call time for hot-reload)
# ---------------------------------------------------------------------------

def _file(key: str, default: str) -> Path:
    return Path(_cfg.get(key, default))


def _int(key: str, default: int, lo: int = 0) -> int:
    return max(lo, int(_cfg.get(key, default)))


def _float(key: str, default: float) -> float:
    return float(_cfg.get(key, default))


def _bool(key: str, default: bool) -> bool:
    v = _cfg.get(key, default)
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 'yes')


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

def init(
    config: dict,
    *,
    closed_trades_ref: list | None = None,
    get_partial_tp_stats_fn=None,
    count_active_fn=None,
) -> None:
    """Inject runtime dependencies."""
    global _cfg, _closed_trades_ref, _get_partial_tp_stats_fn, _count_active_fn
    _cfg = config
    if closed_trades_ref is not None:
        _closed_trades_ref = closed_trades_ref
    if get_partial_tp_stats_fn is not None:
        _get_partial_tp_stats_fn = get_partial_tp_stats_fn
    if count_active_fn is not None:
        _count_active_fn = count_active_fn
    load_market_performance()


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_market_performance() -> Dict[str, Any]:
    """Load per-market performance metrics from disk into memory."""
    global market_performance
    path = _file('MARKET_PERFORMANCE_FILE', os.path.join('data', 'market_metrics.json'))
    if not path.exists():
        market_performance = {}
        return market_performance
    try:
        with _LOCK:
            with path.open('r', encoding='utf-8') as fh:
                data = json.load(fh)
            market_performance = data if isinstance(data, dict) else {}
    except Exception as exc:
        log(f"Kon market_metrics niet laden: {exc}", level='warning')
        market_performance = {}
    return market_performance


def save_market_performance(force: bool = False) -> None:
    """Persist in-memory performance metrics to disk with throttling."""
    global _LAST_SAVE
    now = time.time()
    interval = max(5, int(_cfg.get('MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS', 30)))
    if not force and (now - _LAST_SAVE) < interval:
        return
    path = _file('MARKET_PERFORMANCE_FILE', os.path.join('data', 'market_metrics.json'))
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    try:
        _ensure_parent_dir(str(path))
        with _LOCK:
            with tmp_path.open('w', encoding='utf-8') as fh:
                json.dump(market_performance, fh, indent=2)
            os.replace(tmp_path, path)
        _LAST_SAVE = now
    except Exception as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception as e:
            log(f"exists failed: {e}", level='debug')
        log(f"Kon marktprestaties niet opslaan: {exc}", level='warning')


def maybe_save_market_performance() -> None:
    """Force-save market_performance if secondary interval elapsed."""
    global _LAST_PERF_SAVE_TIME
    now = time.time()
    interval = max(60, int(_cfg.get('MARKET_PERFORMANCE_SAVE_INTERVAL_SECONDS', 30)) * 2)
    if now - _LAST_PERF_SAVE_TIME >= interval:
        save_market_performance(force=True)
        _LAST_PERF_SAVE_TIME = now


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

def record_trade_performance(
    market: str,
    profit_eur: float,
    invested_eur: Optional[float],
    opened_ts: Optional[float],
    closed_ts: Optional[float],
    reason: Optional[str] = None,
) -> None:
    """Update per-market performance metrics based on a closed trade."""
    if not market:
        return
    try:
        profit_val = float(profit_eur)
    except Exception:
        profit_val = 0.0
    roi_pct = 0.0
    if invested_eur:
        try:
            roi_pct = profit_val / float(invested_eur)
        except Exception:
            roi_pct = 0.0
    hold_seconds = None
    if opened_ts and closed_ts:
        try:
            hold_seconds = max(0.0, float(closed_ts) - float(opened_ts))
        except Exception:
            hold_seconds = None
    now = time.time()
    with _LOCK:
        stats = market_performance.setdefault(
            market,
            {
                'trades': 0, 'wins': 0, 'losses': 0,
                'total_profit': 0.0, 'avg_profit': 0.0,
                'avg_roi_pct': 0.0, 'avg_hold_seconds': 0.0,
                'consecutive_losses': 0, 'win_rate': 0.0,
                'last_profit': 0.0, 'last_reason': '', 'last_closed_ts': 0.0,
                'last_opened_ts': 0.0,
            },
        )
        stats['trades'] = int(stats.get('trades', 0)) + 1
        trades = max(1, int(stats['trades']))
        if profit_val > 0:
            stats['wins'] = int(stats.get('wins', 0)) + 1
            stats['losses'] = int(stats.get('losses', 0))
            stats['consecutive_losses'] = 0
        else:
            stats['losses'] = int(stats.get('losses', 0)) + 1
            stats['consecutive_losses'] = int(stats.get('consecutive_losses', 0)) + 1
        wins = int(stats.get('wins', 0))
        stats['win_rate'] = wins / trades if trades else 0.0
        stats['total_profit'] = float(stats.get('total_profit', 0.0)) + profit_val
        stats['avg_profit'] = stats['total_profit'] / trades if trades else profit_val
        prev_avg_roi = float(stats.get('avg_roi_pct', 0.0))
        stats['avg_roi_pct'] = prev_avg_roi + ((roi_pct - prev_avg_roi) / trades)
        if hold_seconds is not None:
            prev_hold = float(stats.get('avg_hold_seconds', 0.0))
            stats['avg_hold_seconds'] = prev_hold + ((hold_seconds - prev_hold) / trades)
            stats['last_hold_seconds'] = hold_seconds
        stats['last_profit'] = profit_val
        stats['last_reason'] = reason or stats.get('last_reason', '')
        stats['last_closed_ts'] = float(closed_ts or now)
        if opened_ts:
            stats['last_opened_ts'] = float(opened_ts)
        if invested_eur is not None:
            try:
                stats['last_invested_eur'] = float(invested_eur)
            except Exception as e:
                log(f"stats update failed: {e}", level='error')
        stats['last_roi_pct'] = roi_pct
        stats['last_updated_ts'] = now
    save_market_performance()


def record_market_stats_for_close(
    market: str,
    closed_entry: Dict[str, Any],
    open_entry: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort wrapper to pass trade metadata into record_trade_performance."""
    try:
        invested_eur = None
        opened_ts = None
        if isinstance(open_entry, dict):
            try:
                opened_ts = float(open_entry.get('opened_ts') or open_entry.get('timestamp') or 0.0)
            except Exception:
                opened_ts = None
            try:
                invested_eur = float(open_entry.get('invested_eur') or 0.0)
            except Exception:
                invested_eur = 0.0
        else:
            try:
                invested_eur = float(closed_entry.get('invested_eur') or 0.0)
            except Exception:
                invested_eur = None
            try:
                opened_ts = float(closed_entry.get('opened_ts') or 0.0)
            except Exception:
                opened_ts = None
        try:
            closed_ts = float(closed_entry.get('timestamp')) if closed_entry.get('timestamp') is not None else None
        except Exception:
            closed_ts = None
        profit = closed_entry.get('profit', 0.0)
        record_trade_performance(market, profit, invested_eur, opened_ts, closed_ts, closed_entry.get('reason'))
        publish_expectancy_metrics()
    except Exception as e:
        log(f"[ERROR] Failed to record market stats for {closed_entry.get('market')}: {e}", level='error')


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def get_snapshot(market: str) -> Optional[Dict[str, Any]]:
    """Return a deep copy of performance stats for one market."""
    try:
        with _LOCK:
            stats = market_performance.get(market)
            return copy.deepcopy(stats) if isinstance(stats, dict) else None
    except Exception:
        return None


def get_position_size_multiplier(market: str, stats: Optional[Dict[str, Any]] = None) -> float:
    """Return a position size multiplier based on market history."""
    if not _bool('MARKET_PERFORMANCE_SIZE_BIAS_ENABLED', True):
        return 1.0
    stats = stats if stats is not None else get_snapshot(market)
    if not stats:
        return 1.0
    min_trades = _int('MARKET_PERFORMANCE_MIN_TRADES', 5, lo=1)
    trades = int(stats.get('trades', 0) or 0)
    if trades < min_trades:
        return 1.0
    avg_profit = float(stats.get('avg_profit', 0.0) or 0.0)
    consec_losses = int(stats.get('consecutive_losses', 0) or 0)
    min_exp = _float('MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR', 0.0)
    target_exp = max(min_exp + 0.01, _float('MARKET_PERFORMANCE_TARGET_EXPECTANCY_EUR', 1.0))
    max_consec = _int('MARKET_PERFORMANCE_MAX_CONSEC_LOSSES', 3, lo=1)
    size_min = max(0.1, _float('MARKET_PERFORMANCE_SIZE_MIN_MULTIPLIER', 0.5))
    size_max = max(size_min, _float('MARKET_PERFORMANCE_SIZE_MAX_MULTIPLIER', 1.5))
    smoothing = min(1.0, max(0.0, _float('MARKET_PERFORMANCE_SMOOTHING', 0.2)))

    if avg_profit <= min_exp:
        base_mult = size_min
    elif avg_profit >= target_exp:
        base_mult = size_max
    else:
        span = max(0.01, target_exp - min_exp)
        ratio = (avg_profit - min_exp) / span
        base_mult = size_min + ratio * (size_max - size_min)
    if consec_losses >= max_consec:
        base_mult = min(base_mult, size_min)
    if 0 < smoothing < 1:
        base_mult = 1.0 + (base_mult - 1.0) * (1.0 - smoothing)
    return float(max(size_min, min(size_max, base_mult)))


# ---------------------------------------------------------------------------
# Market filtering
# ---------------------------------------------------------------------------

def filter_markets_by_performance(markets: List[str]) -> List[str]:
    """Remove markets with poor historical performance."""
    if not _bool('MARKET_PERFORMANCE_FILTER_ENABLED', True) or not markets:
        return markets
    filtered: List[str] = []
    now = time.time()
    min_trades = _int('MARKET_PERFORMANCE_MIN_TRADES', 5, lo=1)
    min_exp = _float('MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR', 0.0)
    max_consec = _int('MARKET_PERFORMANCE_MAX_CONSEC_LOSSES', 3, lo=1)
    probation_seconds = _int('MARKET_PERFORMANCE_PROBATION_DAYS', 7, lo=1) * 86400
    log_interval = max(60, int(_cfg.get('MARKET_PERFORMANCE_FILTER_LOG_INTERVAL', 1800)))

    for market in markets:
        stats = get_snapshot(market)
        if not stats:
            filtered.append(market)
            continue
        trades = int(stats.get('trades', 0) or 0)
        if trades < min_trades:
            filtered.append(market)
            continue
        avg_profit = float(stats.get('avg_profit', 0.0) or 0.0)
        consec_losses = int(stats.get('consecutive_losses', 0) or 0)

        should_block = (avg_profit < min_exp or consec_losses >= max_consec)

        if should_block:
            if market not in _BLOCK_TIMESTAMPS:
                _BLOCK_TIMESTAMPS[market] = now
            blocked_duration = now - _BLOCK_TIMESTAMPS[market]
            if blocked_duration >= probation_seconds:
                if avg_profit >= min_exp * 0.5 and consec_losses < max_consec:
                    log(f"[PROBATION] {market}: Unblocked after probation (profit improved to {avg_profit:.2f})", level='info')
                    del _BLOCK_TIMESTAMPS[market]
                    filtered.append(market)
                    continue
                else:
                    _BLOCK_TIMESTAMPS[market] = now
            last_log = _FILTER_LOG.get(market, 0.0)
            if (now - last_log) >= log_interval:
                _FILTER_LOG[market] = now
                days_blocked = blocked_duration / 86400
                try:
                    log(
                        f"Performance filter blokkeert {market}: avg_profit={avg_profit:.2f}, "
                        f"consec_losses={consec_losses}, trades={trades} (blocked {days_blocked:.1f}d)",
                        level='info',
                    )
                except Exception as e:
                    log(f"log failed: {e}", level='error')
            continue
        else:
            if market in _BLOCK_TIMESTAMPS:
                blocked_duration = now - _BLOCK_TIMESTAMPS[market]
                log(
                    f"[UNBLOCK] {market}: Conditions improved (avg_profit {avg_profit:.2f}, "
                    f"consec_losses {consec_losses}) after {blocked_duration/86400:.1f}d",
                    level='info',
                )
                del _BLOCK_TIMESTAMPS[market]
            filtered.append(market)

    return filtered


# ---------------------------------------------------------------------------
# Expectancy publishing
# ---------------------------------------------------------------------------

def _compute_win_loss_streaks(series: List[float]) -> Dict[str, Any]:
    longest_win = 0
    longest_loss = 0
    current_len = 0
    current_type: Optional[str] = None
    for value in series:
        if value > 0:
            if current_type == 'win':
                current_len += 1
            else:
                current_len = 1
                current_type = 'win'
            longest_win = max(longest_win, current_len)
        elif value < 0:
            if current_type == 'loss':
                current_len += 1
            else:
                current_len = 1
                current_type = 'loss'
            longest_loss = max(longest_loss, current_len)
        else:
            current_len = 0
            current_type = None
    current = {'type': current_type, 'length': current_len if current_type else 0}
    return {'longest_win': longest_win, 'longest_loss': longest_loss, 'current': current}


def _load_archive_trades() -> list:
    """Load closed trades from the trade archive for complete expectancy stats."""
    archive_path = _cfg.get('ARCHIVE_FILE', os.path.join('data', 'trade_archive.json'))
    if not os.path.exists(archive_path):
        return []
    try:
        with open(archive_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data.get('trades', [])
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def publish_expectancy_metrics() -> None:
    """Compute and write expectancy metrics from closed trades to disk.

    Includes archived trades for accurate lifetime stats.
    """
    # Merge archived trades + current session closed trades for full picture
    archive = _load_archive_trades()
    session_closed = list(_closed_trades_ref) if _closed_trades_ref else []
    # De-duplicate: archive trades have 'archived_at', session trades don't
    archive_ts = {(t.get('market', ''), round(t.get('timestamp', 0), 1)) for t in archive if isinstance(t, dict)}
    unique_session = [
        t for t in session_closed
        if isinstance(t, dict) and (t.get('market', ''), round(t.get('timestamp', 0), 1)) not in archive_ts
    ]
    closed = archive + unique_session
    if not closed:
        return
    try:
        profits = [float(t.get('profit', 0.0) or 0.0) for t in closed if isinstance(t, dict)]
        if not profits:
            return
        total = len(profits)
        wins = [p for p in profits if p > 0]
        losses = [abs(p) for p in profits if p <= 0]
        win_rate = len(wins) / total if total else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = (gross_profit / gross_loss) if gross_loss else None
        recent_window = int(_cfg.get('EXPECTANCY_RECENT_WINDOW', 50) or 50)
        recent = profits[-recent_window:]
        recent_wins = [p for p in recent if p > 0]
        recent_losses = [abs(p) for p in recent if p <= 0]
        recent_win_rate = len(recent_wins) / len(recent) if recent else 0.0
        recent_avg_win = sum(recent_wins) / len(recent_wins) if recent_wins else 0.0
        recent_avg_loss = sum(recent_losses) / len(recent_losses) if recent_losses else 0.0
        recent_expectancy = (recent_win_rate * recent_avg_win) - ((1 - recent_win_rate) * recent_avg_loss)
        streaks = _compute_win_loss_streaks(profits)
        last_trade = closed[-1] if closed else {}
        partial_summary = _get_partial_tp_stats_fn() if _get_partial_tp_stats_fn else {}
        updated_at = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
        dust_threshold = float(_cfg.get('DUST_TRADE_THRESHOLD_EUR', _cfg.get('MIN_ORDER_EUR', 5.0)))
        open_count = _count_active_fn(threshold=dust_threshold) if _count_active_fn else 0
        payload = {
            'ts': int(time.time()),
            'updated_at': updated_at,
            'sample_size': total,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'expectancy_eur': expectancy,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': profit_factor,
            'net_profit': sum(profits),
            'streaks': streaks,
            'recent': {
                'sample_size': len(recent),
                'win_rate': recent_win_rate,
                'expectancy_eur': recent_expectancy,
            },
            'last_trade': {
                'market': last_trade.get('market'),
                'profit': last_trade.get('profit'),
                'timestamp': last_trade.get('timestamp'),
                'reason': last_trade.get('reason'),
            } if last_trade else None,
            'open_trades': open_count,
            'partial_tp_stats': partial_summary,
        }
        exp_file = _file('EXPECTANCY_FILE', 'data/expectancy_stats.json')
        locked_write_json(str(exp_file), payload)
        try:
            history_file = _file('EXPECTANCY_HISTORY_FILE', 'data/expectancy_history.jsonl')
            _ensure_parent_dir(str(history_file))
            with history_file.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + '\n')
        except Exception as e:
            log(f"[ERROR] Expectancy history write failed: {e}", level='error')
    except Exception as e:
        log(f"[ERROR] Expectancy snapshot failed: {e}", level='error')
