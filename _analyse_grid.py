import json, time

with open('data/grid_states.json') as f:
    g = json.load(f)

now = time.time()

for market, state in g.items():
    cfg = state['config']
    last_check = state.get('last_order_check', 0)
    age_h = (now - last_check) / 3600

    placed  = [l for l in state['levels'] if l['status'] == 'placed']
    filled  = [l for l in state['levels'] if l['status'] == 'filled']
    error   = [l for l in state['levels'] if l['status'] == 'cancelled']

    spacing = (cfg['upper_price'] - cfg['lower_price']) / cfg['num_grids']
    mid = (cfg['upper_price'] + cfg['lower_price']) / 2
    spacing_pct = spacing / mid * 100

    p = state['current_price']
    in_range = cfg['lower_price'] <= p <= cfg['upper_price']
    dist_lower = (p - cfg['lower_price']) / cfg['lower_price'] * 100
    dist_upper = (cfg['upper_price'] - p) / cfg['upper_price'] * 100
    fee_pct = 0.0015  # maker fee per kant
    min_spacing_pct = fee_pct * 2 * 100  # minimaal 0.30%

    print("=" * 50)
    print(f"MARKT:           {market}")
    print(f"Status:          {state['status']}")
    print(f"Huidige prijs:   {p}")
    print(f"Grid range:      {cfg['lower_price']:.0f} - {cfg['upper_price']:.0f}")
    print(f"Num grids:       {cfg['num_grids']}")
    print(f"Grid spacing:    {spacing:.0f} EUR ({spacing_pct:.1f}%) [min: {min_spacing_pct:.2f}%]")
    print(f"Winst (netto):   EUR {state['total_profit'] - state['total_fees']:.4f}")
    print(f"Trades:          {state['total_trades']}")
    print(f"Laatste check:   {age_h:.1f}u geleden")
    print(f"Placed orders:   {len(placed)}")
    print(f"Filled levels:   {len(filled)} (onverwerkt!)")
    print(f"Fout-levels:     {len(error)}")
    for l in error:
        print(f"  level {l['level_id']} ({l['side']} {l['price']}): {l['error_msg']}")
    print(f"Prijs in range:  {in_range}")
    print(f"Afstand bodem:   +{dist_lower:.1f}%")
    print(f"Afstand top:     -{dist_upper:.1f}%")

    # Diagnose
    print("\nDIAGNOSE:")
    if cfg['num_grids'] < 8:
        print(f"  [PROBLEEM] Slechts {cfg['num_grids']} grids — te weinig. Minimaal 8-10 aanbevolen.")
    if spacing_pct > 3.0:
        print(f"  [PROBLEEM] Spacing {spacing_pct:.1f}% te groot. Prijs moet ver bewegen voor een fill.")
    if len(error) > 0:
        print(f"  [PROBLEEM] {len(error)} cancelled level(s) — orders worden niet geplaatst.")
    if len(filled) > 0:
        print(f"  [WAARSCHUWING] {len(filled)} filled levels nog in state — kunnen congestion veroorzaken.")
    not_filled_placed = [l for l in placed if l['side'] == 'buy']
    if not_filled_placed:
        prices = [l['price'] for l in not_filled_placed]
        gap = p - max(prices)
        pct = gap / max(prices) * 100
        print(f"  [INFO] Dichtstbijzijnde buy: {max(prices):.2f} (prijs {gap:.2f} EUR / {pct:.1f}% hoger)")
        if pct > 2:
            print(f"  [STAGNATIE] Prijs staat {pct:.1f}% boven alle koop-orders. Geen fills totdat ETH daalt.")
    print()
