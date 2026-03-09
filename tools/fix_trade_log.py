"""
Fix trade_log.json: correct sell prices from real Bitvavo data and recalculate profits.

This script:
1. Matches closed trades with real Bitvavo sell transactions
2. Corrects sell_price for stop-loss trades that used ticker price instead of execution price
3. Recalculates profit fields
4. Rebuilds the profits dict
5. Saves corrected trade_log.json
"""
import json
import copy
import shutil
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRADE_LOG = BASE_DIR / "data" / "trade_log.json"
FEE_TAKER = 0.0025

# ============================================================
# Real Bitvavo sell transactions (from user's exchange data)
# Format: (market_base, amount_crypto, net_eur_received)
# For split fills, we aggregate before matching
# ============================================================
bitvavo_sells = [
    # Mar 5
    ("OP",     196.81770623,  20.92),
    ("SHIB",   5463009.17,    25.81),
    ("PEPE",   6941892.0,     21.02),
    ("LINK",   2.71162526,    21.64),
    ("SOL",    0.27588562,    21.47),
    # Mar 4
    ("RENDER", 17.64639133,   21.80),
    ("UNI",    4.98054898,    17.01),
    ("AVAX",   2.81684019,    22.45),
    ("RENDER", 14.38984324,   17.16),
    ("UNI",    1.66018299,     5.79),  # partial TP
    ("RENDER", 4.79661441,     5.83),  # partial TP
    ("LTC",    0.4752529,     22.21),
    # Mar 3
    ("XRP",    18.415377,     21.72),
    ("LINK",   5.961635,      45.62),
    ("POL",    307.58032999,  26.98),
    ("BTC",    0.00011677,     6.89),
    ("SOL",    0.29880996,    21.51),
    # Mar 2
    ("BTC",    0.00011364,     6.71),
    ("ETH",    0.00358585,     6.21),
    ("ETH",    0.00691132,    11.98),
    ("XRP",    6.478416,       7.64),
    ("XRP",    20.722944,     24.46),
    ("AVAX",   4.10146658,    32.20),
    ("LTC",    1.09858752,    50.85),
    ("DOGE",   632.94941006,  51.15),
    ("SOL",    0.44020764,    32.93),
    ("BTC",    0.00010628,     6.20),
    ("ETH",    0.00726572,    12.59),
    ("BTC",    0.00017939,    10.32),
    ("BTC",    0.00017351,     9.98),
    # Mar 1
    ("SOL",    0.47830832,    34.24),
    ("ETH",    0.00365639,     6.20),
    # Feb 28
    ("BTC",    0.00010878,     6.20),
    ("ETH",    0.00374234,     6.20),
    ("BTC",    0.00011288,     6.29),
    ("ETH",    0.00388331,     6.29),
    ("XRP",    16.841954,     18.48),
    ("INJ",    12.73466553,   31.67),
    ("BCH",    0.0404391,     15.39),  # split fill 1
    ("BCH",    0.044448,      16.91),  # split fill 2
    ("AAVE",   0.091319,       8.45),  # split fill 1
    ("AAVE",   0.25999601,    24.08),  # split fill 2
    ("DOGE",   417.28510802,  32.20),
    # Feb 27
    ("SOL",    0.48034788,    34.05),
    ("INJ",    9.14482368,    24.92),
    ("AVAX",   4.25148302,    32.76),
    ("FET",    248.15868154,  34.24),
]


def aggregate_splits(sells):
    """Group sells by market+approximate_amount to handle split fills."""
    # Build lookup: for each market, list of (amount, eur)
    by_market = {}
    for market, amount, eur in sells:
        by_market.setdefault(market, []).append((amount, eur))
    return by_market


def find_bitvavo_match(market_base, amount, bitvavo_by_market):
    """Find matching Bitvavo sell(s) for a bot closed trade."""
    if market_base not in bitvavo_by_market:
        return None
    
    candidates = bitvavo_by_market[market_base]
    
    # 1. Try exact amount match (single fill)
    for i, (bv_amount, bv_eur) in enumerate(candidates):
        if abs(bv_amount - amount) / max(amount, 1e-12) < 0.0001:  # 0.01% tolerance
            return bv_eur
    
    # 2. Try aggregated match (split fills - sum amounts that together match)
    # Try all pairs
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            combined_amount = candidates[i][0] + candidates[j][0]
            combined_eur = candidates[i][1] + candidates[j][1]
            if abs(combined_amount - amount) / max(amount, 1e-12) < 0.0001:
                return combined_eur
    
    return None


def compute_sell_price_from_net(net_eur, amount, fee_rate=FEE_TAKER):
    """Derive per-unit sell price from net EUR received."""
    # net = sell_price * amount * (1 - fee)
    # sell_price = net / (amount * (1 - fee))
    return net_eur / (amount * (1 - fee_rate))


def recalculate_profit(entry, new_sell_price, bitvavo_net_eur):
    """Recalculate profit fields based on corrected sell price."""
    amount = entry.get('amount', 0)
    invested = float(entry.get('invested_eur', entry.get('total_invested_eur', 0)) or 0)
    total_invested = float(entry.get('total_invested_eur', invested) or invested)
    initial_invested = float(entry.get('initial_invested_eur', 0) or 0)
    partial_tp = float(entry.get('partial_tp_returned_eur', 0) or 0)
    
    # Use real Bitvavo net EUR as the actual proceeds
    net_proceeds = bitvavo_net_eur
    
    # profit_remaining = net_proceeds - current_invested
    profit_remaining = round(net_proceeds - invested, 4)
    
    # profit (total) = (net_proceeds + partial_tp) - total_invested
    total_profit = round((net_proceeds + partial_tp) - total_invested, 4)
    
    return {
        'sell_price': new_sell_price,
        'profit': total_profit,
        'profit_remaining': profit_remaining,
    }


def main():
    # Load
    with open(TRADE_LOG, 'r') as f:
        data = json.load(f)
    
    # Backup
    backup_path = BASE_DIR / "backups" / f"trade_log_pre_price_fix_{int(time.time())}.json"
    shutil.copy2(TRADE_LOG, backup_path)
    print(f"Backup: {backup_path}")
    
    closed = data.get('closed', [])
    bitvavo_by_market = aggregate_splits(bitvavo_sells)
    
    # Period: Feb 27 - Mar 5 2026
    # Feb 27 00:00 UTC ≈ 1772179200
    period_start = 1772179200
    
    corrections = []
    
    for i, entry in enumerate(closed):
        ts = entry.get('timestamp', 0)
        if ts < period_start:
            continue
        
        reason = entry.get('reason', '')
        sell_price = entry.get('sell_price', 0)
        amount = entry.get('amount', 0)
        market = entry.get('market', '')
        market_base = market.replace('-EUR', '')
        
        # Skip non-sell entries
        if sell_price <= 0 or reason in ('sync_removed', 'auto_free_slot'):
            continue
        
        # Find matching Bitvavo sell
        bitvavo_net = find_bitvavo_match(market_base, amount, bitvavo_by_market)
        if bitvavo_net is None:
            print(f"  NO MATCH: {market} amount={amount} reason={reason}")
            continue
        
        # Compute expected net from bot's sell_price
        bot_gross = sell_price * amount
        bot_net = bot_gross * (1 - FEE_TAKER)
        
        # Check if prices differ
        net_diff_pct = abs(bitvavo_net - bot_net) / max(bot_net, 0.01) * 100
        
        if net_diff_pct > 0.05:  # More than 0.05% difference
            new_sell_price = compute_sell_price_from_net(bitvavo_net, amount)
            result = recalculate_profit(entry, new_sell_price, bitvavo_net)
            
            old_profit = entry.get('profit', 0)
            old_sell = entry.get('sell_price', 0)
            
            corrections.append({
                'index': i,
                'market': market,
                'reason': reason,
                'old_sell_price': old_sell,
                'new_sell_price': result['sell_price'],
                'old_profit': old_profit,
                'new_profit': result['profit'],
                'bitvavo_net': bitvavo_net,
                'bot_net': round(bot_net, 2),
                'diff_eur': round(bitvavo_net - bot_net, 4),
                'diff_pct': round(net_diff_pct, 2),
            })
            
            # Apply correction
            closed[i]['sell_price'] = round(result['sell_price'], 8)
            closed[i]['profit'] = result['profit']
            if 'profit_remaining' in closed[i]:
                closed[i]['profit_remaining'] = result['profit_remaining']
            closed[i]['_price_corrected'] = True
            closed[i]['_bitvavo_net_eur'] = bitvavo_net
    
    # Rebuild profits dict from ALL closed trades
    new_profits = {}
    for entry in closed:
        market = entry.get('market', '')
        profit = entry.get('profit', 0)
        if market and profit != 0:
            new_profits[market] = new_profits.get(market, 0) + profit
    
    # Round profits
    for k in new_profits:
        new_profits[k] = round(new_profits[k], 6)
    
    data['closed'] = closed
    data['profits'] = new_profits
    
    # Save
    with open(TRADE_LOG, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Report
    print(f"\n{'='*60}")
    print(f"TRADE_LOG.JSON CORRECTIONS")
    print(f"{'='*60}")
    print(f"Total corrections: {len(corrections)}")
    
    total_profit_change = 0
    for c in corrections:
        profit_diff = c['new_profit'] - c['old_profit']
        total_profit_change += profit_diff
        direction = "+" if profit_diff > 0 else ""
        print(f"  {c['market']:12s} ({c['reason']:10s}): "
              f"sell €{c['old_sell_price']:.6f} → €{c['new_sell_price']:.6f} | "
              f"profit €{c['old_profit']:.4f} → €{c['new_profit']:.4f} ({direction}{profit_diff:.4f}) | "
              f"Bitvavo net: €{c['bitvavo_net']:.2f} vs Bot: €{c['bot_net']:.2f} ({direction}{c['diff_eur']:.2f})")
    
    print(f"\nTotal profit impact: {'+' if total_profit_change > 0 else ''}{total_profit_change:.4f} EUR")
    print(f"Profits dict rebuilt from {len(closed)} closed trades")
    print(f"Saved to: {TRADE_LOG}")
    
    return corrections


if __name__ == '__main__':
    corrections = main()
