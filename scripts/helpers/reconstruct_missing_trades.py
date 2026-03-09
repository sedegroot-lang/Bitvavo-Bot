"""
Reconstruct Missing Trades
--------------------------
Dit script haalt alle trades op van Bitvavo en voegt ontbrekende
trades toe aan het archief.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from python_bitvavo_api.bitvavo import Bitvavo
from modules.trade_archive import archive_trade

ARCHIVE_PATH = "data/trade_archive.json"

def get_bitvavo():
    return Bitvavo({
        'APIKEY': os.getenv('BITVAVO_API_KEY'),
        'APISECRET': os.getenv('BITVAVO_API_SECRET'),
    })

def load_archive() -> Dict:
    if os.path.exists(ARCHIVE_PATH):
        with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"trades": [], "metadata": {}}

def get_archive_timestamps(archive: Dict) -> Set[str]:
    """Get set of unique identifiers for archived trades."""
    identifiers = set()
    for t in archive.get("trades", []):
        market = t.get("market", "")
        ts = t.get("timestamp", 0)
        # Create identifier: market + timestamp rounded to minute
        ts_min = int(ts / 60) * 60
        identifiers.add(f"{market}:{ts_min}")
    return identifiers

def main():
    print("=" * 60)
    print("RECONSTRUCT MISSING TRADES")
    print("=" * 60)
    
    bv = get_bitvavo()
    archive = load_archive()
    existing = get_archive_timestamps(archive)
    
    # Markets to check
    markets = [
        'HEI-EUR', 'BTC-EUR', 'ETH-EUR', 'XRP-EUR', 'ADA-EUR', 
        'AVAX-EUR', 'LINK-EUR', 'FET-EUR', 'NEAR-EUR', 'DOT-EUR', 
        'UNI-EUR', 'LDO-EUR', 'SNX-EUR', 'INJ-EUR', 'ARB-EUR', 
        'OP-EUR', 'RUNE-EUR', 'SOL-EUR', 'ALGO-EUR'
    ]
    
    # Fetch all orders from last 30 days
    cutoff = (datetime.now() - timedelta(days=30)).timestamp() * 1000
    
    all_orders = []
    for market in markets:
        try:
            orders = bv.getOrders(market, {'limit': 500})
            for o in orders:
                o['_market'] = market
                all_orders.append(o)
        except Exception as e:
            print(f"Error fetching {market}: {e}")
    
    # Filter filled orders
    filled = [o for o in all_orders if o.get('status') == 'filled' and o.get('created', 0) > cutoff]
    filled.sort(key=lambda x: x.get('created', 0))
    
    print(f"\nGevonden orders (laatste 30 dagen): {len(filled)}")
    
    # Match buys with sells
    buys_by_market: Dict[str, List] = {}
    sells_by_market: Dict[str, List] = {}
    
    for o in filled:
        market = o.get('_market')
        ts = o.get('created', 0) / 1000
        side = o.get('side')
        amount = float(o.get('filledAmount', 0) or 0)
        quote = float(o.get('filledAmountQuote', 0) or 0)
        
        if amount <= 0:
            continue
            
        price = quote / amount if amount > 0 else 0
        
        entry = {
            'market': market,
            'timestamp': ts,
            'amount': amount,
            'quote': quote,
            'price': price,
            'order': o
        }
        
        if side == 'buy':
            if market not in buys_by_market:
                buys_by_market[market] = []
            buys_by_market[market].append(entry)
        else:
            if market not in sells_by_market:
                sells_by_market[market] = []
            sells_by_market[market].append(entry)
    
    # Try to match sells with preceding buys
    reconstructed = []
    
    for market, sells in sells_by_market.items():
        buys = buys_by_market.get(market, [])
        
        for sell in sells:
            sell_ts = sell['timestamp']
            sell_amount = sell['amount']
            sell_price = sell['price']
            
            # Find best matching buy (closest preceding buy)
            best_buy = None
            best_diff = float('inf')
            
            for buy in buys:
                if buy['timestamp'] < sell_ts:
                    diff = sell_ts - buy['timestamp']
                    # Match if within 7 days and amount is similar
                    if diff < 7 * 24 * 3600:
                        amount_diff = abs(buy['amount'] - sell_amount) / max(buy['amount'], 0.0001)
                        if amount_diff < 0.1 and diff < best_diff:  # Allow 10% difference
                            best_buy = buy
                            best_diff = diff
            
            if best_buy:
                # Calculate profit
                profit = (sell_price - best_buy['price']) * sell_amount
                
                # Check if already in archive
                ts_min = int(sell_ts / 60) * 60
                identifier = f"{market}:{ts_min}"
                
                if identifier not in existing:
                    trade = {
                        'market': market,
                        'buy_price': best_buy['price'],
                        'sell_price': sell_price,
                        'amount': sell_amount,
                        'profit': round(profit, 4),
                        'timestamp': sell_ts,
                        'reason': 'reconstructed',
                        'buy_timestamp': best_buy['timestamp'],
                    }
                    reconstructed.append(trade)
                    existing.add(identifier)
    
    print(f"\nOntbrekende trades gevonden: {len(reconstructed)}")
    
    if reconstructed:
        print("\n--- Te reconstrueren trades ---")
        total_profit = 0
        for t in sorted(reconstructed, key=lambda x: x['timestamp']):
            ts = datetime.fromtimestamp(t['timestamp']).strftime('%d-%m-%Y %H:%M')
            print(f"  {ts} {t['market']:<10} buy={t['buy_price']:.4f} sell={t['sell_price']:.4f} profit={t['profit']:+.2f} EUR")
            total_profit += t['profit']
        
        print(f"\nTotaal ontbrekende winst: {total_profit:+.2f} EUR")
        
        # Ask for confirmation
        response = input("\nToevoegen aan archief? (ja/nee): ").strip().lower()
        
        if response == 'ja':
            for t in reconstructed:
                archive_trade(
                    market=t['market'],
                    buy_price=t['buy_price'],
                    sell_price=t['sell_price'],
                    amount=t['amount'],
                    profit=t['profit'],
                    timestamp=t['timestamp'],
                    reason='reconstructed',
                    original_buy_timestamp=t.get('buy_timestamp')
                )
            print(f"\n✅ {len(reconstructed)} trades toegevoegd aan archief!")
        else:
            print("\n❌ Geannuleerd.")
    else:
        print("\n✅ Geen ontbrekende trades gevonden!")

if __name__ == "__main__":
    main()
