"""
Quick Bitvavo Sync - Detect open positions and add to trade_log.json
"""
import sys
import os
import json
import time
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from python_bitvavo_api.bitvavo import Bitvavo
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BITVAVO_API_KEY")
API_SECRET = os.getenv("BITVAVO_API_SECRET")

if not API_KEY or not API_SECRET:
    print("ERROR: API keys not found in .env")
    sys.exit(1)

bitvavo = Bitvavo({
    'APIKEY': API_KEY,
    'APISECRET': API_SECRET,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/',
    'ACCESSWINDOW': 10000,
    'DEBUGGING': False
})

TRADE_LOG = PROJECT_ROOT / 'data' / 'trade_log.json'

def load_trade_log():
    if TRADE_LOG.exists():
        with open(TRADE_LOG, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"open": {}, "closed": []}

def save_trade_log(data):
    # Create backup
    backup_path = TRADE_LOG.parent / f"trade_log.json.backup_{int(time.time())}"
    if TRADE_LOG.exists():
        import shutil
        shutil.copy(TRADE_LOG, backup_path)
        print(f"Backup created: {backup_path}")
    
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def sync_bitvavo_positions():
    print("=" * 60)
    print("BITVAVO POSITION SYNC")
    print("=" * 60)
    
    # Load current trade_log
    data = load_trade_log()
    open_trades = data.get("open", {})
    
    print(f"Current open trades in trade_log.json: {len(open_trades)}")
    for market, trade in open_trades.items():
        print(f"  - {market}: {trade.get('amount', 0)} @ €{trade.get('buy_price', 0)}")
    
    # Fetch Bitvavo balances
    print("\nFetching Bitvavo balances...")
    balances = bitvavo.balance({})
    
    bitvavo_positions = {}
    for b in balances:
        symbol = b.get('symbol', '')
        available = float(b.get('available', 0))
        if available > 0 and symbol != 'EUR':
            bitvavo_positions[symbol] = available
    
    print(f"\nBitvavo positions found: {len(bitvavo_positions)}")
    for symbol, amount in bitvavo_positions.items():
        print(f"  - {symbol}: {amount}")
    
    # Find missing positions
    missing = []
    for symbol, amount in bitvavo_positions.items():
        market = f"{symbol}-EUR"
        if market not in open_trades:
            missing.append((market, amount))
    
    if not missing:
        print("\n✅ No missing positions - trade_log is synced!")
        return
    
    print(f"\n⚠️ Found {len(missing)} positions on Bitvavo NOT in trade_log.json:")
    for market, amount in missing:
        print(f"  - {market}: {amount}")
    
    # Add missing positions
    print("\nAdding missing positions to trade_log.json...")
    
    # Load config for DCA settings
    config_path = PROJECT_ROOT / 'config' / 'bot_config.json'
    dca_max = 3
    if config_path.exists():
        with open(config_path, 'r') as f:
            config = json.load(f)
            dca_max = config.get('DCA_MAX_BUYS', 3)
    
    for market, amount in missing:
        # Get current price
        try:
            ticker = bitvavo.tickerPrice({'market': market})
            price = float(ticker.get('price', 0))
        except:
            print(f"  ⚠️ Could not get price for {market}, using 0")
            price = 0
        
        if price == 0:
            continue
        
        open_trades[market] = {
            'buy_price': price,
            'highest_price': price,
            'amount': amount,
            'timestamp': time.time(),
            'tp_levels_done': [False, False, False],
            'partial_tp_events': [],
            'dca_buys': 0,
            'dca_max': dca_max,
            'dca_next_price': 0.0,
            'tp_last_time': 0.0,
            'synced_from_bitvavo': True,
        }
        print(f"  ✅ Added {market}: {amount} @ €{price}")
    
    # Save updated trade_log
    data['open'] = open_trades
    save_trade_log(data)
    
    print("\n" + "=" * 60)
    print("SYNC COMPLETED")
    print("=" * 60)
    print(f"Total open trades now: {len(open_trades)}")
    print(f"Added from Bitvavo: {len(missing)}")
    print("\n✅ trade_log.json updated successfully!")

if __name__ == '__main__':
    try:
        sync_bitvavo_positions()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
