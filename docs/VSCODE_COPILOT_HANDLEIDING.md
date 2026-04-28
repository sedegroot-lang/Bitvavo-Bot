# VS Code + GitHub Copilot — Handleiding voor nieuwe bijdrager

## Wat je nodig hebt

| Tool | Download |
|---|---|
| **VS Code** | https://code.visualstudio.com |
| **GitHub Copilot extensie** | Ingebouwd in VS Code via Marketplace |
| **GitHub account** | https://github.com — gratis account voldoende |

---

## Stap 1 — Installeer VS Code

1. Ga naar https://code.visualstudio.com en download de installer voor Windows.
2. Voer de installer uit. Vink aan: **"Open with Code"** (rechtermuisknop in Explorer).
3. Start VS Code.

---

## Stap 2 — Installeer GitHub Copilot

1. Klik op het **Extensions**-icoon in de linker zijbalk (vierkantjes-icoon) of druk `Ctrl+Shift+X`.
2. Zoek naar **"GitHub Copilot"**.
3. Klik **Install** op de extensie van GitHub.
4. VS Code vraagt je aan te melden bij GitHub → klik **Sign in to GitHub** en doorloop de browser-stap.
5. Controleer of je een **Copilot-abonnement** hebt (gratis proefperiode beschikbaar op github.com/features/copilot).

---

## Stap 3 — Open de bot-map

**Optie A — via Explorer:**
1. Navigeer in Windows Explorer naar de map van de bot (bijv. `C:\Users\...\Bitvavo Bot`).
2. Klik met rechtermuisknop op de map → **"Open with Code"**.

**Optie B — via VS Code zelf:**
1. Klik in VS Code op **File → Open Folder…** (`Ctrl+K Ctrl+O`).
2. Navigeer naar de bot-map en klik **Select Folder**.

Je ziet nu alle bestanden in de **Explorer**-zijbalk aan de linkerkant.

---

## Stap 4 — Open de Copilot Chat

Druk `Ctrl+Shift+I` of klik op het **chat-icoon** (praatwolkje) in de linker zijbalk.

Er verschijnt een chatvenster rechts of onderaan. Hier typ je wat je wilt.

---

## Stap 5 — Gebruik Copilot om de bot te bewerken

### Vraag stellen over een bestand
1. Open een bestand (bijv. `trailing_bot.py`) via de Explorer.
2. Selecteer een stuk code dat je wilt begrijpen.
3. Druk `Ctrl+Shift+I` en typ: *"Wat doet dit stuk code?"*

### Laten wijzigen door Copilot (Agent mode)
1. Klik in het chatvenster op het dropdown-menu naast de "Send"-knop.
2. Kies **"Agent"** (of zorg dat **"Agent"** geselecteerd is bovenin de chat).
3. Stel je vraag in normaal Nederlands, bijv.:
   - *"Voeg logging toe aan de trailing stop functie"*
   - *"Fix de bug waarbij invested_eur verkeerd wordt berekend"*
   - *"Leg uit hoe de DCA-logica werkt"*

Copilot leest de relevante bestanden zelf en stelt wijzigingen voor. Je kan de wijziging **accepteren** (✓) of **weigeren** (✗).

### Goedkeuringsmodus kiezen (Default / Bypass / Autopilot)

Naast de chatinvoer staat een kleine dropdown met drie opties:

| Modus | Wat het doet | Wanneer gebruiken |
|---|---|---|
| **Default Approvals** | Vraagt toestemming voor "gevaarlijke" acties (bestanden schrijven, terminal-commando's) | Aanbevolen voor beginners |
| **Bypass Approvals** | Voert alle acties direct uit zonder te vragen | Als je snel wil werken en de taak goed begrijpt |
| **Autopilot (Preview)** | Keurt alles automatisch goed én blijft zelfstandig doorwerken tot de taak klaar is | Voor complexe meerdersstapstaken, bijv. "bouw een nieuwe feature" |

**Autopilot** is de krachtigste modus: Copilot zoekt bestanden op, maakt wijzigingen, voert tests uit en lost problemen op — zonder dat jij bij elke stap op "OK" hoeft te klikken. Handig voor grotere opdrachten zoals:
- *"Refactor de trailing stop logica naar een aparte class"*
- *"Schrijf tests voor alle functies in bot/signals.py"*

> ⚠️ **Let op met Autopilot op een live bot**: Autopilot kan ook bestanden overschrijven of scripts uitvoeren. Zorg dat de bot gestopt is voor je grote wijzigingen maakt (`Stop-Process` of sluit het bot-venster). Controleer altijd de wijzigingen achteraf via `git diff` voor je pushed.

### Belangrijke bestanden om te kennen

| Bestand | Wat het doet |
|---|---|
| `trailing_bot.py` | Hoofd-bot (~4300 regels), main loop |
| `bot/trailing.py` | Trailing stop logica |
| `bot/signals.py` | Koopsignalen |
| `modules/config.py` | Configuratie laden |
| `config/bot_config.json` | Standaard config (niet bewerken) |
| `docs/FIX_LOG.md` | Log van alle bugfixes — **altijd eerst lezen voor een fix** |

---

## Stap 6 — Wijzigingen opslaan en pushen

> ⚠️ Sla wijzigingen **altijd op** voor je de bot herstart (`Ctrl+S`).

1. Open de **Source Control**-zijbalk (`Ctrl+Shift+G`).
2. Je ziet gewijzigde bestanden onder "Changes".
3. Voer een korte beschrijving in (bijv. `fix: trailing stop werkt nu correct`).
4. Klik **Commit** → **Sync Changes** (= push naar GitHub).

---

## Tips

- Typ in Copilot Chat altijd **welk bestand** het gaat als je een specifieke vraag hebt: *"In bot/trailing.py, waarom..."*
- Voor grote wijzigingen: vraag eerst *"Analyseer dit bestand en geef een samenvatting"* voor je iets verandert.
- De bot-instructies voor Copilot staan in `.github/copilot-instructions.md` — Copilot leest dat automatisch.
- Twijfel je of iets veilig is? Vraag Copilot: *"Is deze wijziging veilig voor een live trading bot?"*

---

## Veelgestelde vragen

**Q: Copilot begrijpt de context niet.**  
A: Zorg dat de hele bot-map open is als workspace (stap 3), niet alleen een los bestand.

**Q: Ik zie geen "Agent" optie.**  
A: Update de Copilot extensie: `Ctrl+Shift+X` → zoek GitHub Copilot → Update.

**Q: Welke Python versie gebruiken?**  
A: Python 3.13. Installeer via https://python.org. De virtual environment staat in `.venv\`.
