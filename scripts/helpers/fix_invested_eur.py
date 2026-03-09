#!/usr/bin/env python3
"""
Fix invested_eur values in trade_log.json by deriving from Bitvavo API.
This resolves discrepancies between local tracking and actual exchange data.
"""
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.cost_basis import derive_cost_basis
from modules.bitvavo_client import get_bitvavo
from modules.trade_store import save_snapshot as save_trade_snapshot

def main():
    bv = get_bitvavo()
    if not bv:
        print("ERROR: Could not get Bitvavo client")
        return 1
    
    trade_log_path = project_root / 'data' / 'trade_log.json'
    
    # Load trade log
    data = json.loads(trade_log_path.read_text(encoding='utf-8'))
    open_trades = data.get('open', {})
    
    print(f"=== Syncing {len(open_trades)} trades with Bitvavo API ===\n")
    
    fixes_made = 0
    
    for market, trade in open_trades.items():
        amount = float(trade.get('amount', 0))
        if amount <= 0:
            continue
        
        # Derive cost basis from Bitvavo
        try:
            result = derive_cost_basis(bv, market, amount, tolerance=0.10)
        except Exception as e:
            print(f"  {market}: ERROR - {e}")
            continue
        
        if result and result.invested_eur > 0:
            old_invested = float(trade.get('invested_eur', 0) or 0)
            initial_invested = float(trade.get('initial_invested_eur', 0) or 0)
            
            # CRITICAL: NEVER overwrite if initial_invested_eur exists
            # This prevents corruption of existing trades
            if initial_invested > 0:
                print(f"  {market}: PROTECTED (initial_invested_eur={initial_invested:.2f}, keeping current values)")
                continue
            
            # Only set for NEW trades without initial investment data
            if old_invested <= 0:
                print(f"  {market}:")
                print(f"    invested_eur: {old_invested:.2f} -> {result.invested_eur:.2f}")
                print(f"    buy_price: {trade.get('buy_price', 0):.6f} -> {result.avg_price:.6f}")
                
                trade['invested_eur'] = result.invested_eur
                trade['initial_invested_eur'] = result.invested_eur
                trade['total_invested_eur'] = result.invested_eur
                trade['buy_price'] = result.avg_price
                trade['dca_buys'] = 0  # NEVER set from API
                trade['dca_events'] = []  # ALWAYS empty for new trades
                if result.earliest_timestamp:
                    trade['opened_ts'] = result.earliest_timestamp
                fixes_made += 1
            else:
                print(f"  {market}: OK (invested: {old_invested:.2f})")
        else:
            print(f"  {market}: Could not derive cost basis")
    
    if fixes_made > 0:
        # Save with backup
        backup_path = trade_log_path.with_suffix('.json.bak.sync')
        import shutil
        shutil.copy(trade_log_path, backup_path)
        
        trade_log_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        print(f"\n=== Fixed {fixes_made} trades ===")
        print(f"Backup saved to: {backup_path}")
    else:
        print("\n=== All trades already in sync ===")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
