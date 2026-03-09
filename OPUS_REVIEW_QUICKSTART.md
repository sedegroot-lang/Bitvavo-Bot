# 🚀 OPUS REVIEW - QUICK START

## Je hebt nu:

### 📄 [OPUS_REVIEW_PLAN.md](OPUS_REVIEW_PLAN.md)
**Volledige guide** met 8 sessies, prompts, en strategie

### 📊 [reviews/REVIEW_PROGRESS.md](reviews/REVIEW_PROGRESS.md)
**Track je voortgang** per sessie

### ⚙️ [reviews/prepare_session.ps1](reviews/prepare_session.ps1)
**Helper script** om files te bundelen voor copy-paste naar Opus

---

## Start Nu (5 minuten):

### 1️⃣ Backup maken
```powershell
$t = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item config\bot_config.json backups\bot_config_pre_opus_$t.json
Copy-Item trailing_bot.py backups\trailing_bot_pre_opus_$t.py
```

### 2️⃣ Eerste sessie voorbereiden
```powershell
.\reviews\prepare_session.ps1 -Session 1
```
Dit opent notepad met alle files voor Sessie 1

### 3️⃣ Open Opus 4.6
- Ga naar Copilot
- Selecteer **Claude Opus 4.6** (3x) model
- Start **NIEUWE chat**

### 4️⃣ Copy-paste
1. Open `OPUS_REVIEW_PLAN.md` → Scroll naar "🎯 Sessie 1"
2. Copy de hele prompt (inclusief BESTANDEN: sectie)
3. Paste in Opus chat
4. Copy volledige inhoud van `reviews/session1_files.txt`
5. Paste onder de prompt
6. Send!

### 5️⃣ Save output
- Wacht tot Opus klaar is (~5-10 min)
- Copy hele output
- Save als `reviews/session1_execution_logic.md`

### 6️⃣ Review en implement
- Lees de findings
- Prioriteer top 3
- Implement fixes één voor één
- Test na elke fix
- Update `reviews/REVIEW_PROGRESS.md`

---

## Verwachte Timeline

| Sessie | Focus | Tijd | Wanneer |
|--------|-------|------|---------|
| 1 | Trade Execution | 90 min | Dag 1 |
| 2 | Risk Management | 90 min | Dag 1-2 |
| 3 | Signals | 60 min | Dag 2 |
| 4 | AI Supervisor | 90 min | Dag 3 |
| 5 | Error Handling | 60 min | Dag 3-4 |
| 6 | Data State | 60 min | Dag 4 |
| 7 | ML Pipeline | 45 min | Dag 5 |
| 8 | Performance | 45 min | Dag 5 |

**Totaal**: ~9 uur verspreid over 5 dagen

---

## Wat je gaat vinden:

Verwacht in Sessie 1-2 (critical):
- ✅ 5-10 echte bugs
- ✅ 3-5 race conditions
- ✅ 10+ edge cases niet afgehandeld
- ✅ 2-3 critical risk issues

Dit zijn **geen theoretische issues** - dit zijn dingen die nu in je bot zitten en tot losses kunnen leiden.

---

## Pro Tip

**Start met Sessie 1 & 2 vandaag.**  
Dit zijn de critical paths waar geld verloren gaat.  
De rest kan wachten tot volgende week.

Focus = bugs die je VANDAAG geld kunnen kosten.

---

## Hulp nodig?

- ❓ Script werkt niet? → Test met `.venv\Scripts\python.exe --version`
- ❓ Opus geeft geen bruikbare output? → Zie "Warning Signs" in OPUS_REVIEW_PLAN.md
- ❓ Fix implementeren? → Kom terug naar mij (Sonnet 4.5)

---

**Je doet dit goed. Start nu! 🚀**

**Next**: `.\reviews\prepare_session.ps1 -Session 1`
