"""Validate grid budget scaling - test meegroei bij storting."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("GRID BUDGET SCALING VALIDATIE")
print("=" * 60)

# Load config
with open("config/bot_config.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

grid_cfg = cfg.get("GRID_TRADING", {})
budget_cfg = cfg.get("BUDGET_RESERVATION", {})

print("\n--- GRID CONFIG (optimaal) ---")
for k, v in grid_cfg.items():
    print(f"  {k}: {v}")

print("\n--- BUDGET RESERVATION ---")
for k, v in budget_cfg.items():
    print(f"  {k}: {v}")

# Get current balance
total_eur = 374.0
eur_avail = 0.0
HAS_API = False

try:
    from dotenv import load_dotenv
    load_dotenv()
    from python_bitvavo_api.bitvavo import Bitvavo

    bv = Bitvavo({
        "APIKEY": os.getenv("BITVAVO_API_KEY", ""),
        "APISECRET": os.getenv("BITVAVO_API_SECRET", ""),
    })
    bals = bv.balance({})
    total_eur = 0.0
    for b in bals:
        sym = b.get("symbol", "")
        avail = float(b.get("available", 0) or 0)
        inorder = float(b.get("inOrder", 0) or 0)
        if sym == "EUR":
            total_eur += avail + inorder
            eur_avail = avail
        elif avail + inorder > 0:
            try:
                t = bv.tickerPrice({"market": f"{sym}-EUR"})
                price = float(t.get("price", 0) or 0)
                val = (avail + inorder) * price
                if val >= 0.5:
                    total_eur += val
            except Exception:
                pass
    HAS_API = True
    print(f"\n--- HUIDIG SALDO (live) ---")
    print(f"  EUR beschikbaar: {eur_avail:.2f}")
    print(f"  Totaal portfolio: EUR {total_eur:.2f}")
except Exception as e:
    print(f"\n  API niet beschikbaar ({e}), schatting: EUR {total_eur:.2f}")

# Load grid states
grid_invested = 0.0
grid_profit = 0.0
try:
    with open("data/grid_states.json", "r", encoding="utf-8") as f:
        states = json.load(f)
    for market, state in states.items():
        inv = state.get("config", {}).get("total_investment", 0)
        status = state.get("status", "unknown")
        profit = state.get("total_profit", 0)
        fees = state.get("total_fees", 0)
        trades = state.get("total_trades", 0)
        print(f"\n  Grid {market}: EUR {inv:.2f} invested, status={status}, "
              f"profit=EUR {profit:.4f}, fees=EUR {fees:.4f}, trades={trades}")
        if status in ("running", "initialized", "placing_orders"):
            grid_invested += inv
        grid_profit += profit
except Exception:
    pass

# Simulation parameters
max_grids = grid_cfg.get("max_grids", 2)
num_grids = grid_cfg.get("num_grids", 5)
grid_pct = budget_cfg.get("grid_pct", 25) / 100.0
min_reserve = budget_cfg.get("min_reserve_eur", 0)
reinvest = budget_cfg.get("reinvest_grid_profits", True)

print(f"\n{'=' * 60}")
print("BUDGET SCALING SIMULATIE")
print(f"{'=' * 60}")
print(f"\n  Grid pct: {grid_pct*100:.0f}% | Max grids: {max_grids} | Num grids/grid: {num_grids}")
print(f"  Reinvest profits: {reinvest} | Grid profit: EUR {grid_profit:.4f}")
print(f"  Huidig grid invested: EUR {grid_invested:.2f} ({grid_invested/max_grids:.2f}/grid)")

current_per_grid = grid_invested / max(1, max_grids)

scenarios = [
    ("Huidig", 0),
    ("Na +EUR 50 storting", 50),
    ("Na +EUR 100 storting", 100),
    ("Na +EUR 200 storting", 200),
    ("Na +EUR 500 storting", 500),
]

print()
hdr = f"  {'Scenario':<25} {'Totaal':>8} {'Grid25%':>8} {'PerGrid':>8} {'PerLvl':>7} {'ScaleUp':>8} {'Rebalance':>10}"
print(hdr)
print(f"  {'─'*25} {'─'*8} {'─'*8} {'─'*8} {'─'*7} {'─'*8} {'─'*10}")

for label, deposit in scenarios:
    new_total = total_eur + deposit
    grid_budget = max(0, (new_total - min_reserve) * grid_pct)
    effective = grid_budget + (max(0, grid_profit) if reinvest else 0)
    per_grid = effective / max(1, max_grids)
    per_level = per_grid / max(1, num_grids)

    # Scale-up check: requires >25% increase over current investment
    if current_per_grid > 0 and per_grid > current_per_grid * 1.25:
        scale = "JA!"
        rebalance = "Automatisch"
    elif current_per_grid > 0:
        pct = (per_grid / current_per_grid - 1) * 100
        scale = f"Nee ({pct:+.0f}%)"
        rebalance = "—"
    else:
        scale = "Nieuw"
        rebalance = "Auto-create"

    ok = "OK" if per_level >= 5.50 else "TE LAAG"
    print(f"  {label:<25} EUR{new_total:>5.0f} EUR{grid_budget:>5.0f} EUR{per_grid:>5.1f} EUR{per_level:>4.1f}({ok}) {scale:>8} {rebalance:>10}")

# Calculate exact threshold
if current_per_grid > 0:
    threshold_per_grid = current_per_grid * 1.25
    threshold_budget = threshold_per_grid * max_grids
    threshold_total = (threshold_budget / grid_pct) + min_reserve
    deposit_needed = max(0, threshold_total - total_eur)
    print(f"\n  Scale-up threshold: EUR {threshold_per_grid:.2f}/grid")
    print(f"  Totaal nodig: EUR {threshold_total:.0f} (storting EUR {deposit_needed:.0f})")
else:
    print(f"\n  Geen bestaande grids - nieuwe worden auto-created met dynamisch budget")

# What happens after grid restart with optimal config
print(f"\n{'=' * 60}")
print("SCENARIO: Grid herstart met optimale config")
print(f"{'=' * 60}")

new_grid_budget = max(0, (total_eur - min_reserve) * grid_pct)
new_per_grid = (new_grid_budget + max(0, grid_profit)) / max(1, max_grids)
new_per_level = new_per_grid / max(1, num_grids)

print(f"\n  Huidige portfolio: EUR {total_eur:.2f}")
print(f"  Grid budget (25%): EUR {new_grid_budget:.2f}")
print(f"  Per grid: EUR {new_per_grid:.2f}")
print(f"  Per level ({num_grids} levels): EUR {new_per_level:.2f}")
print(f"  Min order OK: {'JA' if new_per_level >= 5.50 else 'NEE - te weinig budget!'}")

# After 100 deposit
dep = 100
after_total = total_eur + dep
after_budget = max(0, (after_total - min_reserve) * grid_pct)
after_per_grid = (after_budget + max(0, grid_profit)) / max(1, max_grids)
after_per_level = after_per_grid / max(1, num_grids)

print(f"\n  Na EUR {dep} storting:")
print(f"  Totaal: EUR {after_total:.2f}")
print(f"  Grid budget: EUR {after_budget:.2f}")
print(f"  Per grid: EUR {after_per_grid:.2f}")
print(f"  Per level: EUR {after_per_level:.2f}")

# Check if scale-up would trigger
if new_per_grid > 0:
    growth = (after_per_grid / new_per_grid - 1) * 100
    triggers = after_per_grid > new_per_grid * 1.25
    print(f"  Groei: +{growth:.0f}%")
    print(f"  Auto scale-up: {'JA - grid wordt automatisch herbalanceerd!' if triggers else 'NEE - nog onder 25% drempel'}")
    if not triggers:
        needed = new_per_grid * 1.25
        needed_total = (needed * max_grids / grid_pct) + min_reserve
        needed_deposit = max(0, needed_total - total_eur)
        print(f"  Storting nodig voor auto scale-up: EUR {needed_deposit:.0f}")

print(f"\n{'=' * 60}")
print("CONCLUSIE")
print(f"{'=' * 60}")
print(f"""
  Config wijzigingen (backtest-optimaal):
  - num_grids: 10 -> 5 (minder grids = grotere winst per cycle)
  - stop_loss_pct: 0.08 -> 0.12 (8% te tight voor BTC/ETH)
  - take_profit_pct: 0.15 -> 0.50 (laat grid doordraaien)
  - enabled: true
  
  Budget meegroei (25% dynamisch):
  - Grid bot berekent budget automatisch als % van totaal saldo
  - Bij >{'>'}25% groei per grid: automatische rebalance
  - Bij nieuwe grids: altijd dynamisch budget
  
  Bestaande grids (EUR {grid_invested:.0f} invested):
  - Draaien door met huidige levels tot rebalance/stop
  - Nieuwe cycle orders krijgen optimale 5-grid spacing
  - Bij herstart: auto-create met nieuw budget
""")
