import numpy as np
from typing import List, Optional, Tuple

def ema(vals: List[float], w: int) -> Optional[float]:
    """Exponential moving average of last w values. Returns None if insufficient data."""
    if len(vals) < w: return None
    k = 2 / (w + 1)
    e = [vals[0]]
    for x in vals[1:]:
        e.append(x * k + e[-1] * (1 - k))
    return float(e[-1])

def bollinger_bands(vals: List[float], w: int = 20, num_std: int = 2) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (upper, middle, lower) bands or (None, None, None) if insufficient data."""
    if len(vals) < w: return None, None, None
    ma = np.mean(vals[-w:])
    std = np.std(vals[-w:])
    upper = ma + num_std * std
    lower = ma - num_std * std
    return float(upper), float(ma), float(lower)

def stochastic(vals: List[float], w: int = 14) -> Optional[float]:
    """Stochastic oscillator %K over window w. Returns None if insufficient data."""
    if len(vals) < w: return None
    high = max(vals[-w:])
    low = min(vals[-w:])
    close = vals[-1]
    return 100 * (close - low) / (high - low) if high != low else None

def get_min_order_size(market: str, bitvavo, safe_call) -> float:
    """Return Bitvavo min order size/amount for market (best-effort)."""
    info = safe_call(bitvavo.markets, {"market": market})
    if info and isinstance(info, list) and len(info) > 0:
        min_base = info[0].get("minOrderInBaseAsset")
        if min_base:
            return float(min_base)
        min_size = info[0].get("minOrderSize")
        min_amount = info[0].get("minOrderAmount")
        return float(min_size or min_amount or 0)
    return 0.0

def get_expected_slippage(market: str, amount_eur: float, entry_price: float, get_ticker_best_bid_ask) -> Optional[float]:
    """Estimate slippage using orderbook depth approximation. Returns None if unavailable."""
    book = get_ticker_best_bid_ask(market)
    if not book: return None
    # ...implementatie...

def sma(vals: List[float], w: int) -> Optional[float]: return float(np.mean(vals[-w:])) if len(vals)>=w else None

def rsi(vals: List[float], period: int = 14) -> Optional[float]:
    if len(vals)<period+1: return None
    deltas=np.diff(vals); gains=deltas[deltas>0].sum()/period
    losses=-deltas[deltas<0].sum()/period
    if losses==0: return 100
    rs=gains/losses; return 100-(100/(1+rs))

def macd(vals: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(vals)<slow+signal: return None,None,None
    def ema_inner(v,n):
        k=2/(n+1); e=[v[0]]
        for x in v[1:]: e.append(x*k+e[-1]*(1-k))
        return e
    ef,es=ema_inner(vals,fast),ema_inner(vals,slow)
    macd_line=[f-s for f,s in zip(ef[-len(es):],es)]
    sig=ema_inner(macd_line,signal)
    return macd_line[-1],sig[-1],macd_line[-1]-sig[-1]

def atr(h: List[float], l: List[float], c: List[float], window: int = 14) -> Optional[float]:
    if len(h)<window+1: return None
    trs=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return float(np.mean(trs[-window:]))

def close_prices(c) -> List[float]: return [float(x[4]) for x in c if len(x) > 4]
def highs(c) -> List[float]: return [float(x[1]) for x in c if len(x) > 1]
def lows(c) -> List[float]: return [float(x[2]) for x in c if len(x) > 2]
def volumes(c) -> List[float]: return [float(x[5]) for x in c if len(x) > 5]
