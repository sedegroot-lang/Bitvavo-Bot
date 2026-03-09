"""
Full Bot Backtest — End-to-end simulatie van ALLE bot-componenten.

Simuleert de volledige trading loop zonder echte API-calls:
  • Signaalscoring (SMA, RSI, MACD, volume)
  • Trade-entry met positiegrootte
  • DCA (dollar-cost averaging)
  • Trailing stop (stepped + activation)
  • Partial take-profit (3 levels)
  • Hard stop-loss
  • Grid trading (buy/sell ping-pong)
  • Risicobeheer (MAX_OPEN_TRADES, MAX_EXPOSURE)
  • AI regime bias (neutral/defensive/halt)

Gebruik:
  python full_backtest.py            → synthetic data, 3 markten
  python full_backtest.py --real     → echte Bitvavo 1h candles (vereist API)
  python full_backtest.py --days 60  → aantal dagen (default 30)
  python full_backtest.py --seed 42  → reproduceerbaar random
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: voeg project-root toe aan path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Config laden (echte bot-config)
# ---------------------------------------------------------------------------
_CONFIG_PATH = PROJECT_ROOT / "config" / "bot_config.json"
try:
    with open(_CONFIG_PATH, encoding="utf-8") as _f:
        CONFIG: Dict[str, Any] = json.load(_f)
except Exception as _e:
    print(f"[WARN] Kan config niet laden ({_e}), gebruik defaults")
    CONFIG = {}

# Haal relevante config-waarden op (met fallbacks)
SMA_SHORT        = int(CONFIG.get("SMA_SHORT", 7))
SMA_LONG         = int(CONFIG.get("SMA_LONG", 25))
RSI_MIN          = float(CONFIG.get("RSI_MIN_BUY", 35))
RSI_MAX          = float(CONFIG.get("RSI_MAX_BUY", 65))
MACD_FAST        = int(CONFIG.get("MACD_FAST", 8))
MACD_SLOW        = int(CONFIG.get("MACD_SLOW", 26))
MACD_SIG_PERIOD  = int(CONFIG.get("MACD_SIGNAL", 9))
MIN_SCORE        = float(CONFIG.get("MIN_SCORE_TO_BUY", 7.0))
BASE_EUR         = float(CONFIG.get("BASE_AMOUNT_EUR", 38.0))
DCA_MAX          = int(CONFIG.get("DCA_MAX_BUYS", 9))
DCA_DROP         = float(CONFIG.get("DCA_DROP_PCT", 0.02))
DCA_AMOUNT_EUR   = float(CONFIG.get("DCA_AMOUNT_EUR", 30.0))
TRAIL_PCT        = float(CONFIG.get("DEFAULT_TRAILING", 0.025))
TRAIL_ACT_PCT    = float(CONFIG.get("TRAILING_ACTIVATION_PCT", 0.015))
HARD_SL_PCT      = float(CONFIG.get("HARD_SL_ALT_PCT", 0.25))
MAX_TRADES       = int(CONFIG.get("MAX_OPEN_TRADES", 2))
MAX_EXPOSURE     = float(CONFIG.get("MAX_TOTAL_EXPOSURE_EUR", 9999.0))
FEE_MAKER        = float(CONFIG.get("FEE_MAKER", 0.0015))
FEE_TAKER        = float(CONFIG.get("FEE_TAKER", 0.0025))
SLIPPAGE         = float(CONFIG.get("SLIPPAGE_PCT", 0.001))

# Stepped trailing levels: [[activation_pct, trail_pct], ...]
_RAW_STEPPED = CONFIG.get("STEPPED_TRAILING_LEVELS", [])
STEPPED_LEVELS: List[Tuple[float, float]] = []
for _lvl in _RAW_STEPPED:
    try:
        STEPPED_LEVELS.append((float(_lvl[0]), float(_lvl[1])))
    except Exception:
        pass

# Partial TP: gebruik config of fallback
_TP_TARGETS = CONFIG.get("TAKE_PROFIT_TARGETS") or []
_TP_PCTS    = CONFIG.get("TAKE_PROFIT_PERCENTAGES") or []
PARTIAL_TP: List[Tuple[float, float]] = []
for _t, _p in zip(_TP_TARGETS, _TP_PCTS):
    try:
        PARTIAL_TP.append((float(_t), float(_p)))
    except Exception:
        pass
if not PARTIAL_TP:
    PARTIAL_TP = [(0.015, 0.30), (0.03, 0.30), (0.05, 0.40)]

# Grid config
GRID_NUM         = int(CONFIG.get("GRID_NUM_LEVELS", 10))
GRID_RANGE_PCT   = float(CONFIG.get("GRID_RANGE_PCT", 0.18))
GRID_INVESTMENT  = float(CONFIG.get("GRID_INVESTMENT_EUR", 60.0))
MAKER_FEE        = FEE_MAKER


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Candle:
    """OHLCV-candle (1 minuut of 1 uur voor simulatie)."""
    ts: float        # UNIX timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float    # volume in EUR


@dataclass
class Position:
    """Open handelspositie."""
    market: str
    buy_price: float          # gewogen gemiddelde inkoopprijs
    amount: float             # base currency hoeveelheid
    invested_eur: float       # totaal geïnvesteerd EUR (incl. DCA's)
    initial_invested: float   # eerste investering
    opened_ts: float
    dca_buys: int = 0
    highest_price: float = 0.0
    trailing_active: bool = False
    tp_flags: List[bool] = field(default_factory=lambda: [False] * len(PARTIAL_TP))
    last_dca_price: float = 0.0


@dataclass
class ClosedTrade:
    """Afgesloten handelspositie."""
    market: str
    buy_price: float
    sell_price: float
    amount: float
    invested_eur: float
    profit_eur: float
    profit_pct: float
    opened_ts: float
    closed_ts: float
    reason: str            # 'trailing_stop', 'hard_sl', 'partial_tp', 'full_tp', 'grid'
    dca_buys: int
    fees_paid: float


@dataclass
class GridLevel:
    price: float
    side: str              # 'buy' or 'sell'
    amount: float
    filled: bool = False
    profit: float = 0.0


@dataclass
class ComponentResult:
    """Resultaat van een component-validatietest."""
    name: str
    passed: bool
    detail: str
    value: Optional[float] = None


# ============================================================
# INDICATOR FUNCTIES (standalone, geen externe imports nodig)
# ============================================================

def _sma(prices: List[float], period: int) -> List[float]:
    """Simple Moving Average."""
    result = [float("nan")] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = statistics.mean(prices[i - period + 1 : i + 1])
    return result


def _ema(prices: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    result = [float("nan")] * len(prices)
    if len(prices) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = statistics.mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def _rsi(prices: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index."""
    result = [float("nan")] * len(prices)
    if len(prices) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = statistics.mean(gains[:period])
    avg_loss = statistics.mean(losses[:period])
    for i in range(period, len(prices) - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 1e-9 else 1e9
        result[i + 1] = 100 - (100 / (1 + rs))
    return result


def _macd(prices: List[float]) -> Tuple[List[float], List[float], List[float]]:
    """MACD: returns (macd_line, signal_line, histogram)."""
    fast = _ema(prices, MACD_FAST)
    slow = _ema(prices, MACD_SLOW)
    macd_line = [
        (f - s) if not math.isnan(f) and not math.isnan(s) else float("nan")
        for f, s in zip(fast, slow)
    ]
    # Signal is EMA of macd_line (skip NaNs)
    valid_start = next((i for i, v in enumerate(macd_line) if not math.isnan(v)), None)
    signal_line = [float("nan")] * len(macd_line)
    hist = [float("nan")] * len(macd_line)
    if valid_start is not None:
        sub = macd_line[valid_start:]
        sub_sig = _ema(sub, MACD_SIG_PERIOD)
        for i, (m, s) in enumerate(zip(sub, sub_sig)):
            idx = valid_start + i
            signal_line[idx] = s
            if not math.isnan(m) and not math.isnan(s):
                hist[idx] = m - s
            else:
                hist[idx] = float("nan")
    return macd_line, signal_line, hist


@dataclass
class PrecomputedIndicators:
    """Vooraf berekende indicator-arrays voor de hele candle-reeks (O(n) in plaats van O(n²))."""
    sma_s: List[float]
    sma_l: List[float]
    rsi_v: List[float]
    macd_h: List[float]
    volumes: List[float]


def precompute_indicators(closes: List[float], volumes: List[float]) -> PrecomputedIndicators:
    """Berekent alle indicators éénmalig voor de volledige candle-reeks."""
    _, _, macd_h = _macd(closes)
    return PrecomputedIndicators(
        sma_s=_sma(closes, SMA_SHORT),
        sma_l=_sma(closes, SMA_LONG),
        rsi_v=_rsi(closes),
        macd_h=macd_h,
        volumes=volumes,
    )


def _score_signal(ind: PrecomputedIndicators, idx: int) -> float:
    """
    Berekent entry-score (max ~12) op basis van vooraf berekende indicators.
    Zelfde logica als de echte bot: SMA crossover, RSI range, MACD, volume.
    """
    if idx < SMA_LONG:
        return 0.0

    score = 0.0

    # SMA crossover
    if not math.isnan(ind.sma_s[idx]) and not math.isnan(ind.sma_l[idx]):
        if ind.sma_s[idx] > ind.sma_l[idx]:
            score += 3.0
        if idx > 0 and not math.isnan(ind.sma_s[idx - 1]) and not math.isnan(ind.sma_l[idx - 1]):
            if ind.sma_s[idx - 1] <= ind.sma_l[idx - 1] and ind.sma_s[idx] > ind.sma_l[idx]:
                score += 2.0  # verse crossover bonus

    # RSI in koopzone
    if not math.isnan(ind.rsi_v[idx]):
        if RSI_MIN <= ind.rsi_v[idx] <= RSI_MAX:
            score += 2.0
        elif ind.rsi_v[idx] < RSI_MIN:
            score -= 1.0

    # MACD positief histogram
    if not math.isnan(ind.macd_h[idx]) and ind.macd_h[idx] > 0:
        score += 2.0

    # Volume boven 1.5x gemiddelde van afgelopen 20 candles
    if idx >= 20 and len(ind.volumes) > idx:
        avg_vol = statistics.mean(ind.volumes[max(0, idx - 20): idx])
        if avg_vol > 0 and ind.volumes[idx] > avg_vol * 1.5:
            score += 2.0

    return max(0.0, score)


# ============================================================
# SYNTHETISCHE PRIJSDATA GENERATIE
# ============================================================

def generate_candles(
    name: str,
    n: int = 1440,    # aantal candles (1440 = 30 dagen × 48 × 30min candles)
    start_price: float = 100.0,
    trend: float = 0.0,         # dagelijkse drift (0.001 = +0.1% per candle)
    volatility: float = 0.015,  # standaarddeviatie per candle
    seed: int = 42,
) -> List[Candle]:
    """
    Genereert realistische OHLCV-candles via geometric Brownian motion met
    autocorrelatie, volumespikes en periodieke trendomkeringen.
    """
    rng = random.Random(seed)
    candles: List[Candle] = []
    price = start_price
    ts = 1_700_000_000.0  # vaste starttijd voor reproduceerbaarheid

    for i in range(n):
        # Geometric Brownian Motion met drift
        ret = rng.gauss(trend, volatility)
        # Occasionele schok (fat tail) — 2% kans op 3× normale beweeglijkheid
        if rng.random() < 0.02:
            ret *= 3.0

        open_ = price
        close = max(0.01, price * (1 + ret))

        # Intra-candle high/low (realistisch: high > max(open, close))
        intra_range = abs(ret) * rng.uniform(1.2, 2.5)
        high = max(open_, close) * (1 + rng.uniform(0, intra_range))
        low  = min(open_, close) * (1 - rng.uniform(0, intra_range))
        low  = max(0.001, low)

        # Volume: log-normaal + spike correlatie met beweeglijkheid
        base_vol = rng.lognormvariate(3, 1) * 1000
        if abs(ret) > volatility * 2:
            base_vol *= rng.uniform(1.5, 4.0)

        candles.append(Candle(
            ts=ts,
            open=round(open_, 6),
            high=round(high, 6),
            low=round(low, 6),
            close=round(close, 6),
            volume=round(base_vol, 2),
        ))
        price = close
        ts += 1800  # 30-minuut candles

    return candles


# ============================================================
# TRAILING STOP LOGICA (spiegelt echte bot)
# ============================================================

def _get_stepped_trailing(profit_pct: float) -> float:
    """
    Bepaalt de toepasselijke trailing-callback op basis van stepped levels.
    Neemt het hoogste niveau dat de huidige winst overschrijdt.
    """
    if not STEPPED_LEVELS:
        return TRAIL_PCT
    best_trail = TRAIL_PCT
    for act_pct, trail in STEPPED_LEVELS:
        if profit_pct >= act_pct:
            best_trail = trail
        else:
            break
    return best_trail


def _check_trailing_exit(pos: Position, current: float) -> Optional[str]:
    """
    Controleert trailing stop exit condities.
    Retourneert reden-string als er verkocht moet worden, anders None.
    """
    profit_pct = (current - pos.buy_price) / pos.buy_price if pos.buy_price > 0 else 0.0

    # Trailing activatie
    if profit_pct >= TRAIL_ACT_PCT:
        pos.trailing_active = True

    if current > pos.highest_price:
        pos.highest_price = current

    # Hard stop-loss (altijd actief)
    if current <= pos.buy_price * (1 - HARD_SL_PCT):
        return "hard_sl"

    # Trailing stop (alleen na activatie)
    if pos.trailing_active and pos.highest_price > 0:
        trail_pct = _get_stepped_trailing(
            (pos.highest_price - pos.buy_price) / pos.buy_price
        )
        stop_price = pos.highest_price * (1 - trail_pct)
        if current <= stop_price:
            return "trailing_stop"

    return None


# ============================================================
# GRID TRADING SIMULATIE
# ============================================================

def simulate_grid(candles: List[Candle], investment: float = GRID_INVESTMENT) -> Dict[str, Any]:
    """
    Simuleert grid trading over een reeks candles.
    Bij elke fill wordt een tegengestelde order geplaatst op het naburige grid-niveau.
    Retourneert statistieken: totale winst, cycles, fees.
    """
    if not candles:
        return {}

    mid = candles[0].close
    lower = mid * (1 - GRID_RANGE_PCT / 2)
    upper = mid * (1 + GRID_RANGE_PCT / 2)
    spacing = (upper - lower) / GRID_NUM

    # Bouw grid-levels
    levels: List[GridLevel] = []
    amount_per_level = (investment / GRID_NUM) / mid
    for i in range(GRID_NUM + 1):
        price = lower + i * spacing
        side = "buy" if price < mid else "sell"
        levels.append(GridLevel(price=price, side=side, amount=amount_per_level))

    total_profit = 0.0
    total_fees   = 0.0
    cycles       = 0
    rebalances   = 0

    for candle in candles:
        for lvl in levels:
            if lvl.filled:
                continue

            # Buy fill: candle laagste prijs raakt level
            if lvl.side == "buy" and candle.low <= lvl.price <= candle.high:
                cost = lvl.price * lvl.amount
                fee  = cost * MAKER_FEE
                lvl.filled = True
                total_fees += fee
                # Maak tegengestelde verkoop-order op naasthoger niveau
                sell_price = lvl.price + spacing
                idx = levels.index(lvl)
                if idx + 1 < len(levels):
                    sell_lvl = levels[idx + 1]
                    sell_lvl.side   = "sell"
                    sell_lvl.filled = False
                    sell_lvl.amount = lvl.amount
                    sell_lvl.price  = sell_price

            # Sell fill: candle hoogte raakt level
            elif lvl.side == "sell" and candle.low <= lvl.price <= candle.high:
                rev  = lvl.price * lvl.amount
                fee  = rev * MAKER_FEE
                gross_profit = spacing * lvl.amount - 2 * MAKER_FEE * lvl.price * lvl.amount
                lvl.filled = True
                total_fees   += fee
                total_profit += gross_profit
                cycles       += 1
                # Maak tegengestelde koop-order op naastlager niveau
                buy_price = lvl.price - spacing
                idx = levels.index(lvl)
                if idx - 1 >= 0:
                    buy_lvl = levels[idx - 1]
                    buy_lvl.side   = "buy"
                    buy_lvl.filled = False
                    buy_lvl.amount = lvl.amount

        # Herbalanceer als prijs buiten range valt
        if candle.close > upper * 1.05 or candle.close < lower * 0.95:
            mid   = candle.close
            lower = mid * (1 - GRID_RANGE_PCT / 2)
            upper = mid * (1 + GRID_RANGE_PCT / 2)
            for i, lvl in enumerate(levels):
                lvl.price  = lower + i * spacing
                lvl.filled = False
                lvl.side   = "buy" if lvl.price < mid else "sell"
            rebalances += 1

    net_profit = total_profit - total_fees
    days = len(candles) * 1800 / 86400 if candles else 1
    roi = net_profit / investment * 100 if investment > 0 else 0.0

    return {
        "total_profit_eur": round(total_profit, 4),
        "total_fees_eur":   round(total_fees, 4),
        "net_profit_eur":   round(net_profit, 4),
        "cycles":           cycles,
        "rebalances":       rebalances,
        "roi_pct":          round(roi, 2),
        "daily_profit":     round(net_profit / max(days, 1), 4),
    }


# ============================================================
# HOOFD BACKTEST SIMULATIE
# ============================================================

@dataclass
class BacktestResult:
    market: str
    total_profit_eur: float
    total_fees_eur: float
    net_profit_eur: float
    win_rate: float
    total_trades: int
    max_drawdown_pct: float
    sharpe_ratio: float
    roi_pct: float
    avg_hold_candles: float
    dca_triggers: int
    trailing_exits: int
    hard_sl_exits: int
    partial_tp_events: int
    max_open_simultaneous: int
    exposure_breach: bool
    component_results: List[ComponentResult]


def run_backtest(
    market: str,
    candles: List[Candle],
    *,
    ai_regime: str = "neutral",     # 'neutral', 'defensive', 'aggressive', 'halt'
    verbose: bool = False,
) -> BacktestResult:
    """
    Voert een volledige bot-simulatie uit over de opgegeven candles.
    Test elk component afzonderlijk en rapporteert PASS/FAIL.
    """
    if len(candles) < SMA_LONG + MACD_SLOW + 10:
        raise ValueError(f"Te weinig candles ({len(candles)}) voor backtest (min {SMA_LONG + MACD_SLOW + 10})")

    # AI regime multiplier voor positiegrootte
    regime_mult = {
        "neutral":   1.0,
        "defensive": 0.6,
        "aggressive": 1.2,
        "halt":      0.0,
    }.get(ai_regime, 1.0)

    closes  = [c.close  for c in candles]
    vols    = [c.volume for c in candles]
    highs   = [c.high   for c in candles]
    lows    = [c.low    for c in candles]

    # Precompute alle indicators éénmalig (O(n) in plaats van O(n²))
    ind = precompute_indicators(closes, vols)

    # Simulatie-staat
    open_positions: Dict[str, Position] = {}  # market_key → Position
    closed_trades_list: List[ClosedTrade] = []
    eur_balance = 1000.0   # startbalans voor simulatie
    total_fees  = 0.0
    max_open_simultaneous = 0
    exposure_breach = False
    dca_triggers   = 0
    trailing_exits = 0
    hard_sl_exits  = 0
    partial_tp_events  = 0

    # Trackers voor validatietests
    _max_dca_per_trade = 0
    _dca_above_max_seen = False
    _fees_missed = False
    _trailing_before_hard_sl_ok = True   # trailing moet activeren vóór hard SL

    last_open_ts: float = 0.0

    for idx in range(SMA_LONG + MACD_SLOW, len(candles)):
        candle = candles[idx]
        current_price = candle.close

        # ── 1. Beheer openstaande posities ──────────────────────────────
        for key in list(open_positions.keys()):
            pos = open_positions[key]
            pos_profit_pct = (current_price - pos.buy_price) / pos.buy_price

            # ── 1a. Partial take-profit ──────────────────────────────────
            for tp_idx, (tp_target, tp_sell_pct) in enumerate(PARTIAL_TP):
                if not pos.tp_flags[tp_idx] and pos_profit_pct >= tp_target:
                    sell_amount  = pos.amount * tp_sell_pct
                    sell_revenue = sell_amount * current_price
                    fee          = sell_revenue * FEE_TAKER
                    cost_portion = pos.invested_eur * tp_sell_pct
                    profit       = sell_revenue - fee - cost_portion
                    pos.amount   -= sell_amount
                    pos.invested_eur -= cost_portion
                    pos.tp_flags[tp_idx] = True
                    eur_balance += sell_revenue - fee
                    total_fees  += fee
                    partial_tp_events += 1
                    if verbose:
                        print(f"  [PARTIAL_TP lvl{tp_idx+1}] {market} +{tp_target*100:.1f}% → €{profit:.2f}")
                    if pos.amount <= 0:
                        break

            if pos.amount <= 0:
                # Positie volledig gesloten via partial TPs
                closed_trades_list.append(ClosedTrade(
                    market=market,
                    buy_price=pos.buy_price,
                    sell_price=current_price,
                    amount=0.0,
                    invested_eur=pos.initial_invested,
                    profit_eur=sum(
                        t.profit_eur for t in closed_trades_list
                        if t.market == market and t.opened_ts == pos.opened_ts
                    ),
                    profit_pct=pos_profit_pct * 100,
                    opened_ts=pos.opened_ts,
                    closed_ts=candle.ts,
                    reason="full_tp",
                    dca_buys=pos.dca_buys,
                    fees_paid=total_fees,
                ))
                del open_positions[key]
                continue

            # ── 1b. Trailing / hard SL exit ──────────────────────────────
            exit_reason = _check_trailing_exit(pos, current_price)
            if exit_reason:
                sell_revenue = pos.amount * current_price
                fee          = sell_revenue * FEE_TAKER
                profit_eur   = sell_revenue - fee - pos.invested_eur
                eur_balance += sell_revenue - fee
                total_fees  += fee

                if exit_reason == "trailing_stop":
                    trailing_exits += 1
                    # Validatie: trailing_active moet True zijn
                    if not pos.trailing_active:
                        _trailing_before_hard_sl_ok = False
                elif exit_reason == "hard_sl":
                    hard_sl_exits += 1
                    # Validatie: als trailing actief was had het eerder moeten stoppen
                    if pos.trailing_active and pos_profit_pct > 0:
                        _trailing_before_hard_sl_ok = False

                ct = ClosedTrade(
                    market=market,
                    buy_price=pos.buy_price,
                    sell_price=current_price,
                    amount=pos.amount,
                    invested_eur=pos.initial_invested,
                    profit_eur=profit_eur,
                    profit_pct=pos_profit_pct * 100,
                    opened_ts=pos.opened_ts,
                    closed_ts=candle.ts,
                    reason=exit_reason,
                    dca_buys=pos.dca_buys,
                    fees_paid=fee,
                )
                closed_trades_list.append(ct)
                del open_positions[key]
                continue

            # ── 1c. DCA trigger ──────────────────────────────────────────
            if (
                pos.dca_buys < DCA_MAX
                and pos.dca_buys < 99  # extra veiligheidsgrens
                and current_price <= pos.buy_price * (1 - DCA_DROP * (pos.dca_buys + 1))
                and eur_balance >= DCA_AMOUNT_EUR * 0.5
            ):
                dca_eur    = min(DCA_AMOUNT_EUR, eur_balance * 0.3)
                fee        = dca_eur * FEE_TAKER
                new_amount = (dca_eur - fee) / current_price
                # Gewogen gemiddelde inkoopprijs herberekenen
                total_cost   = pos.invested_eur + dca_eur
                total_amount = pos.amount + new_amount
                pos.buy_price    = total_cost / total_amount if total_amount > 0 else pos.buy_price
                pos.amount       = total_amount
                pos.invested_eur = total_cost
                pos.dca_buys    += 1
                pos.trailing_active = False   # reset trailing na DCA
                pos.highest_price   = current_price
                eur_balance -= dca_eur
                total_fees  += fee
                dca_triggers += 1

                if pos.dca_buys > DCA_MAX:
                    _dca_above_max_seen = True
                _max_dca_per_trade = max(_max_dca_per_trade, pos.dca_buys)

                if verbose:
                    print(f"  [DCA #{pos.dca_buys}] {market} @ {current_price:.4f} (avg: {pos.buy_price:.4f})")

        # ── 2. Exposure-check ────────────────────────────────────────────
        total_exposure = sum(p.invested_eur for p in open_positions.values())
        if total_exposure > MAX_EXPOSURE and MAX_EXPOSURE < 9999:
            exposure_breach = True

        # ── 3. Kandidaat voor entry? ─────────────────────────────────────
        if (
            len(open_positions) < MAX_TRADES
            and regime_mult > 0
            and eur_balance >= BASE_EUR * 0.5
        ):
            score = _score_signal(ind, idx)
            if score >= MIN_SCORE:
                trade_eur = BASE_EUR * regime_mult
                trade_eur = min(trade_eur, eur_balance * 0.95)
                if trade_eur >= 5.0:
                    entry_price = current_price * (1 + SLIPPAGE)
                    fee = trade_eur * FEE_TAKER
                    amount = (trade_eur - fee) / entry_price
                    pos_key = f"{market}_{candle.ts}"

                    open_positions[pos_key] = Position(
                        market=market,
                        buy_price=entry_price,
                        amount=amount,
                        invested_eur=trade_eur,
                        initial_invested=trade_eur,
                        opened_ts=candle.ts,
                        highest_price=entry_price,
                        tp_flags=[False] * len(PARTIAL_TP),
                    )
                    eur_balance -= trade_eur
                    total_fees  += fee
                    last_open_ts = candle.ts

                    max_open_simultaneous = max(max_open_simultaneous, len(open_positions))

                    if verbose:
                        print(f"  [ENTRY] {market} score={score:.1f} @ {entry_price:.4f} €{trade_eur:.2f}")

    # ── 4. Sluit resterende posities op laatste prijs ────────────────────
    final_price = candles[-1].close
    for key, pos in list(open_positions.items()):
        sell_revenue = pos.amount * final_price
        fee = sell_revenue * FEE_TAKER
        profit_eur = sell_revenue - fee - pos.invested_eur
        eur_balance += sell_revenue - fee
        total_fees  += fee
        closed_trades_list.append(ClosedTrade(
            market=market,
            buy_price=pos.buy_price,
            sell_price=final_price,
            amount=pos.amount,
            invested_eur=pos.initial_invested,
            profit_eur=profit_eur,
            profit_pct=(final_price - pos.buy_price) / pos.buy_price * 100,
            opened_ts=pos.opened_ts,
            closed_ts=candles[-1].ts,
            reason="end_of_backtest",
            dca_buys=pos.dca_buys,
            fees_paid=fee,
        ))

    # ── 5. Statistieken berekenen ────────────────────────────────────────
    n_trades = len(closed_trades_list)
    if n_trades > 0:
        profits    = [t.profit_eur for t in closed_trades_list]
        win_rate   = sum(1 for p in profits if p > 0) / n_trades
        total_pnl  = sum(profits)
        net_pnl    = total_pnl - total_fees

        # Max drawdown via equity curve
        equity = 1000.0
        equity_curve: List[float] = [equity]
        for p in profits:
            equity += p
            equity_curve.append(equity)
        peak = equity_curve[0]
        max_dd = 0.0
        for e in equity_curve:
            if e > peak:
                peak = e
            dd = (peak - e) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        # Sharpe ratio (daily returns, rf=0)
        hold_secs  = [(t.closed_ts - t.opened_ts) for t in closed_trades_list]
        avg_hold   = statistics.mean(hold_secs) / 1800 if hold_secs else 0
        if len(profits) >= 2:
            mean_r = statistics.mean(profits)
            std_r  = statistics.stdev(profits)
            sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
        else:
            sharpe = 0.0

        roi = total_pnl / 1000.0 * 100
    else:
        win_rate = 0.0
        total_pnl = net_pnl = 0.0
        max_dd = 0.0
        sharpe = 0.0
        roi = 0.0
        avg_hold = 0.0

    # ── 6. Component-validatietests ──────────────────────────────────────
    comp = []

    # TEST 1: DCA nooit boven DCA_MAX
    comp.append(ComponentResult(
        name="DCA limiet (max_buys)",
        passed=not _dca_above_max_seen and _max_dca_per_trade <= DCA_MAX,
        detail=(
            f"Max DCA buys gezien: {_max_dca_per_trade} (limiet: {DCA_MAX})"
            if not _dca_above_max_seen
            else f"FOUT: DCA boven max ({_max_dca_per_trade} > {DCA_MAX})"
        ),
        value=float(_max_dca_per_trade),
    ))

    # TEST 2: MAX_OPEN_TRADES nooit overschreden
    comp.append(ComponentResult(
        name="MAX_OPEN_TRADES limiet",
        passed=max_open_simultaneous <= MAX_TRADES,
        detail=f"Maximaal {max_open_simultaneous} gelijktijdige posities (limiet: {MAX_TRADES})",
        value=float(max_open_simultaneous),
    ))

    # TEST 3: Fees zijn altijd ingehouden (elke trade heeft fee > 0)
    fees_ok = all(t.fees_paid > 0 for t in closed_trades_list) if closed_trades_list else True
    comp.append(ComponentResult(
        name="Fee-inhouding",
        passed=fees_ok,
        detail=f"Alle {n_trades} trades hadden fees > 0" if fees_ok else "FOUT: Trade(s) zonder fee gevonden",
    ))

    # TEST 4: Trailing stop activeert voor hard SL in winstscenario
    comp.append(ComponentResult(
        name="Trailing stop vóór hard SL",
        passed=_trailing_before_hard_sl_ok,
        detail=(
            "Trailing stop correct geactiveerd vóór hard SL"
            if _trailing_before_hard_sl_ok
            else "WAARSCHUWING: Hard SL sloeg in terwijl trailing actief was"
        ),
    ))

    # TEST 5: Bij AI halt regime wordt er niet gehandeld
    halt_ok = True
    if ai_regime == "halt":
        halt_ok = n_trades == 0
    comp.append(ComponentResult(
        name="AI-regime halt blokkering",
        passed=halt_ok,
        detail=(
            f"halt-regime: {n_trades} trades (verwacht: 0)"
            if ai_regime == "halt"
            else f"regime={ai_regime}, geen halt-blokkering nodig"
        ),
    ))

    # TEST 6: Hard SL exits zijn ≤ HARD_SL_PCT verlies
    hard_sl_ok = True
    worst_hard_sl = 0.0
    for t in closed_trades_list:
        if t.reason == "hard_sl":
            loss_pct = abs((t.sell_price - t.buy_price) / t.buy_price)
            worst_hard_sl = max(worst_hard_sl, loss_pct)
            # Marge van 5% voor slippage + fees in simulatie
            if loss_pct > HARD_SL_PCT * 1.10:
                hard_sl_ok = False
    comp.append(ComponentResult(
        name="Hard SL exit-niveau",
        passed=hard_sl_ok,
        detail=(
            f"Hard SL exits binnen bandbreedte (worst: -{worst_hard_sl*100:.1f}%, limiet: -{HARD_SL_PCT*100:.1f}%)"
            if hard_sl_ok
            else f"FOUT: Hard SL te laat ingegrepen (worst: -{worst_hard_sl*100:.1f}%)"
        ),
        value=round(worst_hard_sl * 100, 2),
    ))

    # TEST 7: Exposure nooit boven MAX_EXPOSURE (als ingesteld)
    comp.append(ComponentResult(
        name="Exposure limiet",
        passed=not exposure_breach,
        detail=(
            "Exposure altijd binnen MAX_EXPOSURE"
            if not exposure_breach
            else f"WAARSCHUWING: Exposure limiet (€{MAX_EXPOSURE}) overschreden"
        ),
    ))

    # TEST 8: Partial TP werd minimaal 1× geactiveerd als er winst-trades zijn
    profit_trades = [t for t in closed_trades_list if t.profit_pct > PARTIAL_TP[0][0] * 100 * 0.5]
    partial_tp_ok = partial_tp_events > 0 if profit_trades else True
    comp.append(ComponentResult(
        name="Partial TP activering",
        passed=partial_tp_ok,
        detail=(
            f"{partial_tp_events} partial TP events voor {len(profit_trades)} winstkandidaten"
            if partial_tp_ok
            else "WAARSCHUWING: Geen partial TP events ondanks winstbare trades"
        ),
        value=float(partial_tp_events),
    ))

    return BacktestResult(
        market=market,
        total_profit_eur=round(total_pnl, 2),
        total_fees_eur=round(total_fees, 2),
        net_profit_eur=round(net_pnl, 2),
        win_rate=round(win_rate * 100, 1),
        total_trades=n_trades,
        max_drawdown_pct=round(max_dd * 100, 2),
        sharpe_ratio=round(sharpe, 3),
        roi_pct=round(roi, 2),
        avg_hold_candles=round(avg_hold, 1),
        dca_triggers=dca_triggers,
        trailing_exits=trailing_exits,
        hard_sl_exits=hard_sl_exits,
        partial_tp_events=partial_tp_events,
        max_open_simultaneous=max_open_simultaneous,
        exposure_breach=exposure_breach,
        component_results=comp,
    )


# ============================================================
# RAPPORTAGE
# ============================================================

def _pass_fail(b: bool) -> str:
    return "[PASS]" if b else "[FAIL]"


def print_report(
    results: List[BacktestResult],
    grid_results: Dict[str, Dict[str, Any]],
) -> int:
    """Print volledig backtest-rapport. Retourneert aantal mislukte tests."""
    sep = "-" * 68
    hw  = "=" * 68

    print(f"\n{hw}")
    print("  FULL BOT BACKTEST RAPPORT")
    print(f"  Gegenereerd: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(hw)
    sys.stdout.flush()

    all_components: List[ComponentResult] = []
    total_fails = 0

    for res in results:
        print(f"\n[MARKT: {res.market}]")
        print(sep)
        print(f"  Trades:          {res.total_trades}")
        print(f"  Win-rate:        {res.win_rate:.1f}%")
        print(f"  Bruto winst:     €{res.total_profit_eur:.2f}")
        print(f"  Fees betaald:    €{res.total_fees_eur:.2f}")
        print(f"  Netto winst:     €{res.net_profit_eur:.2f}")
        print(f"  ROI:             {res.roi_pct:.2f}%")
        print(f"  Max drawdown:    {res.max_drawdown_pct:.2f}%")
        print(f"  Sharpe ratio:    {res.sharpe_ratio:.3f}")
        print(f"  Gem. looptijd:   {res.avg_hold_candles:.1f} candles")
        print(f"  DCA-triggers:    {res.dca_triggers}")
        print(f"  Trailing exits:  {res.trailing_exits}")
        print(f"  Hard SL exits:   {res.hard_sl_exits}")
        print(f"  Partial TP:      {res.partial_tp_events}")

        print(f"\n  COMPONENT-TESTS:")
        for cr in res.component_results:
            status = _pass_fail(cr.passed)
            print(f"    {status}  {cr.name}")
            print(f"           {cr.detail}")
            all_components.append(cr)
            if not cr.passed:
                total_fails += 1

    # Grid resultaten
    if grid_results:
        print(f"\n[GRID TRADING SIMULATIE]")
        print(sep)
        for mkt, gr in grid_results.items():
            print(f"  {mkt}:")
            print(f"    Cycles:       {gr.get('cycles', 0)}")
            print(f"    Netto winst:  €{gr.get('net_profit_eur', 0):.4f}")
            print(f"    ROI:          {gr.get('roi_pct', 0):.2f}%")
            print(f"    Rebalances:   {gr.get('rebalances', 0)}")
            print(f"    Dag-winst:    €{gr.get('daily_profit', 0):.4f}")

            grid_ok = gr.get("net_profit_eur", 0) >= 0 or gr.get("cycles", 0) == 0
            status = _pass_fail(grid_ok)
            print(f"    {status}  Grid profitable (of geen fills)")
            if not grid_ok:
                total_fails += 1

    # Samenvatting
    total_tests = len(all_components) + len(grid_results)
    passed_tests = sum(1 for c in all_components if c.passed) + sum(
        1 for gr in grid_results.values()
        if gr.get("net_profit_eur", 0) >= 0 or gr.get("cycles", 0) == 0
    )

    print(f"\n{hw}")
    print(f"  SAMENVATTING")
    print(sep)
    print(f"  Tests geslaagd:   {passed_tests}/{total_tests}")
    print(f"  Tests mislukt:    {total_fails}")

    overall_eur = sum(r.net_profit_eur for r in results) + sum(
        gr.get("net_profit_eur", 0) for gr in grid_results.values()
    )
    print(f"  Totale netto P&L: €{overall_eur:.2f}")
    print(
        f"  Algeheel verdict: "
        + (_pass_fail(True) + "  (all components OK)" if total_fails == 0
           else _pass_fail(False) + f"  ({total_fails} issues gevonden)")
    )
    print(hw)

    return total_fails


# ============================================================
# OPTIONEEL: echte candles laden via Bitvavo API
# ============================================================

def fetch_real_candles(market: str, days: int = 30) -> List[Candle]:
    """Haalt echte historische candles op via Bitvavo API (1h interval)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from python_bitvavo_api.bitvavo import Bitvavo as BV
        api_key    = os.getenv("BITVAVO_API_KEY", "")
        api_secret = os.getenv("BITVAVO_API_SECRET", "")
        bv = BV({"APIKEY": api_key, "APISECRET": api_secret, "RESTURL": "https://api.bitvavo.com/v2", "ACCESSWINDOW": 10000})
    except ImportError:
        print("[WARN] python_bitvavo_api niet beschikbaar — gebruik synthetic data")
        return []

    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    # Bitvavo limit = 1440 per call; ophalen in batches
    result: List[Candle] = []
    chunk_ms = 1440 * 3600 * 1000  # 1440 uur per batch
    curr_start = start_ms
    while curr_start < end_ms:
        curr_end = min(curr_start + chunk_ms, end_ms)
        try:
            raw = bv.candles(market, "1h", {"start": curr_start, "end": curr_end, "limit": 1440})
            if isinstance(raw, list):
                for r in raw:
                    try:
                        result.append(Candle(
                            ts=float(r[0]) / 1000,
                            open=float(r[1]),
                            high=float(r[2]),
                            low=float(r[3]),
                            close=float(r[4]),
                            volume=float(r[5]),
                        ))
                    except Exception:
                        continue
            time.sleep(0.2)
        except Exception as e:
            print(f"[WARN] Candles ophalen mislukt voor {market}: {e}")
            break
        curr_start = curr_end

    # Sorteer op timestamp
    result.sort(key=lambda c: c.ts)
    return result


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    # Forceer UTF-8 output op Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Full Bot Backtest")
    parser.add_argument("--real",   action="store_true", help="Gebruik echte Bitvavo candles")
    parser.add_argument("--days",   type=int, default=30, help="Aantal dagen historische data")
    parser.add_argument("--seed",   type=int, default=42, help="Random seed voor reproduceerbare resultaten")
    parser.add_argument("--verbose",action="store_true", help="Toon iedere trade-actie")
    parser.add_argument(
        "--markets", nargs="+",
        default=["BTC-EUR", "ETH-EUR", "SOL-EUR"],
        help="Markten voor backtest (alleen relevant bij --real)"
    )
    args = parser.parse_args()

    print(f"\n{'='*68}")
    print("  BITVAVO BOT - VOLLEDIGE BACKTEST")
    print(f"  Config:  {_CONFIG_PATH}")
    print(f"  Mode:    {'echte Bitvavo data' if args.real else 'synthetische data'}")
    print(f"  Periode: {args.days} dagen")
    print(f"  Seed:    {args.seed}")
    print(f"{'='*68}\n")

    print("Config-samenvatting:")
    print(f"  SMA: {SMA_SHORT}/{SMA_LONG} | RSI: {RSI_MIN}-{RSI_MAX} | MIN_SCORE: {MIN_SCORE}")
    print(f"  BASE_EUR: €{BASE_EUR} | MAX_TRADES: {MAX_TRADES} | DCA_MAX: {DCA_MAX}")
    print(f"  Trailing: activatie={TRAIL_ACT_PCT*100:.1f}%, callback={TRAIL_PCT*100:.1f}%")
    print(f"  Hard SL: -{HARD_SL_PCT*100:.1f}% | Partial TP: {PARTIAL_TP}")
    print(f"  Gestepte trailing: {len(STEPPED_LEVELS)} niveaus")
    print()

    # Candle-sets per scenario
    n_candles = args.days * 48  # 48 × 30-min candles = 1 dag

    scenarios = [
        # (naam,      trend,   volatility, start_price, seed_offset)
        ("bullish",  +0.0008,  0.012,      100.0,       0),
        ("bearish",  -0.0006,  0.015,      100.0,       1),
        ("ranging",  +0.0001,  0.018,      100.0,       2),
    ]

    results: List[BacktestResult] = []
    grid_results: Dict[str, Dict[str, Any]] = {}

    for i, market in enumerate(args.markets):
        if args.real:
            print(f"Ophalen echte data: {market} ({args.days}d)...", end=" ", flush=True)
            candles = fetch_real_candles(market, args.days)
            if not candles:
                print(f"geen data, valt terug op synthetic")
                name, trend, vol, start, soff = scenarios[i % len(scenarios)]
                candles = generate_candles(market, n_candles, start, trend, vol, args.seed + soff)
            else:
                print(f"{len(candles)} candles opgehaald")
        else:
            name, trend, vol, start, soff = scenarios[i % len(scenarios)]
            candles = generate_candles(market, n_candles, start, trend, vol, args.seed + soff)
            print(f"Synthetisch scenario '{name}': {len(candles)} candles voor {market}")

        # Trailing-bot simulatie
        res = run_backtest(market, candles, ai_regime="neutral", verbose=args.verbose)
        results.append(res)

        # Grid simulatie (op dezelfde candles)
        gr = simulate_grid(candles)
        grid_results[f"{market} (grid)"] = gr

    # Halt-regime test (geen trades verwacht)
    print("\nHalt-regime test (AI halt → geen trades)...")
    halt_market  = args.markets[0] + "_HALT"
    halt_candles = generate_candles(halt_market, n_candles, 100.0, 0.001, 0.015, args.seed + 99)
    halt_res     = run_backtest(halt_market, halt_candles, ai_regime="halt", verbose=False)
    results.append(halt_res)

    # Rapport
    fails = print_report(results, grid_results)

    # Sla resultaten op als JSON
    out_path = PROJECT_ROOT / "reports" / f"full_backtest_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "config_snapshot": {
                    "SMA_SHORT": SMA_SHORT, "SMA_LONG": SMA_LONG,
                    "RSI_MIN": RSI_MIN, "RSI_MAX": RSI_MAX,
                    "MIN_SCORE": MIN_SCORE, "BASE_EUR": BASE_EUR,
                    "DCA_MAX": DCA_MAX, "DCA_DROP_PCT": DCA_DROP,
                    "TRAIL_PCT": TRAIL_PCT, "TRAIL_ACT_PCT": TRAIL_ACT_PCT,
                    "HARD_SL_PCT": HARD_SL_PCT, "MAX_TRADES": MAX_TRADES,
                },
                "trailing_bot_results": [
                    {
                        "market": r.market,
                        "net_profit_eur": r.net_profit_eur,
                        "win_rate_pct": r.win_rate,
                        "total_trades": r.total_trades,
                        "max_drawdown_pct": r.max_drawdown_pct,
                        "sharpe": r.sharpe_ratio,
                        "roi_pct": r.roi_pct,
                        "dca_triggers": r.dca_triggers,
                        "trailing_exits": r.trailing_exits,
                        "hard_sl_exits": r.hard_sl_exits,
                        "partial_tp_events": r.partial_tp_events,
                        "component_tests": [
                            {"name": c.name, "passed": c.passed, "detail": c.detail}
                            for c in r.component_results
                        ],
                    }
                    for r in results
                ],
                "grid_results": {k: v for k, v in grid_results.items()},
                "total_fails": fails,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nResultaten opgeslagen: {out_path.relative_to(PROJECT_ROOT)}")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    main()
