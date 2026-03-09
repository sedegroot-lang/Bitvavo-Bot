#!/usr/bin/env python3
"""
FIX INVESTED AMOUNTS BY ANALYZING SELLS

Finds the LAST sell order for each coin, then only counts buys AFTER that sell.
This ensures invested_eur reflects the CURRENT position, not old DCA history.

Usage: python scripts/helpers/fix_invested_with_sells.py
"""
import json
import sys
import os
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.bitvavo_client import get_bitvavo


def fix_invested_amounts():
    print("=" * 80)
    print("FIX INVESTED AMOUNTS - SELL ANALYSIS")
    print("=" * 80)
    
    # Connect to Bitvavo
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
        current_invested = float(trade.get('invested_eur', 0))
        current_opened_ts = float(trade.get('opened_ts', 0))
        
        print(f"  Current invested: EUR {current_invested:.2f}")
        print(f"  Current amount: {current_amount}")
        
        # Get ALL trades for this market
        try:
            trades_response = bitvavo.trades(market, {'limit': 1000})
            
            if not trades_response or isinstance(trades_response, dict):
                print(f"  [!] No trade history")
                continue
            
            # Parse and sort trades
            all_trades = []
            for t in trades_response:
                ts_raw = t.get('timestamp', 0)
                ts = float(ts_raw) / 1000 if ts_raw > 10000000000 else float(ts_raw)
                
                all_trades.append({
                    'timestamp': ts,
                    'side': str(t.get('side', '')).lower(),
                    'price': float(t.get('price', 0)),
                    'amount': float(t.get('amount', 0)),
                    'fee': float(t.get('fee', 0)),
                    'fee_currency': str(t.get('feeCurrency', '')).upper(),
                    'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                })
            
            # Sort oldest first
            all_trades.sort(key=lambda x: x['timestamp'])
            
            # Find LAST sell order
            last_sell_ts = None
            last_sell_date = None
            for t in reversed(all_trades):
                if t['side'] == 'sell':
                    last_sell_ts = t['timestamp']
                    last_sell_date = t['date']
                    break
            
            if last_sell_ts:
                print(f"  Last SELL: {last_sell_date}")
            else:
                print(f"  No sells found")
            
            # Count buys AFTER last sell (or all buys if no sell)
            buys_after_sell = []
            for t in all_trades:
                if t['side'] == 'buy':
                    if last_sell_ts is None or t['timestamp'] > last_sell_ts:
                        buys_after_sell.append(t)
            
            if not buys_after_sell:
                print(f"  [!] No buys after last sell")
                continue
            
            # Calculate position from these buys
            position_amount = 0
            position_cost = 0
            first_buy_ts = None
            
            base_currency = market.split('-')[0].upper()
            
            for buy in buys_after_sell:
                # Account for fees
                buy_amount = buy['amount']
                if buy['fee_currency'] == base_currency:
                    buy_amount = max(0, buy_amount - buy['fee'])
                
                position_amount += buy_amount
                
                eur_cost = buy['price'] * buy['amount']
                if buy['fee_currency'] == 'EUR':
                    eur_cost += buy['fee']
                
                position_cost += eur_cost
                
                if first_buy_ts is None:
                    first_buy_ts = buy['timestamp']
            
            first_buy_date = datetime.fromtimestamp(first_buy_ts).strftime('%Y-%m-%d %H:%M:%S')
            
            print(f"  Buys after sell: {len(buys_after_sell)}")
            print(f"  First buy (NEW opened_ts): {first_buy_date}")
            print(f"  Calculated amount: {position_amount:.8f}")
            print(f"  Calculated invested: EUR {position_cost:.2f}")
            
            # Check if amount matches current position
            amount_diff_pct = abs(position_amount - current_amount) / max(current_amount, 0.0000001)
            
            if amount_diff_pct > 0.10:  # More than 10% difference
                print(f"  [!] WARNING: Calculated amount differs by {amount_diff_pct*100:.1f}%")
                print(f"  This suggests sells/buys weren't fully tracked")
            
            # Update trade
            old_invested = current_invested
            new_invested = position_cost
            diff = new_invested - old_invested
            
            print(f"  OLD invested: EUR {old_invested:.2f}")
            print(f"  NEW invested: EUR {new_invested:.2f}")
            print(f"  Difference: EUR {diff:+.2f}")
            
            trade['invested_eur'] = new_invested
            trade['opened_ts'] = first_buy_ts
            trade['dca_buys'] = max(0, len(buys_after_sell) - 1)
            
            if len(buys_after_sell) > 0:
                trade['original_buy_price'] = buys_after_sell[0]['price']
            
            changes_made += 1
            print(f"  [OK] UPDATED")
            
        except Exception as e:
            print(f"  [X] Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Save changes
    if changes_made > 0:
        print(f"\n{'='*80}")
        print(f"[SAVE] Saving {changes_made} changes to {trade_log_path}")
        with open(trade_log_path, 'w', encoding='utf-8') as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        print("[OK] Trade log updated!")
        print(f"{'='*80}")
        print("\n[DONE] Invested amounts now match current positions")
        print("[NEXT] Restart dashboard to see changes")
    else:
        print("\n[OK] No changes needed")


if __name__ == '__main__':
    try:
        fix_invested_amounts()
    except Exception as e:
        print(f"\n[X] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
