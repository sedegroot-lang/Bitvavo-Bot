# Bitvavo Bot — Portfolio Roadmap

> **Doel**: Stap-voor-stap opschaalplan van €465 naar €5.000 met exacte config-wijzigingen per €100 mijlpaal.
> Gebaseerd op echte performance data en €100/maand stortingen.

---

## Prestatie-analyse (bron voor alle berekeningen)

| Metric | Waarde | Bron |
|--------|--------|------|
| **Portfoliowaarde** | €465 | account_overview 11-03-2026 |
| **EUR beschikbaar** | €160 | account_overview |
| **Open posities** | 9 | na sync recovery |
| **Totaal gestort** | €870 (12 stortingen) | deposits.json |
| **Maandelijkse storting** | €100 | vast |
| **Trading winst (echt)** | +€859 uit 535 trades | trailing_tp + partial_tp + stop |
| **Bug-gerelateerd verlies** | −€1.713 uit 336 trades | saldo_flood_guard, sync_removed, saldo_error |
| **Winrate (echte trades)** | 71,2% (381 wins / 535) | trade_archive.json |
| **Gem. winst per trade** | €1,61 | alleen echte trades |
| **Laatste 4 weken** | +€65 (W07-W10) | conservatief, zonder outlier W06 |
| **Conservatief weekgemiddelde** | ~€14/week | basis voor alle projecties |

### Huidige config (werkelijk, 3 april 2026)

> **Roadmap €800 fase geactiveerd op 03-04-2026.** 4e trade slot open, BASE en DCA verhoogd.
> HODL scheduler uitgeschakeld.

```json
{
  "MAX_OPEN_TRADES": 4,
  "BASE_AMOUNT_EUR": 52,
  "DCA_MAX_BUYS": 17,
  "DCA_AMOUNT_EUR": 27,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.025,
  "MIN_SCORE_TO_BUY": 7.0,
  "DEFAULT_TRAILING": 0.025,
  "TRAILING_ACTIVATION_PCT": 0.015,
  "HARD_SL_ALT_PCT": 0.25,
  "TAKE_PROFIT_TARGETS": [0.03, 0.06, 0.1],
  "TAKE_PROFIT_PERCENTAGES": [0.3, 0.35, 0.35],
  "GRID_TRADING": { "enabled": false }
}
```

**DCA-bedragen per level (0.9x)**: €27 → €24,30 → €21,87 → €19,68 → ... → €5,03 (level 17)
**Typische blootstelling** (2 DCA): €52 + 27 + 24,30 = **€103,30/slot** → 4 slots = **€413**
**Worst case** (17 DCA): €52 + €227 = **€279/slot** → 4 slots = **€1.116**

---

## Gouden Regels

1. **Nooit een stap overslaan** — elke verhoging bouwt voort op bewezen stabiliteit
2. **Minimaal 2 weken wachten** na elke config-wijziging voor je verder gaat
3. **Winrate check**: moet ≥ 50% zijn over laatste 2 weken voor je opschaalt
4. **EUR buffer**: houd ALTIJD minimaal **15% van portfoliowaarde** vrij in EUR
5. **Grid pas bij €1.000+** met minimaal €40/level (anders vreten fees de marge op)
6. **Bij 15% drawdown**: ga terug naar de vorige mijlpaal-config
7. **Eén ding tegelijk wijzigen** — nooit BASE + DCA + TRADES tegelijk verhogen

---

## Stortingsplan

| Maand | Storting | Cum. gestort | Geschatte portfolio* |
|-------|----------|-------------|---------------------|
| Mrt 2026 | €100 (gedaan) | €870 | €465 (actueel) |
| Apr 2026 | €100 | €970 | €521 |
| Mei 2026 | €100 | €1.070 | €581 |
| Jun 2026 | €100 | €1.170 | €645 |
| Jul 2026 | €100 | €1.270 | €713 |
| Aug 2026 | €100 | €1.370 | €785 |
| Sep 2026 | €100 | €1.470 | €861 |
| Okt 2026 | €100 | €1.570 | €945 |
| Nov 2026 | €100 | €1.670 | €1.035 |
| Dec 2026 | €100 | €1.770 | €1.135 |

*\* Conservatief: €14/week trading + €100/maand storting, stijgend naar €18/w bij opschaling*

> **Na €1.000**: stortingen worden optioneel — de bot verdient genoeg om zelf te groeien.
> **Na €2.000**: overweeg stortingen te stoppen en puur op compounding te draaien.

---

## Overzicht per €100 Mijlpaal

Hieronder elk bedrag met de exacte actie. **"—"** = geen wijziging, blijf op huidige settings.
**DCA_SIZE_MULTIPLIER = 0.9** op alle niveaus. **DCA_MAX_BUYS = 17** op alle niveaus.

| Portfolio | Actie | MAX_TRADES | BASE | DCA_AMT | DCA_DROP | MIN_SCORE | TRAILING | Grid |
|-----------|-------|------------|------|---------|----------|-----------|----------|------|
| **€700** ← nu | *Hybrid F_CONSERVATIEF* | 3 | 48 | 25 | 2,5% | 7,0 | 2,5% | Uit |
| **€800** | ↑ 4 trades, BASE 52, DCA 27 | **4** | **52** | **27** | 2,5% | 7,0 | 2,5% | Uit |
| **€900** | ↑ BASE 56, DCA 28 | 4 | **56** | **28** | 2,5% | 7,0 | 2,4% | Uit |
| **€1.000** | ↑ Grid BTC aan (€150) | 4 | 56 | 28 | 2,5% | 7,0 | 2,4% | **€150 BTC** |
| **€1.100** | ↑ BASE 62, DCA 30 | 4 | **62** | **30** | 2,5% | 7,0 | 2,4% | €150 BTC |
| **€1.200** | ↑ 5 trades | **5** | 62 | 30 | 2,5% | **6,5** | 2,4% | €150 BTC |
| **€1.300** | ↑ BASE 68, DCA 32 | 5 | **68** | **32** | 2,5% | 6,5 | 2,3% | €150 BTC |
| **€1.400** | ↑ Grid ETH erbij (€250 tot.) | 5 | 68 | 32 | 2,5% | 6,5 | 2,3% | **€250 BTC+ETH** |
| **€1.500** | ↑ BASE 75, DCA 35 | 5 | **75** | **35** | 2,5% | 6,5 | 2,3% | €250 |
| **€1.600** | ↑ 6 trades | **6** | 75 | 35 | 2,5% | 6,5 | 2,3% | €250 |
| **€1.700** | ↑ BASE 80, DCA 38 | 6 | **80** | **38** | 2,5% | 6,5 | 2,2% | €250 |
| **€1.800** | ↑ Grid SOL erbij (€400 tot.) | 6 | 80 | 38 | 2,5% | 6,5 | 2,2% | **€400 3 mktn** |
| **€1.900** | ↑ BASE 85 | 6 | **85** | 38 | 2,5% | 6,5 | 2,2% | €400 |
| **€2.000** | ↑ 7 trades, DCA 40 | **7** | 85 | **40** | 2,3% | 6,5 | 2,2% | €400 |
| **€2.200** | ↑ BASE 95, DCA 44 | 7 | **95** | **44** | 2,3% | 6,5 | 2,1% | €400 |
| **€2.400** | ↑ Grid 4 mktn (€600 tot.) | 7 | 95 | 44 | 2,3% | 6,5 | 2,1% | **€600 4 mktn** |
| **€2.600** | ↑ BASE 105, DCA 48 | 7 | **105** | **48** | 2,3% | 6,0 | 2,1% | €600 |
| **€2.800** | ↑ 8 trades | **8** | 105 | 48 | 2,3% | 6,0 | 2,0% | €600 |
| **€3.000** | ↑ BASE 115, DCA 52, Grid 5 mktn | 8 | **115** | **52** | 2,0% | 6,0 | 2,0% | **€800 5 mktn** |
| **€3.500** | ↑ BASE 130, DCA 58, Grid €1.000 | 8 | **130** | **58** | 2,0% | 6,0 | 2,0% | **€1.000 5 mktn** |
| **€4.000** | ↑ 9 trades, BASE 145, Grid 6 mktn | **9** | **145** | **65** | 2,0% | 6,0 | 2,0% | **€1.400 6 mktn** |
| **€4.500** | ↑ BASE 155, DCA 72 | 9 | **155** | **72** | 2,0% | 6,0 | 2,0% | €1.400 |
| **€5.000** | ↑ 10 trades, DCA 78, Grid €2.000 | **10** | **160** | **78** | 2,0% | 6,0 | 2,0% | **€2.000 8 mktn** |

---

## Gedetailleerde Mijlpalen

### 🟢 NU — €738 (Hybrid F_CONSERVATIEF DCA, 26 maart 2026)

> DCA-strategie geoptimaliseerd via simulatie (844 trades). €700 milestone actief.

**DCA wijziging toegepast:**
- DCA_AMOUNT_EUR: 32 → **25** (kleiner startbedrag)
- DCA_SIZE_MULTIPLIER: 0.8 → **0.9** (tragere afname per level)
- DCA_DROP_PCT: 1.9% → **2.5%** (breder: alleen bijkopen bij echte dips)
- DCA_MAX_BUYS: **17** (ongewijzigd — diepe dip-recovery)

**Wat je nu doet:**
- ✅ 3 trailing trades (al ingesteld)
- ✅ Grid uit (terecht — te weinig budget)
- ✅ DCA 17 levels actief met 0.9x afname en 2.5% drop
- 🎯 Wacht tot portfolio stabiel boven €800 voor 2 weken

**Budget check:**
- Typische blootstelling (3 trades, gem. 2 DCA): 3 × (48 + 25 + 22,50) = **€287**
- Worst case (3 trades, 17 DCA elk): 3 × 257 = **€770** (nooit tegelijk)
- EUR buffer bij typische load: €738 − €287 = **€451 vrij** ✅

**Verwacht**: €14/week trailing + €25/week storting = ~€39/week groei → **€800 in ~2 weken**

---

### 📍 €600 — ~~Eerste Verhoging~~ (BEREIKT — overgeslagen)

> Milestone overgeslagen — direct van €465 naar €700 gegaan op 23 maart 2026.

---

### 📍 €700 — Posities Vergroten + DCA Optimalisatie (BEREIKT)

> **Bereikt**: 23 maart 2026. DCA geoptimaliseerd op 26 maart 2026.

**Wijzigingen**: BASE **42 → 48**, DCA **→ 25 (0.9x, 2.5% drop)** (Hybrid F_CONSERVATIEF)

```json
{
  "BASE_AMOUNT_EUR": 48,
  "DCA_AMOUNT_EUR": 25,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.025
}
```

**Waarom DCA_DROP omhoog naar 2.5%?** Simulatie op 844 trades toonde aan dat bredere DCA-afstand alleen bij echte dips bijkoopt (niet bij marktruis). Resultaat: +92% meer P/L bij lagere exposure.

**Budget check:**
- Typisch: 3 × (48 + 25 + 22,50) = **€287** → buffer €451 ✅
- 15% reserve: €700 × 0,15 = €105 ✅

---

### 📍 €800 — Vierde Trade Slot

> **Trigger**: Portfolio ≥ €800 gedurende 2 weken, winrate ≥ 55%.

**Wijzigingen**: MAX_OPEN_TRADES **3 → 4**, BASE **48 → 52**, DCA **25 → 27**

```json
{
  "MAX_OPEN_TRADES": 4,
  "BASE_AMOUNT_EUR": 52,
  "DCA_AMOUNT_EUR": 27
}
```

**Waarom nu een 4e slot?** Meer gelijktijdige trades = meer kansen. Bij €800 is er genoeg buffer voor 4 posities.

**Budget check:**
- Typisch: 4 × (52 + 27 + 24,30) = **€413** → buffer €387 ✅
- 15% reserve: €800 × 0,15 = €120 ✅

---

### 📍 €900 — Posities Verder Verhogen

> **Trigger**: Portfolio ≥ €900, 4e slot werkt soepel.

**Wijzigingen**: BASE **52 → 56**, DCA_AMOUNT **27 → 28**, TRAILING **2,5% → 2,4%**

```json
{
  "BASE_AMOUNT_EUR": 56,
  "DCA_AMOUNT_EUR": 28,
  "DEFAULT_TRAILING": 0.024
}
```

**Waarom trailing naar 2,4%?** Bij grotere posities wil je winst iets sneller vastzetten — €56 × 2,4% = €1,34 activatie. Proportioneel dezelfde uitkomst.

**Budget check:**
- Typisch: 4 × (56 + 28 + 25,20) = **€437** → buffer €463 ✅

---

### ⭐ €1.000 — GRID TRADING TERUG

> **Trigger**: Portfolio ≥ €1.000 voor 4 weken stabiel. Winrate ≥ 55%. Dit is een grote mijlpaal.

**Wijziging**: Grid BTC aan met €150 budget

```json
{
  "GRID_TRADING": {
    "enabled": true,
    "preferred_markets": ["BTC-EUR"],
    "investment_per_grid": 150,
    "max_total_investment": 150,
    "num_grids": 5,
    "grid_mode": "arithmetic",
    "stop_loss_pct": 0.12,
    "take_profit_pct": 0.10,
    "trailing_tp_enabled": true,
    "volatility_adaptive": true
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 15,
    "trailing_pct": 85
  }
}
```

**Waarom nu pas grid?**
- Bij €650 hadden we €80 / 5 levels = €16/level → te klein, fees vraten alles op
- Bij €1.000 met €150 / 5 levels = **€30/level** → minimaal rendabel op BTC
- En er is genoeg trailing budget over: €1.000 × 85% = €850 voor trailing

**Waarom alleen BTC?** Laagste spread, hoogste liquiditeit. Bewijs eerst dat grid werkt op de veiligste markt.

**Budget check:**
- Grid: €150 gereserveerd
- Trailing: 4 slots typisch 4 × (56 + 28 + 25,20) = **€437** → vrij: €1.000 − 150 − 437 = **€413** ✅

---

### 📍 €1.200 — Vijfde Trade Slot

> **Trigger**: Portfolio ≥ €1.200, grid BTC draait ≥ 4 weken, ≥ 3 completed cycles.

**Wijzigingen**: MAX_OPEN_TRADES **4 → 5**, MIN_SCORE **7,0 → 6,5**

```json
{
  "MAX_OPEN_TRADES": 5,
  "MIN_SCORE_TO_BUY": 6.5
}
```

**Waarom MIN_SCORE omlaag?** Met 5 slots wil je iets meer trades — 6,5 laat de goede B-kwaliteit setups ook toe.

**Budget check:**
- Grid: €150 + Trailing 5 × (62 + 30 + 27) = **€595** → totaal €745 → buffer €455 ✅

---

### 📍 €1.400 — Grid Uitbreiden met ETH

> **Trigger**: Portfolio ≥ €1.400, grid BTC rendabel (positieve winst).

**Wijziging**: Grid uitbreiden naar BTC + ETH, totaal €250

```json
{
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR"],
    "investment_per_grid": 125,
    "max_total_investment": 250
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 18,
    "trailing_pct": 82
  }
}
```

**Per grid**: €125 / 5 levels = €25/level. ETH heeft iets grotere moves, dus iets hogere winst per cycle.

---

### ⭐ €1.600 — Zesde Trade Slot

> **Trigger**: Portfolio ≥ €1.600, 5 slots werken stabiel.

**Wijziging**: MAX_OPEN_TRADES **5 → 6**

```json
{ "MAX_OPEN_TRADES": 6 }
```

**Budget check:**
- Grid: €250
- Trailing: 6 × (75 + 35 + 31,50) = **€849** typisch → buffer: €1.600 − 250 − 849 = **€501** ✅

---

### 📍 €1.800 — Grid SOL Erbij

> **Trigger**: Portfolio ≥ €1.800, grid BTC+ETH ≥ 10 completed cycles totaal.

**Wijziging**: Grid naar 3 markten, totaal €400

```json
{
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR"],
    "investment_per_grid": 135,
    "max_total_investment": 400
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 22,
    "trailing_pct": 78
  }
}
```

---

### ⭐ €2.000 — Zevende Slot

> **Trigger**: Portfolio ≥ €2.000 voor 4 weken. Grote mijlpaal!

**Wijzigingen**: MAX_OPEN_TRADES **6 → 7**, DCA_AMOUNT **38 → 40**, DCA_DROP **2,5% → 2,3%**

```json
{
  "MAX_OPEN_TRADES": 7,
  "DCA_AMOUNT_EUR": 40,
  "DCA_DROP_PCT": 0.023
}
```

**Waarom DCA_DROP nu iets omlaag?** Bij €2.000 is er genoeg buffer voor iets agressievere DCA. 2,3% is nog steeds breder dan de oude 1,6% en vangt echte dips.

**Budget check:**
- Grid: €400
- Trailing: 7 × (85 + 40 + 36) = **€1.127** typisch → buffer: €2.000 − 400 − 1.127 = **€473** ✅

---

### 📍 €2.400 — Grid 4 Markten

> **Trigger**: Portfolio ≥ €2.400.

**Wijziging**: Grid naar 4 markten + ADA, totaal €600

```json
{
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR", "ADA-EUR"],
    "investment_per_grid": 150,
    "max_total_investment": 600
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 25,
    "trailing_pct": 75
  }
}
```

---

### ⭐ €3.000 — Achtste Slot + Grid 5 Markten

> **Trigger**: Portfolio ≥ €3.000 voor 6 weken. Respect.

**Wijzigingen**: MAX_OPEN_TRADES **7 → 8**, BASE **105 → 115**, DCA **48 → 52**, DCA_DROP **2,3% → 2,0%**, Grid €800 met 5 markten

```json
{
  "MAX_OPEN_TRADES": 8,
  "BASE_AMOUNT_EUR": 115,
  "DCA_AMOUNT_EUR": 52,
  "DCA_DROP_PCT": 0.020,
  "DEFAULT_TRAILING": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR", "ADA-EUR", "DOT-EUR"],
    "investment_per_grid": 160,
    "max_total_investment": 800
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 27,
    "trailing_pct": 73
  }
}
```

**Budget check:**
- Grid: €800
- Trailing: 8 × (115 + 52 + 46,80) = **€1.710** typisch → buffer: €3.000 − 800 − 1.710 = **€490** ✅

**Verwachte opbrengst bij €3.000:**
- Trailing: 8 slots × ~€2,50/trade × ~2 trades/dag = **€4/dag**
- Grid: €800 budget × ~0,08%/dag = **€0,64/dag**
- **Totaal**: ~€4,60/dag → **€32/week** → **€140/maand**

---

### 📍 €3.500 — Posities Opschalen

```json
{
  "BASE_AMOUNT_EUR": 130,
  "DCA_AMOUNT_EUR": 58,
  "GRID_TRADING": {
    "max_total_investment": 1000,
    "investment_per_grid": 200
  }
}
```

---

### 📍 €4.000 — Negende Slot + Grid 6 Markten

```json
{
  "MAX_OPEN_TRADES": 9,
  "BASE_AMOUNT_EUR": 145,
  "DCA_AMOUNT_EUR": 65,
  "DEFAULT_TRAILING": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR", "ADA-EUR", "DOT-EUR", "LINK-EUR"],
    "investment_per_grid": 235,
    "max_total_investment": 1400
  }
}
```

---

### 📍 €4.500 — DCA Opschalen

```json
{
  "BASE_AMOUNT_EUR": 155,
  "DCA_AMOUNT_EUR": 72
}
```

---

### 🏆 €5.000 — Einddoel: Passief Inkomen

> **Portfolio machine.** Bot draait zichzelf. Stortingen niet meer nodig.

```json
{
  "MAX_OPEN_TRADES": 10,
  "BASE_AMOUNT_EUR": 160,
  "DCA_AMOUNT_EUR": 78,
  "DCA_DROP_PCT": 0.020,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "MIN_SCORE_TO_BUY": 6.0,
  "DEFAULT_TRAILING": 0.020,
  "TRAILING_ACTIVATION_PCT": 0.012,
  "GRID_TRADING": {
    "enabled": true,
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR", "ADA-EUR", "DOT-EUR", "LINK-EUR", "AVAX-EUR", "MATIC-EUR"],
    "investment_per_grid": 250,
    "max_total_investment": 2000,
    "num_grids": 8,
    "grid_mode": "arithmetic",
    "trailing_tp_enabled": true,
    "volatility_adaptive": true
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 40,
    "trailing_pct": 60
  }
}
```

**Verwachte opbrengst bij €5.000:**
- Trailing: 10 slots, ~€3/trade, ~3 trades/dag = **€9/dag**
- Grid: €2.000 × ~0,08%/dag = **€1,60/dag**
- **Totaal**: ~€10,50/dag → **€73/week** → **€315/maand**

---

## Bear Market Protocol 🔴

> Als de cryptomarkt crasht, bescherm je kapitaal met deze noodprocedure.

### Trigger 1: Portfolio daalt 10% in 1 week
**Actie**: Verlaag MAX_OPEN_TRADES met 1, verhoog MIN_SCORE_TO_BUY met 0,5

### Trigger 2: Portfolio daalt 20% in 2 weken
**Actie**: Ga terug naar config van 2 mijlpalen eerder (bijv. van €1.200 naar €1.000 config)

### Trigger 3: Portfolio daalt 30%+ (crash)
**Noodconfig:**
```json
{
  "MAX_OPEN_TRADES": 2,
  "BASE_AMOUNT_EUR": 30,
  "DCA_AMOUNT_EUR": 15,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.030,
  "MIN_SCORE_TO_BUY": 8.0,
  "GRID_TRADING": { "enabled": false }
}
```
> DCA_MAX_BUYS blijft 17 maar met €15 base en 0.9x multiplier is worst-case DCA-exposure slechts ~€125/slot.
> DCA_DROP 3,0% zorgt voor brede spacing zodat alleen echte dips aangevuld worden.

**Wacht** tot markt 2 weken stabiel is. Schaal dan geleidelijk terug op.

### Herstelprotocol
1. Na 2 groene weken: terug naar 3 trades
2. Na 4 groene weken: terug naar vorige mijlpaal-config
3. Na 6 groene weken: verder met roadmap

---

## Stortingen Stopzetten?

| Portfolio | Storting | Reden |
|-----------|----------|-------|
| < €1.000 | €100/maand | Versnelt groei significant |
| €1.000–€2.000 | €100/maand of €50/maand | Bot verdient ~€60-100/maand zelf |
| €2.000–€3.000 | €50/maand optioneel | Bot verdient genoeg |
| > €3.000 | Stoppen | Puur compounding, geen stortingen meer nodig |

---

## Waarschuwingen

### ❌ Nooit doen
- **Sla geen mijlpaal over** — verliesgevend opschalen vernietigt compounding
- **Grid onder €1.000** — fees vreten bij kleine orders alle marge op (bewezen: 0 fills bij €7,60/level)
- **BASE_AMOUNT verhogen als winrate < 50%** — fix eerst je entries
- **DCA_AMOUNT ophogen zonder budget check** — bereken altijd worst-case exposure (17 DCAs met 0.9x multiplier)
- **DCA_DROP onder 2,0%** — simulatie bewees: bredere drops = beter rendement
- **MIN_SCORE onder 6.0** — te veel noise trades
- **Meerdere dingen tegelijk wijzigen** — onduidelijk wat werkt en wat niet
- **Trailing onder 2,0%** — te veel vroegtijdige exits bij normale volatiliteit

### ✅ Altijd doen
- Check winrate elke 2 weken in het dashboard
- Houd 15% van portfolio als EUR reserve
- Na config-wijziging: 2 weken stabilisatieperiode
- Log elke wijziging in git commit message
- Bij twijfel: doe NIETS en wacht een week

---

## Voortgang Tracker

Vink af wanneer bereikt:

- [x] €465 — Huidige stand (11 maart 2026)
- [x] €500 — Stabiel draaien, geen wijzigingen (bereikt ~18 maart 2026)
- [x] €600 — BASE → 42 (overgeslagen — direct naar €700)
- [x] €700 — Hybrid F_CONSERVATIEF DCA: DCA=25, MULT=0.9, DROP=2.5% (26 maart 2026)
- [x] €800 — 4 trades, BASE → 52, DCA → 27 (3 april 2026)
- [ ] €900 — BASE → 56, DCA → 28
- [ ] €1.000 ⭐ — Grid BTC aan (€150)
- [ ] €1.100 — BASE → 62, DCA → 30
- [ ] €1.200 — 5 trades, MIN_SCORE → 6,5
- [ ] €1.300 — BASE → 68, DCA → 32
- [ ] €1.400 — Grid ETH erbij (€250 totaal)
- [ ] €1.500 — BASE → 75, DCA → 35
- [ ] €1.600 — 6 trades
- [ ] €1.700 — BASE → 80, DCA → 38
- [ ] €1.800 — Grid SOL erbij (€400 totaal)
- [ ] €1.900 — BASE → 85
- [ ] €2.000 ⭐ — 7 trades, DCA → 40, DROP → 2,3%
- [ ] €2.200 — BASE → 95, DCA → 44
- [ ] €2.400 — Grid 4 markten (€600)
- [ ] €2.600 — BASE → 105, DCA → 48
- [ ] €2.800 — 8 trades
- [ ] €3.000 ⭐ — Grid 5 markten (€800), DROP → 2,0%
- [ ] €3.500 — BASE → 130, DCA → 58, Grid €1.000
- [ ] €4.000 — 9 trades, DCA → 65, Grid 6 markten (€1.400)
- [ ] €4.500 — BASE → 155, DCA → 72
- [ ] €5.000 🏆 — 10 trades, DCA → 78, Grid €2.000, passief inkomen

---

*Laatste update: 3 april 2026 — Portfolio ~€800, Roadmap €800 fase actief, HODL scheduler uit*
*Config: BASE=52, DCA=27, MULT=0.9, DCA_DROP=2.5%, 4 slots, grid uit*
*Volgende mijlpaal: €900 (BASE → 56, DCA → 28, TRAILING → 2,4%) — wacht 2 weken stabilisatie*
