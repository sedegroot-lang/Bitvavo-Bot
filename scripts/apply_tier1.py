"""Apply Tier 1 portfolio settings."""
import json
import shutil
import datetime

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# Backup
shutil.copy2("config/bot_config.json", f"backups/bot_config_pre_tier1_{ts}.json")
print(f"Backup: backups/bot_config_pre_tier1_{ts}.json")

# Load
cfg = json.load(open("config/bot_config.json"))

# Apply Tier 1 settings
cfg["BASE_AMOUNT_EUR"] = 25.0
cfg["MAX_OPEN_TRADES"] = 5
cfg["GRID_TRADING"]["enabled"] = False

# Save
with open("config/bot_config.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print("bot_config.json updated")

# Sync overrides
ovr = json.load(open("config/bot_config_overrides.json"))
changed = False
for k in ["BASE_AMOUNT_EUR", "MAX_OPEN_TRADES", "GRID_TRADING"]:
    if k not in ovr or ovr[k] != cfg[k]:
        ovr[k] = cfg[k]
        changed = True
if changed:
    with open("config/bot_config_overrides.json", "w", encoding="utf-8") as f:
        json.dump(ovr, f, indent=2, ensure_ascii=False)
    print("overrides synced")

# Verify
cfg2 = json.load(open("config/bot_config.json"))
base = cfg2["BASE_AMOUNT_EUR"]
trades = cfg2["MAX_OPEN_TRADES"]
dca = cfg2["DCA_AMOUNT_EUR"]
dca_max = cfg2["DCA_MAX_BUYS"]
max_exp = trades * (base + dca_max * dca)
print(f"\n=== Tier 1 Applied ===")
print(f"BASE_AMOUNT_EUR: {base}")
print(f"MAX_OPEN_TRADES: {trades}")
print(f"GRID_TRADING.enabled: {cfg2['GRID_TRADING']['enabled']}")
print(f"Max exposure: {trades} x (EUR{base} + {dca_max}xEUR{dca}) = EUR{max_exp}")
print(f"RSI_DCA_THRESHOLD: {cfg2['RSI_DCA_THRESHOLD']}")
print(f"DCA_MAX_BUYS: {cfg2['DCA_MAX_BUYS']}")
print(f"DCA_HYBRID: {cfg2['DCA_HYBRID']}")
