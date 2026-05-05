---
mode: agent
description: Stuur een bericht naar de configured Telegram chat van de bot.
---

Argument: het bericht (vrije tekst, mag emojis bevatten). Vraag user als niet opgegeven.

## Uitvoeren

```powershell
.\.venv\Scripts\python.exe -c "
import os, requests
from modules.config import load_config
cfg = load_config()
tok = os.environ.get('TELEGRAM_BOT_TOKEN') or cfg.get('TELEGRAM_BOT_TOKEN','')
chat = os.environ.get('TELEGRAM_CHAT_ID') or cfg.get('TELEGRAM_CHAT_ID','')
msg = '''<HET BERICHT HIER>'''
r = requests.post(f'https://api.telegram.org/bot{tok}/sendMessage', data={'chat_id': chat, 'text': msg})
print(r.status_code, r.text[:200])
"
```

## Tips
- Gebruik triple-quoted strings voor multi-line berichten met newlines
- Vermijd `\n` escapes — die werken niet in PowerShell `-c "..."` blokken
- Als emoji's mojibake worden, sla het bericht op in `tmp/_msg.txt` (UTF-8) en lees met `open('tmp/_msg.txt', encoding='utf-8').read()`
- Verifieer response: `r.status_code == 200` en `"ok":true` in JSON
