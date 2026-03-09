"""Revert Tier 1 changes."""
import json, glob, shutil

files = sorted(glob.glob("backups/bot_config_pre_tier1_*.json"))
src = files[-1]
shutil.copy2(src, "config/bot_config.json")
print(f"Reverted from {src}")

cfg = json.load(open("config/bot_config.json"))
print(f"BASE={cfg['BASE_AMOUNT_EUR']}, MAX_TRADES={cfg['MAX_OPEN_TRADES']}, GRID={cfg['GRID_TRADING']['enabled']}")
