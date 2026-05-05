---
mode: agent
description: Volledige bug-fix workflow — FIX_LOG check, fix, test, commit, push, telegram.
---

Volg STRIKT deze volgorde voor elke bugfix. Sla geen stap over.

## 1. Read FIX_LOG (mandatory)
Lees [docs/FIX_LOG.md](../../docs/FIX_LOG.md) en check of dit issue eerder is opgelost. Zo ja: pas de bestaande fix aan in plaats van duplicaat.

## 2. Repo memory
Lees relevante files in `/memories/repo/` (zoals `cost_basis_rules.md`, `lessons_learned.md`) als de bug raakvlak heeft met cost basis, sync, DCA, of trailing.

## 3. Diagnose
- Lees de relevante module(s) volledig (geen kleine reads).
- Identificeer root cause met bewijs uit logs/code (niet gokken).
- Schrijf 1-2 zinnen root-cause uitleg in chat.

## 4. Fix
- Edit alleen wat strikt nodig is. Geen "improvements" eromheen.
- Geen docstrings/comments toevoegen aan code die je niet wijzigt.
- Behoud bestaande style (Dutch log messages oké).

## 5. Tests
- Schrijf een **regression test** die zonder de fix faalt en met de fix slaagt.
- Run: `.\.venv\Scripts\python.exe -m pytest tests/<relevant_file> -v`
- Zorg dat alle tests passen.

## 6. FIX_LOG entry
Voeg een nieuwe entry toe BOVEN de meest recente in [docs/FIX_LOG.md](../../docs/FIX_LOG.md) met dit template:
```markdown
## #NNN — <korte titel> (YYYY-MM-DD)

### Symptom
<wat zag de user / wat ging fout>

### Root cause
<exacte regel/functie + uitleg>

### Fix
<wat je veranderd hebt + code snippet>

### Tests
<welke tests + waar>

### Lesson
<1 zin om te onthouden>
```

## 7. Commit + push
```powershell
git add <files> ; git commit -m "fix(#NNN): <korte titel>" ; git push
```

## 8. Telegram notify
```python
.\.venv\Scripts\python.exe -c "
import os, requests
from modules.config import load_config
cfg = load_config()
tok = cfg.get('TELEGRAM_BOT_TOKEN','')
chat = cfg.get('TELEGRAM_CHAT_ID','')
msg = '🛠 FIX #NNN deployed (commit <hash>)\n\n<korte uitleg + verificatie>'
requests.post(f'https://api.telegram.org/bot{tok}/sendMessage', data={'chat_id': chat, 'text': msg})
"
```

## 9. Restart bot (als runtime fix)
Stop de oude PIDs en start opnieuw via `start_automated.bat` of direct `trailing_bot.py`. Verifieer met `Get-CimInstance Win32_Process` dat hij draait.

## 10. Eindrapport
Geef in chat: fix-nummer, commit hash, tests passed (X/X), wat is herhersteld.
