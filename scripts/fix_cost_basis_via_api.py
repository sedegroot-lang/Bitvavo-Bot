"""
HERSTEL SCRIPT: Bereken exacte cost basis via Bitvavo API trades
=================================================================
Probleem: invested_eur klopt niet door ontbrekende DCA tracking
Oplossing: Haal alle trades op van Bitvavo API en bereken exact
"""

import json
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from python_bitvavo_api.bitvavo import Bitvavo
from modules.cost_basis import derive_cost_basis


def load_config():
    """Laad bot config en system config"""
    # Probeer eerst system_config.json voor API credentials
    system_config_path = PROJECT_ROOT / "config" / "system_config.json"
    if system_config_path.exists():
        with open(system_config_path, 'r') as f:
            return json.load(f)
    
    # Fallback naar bot_config.json
    config_path = PROJECT_ROOT / "config" / "bot_config.json"
    with open(config_path, 'r') as f:
        return json.load(f)


def recalculate_cost_basis(market: str):
    """Bereken exacte cost basis voor een market via API"""
    
    print(f"\n{'='*80}")
    print(f"COST BASIS BEREKENING: {market}")
    print(f"{'='*80}")
    
    # Laad config
    config = load_config()
    
    # Init Bitvavo
    api_key = config.get('api_key', '')
    api_secret = config.get('api_secret', '')
    if not api_key or not api_secret:
        print("❌ Geen API credentials gevonden in config")
        return None
    
    bitvavo = Bitvavo({
        'APIKEY': api_key,
        'APISECRET': api_secret,
        'RESTURL': 'https://api.bitvavo.com/v2',
        'WSURL': 'wss://ws.bitvavo.com/v2/',
        'ACCESSWINDOW': 10000
    })
    
    # Haal trade log op
    trade_log_path = PROJECT_ROOT / "data" / "trade_log.json"
    with open(trade_log_path, 'r') as f:
        trade_log = json.load(f)
    
    trade = trade_log['open'].get(market)
    if not trade:
        print(f"❌ Geen open trade gevonden voor {market}")
        return None
    
    # Trade info
    current_amount = trade.get('amount', 0)
    current_invested = trade.get('invested_eur', 0)
    opened_ts = trade.get('opened_ts') or trade.get('timestamp', 0)
    
    print(f"\n📊 HUIDIGE TRADE DATA:")
    print(f"   Amount: {current_amount:.2f} tokens")
    print(f"   Invested (stored): €{current_invested:.2f}")
    print(f"   Opened timestamp: {opened_ts} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(opened_ts))})")
    
    # Bereken cost basis via API
    print(f"\n🔍 BEREKENEN via Bitvavo API trades...")
    print(f"   Fetching trades vanaf {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(opened_ts))}...")
    
    try:
        result = derive_cost_basis(
            bitvavo=bitvavo,
            market=market,
            target_amount=current_amount,
            opened_ts=opened_ts,
            tolerance=0.02,
            max_iterations=10,
            batch_limit=1000
        )
    except Exception as e:
        print(f"❌ FOUT bij cost basis berekening: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    if not result:
        print(f"❌ Geen cost basis resultaat gevonden")
        return None
    
    # Toon resultaat
    print(f"\n✅ COST BASIS BEREKEND:")
    print(f"   Invested EUR: €{result.invested_eur:.2f}")
    print(f"   Avg Price: €{result.avg_price:.8f}")
    print(f"   Position Amount: {result.position_amount:.2f} tokens")
    print(f"   Position Cost: €{result.position_cost:.2f}")
    print(f"   Amount Diff: {result.amount_diff:.4f}")
    print(f"   Fills Used: {result.fills_used}")
    print(f"   Buy Orders: {result.buy_order_count}")
    if result.earliest_timestamp:
        print(f"   Earliest Trade: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result.earliest_timestamp))}")
    
    # Vergelijking
    print(f"\n📈 VERGELIJKING:")
    print(f"   Stored invested:    €{current_invested:.2f}")
    print(f"   Calculated invested: €{result.invested_eur:.2f}")
    diff = result.invested_eur - current_invested
    diff_pct = (diff / current_invested * 100) if current_invested > 0 else 0
    print(f"   Verschil: €{diff:+.2f} ({diff_pct:+.2f}%)")
    
    if abs(diff) > 1:  # Meer dan €1 verschil
        print(f"\n⚠️  SIGNIFICANT VERSCHIL GEDETECTEERD!")
        print(f"   De stored invested waarde klopt niet met API trades")
    
    return result


def update_trade_log(market: str, result):
    """Update trade_log.json met correcte cost basis"""
    
    trade_log_path = PROJECT_ROOT / "data" / "trade_log.json"
    
    # Backup
    backup_path = trade_log_path.parent / f"trade_log_pre_costbasis_fix_{time.strftime('%Y%m%d_%H%M%S')}.json"
    import shutil
    shutil.copy(trade_log_path, backup_path)
    print(f"\n💾 Backup gemaakt: {backup_path}")
    
    # Laad trade log
    with open(trade_log_path, 'r') as f:
        data = json.load(f)
    
    # Update trade
    trade = data['open'][market]
    old_invested = trade.get('invested_eur', 0)
    old_buy_price = trade.get('buy_price', 0)
    
    # CRITICAL: Only update if initial_invested_eur is missing
    # This prevents corruption of existing trades
    if trade.get('initial_invested_eur') and float(trade.get('initial_invested_eur', 0)) > 0:
        print(f"\n⚠️ SKIPPED: Trade already has initial_invested_eur={trade.get('initial_invested_eur'):.2f}")
        print(f"   Use manual editing if you need to override this value.")
        return
    
    # Update invested values - only for NEW trades without initial data
    trade['invested_eur'] = float(result.invested_eur)
    trade['initial_invested_eur'] = float(result.invested_eur)
    trade['total_invested_eur'] = float(result.invested_eur)
    trade['buy_price'] = float(result.avg_price)
    trade['dca_buys'] = 0  # NEVER set from API
    trade['dca_events'] = []  # ALWAYS empty for new trades
    
    # Sla op
    with open(trade_log_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ TRADE LOG GEÜPDATET:")
    print(f"   invested_eur: €{old_invested:.2f} → €{result.invested_eur:.2f}")
    print(f"   buy_price: €{old_buy_price:.8f} → €{result.avg_price:.8f}")
    print(f"   initial_invested_eur: €{trade['initial_invested_eur']:.2f}")
    print(f"   total_invested_eur: €{trade['total_invested_eur']:.2f}")


if __name__ == "__main__":
    market = "MOODENG-EUR"
    
    print(f"🔧 COST BASIS HERSTEL TOOL")
    print(f"Market: {market}")
    
    # Bereken cost basis
    result = recalculate_cost_basis(market)
    
    if result:
        print(f"\n{'='*80}")
        choice = input("\n❓ Wil je de trade_log.json updaten met deze waarden? (ja/nee): ")
        
        if choice.lower() in ['ja', 'j', 'yes', 'y']:
            update_trade_log(market, result)
            print(f"\n✅ KLAAR! De trade_log.json is geüpdatet.")
            print(f"\n🔄 Herstart de bot om de nieuwe waarden te laden:")
            print(f"   & 'scripts\\restart_bot_stack.ps1'")
        else:
            print(f"\n❌ Geannuleerd, trade_log.json niet aangepast")
    else:
        print(f"\n❌ Kan cost basis niet berekenen")
