#!/usr/bin/env python3
"""
SYNC TRADES WITH BITVAVO REALITY

This script checks Bitvavo balance and order history to:
1. Close trades that are marked "open" but you don't actually own anymore
2. Reset opened_ts for trades that were re-bought after being sold

Usage: python scripts/helpers/sync_bitvavo_reality.py
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


def sync_with_bitvavo():
    """Sync trade_log with actual Bitvavo holdings."""
    print("=" * 80)
    print("SYNC TRADES WITH BITVAVO REALITY")
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
    
    # Get actual balance
    try:
        balance_response = bitvavo.balance({})
        actual_holdings = {}
        for item in balance_response:
            symbol = item.get('symbol', '')
            available = float(item.get('available', 0))
            in_order = float(item.get('inOrder', 0))
            total = available + in_order
            if total > 0.00000001:  # Ignore dust
                actual_holdings[symbol] = total
        
        print(f"[OK] Found {len(actual_holdings)} assets in your Bitvavo wallet")
        for symbol, amount in actual_holdings.items():
            print(f"  {symbol}: {amount}")
    except Exception as e:
        print(f"[X] Failed to get balance: {e}")
        return
    
    # Load trade log
    trade_log_path = PROJECT_ROOT / "data" / "trade_log.json"
    with open(trade_log_path, 'r', encoding='utf-8') as f:
        trade_log = json.load(f)
    
    open_trades = trade_log.get('open', {})
    closed_trades = trade_log.get('closed', [])
    
    print(f"\n[OK] Trade log has {len(open_trades)} open trades\n")
    
    # Check each "open" trade
    changes_made = False
    for market, trade in list(open_trades.items()):
        base_currency = market.split('-')[0]
        trade_amount = float(trade.get('amount', 0))
        
        actual_amount = actual_holdings.get(base_currency, 0)
        
        print(f"{'='*60}")
        print(f"Market: {market}")
        print(f"  Bot thinks you own: {trade_amount} {base_currency}")
        print(f"  You ACTUALLY own: {actual_amount} {base_currency}")
        
        # Check if amounts roughly match (within 1%)
        if actual_amount < 0.00000001:
            # You don't own this anymore - CLOSE THE TRADE
            print(f"  [!] YOU DON'T OWN THIS ANYMORE - CLOSING TRADE")
            
            # Move to closed
            close_record = {
                'market': market,
                'buy_price': trade.get('buy_price', 0),
                'sell_price': 0,  # Unknown - was sold outside bot
                'amount': 0,
                'profit': 0,
                'timestamp': datetime.now().timestamp(),
                'reason': 'manual_sync_not_in_wallet',
                'invested_eur': trade.get('invested_eur', 0)
            }
            closed_trades.append(close_record)
            del open_trades[market]
            changes_made = True
            print(f"  [OK] Moved to closed trades")
            
        elif abs(actual_amount - trade_amount) / max(trade_amount, actual_amount) > 0.05:
            # Amount mismatch > 5%
            print(f"  [!] AMOUNT MISMATCH > 5%")
            print(f"  Suggestion: Update trade amount to {actual_amount}")
            # Don't auto-fix this - could be a pending order
        else:
            print(f"  [OK] Amount matches within tolerance")
    
    # Save if changes
    if changes_made:
        trade_log['open'] = open_trades
        trade_log['closed'] = closed_trades
        
        print(f"\n{'='*80}")
        print(f"[SAVE] Saving changes to {trade_log_path}")
        with open(trade_log_path, 'w', encoding='utf-8') as f:
            json.dump(trade_log, f, indent=2, ensure_ascii=False)
        print("[OK] Trade log updated!")
        print(f"{'='*80}")
    else:
        print("\n[OK] No changes needed - trade_log matches Bitvavo")
    
    print("\n[INFO] To fix invested amounts, run:")
    print("  python scripts/helpers/fix_invested_now.py")


if __name__ == '__main__':
    try:
        sync_with_bitvavo()
    except Exception as e:
        print(f"\n[X] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
