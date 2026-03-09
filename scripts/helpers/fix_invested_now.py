#!/usr/bin/env python3
"""
EMERGENCY FIX: Recalculate invested_eur for ALL open trades from Bitvavo API.
This script FORCES a refresh of invested amounts using actual Bitvavo trade history.

Usage: python scripts/helpers/fix_invested_now.py
"""
import json
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.bitvavo_client import get_bitvavo
from modules.cost_basis import derive_cost_basis


def fix_invested_amounts():
    """Recalculate invested_eur for all open trades."""
    print("=" * 80)
    print("EMERGENCY FIX: Recalculating invested_eur from Bitvavo API")
    print("=" * 80)
    
    # Load trade log
    trade_log_path = PROJECT_ROOT / "data" / "trade_log.json"
    with open(trade_log_path, 'r', encoding='utf-8') as f:
        trade_log = json.load(f)
    
    open_trades = trade_log.get('open', {})
    if not open_trades:
        print("[X] No open trades found in trade_log.json")
        return
    
    print(f"[OK] Found {len(open_trades)} open trades\n")
    
    # Get Bitvavo client
    try:
        bitvavo = get_bitvavo()
        if not bitvavo:
            print("[X] Bitvavo client not available. Check your .env file.")
            return
        print("[OK] Bitvavo client connected\n")
    except Exception as e:
        print(f"[X] Failed to connect to Bitvavo: {e}")
        return
    
    # Recalculate each trade
    changes_made = 0
    for market, trade in open_trades.items():
        print(f"\n{'='*60}")
        print(f"Market: {market}")
        
        amount = float(trade.get('amount', 0))
        old_invested = float(trade.get('invested_eur', 0))
        opened_ts = float(trade.get('opened_ts', 0))
        dca_buys = int(trade.get('dca_buys', 0))
        
        print(f"  Amount: {amount}")
        print(f"  OLD invested_eur: EUR {old_invested:.2f}")
        print(f"  DCA buys: {dca_buys}")
        print(f"  Opened timestamp: {opened_ts}")
        
        if amount <= 0:
            print("  [!] Skip: amount is 0")
            continue
        
        # Derive cost basis from Bitvavo
        try:
            result = derive_cost_basis(
                bitvavo,
                market,
                amount,
                opened_ts=opened_ts if opened_ts > 0 else None,
                tolerance=0.10
            )
            
            if result and result.invested_eur > 0:
                new_invested = result.invested_eur
                print(f"  NEW invested_eur: EUR {new_invested:.2f}")
                print(f"  Difference: EUR {new_invested - old_invested:.2f}")
                print(f"  Fills used: {result.fills_used}")
                print(f"  Buy orders: {result.buy_order_count}")
                
                # Update trade log
                trade['invested_eur'] = new_invested
                changes_made += 1
                print("  [OK] UPDATED")
            else:
                print("  [!] Could not derive cost basis from API")
                # Fallback: use buy_price * amount
                fallback = float(trade.get('buy_price', 0)) * amount
                if fallback > 0:
                    print(f"  Using fallback: buy_price * amount = EUR {fallback:.2f}")
                    trade['invested_eur'] = fallback
                    changes_made += 1
        except Exception as e:
            print(f"  [X] Error: {e}")
            # Fallback
            fallback = float(trade.get('buy_price', 0)) * amount
            if fallback > 0:
                print(f"  Using fallback: buy_price * amount = EUR {fallback:.2f}")
                trade['invested_eur'] = fallback
                changes_made += 1
    
    # Save updated trade log
    if changes_made > 0:
        print(f"\n{'='*80}")
        print(f"[SAVE] Saving {changes_made} changes to {trade_log_path}")
        with open(trade_log_path, 'w', encoding='utf-8') as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        print("[OK] Trade log updated successfully!")
        print(f"{'='*80}")
        print("\n[NEXT] Restart dashboard to see changes:")
        print("   .venv\\Scripts\\python -m streamlit run tools\\dashboard\\dashboard_streamlit.py")
    else:
        print("\n[!] No changes made.")


if __name__ == '__main__':
    try:
        fix_invested_amounts()
    except Exception as e:
        print(f"\n[X] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
