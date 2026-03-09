#!/usr/bin/env python3
"""
Remove phantom trades from trade_log.json.

These are trades that were logged as closed but the sell orders failed.
Identified by:
- Missing buy_order_id and sell_order_id
- reason='trailing_tp' (most recent phantom trades)
- reason='sync_removed', 'saldo_error', etc. (other phantom types)
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADE_LOG = PROJECT_ROOT / 'data' / 'trade_log.json'

def main():
    print("PHANTOM TRADES CLEANUP")
    print("="*70)
    
    # Backup
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = PROJECT_ROOT / 'data' / f'trade_log_pre_phantom_cleanup_{timestamp}.json'
    shutil.copy(TRADE_LOG, backup_path)
    print(f"Backup: {backup_path.name}")
    
    # Load
    with open(TRADE_LOG, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    closed_trades = data.get('closed', [])
    original_count = len(closed_trades)
    
    # Identify phantom trades
    phantom_trades = []
    real_trades = []
    
    for trade in closed_trades:
        buy_id = trade.get('buy_order_id', 'MISSING')
        sell_id = trade.get('sell_order_id', 'MISSING')
        reason = trade.get('reason', 'unknown')
        
        # A trade is phantom if it has NO order IDs
        is_phantom = (
            (not buy_id or buy_id == 'MISSING') and
            (not sell_id or sell_id == 'MISSING')
        )
        
        if is_phantom:
            phantom_trades.append(trade)
        else:
            real_trades.append(trade)
    
    print(f"\nOriginal closed trades: {original_count}")
    print(f"Real trades (with order IDs): {len(real_trades)}")
    print(f"Phantom trades (no order IDs): {len(phantom_trades)}")
    
    # Show breakdown by reason
    reasons = {}
    for trade in phantom_trades:
        reason = trade.get('reason', 'unknown')
        reasons[reason] = reasons.get(reason, 0) + 1
    
    print("\nPhantom trades by reason:")
    for reason, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  {reason:25s}: {count:3d}")
    
    # Ask for confirmation
    print(f"\nThis will REMOVE {len(phantom_trades)} phantom trades.")
    print(f"Keeping {len(real_trades)} real trades.")
    
    response = input("\nProceed? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Aborted.")
        return
    
    # Update data
    data['closed'] = real_trades
    
    # Save
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ DONE!")
    print(f"Removed: {len(phantom_trades)} phantom trades")
    print(f"Remaining: {len(real_trades)} real trades")
    print(f"Backup: {backup_path.name}")
    
    # Show recent phantom trades for reference
    print("\n📋 Last 10 phantom trades removed:")
    phantom_trades.sort(key=lambda x: x.get('timestamp', 0))
    for trade in phantom_trades[-10:]:
        dt = datetime.fromtimestamp(trade['timestamp'])
        print(f"  {dt.strftime('%Y-%m-%d %H:%M:%S')} - {trade['market']:15s} - EUR {trade['profit']:7.2f} - {trade.get('reason', 'unknown')}")

if __name__ == '__main__':
    main()
