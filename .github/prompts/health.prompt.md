---
mode: agent
description: Run de bot health check + geef een korte samenvatting (Nederlands).
---

Voer uit: `python scripts/helpers/ai_health_check.py`

Lees daarna de output en geef een **korte Nederlandse samenvatting** in dit formaat:

- ✅/⚠️/❌ Config (3-layer merge, MAX_OPEN_TRADES, MIN_SCORE_TO_BUY, DCA settings)
- ✅/⚠️/❌ Open trades (aantal, totaal invested, P&L)
- ✅/⚠️/❌ Performance (laatste 24h, win-rate)
- ✅/⚠️/❌ Budget (15% EUR reserve, beschikbare ruimte voor nieuwe trades)
- ✅/⚠️/❌ Processen (trailing_bot.py PIDs, dashboard, ai_supervisor)
- ✅/⚠️/❌ Errors (laatste 50 regels in logs/bot_log.txt)
- ✅/⚠️/❌ Roadmap-alignment

Eindig met **één concrete actie** als er iets ⚠️ of ❌ is, anders "Alles in orde."
