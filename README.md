# Bitvavo Trading Bot

Gratis geautomatiseerde crypto trading bot voor Bitvavo — DCA, trailing stop, grid trading en AI-gestuurde entry signals.

---

## 🏦 Stap 1 — Bitvavo account aanmaken

> ### 👉 [Registreer GRATIS via onze link](https://bitvavo.com/invite?a=B8942E4528)
> **https://bitvavo.com/invite?a=B8942E4528**
>
> - ✅ 100% gratis registratie
> - ✅ **#1 crypto exchange van Nederland**
> - ✅ Laagste kosten: **0,00% – 0,25%** per trade
> - ✅ Gereguleerd en veilig (DNB-vergunning)
> - ✅ Vereist voor gebruik van deze bot
>
> **Al een account?** Ga direct naar stap 2.

---

## 💿 Stap 2 — Python installeren

De bot heeft Python nodig. Dit is eenmalig.

1. Ga naar [python.org/downloads](https://www.python.org/downloads/)
2. Download de nieuwste versie (3.11 of hoger)
3. Start de installer
4. ⚠️ **Belangrijk:** vink **"Add Python to PATH"** aan onderaan het eerste scherm — zonder dit werkt de bot niet!
5. Klik "Install Now"

---

## 📥 Stap 3 — Bot downloaden

👉 **[Download de nieuwste versie (ZIP)](https://github.com/sedegroot-lang/Bitvavo-Bot/archive/refs/heads/main.zip)**

1. Klik op de link hierboven
2. Pak het ZIP-bestand uit naar een map naar keuze (bijv. `C:\BitvavoBot\`)

---

## ⚙️ Stap 4 — Installeren via setup wizard

Dubbelklik **`setup.bat`** in de uitgepakte map.

De wizard doet automatisch:
- ✅ Vraagt of je een Bitvavo account hebt
- ✅ Begeleidt je bij het aanmaken van API sleutels
- ✅ Slaat je sleutels veilig op (alleen op jouw PC, nooit online)
- ✅ Installeert alle benodigde onderdelen
- ✅ Start de bot direct als je wil

### API sleutels aanmaken

De wizard vraagt je om Bitvavo API sleutels. Zo maak je ze aan:

1. Log in op [bitvavo.com](https://bitvavo.com)
2. Ga naar **Account → Instellingen → API sleutels**
3. Klik **"Nieuwe API sleutel aanmaken"**
4. Vink aan: **Lezen** ✅ en **Handelen** ✅ — **Opnemen** ❌ (NIET aanvinken)
5. Kopieer de **Key** en **Secret** — de Secret zie je maar één keer!
6. Plak ze in de wizard

---

## 🚀 Stap 5 — Bot starten

Na de wizard dubbelklik je voortaan op **`start_automated.bat`** om de bot te starten.

Het dashboard opent automatisch op: **http://localhost:5001**

---

## ⚙️ Parameters instellen

Alle instellingen wijzig je via het **dashboard in je browser** op `http://localhost:5001`.

Ga naar het tabblad **⚙️ Settings**. Daar stel je in:

| Instelling | Wat het doet | Standaard |
|---|---|---|
| **Budget per trade** | Hoeveel euro per aankoop | €12 |
| **Max open trades** | Hoeveel munten tegelijk | 5 |
| **Trailing stop %** | Wanneer winst vastzetten | 4% |
| **DCA levels** | Hoeveel keer bijkopen bij daling | 9x |
| **Min AI score** | Hoe zeker de AI moet zijn voor een koop | 5 |
| **Budget verdeling** | % voor Trailing Bot vs Grid Bot | 75% / 25% |

Wijzigingen worden direct opgeslagen in `config/bot_config.json`. Je hoeft de bot niet te herstarten.

> **Tip voor beginners:** begin met de standaardinstellingen. Pas alleen **Budget per trade** aan op basis van hoeveel geld je beschikbaar hebt.

---

## 🔄 Updates

De bot updatet **niet automatisch**. Als er een nieuwe versie uitkomt:

1. Ga naar 👉 [github.com/sedegroot-lang/Bitvavo-Bot/releases](https://github.com/sedegroot-lang/Bitvavo-Bot/releases)
2. Download de nieuwe ZIP
3. Pak uit en vervang de bestanden — je `.env` met API keys blijft staan
4. Dubbelklik `start_automated.bat`

⭐ **Klik op "Watch" of geef een ster op GitHub** om meldingen te krijgen van nieuwe versies.

---

## 💛 Steun de bot

Deze bot is **100% gratis** en blijft gratis. Als je hem waardevol vindt, help me dan om hem te blijven verbeteren!

**Doneer via Bitcoin:**
```
1DUCu4ZGgKHZr22DvAxuWKBujcfpCLJoNy
```

Elke donatie helpt direct mee aan:
- 🐛 Bugfixes en stabiliteitsupdates
- 📈 Nieuwe trading strategieën
- 🤖 Betere AI modellen
- 📊 Dashboard verbeteringen

Dank je wel! 🙏

---

## ✨ Functies

| Functie | Beschrijving |
|---|---|
| **Trailing Stop** | Stop loss die meebeweegt met de winst |
| **DCA Safety Buys** | Automatisch bijkopen bij prijsdaling (tot 9x) |
| **Grid Bot** | AI-geoptimaliseerde grid trading |
| **XGBoost AI** | Machine learning voor entry-signalen |
| **Flask Dashboard** | Real-time portfolio monitoring in browser |
| **Audit Log** | Elke trade vastgelegd met reden en tijdstip |

---

## 🔒 Veiligheid

- API keys staan **alleen** op jouw eigen PC (in `.env` bestand)
- `.env` wordt **nooit** naar GitHub geüpload
- De bot heeft **geen** opnamebevoegdheid — alleen lezen en handelen
- Alle trades worden gelogd voor transparantie

---

## ⚠️ Disclaimer

Cryptocurrency trading brengt financiële risico's met zich mee. Deze bot is een hulpmiddel — geen garantie op winst. Gebruik op eigen risico. Beleg nooit meer dan je kunt missen.

---

## 🏗️ Architectuur (voor gevorderden)

```
trailing_bot.py          ← Hoofd trading engine
modules/                 ← DCA, grid, risk management
core/                    ← Signalen, prijzen, config
ai/                      ← XGBoost AI, supervisor
tools/dashboard_flask/   ← Web dashboard (Flask)
config/bot_config.json   ← Bot configuratie (via dashboard)
data/                    ← Runtime data
logs/                    ← Logbestanden
```
