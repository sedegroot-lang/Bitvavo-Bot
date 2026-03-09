"""Calculate tier data for roadmap."""
import json

cfg = json.load(open("config/bot_config.json"))
base = cfg["BASE_AMOUNT_EUR"]
max_t = cfg["MAX_OPEN_TRADES"]
dca_amt = cfg["DCA_AMOUNT_EUR"]
dca_max = cfg["DCA_MAX_BUYS"]
grid_inv = cfg["GRID_TRADING"]["investment_per_grid"]
grid_max = cfg["GRID_TRADING"]["max_grids"]
grid_total = grid_inv * grid_max
budget = cfg["BUDGET_RESERVATION"]
grid_pct = budget["grid_pct"]
trail_pct = budget["trailing_pct"]

print(f"Current: BASE={base}, MAX_TRADES={max_t}, DCA={dca_amt}x{dca_max}")
print(f"Grid: {grid_max} grids x EUR{grid_inv} = EUR{grid_total}")
print(f"Budget split: grid={grid_pct}%, trailing={trail_pct}%, reserve=0%")
print()

for bal in [400, 500, 600, 700, 800, 1000]:
    grid_eur = bal * grid_pct / 100
    trail_eur = bal * trail_pct / 100
    # How many trades fit if all go full DCA
    full_cost = base + dca_max * dca_amt  # 40 + 30 = 70
    safe_trades = int(trail_eur / full_cost)
    base_only_trades = int(trail_eur / base)
    actual_exposure = max_t * full_cost
    fits = "OK" if actual_exposure <= trail_eur else f"OVER ({actual_exposure:.0f}>{trail_eur:.0f})"
    print(f"EUR{bal}: grid_budget={grid_eur:.0f}, trail_budget={trail_eur:.0f}, "
          f"safe_max_trades={safe_trades}, base_only_max={base_only_trades}, "
          f"current({max_t}x{full_cost:.0f}={actual_exposure:.0f})={fits}")
