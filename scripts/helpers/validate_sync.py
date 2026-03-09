#!/usr/bin/env python3
"""
Validate sync between bot trade_log and Bitvavo account.
Run periodically to detect desyncs early.
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from python_bitvavo_api.bitvavo import Bitvavo
from dotenv import load_dotenv
from modules.sync_validator import SyncValidator

# Load environment
load_dotenv()

API_KEY = os.getenv('BITVAVO_API_KEY')
API_SECRET = os.getenv('BITVAVO_API_SECRET')

if not API_KEY or not API_SECRET:
    print("ERROR: BITVAVO_API_KEY and BITVAVO_API_SECRET must be set")
    sys.exit(1)

# Initialize Bitvavo client
bitvavo = Bitvavo({
    'APIKEY': API_KEY,
    'APISECRET': API_SECRET
})

# Initialize validator
trade_log_path = project_root / 'data' / 'trade_log.json'
validator = SyncValidator(bitvavo, trade_log_path)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Validate sync between bot and Bitvavo')
    parser.add_argument('--auto-fix', action='store_true', help='Automatically fix desyncs')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without applying')
    args = parser.parse_args()
    
    print("\n=== BITVAVO SYNC VALIDATION ===\n")
    
    # Validate
    is_synced, issues = validator.validate_sync()
    
    if is_synced:
        print("\n✓ Everything is in sync!")
        return 0
    
    print(f"\n✗ Found {len(issues)} sync issues")
    
    if not args.auto_fix and not args.dry_run:
        print("\nRun with --auto-fix to automatically fix, or --dry-run to see what would be fixed")
        return 1
    
    # Auto-fix
    print("\n=== AUTO-FIX ===\n")
    
    # Fix phantom positions (bot has, Bitvavo doesn't)
    fixed_phantom = validator.auto_fix_phantom_positions(dry_run=args.dry_run)
    
    # Add missing positions (Bitvavo has, bot doesn't)
    added_missing = validator.auto_add_missing_positions(dry_run=args.dry_run)
    
    if args.dry_run:
        print(f"\nDRY RUN complete - no changes made")
        print(f"Would fix: {fixed_phantom} phantom positions, add {added_missing} missing positions")
    else:
        print(f"\n✓ Auto-fix complete: removed {fixed_phantom} phantoms, added {added_missing} missing")
        
        # Re-validate
        print("\n=== RE-VALIDATION ===\n")
        is_synced, issues = validator.validate_sync()
        if is_synced:
            print("\n✓ Sync restored!")
            return 0
        else:
            print(f"\n⚠ Still {len(issues)} issues remaining - manual intervention needed")
            return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
