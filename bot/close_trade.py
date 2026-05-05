"""bot.close_trade — Unified close-trade finalization sequence.

Extracted from `trailing_bot.py` (#066 batch 2). Handles archive → append →
record stats → remove → save bookkeeping that was copy-pasted 7× through the
codebase. All globals accessed via `bot.shared.state`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from bot.shared import state

_OPERATIONAL_REASONS = {"saldo_error", "sync_removed", "manual_close", "reconstructed", "dust_cleanup"}


def finalize_close_trade(
    market: str,
    trade: Dict[str, Any],
    closed_entry: Dict[str, Any],
    *,
    update_market_profits: bool = False,
    profit_for_market: Optional[float] = None,
    do_save: bool = True,
    do_cleanup: bool = True,
) -> None:
    """Unified close-trade sequence: archive → append → record stats → remove → save."""
    cfg = state.CONFIG
    open_trades = state.open_trades
    closed_trades = state.closed_trades
    market_profits = state.market_profits

    # Compute max_profit_pct from trade price tracking
    if trade and not closed_entry.get("max_profit_pct"):
        _hp = trade.get("highest_price", 0)
        _bp = trade.get("buy_price", 0)
        if _hp and _bp and _hp > 0 and _bp > 0:
            closed_entry["max_profit_pct"] = round((_hp - _bp) / _bp * 100, 2)

    # Carry forward useful metadata from open trade
    for _meta_key in (
        "score",
        "rsi_at_entry",
        "volume_24h_eur",
        "volatility_at_entry",
        "opened_regime",
        "macd_at_entry",
        "sma_short_at_entry",
        "sma_long_at_entry",
        "dca_buys",
        "tp_levels_done",
        "highest_price",
        "trailing_activation_pct",
        "base_trailing_pct",
    ):
        if _meta_key not in closed_entry and trade and _meta_key in trade:
            closed_entry[_meta_key] = trade[_meta_key]

    try:
        state.archive_trade(**closed_entry)
    except Exception:
        pass

    try:
        closed_trades.append(closed_entry)
    except Exception:
        pass

    try:
        state._record_market_stats_for_close(market, closed_entry, trade)
    except Exception:
        pass

    if update_market_profits:
        try:
            p = profit_for_market if profit_for_market is not None else closed_entry.get("profit", 0.0)
            market_profits[market] = market_profits.get(market, 0.0) + float(p or 0)
        except Exception:
            pass

    _reason = (closed_entry.get("reason") or "").lower()
    _has_profit = closed_entry.get("profit") is not None
    _is_signal = _reason not in _OPERATIONAL_REASONS and _has_profit

    # Per-market empirical-Bayes expectancy update
    if _is_signal:
        try:
            from core.market_expectancy import market_ev as _mev

            _mev.record_trade(market, float(closed_entry.get("profit", 0) or 0))
        except Exception:
            pass

        # Post-loss per-market cooldown
        try:
            from bot.post_loss_cooldown import get_instance as _get_pl

            _root = getattr(state, "PROJECT_ROOT", None) or Path(__file__).resolve().parent.parent
            _pl = _get_pl(Path(_root) / "data" / "post_loss_cooldown.json")
            _pl.record_close(market, float(closed_entry.get("profit", 0) or 0))
        except Exception:
            pass

        # Adaptive MIN_SCORE rolling buffer
        try:
            from bot.adaptive_score import get_instance as _get_adapt

            _get_adapt().record_close(float(closed_entry.get("profit", 0) or 0))
        except Exception:
            pass

    # Bayesian Signal Fusion
    try:
        if cfg.get("BAYESIAN_FUSION_ENABLED", True):
            from core.bayesian_fusion import update_from_trade_result

            _active_sigs = {
                sn: True
                for sn in (
                    "sma_cross",
                    "price_above_sma",
                    "rsi_ok",
                    "macd_ok",
                    "ema_ok",
                    "bb_breakout",
                    "stoch_ok",
                    "trend_1m",
                    "trend_5m",
                    "trend_5m_strong",
                    "breakout",
                    "vol_above_avg",
                    "rsi_momentum",
                )
            }
            update_from_trade_result(_active_sigs, float(closed_entry.get("profit", 0) or 0))
    except Exception:
        pass

    # Meta-Learner
    try:
        if cfg.get("META_LEARNER_ENABLED", True):
            from core.meta_learner import MetaLearner

            _ml = MetaLearner.load()
            _rsi_entry = trade.get("rsi_at_entry") if trade else None
            _sma_cross = (
                trade
                and trade.get("sma_short_at_entry")
                and trade.get("sma_long_at_entry")
                and float(trade.get("sma_short_at_entry", 0) or 0) > float(trade.get("sma_long_at_entry", 0) or 0)
            )
            _strategy = _ml.classify_trade(rsi=_rsi_entry, sma_cross=_sma_cross)
            _ml.record_outcome(_strategy, float(closed_entry.get("profit", 0) or 0))
            _ml.update_weights()
            _ml.save()
    except Exception:
        pass

    if market in open_trades:
        try:
            del open_trades[market]
        except Exception:
            pass

    # Clear entry-metadata cache for this market (trade is closed).
    try:
        from core import entry_metadata as _em

        _em.clear(market)
    except Exception:
        pass

    if do_save:
        try:
            fn = getattr(state, "save_trades_fn", None)
            if callable(fn):
                fn()
        except Exception:
            pass

    if do_cleanup:
        try:
            state.cleanup_trades()
        except Exception:
            pass

    # Signal Publisher
    try:
        from modules import signal_publisher as _sp

        if _sp is not None:
            _bp = float(closed_entry.get("buy_price", 0) or 0)
            _sp_price = float(closed_entry.get("sell_price", 0) or 0)
            _profit = float(closed_entry.get("profit", 0) or 0)
            _pct = ((_sp_price - _bp) / _bp * 100) if _bp > 0 else 0.0
            _hold_h = None
            if trade and trade.get("opened_ts"):
                try:
                    _hold_h = (time.time() - float(trade["opened_ts"])) / 3600
                except Exception:
                    _hold_h = None
            _sp.publish_sell(
                market,
                _bp,
                _sp_price,
                _profit,
                _pct,
                reason=closed_entry.get("reason", "unknown"),
                hold_time_hours=_hold_h,
                dca_count=int(closed_entry.get("dca_buys", 0) or 0),
            )
    except Exception:
        pass
