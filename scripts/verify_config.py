import json
cfg = json.load(open('config/bot_config.json'))

sl = cfg['HARD_SL_ALT_PCT']
sl_btc = cfg['HARD_SL_BTCETH_PCT']
dca = cfg['DCA_DROP_PCT']
mx = cfg['DCA_MAX_BUYS']
buf = cfg.get('DCA_SL_BUFFER_PCT', 0.015)
tp = cfg['TAKE_PROFIT_TARGETS']
act = cfg['TRAILING_ACTIVATION_PCT']
tr = cfg['DEFAULT_TRAILING']
ms = dca * mx + buf
weighted_tp = tp[0] * 0.25 + tp[1] * 0.30 + tp[2] * 0.35
rr = weighted_tp / sl

print("=== CONFIG MATH ===")
print(f"SL ALT={sl:.1%}  SL BTC={sl_btc:.1%}")
print(f"DCA: {mx}x adds at -{dca:.1%} (step_mult={cfg['DCA_STEP_MULTIPLIER']})")
print(f"min_safe_sl={ms:.1%}  SL>=min_safe: ALT={sl>=ms} BTC={sl_btc>=ms}")
print(f"Trail: activation={act:.1%} distance={tr:.1%} min_exit=+{act-tr:.1%}")
print(f"TP: L1=+{tp[0]:.0%}  L2=+{tp[1]:.0%}  L3=+{tp[2]:.0%}")
print(f"Weighted avg TP = {weighted_tp:.1%}  R:R = {rr:.2f}")
print(f"Circuit breaker: win_rate>{cfg['CIRCUIT_BREAKER_MIN_WIN_RATE']:.0%}")
print(f"Exposure cap: {cfg['MAX_TOTAL_EXPOSURE_EUR']} EUR")
print(f"Balance floor: {cfg['MIN_BALANCE_EUR']} EUR")
print(f"Pyramid: {cfg['DCA_PYRAMID_UP']}")
print(f"Reinvest: {cfg['REINVEST_ENABLED']}")
print(f"Budget: grid={cfg['BUDGET_RESERVATION']['grid_pct']}% trail={cfg['BUDGET_RESERVATION']['trailing_pct']}% reserve={cfg['BUDGET_RESERVATION']['reserve_pct']}%")
print()

checks = {
    "SL ALT >= min_safe": sl >= ms,
    "SL BTC >= min_safe": sl_btc >= ms,
    "Activation < trail_dist (lets trades run)": act < tr,
    "L3 TP reachable (> SL)": tp[2] > sl,
    "R:R > 1.0": rr > 1.0,
    "Circuit breaker ON": cfg['CIRCUIT_BREAKER_MIN_WIN_RATE'] > 0,
    "Exposure capped": cfg['MAX_TOTAL_EXPOSURE_EUR'] < 9999,
    "Balance floor > 0": cfg['MIN_BALANCE_EUR'] > 0,
}
print("=== CHECKS ===")
for name, ok in checks.items():
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
print(f"\nAll pass: {all(checks.values())}")
