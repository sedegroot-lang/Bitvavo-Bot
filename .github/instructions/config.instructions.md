---
applyTo: "config/**/*.json"
description: "Config files — DO NOT EDIT for settings changes"
---

# Config files — read-only for settings

## ⚠️ NEVER edit these files for settings changes
Files under `config/` (`bot_config.json`, `bot_config_overrides.json`) are synced via OneDrive and **regularly reverted**.

## Where settings changes go
**ALL config value changes** must go to:
```
%LOCALAPPDATA%\BotConfig\bot_config_local.json
```
This file is OUTSIDE OneDrive, loads LAST in the 3-layer merge, and wins over everything.

## When editing here is OK
- Adding a NEW config key with its safe default (so it propagates as a baseline).
- Schema changes in `config/bot_config_schema.py` (different file, conceptually).
- Adding documentation comments via the schema.

## Reference paths
- Read local override path from code: `modules.config.LOCAL_OVERRIDE_PATH`.
- PowerShell quick edit:
  ```powershell
  notepad (Join-Path $env:LOCALAPPDATA "BotConfig\bot_config_local.json")
  ```

## Hard floors (enforced)
- `MAX_OPEN_TRADES >= 3`
- `MIN_SCORE_TO_BUY = 7.0` (locked)
- 15% EUR reserve must be maintained: `(BASE + DCA + DCA*0.9) * MAX_TRADES + GRID_INVESTMENT <= 85% of total budget`
