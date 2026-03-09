"""
DEDUPLICATION SCRIPT: Remove duplicate closed trades
====================================================
Problem: Same trade logged multiple times (same market, profit, sell price, timestamp nearby)
Solution: Keep only unique trades, remove duplicates
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"


def are_trades_duplicate(trade1, trade2, time_tolerance=300):
    """
    Check if two trades are duplicates
    - Same market
    - Same profit
    - Same sell price
    - Timestamps within time_tolerance seconds (default 5 minutes)
    """
    if trade1.get('market') != trade2.get('market'):
        return False
    
    profit1 = round(trade1.get('profit', 0), 4)
    profit2 = round(trade2.get('profit', 0), 4)
    if profit1 != profit2:
        return False
    
    sell1 = round(trade1.get('sell_price', 0), 8)
    sell2 = round(trade2.get('sell_price', 0), 8)
    if sell1 != sell2:
        return False
    
    ts1 = trade1.get('timestamp', 0)
    ts2 = trade2.get('timestamp', 0)
    if abs(ts1 - ts2) > time_tolerance:
        return False
    
    return True


def deduplicate_trades():
    """Remove duplicate closed trades from trade_log.json"""
    
    print("=" * 80)
    print("TRADE LOG DEDUPLICATION")
    print("=" * 80)
    
    # Backup
    backup_path = TRADE_LOG_PATH.parent / f"trade_log_pre_dedup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy(TRADE_LOG_PATH, backup_path)
    print(f"✅ Backup: {backup_path}")
    
    # Load
    with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    closed_trades = data.get('closed', [])
    print(f"\n📊 Original closed trades: {len(closed_trades)}")
    
    # Find duplicates
    unique_trades = []
    removed_duplicates = []
    
    for i, trade in enumerate(closed_trades):
        is_duplicate = False
        
        # Check if this trade is duplicate of any already added unique trade
        for unique_trade in unique_trades:
            if are_trades_duplicate(trade, unique_trade):
                is_duplicate = True
                removed_duplicates.append({
                    'index': i,
                    'trade': trade,
                    'duplicate_of': unique_trade
                })
                break
        
        if not is_duplicate:
            unique_trades.append(trade)
    
    print(f"📊 Unique trades: {len(unique_trades)}")
    print(f"🗑️  Duplicates removed: {len(removed_duplicates)}")
    
    if removed_duplicates:
        print(f"\n🔍 REMOVED DUPLICATES:")
        for i, dup_info in enumerate(removed_duplicates[:20], 1):  # Show first 20
            trade = dup_info['trade']
            market = trade.get('market')
            profit = trade.get('profit', 0)
            ts = trade.get('timestamp', 0)
            timestr = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            print(f"  {i}. {market}: €{profit:.2f} @ {timestr}")
    
    # Update data
    data['closed'] = unique_trades
    
    # Save
    with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Trade log deduplicated!")
    print(f"💾 Backup: {backup_path}")
    print("=" * 80)
    
    return len(removed_duplicates)


if __name__ == "__main__":
    try:
        removed_count = deduplicate_trades()
        print(f"\n✅ SUCCESS: {removed_count} duplicate trades removed")
        print("\n🔄 Herstart dashboard om nieuwe data te laden:")
        print("   Get-Process python -EA SilentlyContinue | Where-Object {$_.CommandLine -like '*dashboard*'} | Stop-Process -Force")
        print("   & 'C:\\Users\\Sedeg\\OneDrive\\Dokumente\\Bitvavo Bot\\.venv\\Scripts\\python.exe' tools\\dashboard_flask\\app.py")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
