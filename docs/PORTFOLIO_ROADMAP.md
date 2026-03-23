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

### Huidige config (werkelijk, maart 2026)

```json
{
  "MAX_OPEN_TRADES": 3,
  "BASE_AMOUNT_EUR": 38.0,
  "DCA_MAX_BUYS": 9,
  "DCA_AMOUNT_EUR": 30.4,
  "DCA_DROP_PCT": 0.02,
  "MIN_SCORE_TO_BUY": 7.0,
  "DEFAULT_TRAILING": 0.025,
  "TRAILING_ACTIVATION_PCT": 0.015,
  "HARD_SL_ALT_PCT": 0.25,
  "TAKE_PROFIT_TARGETS": [0.03, 0.06, 0.1],
  "TAKE_PROFIT_PERCENTAGES": [0.3, 0.35, 0.35],
  "GRID_TRADING": { "enabled": false }
}
```

**Max blootstelling huidige config**: €38 + 9 × €30,40 = **€311,60 per slot** → 3 slots = **€934,80 worst case**

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

| Portfolio | Actie | MAX_TRADES | BASE | DCA_MAX | DCA_AMT | DCA_DROP | MIN_SCORE | TRAILING | Grid |
|-----------|-------|------------|------|---------|---------|----------|-----------|----------|------|
| **€465** ← nu | *Huidige config* | 3 | 38 | 9 | 30,40 | 2,0% | 7,0 | 2,5% | Uit |
| **€500** | — geen wijziging | 3 | 38 | 9 | 30,40 | 2,0% | 7,0 | 2,5% | Uit |
| **€600** | ↑ BASE naar 42 | 3 | **42** | 9 | 30,40 | 2,0% | 7,0 | 2,5% | Uit |
| **€700** | ↑ BASE naar 48, DCA naar 32 | 3 | **48** | 9 | **32** | 1,9% | 7,0 | 2,5% | Uit |
| **€800** | ↑ 4 trades, BASE 52 | **4** | **52** | 9 | 32 | 1,9% | 7,0 | 2,5% | Uit |
| **€900** | ↑ BASE 56, DCA 34 | 4 | **56** | 9 | **34** | 1,8% | 7,0 | 2,4% | Uit |
| **€1.000** | ↑ Grid BTC aan (€150) | 4 | 56 | 9 | 34 | 1,8% | 7,0 | 2,4% | **€150 BTC** |
| **€1.100** | ↑ BASE 62 | 4 | **62** | 9 | 34 | 1,8% | 7,0 | 2,4% | €150 BTC |
| **€1.200** | ↑ 5 trades, DCA 36 | **5** | 62 | 9 | **36** | 1,8% | **6,5** | 2,4% | €150 BTC |
| **€1.300** | ↑ BASE 68 | 5 | **68** | 9 | 36 | 1,7% | 6,5 | 2,3% | €150 BTC |
| **€1.400** | ↑ Grid ETH erbij (€250 tot.) | 5 | 68 | 9 | 36 | 1,7% | 6,5 | 2,3% | **€250 BTC+ETH** |
| **€1.500** | ↑ BASE 75, DCA 40 | 5 | **75** | 9 | **40** | 1,7% | 6,5 | 2,3% | €250 |
| **€1.600** | ↑ 6 trades | **6** | 75 | 9 | 40 | 1,7% | 6,5 | 2,3% | €250 |
| **€1.700** | ↑ BASE 80, DCA 44 | 6 | **80** | 9 | **44** | 1,6% | 6,5 | 2,2% | €250 |
| **€1.800** | ↑ Grid SOL erbij (€400 tot.) | 6 | 80 | 9 | 44 | 1,6% | 6,5 | 2,2% | **€400 3 mktn** |
| **€1.900** | ↑ BASE 85 | 6 | **85** | 9 | 44 | 1,6% | 6,5 | 2,2% | €400 |
| **€2.000** | ↑ 7 trades, DCA 10 levels | **7** | 85 | **10** | 44 | 1,6% | 6,5 | 2,2% | €400 |
| **€2.200** | ↑ BASE 95, DCA 50 | 7 | **95** | 10 | **50** | 1,5% | 6,5 | 2,1% | €400 |
| **€2.400** | ↑ Grid 4 mktn (€600 tot.) | 7 | 95 | 10 | 50 | 1,5% | 6,5 | 2,1% | **€600 4 mktn** |
| **€2.600** | ↑ BASE 105, DCA 55 | 7 | **105** | 10 | **55** | 1,5% | 6,0 | 2,1% | €600 |
| **€2.800** | ↑ 8 trades | **8** | 105 | 10 | 55 | 1,5% | 6,0 | 2,0% | €600 |
| **€3.000** | ↑ BASE 115, Grid 5 mktn (€800) | 8 | **115** | 10 | **60** | 1,4% | 6,0 | 2,0% | **€800 5 mktn** |
| **€3.500** | ↑ BASE 130, DCA 70, Grid €1.000 | 8 | **130** | 10 | **70** | 1,4% | 6,0 | 2,0% | **€1.000 5 mktn** |
| **€4.000** | ↑ 9 trades, BASE 145, Grid 6 mktn | **9** | **145** | 10 | **75** | 1,3% | 6,0 | 1,9% | **€1.400 6 mktn** |
| **€4.500** | ↑ BASE 155, DCA 85 | 9 | **155** | **11** | **85** | 1,3% | 6,0 | 1,9% | €1.400 |
| **€5.000** | ↑ 10 trades, Grid €2.000 | **10** | **160** | **12** | **90** | 1,2% | 6,0 | 1,8% | **€2.000 8 mktn** |

---

## Gedetailleerde Mijlpalen

### 🟢 NU — €465 (Huidige Config)

> De bot draait stabiel. Bugs zijn gefixt. Focus: consistent winst maken.

**Geen wijzigingen aan config.** Huidige settings zijn correct voor dit niveau.

**Wat je nu doet:**
- ✅ 3 trailing trades (al ingesteld)
- ✅ Grid uit (terecht — te weinig budget)
- ✅ DCA 9 levels actief (goede recovery bij dips)
- 🎯 Wacht tot portfolio stabiel boven €500 voor 2 weken

**Budget check:**
- Typische blootstelling (3 trades, gem. 2 DCA): 3 × (38 + 2×30) = **€294**
- Worst case (3 trades, 9 DCA elk): 3 × 312 = **€936** (gebeurt nooit tegelijk)
- EUR buffer bij typische load: €465 − €294 = **€171 vrij** ✅

**Verwacht**: €14/week trailing + €25/week storting = ~€39/week groei → **€500 in ~1 week**

---

### 📍 €600 — Eerste Verhoging

> **Trigger**: Portfolio ≥ €600 gedurende 2 weken. Winrate ≥ 50%.

**Wijziging**: BASE_AMOUNT_EUR **38 → 42** (+€4)

```json
{ "BASE_AMOUNT_EUR": 42 }
```

**Waarom alleen BASE?** Meer winst per succesvolle trade, zonder extra risicospreiding. €4 extra per trade = +10% meer euro per win.

**Budget check:**
- Typisch: 3 × (42 + 2×30) = **€306** → buffer €294 ✅
- EUR buffer 15% vereist: €600 × 0,15 = €90 → ruim gehaald ✅

---

### 📍 €700 — Posities Vergroten

> **Trigger**: Portfolio ≥ €700 gedurende 2 weken.

**Wijzigingen**: BASE **42 → 48**, DCA_AMOUNT **30,40 → 32**, DCA_DROP **2,0% → 1,9%**

```json
{
  "BASE_AMOUNT_EUR": 48,
  "DCA_AMOUNT_EUR": 32,
  "DCA_DROP_PCT": 0.019
}
```

**Waarom DCA_DROP iets omlaag?** Bij grotere posities wil je dat DCA's dichter bij de entry vallen — snellere recovery bij kleine dips.

**Budget check:**
- Typisch: 3 × (48 + 2×32) = **€336** → buffer €364 ✅
- 15% reserve: €700 × 0,15 = €105 ✅

---

### 📍 €800 — Vierde Trade Slot

> **Trigger**: Portfolio ≥ €800 gedurende 2 weken, winrate ≥ 55%.

**Wijzigingen**: MAX_OPEN_TRADES **3 → 4**, BASE **48 → 52**

```json
{
  "MAX_OPEN_TRADES": 4,
  "BASE_AMOUNT_EUR": 52
}
```

**Waarom nu een 4e slot?** Meer gelijktijdige trades = meer kansen. Bij €800 is er genoeg buffer voor 4 posities.

**Budget check:**
- Typisch: 4 × (52 + 2×32) = **€464** → buffer €336 ✅
- Worst case 4 × (52 + 9×32) = **€1.360** (nooit volledig, bot checkt balans)
- 15% reserve: €800 × 0,15 = €120 ✅

---

### 📍 €900 — Posities Verder Verhogen

> **Trigger**: Portfolio ≥ €900, 4e slot werkt soepel.

**Wijzigingen**: BASE **52 → 56**, DCA_AMOUNT **32 → 34**, DCA_DROP **1,9% → 1,8%**, TRAILING **2,5% → 2,4%**

```json
{
  "BASE_AMOUNT_EUR": 56,
  "DCA_AMOUNT_EUR": 34,
  "DCA_DROP_PCT": 0.018,
  "DEFAULT_TRAILING": 0.024
}
```

**Waarom trailing naar 2,4%?** Bij grotere posities wil je winst iets sneller vastzetten — €56 × 2,4% = €1,34 activatie vs €38 × 2,5% = €0,95 eerder. Proportioneel dezelfde uitkomst.

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
- Trailing: 4 slots typisch 4 × (56 + 2×34) = **€496** → vrij: €1.000 − 150 − 496 = **€354** ✅

---

### 📍 €1.200 — Vijfde Trade Slot

> **Trigger**: Portfolio ≥ €1.200, grid BTC draait ≥ 4 weken, ≥ 3 completed cycles.

**Wijzigingen**: MAX_OPEN_TRADES **4 → 5**, DCA_AMOUNT **34 → 36**, MIN_SCORE **7,0 → 6,5**

```json
{
  "MAX_OPEN_TRADES": 5,
  "DCA_AMOUNT_EUR": 36,
  "MIN_SCORE_TO_BUY": 6.5
}
```

**Waarom MIN_SCORE omlaag?** Met 5 slots wil je iets meer trades — 6,5 laat de goede B-kwaliteit setups ook toe.

**Worst case check:**
- Grid: €150 + Trailing 5 × (62 + 9×36) = 5 × €386 = €1.930 max → ver boven portfolio
- **Realistisch**: 5 × (62 + 2×36) = **€670** trailing + €150 grid = €820 → buffer €380 ✅

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
- Trailing: 6 × (75 + 2×40) = **€930** typisch → buffer: €1.600 − 250 − 930 = **€420** ✅

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

### ⭐ €2.000 — Zevende Slot + DCA 10 Levels

> **Trigger**: Portfolio ≥ €2.000 voor 4 weken. Grote mijlpaal!

**Wijzigingen**: MAX_OPEN_TRADES **6 → 7**, DCA_MAX_BUYS **9 → 10**

```json
{
  "MAX_OPEN_TRADES": 7,
  "DCA_MAX_BUYS": 10,
  "DCA_DROP_PCT": 0.016
}
```

**Waarom nu pas DCA 10?** Meer DCA levels = meer kapitaal nodig per trade bij drawdown. Bij €2.000 is er genoeg buffer om dieper te DCA'en.

**Budget check:**
- Grid: €400
- Trailing: 7 × (85 + 3×44) = **€1.519** realistisch (gem. 3 DCA) → buffer: €2.000 − 400 − 1.519 = **€81** ⚠️ krap
- Maar: niet alle 7 slots zitten tegelijk in 3 DCA → typisch 7 × (85 + 1×44) = **€903** → buffer €697 ✅

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

**Wijzigingen**: MAX_OPEN_TRADES **7 → 8**, BASE **105 → 115**, Grid €800 met 5 markten

```json
{
  "MAX_OPEN_TRADES": 8,
  "BASE_AMOUNT_EUR": 115,
  "DCA_AMOUNT_EUR": 60,
  "DCA_DROP_PCT": 0.014,
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

**Verwachte opbrengst bij €3.000:**
- Trailing: 8 slots × ~€2,50/trade × ~2 trades/dag = **€4/dag**
- Grid: €800 budget × ~0,08%/dag = **€0,64/dag**
- **Totaal**: ~€4,60/dag → **€32/week** → **€140/maand**

---

### 📍 €3.500 — Posities Opschalen

```json
{
  "BASE_AMOUNT_EUR": 130,
  "DCA_AMOUNT_EUR": 70,
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
  "DCA_AMOUNT_EUR": 75,
  "DEFAULT_TRAILING": 0.019,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "SOL-EUR", "ADA-EUR", "DOT-EUR", "LINK-EUR"],
    "investment_per_grid": 235,
    "max_total_investment": 1400
  }
}
```

---

### 📍 €4.500 — DCA 11 Levels

```json
{
  "BASE_AMOUNT_EUR": 155,
  "DCA_MAX_BUYS": 11,
  "DCA_AMOUNT_EUR": 85
}
```

---

### 🏆 €5.000 — Einddoel: Passief Inkomen

> **Portfolio machine.** Bot draait zichzelf. Stortingen niet meer nodig.

```json
{
  "MAX_OPEN_TRADES": 10,
  "BASE_AMOUNT_EUR": 160,
  "DCA_MAX_BUYS": 12,
  "DCA_AMOUNT_EUR": 90,
  "DCA_DROP_PCT": 0.012,
  "MIN_SCORE_TO_BUY": 6.0,
  "DEFAULT_TRAILING": 0.018,
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
  "DCA_MAX_BUYS": 5,
  "DCA_AMOUNT_EUR": 20,
  "MIN_SCORE_TO_BUY": 8.0,
  "GRID_TRADING": { "enabled": false }
}
```
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
- **DCA_MAX > 10 onder €2.000** — te veel kapitaal opgesloten bij drawdown
- **MIN_SCORE onder 6.0** — te veel noise trades
- **Meerdere dingen tegelijk wijzigen** — onduidelijk wat werkt en wat niet
- **Trailing onder 1,8%** — te veel vroegtijdige exits bij normale volatiliteit

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
- [x] €700 — BASE → 48, DCA → 32, DCA_DROP → 1,9% (23 maart 2026)
- [ ] €800 — 4 trades, BASE → 52
- [ ] €900 — BASE → 56, DCA → 34, trailing → 2,4%
- [ ] €1.000 ⭐ — Grid BTC aan (€150)
- [ ] €1.100 — BASE → 62
- [ ] €1.200 — 5 trades, MIN_SCORE → 6,5
- [ ] €1.300 — BASE → 68
- [ ] €1.400 — Grid ETH erbij (€250 totaal)
- [ ] €1.500 — BASE → 75, DCA → 40
- [ ] €1.600 — 6 trades
- [ ] €1.700 — BASE → 80, DCA → 44
- [ ] €1.800 — Grid SOL erbij (€400 totaal)
- [ ] €1.900 — BASE → 85
- [ ] €2.000 ⭐ — 7 trades, DCA 10 levels
- [ ] €2.200 — BASE → 95, DCA → 50
- [ ] €2.400 — Grid 4 markten (€600)
- [ ] €2.600 — BASE → 105, DCA → 55
- [ ] €2.800 — 8 trades
- [ ] €3.000 ⭐ — Grid 5 markten (€800), stortingen optioneel
- [ ] €3.500 — BASE → 130, DCA → 70, Grid €1.000
- [ ] €4.000 — 9 trades, Grid 6 markten (€1.400)
- [ ] €4.500 — DCA 11 levels, BASE → 155
- [ ] €5.000 🏆 — 10 trades, DCA 12, Grid €2.000, passief inkomen

---

*Laatste update: 23 maart 2026 — Portfolio ~€738, €700 milestone config actief*
*Config: BASE=48, DCA=32, DCA_DROP=1.9%, 3 slots, grid uit*
*Volgende mijlpaal: €800 (4 trades, BASE → 52) — wacht 2 weken stabilisatie*
