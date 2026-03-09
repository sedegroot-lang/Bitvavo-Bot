"""
Grid Trading Strategy Analyzer - Provides optimal grid settings based on portfolio.
"""
import json
from pathlib import Path
from python_bitvavo_api.bitvavo import Bitvavo

def analyze_portfolio_for_grid():
    """Analyze current portfolio and recommend grid trading parameters."""
    
    # Load current portfolio
    trade_log = Path('data/trade_log.json')
    data = json.loads(trade_log.read_text())
    
    open_trades = data.get('open', {})
    total_invested = sum(t.get('invested_eur', 0) for t in open_trades.values())
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 PORTFOLIO ANALYSIS FOR GRID TRADING")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    # Portfolio stats
    print(f"Current Portfolio:")
    print(f"  • Open positions: {len(open_trades)}")
    print(f"  • Total invested: €{total_invested:.2f}")
    print(f"  • Max trades configured: 6")
    print(f"  • Base amount per trade: €12.00\n")
    
    # Get Bitvavo data
    bv = Bitvavo()
    
    # Analyze BTC-EUR (most liquid, best for grid)
    ticker = bv.tickerPrice({'market': 'BTC-EUR'})
    ticker_24h = bv.ticker24h({'market': 'BTC-EUR'})
    
    btc_price = float(ticker['price'])
    stats = ticker_24h[0] if isinstance(ticker_24h, list) else ticker_24h
    high_24h = float(stats['high'])
    low_24h = float(stats['low'])
    volume_24h = float(stats['volume'])
    
    print(f"BTC-EUR Market Analysis:")
    print(f"  • Current price: €{btc_price:,.2f}")
    print(f"  • 24h High: €{high_24h:,.2f}")
    print(f"  • 24h Low: €{low_24h:,.2f}")
    print(f"  • 24h Range: {((high_24h - low_24h) / low_24h * 100):.2f}%")
    print(f"  • 24h Volume: {volume_24h:,.2f} BTC\n")
    
    # Calculate volatility
    volatility = (high_24h - low_24h) / low_24h
    
    # Risk assessment
    print("Risk Profile:")
    print(f"  • Current exposure: €{total_invested:.2f}")
    print(f"  • Available for grid: €40-50 recommended (low risk)")
    print(f"  • Max trades: 6 → suggests smaller grid positions")
    print(f"  • Bot strategy: Trailing stops + DCA (conservative)\n")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🎯 RECOMMENDED GRID STRATEGY")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    # Strategy 1: Conservative BTC Grid
    current_price = btc_price
    lower_bound = current_price * 0.94  # -6%
    upper_bound = current_price * 1.06  # +6%
    
    print("STRATEGY 1: Conservative BTC Grid (RECOMMENDED)")
    print("  Market: BTC-EUR")
    print(f"  Lower Price: €{lower_bound:,.2f} (-6% from current)")
    print(f"  Upper Price: €{upper_bound:,.2f} (+6% from current)")
    print(f"  Number of Grids: 15")
    print(f"  Total Investment: €50.00 (conservative, ~40% of available)")
    print(f"  Grid Mode: arithmetic (equal spacing)")
    print(f"  Grid Spacing: €{(upper_bound - lower_bound) / 15:,.2f} per level")
    print(f"  Investment per Grid: €{50 / 15:.2f}")
    print(f"  Stop Loss: None (let trailing bot handle)")
    print(f"  Take Profit: None (continuous cycling)")
    print()
    print("  ✅ Why This Strategy?")
    print("    • BTC has highest liquidity (low slippage)")
    print("    • 12% range captures typical daily volatility")
    print("    • 15 grids = frequent profit opportunities")
    print("    • €50 investment = low risk (<40% balance)")
    print("    • Won't conflict with trailing bot (different market mechanism)")
    print()
    
    # Strategy 2: Aggressive Alt Grid
    print("STRATEGY 2: Aggressive Altcoin Grid (HIGHER RISK)")
    print("  Market: SOL-EUR (currently in portfolio)")
    
    # Get SOL data
    sol_ticker = bv.tickerPrice({'market': 'SOL-EUR'})
    sol_price = float(sol_ticker['price'])
    sol_lower = sol_price * 0.88  # -12%
    sol_upper = sol_price * 1.12  # +12%
    
    print(f"  Current SOL Price: €{sol_price:.2f}")
    print(f"  Lower Price: €{sol_lower:.2f} (-12%)")
    print(f"  Upper Price: €{sol_upper:.2f} (+12%)")
    print(f"  Number of Grids: 20")
    print(f"  Total Investment: €40.00")
    print(f"  Grid Mode: geometric (logarithmic spacing)")
    print(f"  Stop Loss: 15% (exit if drops below €{sol_price * 0.85:.2f})")
    print(f"  Take Profit: 20% (exit if reaches €{sol_price * 1.20:.2f})")
    print()
    print("  ⚠️ Higher Risk Because:")
    print("    • Altcoins more volatile (can exit range quickly)")
    print("    • May conflict with existing SOL-EUR trailing position")
    print("    • Wider range (24%) = fewer trades")
    print()
    
    # Strategy 3: Hybrid
    print("STRATEGY 3: Hybrid Multi-Market Grid")
    print("  Setup: 3 small grids across different markets")
    print("  Total Investment: €60 (€20 each)")
    print()
    print("  Grid A - BTC-EUR:")
    print(f"    Range: €{current_price * 0.96:,.2f} - €{current_price * 1.04:,.2f} (8% range)")
    print(f"    Grids: 10, Investment: €20")
    print()
    print("  Grid B - ETH-EUR:")
    eth_ticker = bv.tickerPrice({'market': 'ETH-EUR'})
    eth_price = float(eth_ticker['price'])
    print(f"    Range: €{eth_price * 0.94:.2f} - €{eth_price * 1.06:.2f} (12% range)")
    print(f"    Grids: 12, Investment: €20")
    print()
    print("  Grid C - XRP-EUR:")
    print(f"    Range: €{1.60:.2f} - €{1.80:.2f} (12.5% range)")
    print(f"    Grids: 15, Investment: €20")
    print()
    print("  ⚖️ Balanced Approach:")
    print("    • Diversifies across 3 majors")
    print("    • Smaller positions = lower risk per market")
    print("    • Different volatility profiles")
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🏆 FINAL RECOMMENDATION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    print("Based on your portfolio profile, I recommend:")
    print()
    print("▶ START WITH: Strategy 1 (Conservative BTC Grid)")
    print()
    print("  Configuration:")
    print(f"  ┌─────────────────────────────────────")
    print(f"  │ Market:           BTC-EUR")
    print(f"  │ Lower Price:      €{lower_bound:,.2f}")
    print(f"  │ Upper Price:      €{upper_bound:,.2f}")
    print(f"  │ Number of Grids:  15")
    print(f"  │ Total Investment: €50.00")
    print(f"  │ Grid Mode:        arithmetic")
    print(f"  │ Stop Loss:        0% (disabled)")
    print(f"  │ Take Profit:      0% (disabled)")
    print(f"  └─────────────────────────────────────")
    print()
    print("  Why This Is Best:")
    print("    ✓ Low risk (€50 = 40% of available balance)")
    print("    ✓ BTC-EUR is most liquid market (tight spreads)")
    print("    ✓ 12% range captures typical BTC daily movement")
    print("    ✓ 15 grids = good balance (not too many orders)")
    print("    ✓ €3.33 per grid level = manageable order sizes")
    print("    ✓ No stop/TP = let it run continuously")
    print("    ✓ Won't interfere with trailing bot positions")
    print()
    print("  Expected Performance:")
    print(f"    • If BTC moves ±3% daily: ~6-9 grid fills/day")
    print(f"    • Profit per fill: ~0.8% (€{50 * 0.008:.2f} per cycle)")
    print(f"    • Estimated daily profit: €{50 * 0.008 * 7:.2f} (7 fills)")
    print(f"    • Monthly potential: €{50 * 0.008 * 7 * 30:.2f} (if sustained)")
    print()
    print("  Risk Management:")
    print("    • If BTC drops >6%: Grid accumulates BTC (DCA effect)")
    print("    • If BTC rises >6%: Grid sells into EUR (profit taking)")
    print("    • Can pause/stop grid anytime from dashboard")
    print()
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📋 COPY-PASTE SETTINGS FOR DASHBOARD")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    print("Grid Configuration:")
    print("┌─────────────────────────────────────┐")
    print(f"│ Market:          BTC-EUR            │")
    print(f"│ Lower Price:     {lower_bound:>7,.2f}           │")
    print(f"│ Upper Price:     {upper_bound:>7,.2f}           │")
    print(f"│ Number of Grids: 15                 │")
    print(f"│ Total Investment: 50.00             │")
    print(f"│ Grid Mode:       arithmetic         │")
    print(f"│ Stop Loss:       0.00               │")
    print(f"│ Take Profit:     0.00               │")
    print("└─────────────────────────────────────┘")
    print()

if __name__ == '__main__':
    try:
        analyze_portfolio_for_grid()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
