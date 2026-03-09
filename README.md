# 🤖 Bitvavo Trading Bot

> **Laat de bot je crypto handelen — terwijl jij leeft.**

Volledig geautomatiseerde crypto trading bot voor Bitvavo, speciaal gebouwd voor de Nederlandse markt. 100% gratis, open source, en draait op je eigen PC.

---

## 💡 Wat doet de bot precies?

De bot koopt en verkoopt crypto voor je op [Bitvavo](https://bitvavo.com/invite?a=B8942E4528) — automatisch, 24 uur per dag, 7 dagen per week. Terwijl jij slaapt, werkt, of op vakantie bent.

### De drie strategieën:

**1. 🎯 Trailing Stop Bot**
De bot koopt in als de AI een goed instapmoment herkent. Zodra de prijs stijgt, beweegt de stop mee omhoog. Daalt de prijs na een stijging? Automatisch verkopen met winst. Je winst wordt beschermd, verliezen worden beperkt.

**2. 💧 DCA Safety Buys (Dollar Cost Averaging)**
Als een munt daalt na aankoop, koopt de bot automatisch bij op lagere niveaus — zodat je gemiddelde aankoopprijs daalt. Tot 9 bijkopen mogelijk. Bij herstel van de prijs staat de bot daardoor sneller in de winst.

**3. 📊 Grid Bot**
In zijwaartse markten verdient de bot door te kopen op support-niveaus en te verkopen op resistance-niveaus. Pakt kleine winsten bij elk op-en-neer.

### De AI:
Een **XGBoost machine learning model** analyseert koerssignalen (RSI, MACD, SMA, volume) en geeft elk koopmoment een score. De bot koopt alleen als de kans op succes hoog genoeg is. Hoe langer de bot draait, hoe beter het model leert van jouw eigen trades.

---

## 🏆 Bot vs. handmatig traden

| | Handmatig traden | Met deze bot |
|---|---|---|
| Analyseren | Zelf doen, uren per dag | Automatisch, 24/7 |
| Instap timing | Op gevoel | AI score-systeem |
| Stop loss | Vergeten in te stellen | Altijd actief, dynamisch |
| Bijkopen bij dip | Vaak te laat of te bang | Automatisch op de juiste niveaus |
| Emoties | Kopen op FOMO, verkopen in paniek | Geen emoties — alleen regels |
| Kosten | Uw eigen tijd | €0 — volledig gratis |

---

## 📊 Dashboard

Alles in realtime in je browser op **http://localhost:5001**:

| Tab | Wat je ziet |
|---|---|
| **📊 Overview** | Portfolio P&L, open trades, winst vandaag |
| **💼 Trades** | Alle open en gesloten posities |
| **🤖 AI** | AI scores, markt regime, suggesties |
| **📈 Analytics** | Historische performance, grafieken |
| **⚙️ Settings** | Alle parameters + Telegram instellen |
| **📅 HODL** | Wekelijkse DCA voor BTC/ETH |
| **🔲 Grid** | Grid bot status en instellingen |

---

## 🏦 Stap 1 — Bitvavo account aanmaken

> ### 👉 [Registreer GRATIS via onze link](https://bitvavo.com/invite?a=B8942E4528)
> **https://bitvavo.com/invite?a=B8942E4528**
>
> - ✅ **#1 crypto exchange van Nederland** — meeste volume, beste gebruikersgemak
> - ✅ Laagste kosten: **0,00% – 0,25%** per trade
> - ✅ Gereguleerd en veilig (DNB-vergunning)
> - ✅ 100% gratis registratie, binnen 5 minuten actief
>
> _Via onze link ontvangen we een kleine commissie van Bitvavo. Voor jou verandert niets._
>
> **Al een account?** Ga direct naar stap 2.

---

## 💿 Stap 2 — Python installeren

De bot heeft Python nodig. Dit is eenmalig.

1. Ga naar [python.org/downloads](https://www.python.org/downloads/)
2. Download de nieuwste versie (3.11 of hoger)
3. Start de installer
4. ⚠️ **Belangrijk:** vink **"Add Python to PATH"** aan onderaan het eerste scherm
5. Klik "Install Now"

---

## 📥 Stap 3 — Bot downloaden

👉 **[Download de nieuwste versie (ZIP)](https://github.com/sedegroot-lang/Bitvavo-Bot/releases/latest)**

1. Klik op de link → **Assets → bitvavo-bot-vX.Y.Z.zip**
2. Pak het ZIP-bestand uit naar een vaste map, bijv. `C:\BitvavoBot\`

> **Let op:** gebruik een mapnaam zonder spaties, bijv. `C:\BitvavoBot\`

---

## ⚙️ Stap 4 — Installeren via setup wizard

Dubbelklik op **`setup.bat`** in de uitgepakte map.

De wizard:
- ✅ Vraagt of je een Bitvavo account hebt
- ✅ Begeleidt je bij API sleutels aanmaken
- ✅ Slaat je sleutels veilig op (alleen op jouw PC, nooit online)
- ✅ Stelt optioneel Telegram notificaties in
- ✅ Installeert alle benodigde Python packages
- ✅ Start de bot direct als je wil

### API sleutels aanmaken (in de wizard)

1. Log in op [bitvavo.com](https://bitvavo.com)
2. Ga naar **Account → Instellingen → API sleutels**
3. Klik **"Nieuwe API sleutel aanmaken"**
4. Vink aan: **Lezen** ✅ en **Handelen** ✅ — **Opnemen** ❌ (NIET aanvinken!)
5. Kopieer de **Key** en **Secret** — de Secret zie je maar één keer!
6. Plak ze in de wizard

---

## 🚀 Stap 5 — Bot starten

Na de wizard dubbelklik je voortaan op **`start_automated.bat`**.

Het dashboard opent automatisch op: **http://localhost:5001**

> **Sluit het PowerShell-venster niet** — dat is de bot. Minimaliseer het naar de taakbalk.

---

## ⚙️ Parameters instellen

Ga naar **http://localhost:5001** → tab **⚙️ Settings**:

| Instelling | Wat het doet | Standaard |
|---|---|---|
| **Budget per trade** | Hoeveel euro per aankoop | €12 |
| **Max open trades** | Hoeveel munten tegelijk | 5 |
| **Trailing stop %** | Hoe ver de prijs mag dalen na een top | 4% |
| **DCA levels** | Hoeveel keer bijkopen bij daling | 9x |
| **Min AI score** | Hoe zeker de AI moet zijn voor aankoop | 5 |
| **Budget verdeling** | % voor Trailing Bot vs Grid Bot | 75% / 25% |

> **Tip voor beginners:** Begin met de standaardinstellingen. Pas alleen **Budget per trade** aan op je beschikbare kapitaal. Klein beginnen (€10/trade) is verstandig.

---

## 📱 Telegram notificaties instellen (aanbevolen)

Ontvang direct een berichtje op je telefoon als de bot koopt, verkoopt of een fout tegenkomt.

### Stap 1 — Telegram bot aanmaken (2 min)

1. Open Telegram → zoek **@BotFather** → tik `/newbot`
2. Geef een naam (bijv. `Bitvavo Bot`) en gebruikersnaam (bijv. `mijnbitvavo_bot`)
3. Je krijgt een **token** zoals `8397921391:AAGYxx...` — bewaar dit

### Stap 2 — Je Chat ID ophalen

1. Stuur je nieuwe bot een willekeurig berichtje
2. Ga naar:
   ```
   https://api.telegram.org/bot<JOUW_TOKEN>/getUpdates
   ```
3. Zoek het getal achter `"id":` — dit is je **Chat ID**

### Stap 3 — Instellen in dashboard

Ga naar **⚙️ Settings** → sectie **📱 Telegram Notificaties**:
- Vul Token en Chat ID in
- Zet toggle op **Aan**
- Klik **💾 Opslaan** en dan **🔔 Test**

Je ontvangt dan direct een testberichtje ✅

---

## 🔄 Updates

De bot updatet **niet automatisch**. Nieuwe versie uitgebracht?

1. Ga naar 👉 [github.com/sedegroot-lang/Bitvavo-Bot/releases](https://github.com/sedegroot-lang/Bitvavo-Bot/releases)
2. Download de nieuwe ZIP
3. Pak uit in **dezelfde map** — overschrijf de bestanden
4. Je `.env` en `config/bot_config.json` blijven bewaard
5. Dubbelklik `start_automated.bat`

⭐ Klik op **"Watch" → "Releases only"** op GitHub voor e-mailmeldingen bij nieuwe versies.

---

## 📚 Documentatie

| Document | Beschrijving |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technische opbouw van de bot |
| [CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md) | Alle configuratie-opties gedetailleerd |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Installatie op Linux, VPS of Docker |
| [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Veelvoorkomende problemen oplossen |
| [STRATEGY_LOGIC.md](docs/STRATEGY_LOGIC.md) | Hoe de trading strategieën werken |
| [TRADING_STRATEGY.md](docs/TRADING_STRATEGY.md) | Entry/exit logica gedetailleerd |

---

## 🐛 Bug melden of hulp nodig?

👉 **[Open een Issue op GitHub](https://github.com/sedegroot-lang/Bitvavo-Bot/issues/new)**

Vermeld:
- Wat je deed toen het misging
- De foutmelding (kopieer uit het PowerShell-venster)
- Windows versie + Python versie (`python --version`)

💡 Bekijk eerst [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — je antwoord staat er misschien al in.

---

## 💛 Steun de bot

Deze bot is **100% gratis** en blijft gratis. Vind je hem waardevol?

**Doneer via Bitcoin:**
```
1DUCu4ZGgKHZr22DvAxuWKBujcfpCLJoNy
```

Elke donatie helpt direct: bugfixes, nieuwe strategieën, betere AI, dashboard verbeteringen. Dank je wel! 🙏

---

## 🔒 Veiligheid

- API keys staan **alleen** op jouw PC (`.env` bestand)
- `.env` wordt **nooit** naar GitHub geüpload (staat in `.gitignore`)
- De bot heeft **geen** opnamebevoegdheid — alleen lezen en handelen
- Volledig open source — je kunt alles inzien

---

## ⚠️ Disclaimer

Cryptocurrency trading brengt financiële risico's met zich mee. Deze bot is een hulpmiddel — geen garantie op winst. Gebruik op eigen risico. Beleg nooit meer dan je kunt missen.

---

## 🏗️ Architectuur (voor gevorderden)

```
trailing_bot.py          ← Hoofd trading engine
modules/                 ← DCA, grid, risk management
core/                    ← Signalen, prijzen, indicatoren
ai/                      ← XGBoost AI, supervisor
tools/dashboard_flask/   ← Web dashboard (Flask, poort 5001)
config/bot_config.json   ← Bot configuratie (via dashboard)
data/                    ← Runtime data en trade log
logs/                    ← Logbestanden
```

Zie [ARCHITECTURE.md](docs/ARCHITECTURE.md) voor volledige technische uitleg.