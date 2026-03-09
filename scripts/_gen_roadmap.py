"""Generate portfolio roadmap data for €400-€5000 in €100 steps."""
import json, math

# Current config as baseline
GRID_PCT = 25
TRAIL_PCT = 75
MAX_GRIDS = 2

def calc_tier(balance):
    grid_budget = balance * GRID_PCT / 100
    trail_budget = balance * TRAIL_PCT / 100
    inv_per_grid = round(grid_budget / MAX_GRIDS)
    
    # Scaling logic based on portfolio size
    if balance <= 500:
        base = 25
        dca_amt = 10
        dca_max = 3
        max_trades = max(3, int(trail_budget / (base + dca_max * dca_amt) * 0.90))
        max_trades = min(max_trades, 5)
        reinvest = False
        num_grids = 5
    elif balance <= 700:
        base = 30
        dca_amt = 10
        dca_max = 3
        max_trades = max(4, int(trail_budget / (base + dca_max * dca_amt) * 0.90))
        max_trades = min(max_trades, 7)
        reinvest = False
        num_grids = 5
    elif balance <= 1000:
        base = 40
        dca_amt = 12
        dca_max = 3
        max_trades = max(5, int(trail_budget / (base + dca_max * dca_amt) * 0.90))
        max_trades = min(max_trades, 8)
        reinvest = balance >= 800
        num_grids = 6
    elif balance <= 1500:
        base = 50
        dca_amt = 15
        dca_max = 3
        max_trades = max(6, int(trail_budget / (base + dca_max * dca_amt) * 0.90))
        max_trades = min(max_trades, 10)
        reinvest = True
        num_grids = 7
    elif balance <= 2000:
        base = 60
        dca_amt = 18
        dca_max = 3
        max_trades = max(7, int(trail_budget / (base + dca_max * dca_amt) * 0.88))
        max_trades = min(max_trades, 12)
        reinvest = True
        num_grids = 8
    elif balance <= 3000:
        base = 75
        dca_amt = 20
        dca_max = 4
        max_trades = max(8, int(trail_budget / (base + dca_max * dca_amt) * 0.88))
        max_trades = min(max_trades, 14)
        reinvest = True
        num_grids = 8
    elif balance <= 4000:
        base = 90
        dca_amt = 25
        dca_max = 4
        max_trades = max(9, int(trail_budget / (base + dca_max * dca_amt) * 0.88))
        max_trades = min(max_trades, 15)
        reinvest = True
        num_grids = 10
    else:
        base = 100
        dca_amt = 30
        dca_max = 4
        max_trades = max(10, int(trail_budget / (base + dca_max * dca_amt) * 0.88))
        max_trades = min(max_trades, 16)
        reinvest = True
        num_grids = 10
    
    full_cost = base + dca_max * dca_amt
    max_exposure = max_trades * full_cost
    utilization = max_exposure / trail_budget * 100
    grid_total = inv_per_grid * MAX_GRIDS
    
    return {
        "balance": balance,
        "grid_budget": grid_budget,
        "trail_budget": trail_budget,
        "inv_per_grid": inv_per_grid,
        "grid_total": grid_total,
        "num_grids": num_grids,
        "base": base,
        "max_trades": max_trades,
        "dca_amt": dca_amt,
        "dca_max": dca_max,
        "full_cost": full_cost,
        "max_exposure": max_exposure,
        "utilization": utilization,
        "reinvest": reinvest,
        "fits": max_exposure <= trail_budget,
    }

# Generate all tiers
tiers = []
for bal in range(400, 5100, 100):
    t = calc_tier(bal)
    tiers.append(t)

# Print table
print("| Portfolio | BASE | MAX_TRADES | DCA | DCA_MAX | Grid/grid | Grids | Max Exposure | Trail Budget | Util% | Reinvest | Fit |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for t in tiers:
    fit = "✓" if t["fits"] else "✗ OVER"
    ri = "Ja" if t["reinvest"] else "Nee"
    print(f"| €{t['balance']:,} | €{t['base']} | {t['max_trades']} | €{t['dca_amt']} | {t['dca_max']}x | €{t['inv_per_grid']} | {t['num_grids']} | €{t['max_exposure']:,} | €{t['trail_budget']:,.0f} | {t['utilization']:.0f}% | {ri} | {fit} |")
