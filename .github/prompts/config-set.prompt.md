---
mode: agent
description: Wijzig een config-key in de LOCAL override file (immune voor OneDrive sync).
---

Argument: `KEY=VALUE` of `KEY=VALUE,KEY2=VALUE2`. Vraag user als niet opgegeven.

## ⚠️ Mandatory rules
- Edit ALLEEN `%LOCALAPPDATA%/BotConfig/bot_config_local.json`
- NOOIT `config/bot_config.json` of `config/bot_config_overrides.json` (OneDrive revert die)
- `MAX_OPEN_TRADES` minimum is **3** — weiger lager
- `MIN_SCORE_TO_BUY` blijft **7.0** — vraag expliciete bevestiging als user dat wil verlagen

## Stappen

### 1. Pre-check
- Lees huidige value uit local config
- Check tegen [docs/PORTFOLIO_ROADMAP_V2.md](../../docs/PORTFOLIO_ROADMAP_V2.md) of de wijziging matched de actieve fase
- Bereken budget impact: `(BASE + DCA + DCA×0.9) × MAX_TRADES + GRID_INVESTMENT`
- Verifieer 15% EUR reserve blijft behouden

### 2. Edit local config
```powershell
$path = Join-Path $env:LOCALAPPDATA "BotConfig\bot_config_local.json"
$cfg = Get-Content $path -Raw | ConvertFrom-Json
$cfg.<KEY> = <VALUE>
$cfg | ConvertTo-Json -Depth 10 | Set-Content $path -Encoding UTF8
```

### 3. Verify readback
```powershell
.\.venv\Scripts\python.exe -c "from modules.config import load_config; c = load_config(); print('<KEY> =', c.get('<KEY>'))"
```
Bevestig dat de nieuwe waarde wordt geladen.

### 4. Update roadmap (als config change matched een phase milestone)
Update header, config block, table, checklist, footer in [docs/PORTFOLIO_ROADMAP_V2.md](../../docs/PORTFOLIO_ROADMAP_V2.md).

### 5. Commit + push (alleen als roadmap geüpdatet)
```powershell
git add docs/PORTFOLIO_ROADMAP_V2.md ; git commit -m "config: <KEY>=<VALUE> (<reden>)" ; git push
```

### 6. Hot-reload
De bot leest config elke loop opnieuw — geen restart nodig (tenzij specifieke key).

### 7. Rapporteer
Geef oude → nieuwe waarde, budget impact, en of restart nodig is.
