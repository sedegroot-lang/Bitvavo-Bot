"""
MIGRATIE SCRIPT: Fix Missing initial_invested_eur/total_invested_eur/dca_events
================================================================================
Probleem: Oude trades missen 'initial_invested_eur', 'total_invested_eur', 'dca_events'
Oplossing: Voeg ze toe op basis van bestaande 'invested_eur' en 'dca_buys'
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trade_log.json"


def migrate_trade_log():
    """Migreer trade_log.json met ontbrekende invested velden"""
    
    print("=" * 80)
    print("MIGRATIE: Fix Missing Invested Fields")
    print("=" * 80)
    
    # Backup maken
    backup_path = TRADE_LOG_PATH.parent / f"trade_log_pre_invest_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy(TRADE_LOG_PATH, backup_path)
    print(f"✅ Backup gemaakt: {backup_path}")
    
    # Laad trade_log
    with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    open_trades = data.get('open', {})
    migrated_count = 0
    already_ok_count = 0
    
    print(f"\n🔍 Checking {len(open_trades)} open trades...")
    
    for market, trade in open_trades.items():
        # Check of velden ontbreken
        missing_fields = []
        if 'initial_invested_eur' not in trade:
            missing_fields.append('initial_invested_eur')
        if 'total_invested_eur' not in trade:
            missing_fields.append('total_invested_eur')
        if 'dca_events' not in trade:
            missing_fields.append('dca_events')
        
        if not missing_fields:
            already_ok_count += 1
            continue
        
        # Migreer trade
        print(f"\n📝 Migreren: {market}")
        print(f"   Ontbrekende velden: {', '.join(missing_fields)}")
        
        invested_eur = trade.get('invested_eur', 0)
        buy_price = trade.get('buy_price', 0)
        amount = trade.get('amount', 0)
        dca_buys = trade.get('dca_buys', 0)
        
        print(f"   invested_eur: €{invested_eur:.2f}")
        print(f"   buy_price: €{buy_price:.8f}")
        print(f"   amount: {amount:.2f} tokens")
        print(f"   dca_buys: {dca_buys}")
        
        # Bereken initial invested
        # Als dca_buys > 0, dan is invested_eur het totaal na DCAs
        # We moeten initial invested schatten
        if dca_buys > 0:
            # Schatting: initial = invested / (1 + dca_buys)
            # Dit is een benadering omdat we geen DCA prijzen hebben
            initial_invested = invested_eur / (1 + dca_buys)
            print(f"   ⚠️  Trade heeft {dca_buys} DCA(s), schatting initial: €{initial_invested:.2f}")
        else:
            # Geen DCA, dus invested = initial
            initial_invested = invested_eur
        
        # Voeg velden toe
        if 'initial_invested_eur' not in trade:
            trade['initial_invested_eur'] = float(initial_invested)
            print(f"   ✅ Added initial_invested_eur: €{initial_invested:.2f}")
        
        if 'total_invested_eur' not in trade:
            trade['total_invested_eur'] = float(invested_eur)
            print(f"   ✅ Added total_invested_eur: €{invested_eur:.2f}")
        
        if 'dca_events' not in trade:
            trade['dca_events'] = []
            print(f"   ✅ Added dca_events: []")
        
        migrated_count += 1
    
    # Sla op
    with open(TRADE_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 80)
    print("MIGRATIE VOLTOOID")
    print("=" * 80)
    print(f"✅ Gemigreerde trades: {migrated_count}")
    print(f"✅ Al correct: {already_ok_count}")
    print(f"💾 Backup: {backup_path}")
    print("=" * 80)
    
    return migrated_count, already_ok_count


if __name__ == "__main__":
    try:
        migrated, ok = migrate_trade_log()
        print(f"\n✅ SUCCES: {migrated} trades gemigreerd, {ok} trades waren al correct")
    except Exception as e:
        print(f"\n❌ FOUT: {e}")
        import traceback
        traceback.print_exc()
