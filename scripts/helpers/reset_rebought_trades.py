#!/usr/bin/env python3
"""
RESET TRADES THAT WERE RE-BOUGHT

If you sold a position and bought it again, the bot still has the old opened_ts.
This script finds the MOST RECENT buy order for each holding and resets the trade.

Usage: python scripts/helpers/reset_rebought_trades.py
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Add project root to path  
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.bitvavo_client import get_bitvavo


def reset_rebought_trades():
    """Reset opened_ts for trades that were sold and re-bought."""
    print("=" * 80)
    print("RESET RE-BOUGHT TRADES")
    print("=" * 80)
    
    # Get Bitvavo client
    try:
        bitvavo = get_bitvavo()
        if not bitvavo:
            print("[X] Bitvavo client not available")
            return
        print("[OK] Connected to Bitvavo\n")
    except Exception as e:
        print(f"[X] Failed to connect: {e}")
        return
    
    # Load trade log
    trade_log_path = PROJECT_ROOT / "data" / "trade_log.json"
    with open(trade_log_path, 'r', encoding='utf-8') as f:
        trade_log = json.load(f)
    
    open_trades = trade_log.get('open', {})
    print(f"[OK] Found {len(open_trades)} open trades\n")
    
    changes_made = 0
    
    for market, trade in open_trades.items():
        print(f"{'='*60}")
        print(f"Market: {market}")
        
        current_amount = float(trade.get('amount', 0))
        current_opened_ts = float(trade.get('opened_ts', 0))
        current_invested = float(trade.get('invested_eur', 0))
        current_dca = int(trade.get('dca_buys', 0))
        
        if current_opened_ts > 0:
            opened_date = datetime.fromtimestamp(current_opened_ts).strftime('%Y-%m-%d %H:%M')
        else:
            opened_date = "Unknown"
        
        print(f"  Current opened_ts: {opened_date}")
        print(f"  Current invested: EUR {current_invested:.2f}")
        print(f"  Current DCA count: {current_dca}")
        
        # Get trade history for this market
        try:
            # Get recent trades (last 30 days)
            trades_response = bitvavo.trades(market, {'limit': 1000})
            
            if not trades_response or isinstance(trades_response, dict):
                print(f"  [!] No trade history available")
                continue
            
            # Find ALL buy orders
            buy_orders = []
            for t in trades_response:
                if str(t.get('side', '')).lower() == 'buy':
                    ts_raw = t.get('timestamp', 0)
                    # Convert from ms to seconds if needed
                    ts = float(ts_raw) / 1000 if ts_raw > 10000000000 else float(ts_raw)
                    buy_orders.append({
                        'timestamp': ts,
                        'price': float(t.get('price', 0)),
                        'amount': float(t.get('amount', 0)),
                        'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
                    })
            
            if not buy_orders:
                print(f"  [!] No buy orders found")
                continue
            
            # Sort by timestamp descending
            buy_orders.sort(key=lambda x: x['timestamp'], reverse=True)
            
            most_recent_buy = buy_orders[0]
            most_recent_ts = most_recent_buy['timestamp']
            most_recent_date = most_recent_buy['date']
            
            print(f"  Most recent BUY: {most_recent_date}")
            
            # Check if most recent buy is MUCH newer than current opened_ts
            days_diff = (most_recent_ts - current_opened_ts) / 86400
            
            if days_diff > 7:  # If most recent buy is > 7 days after opened_ts
                print(f"  [!] RESET NEEDED: Most recent buy is {days_diff:.0f} days after opened_ts")
                print(f"  This suggests you sold and re-bought")
                
                # Calculate how many buys happened in the CURRENT position
                # (buys that happened AFTER a potential sell)
                
                # Find the earliest buy that is part of current position
                # We know current_amount - find buys that add up to this
                accumulated = 0
                position_start_ts = None
                buys_in_position = 0
                invested_in_position = 0
                
                for buy in reversed(buy_orders):  # oldest first
                    accumulated += buy['amount']
                    invested_in_position += buy['price'] * buy['amount']
                    buys_in_position += 1
                    
                    if position_start_ts is None:
                        position_start_ts = buy['timestamp']
                    
                    # Check if we've accounted for current position
                    if abs(accumulated - current_amount) / max(current_amount, 0.0000001) < 0.05:
                        # Found the full position
                        break
                
                if position_start_ts:
                    position_start_date = datetime.fromtimestamp(position_start_ts).strftime('%Y-%m-%d %H:%M')
                    print(f"  NEW opened_ts: {position_start_date}")
                    print(f"  NEW invested_eur: EUR {invested_in_position:.2f}")
                    print(f"  Buys in current position: {buys_in_position}")
                    
                    # Update trade
                    trade['opened_ts'] = position_start_ts
                    trade['invested_eur'] = invested_in_position
                    trade['dca_buys'] = max(0, buys_in_position - 1)  # First buy doesn't count as DCA
                    trade['original_buy_price'] = buy_orders[-1]['price'] if buy_orders else trade.get('buy_price', 0)
                    
                    changes_made += 1
                    print(f"  [OK] UPDATED")
            else:
                print(f"  [OK] No reset needed (recent buy within {days_diff:.0f} days)")
                
        except Exception as e:
            print(f"  [X] Error checking trades: {e}")
            continue
    
    # Save if changes
    if changes_made > 0:
        trade_log['open'] = open_trades
        
        print(f"\n{'='*80}")
        print(f"[SAVE] Saving {changes_made} changes to {trade_log_path}")
        with open(trade_log_path, 'w', encoding='utf-8') as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        print("[OK] Trade log updated!")
        print(f"{'='*80}")
        print("\n[NEXT] Restart bot/dashboard to see changes")
    else:
        print("\n[OK] No trades needed resetting")


if __name__ == '__main__':
    try:
        reset_rebought_trades()
    except Exception as e:
        print(f"\n[X] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
