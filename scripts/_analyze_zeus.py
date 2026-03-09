"""Analyze ZEUS-EUR for grid bot suitability."""
import os, json, time
from dotenv import load_dotenv
load_dotenv()
from python_bitvavo_api.bitvavo import Bitvavo

bv = Bitvavo({
    'APIKEY': os.getenv('BITVAVO_API_KEY', ''),
    'APISECRET': os.getenv('BITVAVO_API_SECRET', ''),
})

# 1. Current ticker
ticker = bv.tickerPrice({'market': 'ZEUS-EUR'})
print(f"Current price: {ticker}")

# 2. 24h stats
t24 = bv.ticker24h({'market': 'ZEUS-EUR'})
print(f"24h volume: EUR {float(t24.get('volume','0')) * float(t24.get('last','1')):,.0f}")
print(f"24h high: {t24.get('high')}, low: {t24.get('low')}, last: {t24.get('last')}")

# 3. Get 90 days of daily candles
end = int(time.time() * 1000)
start = end - (90 * 24 * 60 * 60 * 1000)
candles = bv.candles('ZEUS-EUR', '1d', {'start': start, 'end': end})
print(f"\nCandles (90d): {len(candles)} days")

# Also get BTC and ETH for comparison
btc_candles = bv.candles('BTC-EUR', '1d', {'start': start, 'end': end})
eth_candles = bv.candles('ETH-EUR', '1d', {'start': start, 'end': end})

def analyze(name, candles_data):
    if not candles_data:
        print(f"\n{name}: No data")
        return {}
    
    prices = []
    volumes = []
    daily_ranges = []
    for c in candles_data:
        o, h, l, cl, vol = float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])
        prices.append(cl)
        volumes.append(vol * cl)
        if o > 0:
            daily_ranges.append((h - l) / o * 100)
    
    high = max(float(c[2]) for c in candles_data)
    low = min(float(c[3]) for c in candles_data)
    current = prices[-1]
    
    print(f"\n{'='*50}")
    print(f"{name} - 90 Day Analysis")
    print(f"{'='*50}")
    print(f"Price range: EUR {low:.4f} - EUR {high:.4f}")
    print(f"Current: EUR {current:.4f}")
    print(f"Range ratio: {high/low:.1f}x (high/low)")
    print(f"From 90d high: {(current - high) / high * 100:.1f}%")
    print(f"From 90d low: {(current - low) / low * 100:.1f}%")
    
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    print(f"\nAvg daily volume: EUR {avg_vol:,.0f}")
    print(f"Min daily volume: EUR {min(volumes):,.0f}")
    
    avg_range = sum(daily_ranges) / len(daily_ranges) if daily_ranges else 0
    print(f"\nAvg daily range: {avg_range:.2f}%")
    print(f"Max daily range: {max(daily_ranges):.2f}%")
    days_5 = sum(1 for r in daily_ranges if r > 5)
    days_10 = sum(1 for r in daily_ranges if r > 10)
    days_20 = sum(1 for r in daily_ranges if r > 20)
    print(f"Days > 5% range: {days_5}/{len(daily_ranges)}")
    print(f"Days > 10% range: {days_10}/{len(daily_ranges)}")
    print(f"Days > 20% range: {days_20}/{len(daily_ranges)}")
    
    # Trend
    if len(prices) >= 30:
        ma30 = sum(prices[-30:]) / 30
        ma7 = sum(prices[-7:]) / 7
        trend = "BULLISH" if ma7 > ma30 else "BEARISH"
        print(f"\nMA7: EUR {ma7:.4f}, MA30: EUR {ma30:.4f} -> {trend}")
    
    # Volatility
    returns = []
    if len(prices) >= 2:
        returns = [(prices[i] - prices[i-1]) / prices[i-1] * 100 for i in range(1, len(prices))]
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r - avg_ret)**2 for r in returns) / len(returns)) ** 0.5
        ann_vol = std_ret * (365**0.5)
        pos_days = sum(1 for r in returns if r > 0)
        print(f"\nDaily return std: {std_ret:.2f}%")
        print(f"Annualized volatility: {ann_vol:.1f}%")
        print(f"Up days: {pos_days}/{len(returns)} ({pos_days/len(returns)*100:.0f}%)")
        
        # Max drawdown
        max_dd = 0
        peak = prices[0]
        for p in prices:
            if p > peak:
                peak = p
            dd = (peak - p) / peak * 100
            if dd > max_dd:
                max_dd = dd
        print(f"Max drawdown: {max_dd:.1f}%")
    
    # Grid suitability: mean reversion check
    # Count how many times price crosses the median
    if len(prices) >= 10:
        median = sorted(prices)[len(prices)//2]
        crosses = 0
        above = prices[0] > median
        for p in prices[1:]:
            now_above = p > median
            if now_above != above:
                crosses += 1
                above = now_above
        print(f"\nMedian crosses (mean-reversion proxy): {crosses}")
        print(f"Crosses per 30d: {crosses / (len(prices)/30):.1f}")
    
    return {
        'avg_range': avg_range,
        'avg_vol': avg_vol,
        'min_vol': min(volumes) if volumes else 0,
        'ann_vol': std_ret * (365**0.5) if returns else 0,
        'max_dd': max_dd if returns else 0,
        'crosses': crosses if len(prices) >= 10 else 0,
        'high_low_ratio': high / low if low > 0 else 0,
        'current': current,
        'up_pct': pos_days / len(returns) * 100 if returns else 0,
    }

zeus = analyze("ZEUS-EUR", candles)
btc = analyze("BTC-EUR", btc_candles)
eth = analyze("ETH-EUR", eth_candles)

# Grid bot simulation for ZEUS
print(f"\n{'='*50}")
print("GRID BOT SUITABILITY COMPARISON")
print(f"{'='*50}")
print(f"{'Metric':<30} {'ZEUS':>10} {'BTC':>10} {'ETH':>10}")
print(f"{'-'*30} {'-'*10} {'-'*10} {'-'*10}")
for metric, label in [
    ('avg_range', 'Avg daily range %'),
    ('ann_vol', 'Annualized volatility %'),
    ('avg_vol', 'Avg daily volume EUR'),
    ('min_vol', 'Min daily volume EUR'),
    ('max_dd', 'Max drawdown %'),
    ('crosses', 'Median crosses (90d)'),
    ('high_low_ratio', 'High/Low ratio'),
    ('up_pct', 'Up days %'),
]:
    z = zeus.get(metric, 0)
    b = btc.get(metric, 0)
    e = eth.get(metric, 0)
    if metric in ('avg_vol', 'min_vol'):
        print(f"{label:<30} {z:>10,.0f} {b:>10,.0f} {e:>10,.0f}")
    else:
        print(f"{label:<30} {z:>10.1f} {b:>10.1f} {e:>10.1f}")

# Critical check: minimum order size feasibility
print(f"\n{'='*50}")
print("KRITIEKE CHECKS")
print(f"{'='*50}")
zeus_price = zeus.get('current', 0)
if zeus_price > 0:
    print(f"ZEUS prijs: EUR {zeus_price:.4f}")
    min_order_eur = 5.50  # Bitvavo minimum
    coins_per_order = min_order_eur / zeus_price
    print(f"Min order (EUR 5.50) = {coins_per_order:.2f} ZEUS")
    
    # With 50 EUR per grid, 5 levels
    per_level = 50 / 5
    print(f"Per grid level (EUR50/5): EUR {per_level:.2f}")
    ok = "OK" if per_level >= min_order_eur else "TE LAAG"
    print(f"Order size check: {ok}")
    
    # Spread check
    book = bv.book('ZEUS-EUR', {'depth': 10})
    if 'bids' in book and 'asks' in book and book['bids'] and book['asks']:
        best_bid = float(book['bids'][0][0])
        best_ask = float(book['asks'][0][0])
        spread_pct = (best_ask - best_bid) / best_bid * 100
        bid_depth = sum(float(b[0]) * float(b[1]) for b in book['bids'][:5])
        ask_depth = sum(float(a[0]) * float(a[1]) for a in book['asks'][:5])
        print(f"\nOrderbook spread: {spread_pct:.2f}%")
        print(f"Bid depth (5 levels): EUR {bid_depth:,.2f}")
        print(f"Ask depth (5 levels): EUR {ask_depth:,.2f}")
        if spread_pct > 2:
            print("! WAARSCHUWING: Hoge spread - slippage risico!")
        elif spread_pct > 1:
            print("~ Matige spread - acceptabel voor grid")
        else:
            print("V Goede spread")
