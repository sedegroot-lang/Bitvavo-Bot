"""Data migration script: Add immutable initial_invested_eur and dca_events to existing trades.

WHAT THIS DOES:
1. Backs up trade_log.json with timestamp
2. Adds initial_invested_eur (immutable baseline) = current invested_eur
3. Adds total_invested_eur = current invested_eur (will grow with DCAs)
4. Adds empty dca_events: [] list (future DCA buys will append here)
5. Preserves all existing trade data

RUN THIS BEFORE DEPLOYING NEW CODE.

Usage:
    python scripts/migrate_invest_fields.py --execute
    
Options:
    --dry-run: Show what would be changed (default)
    --execute: Actually perform the migration
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"
BACKUP_DIR = PROJECT_ROOT / "backups"


def backup_trade_log():
    """Create timestamped backup of trade_log.json."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"trade_log_pre_migration_{timestamp}.json"
    shutil.copy2(TRADE_LOG_PATH, backup_path)
    print(f"✅ Backup created: {backup_path}")
    return backup_path


def load_trade_log():
    """Load current trade_log.json."""
    with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_trade_log(data):
    """Save migrated trade_log.json."""
    with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def migrate_trade(trade: dict, market: str) -> dict:
    """Add immutable initial_invested_eur and dca_events to a single trade."""
    migrated = trade.copy()
    
    # 1. Set initial_invested_eur (IMMUTABLE baseline for P/L)
    if 'initial_invested_eur' not in migrated:
        # Use existing invested_eur or calculate from buy_price * amount
        invested_eur = migrated.get('invested_eur')
        if invested_eur is not None:
            migrated['initial_invested_eur'] = float(invested_eur)
        else:
            buy_price = float(migrated.get('buy_price', 0) or 0)
            amount = float(migrated.get('amount', 0) or 0)
            migrated['initial_invested_eur'] = buy_price * amount
        
        print(f"  {market}: Set initial_invested_eur = €{migrated['initial_invested_eur']:.2f}")
    
    # 2. Set total_invested_eur (will grow with DCAs)
    if 'total_invested_eur' not in migrated:
        migrated['total_invested_eur'] = migrated.get('invested_eur') or migrated['initial_invested_eur']
        print(f"  {market}: Set total_invested_eur = €{migrated['total_invested_eur']:.2f}")
    
    # 3. Add empty dca_events list (future DCAs will append here)
    if 'dca_events' not in migrated:
        migrated['dca_events'] = []
        print(f"  {market}: Added dca_events = []")
    
    # 4. Keep dca_buys counter for backward compatibility
    # Future code will sync len(dca_events) with dca_buys
    
    return migrated


def run_migration(dry_run=True):
    """Execute the migration."""
    print("=" * 70)
    print(" INVEST FIELDS MIGRATION SCRIPT")
    print("=" * 70)
    print()
    
    if not TRADE_LOG_PATH.exists():
        print(f"❌ Error: {TRADE_LOG_PATH} not found")
        return False
    
    print(f"📁 Loading: {TRADE_LOG_PATH}")
    data = load_trade_log()
    
    open_trades = data.get('open', {})
    closed_trades = data.get('closed', [])
    
    print(f"📊 Found: {len(open_trades)} open trades, {len(closed_trades)} closed trades")
    print()
    
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be saved")
    else:
        print("⚠️  EXECUTE MODE - Changes will be saved")
        backup_path = backup_trade_log()
        print()
    
    print("-" * 70)
    print("MIGRATING OPEN TRADES:")
    print("-" * 70)
    
    migrated_open = {}
    for market, trade in open_trades.items():
        migrated_open[market] = migrate_trade(trade, market)
    
    print()
    print("-" * 70)
    print("MIGRATING CLOSED TRADES:")
    print("-" * 70)
    
    migrated_closed = []
    for i, trade in enumerate(closed_trades):
        market = trade.get('market', f'closed_{i}')
        migrated_closed.append(migrate_trade(trade, market))
    
    print()
    print("=" * 70)
    print("MIGRATION SUMMARY:")
    print("=" * 70)
    print(f"✅ Open trades migrated: {len(migrated_open)}")
    print(f"✅ Closed trades migrated: {len(migrated_closed)}")
    
    if dry_run:
        print()
        print("🔍 This was a DRY RUN. To execute migration, run:")
        print("   python scripts/migrate_invest_fields.py --execute")
        return True
    
    # Save migrated data
    migrated_data = {
        'open': migrated_open,
        'closed': migrated_closed,
        'profits': data.get('profits', {})
    }
    
    save_trade_log(migrated_data)
    print()
    print(f"✅ Migration complete! Saved to: {TRADE_LOG_PATH}")
    print(f"🔒 Backup available at: {backup_path}")
    print()
    print("🚀 You can now deploy the new code with invest immutability fixes.")
    
    return True


def main():
    """Main entry point."""
    dry_run = True
    
    if len(sys.argv) > 1:
        if "--execute" in sys.argv:
            dry_run = False
        elif "--help" in sys.argv or "-h" in sys.argv:
            print(__doc__)
            return
    
    success = run_migration(dry_run=dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
