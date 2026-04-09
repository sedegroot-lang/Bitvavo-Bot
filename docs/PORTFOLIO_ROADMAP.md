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

### Huidige config (werkelijk, 8 april 2026)

> **Roadmap €1.200 fase geactiveerd op 09-04-2026.** MAX_OPEN_TRADES 4→5.
> €900 fase overgeslagen (portfolio sprong van €800 naar €1.050).
> Grid BTC actief sinds €1.000 fase (07-04-2026). HODL scheduler uitgeschakeld.

```json
{
  "MAX_OPEN_TRADES": 5,
  "BASE_AMOUNT_EUR": 62,
  "DCA_MAX_BUYS": 17,
  "DCA_AMOUNT_EUR": 30,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.025,
  "MIN_SCORE_TO_BUY": 7.0,
  "DEFAULT_TRAILING": 0.024,
  "TRAILING_ACTIVATION_PCT": 0.020,
  "TAKE_PROFIT_ENABLED": false,
  "HARD_SL_ALT_PCT": 0.25,
  "GRID_TRADING": {
    "enabled": true,
    "preferred_markets": ["BTC-EUR"],
    "investment_per_grid": 150,
    "max_total_investment": 150,
    "num_grids": 5
  },
  "BUDGET_RESERVATION": { "grid_pct": 15, "trailing_pct": 85 }
}
```

**DCA-bedragen per level (0.9x)**: €30 → €27,00 → €24,30 → €21,87 → ... → €5,58 (level 17)
**Typische blootstelling** (2 DCA): €62 + 30 + 27,00 = **€119,00/slot** → 5 slots = **€595**
**Grid BTC**: €150 gereserveerd (15% van portfolio)
**Worst case** (17 DCA): €62 + €256 = **€318/slot** → 5 slots = **€1.590**

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
| **€700** ✅ | *Hybrid F_CONSERVATIEF* | 3 | 48 | 25 | 2,5% | 7,0 | 2,5% | Uit |
| **€800** ✅ | ↑ 4 trades, BASE 52, DCA 27 | **4** | **52** | **27** | 2,5% | 7,0 | 2,5% | Uit |
| **€900** ⏭️ | ↑ BASE 56, DCA 28 | 4 | **56** | **28** | 2,5% | 7,0 | 2,4% | Uit |
| **€1.000** ✅ | ↑ Grid BTC aan (€150) | 4 | 56 | 28 | 2,5% | 7,0 | 2,4% | **€150 BTC** |
| **€1.100** ✅ | ↑ BASE 62, DCA 30 | 4 | **62** | **30** | 2,5% | 7,0 | 2,4% | €150 BTC |
| **€1.200** ← nu | ↑ 5 trades | **5** | 62 | 30 | 2,5% | 7,0 | 2,4% | €150 BTC |
| **€1.400** | ↑ BASE 68, DCA 32, Grid +ETH | 5 | **68** | **32** | 2,5% | 7,0 | 2,3% | **€250 BTC+ETH** |
| **€1.600** | ↑ 6 trades, BASE 75, DCA 35 | **6** | **75** | **35** | 2,5% | 7,0 | 2,3% | €250 |
| **€2.000** | ↑ 7 trades, BASE 85, DCA 40 | **7** | **85** | **40** | 2,3% | 7,0 | 2,2% | **€350 BTC+ETH** |
| **€2.500** | ↑ BASE 100, DCA 46, Grid +LINK | 7 | **100** | **46** | 2,3% | 7,0 | 2,1% | **€500 3 mktn** |
| **€3.000** | ↑ 8 trades, BASE 115, DCA 52, +XRP | **8** | **115** | **52** | 2,0% | 7,0 | 2,0% | **€700 4 mktn** |
| **€3.500** | ↑ BASE 130, DCA 58, Grid €900 | 8 | **130** | **58** | 2,0% | 7,0 | 2,0% | **€900 4 mktn** |
| **€4.000** | ↑ 9 trades, BASE 145, DCA 65, +DOT | **9** | **145** | **65** | 2,0% | 7,0 | 2,0% | **€1.200 5 mktn** |
| **€5.000** | ↑ 10 trades, BASE 160, DCA 78 | **10** | **160** | **78** | 2,0% | 7,0 | 2,0% | **€1.800 6 mktn** |

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

### 📍 €900 — ~~Posities Verder Verhogen~~ (OVERGESLAGEN)

> Milestone overgeslagen — direct van €800 naar €1.000+ gegaan op 7 april 2026.
> Wijzigingen (BASE 56, DCA 28, TRAILING 2.4%) meegenomen in €1.000 activatie.

> ~~**Trigger**: Portfolio ≥ €900, 4e slot werkt soepel.~~

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

### ⭐ €1.000 — GRID TRADING TERUG (GEACTIVEERD)

> **Geactiveerd**: 7 april 2026. Portfolio €1.050. Grid BTC aan met €150.
> ~~**Trigger**: Portfolio ≥ €1.000 voor 4 weken stabiel. Winrate ≥ 55%.~~ Dit is een grote mijlpaal.

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

**Wijzigingen**: MAX_OPEN_TRADES **4 → 5**

```json
{
  "MAX_OPEN_TRADES": 5
}
```

**MIN_SCORE blijft 7,0** — hogere drempel houdt kwaliteit hoog, ook met meer slots.

**Budget check:**
- Grid: €150 + Trailing 5 × (62 + 30 + 27) = **€595** → totaal €745 → buffer €455 ✅

---

### 📍 €1.400 — Posities Vergroten + Grid ETH

> **Trigger**: Portfolio ≥ €1.400, grid BTC rendabel (positieve winst).
> Combineert oude €1.300 + €1.400 stappen — grotere sprongen = minder overhead.

**Wijzigingen**: BASE **62 → 68**, DCA **30 → 32**, Grid uitbreiden naar BTC + ETH (€250)

```json
{
  "BASE_AMOUNT_EUR": 68,
  "DCA_AMOUNT_EUR": 32,
  "DEFAULT_TRAILING": 0.023,
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

**Per grid**: €125 / 5 levels = €25/level. ETH helpt diversificatie — iets grotere moves dan BTC, meer grid-cycli.

**Budget check:**
- Grid: €250 + Trailing 5 × (68 + 32 + 28,80) = **€644** → totaal €894 → buffer €506 (36%) ✅

---

### ⭐ €1.600 — Zesde Trade Slot + Opschalen

> **Trigger**: Portfolio ≥ €1.600, 5 slots werken stabiel ≥ 2 weken.
> Combineert oude €1.500 + €1.600 stappen.

**Wijzigingen**: MAX_OPEN_TRADES **5 → 6**, BASE **68 → 75**, DCA **32 → 35**

```json
{
  "MAX_OPEN_TRADES": 6,
  "BASE_AMOUNT_EUR": 75,
  "DCA_AMOUNT_EUR": 35
}
```

**Budget check:**
- Grid: €250
- Trailing: 6 × (75 + 35 + 31,50) = **€849** → totaal €1.099 → buffer €501 (31%) ✅

---

### ⭐ €2.000 — Zevende Slot + Grid Opschalen

> **Trigger**: Portfolio ≥ €2.000 voor 4 weken. Grote mijlpaal!
> Combineert oude €1.700–€2.000 stappen. Grid blijft 2 markten — hogere bedragen per level = minder fee-drag.

**Wijzigingen**: MAX_OPEN_TRADES **6 → 7**, BASE **75 → 85**, DCA **35 → 40**, DCA_DROP **2,5% → 2,3%**, Grid budget omhoog naar €350

```json
{
  "MAX_OPEN_TRADES": 7,
  "BASE_AMOUNT_EUR": 85,
  "DCA_AMOUNT_EUR": 40,
  "DCA_DROP_PCT": 0.023,
  "DEFAULT_TRAILING": 0.022,
  "GRID_TRADING": {
    "investment_per_grid": 175,
    "max_total_investment": 350
  }
}
```

**Waarom 2 grids houden?** €350 / 2 markten = €175/markt / 5 levels = **€35/level** — comfortabel. 3 markten zou €117/markt = €23/level zijn → te dun, meer fee-drag. Pas bij €2.500+ is 3 markten zinvol.

**Budget check:**
- Grid: €350
- Trailing: 7 × (85 + 40 + 36) = **€1.127** → totaal €1.477 → buffer €523 (26%) ✅

---

### 📍 €2.500 — Grid LINK Erbij

> **Trigger**: Portfolio ≥ €2.500, grid BTC+ETH ≥ 20 completed cycles totaal.
> LINK als 3e grid i.p.v. SOL — LINK heeft bewezen hogere winrate (90%) en betere PnL in grid-analyse.

**Wijzigingen**: BASE **85 → 100**, DCA **40 → 46**, Grid naar 3 markten (BTC+ETH+LINK), totaal €500

```json
{
  "BASE_AMOUNT_EUR": 100,
  "DCA_AMOUNT_EUR": 46,
  "DEFAULT_TRAILING": 0.021,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR"],
    "investment_per_grid": 167,
    "max_total_investment": 500
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 20,
    "trailing_pct": 80
  }
}
```

**Waarom LINK i.p.v. SOL?** Grid-analyse toonde: LINK-EUR had 90% winrate (+€7,11 PnL), SOL-EUR was negatief (-€6,14). LINK heeft goede mean-reversion, voldoende volume op Bitvavo, en lagere correlatie met BTC/ETH.

**Budget check:**
- Grid: €500
- Trailing: 7 × (100 + 46 + 41,40) = **€1.312** → totaal €1.812 → buffer €688 (28%) ✅

---

### ⭐ €3.000 — Achtste Slot + Grid XRP

> **Trigger**: Portfolio ≥ €3.000 voor 4 weken. Respect!
> XRP als 4e grid — hoogste volume op Bitvavo, strakke spread, goede grid-fit.

**Wijzigingen**: MAX_OPEN_TRADES **7 → 8**, BASE **100 → 115**, DCA **46 → 52**, DCA_DROP **2,3% → 2,0%**, Grid €700 met 4 markten

```json
{
  "MAX_OPEN_TRADES": 8,
  "BASE_AMOUNT_EUR": 115,
  "DCA_AMOUNT_EUR": 52,
  "DCA_DROP_PCT": 0.020,
  "DEFAULT_TRAILING": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR"],
    "investment_per_grid": 175,
    "max_total_investment": 700
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 23,
    "trailing_pct": 77
  }
}
```

**Budget check:**
- Grid: €700
- Trailing: 8 × (115 + 52 + 46,80) = **€1.710** → totaal €2.410 → buffer €590 (20%) ✅

**Verwachte opbrengst bij €3.000:**
- Trailing: 8 slots × ~€2,50/trade × ~2 trades/dag = **€4/dag**
- Grid: €700 budget × ~0,08%/dag = **€0,56/dag**
- **Totaal**: ~€4,56/dag → **€32/week** → **€140/maand**

---

### 📍 €3.500 — Posities Opschalen

> Grid 4 markten met meer kapitaal per level.

```json
{
  "BASE_AMOUNT_EUR": 130,
  "DCA_AMOUNT_EUR": 58,
  "GRID_TRADING": {
    "investment_per_grid": 225,
    "max_total_investment": 900
  }
}
```

**Budget check:**
- Grid: €900
- Trailing: 8 × (130 + 58 + 52,20) = **€1.922** → totaal €2.822 → buffer €678 (19%) ✅

---

### 📍 €4.000 — Negende Slot + Grid DOT

> 5e grid markt: DOT. Portfolio groot genoeg voor verdere diversificatie.

```json
{
  "MAX_OPEN_TRADES": 9,
  "BASE_AMOUNT_EUR": 145,
  "DCA_AMOUNT_EUR": 65,
  "DEFAULT_TRAILING": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR", "DOT-EUR"],
    "investment_per_grid": 240,
    "max_total_investment": 1200
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 30,
    "trailing_pct": 70
  }
}
```

---

### 🏆 €5.000 — Einddoel: Passief Inkomen

> **Portfolio machine.** Bot draait zichzelf. Stortingen niet meer nodig.
> 6e grid markt: AVAX. Volledige diversificatie.

```json
{
  "MAX_OPEN_TRADES": 10,
  "BASE_AMOUNT_EUR": 160,
  "DCA_AMOUNT_EUR": 78,
  "DCA_DROP_PCT": 0.020,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "MIN_SCORE_TO_BUY": 7.0,
  "DEFAULT_TRAILING": 0.020,
  "TRAILING_ACTIVATION_PCT": 0.012,
  "GRID_TRADING": {
    "enabled": true,
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR", "DOT-EUR", "AVAX-EUR"],
    "investment_per_grid": 300,
    "max_total_investment": 1800,
    "num_grids": 8,
    "grid_mode": "arithmetic",
    "trailing_tp_enabled": true,
    "volatility_adaptive": true
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 36,
    "trailing_pct": 64
  }
}
```

**Verwachte opbrengst bij €5.000:**
- Trailing: 10 slots, ~€3/trade, ~3 trades/dag = **€9/dag**
- Grid: €1.800 × ~0,08%/dag = **€1,44/dag**
- **Totaal**: ~€10,44/dag → **€73/week** → **€315/maand**

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
- [x] €900 — BASE → 56, DCA → 28 (overgeslagen → meegenomen in €1.000)
- [x] €1.000 ⭐ — Grid BTC aan (€150) (7 april 2026)
- [x] €1.100 ✅ — BASE → 62, DCA → 30 (8 april 2026)
- [x] €1.200 ← nu — 5 trades (9 april 2026)
- [ ] €1.400 — BASE → 68, DCA → 32, Grid +ETH (€250)
- [ ] €1.600 — 6 trades, BASE → 75, DCA → 35
- [ ] €2.000 ⭐ — 7 trades, BASE → 85, DCA → 40, Grid €350
- [ ] €2.500 — BASE → 100, DCA → 46, Grid +LINK (€500)
- [ ] €3.000 ⭐ — 8 trades, BASE → 115, DCA → 52, Grid +XRP (€700)
- [ ] €3.500 — BASE → 130, DCA → 58, Grid €900
- [ ] €4.000 — 9 trades, BASE → 145, DCA → 65, Grid +DOT (€1.200)
- [ ] €5.000 🏆 — 10 trades, BASE → 160, DCA → 78, Grid +AVAX (€1.800)

---

*Laatste update: 9 april 2026 — Trailing activation 1.5→2.0%, Partial TP uitgeschakeld, roadmap geherstructureerd*
*Config: BASE=62, DCA=30, MULT=0.9, DCA_DROP=2.5%, 5 slots, grid BTC €150, MIN_SCORE=7.0, TRAILING_ACT=2.0%, Partial TP=UIT*
*Volgende mijlpaal: €1.400 (BASE → 68, DCA → 32, Grid +ETH) — wacht 2 weken stabilisatie*
