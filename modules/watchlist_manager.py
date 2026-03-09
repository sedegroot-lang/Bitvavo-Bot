"""Centralized automation for AI watchlist promotions/demotions.

The watchlist enforces a two-step onboarding flow:
1. Markets proposed by the AI land on the watchlist first (paper or micro mode).
2. Periodic analytics-driven reviews promote/demote markets automatically within guardrails.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.logging_utils import log

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'bot_config.json'
STATE_PATH = PROJECT_ROOT / 'data' / 'watchlist_state.json'


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        with path.open('r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        with tmp.open('w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
        tmp.replace(path)
        return True
    except Exception as exc:
        log(f"watchlist_manager: failed to write {path.name}: {exc}", level='error')
        return False


def _load_config() -> Dict[str, Any]:
    return _load_json(CONFIG_PATH, {}) or {}


def _write_config(cfg: Dict[str, Any]) -> bool:
    return _write_json(CONFIG_PATH, cfg)


def load_state() -> Dict[str, Any]:
    default = {'markets': {}, 'last_review_ts': 0}
    state = _load_json(STATE_PATH, default)
    if not isinstance(state, dict):
        return default
    state.setdefault('markets', {})
    state.setdefault('last_review_ts', 0)
    return state


def save_state(state: Dict[str, Any]) -> bool:
    return _write_json(STATE_PATH, state)


def get_watchlist_settings(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or _load_config()
    settings = cfg.get('WATCHLIST_SETTINGS') or {}
    mode = str(settings.get('mode', 'micro') or 'micro').lower()
    return {
        'enabled': bool(settings.get('enabled', True)),
        'mode': mode,
        'paper_only': bool(settings.get('paper_only', mode == 'paper')),
        'micro_trade_amount_eur': float(settings.get('micro_trade_amount_eur', 5.0)),
        'max_parallel': max(0, int(settings.get('max_parallel', 3))),
        'review_window_days': max(1, int(settings.get('review_window_days', 5))),
        'promotion_min_trades': max(1, int(settings.get('promotion_min_trades', 5))),
        'promotion_min_win_rate_pct': float(settings.get('promotion_min_win_rate_pct', 45.0)),
        'promotion_min_avg_pnl': float(settings.get('promotion_min_avg_pnl', 0.5)),
        'paper_min_days': max(1, int(settings.get('paper_min_days', 3))),
        'paper_promotion_min_return_pct': float(settings.get('paper_promotion_min_return_pct', 3.0)),
        'demote_after_days': max(1, int(settings.get('demote_after_days', 10))),
        'demote_min_trades': max(1, int(settings.get('demote_min_trades', 6))),
        'demote_max_win_rate_pct': float(settings.get('demote_max_win_rate_pct', 30.0)),
        'demote_max_avg_pnl': float(settings.get('demote_max_avg_pnl', -1.0)),
        'max_loss_streak': max(1, int(settings.get('max_loss_streak', 4))),
        'disable_dca': bool(settings.get('disable_dca', True)),
    }


def get_watchlist_markets(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    cfg = cfg or _load_config()
    return list(cfg.get('WATCHLIST_MARKETS') or [])


def _fetch_market_price(market: str) -> Optional[float]:
    try:
        from modules.ai_markets import get_bid_ask

        book = get_bid_ask(market)
        if not book:
            return None
        ask = float(book.get('ask') or 0)
        bid = float(book.get('bid') or 0)
        if ask and bid:
            return (ask + bid) / 2.0
        return ask or bid or None
    except Exception:
        return None


def queue_market_for_watchlist(
    market: str,
    *,
    reason: str = '',
    source: str = 'ai',
    cfg: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = cfg or _load_config()
    settings = get_watchlist_settings(cfg)
    if not settings['enabled']:
        log(f"[WATCHLIST] Skipping {market}: watchlist disabled", level='info')
        return False
    watchlist = list(cfg.get('WATCHLIST_MARKETS') or [])
    already_listed = market in watchlist
    if not already_listed:
        watchlist.append(market)
        cfg['WATCHLIST_MARKETS'] = watchlist
        if not _write_config(cfg):
            return False
    state = load_state()
    markets_state = state.setdefault('markets', {})
    entry = markets_state.get(market, {})
    now = time.time()
    entry.setdefault('added_ts', now)
    entry['status'] = 'watching'
    entry['reason'] = reason or entry.get('reason', '')
    entry['source'] = source
    entry['mode'] = settings['mode']
    entry['last_review_ts'] = entry.get('last_review_ts', 0)
    if settings['mode'] == 'paper' or settings['paper_only']:
        if 'paper_entry_price' not in entry:
            entry['paper_entry_price'] = _fetch_market_price(market)
        entry['paper_last_price'] = entry.get('paper_entry_price')
    markets_state[market] = entry
    state['markets'] = markets_state
    save_state(state)
    if not already_listed:
        log(f"[WATCHLIST] Added {market} ({settings['mode']}) - {reason or 'no reason'}", level='info')
    else:
        log(f"[WATCHLIST] Refreshed {market} entry", level='debug')
    return True


def remove_from_watchlist(market: str, *, cfg: Optional[Dict[str, Any]] = None, reason: str = '') -> bool:
    cfg = cfg or _load_config()
    watchlist = list(cfg.get('WATCHLIST_MARKETS') or [])
    if market not in watchlist:
        return True
    watchlist = [m for m in watchlist if m != market]
    cfg['WATCHLIST_MARKETS'] = watchlist
    if not _write_config(cfg):
        return False
    state = load_state()
    entry = state.get('markets', {}).get(market)
    if entry:
        entry['status'] = 'removed'
        entry['removed_ts'] = time.time()
        if reason:
            entry['removed_reason'] = reason
        state['markets'][market] = entry
        save_state(state)
    log(f"[WATCHLIST] Removed {market} ({reason or 'no reason'})", level='info')
    return True


def demote_market_to_watchlist(market: str, *, reason: str = '') -> bool:
    cfg = _load_config()
    whitelist = list(cfg.get('WHITELIST_MARKETS') or [])
    if market in whitelist:
        whitelist = [m for m in whitelist if m != market]
        cfg['WHITELIST_MARKETS'] = whitelist
        if not _write_config(cfg):
            return False
        log(f"[WATCHLIST] Demoted {market} from whitelist -> watchlist ({reason or 'performance'})", level='warning')
    return queue_market_for_watchlist(market, reason=reason or 'demoted', source='ai-demotion', cfg=cfg)


def _compute_paper_performance(entry: Dict[str, Any]) -> Dict[str, float]:
    entry_price = entry.get('paper_entry_price')
    if not entry_price:
        return {'return_pct': 0.0}
    current = _fetch_market_price(entry.get('market'))
    if not current:
        return {'return_pct': 0.0}
    entry['paper_last_price'] = current
    try:
        pct = ((current - float(entry_price)) / float(entry_price)) * 100.0
    except Exception:
        pct = 0.0
    return {'return_pct': float(pct), 'current_price': float(current)}


def promote_watchlist_market(
    market: str,
    *,
    reason: str = 'watchlist promotion',
    cfg: Optional[Dict[str, Any]] = None,
    analytics_stats: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = cfg or _load_config()
    try:
        from modules.ai_markets import market_allowed_to_auto_apply, add_market_to_whitelist

        guard_ok = market_allowed_to_auto_apply(market, cfg, analytics_stats=analytics_stats)
    except Exception as exc:
        log(f"[WATCHLIST] Guardrail check failed for {market}: {exc}", level='warning')
        return False
    if not guard_ok:
        log(f"[WATCHLIST] Guardrails blocked promotion for {market}", level='warning')
        return False
    if not add_market_to_whitelist(market):
        log(f"[WATCHLIST] Failed to promote {market} into whitelist", level='error')
        return False
    remove_from_watchlist(market, cfg=cfg, reason='promoted')
    state = load_state()
    entry = state.get('markets', {}).get(market)
    if entry:
        entry['status'] = 'promoted'
        entry['promoted_ts'] = time.time()
        entry['promotion_reason'] = reason
        state['markets'][market] = entry
        save_state(state)
    log(f"[WATCHLIST] Promoted {market} to whitelist ({reason})", level='info')
    return True


def run_periodic_review(cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cfg = cfg or _load_config()
    settings = get_watchlist_settings(cfg)
    if not settings['enabled']:
        return []
    actions: List[Dict[str, Any]] = []
    try:
        from modules.performance_analytics import PerformanceAnalytics

        analytics = PerformanceAnalytics()
        stats = analytics.market_statistics(days=settings['review_window_days'])
    except Exception as exc:
        log(f"[WATCHLIST] Unable to load analytics: {exc}", level='warning')
        return []

    watchlist = list(cfg.get('WATCHLIST_MARKETS') or [])
    state = load_state()
    state.setdefault('markets', {})
    now = time.time()

    for market in watchlist:
        entry = state['markets'].get(market, {'market': market, 'added_ts': now})
        entry['market'] = market
        entry['last_review_ts'] = now
        entry.setdefault('mode', settings['mode'])
        metrics = stats.get(market)
        if metrics:
            entry['last_trades'] = metrics.get('trades', 0)
            entry['last_win_rate_pct'] = metrics.get('win_rate', 0.0)
            entry['last_avg_pnl'] = metrics.get('avg_pnl', 0.0)
        state['markets'][market] = entry

        if entry.get('mode') == 'paper' or settings['paper_only']:
            perf = _compute_paper_performance(entry)
            entry['paper_perf'] = perf
            state['markets'][market] = entry
            added = float(now - entry.get('added_ts', now))
            days_active = added / 86400
            if days_active >= settings['paper_min_days'] and perf.get('return_pct', 0.0) >= settings['paper_promotion_min_return_pct']:
                if promote_watchlist_market(market, reason='paper performance ok', cfg=cfg, analytics_stats=stats):
                    actions.append({'action': 'promoted', 'market': market, 'mode': 'paper', 'return_pct': perf.get('return_pct')})
                    continue
        else:
            if metrics and metrics.get('trades', 0) >= settings['promotion_min_trades']:
                if (
                    metrics.get('win_rate', 0.0) >= settings['promotion_min_win_rate_pct']
                    and metrics.get('avg_pnl', 0.0) >= settings['promotion_min_avg_pnl']
                ):
                    if promote_watchlist_market(market, reason='live performance ok', cfg=cfg, analytics_stats=stats):
                        actions.append({
                            'action': 'promoted',
                            'market': market,
                            'mode': 'micro',
                            'win_rate': metrics.get('win_rate'),
                            'avg_pnl': metrics.get('avg_pnl'),
                        })
                        continue

        # Drop watchlist entries that stagnate or underperform
        added_ts = entry.get('added_ts', now)
        days_active = (now - added_ts) / 86400
        loss_streak = int(entry.get('last_loss_streak', 0))
        if metrics:
            losses_est = (1.0 - (float(metrics.get('win_rate', 0.0)) / 100.0)) * float(metrics.get('trades', 0) or 0)
            loss_streak = max(loss_streak, int(round(losses_est)))
        should_drop = False
        if days_active >= settings['demote_after_days']:
            should_drop = True
        if metrics and metrics.get('trades', 0) >= settings['promotion_min_trades']:
            if metrics.get('win_rate', 100.0) <= settings['demote_max_win_rate_pct'] and metrics.get('avg_pnl', 1.0) <= settings['demote_max_avg_pnl']:
                should_drop = True
        if loss_streak >= settings['max_loss_streak']:
            should_drop = True
        if should_drop:
            remove_from_watchlist(market, cfg=cfg, reason='watchlist drop')
            actions.append({'action': 'dropped', 'market': market})

    # Review whitelist for demotions
    whitelist = list(cfg.get('WHITELIST_MARKETS') or [])
    for market in whitelist:
        metrics = stats.get(market)
        if not metrics:
            continue
        if metrics.get('trades', 0) < settings['demote_min_trades']:
            continue
        if (
            metrics.get('win_rate', 100.0) <= settings['demote_max_win_rate_pct']
            and metrics.get('avg_pnl', 1.0) <= settings['demote_max_avg_pnl']
        ):
            if demote_market_to_watchlist(market, reason='performance demotion'):
                actions.append({
                    'action': 'demoted',
                    'market': market,
                    'win_rate': metrics.get('win_rate'),
                    'avg_pnl': metrics.get('avg_pnl'),
                })

    state['last_review_ts'] = now
    save_state(state)
    if actions:
        log(f"[WATCHLIST] Review complete: {len(actions)} changes", level='info')
    return actions
