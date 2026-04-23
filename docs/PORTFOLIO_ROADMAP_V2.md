# Bitvavo Bot — Portfolio Roadmap V2

> **Doel**: Agressiever opschaalplan gebaseerd op **data-driven analyse** van 938 historische trades.
> V1 was te conservatief — 97% van trades kreeg geen DCA, 60% van kapitaal zat ongebruikt in cash.
> V2 maximaliseer kapitaalefficiëntie: hogere BASE orders, minder slots, bewezen DCA-limieten.
>
> **Update 23 april 2026 (V2.1)** — Portfolio €1.450 milestone toegevoegd met drie nieuwe edge-componenten:
> position size floor + per-market EV-sizing (empirical-Bayes) + tighter trailing.
> Backtest op 159 trades sinds 1 maart 2026: **+134% projected PnL improvement**.

---

## Waarom V2? Data-Driven Inzichten (april 2026)

Analyse van alle 584 echte trades + 68 trades uit de laatste 6 weken onthulde:

| Inzicht | Data | Impact |
|---------|------|--------|
| **97% trades krijgt GEEN DCA** | 564/584 trades = 0 DCA buys | DCA worst-case berekeningen waren irrelevant |
| **Werkelijke exposure = BASE × TRADES** | Niet de DCA-gewogen bedragen | Budget veel ruimer dan gedacht |
| **60% cash deed niets** | EUR 700 van EUR 1.240 ongebruikt | Verloren rendement op idle kapitaal |
| **Trades 50-100 EUR: 100% winrate** | 13 trades, EUR 56 totaal profit | Sweet spot voor bot-trades |
| **Trades < 50 EUR: 52% winrate** | 58 trades, EUR -28 verlies | Kleine trades verliezen geld |
| **Hogere BASE = proportioneel meer winst** | BASE 150 → 2.4x netto EUR | Verliezen schalen mee maar netto is beter |

### Simulatie-uitkomsten (op 68 recente trades)

| Scenario | Netto (6w) | Per week | Per maand |
|----------|-----------|----------|-----------|
| V1: BASE=62, 5 slots | EUR 34 | EUR 5.75 | EUR 25 |
| **V2: BASE=150, 4 slots** | **EUR 83** | **EUR 14** | **EUR 60** |

---

## Prestatie-analyse (bron voor alle berekeningen)

| Metric | Waarde | Bron |
|--------|--------|------|
| **Portfoliowaarde** | €1.240 | balance_history 10-04-2026 |
| **EUR beschikbaar** | €699 | sync_raw_balances |
| **In open trades** | €358 | portfolio_snapshot |
| **Grid BTC (in orders)** | €182 | sync_raw_balances |
| **Totaal gestort** | ~€970 | deposits (incl. april) |
| **Maandelijkse storting** | €100 | vast |
| **Trading winst (echt)** | +€859 uit 584 trades | trailing_tp + partial_tp |
| **Winrate (echte trades)** | 72% (laatste 6 weken) | trade_archive.json |
| **Gem. winst per week** | €9.12 (laatste 8 weken) | weekly_profit berekening |
| **Gem. DCA per trade** | 0.2 (mediaan: 0) | 97% krijgt geen DCA |

### Huidige config (werkelijk, 10 april 2026)

> **Roadmap V2 geactiveerd op 10-04-2026.** Sprong van BASE 62 → 150, MAX_TRADES 5 → 4, DCA_MAX_BUYS 17 → 6.
> Grid BTC actief sinds 07-04-2026.

```json
{
  "MAX_OPEN_TRADES": 4,
  "BASE_AMOUNT_EUR": 150,
  "DCA_MAX_BUYS": 6,
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
    "num_grids": 5
  },
  "BUDGET_RESERVATION": { "grid_pct": 15, "trailing_pct": 85 }
}
```

**DCA-bedragen per level (0.9x)**: €30 → €27 → €24,30 → €21,87 → €19,68 → €17,72 (level 6)
**Realistische blootstelling (97% geen DCA)**: 4 × €150 = **€600** (puur base)
**Typische blootstelling** (3% kans, 2 DCA): 4 × (150 + 30 + 27) = **€828**
**Grid BTC**: €182 gereserveerd
**Worst case** (6 DCA): 4 × (150 + 141) = **€1.162** → buffer €78 (krap maar beheersbaar)
**Buffer bij realistische load**: €1.240 − 182 − 600 = **€458 vrij (37%)** ✅

---

## Gouden Regels (V2)

1. **Minimaal 2 weken evalueren** na elke config-wijziging
2. **Winrate check**: moet ≥ 60% zijn over laatste 2 weken (hogere drempel bij hogere BASE)
3. **EUR buffer**: houd ALTIJD minimaal **20% van portfoliowaarde** vrij (strenger dan V1 i.v.m. grotere posities)
4. **Bij 15% drawdown**: verlaag BASE met 30% en ga naar vorige fase
5. **DCA_MAX_BUYS nooit boven 8** — data toont: meer DCA = geld vastzetten met marginale winst
6. **Grid pas uitbreiden bij bewezen positieve PnL** op bestaande grids
7. **MAX_TRADES verhogen = BASE verlagen** — nooit beide tegelijk omhoog

---

## Stortingsplan (V2 — Versneld)

| Maand | Storting | Trading (est.) | Geschatte portfolio* |
|-------|----------|---------------|---------------------|
| Apr 2026 | €100 | €60 | €1.300 (V2 start) |
| Mei 2026 | €100 | €60 | €1.460 |
| Jun 2026 | €100 | €70 | €1.630 |
| Jul 2026 | €100 | €80 | €1.810 |
| Aug 2026 | €100 | €90 | €2.000 ⭐ |
| Sep 2026 | €50 | €100 | €2.150 |
| Okt 2026 | €50 | €110 | €2.310 |
| Nov 2026 | €0 | €120 | €2.430 |
| Dec 2026 | €0 | €130 | €2.560 |

*\* Gebaseerd op ~€14/week bij BASE=150, stijgend bij opschaling. Bij €2.000+ stopt storting.*

> **V2 is ~3 maanden sneller** naar €2.000 dan V1 dankzij hogere BASE en betere kapitaalbenutting.

---

## Overzicht per Mijlpaal (V2)

**Kernfilosofie V2**: Hogere BASE, minder slots, DCA beperkt tot max 6-8 levels.
**DCA_SIZE_MULTIPLIER = 0.9** op alle niveaus.

| Portfolio | Actie | MAX_TRADES | BASE | DCA_AMT | DCA_MAX | TRAILING | Grid |
|-----------|-------|------------|------|---------|---------|----------|------|
| **≤€1.000** ✅ | *V1 bereikt — Grid BTC aan* | 4 | 56 | 28 | 17 | 2,4% | €150 BTC |
| **€1.200** ✅ | *V1: 5 trades, BASE 62* | 5 | 62 | 30 | 17 | 2,4% | €150 BTC |
| **€1.240** ✅ | *V2 START: BASE 150, 4 trades* | 4 | 150 | 30 | 6 | 2,4% | €150 BTC |
| **€1.450** ← nu | **V2.1: Size-floor + EV-sizing + tighter trailing** | **4** | **120** | **30** | **3** | **2,2% / act 2,5%** | UIT |
| **€1.500** | ↑ Grid +ETH (€250 totaal) | 4 | 150 | 30 | 6 | 2,4% | **€250 BTC+ETH** |
| **€1.800** | ↑ 5 trades, BASE 160, DCA 35 | **5** | **160** | **35** | **6** | 2,3% | €250 |
| **€2.200** | ↑ BASE 180, DCA 40, Grid +LINK | 5 | **180** | **40** | **6** | 2,3% | **€400 3 mktn** |
| **€2.700** | ↑ 6 trades, BASE 200, DCA 45 | **6** | **200** | **45** | **8** | 2,2% | **€500 3 mktn** |
| **€3.500** | ↑ 7 trades, BASE 220, DCA 50, +XRP | **7** | **220** | **50** | **8** | 2,0% | **€700 4 mktn** |
| **€4.500** | ↑ 8 trades, BASE 250, DCA 55 | **8** | **250** | **55** | **8** | 2,0% | **€1.000 5 mktn** |
| **€6.000** | ↑ BASE 300, DCA 60, +AVAX | 8 | **300** | **60** | **8** | 2,0% | **€1.500 6 mktn** |

---

## Gedetailleerde Mijlpalen (V2)

### Geschiedenis (V1 mijlpalen)

> De volgende mijlpalen zijn bereikt onder V1 en behouden als historisch referentie.

- ✅ **€465** — Start (11 maart 2026)
- ✅ **€500** — Stabiel draaien (18 maart 2026)
- ✅ **€600** — Overgeslagen (direct naar €700)
- ✅ **€700** — DCA geoptimaliseerd: Hybrid F_CONSERVATIEF (26 maart 2026)
- ✅ **€800** — 4 trades, BASE 52, DCA 27 (3 april 2026)
- ✅ **€900** — Overgeslagen (meegenomen in €1.000)
- ✅ **€1.000** — Grid BTC aan, €150 budget (7 april 2026)
- ✅ **€1.100** — BASE 62, DCA 30 (8 april 2026)
- ✅ **€1.200** — 5 trades (V1 milestone, 9 april 2026)

---

### ⭐ €1.240 — V2 START: Data-Driven Opschaling (GEACTIVEERD)

> **Geactiveerd**: 10 april 2026. Strategiewijziging op basis van simulatie.
> Sprong van BASE 62 → 150, MAX_TRADES 5 → 4, DCA_MAX_BUYS 17 → 6.

**Reden voor de switch:**
- 97% van trades kreeg nooit DCA — worst-case berekeningen waren overbodig
- Trades < €50 verloren geld (52% winrate), trades €50-100 hadden 100% winrate
- EUR 700 cash zat ongebruikt — kapitaalefficiëntie was slechts 29%
- Simulatie op 68 recente trades: BASE=150 levert €14/week vs €5.75/week

**Wijzigingen:**

```json
{
  "BASE_AMOUNT_EUR": 150,
  "MAX_OPEN_TRADES": 4,
  "DCA_MAX_BUYS": 6,
  "DCA_MAX_ORDERS": 6,
  "AVELLANEDA_STOIKOV_GRID": false
}
```

> **A-S grid uit**: Bij €184 budget en 5 levels berekent A-S een 5% spread → levels te ver van prijs.
> Arithmetic spacing geeft strakke, voorspelbare levels (1,5% stap). Weer aan bij €1.500 (meer budget).

**Budget check (realiteit: 97% geen DCA):**
- Alle slots vol, puur base: 4 × 150 = **€600**
- Grid: €182
- **Buffer: €458 (37%)** ✅ (ruim boven 20% regel)

**Verwachte opbrengst:** ~€14/week → **~€60/maand**

**Evaluatie na 2 weken (24 april 2026):**
- [ ] Winrate ≥ 60%?
- [ ] Geen enkele trade > €50 verlies?
- [ ] Portfolio ≥ €1.300?
- [ ] Gemiddelde profit per trade ≥ €1,50?

---

### ⭐ €1.450 — V2.1: Size-Floor + Per-Market EV-Sizing + Strakker Trailing (GEACTIVEERD)

> **Geactiveerd**: 23 april 2026. Datadriven herijking na 159 trades sinds 1 maart 2026.
> Drie nieuwe edge-componenten gewired in `bot/orders_impl.py:place_buy()`:
> 1. **Position size floor** ([bot/sizing_floor.py](bot/sizing_floor.py)) — bumpt tiny posities (<€75) naar de bewezen 75-150 EV-sweet-spot of breekt af bij <€50.
> 2. **Per-market EV-sizing met empirical-Bayes shrinkage** ([core/market_expectancy.py](core/market_expectancy.py)) — schaalt elke koop met 0.3x..1.8x op basis van per-markt expectancy, geseed met 159 historische trades.
> 3. **Score-stamping** in `open_trade_async` zodat het size-floor een high-conviction bypass kan uitvoeren bij score ≥ 14.

**Reden voor de switch (data sinds 1 maart 2026):**
- 159 nettrades, +€116,59 totaal, WR 74,2%, profit factor 7,4, expectancy +€0,73/trade.
- Size-bucket analyse: trades **<€25 verloren −€0,12/trade**, **€25-75 +€0,41**, **€75-150 +€3,34/trade (+2,95% ROI)** — duidelijke sweet-spot.
- Backtest replay: EV-weighted sizing **+55%** (van +€72,31 naar +€111,92 op test-set).
- Profit-lock ratchet replay (33 trades): **+18%** door bestaande `STEPPED_TRAILING_LEVELS` strakker te trekken (config-only, geen nieuwe module nodig).
- Portfolio: €1.450 (was €1.240 bij V2-start). Oude config (BASE=1000, MAX=6, DCA=61x5) was **6× over-leveraged** voor deze portefeuille.

**Wijzigingen (lokale config):**

```json
{
  "BASE_AMOUNT_EUR": 120,
  "MAX_OPEN_TRADES": 4,
  "DCA_AMOUNT_EUR": 30,
  "DCA_MAX_BUYS": 3,
  "DCA_MAX_ORDERS": 3,
  "DEFAULT_TRAILING": 0.022,
  "TRAILING_ACTIVATION_PCT": 0.025,
  "POSITION_SIZE_FLOOR_ENABLED": true,
  "POSITION_SIZE_ABS_MIN_EUR": 75,
  "POSITION_SIZE_SOFT_MIN_EUR": 50,
  "POSITION_SIZE_HIGH_CONVICTION_SCORE": 14,
  "MARKET_EV_SIZING_ENABLED": true
}
```

**Budget check (worst case, alle slots vol + alle DCAs gevuld):**
- Per trade max (zonder EV-boost): 120 + 30×3 = €210
- Alle 4 slots vol: 4 × 210 = **€840 (58%)** ✅ binnen 60%-target
- Met EV-boost (avg 1,3x op winners): ~€700-€900 typisch (48-62%)
- Reserve EUR: ≥ €217 (15%) gegarandeerd via `MIN_BALANCE_EUR` + `MAX_OPEN_TRADES` cap
- Grid: UIT — focus 100% op trailing-bot voor maximale capital-efficiency op deze schaal

**Verwachte opbrengst (geprojecteerd uit backtest):**
- Sim PnL op 123 trades sinds 1 maart 2026: **+€273,24** (vs realiteit +€116,59 = **+134% verbetering**)
- Per week: ~€38-€45 (vs huidige €14,57/week)
- Per maand: ~€160-€190

**Bootstrap stap (eenmalig, al uitgevoerd 23 april):**
```powershell
python scripts/helpers/bootstrap_market_ev.py
```
Schrijft `data/market_expectancy.json` met 159 historische trades. Vanaf dat moment past de bot per koop automatisch een EV-multiplier toe.

**Evaluatie na 2 weken (7 mei 2026):**
- [ ] Geen size-floor reject-rate > 25% (anders SOFT_MIN te hoog)?
- [ ] Avg trade size landt in €75-€150 band?
- [ ] Per-market blacklist activeert correct (geen DOT/LINK forced trades)?
- [ ] WR ≥ 70% en expectancy ≥ €1,00/trade?
- [ ] Portfolio ≥ €1.550?

---

### 📍 €1.500 — Grid Uitbreiden naar ETH + A-S Weer Aan

> **Trigger**: Portfolio ≥ €1.500 stabiel, V2 draait ≥ 3 weken, winrate ≥ 60%.

**Wijziging**: Grid budget omhoog naar €250, ETH erbij, **Avellaneda-Stoikov weer aan** (€250 budget + 2 grids = genoeg levels voor dynamische spacing)

```json
{
  "AVELLANEDA_STOIKOV_GRID": true,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR"],
    "investment_per_grid": 125,
    "max_total_investment": 250,
    "max_grids": 2
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 17,
    "trailing_pct": 83
  }
}
```

**Waarom nu ETH?** Bij €1.500 met €250 grid = €125/markt = €25/level. Minimaal rendabel. ETH heeft iets grotere swings dan BTC = meer grid-cycli.

**Budget check:**
- Grid: €250
- Trailing: 4 × 150 = €600
- **Buffer: €650 (43%)** ✅

---

### ⭐ €1.800 — Vijfde Trade Slot + Opschalen

> **Trigger**: Portfolio ≥ €1.800, grid BTC+ETH positief, V2 ≥ 6 weken stabiel.

**Wijzigingen**: MAX_OPEN_TRADES **4 → 5**, BASE **150 → 160**, DCA **30 → 35**

```json
{
  "MAX_OPEN_TRADES": 5,
  "BASE_AMOUNT_EUR": 160,
  "DCA_AMOUNT_EUR": 35,
  "DEFAULT_TRAILING": 0.023
}
```

**Waarom nu pas 5 slots?** In V2 moet het 5e slot verdient worden — 4 slots met hogere BASE leveren meer op dan 5 slots met lagere BASE. Pas bij €1.800 is er genoeg voor 5 × €160.

**Budget check:**
- Grid: €250
- Trailing: 5 × 160 = €800
- **Buffer: €750 (42%)** ✅

**Verwachte opbrengst:** ~€18/week → **~€77/maand**

---

### 📍 €2.200 — Posities Vergroten + Grid LINK

> **Trigger**: Portfolio ≥ €2.200, 5 slots stabiel ≥ 2 weken.

**Wijzigingen**: BASE **160 → 180**, DCA **35 → 40**, Grid naar 3 markten (€400)

```json
{
  "BASE_AMOUNT_EUR": 180,
  "DCA_AMOUNT_EUR": 40,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR"],
    "investment_per_grid": 133,
    "max_total_investment": 400,
    "max_grids": 3
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 18,
    "trailing_pct": 82
  }
}
```

**Waarom LINK?** Grid-analyse toonde LINK met 90% winrate en +€7,11 PnL — beste grid-candidate na BTC/ETH. Goede mean-reversion, voldoende volume.

**Budget check:**
- Grid: €400
- Trailing: 5 × 180 = €900
- **Buffer: €900 (41%)** ✅

**Verwachte opbrengst:** ~€22/week → **~€95/maand**

---

### ⭐ €2.700 — Zesde Trade Slot

> **Trigger**: Portfolio ≥ €2.700, winrate ≥ 60%, geen week > €100 verlies.

**Wijzigingen**: MAX_OPEN_TRADES **5 → 6**, BASE **180 → 200**, DCA **40 → 45**, DCA_MAX_BUYS **6 → 8**

```json
{
  "MAX_OPEN_TRADES": 6,
  "BASE_AMOUNT_EUR": 200,
  "DCA_AMOUNT_EUR": 45,
  "DCA_MAX_BUYS": 8,
  "DEFAULT_TRAILING": 0.022,
  "GRID_TRADING": {
    "max_total_investment": 500
  }
}
```

**Waarom DCA_MAX_BUYS omhoog naar 8?** Bij BASE=200 is de worst case met 8 DCA: 200 + 237 = €437/slot. Bij 6 slots = €2.622. Buffer = €78 — krap maar dit is het absolute maximum (97% kans: exposure = 6 × 200 = €1.200).

**Budget check (realistisch):**
- Grid: €500
- Trailing: 6 × 200 = €1.200
- **Buffer: €1.000 (37%)** ✅

**Verwachte opbrengst:** ~€30/week → **~€130/maand**

---

### ⭐ €3.500 — Zevende Slot + Grid XRP

> **Trigger**: Portfolio ≥ €3.500, 6 slots ≥ 4 weken stabiel.

**Wijzigingen**: MAX_OPEN_TRADES **6 → 7**, BASE **200 → 220**, DCA **45 → 50**, Grid +XRP (€700)

```json
{
  "MAX_OPEN_TRADES": 7,
  "BASE_AMOUNT_EUR": 220,
  "DCA_AMOUNT_EUR": 50,
  "DEFAULT_TRAILING": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR"],
    "investment_per_grid": 175,
    "max_total_investment": 700,
    "max_grids": 4
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 20,
    "trailing_pct": 80
  }
}
```

**Budget check:**
- Grid: €700
- Trailing: 7 × 220 = €1.540
- **Buffer: €1.260 (36%)** ✅

**Verwachte opbrengst:** ~€40/week → **~€172/maand**

---

### 📍 €4.500 — Achtste Slot

> **Trigger**: Portfolio ≥ €4.500, alle 4 grids positief.

**Wijzigingen**: MAX_OPEN_TRADES **7 → 8**, BASE **220 → 250**, DCA **50 → 55**, Grid +DOT (€1.000)

```json
{
  "MAX_OPEN_TRADES": 8,
  "BASE_AMOUNT_EUR": 250,
  "DCA_AMOUNT_EUR": 55,
  "DCA_DROP_PCT": 0.020,
  "GRID_TRADING": {
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR", "DOT-EUR"],
    "investment_per_grid": 200,
    "max_total_investment": 1000,
    "max_grids": 5
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 22,
    "trailing_pct": 78
  }
}
```

**Budget check:**
- Grid: €1.000
- Trailing: 8 × 250 = €2.000
- **Buffer: €1.500 (33%)** ✅

**Verwachte opbrengst:** ~€55/week → **~€235/maand**

---

### 🏆 €6.000 — Einddoel V2: Passief Inkomen

> **Portfolio machine.** Stortingen gestopt. Puur compounding.
> 6e grid markt: AVAX.

```json
{
  "MAX_OPEN_TRADES": 8,
  "BASE_AMOUNT_EUR": 300,
  "DCA_AMOUNT_EUR": 60,
  "DCA_MAX_BUYS": 8,
  "DCA_DROP_PCT": 0.020,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "MIN_SCORE_TO_BUY": 7.0,
  "DEFAULT_TRAILING": 0.020,
  "TRAILING_ACTIVATION_PCT": 0.015,
  "GRID_TRADING": {
    "enabled": true,
    "preferred_markets": ["BTC-EUR", "ETH-EUR", "LINK-EUR", "XRP-EUR", "DOT-EUR", "AVAX-EUR"],
    "investment_per_grid": 250,
    "max_total_investment": 1500,
    "num_grids": 8,
    "grid_mode": "arithmetic",
    "trailing_tp_enabled": true,
    "volatility_adaptive": true
  },
  "BUDGET_RESERVATION": {
    "grid_pct": 25,
    "trailing_pct": 75
  }
}
```

**Budget check:**
- Grid: €1.500
- Trailing: 8 × 300 = €2.400
- **Buffer: €2.100 (35%)** ✅

**Verwachte opbrengst bij €6.000:**
- Trailing: 8 slots × ~€5/trade × ~2 trades/dag = **€10/dag**
- Grid: €1.500 × ~0,08%/dag = **€1,20/dag**
- **Totaal**: ~€11,20/dag → **€78/week** → **€340/maand**

---

## Bear Market Protocol 🔴 (V2)

> Aangepast voor hogere BASE — grotere posities = sneller ingrijpen.

### Trigger 1: Portfolio daalt 8% in 1 week
**Actie**: Verlaag BASE met 30% (bijv. 150 → 105), verhoog MIN_SCORE met 0,5

### Trigger 2: Portfolio daalt 15% in 2 weken
**Actie**: Ga terug naar 2 mijlpalen eerder + halveer grid budget

### Trigger 3: Portfolio daalt 25%+ (crash)
**Noodconfig:**
```json
{
  "MAX_OPEN_TRADES": 3,
  "BASE_AMOUNT_EUR": 50,
  "DCA_AMOUNT_EUR": 20,
  "DCA_MAX_BUYS": 4,
  "DCA_SIZE_MULTIPLIER": 0.9,
  "DCA_DROP_PCT": 0.030,
  "MIN_SCORE_TO_BUY": 8.0,
  "GRID_TRADING": { "enabled": false }
}
```
> Absolut minimum: 3 × 50 = €150 exposure. Overleef de storm. Wacht.

### Herstelprotocol
1. Na 2 groene weken: terug naar vorige fase BASE
2. Na 4 groene weken: terug naar vorige mijlpaal-config
3. Na 6 groene weken: verder met roadmap

---

## Stortingen Stopzetten?

| Portfolio | Storting | Reden |
|-----------|----------|-------|
| < €1.500 | €100/maand | Bot nog in groeifase |
| €1.500–€2.000 | €100/maand | Versnelt bereiken van €2.000 target |
| €2.000–€2.500 | €50/maand optioneel | Bot verdient ~€100/maand zelf |
| > €2.500 | **Stoppen** | Puur compounding werkt beter |

---

## V1 vs V2 Vergelijking

| Aspect | V1 (conservatief) | V2 (data-driven) |
|--------|-------------------|-------------------|
| BASE bij €1.200 | €62 | **€150** |
| MAX_TRADES bij €1.200 | 5 | **4** |
| DCA_MAX_BUYS | 17 | **6** |
| Worst case per slot | €318 | **€291** |
| Typische exposure | €595 (29% portfolio) | **€600 (48% portfolio)** |
| Buffer | 60% (te veel idle) | **37% (optimaal)** |
| Verwacht/week | €5.75 | **€14** |
| Verwacht/maand | €25 | **€60** |
| Tijd naar €2.000 | Dec 2026 | **Aug 2026** |
| Tijd naar €5.000 | ~2028 | **~Midden 2027** |

---

## Waarschuwingen

### ❌ Nooit doen
- **BASE verhogen als winrate < 55%** — bij hogere BASE zijn verliezen groter
- **DCA_MAX_BUYS boven 8** — data toont: meer DCA = geld vastzetten
- **DCA_DROP onder 2,0%** — te vaak triggeren = geen echte dips bijkopen
- **Grid onder €25/level** — fees vreten marge op
- **MIN_SCORE onder 7.0** — kwaliteitsdrempel is bewezen effectief
- **MAX_TRADES + BASE tegelijk verhogen** — één ding per keer
- **Trailing onder 2,0%** — te vroege exits

### ✅ Altijd doen
- Check winrate elke 2 weken
- Houd 20% van portfolio als EUR reserve (strenger dan V1)
- Na config-wijziging: 2 weken stabilisatie
- Bij verliestrade > €30: analyseer waarom, pas evt. EXCLUDED_MARKETS aan
- Log elke wijziging in git commit

---

## Voortgang Tracker

### V1 Bereikt
- [x] €465 — Start (11 maart 2026)
- [x] €500 — Stabiel (18 maart 2026)
- [x] €700 — DCA optimalisatie (26 maart 2026)
- [x] €800 — 4 trades (3 april 2026)
- [x] €1.000 — Grid BTC aan (7 april 2026)
- [x] €1.100 — BASE 62 (8 april 2026)
- [x] €1.200 — 5 trades, V1 einde (9 april 2026)

### V2 Roadmap
- [x] €1.240 — **V2 START**: BASE 150, 4 trades, DCA max 6 (10 april 2026)
- [x] €1.450 ← nu — **V2.1**: size-floor + per-market EV-sizing + tighter trailing (23 april 2026)
- [ ] €1.500 — Grid +ETH (€250)
- [ ] €1.800 ⭐ — 5 trades, BASE 160, DCA 35
- [ ] €2.200 — BASE 180, DCA 40, Grid +LINK (€400)
- [ ] €2.700 — 6 trades, BASE 200, DCA 45 (DCA max 8)
- [ ] €3.500 ⭐ — 7 trades, BASE 220, DCA 50, Grid +XRP (€700)
- [ ] €4.500 — 8 trades, BASE 250, DCA 55, Grid +DOT (€1.000)
- [ ] €6.000 🏆 — BASE 300, DCA 60, Grid +AVAX (€1.500) — Passief Inkomen
