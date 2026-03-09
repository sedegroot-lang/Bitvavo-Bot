#!/usr/bin/env python3
"""
Invested EUR Sync Tool - Houdt invested_eur correct op basis van Bitvavo trades.

Dit script:
1. Haalt actuele posities op van Bitvavo
2. Berekent de correcte invested_eur voor elke positie
3. Corrigeert trade_log.json indien nodig

Formule: invested_eur = SUM(buys) - SUM(sells) voor huidige positie
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from python_bitvavo_api.bitvavo import Bitvavo

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_bitvavo_client() -> Bitvavo:
    """Get Bitvavo API client."""
    return Bitvavo({
        'APIKEY': os.getenv('BITVAVO_API_KEY'),
        'APISECRET': os.getenv('BITVAVO_API_SECRET')
    })


def calculate_invested_for_position(bitvavo: Bitvavo, market: str, current_amount: float, position: dict = None) -> dict:
    """
    Calculate the correct invested_eur for a position by tracing trade history.
    
    IMPORTANT: This function is DISABLED for positions that already have valid
    initial_invested_eur. Historical trade calculation corrupts data for positions
    that had previous buy/sell cycles.
    
    Returns dict with:
    - invested_eur: Current exposure (after TPs)
    - total_invested_eur: Total bought value (for profit calc)
    - dca_count: Number of DCA orders (buys after initial)
    
    Returns None if position is protected (has valid initial_invested_eur > 0).
    """
    # =========================================================================
    # PROTECTION: Don't recalculate for positions with valid data!
    # The historical trade calculation is BROKEN for coins with previous cycles.
    # XRP, ADA etc. had buy/sell cycles before current position - API returns
    # ALL trades, not just current position, causing wrong invested_eur.
    # =========================================================================
    if position:
        initial = position.get('initial_invested_eur', 0)
        invested = position.get('invested_eur', 0)
        if initial and initial > 0 and invested and invested > 0:
            # Position has valid data - DO NOT recalculate from history!
            logger.info(f"  PROTECTED: Position has initial_invested_eur={initial}, keeping current values")
            return None
    
    trades = bitvavo.trades(market, {'limit': 100})
    if not trades:
        return None
    
    # Sort by timestamp (oldest first)
    trades.sort(key=lambda x: int(x['timestamp']))
    
    # Find the start of current position by working backwards
    running_amount = 0
    position_start_idx = 0
    
    for i, t in enumerate(trades):
        amount = float(t['amount'])
        if t['side'] == 'buy':
            running_amount += amount
        else:
            running_amount -= amount
        
        # If we've reached the current amount, this is our position
        if abs(running_amount - current_amount) < 0.001:
            # Find where this position started (last time we had 0)
            temp_amount = 0
            for j in range(i + 1):
                temp_t = trades[j]
                temp_a = float(temp_t['amount'])
                if temp_t['side'] == 'buy':
                    temp_amount += temp_a
                else:
                    temp_amount -= temp_a
                if temp_amount < 0.001:
                    position_start_idx = j + 1
            break
    
    # Calculate invested from position start
    total_bought = 0
    total_sold = 0
    buy_timestamps = []
    
    for i in range(position_start_idx, len(trades)):
        t = trades[i]
        amount = float(t['amount'])
        price = float(t['price'])
        value = amount * price
        ts = int(t['timestamp'])
        
        if t['side'] == 'buy':
            total_bought += value
            buy_timestamps.append(ts)
        else:
            total_sold += value
    
    # Count DCA orders (buys with >60 seconds gap from initial)
    dca_count = 0
    if len(buy_timestamps) > 1:
        initial_ts = buy_timestamps[0]
        for ts in buy_timestamps[1:]:
            # If more than 60 seconds after initial, it's a DCA
            if (ts - initial_ts) > 60000:  # milliseconds
                dca_count += 1
    
    invested_eur = total_bought - total_sold
    
    return {
        'invested_eur': round(invested_eur, 2),
        'total_invested_eur': round(total_bought, 2),
        'dca_count': dca_count
    }


def sync_invested_eur(dry_run: bool = False) -> dict:
    """
    Sync invested_eur in trade_log.json with actual Bitvavo trades.
    
    Args:
        dry_run: If True, don't save changes, just report
    
    Returns:
        Dict with corrections made
    """
    bitvavo = get_bitvavo_client()
    trade_log_path = PROJECT_ROOT / 'data' / 'trade_log.json'
    
    # Load current trade log
    with open(trade_log_path) as f:
        trade_log = json.load(f)
    
    # Get current balances
    balances = bitvavo.balance({})
    balance_map = {}
    for coin in balances:
        available = float(coin.get('available', 0) or 0)
        in_order = float(coin.get('inOrder', 0) or 0)
        total = available + in_order
        if total > 0:
            balance_map[coin['symbol']] = total
    
    corrections = []
    
    for market, position in trade_log.get('open', {}).items():
        symbol = market.split('-')[0]
        current_amount = balance_map.get(symbol, 0)
        
        if current_amount < 0.001:
            logger.warning(f"{market}: No balance found on Bitvavo!")
            continue
        
        # Calculate correct values - pass position for protection check
        result = calculate_invested_for_position(bitvavo, market, current_amount, position)
        
        if not result:
            # Position is protected or could not calculate
            current_invested = position.get('invested_eur', 0)
            current_dca = position.get('dca_buys', 0)
            logger.info(f"{market}: OK (protected, invested={current_invested:.2f}, dca={current_dca})")
            continue
        
        current_invested = position.get('invested_eur', 0)
        current_total = position.get('total_invested_eur', 0)
        current_dca = position.get('dca_buys', 0)
        
        correct_invested = result['invested_eur']
        correct_total = result['total_invested_eur']
        correct_dca = result['dca_count']
        
        # Check for differences
        needs_update = False
        updates = {}
        
        if abs(current_invested - correct_invested) > 0.50:
            needs_update = True
            updates['invested_eur'] = (current_invested, correct_invested)
            
        if abs(current_total - correct_total) > 0.50:
            needs_update = True
            updates['total_invested_eur'] = (current_total, correct_total)
            
        if current_dca != correct_dca:
            needs_update = True
            updates['dca_buys'] = (current_dca, correct_dca)
        
        if needs_update:
            logger.info(f"{market}: Correction needed!")
            for field, (old, new) in updates.items():
                logger.info(f"  {field}: {old} -> {new}")
            
            corrections.append({
                'market': market,
                'updates': updates
            })
            
            if not dry_run:
                position['invested_eur'] = correct_invested
                position['total_invested_eur'] = correct_total
                position['dca_buys'] = correct_dca
        else:
            logger.info(f"{market}: OK (invested={current_invested:.2f}, dca={current_dca})")
    
    # Save if changes made
    if corrections and not dry_run:
        # Backup first
        backup_path = PROJECT_ROOT / 'backups' / f'trade_log_pre_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        backup_path.parent.mkdir(exist_ok=True)
        with open(backup_path, 'w') as f:
            json.dump(trade_log, f, indent=2)
        logger.info(f"Backup saved to {backup_path}")
        
        # Save corrected
        with open(trade_log_path, 'w') as f:
            json.dump(trade_log, f, indent=2)
        logger.info(f"trade_log.json updated with {len(corrections)} corrections")
    
    return {
        'corrections': corrections,
        'total': len(corrections)
    }


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync invested_eur with Bitvavo trades')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without saving')
    args = parser.parse_args()
    
    print("=" * 60)
    print("INVESTED EUR SYNC TOOL")
    print("=" * 60)
    print()
    
    result = sync_invested_eur(dry_run=args.dry_run)
    
    print()
    print("=" * 60)
    if result['total'] == 0:
        print("✅ All positions correct!")
    else:
        print(f"{'Would correct' if args.dry_run else 'Corrected'}: {result['total']} positions")
    print("=" * 60)
