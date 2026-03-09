"""
Grid Bot Deep Backtest — Historische simulatie voor optimale config.

Test parameters:
- num_grids: 5, 8, 10, 15, 20
- grid_mode: arithmetic vs geometric
- range_pct: 10%, 15%, 20%, 25%
- trailing_profit: aan/uit (simulatie hoe het ZOU werken)
- stop_loss_pct: 0.05, 0.08, 0.12, 0.15
- investment: 60 EUR (huidige waarde)

Gebruikt Bitvavo API voor 30d historische 1h candles.
"""

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from itertools import product

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
    load_dotenv()
    from python_bitvavo_api.bitvavo import Bitvavo
    HAS_API = True
except ImportError:
    HAS_API = False

MAKER_FEE = 0.0015  # 0.15%

@dataclass
class GridSimConfig:
    num_grids: int = 10
    grid_mode: str = 'arithmetic'  # arithmetic or geometric
    range_pct: float = 0.18  # total range as % of mid price
    investment: float = 60.0
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.15
    trailing_profit: bool = False
    trailing_callback_pct: float = 0.02  # 2% callback for trailing
    rebalance_at_pct: float = 0.02  # rebalance when price exits ±2%

@dataclass  
class GridSimResult:
    config: GridSimConfig
    market: str
    total_profit: float = 0.0
    total_fees: float = 0.0
    net_profit: float = 0.0
    total_cycles: int = 0
    max_drawdown_pct: float = 0.0
    roi_pct: float = 0.0
    profit_per_day: float = 0.0
    rebalance_count: int = 0
    stop_loss_triggered: bool = False
    take_profit_triggered: bool = False
    grid_spacing_pct: float = 0.0
    days_active: float = 0.0
    sharpe_ratio: float = 0.0

def fetch_candles(market: str, interval: str = '1h', days: int = 30) -> List[List]:
    """Fetch historical candles from Bitvavo."""
    if not HAS_API:
        print("ERROR: Bitvavo API niet beschikbaar")
        return []
    
    api_key = os.getenv('BITVAVO_API_KEY', '')
    api_secret = os.getenv('BITVAVO_API_SECRET', '')
    
    bv = Bitvavo({
        'APIKEY': api_key,
        'APISECRET': api_secret,
        'RESTURL': 'https://api.bitvavo.com/v2',
        'ACCESSWINDOW': 10000,
    })
    
    # Fetch candles in chunks (max 1440 per call)
    all_candles = []
    end_time = int(time.time() * 1000)
    total_candles_needed = days * 24 if interval == '1h' else days * 24 * 4
    
    while len(all_candles) < total_candles_needed:
        params = {'limit': 1440, 'end': end_time}
        candles = bv.candles(market, interval, params)
        
        if not candles or not isinstance(candles, list):
            break
        
        # Filter out error responses
        valid = [c for c in candles if isinstance(c, list) and len(c) >= 6]
        if not valid:
            break
        
        all_candles.extend(valid)
        
        # Move end_time back
        oldest_ts = min(c[0] for c in valid)
        end_time = oldest_ts - 1
        
        time.sleep(0.15)  # Rate limit
    
    # Sort by timestamp ascending
    all_candles.sort(key=lambda c: c[0])
    
    # Remove duplicates
    seen = set()
    unique = []
    for c in all_candles:
        ts = c[0]
        if ts not in seen:
            seen.add(ts)
            unique.append(c)
    
    return unique

def simulate_grid(candles: List[List], cfg: GridSimConfig, market: str) -> GridSimResult:
    """
    Simulate grid trading on historical candle data.
    
    Each candle: [timestamp, open, high, low, close, volume]
    """
    result = GridSimResult(config=cfg, market=market)
    
    if len(candles) < 24:
        return result
    
    # Calculate grid parameters from first candle
    start_price = float(candles[0][4])  # close of first candle
    
    lower_price = start_price * (1 - cfg.range_pct / 2)
    upper_price = start_price * (1 + cfg.range_pct / 2)
    
    # Generate grid levels
    levels = []
    if cfg.grid_mode == 'geometric':
        ratio = (upper_price / lower_price) ** (1.0 / cfg.num_grids)
        for i in range(cfg.num_grids + 1):
            levels.append(lower_price * (ratio ** i))
    else:  # arithmetic
        step = (upper_price - lower_price) / cfg.num_grids
        for i in range(cfg.num_grids + 1):
            levels.append(lower_price + step * i)
    
    result.grid_spacing_pct = (levels[1] - levels[0]) / levels[0] * 100 if len(levels) > 1 else 0
    
    # Investment per level
    amount_per_level = cfg.investment / cfg.num_grids
    
    # State tracking
    # Each grid level can have a pending buy or sell
    # We place buys below current price, sells above
    grid_orders = {}  # level_idx -> {'side': 'buy'/'sell', 'price': float, 'amount': float}
    
    total_profit = 0.0
    total_fees = 0.0
    total_cycles = 0
    daily_profits = []
    current_day_profit = 0.0
    last_day = None
    mid_price = start_price
    peak_profit = 0.0
    max_drawdown = 0.0
    rebalance_count = 0
    
    # Trailing profit state
    trailing_peak = 0.0
    trailing_active = False
    
    # Initialize orders: buys below mid, sells above mid
    for i, level_price in enumerate(levels):
        coin_amount = amount_per_level / level_price
        if level_price < start_price:
            grid_orders[i] = {'side': 'buy', 'price': level_price, 'amount': coin_amount}
        elif level_price > start_price:
            grid_orders[i] = {'side': 'sell', 'price': level_price, 'amount': coin_amount}
        # Level at exactly start_price: skip
    
    start_ts = candles[0][0]
    end_ts = candles[-1][0]
    
    for candle in candles:
        ts = candle[0]
        c_open = float(candle[1])
        c_high = float(candle[2])
        c_low = float(candle[3])
        c_close = float(candle[4])
        
        # Track daily profit
        day = ts // (86400 * 1000)
        if last_day is not None and day != last_day:
            daily_profits.append(current_day_profit)
            current_day_profit = 0.0
        last_day = day
        
        # Check stop loss
        loss_pct = (mid_price - c_low) / mid_price if mid_price > 0 else 0
        if loss_pct >= cfg.stop_loss_pct:
            result.stop_loss_triggered = True
            break
        
        # Check fills: scan from low to high in this candle
        filled_this_candle = []
        
        for idx, order in list(grid_orders.items()):
            if order['side'] == 'buy' and c_low <= order['price']:
                # Buy filled
                fee = order['price'] * order['amount'] * MAKER_FEE
                total_fees += fee
                filled_this_candle.append((idx, 'buy', order['price'], order['amount']))
            elif order['side'] == 'sell' and c_high >= order['price']:
                # Sell filled
                fee = order['price'] * order['amount'] * MAKER_FEE
                total_fees += fee
                filled_this_candle.append((idx, 'sell', order['price'], order['amount']))
        
        # Process fills: place counter orders
        for idx, side, fill_price, fill_amount in filled_this_candle:
            if side == 'buy':
                # Place sell at next higher level
                if idx + 1 < len(levels):
                    sell_price = levels[idx + 1]
                    # Profit from this buy→sell cycle (estimated)
                    spread = sell_price - fill_price
                    cycle_profit = spread * fill_amount - 2 * fill_price * fill_amount * MAKER_FEE
                    # Replace order with sell
                    grid_orders[idx] = {'side': 'sell', 'price': sell_price, 'amount': fill_amount}
                else:
                    del grid_orders[idx]
            elif side == 'sell':
                # Record profit
                if idx - 1 >= 0:
                    buy_price = levels[idx - 1]
                    spread = fill_price - buy_price
                    cycle_profit = spread * fill_amount - 2 * fill_price * fill_amount * MAKER_FEE
                    total_profit += cycle_profit
                    current_day_profit += cycle_profit
                    total_cycles += 1
                    
                    # Place buy at next lower level
                    new_amount = amount_per_level / buy_price
                    grid_orders[idx] = {'side': 'buy', 'price': buy_price, 'amount': new_amount}
                else:
                    del grid_orders[idx]
        
        # Trailing profit check
        if cfg.trailing_profit:
            roi = total_profit / cfg.investment if cfg.investment > 0 else 0
            if roi >= cfg.take_profit_pct:
                if not trailing_active:
                    trailing_active = True
                    trailing_peak = total_profit
                else:
                    trailing_peak = max(trailing_peak, total_profit)
                    callback = (trailing_peak - total_profit) / trailing_peak if trailing_peak > 0 else 0
                    if callback >= cfg.trailing_callback_pct:
                        result.take_profit_triggered = True
                        break
        else:
            # Fixed take profit
            roi = total_profit / cfg.investment if cfg.investment > 0 else 0
            if roi >= cfg.take_profit_pct:
                result.take_profit_triggered = True
                break
        
        # Track drawdown
        peak_profit = max(peak_profit, total_profit)
        if peak_profit > 0:
            dd = (peak_profit - total_profit) / peak_profit
            max_drawdown = max(max_drawdown, dd)
        
        # Rebalance check: if price exits range
        if c_close < lower_price * (1 - cfg.rebalance_at_pct) or c_close > upper_price * (1 + cfg.rebalance_at_pct):
            # Rebalance: recenter grid on current price
            rebalance_count += 1
            mid_price = c_close
            lower_price = mid_price * (1 - cfg.range_pct / 2)
            upper_price = mid_price * (1 + cfg.range_pct / 2)
            
            # Regenerate levels
            levels = []
            if cfg.grid_mode == 'geometric':
                ratio = (upper_price / lower_price) ** (1.0 / cfg.num_grids)
                for i in range(cfg.num_grids + 1):
                    levels.append(lower_price * (ratio ** i))
            else:
                step = (upper_price - lower_price) / cfg.num_grids
                for i in range(cfg.num_grids + 1):
                    levels.append(lower_price + step * i)
            
            # Reset orders
            grid_orders = {}
            for i, level_price in enumerate(levels):
                coin_amount = amount_per_level / level_price
                if level_price < c_close:
                    grid_orders[i] = {'side': 'buy', 'price': level_price, 'amount': coin_amount}
                elif level_price > c_close:
                    grid_orders[i] = {'side': 'sell', 'price': level_price, 'amount': coin_amount}
    
    # Final daily profit
    if current_day_profit != 0:
        daily_profits.append(current_day_profit)
    
    # Calculate results
    result.total_profit = round(total_profit, 4)
    result.total_fees = round(total_fees, 4)
    result.net_profit = round(total_profit - total_fees, 4)
    result.total_cycles = total_cycles
    result.max_drawdown_pct = round(max_drawdown * 100, 2)
    result.roi_pct = round((total_profit / cfg.investment * 100) if cfg.investment > 0 else 0, 2)
    result.rebalance_count = rebalance_count
    
    # Days active
    duration_ms = end_ts - start_ts
    result.days_active = duration_ms / (86400 * 1000)
    result.profit_per_day = round(total_profit / max(1, result.days_active), 4)
    
    # Sharpe ratio (annualized from daily profits)
    if len(daily_profits) > 1:
        avg_daily = sum(daily_profits) / len(daily_profits)
        std_daily = math.sqrt(sum((p - avg_daily) ** 2 for p in daily_profits) / (len(daily_profits) - 1))
        result.sharpe_ratio = round((avg_daily / std_daily * math.sqrt(365)) if std_daily > 0 else 0, 2)
    
    return result

def run_full_backtest():
    """Run comprehensive grid backtest across all parameter combinations."""
    
    print("=" * 70)
    print("GRID BOT DEEP BACKTEST — Historische Data Analyse")
    print("=" * 70)
    
    markets = ['BTC-EUR', 'ETH-EUR']
    
    # Fetch candle data
    candle_data = {}
    for market in markets:
        print(f"\n📊 Fetching 30d candles for {market}...")
        candles = fetch_candles(market, '1h', 30)
        if candles:
            candle_data[market] = candles
            first_ts = candles[0][0] / 1000
            last_ts = candles[-1][0] / 1000
            days = (last_ts - first_ts) / 86400
            print(f"   ✓ {len(candles)} candles, {days:.1f} dagen, "
                  f"€{float(candles[0][4]):.2f} → €{float(candles[-1][4]):.2f}")
        else:
            print(f"   ✗ Geen data voor {market}")
    
    if not candle_data:
        print("\nERROR: Geen candle data beschikbaar!")
        return
    
    # Define parameter grid
    param_grid = {
        'num_grids': [5, 8, 10, 15],
        'grid_mode': ['arithmetic', 'geometric'],
        'range_pct': [0.10, 0.15, 0.20, 0.25],
        'stop_loss_pct': [0.05, 0.08, 0.12, 0.15],
        'trailing_profit': [False, True],
    }
    
    # Generate all combinations
    keys = list(param_grid.keys())
    combos = list(product(*[param_grid[k] for k in keys]))
    
    print(f"\n🔬 Testing {len(combos)} configuraties × {len(candle_data)} markets = {len(combos) * len(candle_data)} simulaties...")
    
    all_results = []
    
    for market, candles in candle_data.items():
        print(f"\n{'─'*50}")
        print(f"Market: {market}")
        print(f"{'─'*50}")
        
        market_results = []
        
        for i, combo in enumerate(combos):
            params = dict(zip(keys, combo))
            
            cfg = GridSimConfig(
                num_grids=params['num_grids'],
                grid_mode=params['grid_mode'],
                range_pct=params['range_pct'],
                investment=60.0,
                stop_loss_pct=params['stop_loss_pct'],
                take_profit_pct=0.15 if not params['trailing_profit'] else 0.10,
                trailing_profit=params['trailing_profit'],
                trailing_callback_pct=0.02,
            )
            
            result = simulate_grid(candles, cfg, market)
            market_results.append(result)
            
            if (i + 1) % 100 == 0:
                print(f"   Progress: {i+1}/{len(combos)}", end='\r')
        
        # Sort by net_profit descending
        market_results.sort(key=lambda r: r.net_profit, reverse=True)
        all_results.extend(market_results)
        
        # Show top 5
        print(f"\n   🏆 Top 5 configs voor {market}:")
        print(f"   {'Grids':>5} {'Mode':>10} {'Range%':>7} {'SL%':>5} {'Trail':>5} │ {'NetP':>8} {'Cycles':>6} {'ROI%':>6} {'€/dag':>6} {'Sharpe':>6}")
        print(f"   {'─'*5} {'─'*10} {'─'*7} {'─'*5} {'─'*5} │ {'─'*8} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
        
        for r in market_results[:5]:
            c = r.config
            trail = "Ja" if c.trailing_profit else "Nee"
            print(f"   {c.num_grids:>5} {c.grid_mode:>10} {c.range_pct*100:>6.0f}% {c.stop_loss_pct*100:>4.0f}% {trail:>5} │ "
                  f"€{r.net_profit:>7.2f} {r.total_cycles:>6} {r.roi_pct:>5.1f}% €{r.profit_per_day:>5.3f} {r.sharpe_ratio:>6.2f}")
        
        # Show worst 3 (to see what to avoid)
        print(f"\n   ❌ Worst 3 configs:")
        for r in market_results[-3:]:
            c = r.config
            trail = "Ja" if c.trailing_profit else "Nee"
            sl = " SL!" if r.stop_loss_triggered else ""
            print(f"   {c.num_grids:>5} {c.grid_mode:>10} {c.range_pct*100:>6.0f}% {c.stop_loss_pct*100:>4.0f}% {trail:>5} │ "
                  f"€{r.net_profit:>7.2f} {r.total_cycles:>6}{sl}")
    
    # =============================================
    # OVERALL BEST CONFIG (combined)
    # =============================================
    print(f"\n{'='*70}")
    print("OVERALL ANALYSE — Gecombineerde resultaten")
    print(f"{'='*70}")
    
    # Group by config (summing profit across markets)
    config_totals = {}
    for r in all_results:
        c = r.config
        key = (c.num_grids, c.grid_mode, c.range_pct, c.stop_loss_pct, c.trailing_profit)
        if key not in config_totals:
            config_totals[key] = {
                'net_profit': 0.0, 'cycles': 0, 'roi_pct': 0.0,
                'profit_per_day': 0.0, 'markets': 0, 'sl_count': 0,
                'rebalances': 0, 'sharpe_sum': 0.0
            }
        config_totals[key]['net_profit'] += r.net_profit
        config_totals[key]['cycles'] += r.total_cycles
        config_totals[key]['roi_pct'] += r.roi_pct
        config_totals[key]['profit_per_day'] += r.profit_per_day
        config_totals[key]['markets'] += 1
        config_totals[key]['sl_count'] += (1 if r.stop_loss_triggered else 0)
        config_totals[key]['rebalances'] += r.rebalance_count
        config_totals[key]['sharpe_sum'] += r.sharpe_ratio
    
    # Sort by total net profit
    sorted_configs = sorted(config_totals.items(), key=lambda x: x[1]['net_profit'], reverse=True)
    
    print(f"\n🏆 TOP 10 CONFIGS (gecombineerd over alle markets):")
    print(f"{'#':>2} {'Grids':>5} {'Mode':>10} {'Range%':>7} {'SL%':>5} {'Trail':>5} │ {'TotProfit':>9} {'Cycles':>6} {'€/dag':>7} {'Sharpe':>6} {'SL':>3} {'Reb':>3}")
    print(f"{'─'*2} {'─'*5} {'─'*10} {'─'*7} {'─'*5} {'─'*5} │ {'─'*9} {'─'*6} {'─'*7} {'─'*6} {'─'*3} {'─'*3}")
    
    for rank, (key, data) in enumerate(sorted_configs[:10], 1):
        num_grids, grid_mode, range_pct, sl_pct, trailing = key
        trail = "Ja" if trailing else "Nee"
        avg_sharpe = data['sharpe_sum'] / max(1, data['markets'])
        print(f"{rank:>2} {num_grids:>5} {grid_mode:>10} {range_pct*100:>6.0f}% {sl_pct*100:>4.0f}% {trail:>5} │ "
              f"€{data['net_profit']:>8.2f} {data['cycles']:>6} €{data['profit_per_day']:>6.3f} {avg_sharpe:>6.2f} {data['sl_count']:>3} {data['rebalances']:>3}")
    
    # =============================================
    # COMPARE VS CURRENT CONFIG
    # =============================================
    print(f"\n{'='*70}")
    print("VERGELIJKING: Huidige config vs Beste config")
    print(f"{'='*70}")
    
    # Current config from bot_config.json
    current_key = None
    best_key = sorted_configs[0][0] if sorted_configs else None
    
    for key, data in sorted_configs:
        num_grids, grid_mode, range_pct, sl_pct, trailing = key
        if num_grids == 10 and grid_mode == 'arithmetic' and not trailing:
            if current_key is None or abs(sl_pct - 0.08) < abs(current_key[3] - 0.08):
                current_key = key
    
    if current_key and best_key:
        curr_data = config_totals[current_key]
        best_data = config_totals[best_key]
        
        cg, cm, cr, cs, ct = current_key
        bg, bm, br, bs, bt = best_key
        
        print(f"\n{'Param':<20} {'Huidig':>15} {'Optimaal':>15} {'Verschil':>15}")
        print(f"{'─'*20} {'─'*15} {'─'*15} {'─'*15}")
        print(f"{'num_grids':<20} {cg:>15} {bg:>15} {'✓' if cg == bg else '← wijzig':>15}")
        print(f"{'grid_mode':<20} {cm:>15} {bm:>15} {'✓' if cm == bm else '← wijzig':>15}")
        print(f"{'range_pct':<20} {cr*100:>14.0f}% {br*100:>14.0f}% {'✓' if cr == br else '← wijzig':>15}")
        print(f"{'stop_loss_pct':<20} {cs*100:>14.0f}% {bs*100:>14.0f}% {'✓' if cs == bs else '← wijzig':>15}")
        print(f"{'trailing_profit':<20} {'Ja' if ct else 'Nee':>15} {'Ja' if bt else 'Nee':>15} {'✓' if ct == bt else '← wijzig':>15}")
        print(f"{'─'*20} {'─'*15} {'─'*15} {'─'*15}")
        print(f"{'Totaal winst':<20} €{curr_data['net_profit']:>14.2f} €{best_data['net_profit']:>14.2f} €{best_data['net_profit'] - curr_data['net_profit']:>14.2f}")
        print(f"{'Cycles':<20} {curr_data['cycles']:>15} {best_data['cycles']:>15}")
        print(f"{'€/dag':<20} €{curr_data['profit_per_day']:>14.3f} €{best_data['profit_per_day']:>14.3f}")
        print(f"{'Stop-losses':<20} {curr_data['sl_count']:>15} {best_data['sl_count']:>15}")
    
    # =============================================
    # TRAILING PROFIT ANALYSIS
    # =============================================
    print(f"\n{'='*70}")
    print("TRAILING PROFIT ANALYSE")
    print(f"{'='*70}")
    
    trail_on = [v for k, v in config_totals.items() if k[4] == True]
    trail_off = [v for k, v in config_totals.items() if k[4] == False]
    
    avg_trail_on = sum(d['net_profit'] for d in trail_on) / max(1, len(trail_on))
    avg_trail_off = sum(d['net_profit'] for d in trail_off) / max(1, len(trail_off))
    
    print(f"\n  Trailing UIT: gemiddeld €{avg_trail_off:.4f} winst per config")
    print(f"  Trailing AAN: gemiddeld €{avg_trail_on:.4f} winst per config")
    print(f"  Verschil:     €{avg_trail_on - avg_trail_off:+.4f} {'(trailing beter)' if avg_trail_on > avg_trail_off else '(vast TP beter)'}")
    
    # =============================================
    # ARITHMETIC vs GEOMETRIC
    # =============================================
    print(f"\n{'='*70}")
    print("ARITHMETIC vs GEOMETRIC")
    print(f"{'='*70}")
    
    arith = [v for k, v in config_totals.items() if k[1] == 'arithmetic']
    geom = [v for k, v in config_totals.items() if k[1] == 'geometric']
    
    avg_arith = sum(d['net_profit'] for d in arith) / max(1, len(arith))
    avg_geom = sum(d['net_profit'] for d in geom) / max(1, len(geom))
    
    print(f"\n  Arithmetic: gemiddeld €{avg_arith:.4f} winst per config")
    print(f"  Geometric:  gemiddeld €{avg_geom:.4f} winst per config")
    print(f"  Verschil:   €{avg_geom - avg_arith:+.4f} {'(geometric beter)' if avg_geom > avg_arith else '(arithmetic beter)'}")
    
    # =============================================
    # OPTIMAL NUM_GRIDS
    # =============================================
    print(f"\n{'='*70}")
    print("OPTIMAAL AANTAL GRIDS")
    print(f"{'='*70}")
    
    for ng in [5, 8, 10, 15]:
        ng_results = [v for k, v in config_totals.items() if k[0] == ng]
        avg_p = sum(d['net_profit'] for d in ng_results) / max(1, len(ng_results))
        avg_c = sum(d['cycles'] for d in ng_results) / max(1, len(ng_results))
        avg_sl = sum(d['sl_count'] for d in ng_results) / max(1, len(ng_results))
        print(f"  {ng:>2} grids: gemiddeld €{avg_p:.4f} winst, {avg_c:.0f} cycles, {avg_sl:.1f} stop-losses")
    
    # =============================================
    # OPTIMAL RANGE
    # =============================================
    print(f"\n{'='*70}")
    print("OPTIMAAL RANGE %")
    print(f"{'='*70}")
    
    for rp in [0.10, 0.15, 0.20, 0.25]:
        rp_results = [v for k, v in config_totals.items() if k[2] == rp]
        avg_p = sum(d['net_profit'] for d in rp_results) / max(1, len(rp_results))
        avg_reb = sum(d['rebalances'] for d in rp_results) / max(1, len(rp_results))
        avg_sl = sum(d['sl_count'] for d in rp_results) / max(1, len(rp_results))
        print(f"  {rp*100:>3.0f}% range: gemiddeld €{avg_p:.4f} winst, {avg_reb:.1f} rebalances, {avg_sl:.1f} stop-losses")
    
    # =============================================
    # SAVE FULL RESULTS
    # =============================================
    output = {
        'timestamp': time.time(),
        'markets': list(candle_data.keys()),
        'candles_per_market': {m: len(c) for m, c in candle_data.items()},
        'total_configs_tested': len(combos),
        'top_10': [],
        'current_vs_best': {},
    }
    
    for rank, (key, data) in enumerate(sorted_configs[:10], 1):
        ng, gm, rp, sl, tr = key
        output['top_10'].append({
            'rank': rank,
            'num_grids': ng,
            'grid_mode': gm,
            'range_pct': rp,
            'stop_loss_pct': sl,
            'trailing_profit': tr,
            'net_profit': round(data['net_profit'], 4),
            'cycles': data['cycles'],
            'profit_per_day': round(data['profit_per_day'], 4),
            'sl_count': data['sl_count'],
            'rebalances': data['rebalances'],
        })
    
    if best_key:
        bg, bm, br, bs, bt = best_key
        output['recommended_config'] = {
            'num_grids': bg,
            'grid_mode': bm,
            'range_pct': br,
            'stop_loss_pct': bs,
            'trailing_profit': bt,
            'take_profit_pct': 0.10 if bt else 0.15,
        }
    
    out_path = os.path.join(os.path.dirname(__file__), 'reviews', 'grid_backtest_results.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    print(f"\n💾 Resultaten opgeslagen: {out_path}")
    
    print(f"\n{'='*70}")
    print("CONCLUSIE")
    print(f"{'='*70}")
    if best_key:
        bg, bm, br, bs, bt = best_key
        bd = config_totals[best_key]
        print(f"""
  Optimale grid config op basis van 30d backtest:
  ┌─────────────────────────────────────────┐
  │ num_grids:       {bg:<24}│
  │ grid_mode:       {bm:<24}│
  │ range_pct:       {br*100:.0f}%{' '*(22-len(f'{br*100:.0f}%'))}│
  │ stop_loss_pct:   {bs*100:.0f}%{' '*(22-len(f'{bs*100:.0f}%'))}│
  │ trailing_profit: {'Ja' if bt else 'Nee':<24}│
  │ take_profit_pct: {'10%' if bt else '15%':<24}│
  ├─────────────────────────────────────────┤
  │ Verwachte winst: €{bd['net_profit']:.2f}/30d{' '*(18-len(f"€{bd['net_profit']:.2f}/30d"))}│
  │ Per dag:         €{bd['profit_per_day']:.3f}{' '*(21-len(f"€{bd['profit_per_day']:.3f}"))}│
  │ Cycles:          {bd['cycles']}{' '*(24-len(str(bd['cycles'])))}│
  └─────────────────────────────────────────┘
  
  Trailing profit: {'ZOU verbetering geven' if avg_trail_on > avg_trail_off else 'Geen verbetering'} 
  → Grid bot heeft momenteel GEEN trailing. {'Aanbeveling: implementeer trailing TP.' if avg_trail_on > avg_trail_off else ''}
""")


if __name__ == '__main__':
    run_full_backtest()
