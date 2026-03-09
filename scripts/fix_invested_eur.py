#!/usr/bin/env python3
"""
Fix invested_eur values using Bitvavo API as authoritative source.

This script:
1. Fetches actual trade fills from Bitvavo API
2. Calculates correct invested_eur from filledAmountQuote
3. Updates trade_log.json with corrected values

Usage:
    python scripts/fix_invested_eur.py --dry-run   # Preview changes
    python scripts/fix_invested_eur.py             # Apply fixes
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

try:
    from python_bitvavo_api.bitvavo import Bitvavo
except ImportError:
    print("ERROR: python_bitvavo_api not installed")
    print("Run: pip install python-bitvavo-api")
    sys.exit(1)

TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"
BACKUP_DIR = PROJECT_ROOT / "backups"


def safe_decimal(value, default=Decimal('0')):
    """Safely convert any value to Decimal."""
    if value is None:
        return default
    try:
        if isinstance(value, float):
            return Decimal(str(value))
        return Decimal(str(value))
    except:
        return default


def load_trade_log():
    """Load trade_log.json."""
    with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_trade_log(data, dry_run=False):
    """Save trade_log.json with backup."""
    if dry_run:
        print("\n🔍 DRY RUN - No changes written")
        return
    
    # Create backup
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = BACKUP_DIR / f"trade_log_pre_fix_{timestamp}.json"
    
    with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
        backup_data = f.read()
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(backup_data)
    print(f"📦 Backup saved to: {backup_path}")
    
    # Write new data
    with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Updated trade_log.json")


def get_bitvavo_client():
    """Create Bitvavo client."""
    api_key = os.getenv('BITVAVO_API_KEY')
    api_secret = os.getenv('BITVAVO_API_SECRET')
    
    if not api_key or not api_secret:
        print("ERROR: BITVAVO_API_KEY and BITVAVO_API_SECRET required in .env")
        sys.exit(1)
    
    return Bitvavo({
        'APIKEY': api_key,
        'APISECRET': api_secret,
    })


def fetch_fills(bitvavo, market, limit=50):
    """Fetch trade fills from API."""
    try:
        trades = bitvavo.trades(market, {'limit': limit})
        if isinstance(trades, dict) and 'error' in trades:
            print(f"  ⚠️  API error for {market}: {trades}")
            return []
        return trades if isinstance(trades, list) else []
    except Exception as e:
        print(f"  ❌ Failed to fetch {market}: {e}")
        return []


def calculate_invested_from_fills(fills, target_amount, side='buy'):
    """
    Calculate invested EUR from fills using EXACT MATCH on the most recent fill.
    
    When a position was fully sold and re-bought, only the most recent buy
    that matches the current amount is relevant.
    
    Args:
        fills: List of trade fills from API
        target_amount: Current position amount
        side: 'buy' or 'sell'
    
    Returns:
        (invested_eur, matched_fills_count, avg_price)
    """
    # Filter and sort by timestamp (NEWEST first - most recent buy is current position)
    buy_fills = sorted(
        [f for f in fills if f.get('side', '').lower() == side],
        key=lambda x: x.get('timestamp', 0),
        reverse=True  # Most recent first
    )
    
    if not buy_fills:
        return Decimal('0'), 0, Decimal('0')
    
    target = safe_decimal(target_amount)
    tolerance = Decimal('0.0001')
    
    # STRATEGY 1: Look for exact match on most recent fill
    for fill in buy_fills:
        amount = safe_decimal(fill.get('amount'))
        price = safe_decimal(fill.get('price'))
        fee = safe_decimal(fill.get('fee'))
        fee_currency = str(fill.get('feeCurrency', '')).upper()
        
        # Check if this single fill matches our position
        if abs(amount - target) <= tolerance:
            cost = price * amount
            if fee_currency == 'EUR':
                cost += fee
            print(f"   ✓ Exact match found: {amount} @ {price}")
            return cost, 1, price
    
    # STRATEGY 2: Accumulate from most recent fills (LIFO for current position)
    accumulated_amount = Decimal('0')
    accumulated_cost = Decimal('0')
    matched_count = 0
    matched_fills = []
    
    for fill in buy_fills:
        amount = safe_decimal(fill.get('amount'))
        price = safe_decimal(fill.get('price'))
        fee = safe_decimal(fill.get('fee'))
        fee_currency = str(fill.get('feeCurrency', '')).upper()
        
        if amount <= 0:
            continue
        
        # Calculate cost for this fill
        cost = price * amount
        if fee_currency == 'EUR':
            cost += fee
        
        accumulated_amount += amount
        accumulated_cost += cost
        matched_count += 1
        matched_fills.append((amount, price))
        
        # Stop when we've matched enough
        if accumulated_amount >= target - tolerance:
            break
    
    avg_price = accumulated_cost / accumulated_amount if accumulated_amount > 0 else Decimal('0')
    
    if matched_count > 1:
        print(f"   ✓ Multiple fills matched: {matched_fills}")
    
    return accumulated_cost, matched_count, avg_price


def fix_trade(trade_data, bitvavo, market):
    """
    Fix a single trade's invested_eur.
    
    Returns:
        (corrections_dict, is_changed)
    """
    corrections = {}
    
    stored_amount = safe_decimal(trade_data.get('amount'))
    stored_invested = safe_decimal(trade_data.get('invested_eur'))
    stored_buy_price = safe_decimal(trade_data.get('buy_price'))
    dca_buys = int(trade_data.get('dca_buys', 0) or 0)
    dca_events = trade_data.get('dca_events', [])
    
    print(f"\n📊 {market}")
    print(f"   Stored: amount={stored_amount}, invested=€{stored_invested}, price={stored_buy_price}")
    print(f"   DCAs: {dca_buys} recorded, {len(dca_events) if dca_events else 0} events")
    
    if stored_amount <= 0:
        print(f"   ⚠️  Zero amount, skipping")
        return corrections, False
    
    # Fetch API data
    fills = fetch_fills(bitvavo, market)
    if not fills:
        print(f"   ⚠️  No API fills found")
        return corrections, False
    
    # Calculate correct values from API
    api_invested, fill_count, api_avg_price = calculate_invested_from_fills(
        fills, stored_amount, side='buy'
    )
    
    # Round for comparison
    api_invested = api_invested.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    print(f"   API:    invested=€{api_invested} (from {fill_count} fills), avg_price={api_avg_price:.6f}")
    
    # Check invested_eur difference
    invested_diff = abs(stored_invested - api_invested)
    if invested_diff > Decimal('0.02'):  # More than 2 cents difference
        corrections['invested_eur'] = float(api_invested)
        
        # Also fix initial/total if no DCAs
        if dca_buys == 0 and not dca_events:
            corrections['initial_invested_eur'] = float(api_invested)
            corrections['total_invested_eur'] = float(api_invested)
        
        print(f"   ⚡ FIX: invested_eur €{stored_invested} → €{api_invested} (diff: €{invested_diff})")
    else:
        print(f"   ✅ invested_eur OK (diff: €{invested_diff})")
    
    # Check buy_price difference
    price_diff_pct = abs(stored_buy_price - api_avg_price) / api_avg_price * 100 if api_avg_price > 0 else 0
    if price_diff_pct > 1:  # More than 1% difference
        corrections['buy_price'] = float(api_avg_price)
        corrections['original_buy_price'] = float(api_avg_price)
        print(f"   ⚡ FIX: buy_price {stored_buy_price:.6f} → {api_avg_price:.6f} ({price_diff_pct:.1f}% diff)")
    
    # Check DCA count consistency
    actual_dca_count = len(dca_events) if isinstance(dca_events, list) else 0
    if dca_buys != actual_dca_count:
        corrections['dca_buys'] = actual_dca_count
        print(f"   ⚡ FIX: dca_buys {dca_buys} → {actual_dca_count} (matches dca_events)")
    
    return corrections, len(corrections) > 0


def main():
    """Main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description='Fix invested_eur from Bitvavo API')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes only')
    parser.add_argument('--market', help='Fix only this market (e.g., XRP-EUR)')
    args = parser.parse_args()
    
    print("=" * 60)
    print("INVESTED_EUR FIXER - Using Bitvavo API as source of truth")
    print("=" * 60)
    
    # Load data
    trade_log = load_trade_log()
    open_trades = trade_log.get('open', {})
    
    if not open_trades:
        print("No open trades found")
        return
    
    # Connect to Bitvavo
    print("\n🔌 Connecting to Bitvavo API...")
    bitvavo = get_bitvavo_client()
    
    # Process trades
    fixed_count = 0
    total_corrections = {}
    
    markets_to_fix = [args.market] if args.market else list(open_trades.keys())
    
    for market in markets_to_fix:
        if market not in open_trades:
            print(f"\n⚠️  Market {market} not found in open trades")
            continue
        
        corrections, changed = fix_trade(open_trades[market], bitvavo, market)
        
        if changed:
            fixed_count += 1
            total_corrections[market] = corrections
            
            # Apply corrections to data structure
            for field, value in corrections.items():
                open_trades[market][field] = value
    
    # Summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {fixed_count} trades fixed")
    print("=" * 60)
    
    if fixed_count > 0:
        for market, corrs in total_corrections.items():
            print(f"\n{market}:")
            for field, value in corrs.items():
                print(f"  {field}: → {value}")
    
    # Save changes
    if fixed_count > 0:
        trade_log['open'] = open_trades
        save_trade_log(trade_log, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
