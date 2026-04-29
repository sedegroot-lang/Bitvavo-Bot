"""Signal scoring — entry signal strength calculation.

Initialise via ``init(config, ml_history)`` before calling.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, Optional, Tuple

import numpy as np

from modules.logging_utils import log
from bot.helpers import as_float, as_int
import bot.api as _api
from core.indicators import (
    close_prices, highs, lows, volumes,
    sma, ema, rsi, macd, bollinger_bands, stochastic,
)
from modules.signals import SignalContext, evaluate_signal_pack

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------
_cfg: dict = {}
_ml_signal_history: deque = deque(maxlen=100)
_ml_veto_alert_threshold: float = 0.8
_signal_cache: Dict[str, Tuple[Any, float]] = {}
_cache_ttl: int = 30


def init(config: dict, *, ml_history: Optional[deque] = None) -> None:
    global _cfg, _ml_signal_history
    _cfg = config
    if ml_history is not None:
        _ml_signal_history = ml_history


# ===================================================================
# Internal implementation
# ===================================================================

def _signal_strength_impl(m: str) -> Tuple[float, Any, Any, dict]:
    """Core signal scoring for a single market."""
    sma_short_period = as_int(_cfg.get('SMA_SHORT', 9), 9)
    sma_long_period = as_int(_cfg.get('SMA_LONG', 21), 21)
    macd_fast = as_int(_cfg.get('MACD_FAST', 12), 12)
    macd_slow = as_int(_cfg.get('MACD_SLOW', 26), 26)
    macd_signal_period = as_int(_cfg.get('MACD_SIGNAL', 9), 9)
    breakout_lookback = as_int(_cfg.get('BREAKOUT_LOOKBACK', 20), 20)
    min_avg_volume = as_float(_cfg.get('MIN_AVG_VOLUME_1M', 100), 100)
    rsi_min_buy = as_float(_cfg.get('RSI_MIN_BUY', 25), 25)
    rsi_max_buy = as_float(_cfg.get('RSI_MAX_BUY', 70), 70)

    c1 = _api.get_candles(m, '1m', 120)
    if not c1 or len(c1) < max(sma_long_period + 2, breakout_lookback + 2):
        return 0.0, None, None, {}

    p1 = close_prices(c1)

    # EARLY SPREAD CHECK
    if not _api.spread_ok(m):
        return 0.0, p1[-1] if p1 else None, None, {}

    s_short = sma(p1, sma_short_period)
    s_long = sma(p1, sma_long_period)
    r = rsi(p1, 14)
    m_line, m_sig, _ = macd(p1, macd_fast, macd_slow, macd_signal_period)
    ema_val = ema(p1, 20)
    bb_upper, bb_ma, bb_lower = bollinger_bands(p1, 20, 2)
    stoch_val = stochastic(p1, 14)

    v1 = volumes(c1)
    avg_vol = float(np.mean(v1[-60:])) if v1 and len(v1) >= 60 else 0.0

    # === ENSEMBLE ML Integration ===
    ml_boost = 0.0
    ml_signal = 0
    ml_conf = 0.0
    try:
        from modules.ml import predict_ensemble, prepare_lstm_sequence, feature_engineering
        # Build 7-feature array matching the XGBoost model (rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k)
        _sma_s = float(s_short[-1] if s_short is not None and hasattr(s_short, '__getitem__') else (s_short if s_short is not None else p1[-1]))
        _sma_l = float(s_long[-1] if s_long is not None and hasattr(s_long, '__getitem__') else (s_long if s_long is not None else p1[-1]))
        _bb_u = float(bb_upper[-1] if bb_upper is not None and hasattr(bb_upper, '__getitem__') else (bb_upper if bb_upper is not None else p1[-1] * 1.02))
        _bb_l = float(bb_lower[-1] if bb_lower is not None and hasattr(bb_lower, '__getitem__') else (bb_lower if bb_lower is not None else p1[-1] * 0.98))
        _bb_range = _bb_u - _bb_l
        _bb_pos = ((p1[-1] - _bb_l) / _bb_range) if _bb_range > 0 else 0.5
        features = feature_engineering({
            'rsi': float(r if r is not None else 50.0),
            'macd': float((m_line - m_sig) if (m_line is not None and m_sig is not None) else 0.0),
            'sma_short': _sma_s,
            'sma_long': _sma_l,
            'volume': float(v1[-1] if v1 and len(v1) > 0 else 0.0),
            'bb_position': float(max(0.0, min(1.0, _bb_pos))),
            'stochastic_k': float(stoch_val if stoch_val is not None else 50.0),
        })
        features_dict = {
            'rsi': float(r if r is not None else 50.0),
            'macd': float((m_line - m_sig) if (m_line is not None and m_sig is not None) else 0.0),
        }
        lstm_sequence = prepare_lstm_sequence(c1, features_dict, lookback_window=60)
        result = predict_ensemble(features, market_data=None, price_sequence=lstm_sequence)
        ml_signal = result.get('signal', 0)
        ml_conf = result.get('confidence', 0.0)

        _ml_signal_history.append(ml_signal)
        if len(_ml_signal_history) >= 100:
            hold_count = sum(1 for s in _ml_signal_history if s == 0)
            hold_pct = hold_count / len(_ml_signal_history)
            if hold_pct >= _ml_veto_alert_threshold:
                log(f"[ML ALERT] High HOLD frequency: {hold_pct*100:.1f}% ({hold_count}/100) - Model retrain recommended", level='warning')

        log(f"[Ensemble] {m}: signal={ml_signal} (conf={ml_conf:.2f}, xgb={result.get('xgb_signal')}, lstm={result.get('lstm_prediction')})", level='info')
        if ml_signal == 1:
            ml_boost = 2.5 + (ml_conf * 1.0)
        elif ml_signal == 0:
            # Soft fallback: when ML is neutral/HOLD, don't penalize
            # Give small positive boost if base technicals are strong
            ml_boost = 0.0
    except Exception as e:
        log(f"ML prediction failed for {m}: {e}", level='debug')
        ml_boost = 0.0

    # === HIGHER TIMEFRAME TREND CONFIRMATION ===
    trend_1m = (s_short is not None and p1[-1] > s_short)
    trend_5m_bullish = False
    trend_5m_strong = False
    try:
        if _cfg.get('HTF_TREND_FILTER_ENABLED', True):
            c5m = _api.get_candles(m, '5m', 40)
            if c5m and len(c5m) >= 20:
                p5m = close_prices(c5m)
                sma_5m_short = sma(p5m, 9)
                sma_5m_long = sma(p5m, 21)
                rsi_5m = rsi(p5m, 14)
                if sma_5m_short is not None and sma_5m_long is not None:
                    trend_5m_bullish = p5m[-1] > sma_5m_short and sma_5m_short > sma_5m_long
                    trend_5m_strong = trend_5m_bullish and (rsi_5m is not None and 40 < rsi_5m < 70)
                elif sma_5m_short is not None:
                    trend_5m_bullish = p5m[-1] > sma_5m_short
            else:
                trend_5m_bullish = True
        else:
            trend_5m_bullish = True
    except Exception:
        trend_5m_bullish = True

    if not trend_5m_bullish:
        if _cfg.get('SIGNALS_DEBUG_LOGGING'):
            log(f"[entry] {m} WARNING: 5m trend bearish (price below 5m SMA) - score penalty applied", level='debug')

    h1 = highs(c1)
    l1 = lows(c1)
    breakout = False
    if h1 and len(h1) >= breakout_lookback:
        breakout = p1[-1] > max(h1[-breakout_lookback:-1])

    # === VOLUME FILTER ===
    if avg_vol < min_avg_volume and not trend_1m:
        if _cfg.get('SIGNALS_DEBUG_LOGGING'):
            log(f"[entry] {m} BLOCKED: avg_vol={avg_vol:.1f} (min={min_avg_volume}), no trend", level='debug')
        return 0.0, p1[-1], s_short, {}

    # === RSI MOMENTUM BONUS ===
    rsi_momentum_bonus = 0.0
    if r is not None:
        if 30 <= r <= 45:
            rsi_momentum_bonus = 1.5
        elif 45 < r <= 55:
            rsi_momentum_bonus = 0.5

    sw = _cfg.get('SIGNAL_WEIGHTS') or {}
    signals = {
        'sma_cross': (s_short is not None and s_long is not None and s_short > s_long, float(sw.get('sma_cross', 1.5))),
        'price_above_sma': (s_short is not None and p1[-1] > s_short, float(sw.get('price_above_sma', 1.0))),
        'rsi_ok': (r is not None and r < rsi_max_buy, float(sw.get('rsi_ok', 1.0))),
        'macd_ok': (m_line is not None and m_sig is not None and m_line > m_sig, float(sw.get('macd_ok', 1.2))),
        'ema_ok': (ema_val is not None and p1[-1] > ema_val, float(sw.get('ema_ok', 1.0))),
        'bb_breakout': (bb_upper is not None and p1[-1] > p1[-2] * 1.01, float(sw.get('bb_breakout', 1.2))),
        'stoch_ok': (stoch_val is not None and stoch_val < 80, float(sw.get('stoch_ok', 0.8))),
        'trend_1m': (trend_1m, float(sw.get('trend_1m', 1.2))),
        'trend_5m': (trend_5m_bullish, float(sw.get('trend_5m', 1.8))),
        'trend_5m_strong': (trend_5m_strong, float(sw.get('trend_5m_strong', 1.2))),
        'breakout': (breakout, float(sw.get('breakout', 1.2))),
        'vol_above_avg': (avg_vol > min_avg_volume * 1.5, float(sw.get('vol_above_avg', 0.7))),
        'rsi_momentum': (rsi_momentum_bonus > 0, rsi_momentum_bonus),
    }
    score = sum(weight for (cond, weight) in signals.values() if cond)

    # Apply Bayesian adaptive weights to classic signals
    if _cfg.get('BAYESIAN_FUSION_ENABLED', True):
        try:
            from core.bayesian_fusion import get_signal_weight
            bayesian_adj = 0.0
            for name, (cond, weight) in signals.items():
                if cond:
                    bw = get_signal_weight(name, default=1.0)
                    bayesian_adj += weight * (bw - 1.0)
            score += bayesian_adj
        except Exception:
            pass

    if _cfg.get('SIGNALS_DEBUG_LOGGING'):
        triggered = [name for name, (cond, _) in signals.items() if cond]
        log(f"[signals] {m} base_score={score:.2f} triggered={triggered}", level='debug')

    # Evaluate advanced signal pack
    advanced_score = 0.0
    try:
        signal_ctx = SignalContext(
            market=m, candles_1m=c1, closes_1m=p1,
            highs_1m=h1, lows_1m=l1, volumes_1m=v1, config=_cfg,
        )
        pack = evaluate_signal_pack(signal_ctx)
        weight = float(_cfg.get('SIGNALS_GLOBAL_WEIGHT', 1.0) or 1.0)
        advanced_score = pack.total_score * weight
        if _cfg.get('SIGNALS_DEBUG_LOGGING'):
            log(f"[signals] {m} pack={pack.as_dict()}", level='debug')
    except Exception as signal_exc:
        log(f"Advanced signal pack failed for {m}: {signal_exc}", level='debug')

    ml_weight = 1.5 if ml_boost > 0 else 0.0
    score_before_ml = score + advanced_score
    score += (ml_boost * ml_weight) + advanced_score

    try:
        if r is not None:
            if r < rsi_min_buy:
                score -= 2.0
            elif r > rsi_max_buy:
                score -= 1.5  # Reduced from -3.0; RSI_MAX_BUY already filters
    except Exception as e:
        log(f"if r is not None: failed: {e}", level='error')

    price_now = p1[-1]
    ml_info = {
        'ml_signal': ml_signal, 'ml_confidence': ml_conf,
        'score_before_ml': score_before_ml, 'ml_boost': ml_boost,
        'ml_weight': ml_weight,
        # Indicator values for AI training metadata (computed above, free to expose)
        'rsi': round(float(r), 2) if r is not None else None,
        'macd_line': round(float(m_line), 6) if m_line is not None else None,
        'macd_signal': round(float(m_sig), 6) if m_sig is not None else None,
        'macd_histogram': round(float(m_line - m_sig), 6) if (m_line is not None and m_sig is not None) else None,
        'sma_short': round(float(s_short), 6) if s_short is not None else None,
        'sma_long': round(float(s_long), 6) if s_long is not None else None,
        'ema20': round(float(ema_val), 6) if ema_val is not None else None,
        'stochastic': round(float(stoch_val), 2) if stoch_val is not None else None,
        'bb_upper': round(float(bb_upper), 6) if bb_upper is not None else None,
        'bb_lower': round(float(bb_lower), 6) if bb_lower is not None else None,
        'avg_volume': round(float(avg_vol), 2) if avg_vol else None,
    }

    # === Entry Confidence (6-pillar) — passive logging unless gating enabled ===
    try:
        from bot.entry_confidence import compute_entry_confidence, min_confidence_threshold
        regime_hint = "neutral"
        try:
            from bot.shared import state as _shared_state
            if hasattr(_shared_state, "regime_engine") and _shared_state.regime_engine:
                regime_hint = str(getattr(_shared_state.regime_engine, "current_regime", "neutral") or "neutral").lower()
        except Exception:
            pass
        # Build correlations input from currently open trades (best-effort)
        open_market_closes = None
        try:
            from bot.shared import state as _ss
            if hasattr(_ss, "open_trades") and _ss.open_trades:
                # Collect last 60 closes per other open market from cache only — no extra API calls.
                # Caller can enrich; keep this lightweight.
                open_market_closes = {}
        except Exception:
            open_market_closes = None
        ec = compute_entry_confidence(
            closes_1m=p1, highs_1m=h1, lows_1m=l1, volumes_1m=v1,
            ml_info=ml_info, regime=regime_hint,
            open_market_closes=open_market_closes,
            min_threshold=min_confidence_threshold(_cfg),
        )
        ml_info['entry_confidence'] = ec.confidence
        ml_info['entry_pillars'] = ec.pillars
        ml_info['entry_confidence_passed'] = ec.passed
        ml_info['entry_weakest_pillar'] = ec.weakest_pillar
        if _cfg.get('SIGNALS_DEBUG_LOGGING'):
            log(f"[entry_conf] {m} conf={ec.confidence:.3f} weakest={ec.weakest_pillar} pillars={ec.pillars}", level='debug')
    except Exception as ec_exc:
        log(f"[entry_conf] failed for {m}: {ec_exc}", level='debug')

    return float(score), price_now, s_short, ml_info


# ===================================================================
# Public API — with timeout + cache
# ===================================================================

def signal_strength(m: str) -> Tuple[float, Any, Any, dict]:
    """Compute entry signal score with 8 s timeout guard."""
    cache_key = f"signal_{m}"
    now = time.time()
    if cache_key in _signal_cache:
        cached_val, cached_ts = _signal_cache[cache_key]
        if now - cached_ts < _cache_ttl:
            return cached_val

    result_container: list = [None]
    exception_container: list = [None]

    def _run() -> None:
        try:
            result_container[0] = _signal_strength_impl(m)
        except Exception as exc:
            exception_container[0] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=15.0)

    if thread.is_alive():
        log(f"[TIMEOUT] signal_strength({m}) exceeded 15s limit", level='warning')
        return 0.0, None, None, {}

    if exception_container[0]:
        log(f"[ERROR] signal_strength({m}): {exception_container[0]}", level='error')
        return 0.0, None, None, {}

    result = result_container[0] or (0.0, None, None, {})
    _signal_cache[cache_key] = (result, now)

    if len(_signal_cache) > 100:
        oldest = sorted(_signal_cache.items(), key=lambda x: x[1][1])[:50]
        for k, _ in oldest:
            _signal_cache.pop(k, None)

    return result
