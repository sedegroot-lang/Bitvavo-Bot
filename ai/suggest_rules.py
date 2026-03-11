"""ai.suggest_rules â€“ Grouped suggestion rules extracted from suggest_once().

Each public function takes a RuleContext dict and returns a list of suggestion
dicts to append to the output. This keeps suggest_once() as a thin orchestrator.

Usage (inside ai_supervisor.suggest_once):
    from ai.suggest_rules import (
        rules_basic_performance, rules_signal_optimization,
        rules_profit_factor, rules_advanced_optimization,
        rules_market_intelligence, rules_dynamic_learning,
    )
    ctx = { ... }
    out.extend(rules_basic_performance(ctx))
    ...
"""

from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List

from modules.logging_utils import log
from ai.market_analysis import (
    detect_market_regime,
    get_coin_statistics,
    calculate_risk_metrics,
    calculate_portfolio_sectors,
    scan_all_markets_for_opportunities,
)

# ---------------------------------------------------------------------------
# Type alias for rule context
# ---------------------------------------------------------------------------
RuleCtx = Dict[str, Any]
Suggestion = Dict[str, Any]

# Trade-count gates for rule activation.
# Lowered from 20/25/30 for micro-accounts that may take weeks to accumulate trades.
_GATE_LOW = 8       # was 20 â€” basic rules (trailing, DCA, TP, etc.)
_GATE_MED = 12      # was 25 â€” advanced rules (correlation, DCA spacing, vol)
_GATE_HIGH = 15     # was 30 â€” expert rules (score learning, whitelist mgmt)

# Needed references â€” injected once from ai_supervisor at import time
_bounded_step = None
_cooldown_ok = None
_last_suggest: dict = {}
_utc_now = None
_dbg = None
LIMITS: dict = {}

# Computation cache — expensive calls computed ONCE per suggest cycle
_cache: Dict[str, Any] = {}


def init(*, bounded_step, cooldown_ok, last_suggest, utc_now, dbg, limits):
    """Inject references to ai_supervisor helpers (called once at suggest_once start)."""
    global _bounded_step, _cooldown_ok, _last_suggest, _utc_now, _dbg, LIMITS, _cache
    _bounded_step = bounded_step
    _cooldown_ok = cooldown_ok
    _last_suggest = last_suggest
    _utc_now = utc_now
    _dbg = dbg
    LIMITS = limits
    _cache = {}  # Clear cache each cycle


def _min_sl_for_dca(cfg: dict) -> float:
    """Compute minimum HARD_SL_ALT_PCT so ALL DCA levels can fire.

    Formula: deepest_dca_step = DCA_DROP_PCT * DCA_STEP_MULTIPLIER^(DCA_MAX_BUYS-1)
    SL must be wider than that + 2% safety margin.
    """
    dca_drop = float(cfg.get('DCA_DROP_PCT', 0.06))
    step_mult = float(cfg.get('DCA_STEP_MULTIPLIER', 1.4))
    max_buys = int(cfg.get('DCA_MAX_BUYS', 3))
    if max_buys < 1:
        max_buys = 1
    deepest_step = dca_drop * (step_mult ** (max_buys - 1))
    return min(0.25, deepest_step + 0.02)  # cap at 25% absolute max


def _cached_regime(closed_trades, cfg) -> dict:
    """detect_market_regime — cached per cycle (was called 3x)."""
    if 'regime' not in _cache:
        _cache['regime'] = detect_market_regime(closed_trades, cfg)
    return _cache['regime']


def _cached_risk(closed_trades, cfg) -> dict:
    """calculate_risk_metrics — cached per cycle (was called 3x)."""
    if 'risk' not in _cache:
        _cache['risk'] = calculate_risk_metrics(closed_trades, cfg)
    return _cache['risk']


# ===================================================================
# Helper
# ===================================================================

def _suggest(param, current, target, reason, *, check_duplicate=True, extras=None):
    """Build a suggestion dict if bounded_step and cooldown allow it."""
    new_val = _bounded_step(param, current, target, check_duplicate=check_duplicate)
    if new_val is not None and _cooldown_ok(param):
        s = {'param': param, 'from': current, 'to': new_val, 'reason': reason}
        if extras:
            s.update(extras)
        _last_suggest[param] = _utc_now()
        return s
    return None


def _suggest_int(param, current, target, reason, **kw):
    s = _suggest(param, current, target, reason, **kw)
    if s is not None:
        s['to'] = int(s['to'])
    return s


# ===================================================================
# GROUP A â€” Basic performance rules (Rules 1-6)
# ===================================================================

def rules_basic_performance(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 1-6: trailing, RSI, base amount, DCA, stop-loss adjustments."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl = ctx['pnl']
    pnl_list = ctx['pnl_list']
    open_exposure = ctx['open_exposure']
    max_total = ctx['max_total']
    open_trades = ctx['open_trades']

    # Rule 1: loss + high exposure â†’ tighter trailing
    if pnl < 0 and open_exposure > 0.5 * max_total:
        s = _suggest('DEFAULT_TRAILING', float(cfg.get('DEFAULT_TRAILING', 0.012)),
                      float(cfg.get('DEFAULT_TRAILING', 0.012)) + 0.002, 'loss+high exposure')
        if s:
            out.append(s)

    # Rule 2: profit + low exposure â†’ faster trailing activation
    if pnl > 0 and open_exposure < 0.3 * max_total:
        current = float(cfg.get('TRAILING_ACTIVATION_PCT', 0.025))
        s = _suggest('TRAILING_ACTIVATION_PCT', current, max(0.01, current - 0.003), 'profit+low exposure')
        if s:
            out.append(s)

    # Rule 3: many open trades â†’ stricter RSI
    if open_trades >= max(2, int(cfg.get('MAX_OPEN_TRADES', 3) * 0.8)):
        current = int(cfg.get('RSI_MIN_BUY', 30))
        s = _suggest_int('RSI_MIN_BUY', current, current + 2, 'many open trades')
        if s:
            out.append(s)

    # Rule 4: base amount adjustment
    if pnl < 0:
        current = float(cfg.get('BASE_AMOUNT_EUR', 15))
        s = _suggest('BASE_AMOUNT_EUR', current, max(5.0, current - 2.0), 'recent losses')
        if s:
            out.append(s)
    elif pnl > 0 and open_trades <= 1:
        current = float(cfg.get('BASE_AMOUNT_EUR', 15))
        s = _suggest('BASE_AMOUNT_EUR', current, min(100.0, current + 2.0), 'recent profits')
        if s:
            out.append(s)

    # Rule 5: DCA_MAX_BUYS reduction on big losses
    if pnl < -20:
        current = int(cfg.get('DCA_MAX_BUYS', 3))
        s = _suggest_int('DCA_MAX_BUYS', current, max(2, current - 1), 'high losses: reduce DCA exposure')
        if s:
            out.append(s)

    # Rule 6: HARD_SL on high loss rate + DCA_AMOUNT_EUR adjustment
    if len(pnl_list) >= 10:
        recent_losses = [p for p in pnl_list[-10:] if p < 0]
        if len(recent_losses) >= 5:
            current = float(cfg.get('HARD_SL_ALT_PCT', 0.03))
            s = _suggest('HARD_SL_ALT_PCT', current, max(0.025, current - 0.005),
                          'high loss rate: tighten stop-loss')
            if s:
                out.append(s)

        # DCA_AMOUNT_EUR dynamic sizing
        try:
            current_dca = float(cfg.get('DCA_AMOUNT_EUR', cfg.get('BASE_AMOUNT_EUR', 10)))
            target = None
            if pnl < -50:
                target = max(1.0, current_dca * 0.75)
            elif pnl > 50 and open_exposure < 0.3 * max_total:
                target = min(200.0, current_dca * 1.1)
            if target is not None:
                s = _suggest('DCA_AMOUNT_EUR', current_dca, float(target),
                              'adjust DCA size based on recent pnl/exposure')
                if s:
                    out.append(s)
        except Exception as e:
            _dbg(f"DCA_AMOUNT_EUR rule failed: {e}")

    return out


# ===================================================================
# GROUP B â€” Signal / score optimization (Rules 7-10)
# ===================================================================

def rules_signal_optimization(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 7-10: MIN_SCORE_TO_BUY, MAX_OPEN_TRADES, RSI_MAX_BUY, DCA_DROP_PCT."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    analytics_data = ctx.get('analytics_data', {})
    open_trades = ctx['open_trades']

    win_rate = 0.5
    profit_factor = 1.0

    # Rule 7: MIN_SCORE_TO_BUY â€” analytics-based
    if analytics_data:
        win_rate = analytics_data.get('win_rate', 50.0) / 100.0
        profit_factor = analytics_data.get('profit_factor', 1.0)
        sharpe = analytics_data.get('sharpe', 0.0)

        if sharpe < -2.0 and profit_factor < 0.5 and len(pnl_list) >= 15:
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, min(3.5, current + 0.25),
                          f'Poor Sharpe={sharpe:.2f}: slightly stricter (max 3.5)',
                          extras={'impact': 'MEDIUM'})
            if s:
                out.append(s)
        elif win_rate > 0.55 and profit_factor > 1.2:
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, max(1.5, current - 0.25),
                          f'Good WR={win_rate:.1%}, PF={profit_factor:.2f}: allow more entries')
            if s:
                out.append(s)

    # Rule 7 fallback: manual calculation
    if len(pnl_list) >= 10:
        if not analytics_data:
            win_rate = sum(1 for p in pnl_list[-10:] if p > 0) / len(pnl_list[-10:])
            winners = [p for p in pnl_list[-20:] if p > 0]
            losers = [p for p in pnl_list[-20:] if p < 0]
            avg_win = sum(winners) / len(winners) if winners else 0
            avg_loss = abs(sum(losers) / len(losers)) if losers else 1
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 1.0

        if profit_factor < 0.5 and len(pnl_list) >= 15:
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, min(3.5, current + 0.25),
                          f'Low PF {profit_factor:.2f}: slightly stricter (capped at 3.5)')
            if s:
                out.append(s)
        elif win_rate < 0.4 and not analytics_data:
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, min(3.0, current + 0.25),
                          f'Low WR ({win_rate:.1%}): slightly stricter')
            if s:
                out.append(s)
        elif win_rate > 0.55 and profit_factor > 1.0:
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, max(1.5, current - 0.25),
                          f'high win rate ({win_rate:.1%}) + good PF ({profit_factor:.2f}): allow more entries')
            if s:
                out.append(s)

    # Rule 8: MAX_OPEN_TRADES
    if len(pnl_list) >= _GATE_LOW:
        avg_ppt = sum(pnl_list[-20:]) / 20
        if avg_ppt > 2.0:
            current = int(cfg.get('MAX_OPEN_TRADES', 3))
            s = _suggest_int('MAX_OPEN_TRADES', current, min(5, current + 1),
                              f'good avg profit ({avg_ppt:.2f} EUR): increase capacity')
            if s:
                out.append(s)
        elif avg_ppt < -1.0:
            current = int(cfg.get('MAX_OPEN_TRADES', 3))
            s = _suggest_int('MAX_OPEN_TRADES', current, max(3, current - 1),
                              f'negative avg profit ({avg_ppt:.2f} EUR): reduce exposure')
            if s:
                out.append(s)

    # Rule 9: RSI_MAX_BUY
    if win_rate < 0.45 and len(pnl_list) >= 10:
        current = int(cfg.get('RSI_MAX_BUY', 50))
        s = _suggest_int('RSI_MAX_BUY', current, max(45, current - 5),
                          'low win rate: avoid overbought entries')
        if s:
            out.append(s)

    # Rule 10: DCA_DROP_PCT
    if len(pnl_list) >= 10:
        volatility = sum(1 for p in pnl_list[-10:] if abs(p) > 5) / 10
        if volatility > 0.5:
            current = float(cfg.get('DCA_DROP_PCT', 0.04))
            s = _suggest('DCA_DROP_PCT', current, min(0.06, current + 0.01),
                          f'high volatility ({volatility:.0%}): wider DCA spacing')
            if s:
                out.append(s)

    # Store computed win_rate in context for downstream rules
    ctx['win_rate'] = win_rate
    ctx['profit_factor'] = profit_factor
    return out


# ===================================================================
# GROUP C â€” Profit factor response (Rules 11-15)
# ===================================================================

def rules_profit_factor(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 11-15: comprehensive PF response, hard SL, exposure, balance, DCA alignment."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    win_rate = ctx.get('win_rate', 0.5)

    # Rule 11: Comprehensive Profit Factor Response
    if len(pnl_list) >= 15:
        winners = [p for p in pnl_list[-20:] if p > 0]
        losers = [p for p in pnl_list[-20:] if p < 0]
        avg_win = sum(winners) / len(winners) if winners else 0
        avg_loss = abs(sum(losers) / len(losers)) if losers else 1
        pf = avg_win / avg_loss if avg_loss > 0 else 0

        ct = float(cfg.get('DEFAULT_TRAILING', 0.035))
        cms = float(cfg.get('MIN_SCORE_TO_BUY', 10))
        csl = float(cfg.get('HARD_SL_ALT_PCT', 0.05))
        cba = float(cfg.get('BASE_AMOUNT_EUR', 15))

        if pf < 0.5:  # CRITICAL
            s = _suggest('DEFAULT_TRAILING', ct, min(0.09, max(0.07, ct + 0.02)),
                          f'ðŸš¨ CRITICAL PF={pf:.2f}: need MUCH bigger wins',
                          check_duplicate=False, extras={'impact': 'CRITICAL', 'profit_factor': pf})
            if s:
                out.append(s)
            s = _suggest('HARD_SL_ALT_PCT', csl, max(0.02, csl - 0.015),
                          f'ðŸš¨ CRITICAL PF={pf:.2f}: tighten stop loss',
                          check_duplicate=False, extras={'impact': 'CRITICAL', 'profit_factor': pf})
            if s:
                out.append(s)
            s = _suggest('BASE_AMOUNT_EUR', cba, max(5, cba * 0.6),
                          f'ðŸš¨ CRITICAL PF={pf:.2f}: reduce position size',
                          check_duplicate=False, extras={'impact': 'CRITICAL', 'profit_factor': pf})
            if s:
                out.append(s)
        elif pf < 0.8:  # POOR
            s = _suggest('DEFAULT_TRAILING', ct, min(0.06, ct + 0.01),
                          f'âš ï¸ Poor PF={pf:.2f}: increase trailing for better wins',
                          extras={'impact': 'HIGH', 'profit_factor': pf})
            if s:
                out.append(s)
            if cms < 9.5:
                s = _suggest('MIN_SCORE_TO_BUY', cms, min(10, cms + 0.5),
                              f'âš ï¸ Poor PF={pf:.2f}: raise entry standards',
                              extras={'impact': 'HIGH', 'profit_factor': pf})
                if s:
                    out.append(s)
        elif pf < 1.0 and avg_win < avg_loss:  # WEAK
            s = _suggest('DEFAULT_TRAILING', ct, min(0.05, ct + 0.007),
                          f'Weak PF={pf:.2f}: slightly larger trailing')
            if s:
                out.append(s)
        elif 1.0 <= pf < 1.5:  # GOOD
            log(f"ðŸ“Š Profit Factor {pf:.2f}: Good - maintaining current settings", level='info')
        elif 1.5 <= pf < 2.0:  # EXCELLENT
            if cms > 8:
                s = _suggest('MIN_SCORE_TO_BUY', cms, max(7.5, cms - 0.5),
                              f'âœ… Excellent PF={pf:.2f}: can lower entry barrier')
                if s:
                    out.append(s)
        elif pf > 2.0 and avg_win > avg_loss * 1.8:  # OUTSTANDING
            s = _suggest('DEFAULT_TRAILING', ct, max(0.025, ct - 0.005),
                          f'ðŸ† Outstanding PF={pf:.2f}: take profits sooner')
            if s:
                out.append(s)
            if cba < 25:
                s = _suggest('BASE_AMOUNT_EUR', cba, min(25, cba * 1.2),
                              f'ðŸ† Outstanding PF={pf:.2f}: can increase position size')
                if s:
                    out.append(s)

    # Rule 12: HARD_SL based on avg loss size
    if len(pnl_list) >= 15:
        losers = [abs(p) for p in pnl_list[-20:] if p < 0]
        if losers:
            avg_loss = sum(losers) / len(losers)
            csl = float(cfg.get('HARD_SL_ALT_PCT', 0.05))
            if avg_loss > 1.5:
                s = _suggest('HARD_SL_ALT_PCT', csl, max(0.025, csl - 0.01),
                              f'avg loss â‚¬{avg_loss:.2f} too high: tighten stop loss')
                if s:
                    out.append(s)
            elif avg_loss < 0.5 and len(losers) >= 10:
                s = _suggest('HARD_SL_ALT_PCT', csl, min(0.06, csl + 0.005),
                              f'avg loss â‚¬{avg_loss:.2f} acceptable: allow more room')
                if s:
                    out.append(s)

    # Rule 13: MAX_TOTAL_EXPOSURE — DISABLED, managed manually
    # No AI adjustment of MAX_TOTAL_EXPOSURE_EUR allowed.
    # Budget reservation system enforces separate budgets:
    #   - Grid bot: 120 EUR + reinvested grid profits
    #   - Trailing bot: 180 EUR + reinvested trailing profits
    # See BUDGET_RESERVATION in bot_config.json

    # Rule 14: AUTO_USE_FULL_BALANCE safety
    if len(pnl_list) >= 10:
        if cfg.get('AUTO_USE_FULL_BALANCE', False):
            base = float(cfg.get('BASE_AMOUNT_EUR', 15))
            if base < 20 and _cooldown_ok('AUTO_USE_FULL_BALANCE'):
                out.append({'param': 'AUTO_USE_FULL_BALANCE', 'from': True, 'to': False,
                            'reason': f'BASE_AMOUNT is â‚¬{base}, prevent oversized trades'})
                _last_suggest['AUTO_USE_FULL_BALANCE'] = _utc_now()

    # Rule 15: DCA_AMOUNT_EUR alignment
    if len(pnl_list) >= 10:
        base = float(cfg.get('BASE_AMOUNT_EUR', 15))
        dca = float(cfg.get('DCA_AMOUNT_EUR', 22))
        if dca > base * 3:
            target = max(base * 1.5, 5)
            s = _suggest('DCA_AMOUNT_EUR', dca, target,
                          f'DCA â‚¬{dca} too large vs BASE â‚¬{base}: aligning to {target:.1f}')
            if s:
                out.append(s)
        elif win_rate > 0.60 and dca < base * 1.5:
            target = min(base * 2, dca * 1.3)
            s = _suggest('DCA_AMOUNT_EUR', dca, target,
                          f'win rate {win_rate:.1%}: can increase DCA size')
            if s:
                out.append(s)

    return out


# ===================================================================
# GROUP D â€” Advanced optimization (Rules 16-24)
# ===================================================================

def rules_advanced_optimization(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 16-24: DCA timing, trades cap, entry filter, SMA, TP, vol sizing, volume, momentum, RSI range."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    closed_trades = ctx['closed_trades']
    win_rate = ctx.get('win_rate', 0.5)

    # Rule 16: RSI_DCA_THRESHOLD
    if len(pnl_list) >= 15:
        current_rsi_dca = float(cfg.get('RSI_DCA_THRESHOLD', 60))
        dca_trades = [t for t in closed_trades if t.get('dca_buys', 0) > 0]
        if len(dca_trades) >= 5:
            dca_wins = sum(1 for t in dca_trades if t.get('pnl', 0) > 0)
            dca_wr = dca_wins / len(dca_trades)
            if dca_wr < 0.40:
                s = _suggest('RSI_DCA_THRESHOLD', current_rsi_dca, max(50, current_rsi_dca - 5),
                              f'DCA win rate {dca_wr:.1%}: be more selective (lower RSI)')
                if s:
                    out.append(s)
            elif dca_wr > 0.65:
                s = _suggest('RSI_DCA_THRESHOLD', current_rsi_dca, min(70, current_rsi_dca + 5),
                              f'DCA win rate {dca_wr:.1%}: can be more aggressive')
                if s:
                    out.append(s)

    # Rule 17: MAX_OPEN_TRADES based on win rate
    if len(pnl_list) >= _GATE_LOW:
        max_trades = int(cfg.get('MAX_OPEN_TRADES', 4))
        if win_rate > 0.60 and max_trades < 5:
            s = _suggest_int('MAX_OPEN_TRADES', max_trades, max_trades + 1,
                              f'win rate {win_rate:.1%}: can handle more concurrent trades')
            if s:
                out.append(s)
        elif win_rate < 0.40 and max_trades > 2:
            s = _suggest_int('MAX_OPEN_TRADES', max_trades, max_trades - 1,
                              f'win rate {win_rate:.1%}: focus on fewer quality trades')
            if s:
                out.append(s)

    # Rule 18: MIN_SCORE_TO_BUY dynamic entry filter
    if len(pnl_list) >= _GATE_LOW:
        min_score = float(cfg.get('MIN_SCORE_TO_BUY', 10))
        recent_entries = closed_trades[-15:] if len(closed_trades) >= 15 else closed_trades
        if len(recent_entries) >= 10:
            avg_pnl = sum(t.get('pnl', 0) for t in recent_entries) / len(recent_entries)
            if avg_pnl < -2 and min_score < 10:
                s = _suggest('MIN_SCORE_TO_BUY', min_score, min(10, min_score + 0.5),
                              f'avg entry PnL â‚¬{avg_pnl:.2f}: raise entry standards')
                if s:
                    out.append(s)
            elif avg_pnl > 3 and win_rate > 0.55 and min_score > 7:
                s = _suggest('MIN_SCORE_TO_BUY', min_score, max(7, min_score - 0.5),
                              f'avg entry PnL â‚¬{avg_pnl:.2f}: can lower entry barrier')
                if s:
                    out.append(s)

    # Rule 19: SMA periods
    if len(pnl_list) >= _GATE_MED:
        sma_short = int(cfg.get('SMA_SHORT', 10))
        trend_trades = [t for t in closed_trades if t.get('trend_aligned')]
        if len(trend_trades) >= 8:
            trend_wr = sum(1 for t in trend_trades if t.get('pnl', 0) > 0) / len(trend_trades)
            if trend_wr < 0.45 and sma_short > 5:
                s = _suggest_int('SMA_SHORT', sma_short, max(5, sma_short - 2),
                                  f'trend WR {trend_wr:.1%}: try faster SMA')
                if s:
                    out.append(s)

    # Rule 20: TP optimization
    if len(pnl_list) >= _GATE_LOW and cfg.get('TAKE_PROFIT_ENABLED', True):
        winners = [t for t in closed_trades[-25:] if t.get('pnl', 0) > 0]
        if len(winners) >= 10:
            avg_max_gain = sum(t.get('max_profit_pct', 0) for t in winners) / len(winners)
            if avg_max_gain > 0.06:
                current_tp3 = float(cfg.get('TAKE_PROFIT_TARGET_3', 0.08))
                s = _suggest('TAKE_PROFIT_TARGET_3', current_tp3, min(0.12, current_tp3 + 0.01),
                              f'avg max gain {avg_max_gain:.1%}: can aim higher on TP3')
                if s:
                    out.append(s)
            elif 0 < avg_max_gain < 0.03:
                current_tp1 = float(cfg.get('TAKE_PROFIT_TARGET_1', 0.03))
                s = _suggest('TAKE_PROFIT_TARGET_1', current_tp1, max(0.02, current_tp1 - 0.005),
                              f'avg max gain {avg_max_gain:.1%}: take profits faster')
                if s:
                    out.append(s)

    # Rule 21: Volatility sizing
    if len(pnl_list) >= _GATE_MED:
        pnl_std = (sum((p - sum(pnl_list[-20:]) / 20) ** 2 for p in pnl_list[-20:]) / 20) ** 0.5
        vol_enabled = cfg.get('VOLATILITY_SIZING_ENABLED', False)
        if pnl_std > 2.0 and not vol_enabled and _cooldown_ok('VOLATILITY_SIZING_ENABLED'):
            out.append({'param': 'VOLATILITY_SIZING_ENABLED', 'from': False, 'to': True,
                        'reason': f'high outcome volatility (Ïƒ={pnl_std:.2f}): enable vol sizing'})
            _last_suggest['VOLATILITY_SIZING_ENABLED'] = _utc_now()
        elif pnl_std < 1.0 and vol_enabled and win_rate > 0.50 and _cooldown_ok('VOLATILITY_SIZING_ENABLED'):
            out.append({'param': 'VOLATILITY_SIZING_ENABLED', 'from': True, 'to': False,
                        'reason': f'low volatility (Ïƒ={pnl_std:.2f}): can disable vol sizing'})
            _last_suggest['VOLATILITY_SIZING_ENABLED'] = _utc_now()

    # Rule 22: MIN_VOLUME_24H filter
    if len(pnl_list) >= _GATE_LOW:
        current_min_vol = float(cfg.get('MIN_VOLUME_24H_EUR', 100000))
        low_vol_trades = [t for t in closed_trades[-20:]
                          if t.get('volume_24h_eur', float('inf')) < current_min_vol * 1.5]
        if len(low_vol_trades) >= 5:
            low_vol_wr = sum(1 for t in low_vol_trades if t.get('pnl', 0) > 0) / len(low_vol_trades)
            if low_vol_wr < 0.35:
                s = _suggest('MIN_VOLUME_24H_EUR', current_min_vol, min(180000, current_min_vol + 25000),
                              f'low-vol trades WR {low_vol_wr:.1%}: need more liquidity')
                if s:
                    out.append(s)

    # Rule 23: Momentum filter
    if len(pnl_list) >= _GATE_LOW:
        current_min_change = float(cfg.get('MIN_PRICE_CHANGE_PCT', 0.01))
        momentum_trades = [t for t in closed_trades[-20:] if t.get('price_change_pct', 0) > 0]
        if len(momentum_trades) >= 10:
            high_mom = [t for t in momentum_trades if t.get('price_change_pct', 0) > 0.02]
            low_mom = [t for t in momentum_trades if 0 < t.get('price_change_pct', 0) <= 0.01]
            if len(high_mom) >= 5 and len(low_mom) >= 5:
                high_wr = sum(1 for t in high_mom if t.get('pnl', 0) > 0) / len(high_mom)
                low_wr = sum(1 for t in low_mom if t.get('pnl', 0) > 0) / len(low_mom)
                if high_wr > low_wr + 0.15 and current_min_change < 0.02:
                    s = _suggest('MIN_PRICE_CHANGE_PCT', current_min_change,
                                  min(0.025, current_min_change + 0.005),
                                  f'high momentum WR {high_wr:.1%} vs low {low_wr:.1%}: favor momentum')
                    if s:
                        out.append(s)

    # Rule 24: RSI range optimization
    if len(pnl_list) >= _GATE_MED:
        rsi_max = int(cfg.get('RSI_MAX_BUY', 45))
        rsi_entries = [t for t in closed_trades[-20:] if 'rsi_at_entry' in t]
        if len(rsi_entries) >= 12:
            oversold = [t for t in rsi_entries if t.get('rsi_at_entry', 50) < 35]
            neutral = [t for t in rsi_entries if 35 <= t.get('rsi_at_entry', 50) <= 50]
            if len(oversold) >= 4 and len(neutral) >= 4:
                oversold_wr = sum(1 for t in oversold if t.get('pnl', 0) > 0) / len(oversold)
                neutral_wr = sum(1 for t in neutral if t.get('pnl', 0) > 0) / len(neutral)
                if oversold_wr > neutral_wr + 0.20 and rsi_max > 42:
                    s = _suggest_int('RSI_MAX_BUY', rsi_max, rsi_max - 3,
                                      f'oversold WR {oversold_wr:.1%} >> neutral {neutral_wr:.1%}: prefer oversold')
                    if s:
                        out.append(s)

    return out


# ===================================================================
# GROUP E â€” Market intelligence (Rules 25-28)
# ===================================================================

def rules_market_intelligence(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 25-28: regime adaptation, per-coin learning, risk mgmt, correlation, whitelist."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    closed_trades = ctx['closed_trades']
    win_rate = ctx.get('win_rate', 0.5)

    # Rule 25: Market regime adaptation
    if len(pnl_list) >= _GATE_LOW:
        regime_data = _cached_regime(closed_trades, cfg)
        regime = regime_data.get('regime', 'SIDEWAYS')
        confidence = regime_data.get('confidence', 0.5)

        if confidence > 0.6:
            if regime == 'BULL':
                min_score = float(cfg.get('MIN_SCORE_TO_BUY', 10))
                if min_score > 7.5:
                    s = _suggest('MIN_SCORE_TO_BUY', min_score, 7.5,
                                  f'BULL market detected (conf {confidence:.0%}): lower entry barrier',
                                  extras={'confidence': confidence, 'regime': 'BULL'})
                    if s:
                        out.append(s)
                trailing = float(cfg.get('DEFAULT_TRAILING', 0.04))
                if trailing < 0.06:
                    s = _suggest('DEFAULT_TRAILING', trailing, 0.06,
                                  'BULL market: increase trailing for more upside',
                                  extras={'confidence': confidence, 'regime': 'BULL'})
                    if s:
                        out.append(s)
            elif regime == 'BEAR':
                min_score = float(cfg.get('MIN_SCORE_TO_BUY', 10))
                if min_score < 9.5:
                    s = _suggest('MIN_SCORE_TO_BUY', min_score, 9.5,
                                  f'BEAR market detected (conf {confidence:.0%}): raise entry standards',
                                  extras={'confidence': confidence, 'regime': 'BEAR'})
                    if s:
                        out.append(s)
                hard_sl = float(cfg.get('HARD_SL_ALT_PCT', 0.05))
                if hard_sl > 0.03:
                    s = _suggest('HARD_SL_ALT_PCT', hard_sl, 0.03,
                                  'BEAR market: tighten stop losses',
                                  extras={'confidence': confidence, 'regime': 'BEAR'})
                    if s:
                        out.append(s)
            elif regime == 'SIDEWAYS':
                trailing_act = float(cfg.get('TRAILING_ACTIVATION_PCT', 0.02))
                if trailing_act > 0.01:
                    s = _suggest('TRAILING_ACTIVATION_PCT', trailing_act, 0.01,
                                  'SIDEWAYS market: quick scalping mode',
                                  extras={'confidence': confidence, 'regime': 'SIDEWAYS'})
                    if s:
                        out.append(s)

    # Rule 21bis: Per-coin learning (logging only, no param changes)
    if len(pnl_list) >= _GATE_MED:
        coin_stats = get_coin_statistics(closed_trades)
        qualified = {m: s for m, s in coin_stats.items() if s['trades'] >= 5}
        if qualified:
            sorted_coins = sorted(qualified.items(),
                                  key=lambda x: x[1]['win_rate'] * max(x[1]['avg_pnl'], 0.1),
                                  reverse=True)
            for coin, stats in sorted_coins[:2]:
                if coin not in (cfg.get('WHITELIST_MARKETS') or []):
                    log(f"[COIN-LEARNING] {coin} performs well: WR={stats['win_rate']:.1%}, "
                        f"avg PnL=â‚¬{stats['avg_pnl']:.2f}", level='info')
            for coin, stats in sorted_coins[-3:]:
                if coin in (cfg.get('WHITELIST_MARKETS') or []):
                    if stats['win_rate'] < 0.35 or stats['avg_pnl'] < -2:
                        log(f"[COIN-LEARNING] {coin} performs poorly: WR={stats['win_rate']:.1%}, "
                            f"avg PnL=â‚¬{stats['avg_pnl']:.2f}", level='warning')

    # Rule 22bis: Advanced risk management
    if len(pnl_list) >= 15:
        risk_metrics = _cached_risk(closed_trades, cfg)
        daily_dd = risk_metrics.get('daily_drawdown', 0)
        consecutive = risk_metrics.get('consecutive_losses', 0)

        if daily_dd < -15:
            max_trades = int(cfg.get('MAX_OPEN_TRADES', 4))
            if max_trades > 3 and _cooldown_ok('MAX_OPEN_TRADES'):
                out.append({'param': 'MAX_OPEN_TRADES', 'from': max_trades, 'to': 3,
                            'reason': f'🚨 CRITICAL: Daily drawdown €{daily_dd:.1f} - EMERGENCY MODE',
                            'risk_level': 'CRITICAL', 'daily_dd': daily_dd})
                _last_suggest['MAX_OPEN_TRADES'] = _utc_now()

        if consecutive >= 3:
            base = float(cfg.get('BASE_AMOUNT_EUR', 15))
            if base > 7:
                s = _suggest('BASE_AMOUNT_EUR', base, max(5, base * 0.7),
                              f'âš ï¸ {consecutive} consecutive losses: reduce position size',
                              extras={'consecutive_losses': consecutive})
                if s:
                    out.append(s)

        if risk_metrics.get('current_volatility', 0) > 2.0:
            dca_max = int(cfg.get('DCA_MAX_BUYS', 3))
            if dca_max > 2 and _cooldown_ok('DCA_MAX_BUYS'):
                out.append({'param': 'DCA_MAX_BUYS', 'from': dca_max, 'to': 2,
                            'reason': 'High volatility detected: limit DCA averaging',
                            'volatility': risk_metrics.get('current_volatility')})
                _last_suggest['DCA_MAX_BUYS'] = _utc_now()

    # Rule 23bis: Volatility position sizing
    if len(pnl_list) >= _GATE_LOW:
        risk_metrics = _cached_risk(closed_trades, cfg)
        volatility = risk_metrics.get('current_volatility', 1.0)
        atr_mult = float(cfg.get('ATR_MULTIPLIER', 2.0))
        base = float(cfg.get('BASE_AMOUNT_EUR', 15))

        if volatility > 1.8 and atr_mult < 2.5:
            s = _suggest('ATR_MULTIPLIER', atr_mult, 2.5,
                          f'High volatility ({volatility:.1f}x): increase ATR buffer',
                          extras={'volatility': volatility})
            if s:
                out.append(s)
        elif volatility < 0.8 and base < 20:
            s = _suggest('BASE_AMOUNT_EUR', base, min(base * 1.2, 20),
                          f'Low volatility ({volatility:.1f}x): can increase position size',
                          extras={'volatility': volatility})
            if s:
                out.append(s)

    # Rule 28: Portfolio correlation
    if len(pnl_list) >= 15:
        try:
            trade_log_path = cfg.get('TRADE_LOG', os.path.join('..', 'data', 'trade_log.json'))
            open_trades_data = {}
            try:
                with open(trade_log_path, 'r') as f:
                    trade_data = json.load(f)
                    if isinstance(trade_data, dict):
                        open_trades_data = {t['market']: t for t in trade_data.get('open', [])
                                            if t.get('status') == 'open'}
            except Exception as e:
                _dbg(f"load failed: {e}")

            sectors = calculate_portfolio_sectors(open_trades_data)
            max_open = int(cfg.get('MAX_OPEN_TRADES', 4))
            for sector, count in sectors.items():
                if count > max(2, max_open // 2):
                    log(f"[CORRELATION] âš ï¸ Over-concentrated in {sector}: {count} trades", level='warning')

            btc_trades = [t for t in closed_trades[-10:] if t.get('market') == 'BTC-EUR']
            if btc_trades:
                btc_pnl = sum(t.get('profit', 0) for t in btc_trades) / len(btc_trades)
                if btc_pnl < -5 and max_open > 3:
                    s = _suggest_int('MAX_OPEN_TRADES', max_open, max(3, max_open - 1),
                                      f'BTC dump detected (avg loss: €{btc_pnl:.1f}): reduce altcoin exposure',
                                      extras={'btc_pnl': btc_pnl})
                    if s:
                        out.append(s)

            if open_trades_data:
                unique_sectors = len(sectors)
                total = len(open_trades_data)
                div_score = unique_sectors / max(total, 1)
                if div_score < 0.5 and total >= 3:
                    log(f"[CORRELATION] ðŸ“Š Low diversification: {unique_sectors} sectors across {total} trades", level='info')
        except Exception as e:
            log(f"[CORRELATION] Error: {e}", level='debug')


    # ── BTC candle-driven forward rules ──
    btc_trend = ctx.get('btc_trend', {})
    if btc_trend and btc_trend.get('trend_score') is not None:
        btc_momentum = btc_trend.get('momentum', 0)
        btc_volatility = btc_trend.get('volatility', 0)
        btc_sma_pos = btc_trend.get('sma_position', 'unknown')

        # Rule E-BTC1: BTC strong uptrend -> lower MIN_SCORE (more entries)
        if btc_momentum > 0.03 and btc_sma_pos == 'above':
            current = float(cfg.get('MIN_SCORE_TO_BUY', 2.0))
            s = _suggest('MIN_SCORE_TO_BUY', current, max(1.0, current - 0.3),
                          f'BTC strong uptrend (mom={btc_momentum:.3f}): lower entry bar',
                          extras={'source': 'btc_candles', 'data_quality': 'real'})
            if s:
                s['priority'] = 75  # Higher than base market intel
                out.append(s)

        # Rule E-BTC2: BTC strong downtrend -> tighten stop loss
        if btc_momentum < -0.03 and btc_sma_pos == 'below':
            current = float(cfg.get('HARD_SL_ALT_PCT', 0.03))
            s = _suggest('HARD_SL_ALT_PCT', current, max(0.02, current - 0.005),
                          f'BTC downtrend (mom={btc_momentum:.3f}): tighter SL',
                          extras={'source': 'btc_candles', 'data_quality': 'real'})
            if s:
                s['priority'] = 75
                out.append(s)

        # Rule E-BTC3: BTC high volatility -> widen trailing
        if btc_volatility > 2.0:
            current = float(cfg.get('DEFAULT_TRAILING', 0.012))
            s = _suggest('DEFAULT_TRAILING', current, min(0.05, current * 1.15),
                          f'BTC high volatility ({btc_volatility:.1f}%): widen trailing',
                          extras={'source': 'btc_candles', 'data_quality': 'real'})
            if s:
                s['priority'] = 75
                out.append(s)

        # Rule E-BTC4: BTC low volatility + uptrend -> increase position size
        if btc_volatility < 1.0 and btc_momentum > 0.01:
            current = float(cfg.get('BASE_AMOUNT_EUR', 15))
            s = _suggest('BASE_AMOUNT_EUR', current, min(100.0, current * 1.1),
                          f'BTC calm uptrend: increase size',
                          extras={'source': 'btc_candles', 'data_quality': 'real'})
            if s:
                s['priority'] = 75
                out.append(s)

    return out


# ===================================================================
# GROUP F â€” Dynamic learning & time-based (Rules 26-31)
# ===================================================================

def rules_dynamic_learning(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 26-31: score learning, DCA spacing, profit recycling, time intelligence, volume filter."""
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    closed_trades = ctx['closed_trades']
    win_rate = ctx.get('win_rate', 0.5)
    open_exposure = ctx['open_exposure']
    max_total = ctx['max_total']

    # Rule 26: Dynamic score learning
    if len(pnl_list) >= _GATE_HIGH:
        score_perf: Dict[int, Dict] = {}
        for t in closed_trades:
            score = t.get('score')
            profit = t.get('profit', 0)
            if score is not None and isinstance(score, (int, float)):
                sl = int(score)
                if sl not in score_perf:
                    score_perf[sl] = {'trades': 0, 'wins': 0, 'total_pnl': 0.0}
                score_perf[sl]['trades'] += 1
                if profit > 0:
                    score_perf[sl]['wins'] += 1
                score_perf[sl]['total_pnl'] += profit

        score_stats = {}
        for sl, data in score_perf.items():
            if data['trades'] >= 3:
                wr = data['wins'] / data['trades']
                avg_pnl = data['total_pnl'] / data['trades']
                score_stats[sl] = {'win_rate': wr, 'avg_pnl': avg_pnl,
                                   'trades': data['trades'],
                                   'quality': wr * max(avg_pnl, 0.1)}

        current_min_score = int(cfg.get('MIN_SCORE_TO_BUY', 10))
        regime_data = _cached_regime(closed_trades, cfg)
        regime = regime_data.get('regime', 'SIDEWAYS')

        if score_stats:
            if regime == 'BULL' and regime_data.get('confidence', 0) > 0.6:
                candidates = [(s, d) for s, d in score_stats.items() if d['win_rate'] > 0.55 and s >= 7]
                if candidates:
                    best = min(c[0] for c in candidates)
                    if best < current_min_score and _cooldown_ok('MIN_SCORE_TO_BUY'):
                        out.append({'param': 'MIN_SCORE_TO_BUY', 'from': current_min_score, 'to': best,
                                    'reason': f'BULL: Score {best} has {score_stats[best]["win_rate"]*100:.1f}% WR',
                                    'regime': regime})
                        _last_suggest['MIN_SCORE_TO_BUY'] = _utc_now()
            elif regime == 'BEAR' and regime_data.get('confidence', 0) > 0.6:
                candidates = [(s, d) for s, d in score_stats.items() if d['trades'] >= 5 and s <= 12]
                if candidates:
                    best = sorted(candidates, key=lambda x: x[1]['quality'], reverse=True)[0][0]
                    if best > current_min_score and best >= 9 and _cooldown_ok('MIN_SCORE_TO_BUY'):
                        out.append({'param': 'MIN_SCORE_TO_BUY', 'from': current_min_score, 'to': best,
                                    'reason': f'BEAR: Score {best} has best quality',
                                    'regime': regime})
                        _last_suggest['MIN_SCORE_TO_BUY'] = _utc_now()
            else:
                candidates = [(s, d) for s, d in score_stats.items()
                              if d['win_rate'] > 0.50 and d['avg_pnl'] > 0 and d['trades'] >= 5]
                if candidates:
                    best = sorted(candidates, key=lambda x: x[1]['quality'], reverse=True)[0][0]
                    if best != current_min_score and 7 <= best <= 12 and _cooldown_ok('MIN_SCORE_TO_BUY'):
                        out.append({'param': 'MIN_SCORE_TO_BUY', 'from': current_min_score, 'to': best,
                                    'reason': f'Optimal score: {best} has {score_stats[best]["win_rate"]*100:.1f}% WR',
                                    'quality': score_stats[best]['quality']})
                        _last_suggest['MIN_SCORE_TO_BUY'] = _utc_now()

            if score_stats:
                log("[SCORE ANALYSIS] Performance by score level:", level='info')
                for sc in sorted(score_stats.keys(), reverse=True):
                    d = score_stats[sc]
                    log(f"  Score {sc}: {d['win_rate']*100:.1f}% WR, â‚¬{d['avg_pnl']:.2f} avg, {d['trades']} trades", level='info')

    # Rule 27: Dynamic DCA spacing
    if len(pnl_list) >= _GATE_MED:
        current_drop = float(cfg.get('DCA_DROP_PCT', 0.06))
        regime_data = _cached_regime(closed_trades, cfg)
        regime = regime_data.get('regime', 'SIDEWAYS')
        risk_metrics = _cached_risk(closed_trades, cfg)
        volatility = risk_metrics.get('current_volatility', 1.0)

        if regime == 'BULL' and regime_data.get('confidence', 0) > 0.6:
            target = 0.035 if volatility < 1.2 else 0.04
        elif regime == 'BEAR' and regime_data.get('confidence', 0) > 0.6:
            target = 0.10 if volatility > 1.5 else 0.08
        else:
            target = 0.07 if volatility > 1.8 else (0.05 if volatility < 0.8 else 0.06)

        threshold = 0.01 if regime == 'BEAR' else 0.005
        if abs(current_drop - target) > threshold and _cooldown_ok('DCA_DROP_PCT'):
            new_val = _bounded_step('DCA_DROP_PCT', current_drop, target)
            if new_val is not None:
                out.append({'param': 'DCA_DROP_PCT', 'from': current_drop, 'to': new_val,
                            'reason': f'{regime} market DCA spacing (vol: {volatility:.1f}x)',
                            'regime': regime, 'volatility': volatility})
                _last_suggest['DCA_DROP_PCT'] = _utc_now()

    # Rule 29: Smart profit recycling
    if len(pnl_list) >= _GATE_LOW:
        total_pnl = sum(pnl_list)
        current_portion = float(cfg.get('REINVEST_PORTION', 0.5))

        if total_pnl > 50 and win_rate > 0.55 and current_portion < 0.7:
            new_portion = min(0.7, current_portion + 0.1)
            if _cooldown_ok('REINVEST_PORTION'):
                out.append({'param': 'REINVEST_PORTION', 'from': current_portion, 'to': new_portion,
                            'reason': f'Strong performance (â‚¬{total_pnl:.0f}, {win_rate:.1%} WR): increase reinvestment',
                            'win_rate': win_rate})
                _last_suggest['REINVEST_PORTION'] = _utc_now()
        elif win_rate < 0.45 and current_portion > 0.3:
            new_portion = max(0.3, current_portion - 0.1)
            if _cooldown_ok('REINVEST_PORTION'):
                out.append({'param': 'REINVEST_PORTION', 'from': current_portion, 'to': new_portion,
                            'reason': f'Low win rate ({win_rate:.1%}): reduce profit reinvestment',
                            'win_rate': win_rate})
                _last_suggest['REINVEST_PORTION'] = _utc_now()

    # Rule 30: Time-based intelligence
    if len(pnl_list) >= _GATE_LOW:
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)  # Use UTC, not local time
        is_weekend = now.weekday() >= 5
        hour = now.hour

        if is_weekend:
            base = float(cfg.get('BASE_AMOUNT_EUR', 15))
            target = base * 0.7
            if base > 10 and abs(base - target) > 2 and _cooldown_ok('BASE_AMOUNT_EUR_WEEKEND'):
                out.append({'param': 'BASE_AMOUNT_EUR', 'from': base, 'to': round(target, 1),
                            'reason': 'Weekend: reduce position size (lower liquidity)',
                            'is_weekend': True})
                _last_suggest['BASE_AMOUNT_EUR_WEEKEND'] = _utc_now()
        elif 8 <= hour <= 16:
            min_score = int(cfg.get('MIN_SCORE_TO_BUY', 10))
            if min_score > 8 and _cooldown_ok('MIN_SCORE_TO_BUY_HOURS'):
                out.append({'param': 'MIN_SCORE_TO_BUY', 'from': min_score, 'to': min_score - 1,
                            'reason': 'High volume hours (8-16 UTC): slightly lower threshold',
                            'hour': hour})
                _last_suggest['MIN_SCORE_TO_BUY_HOURS'] = _utc_now()
        elif hour >= 22 or hour <= 6:
            min_score = int(cfg.get('MIN_SCORE_TO_BUY', 10))
            if min_score < 11 and _cooldown_ok('MIN_SCORE_TO_BUY_HOURS'):
                out.append({'param': 'MIN_SCORE_TO_BUY', 'from': min_score, 'to': min_score + 1,
                            'reason': 'Low volume hours (22-6 UTC): raise threshold for safety',
                            'hour': hour})
                _last_suggest['MIN_SCORE_TO_BUY_HOURS'] = _utc_now()

    # Rule 31: Dynamic volume filter
    if len(pnl_list) >= _GATE_MED:
        current_min_vol = float(cfg.get('MIN_AVG_VOLUME_1M', 150))
        low_vol = [t for t in closed_trades[-30:] if t.get('avg_volume', 200) < 100]
        high_vol = [t for t in closed_trades[-30:] if t.get('avg_volume', 200) >= 200]

        if low_vol and high_vol:
            low_wr = sum(1 for t in low_vol if t.get('profit', 0) > 0) / len(low_vol)
            high_wr = sum(1 for t in high_vol if t.get('profit', 0) > 0) / len(high_vol)

            if high_wr > low_wr + 0.15 and current_min_vol < 200:
                s = _suggest('MIN_AVG_VOLUME_1M', current_min_vol, min(200, current_min_vol + 25),
                              f'High volume trades perform better: {high_wr:.1%} vs {low_wr:.1%} WR',
                              extras={'high_vol_wr': high_wr, 'low_vol_wr': low_wr})
                if s:
                    out.append(s)
            elif low_wr >= high_wr - 0.05 and current_min_vol > 100:
                s = _suggest('MIN_AVG_VOLUME_1M', current_min_vol, max(100, current_min_vol - 25),
                              f'Low volume trades acceptable: {low_wr:.1%} vs {high_wr:.1%} WR',
                              extras={'high_vol_wr': high_wr, 'low_vol_wr': low_wr})
                if s:
                    out.append(s)

    return out


# ===================================================================
# GROUP F2 — Orphaned param rules + trailing entry optimization
# ===================================================================

def rules_trailing_entry_tp(ctx: RuleCtx) -> List[Suggestion]:
    """Rules 32-37: PARTIAL_TP sell ratios, TRAILING_ENTRY, DCA_SIZE_MULTIPLIER.

    These params WERE in AI_ALLOW_PARAMS but had zero rules — now they do.
    """
    out: List[Suggestion] = []
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    closed_trades = ctx['closed_trades']
    win_rate = ctx.get('win_rate', 0.5)

    # Rule 32: PARTIAL_TP_SELL_PCT balance — if early TP locks too much/little
    if len(pnl_list) >= _GATE_LOW and cfg.get('TAKE_PROFIT_ENABLED', True):
        winners = [t for t in closed_trades[-25:] if t.get('pnl', 0) > 0]

        if len(winners) >= 5:
            avg_win = sum(t.get('pnl', 0) for t in winners) / len(winners)
            pct1 = float(cfg.get('PARTIAL_TP_SELL_PCT_1', 0.4))
            if avg_win < 0.5 and pct1 > 0.25:
                s = _suggest('PARTIAL_TP_SELL_PCT_1', pct1, max(0.2, pct1 - 0.05),
                              f'Avg win {avg_win:.2f}: sell less at TP1')
                if s:
                    out.append(s)
            elif avg_win > 2.0:
                pct3 = float(cfg.get('PARTIAL_TP_SELL_PCT_3', 0.25))
                if pct3 < 0.35:
                    s = _suggest('PARTIAL_TP_SELL_PCT_3', pct3, min(0.4, pct3 + 0.05),
                                  f'Avg win {avg_win:.2f}: sell more at TP3 to lock profits')
                    if s:
                        out.append(s)

    # Rule 33: TRAILING_ENTRY optimization
    if len(pnl_list) >= _GATE_LOW and cfg.get('TRAILING_ENTRY_ENABLED', False):
        te_trades = [t for t in closed_trades[-20:] if t.get('trailing_entry_used')]
        nm_trades = [t for t in closed_trades[-20:] if not t.get('trailing_entry_used')]

        if len(te_trades) >= 5 and len(nm_trades) >= 5:
            te_wr = sum(1 for t in te_trades if t.get('pnl', 0) > 0) / len(te_trades)
            nm_wr = sum(1 for t in nm_trades if t.get('pnl', 0) > 0) / len(nm_trades)

            pullback = float(cfg.get('TRAILING_ENTRY_PULLBACK_PCT', 0.01))
            timeout = int(cfg.get('TRAILING_ENTRY_TIMEOUT_S', 120))

            if te_wr > nm_wr + 0.10 and pullback < 0.02:
                s = _suggest('TRAILING_ENTRY_PULLBACK_PCT', pullback, min(0.025, pullback + 0.005),
                              f'TE WR {te_wr:.1%} > normal {nm_wr:.1%}: aim deeper pullback')
                if s:
                    out.append(s)
            elif te_wr < nm_wr - 0.10:
                if pullback > 0.008:
                    s = _suggest('TRAILING_ENTRY_PULLBACK_PCT', pullback, max(0.005, pullback - 0.003),
                                  f'TE WR {te_wr:.1%} < normal {nm_wr:.1%}: tighter pullback')
                    if s:
                        out.append(s)
                if timeout > 60:
                    s = _suggest_int('TRAILING_ENTRY_TIMEOUT_S', timeout, max(30, timeout - 30),
                                      'TE underperforms: shorter timeout')
                    if s:
                        out.append(s)

    # Rule 34: DCA_SIZE_MULTIPLIER based on DCA trade outcomes
    if len(pnl_list) >= _GATE_LOW:
        dca_trades = [t for t in closed_trades if t.get('dca_buys', 0) > 0]
        non_dca = [t for t in closed_trades if t.get('dca_buys', 0) == 0]

        if len(dca_trades) >= 5 and len(non_dca) >= 5:
            dca_avg = sum(t.get('pnl', 0) for t in dca_trades) / len(dca_trades)
            non_dca_avg = sum(t.get('pnl', 0) for t in non_dca) / len(non_dca)

            cur_mult = float(cfg.get('DCA_SIZE_MULTIPLIER', 1.0))
            if dca_avg > non_dca_avg and dca_avg > 0 and cur_mult < 1.3:
                s = _suggest('DCA_SIZE_MULTIPLIER', cur_mult, min(1.5, cur_mult + 0.1),
                              f'DCA avg {dca_avg:.2f} > non-DCA {non_dca_avg:.2f}: increase sizing')
                if s:
                    out.append(s)
            elif dca_avg < -1.0 and cur_mult > 0.6:
                s = _suggest('DCA_SIZE_MULTIPLIER', cur_mult, max(0.5, cur_mult - 0.1),
                              f'DCA avg {dca_avg:.2f}: reduce DCA sizing')
                if s:
                    out.append(s)

    # Rule 35: DCA_MAX_BUYS_PER_ITERATION — volatility-based
    if len(pnl_list) >= _GATE_LOW:
        max_iter = int(cfg.get('DCA_MAX_BUYS_PER_ITERATION', 2))
        risk_m = _cached_risk(closed_trades, cfg)
        vol = risk_m.get('current_volatility', 1.0)

        if vol > 1.5 and max_iter > 1:
            s = _suggest_int('DCA_MAX_BUYS_PER_ITERATION', max_iter, 1,
                              f'High volatility ({vol:.1f}x): limit DCA per iteration')
            if s:
                out.append(s)
        elif vol < 0.8 and win_rate > 0.55 and max_iter < 3:
            s = _suggest_int('DCA_MAX_BUYS_PER_ITERATION', max_iter, max_iter + 1,
                              'Low vol + good WR: DCA faster')
            if s:
                out.append(s)

    return out


# ===================================================================
# GROUP F4 — Cross-parameter coherence
# ===================================================================

def coherence_check(out: List[Suggestion], cfg: dict) -> List[Suggestion]:
    """Validate parameter combinations AFTER all rules run.

    Ensures related params move together logically.
    """
    extra: List[Suggestion] = []
    pending = {s.get('param'): s.get('to') for s in out if s.get('param')}

    def _val(param, default=None):
        return pending.get(param, cfg.get(param, default))

    # C1: Trailing & Activation move together
    if 'DEFAULT_TRAILING' in pending and 'TRAILING_ACTIVATION_PCT' not in pending:
        new_trail = float(pending['DEFAULT_TRAILING'])
        cur_act = float(cfg.get('TRAILING_ACTIVATION_PCT', 0.02))
        ideal_act = new_trail * 0.4
        if abs(cur_act - ideal_act) > 0.005:
            s = _suggest('TRAILING_ACTIVATION_PCT', cur_act, ideal_act,
                          f'Coherence: trail->{new_trail:.3f}, act->{ideal_act:.3f}')
            if s:
                extra.append(s)

    # C2: BASE_AMOUNT & DCA_AMOUNT alignment
    if 'BASE_AMOUNT_EUR' in pending and 'DCA_AMOUNT_EUR' not in pending:
        new_base = float(pending['BASE_AMOUNT_EUR'])
        cur_dca = float(cfg.get('DCA_AMOUNT_EUR', 15))
        if cur_dca > new_base * 1.5:
            tgt_dca = max(new_base, LIMITS.get('DCA_AMOUNT_EUR', {}).get('min', 3))
            s = _suggest('DCA_AMOUNT_EUR', cur_dca, tgt_dca,
                          f'Coherence: base->{new_base:.0f}, DCA align->{tgt_dca:.0f}')
            if s:
                extra.append(s)

    # C3: TP targets ordering
    tp1 = float(_val('TAKE_PROFIT_TARGET_1', 0.03))
    tp2 = float(_val('TAKE_PROFIT_TARGET_2', 0.06))
    tp3 = float(_val('TAKE_PROFIT_TARGET_3', 0.10))
    if tp1 >= tp2:
        s = _suggest('TAKE_PROFIT_TARGET_2', tp2, tp1 + 0.015,
                      f'Coherence: TP2 ({tp2:.3f}) must be > TP1 ({tp1:.3f})')
        if s:
            extra.append(s)
    if tp2 >= tp3:
        s = _suggest('TAKE_PROFIT_TARGET_3', tp3, tp2 + 0.02,
                      f'Coherence: TP3 ({tp3:.3f}) must be > TP2 ({tp2:.3f})')
        if s:
            extra.append(s)

    # C4: RSI range validation
    rsi_min = float(_val('RSI_MIN_BUY', 30))
    rsi_max = float(_val('RSI_MAX_BUY', 55))
    if rsi_min >= rsi_max - 5:
        s = _suggest_int('RSI_MAX_BUY', int(rsi_max), int(rsi_min) + 15,
                          f'Coherence: RSI range {rsi_min:.0f}-{rsi_max:.0f} too narrow')
        if s:
            extra.append(s)

    # C5: Stop loss & trailing relationship
    if 'HARD_SL_ALT_PCT' in pending and 'DEFAULT_TRAILING' not in pending:
        new_sl = float(pending['HARD_SL_ALT_PCT'])
        cur_trail = float(cfg.get('DEFAULT_TRAILING', 0.035))
        if new_sl < cur_trail * 2:
            ideal = new_sl * 0.6
            if cur_trail > ideal + 0.005:
                s = _suggest('DEFAULT_TRAILING', cur_trail, ideal,
                              f'Coherence: SL->{new_sl:.3f}, trail tighten->{ideal:.3f}')
                if s:
                    extra.append(s)

    # C6: Partial TP effective coverage check
    # Each TP sells a % of REMAINING, not original. So compounded remainder:
    # remain = (1-pct1) * (1-pct2) * (1-pct3). If remain > 35%, trailing/SL
    # must close the rest — warn if too much is left open.
    pct1 = float(_val('PARTIAL_TP_SELL_PCT_1', 0.4))
    pct2 = float(_val('PARTIAL_TP_SELL_PCT_2', 0.3))
    pct3 = float(_val('PARTIAL_TP_SELL_PCT_3', 0.25))
    total = pct1 + pct2 + pct3
    if total > 1.0:
        scale = 0.95 / total
        s = _suggest('PARTIAL_TP_SELL_PCT_1', pct1, round(pct1 * scale, 3),
                      f'Coherence: total TP sell {total:.0%} > 100%, scaling')
        if s:
            extra.append(s)
    else:
        # Check compounded remainder
        remain = (1.0 - pct1) * (1.0 - pct2) * (1.0 - pct3)
        if remain > 0.35:
            # Push pct3 higher so remainder ≤ 25%
            needed_pct3 = 1.0 - (0.25 / ((1.0 - pct1) * (1.0 - pct2)))
            if needed_pct3 > pct3 and needed_pct3 <= 0.8:
                s = _suggest('PARTIAL_TP_SELL_PCT_3', pct3, round(needed_pct3, 3),
                              f'Coherence: after TP1+2 only {(1-remain):.0%} sold, {remain:.0%} remains unmanaged')
                if s:
                    extra.append(s)

    # C7: HARD_SL_ALT_PCT must be WIDER than deepest DCA level
    # With DCA_STEP_MULTIPLIER compounding, the last DCA fires much deeper
    # than DCA_DROP_PCT alone.  E.g. drop=6%, step=1.4, max_buys=3 →
    # DCA3 step = 6%*1.4² = 11.76% → SL must be > 13.76% (+ 2% margin).
    hard_sl = float(_val('HARD_SL_ALT_PCT', 0.09))
    dca_drop = float(_val('DCA_DROP_PCT', 0.06))
    step_mult = float(_val('DCA_STEP_MULTIPLIER', 1.4))
    max_buys = int(_val('DCA_MAX_BUYS', 3))
    # Build effective cfg for helper (merge pending changes)
    _eff_cfg = dict(cfg)
    _eff_cfg.update({
        'DCA_DROP_PCT': dca_drop,
        'DCA_STEP_MULTIPLIER': step_mult,
        'DCA_MAX_BUYS': max_buys,
    })
    min_sl = _min_sl_for_dca(_eff_cfg)
    if hard_sl < min_sl:
        safe_sl = min(0.25, min_sl)
        s = _suggest('HARD_SL_ALT_PCT', hard_sl, safe_sl,
                      f'Coherence: SL ({hard_sl:.1%}) < deepest DCA level ({min_sl - 0.02:.1%})+margin, all DCAs blocked')
        if s:
            extra.append(s)

    # C8: TRAILING_ACTIVATION_PCT should be <= TAKE_PROFIT_TARGET_1
    # Trailing should activate before or at TP1 so the trailing can manage profit taking.
    trail_act = float(_val('TRAILING_ACTIVATION_PCT', 0.02))
    tp1 = float(_val('TAKE_PROFIT_TARGET_1', 0.03))
    if trail_act > tp1 + 0.01:
        ideal_act = round(tp1 * 0.8, 4)
        s = _suggest('TRAILING_ACTIVATION_PCT', trail_act, max(0.01, ideal_act),
                      f'Coherence: trail activation ({trail_act:.1%}) > TP1 ({tp1:.1%}), trailing never guards TP1 exit')
        if s:
            extra.append(s)

    return extra


# ===================================================================
# GROUP G - Confidence annotation (Rule 24)
# ===================================================================

def annotate_confidence(out: List[Suggestion], pnl_list: list) -> None:
    """Add confidence scores, timestamps, and impact categories to suggestions.

    Multi-factor confidence scoring:
    1. Data quantity (more trades = higher confidence)
    2. Data recency (recent trades weight more)
    3. Source reliability (coherence > analytics > sentiment)
    4. Signal agreement (multiple rules for same direction = boost)
    5. Change magnitude (tiny changes = likely noise)
    6. Regime confidence (from cached regime detection)
    7. Priority level (higher priority rules = higher confidence)
    """
    now = time.time()
    n = len(pnl_list)

    # Pre-compute: count how many suggestions agree per param direction
    param_directions: dict = {}  # param -> {'up': count, 'down': count}
    for s in out:
        param = s.get('param') or s.get('parameter')
        if param:
            try:
                frm = float(s.get('from', 0))
                to = float(s.get('to', 0))
                direction = 'up' if to > frm else 'down' if to < frm else 'neutral'
            except (TypeError, ValueError):
                direction = 'neutral'
            if param not in param_directions:
                param_directions[param] = {'up': 0, 'down': 0, 'neutral': 0}
            param_directions[param][direction] += 1

    # Get regime confidence if available
    regime_conf = 0.5
    try:
        regime_data = _cache.get('regime', {})
        if regime_data:
            regime_conf = regime_data.get('confidence', 0.5)
    except Exception:
        pass

    # Data recency factor: recent trades should weight more
    recency_factor = 1.0
    if n >= 10:
        recent_pnl = pnl_list[-10:]
        older_pnl = pnl_list[-20:-10] if n >= 20 else []
        if older_pnl:
            recent_avg = sum(recent_pnl) / len(recent_pnl)
            older_avg = sum(older_pnl) / len(older_pnl)
            # If recent performance diverges from older, data is "shifting" = lower confidence
            if abs(recent_avg - older_avg) > 2.0:
                recency_factor = 0.85

    for s in out:
        if 'confidence' not in s:
            # Factor 1: Data quantity
            if n >= 50:
                base_conf = 0.90
            elif n >= _GATE_HIGH:
                base_conf = 0.80
            elif n >= _GATE_LOW:
                base_conf = 0.70
            else:
                base_conf = 0.55

            # Factor 2: Data recency
            base_conf *= recency_factor

            # Factor 3: Source reliability
            reason = s.get('reason', '')
            source = s.get('source', '')
            if 'Coherence' in reason:
                base_conf *= 1.10  # Coherence = highest reliability
            elif s.get('priority', 0) >= 70:
                base_conf *= 1.05  # Market intelligence rules
            elif source == 'sentiment':
                data_quality = s.get('data_quality', 'simulated')
                if data_quality == 'real':
                    base_conf *= 0.95  # Real sentiment data
                else:
                    base_conf *= 0.70  # Simulated = low reliability

            # Factor 4: Signal agreement
            param = s.get('param') or s.get('parameter')
            if param and param in param_directions:
                try:
                    frm = float(s.get('from', 0))
                    to = float(s.get('to', 0))
                    direction = 'up' if to > frm else 'down' if to < frm else 'neutral'
                    agreement = param_directions[param].get(direction, 0)
                    if agreement >= 3:
                        base_conf *= 1.15  # Strong agreement
                    elif agreement >= 2:
                        base_conf *= 1.05  # Some agreement
                except (TypeError, ValueError):
                    pass

            # Factor 5: Change magnitude (noise detection)
            try:
                frm = float(s.get('from', 0))
                to = float(s.get('to', 0))
                if frm > 0:
                    change_pct = abs(to - frm) / frm
                    if change_pct < 0.01:
                        base_conf *= 0.70  # Very tiny = noise
                    elif change_pct < 0.03:
                        base_conf *= 0.85  # Small change
                    elif change_pct > 0.30:
                        base_conf *= 0.80  # Very large = suspicious
            except (TypeError, ValueError, ZeroDivisionError):
                pass

            # Factor 6: Regime confidence
            if 'regime' in reason.lower() or 'market' in reason.lower():
                base_conf *= (0.7 + 0.3 * regime_conf)  # Scale with how certain regime is

            s['confidence'] = round(min(0.95, max(0.35, base_conf)), 2)

        s.setdefault('timestamp', now)

        if 'impact' not in s:
            reason = s.get('reason', '')
            priority = s.get('priority', 0)
            if 'risk_level' in s or 'CRITICAL' in reason:
                s['impact'] = 'CRITICAL'
            elif priority >= 70 or 'Coherence' in reason or 'regime' in reason:
                s['impact'] = 'HIGH'
            elif priority >= 40 or 'consecutive' in reason or 'volatility' in reason:
                s['impact'] = 'MEDIUM'
            else:
                s['impact'] = 'LOW'


# ===================================================================
# GROUP H â€” Whitelist management (Rule 25)
# ===================================================================

def rules_whitelist_management(ctx: RuleCtx) -> tuple:
    """Rule 25: Dynamic whitelist management.
    
    Returns (suggestions, extras_dict) â€” extras may contain whitelist changes.
    """
    out: List[Suggestion] = []
    extras: dict = {}
    cfg = ctx['cfg']
    pnl_list = ctx['pnl_list']
    closed_trades = ctx['closed_trades']

    if len(pnl_list) < 30:
        return out, extras

    market_scan = scan_all_markets_for_opportunities(cfg, closed_trades)

    if market_scan.get('recommended_remove'):
        for rec in market_scan['recommended_remove'][:3]:
            log(f"[WHITELIST] ðŸ”´ Remove {rec['market']}: {rec['reason']}", level='warning')
    if market_scan.get('recommended_add'):
        for rec in market_scan['recommended_add'][:3]:
            emoji = 'ðŸ”¥' if rec.get('priority') == 'HIGH' else 'ðŸ’¡'
            log(f"[WHITELIST] {emoji} Add {rec['market']}: {rec['reason']}", level='info')

    # Persist market suggestions
    try:
        scope = cfg.get('AI_MARKET_SCOPE', 'suggest-only')
        if scope in ('suggest-only', 'guarded-auto', 'full-access'):
            try:
                from ai.ai_supervisor import suggest_market
            except ImportError:
                suggest_market = None
            if suggest_market:
                for rec in market_scan.get('recommended_add', [])[:10]:
                    market = rec if isinstance(rec, str) else rec.get('market')
                    if not market:
                        continue
                    current_wl = cfg.get('WHITELIST_MARKETS', []) or []
                    if market in current_wl:
                        continue
                    try:
                        suggest_market(market, reason=(rec.get('reason') if isinstance(rec, dict) else 'ai_scan'))
                    except Exception:
                        pass
    except Exception as e:
        _dbg(f"suggest_market failed: {e}")

    # Auto-manage whitelist
    if cfg.get('AI_AUTO_WHITELIST', False):
        current_wl = list(cfg.get('WHITELIST_MARKETS', []))
        watch_cfg = cfg.get('WATCHLIST_SETTINGS', {}) or {}
        watch_enabled = bool(watch_cfg.get('enabled', True))
        changes = []

        if watch_enabled:
            try:
                from ai.ai_supervisor import demote_market_to_watchlist, queue_market_for_watchlist
            except ImportError:
                demote_market_to_watchlist = queue_market_for_watchlist = None

            if demote_market_to_watchlist:
                for rec in market_scan.get('recommended_remove', [])[:2]:
                    market = rec['market']
                    if market in current_wl:
                        if demote_market_to_watchlist(market, reason=rec['reason']):
                            changes.append(f"Demoted {market}")
                            log(f"[AI-WATCHLIST] Demoted {market}", level='warning')

            high_prio = [r for r in market_scan.get('recommended_add', []) if r.get('priority') == 'HIGH']
            if queue_market_for_watchlist:
                for rec in high_prio[:2]:
                    market = rec['market']
                    if market not in current_wl:
                        if queue_market_for_watchlist(market, reason=rec.get('reason', 'ai-scan'), source='ai-supervisor'):
                            changes.append(f"Watchlisted {market}")
        else:
            whitelist_changed = False
            for rec in market_scan.get('recommended_remove', [])[:2]:
                market = rec['market']
                if market in current_wl and len(current_wl) > 10:
                    current_wl.remove(market)
                    whitelist_changed = True
                    changes.append(f"Removed {market}")
                    log(f"[AI-WHITELIST] Auto-removing {market}", level='warning')

            high_prio = [r for r in market_scan.get('recommended_add', []) if r.get('priority') == 'HIGH']
            for rec in high_prio[:2]:
                market = rec['market']
                if market not in current_wl and len(current_wl) < 20:
                    current_wl.append(market)
                    whitelist_changed = True
                    changes.append(f"Added {market}")
                    log(f"[AI-WHITELIST] Auto-adding {market}", level='info')

            if whitelist_changed:
                extras['whitelist'] = {
                    'new_value': current_wl,
                    'reason': ' | '.join(changes),
                    'confidence': 0.85,
                    'timestamp': time.time()
                }

        if changes:
            log(f"[AI-WHITELIST] Changes: {len(changes)}", level='info')

    return out, extras
