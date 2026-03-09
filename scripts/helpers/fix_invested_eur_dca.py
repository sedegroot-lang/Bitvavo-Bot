"""
Fix invested_eur for trades with DCAs based on DCA count.

Problem: After partial TP events and multiple DCAs, invested_eur gets corrupted
because derive_cost_basis() calculates based on current amount, not total investment.

This script estimates invested_eur as: BASE_AMOUNT + (dca_buys * DCA_AMOUNT)
where BASE_AMOUNT and DCA_AMOUNT are read from config or assumed defaults.
"""

import json
import os
import time

def main():
    print("=" * 80)
    print("FIXING invested_eur FOR TRADES WITH DCAs")
    print("=" * 80)
    
    # Load config
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'bot_config.json')
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        print(f"ERROR loading config: {e}")
        return
    
    # Get DCA settings
    base_amount = float(config.get('BASE_AMOUNT_EUR', 12))
    dca_amount = float(config.get('DCA_AMOUNT_EUR', 5))
    
    print(f"\nConfig values:")
    print(f"  BASE_AMOUNT_EUR: €{base_amount:.2f}")
    print(f"  DCA_AMOUNT_EUR: €{dca_amount:.2f}")
    
    # Load trade_log.json
    trade_log_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'trade_log.json')
    
    with open(trade_log_path, 'r', encoding='utf-8') as f:
        trade_log = json.load(f)
    
    open_trades = trade_log.get('open', {})
    
    # Identify trades to fix
    trades_to_fix = []
    
    print(f"\n{'Market':<15} {'DCAs':>5} {'Current €':>10} {'Expected €':>10} {'Status'}")
    print("-" * 60)
    
    for market, trade in open_trades.items():
        dca_buys = int(trade.get('dca_buys', 0))
        current_invested = float(trade.get('invested_eur') or 0)
        
        if dca_buys == 0:
            expected_invested = current_invested  # No DCAs = keep current
        else:
            # Calculate expected: base + all DCAs
            expected_invested = base_amount + (dca_buys * dca_amount)
        
        diff = current_invested - expected_invested
        
        # Flag if difference is significant (>€1)
        status = "OK"
        if abs(diff) > 1.0:
            if current_invested < expected_invested:
                status = "TOO LOW"
                trades_to_fix.append((market, trade, expected_invested))
            else:
                status = "TOO HIGH"
        
        print(f"{market:<15} {dca_buys:>5} {current_invested:>10.2f} {expected_invested:>10.2f} {status}")
    
    if not trades_to_fix:
        print("\n✅ All trades have correct invested_eur!")
        return
    
    print(f"\n⚠️  Found {len(trades_to_fix)} trades with incorrect invested_eur")
    print("\nWill update these trades:")
    for market, trade, new_value in trades_to_fix:
        print(f"  {market}: €{trade.get('invested_eur', 0):.2f} → €{new_value:.2f}")
    
    print("\nPress Enter to apply fixes or Ctrl+C to cancel...")
    input()
    
    # Apply fixes
    for market, trade, new_invested in trades_to_fix:
        trade['invested_eur'] = new_invested
    
    # Backup original
    backup_path = trade_log_path + f".backup_{int(time.time())}"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(trade_log, f, indent=2)
    
    print(f"\n✅ Backup saved: {backup_path}")
    
    # Save updated trade_log
    with open(trade_log_path, 'w', encoding='utf-8') as f:
        json.dump(trade_log, f, indent=2)
    
    print(f"✅ Updated {len(trades_to_fix)} trades in trade_log.json")
    print("\n🔄 Please restart the bot for changes to take effect")

if __name__ == '__main__':
    main()
