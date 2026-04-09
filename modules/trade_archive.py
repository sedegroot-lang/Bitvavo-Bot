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

# Trades before this timestamp are "dev" phase, after are "production"
# 2026-03-09 00:00:00 local time (CET)
PRODUCTION_CUTOFF_TS = 1773010800.0


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
            phase = "production" if timestamp >= PRODUCTION_CUTOFF_TS else "dev"
            trade_record = {
                "market": market,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "amount": amount,
                "profit": profit,
                "timestamp": timestamp,
                "reason": reason,
                "archived_at": time.time(),
                "phase": phase,
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
    market: Optional[str] = None,
    phase: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retrieve trades from archive with optional filters.
    
    Args:
        exclude_sync_removed: If True, filter out sync_removed trades
        since_timestamp: Only return trades after this timestamp
        market: Only return trades for this market
        phase: Only return trades with this phase ("dev" or "production")
    
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

            if phase is not None:
                trades = [t for t in trades if _get_phase(t) == phase]
            
            return trades
            
        except Exception as e:
            print(f"[ARCHIVE ERROR] Failed to read trades: {e}")
            return []


def recover_cost_from_archive(market: str, current_amount: float) -> Optional[Dict[str, Any]]:
    """Recover cost basis for an orphaned position from the trade archive.

    When the sync engine finds a Bitvavo balance with no matching trade_log entry
    and derive_cost_basis fails (e.g. old fills purged), this function checks the
    archive for the most recent partial_tp or open trade for the same market.  If
    the archived buy_price is plausible it returns a dict with recovered values.

    Returns ``None`` when no usable archive data is found.

    Returned dict keys:
        buy_price, invested_eur, initial_invested_eur, total_invested_eur, source
    """
    try:
        trades = get_all_trades(market=market)
        if not trades:
            return None

        # Sort newest first
        trades.sort(key=lambda t: t.get('timestamp', 0), reverse=True)

        # 1. Look for the most recent partial_tp — that means the position was
        #    partially sold and a remainder still exists on the exchange.
        for t in trades:
            reason = str(t.get('reason', ''))
            if 'partial_tp' not in reason:
                continue
            archived_bp = float(t.get('buy_price', 0) or 0)
            if archived_bp <= 0:
                continue
            # The remaining invested_eur after a partial TP:
            # the original trade invested more, but part was returned.
            invested = round(current_amount * archived_bp, 2)
            return {
                'buy_price': archived_bp,
                'invested_eur': invested,
                'initial_invested_eur': invested,
                'total_invested_eur': invested,
                'source': f'archive_partial_tp ({reason})',
            }

        # 2. Fall back to the most recent closed trade for this market and use
        #    its buy_price as best estimate.
        for t in trades:
            archived_bp = float(t.get('buy_price', 0) or 0)
            if archived_bp <= 0:
                continue
            invested = round(current_amount * archived_bp, 2)
            return {
                'buy_price': archived_bp,
                'invested_eur': invested,
                'initial_invested_eur': invested,
                'total_invested_eur': invested,
                'source': f'archive_last_trade ({t.get("reason", "?")})',
            }

        return None
    except Exception as e:
        print(f"[ARCHIVE] recover_cost_from_archive({market}) failed: {e}")
        return None


def get_archive_stats(phase: Optional[str] = None) -> Dict[str, Any]:
    """Get archive statistics, optionally filtered by phase."""
    with LOCK:
        try:
            _ensure_archive_exists()
            
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)
            
            trades = archive.get("trades", [])
            if phase is not None:
                trades = [t for t in trades if _get_phase(t) == phase]
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


def _get_phase(trade: Dict[str, Any]) -> str:
    """Return the phase of a trade: 'dev' or 'production'."""
    if "phase" in trade:
        return trade["phase"]
    # Fallback for trades not yet tagged: derive from timestamp
    ts = float(trade.get("timestamp", 0) or 0)
    return "production" if ts >= PRODUCTION_CUTOFF_TS else "dev"


def tag_phases() -> int:
    """One-time migration: add 'phase' field to all existing archive trades."""
    with LOCK:
        try:
            _ensure_archive_exists()
            with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
                archive = json.load(f)

            tagged = 0
            for trade in archive.get("trades", []):
                if "phase" not in trade:
                    trade["phase"] = _get_phase(trade)
                    tagged += 1

            if tagged > 0:
                archive["metadata"]["phases_tagged_at"] = time.time()
                temp_path = ARCHIVE_PATH.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(archive, f, indent=2)
                temp_path.replace(ARCHIVE_PATH)

                try:
                    from core.local_state import mirror_to_local
                    mirror_to_local(str(ARCHIVE_PATH), archive)
                except Exception:
                    pass

            return tagged
        except Exception as e:
            print(f"[ARCHIVE ERROR] tag_phases failed: {e}")
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
