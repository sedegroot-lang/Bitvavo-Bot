"""
Permanent Trade Archive - Never delete trade history
Stores all trades in append-only format for AI/RL training and analytics.
"""

import json
import os
import time
import threading
from typing import Dict, List, Optional, Any
from pathlib import Path

ARCHIVE_PATH = Path("data/trade_archive.json")
LOCK = threading.Lock()


def _ensure_archive_exists() -> None:
    """Create archive file if it doesn't exist."""
    if not ARCHIVE_PATH.exists():
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVE_PATH, 'w', encoding='utf-8') as f:
            json.dump({"trades": [], "metadata": {"created": time.time(), "total_trades": 0}}, f, indent=2)


def archive_trade(
    market: str,
    buy_price: float,
    sell_price: float,
    amount: float,
    profit: float,
    timestamp: float,
    reason: str,
    **extra_data
) -> bool:
    """
    Append a trade to the permanent archive.
    
    Args:
        market: Trading pair (e.g., "BTC-EUR")
        buy_price: Average buy price
        sell_price: Sell price (can be 0 for sync_removed)
        amount: Amount traded
        profit: Realized profit in EUR
        timestamp: Unix timestamp of trade close
        reason: Close reason (stop, trailing_tp, sync_removed, etc.)
        **extra_data: Additional fields (dca_buys, tp_levels_done, etc.)
    
    Returns:
        True if archived successfully, False otherwise
    """
    with LOCK:
        try:
            _ensure_archive_exists()
            
            # Load existing archive
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)
            
            # Create trade record
            trade_record = {
                "market": market,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "amount": amount,
                "profit": profit,
                "timestamp": timestamp,
                "reason": reason,
                "archived_at": time.time(),
                **extra_data  # Include DCA info, TP levels, etc.
            }
            
            # Append trade (never delete)
            archive["trades"].append(trade_record)
            archive["metadata"]["total_trades"] = len(archive["trades"])
            archive["metadata"]["last_updated"] = time.time()
            
            # Write back atomically
            temp_path = ARCHIVE_PATH.with_suffix('.tmp')
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(archive, f, indent=2)
            temp_path.replace(ARCHIVE_PATH)

            # Mirror to %LOCALAPPDATA% — safe from OneDrive reverts
            try:
                from core.local_state import mirror_to_local
                mirror_to_local(str(ARCHIVE_PATH), archive)
            except Exception:
                pass
            
            return True
            
        except Exception as e:
            print(f"[ARCHIVE ERROR] Failed to archive trade {market}: {e}")
            return False


def get_all_trades(
    exclude_sync_removed: bool = False,
    since_timestamp: Optional[float] = None,
    market: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve trades from archive with optional filters.
    
    Args:
        exclude_sync_removed: If True, filter out sync_removed trades
        since_timestamp: Only return trades after this timestamp
        market: Only return trades for this market
    
    Returns:
        List of trade records
    """
    with LOCK:
        try:
            _ensure_archive_exists()
            
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)

            # Use the freshest copy (local vs OneDrive)
            try:
                from core.local_state import load_freshest
                freshest = load_freshest(str(ARCHIVE_PATH), archive)
                if freshest and isinstance(freshest.get('trades'), list):
                    if len(freshest['trades']) >= len(archive.get('trades', [])):
                        freshest.pop('_save_ts', None)
                        archive = freshest
            except Exception:
                pass

            trades = archive.get("trades", [])
            
            # Apply filters
            if exclude_sync_removed:
                trades = [t for t in trades if t.get("reason") != "sync_removed"]
            
            if since_timestamp is not None:
                trades = [t for t in trades if t.get("timestamp", 0) >= since_timestamp]
            
            if market is not None:
                trades = [t for t in trades if t.get("market") == market]
            
            return trades
            
        except Exception as e:
            print(f"[ARCHIVE ERROR] Failed to read trades: {e}")
            return []


def get_archive_stats() -> Dict[str, Any]:
    """Get archive statistics."""
    with LOCK:
        try:
            _ensure_archive_exists()
            
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)
            
            trades = archive.get("trades", [])
            real_trades = [t for t in trades if t.get("reason") != "sync_removed"]
            
            total_profit = sum(t.get("profit", 0) for t in real_trades)
            wins = [t for t in real_trades if t.get("profit", 0) > 0]
            losses = [t for t in real_trades if t.get("profit", 0) < 0]
            
            return {
                "total_trades": len(trades),
                "real_trades": len(real_trades),
                "sync_removed": len(trades) - len(real_trades),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": len(wins) / len(real_trades) * 100 if real_trades else 0,
                "total_profit": total_profit,
                "avg_profit": total_profit / len(real_trades) if real_trades else 0,
                "created": archive.get("metadata", {}).get("created", 0),
                "last_updated": archive.get("metadata", {}).get("last_updated", 0)
            }
            
        except Exception as e:
            print(f"[ARCHIVE ERROR] Failed to get stats: {e}")
            return {}


def migrate_from_trade_log(trade_log_path: str = "data/trade_log.json") -> int:
    """
    Import trades from existing trade_log.json into archive.
    
    Args:
        trade_log_path: Path to trade_log.json
    
    Returns:
        Number of trades migrated
    """
    try:
        with open(trade_log_path, 'r', encoding='utf-8') as f:
            trade_log = json.load(f)
        
        closed_trades = trade_log.get("closed", [])
        migrated = 0
        
        for trade in closed_trades:
            success = archive_trade(
                market=trade.get("market", "UNKNOWN"),
                buy_price=trade.get("buy_price", 0),
                sell_price=trade.get("sell_price", 0),
                amount=trade.get("amount", 0),
                profit=trade.get("profit", 0),
                timestamp=trade.get("timestamp", time.time()),
                reason=trade.get("reason", "unknown"),
                # Extra fields if present
                dca_buys=trade.get("dca_buys"),
                tp_levels_done=trade.get("tp_levels_done"),
                invested_eur=trade.get("invested_eur")
            )
            if success:
                migrated += 1
        
        print(f"[ARCHIVE] Migrated {migrated} trades from {trade_log_path}")
        return migrated
        
    except Exception as e:
        print(f"[ARCHIVE ERROR] Migration failed: {e}")
        return 0


def cleanup_duplicates() -> int:
    """
    Remove duplicate trades (same market, timestamp, profit).
    Use with caution - only run once after migration.
    
    Returns:
        Number of duplicates removed
    """
    with LOCK:
        try:
            _ensure_archive_exists()
            
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)
            
            trades = archive.get("trades", [])
            seen = set()
            unique_trades = []
            duplicates = 0
            
            for trade in trades:
                # Create unique key
                key = (
                    trade.get("market"),
                    trade.get("timestamp"),
                    trade.get("profit"),
                    trade.get("buy_price")
                )
                
                if key not in seen:
                    seen.add(key)
                    unique_trades.append(trade)
                else:
                    duplicates += 1
            
            if duplicates > 0:
                archive["trades"] = unique_trades
                archive["metadata"]["total_trades"] = len(unique_trades)
                archive["metadata"]["last_cleaned"] = time.time()
                
                with open(ARCHIVE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(archive, f, indent=2)
                
                print(f"[ARCHIVE] Removed {duplicates} duplicate trades")
            
            return duplicates
            
        except Exception as e:
            print(f"[ARCHIVE ERROR] Cleanup failed: {e}")
            return 0


if __name__ == "__main__":
    # Test/migration script
    print("Trade Archive System - Test & Migration")
    print("=" * 50)
    
    # Show current stats
    stats = get_archive_stats()
    print(f"\nCurrent archive stats:")
    print(f"  Total trades: {stats.get('total_trades', 0)}")
    print(f"  Real trades: {stats.get('real_trades', 0)}")
    print(f"  Win rate: {stats.get('win_rate', 0):.1f}%")
    print(f"  Total P/L: EUR {stats.get('total_profit', 0):.2f}")
    
    # Migrate if needed
    if stats.get('total_trades', 0) == 0:
        print("\n[!] Archive empty - running migration...")
        migrated = migrate_from_trade_log()
        print(f"[✓] Migrated {migrated} trades")
        
        # Show updated stats
        stats = get_archive_stats()
        print(f"\nUpdated archive stats:")
        print(f"  Total trades: {stats.get('total_trades', 0)}")
        print(f"  Real trades: {stats.get('real_trades', 0)}")
        print(f"  Win rate: {stats.get('win_rate', 0):.1f}%")
        print(f"  Total P/L: EUR {stats.get('total_profit', 0):.2f}")
    
    print("\n" + "=" * 50)
    print("[✓] Archive system ready")
