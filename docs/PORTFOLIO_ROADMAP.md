# Portfolio Scaling Roadmap — Cascading DCA

**Datum:** 6 maart 2026  
**Versie:** 3.0 — Cascading DCA Edition  
**Simulator:** `scripts/dca_cascade_simulator.py`

## Strategie: Cascading DCA

Elke trade bouwt een **afnemende DCA-ladder**: de eerste bijkoop is het grootst, elke volgende 20% kleiner. Dit beperkt het risico in diepe dips maar houdt het kapitaal beschikbaar bij normaal herstel.

**Kernformule:**
```
Per trade = BASE × (1 + scale × (1 - scale^N) / (1 - scale))
         ≈ BASE × 4.475   (bij scale=0.8, N=9)
         = BASE × cascade_multiplier

Total = MAX_TRADES × BASE × cascade_multiplier ≤ trail_budget
```

**DCA-ladder voorbeeld (BASE=€38):**

| Level | Drop | Bedrag | Cumulatief |
|-------|------|--------|------------|
| Entry | 0% | €38.00 | €38.00 |
| DCA1 | -2% | €30.40 | €68.40 |
| DCA2 | -4% | €24.32 | €92.72 |
| DCA3 | -6% | €19.46 | €112.18 |
| DCA4 | -8% | €15.56 | €127.74 |
| DCA5 | -10% | €12.45 | €140.19 |
| DCA6 | -12% | €9.96 | €150.15 |
| DCA7 | -14% | €7.97 | €158.12 |
| DCA8 | -16% | €6.38 | €164.50 |
| DCA9 | -18% | €5.10 | €169.60 |

> Alle DCA-bedragen schalen lineair mee als BASE verhoogd wordt.

## Uitgangspunten

- **Startportfolio:** €461 (maart 2026)
- **Maandelijkse storting:** €100
- **Reserve:** 0% — alles wordt ingezet
- **Grid bot:** ALTIJD AAN — 2 grids (BTC+ETH), 25% van portfolio
- **Budget verdeling:** 25% grid / 75% trailing
- **Reinvest:** AAN — BASE groeit automatisch mee
- **Cascade params:** scale=0.8, 9 DCA levels, 2% drop per level
- **Trailing:** 1.5% activatie, stepped tightening (2.5% → 0.3%)
- **Stop-loss:** UIT — trailing only
- **Min DCA bedrag:** €5 (Bitvavo minimum)

## Hoe werkt het schalen?

Bij cascading DCA hoef je slechts **2 parameters** aan te passen:
1. **BASE_AMOUNT_EUR** → hele DCA-ladder schaalt automatisch mee
2. **MAX_OPEN_TRADES** → meer parallelle trades

De DCA-structuur (9 levels, scale=0.8, 2% gap) blijft **altijd gelijk**. Dat is het voordeel van cascading DCA: eenvoudig schalen zonder 5 parameters te tweaken.

**Constraint:** kleinste DCA = BASE × 0.8⁹ = BASE × 0.134 ≥ €5 → BASE ≥ €37.3

---

## Quick Reference

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% |
|-----------|------|--------|-----------|--------------|--------------|-------|
| **€461** | **€38** | **2** | €170 | €340 | €346 | **98%** |
| **€600** | **€40** | **2** | €179 | €358 | €450 | 80% |
| **€800** | **€45** | **3** | €201 | €604 | €600 | ~100% |
| **€1.000** | **€50** | **3** | €224 | €671 | €750 | 89% |
| **€1.200** | **€50** | **4** | €224 | €894 | €900 | 99% |
| **€1.500** | **€55** | **4** | €246 | €984 | €1.125 | 88% |
| **€2.000** | **€65** | **5** | €291 | €1.454 | €1.500 | 97% |
| **€3.000** | **€75** | **7** | €336 | €2.349 | €2.250 | ~100% |
| **€4.000** | **€85** | **8** | €380 | €3.042 | €3.000 | ~100% |
| **€5.000** | **€90** | **9** | €403 | €3.625 | €3.750 | 97% |

> Grid/grid = portfolio × 25% / 2 (automatisch)

---

## Gedetailleerde fases

### Fase 1: Overleven (€461 – €700)

**Focus:** Bewijs dat cascading DCA werkt. Klein beginnen, compound effect opbouwen.

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% | Grid/grid |
|-----------|------|--------|-----------|--------------|--------------|-------|-----------|
| €461 | €38 | 2 | €170 | €340 | €346 | 98% | €58 |
| €500 | €38 | 2 | €170 | €340 | €375 | 91% | €63 |
| €600 | €40 | 2 | €179 | €358 | €450 | 80% | €75 |
| €700 | €42 | 3 | €188 | €564 | €525 | ⚠️107% | €88 |

**Opmerking:** Bij €700 past 3 trades net niet (107%). Oplossing: of 2 trades houden met BASE=€50 (util=89%), of BASE=€39 voor 3 trades (util=100%). Keuze hangt af van marktcondities.

**Wijzigingen t.o.v. start:**
- Bij €600: `BASE_AMOUNT_EUR` → 40
- Bij €700: `MAX_OPEN_TRADES` → 3, `BASE_AMOUNT_EUR` → 39 OF houd 2 trades met BASE=50

### Fase 2: Stabiliseren (€800 – €1.100)

**Focus:** 3 trades draaien, stabiele winsten. Eerste keer compound effect zichtbaar.

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% | Grid/grid |
|-----------|------|--------|-----------|--------------|--------------|-------|-----------|
| €800 | €45 | 3 | €201 | €604 | €600 | ~100% | €100 |
| €900 | €45 | 3 | €201 | €604 | €675 | 89% | €113 |
| €1.000 | €50 | 3 | €224 | €671 | €750 | 89% | €125 |
| €1.100 | €50 | 4 | €224 | €894 | €825 | ⚠️108% | €138 |

**Opmerking:** Bij €1.100 past 4 trades net niet. Houd 3 trades tot €1.200.

**Wijzigingen:**
- Bij €800: `BASE_AMOUNT_EUR` → 45
- Bij €1.000: `BASE_AMOUNT_EUR` → 50

### Fase 3: Groeien (€1.200 – €2.000)

**Focus:** 4-5 trades, serieuze diversificatie. Bot begint zichzelf te bewijzen.

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% | Grid/grid |
|-----------|------|--------|-----------|--------------|--------------|-------|-----------|
| €1.200 | €50 | 4 | €224 | €894 | €900 | 99% | €150 |
| €1.300 | €50 | 4 | €224 | €894 | €975 | 92% | €163 |
| €1.500 | €55 | 4 | €246 | €984 | €1.125 | 88% | €188 |
| €1.700 | €60 | 5 | €268 | €1.342 | €1.275 | ⚠️105% | €213 |
| €1.800 | €60 | 5 | €268 | €1.342 | €1.350 | 99% | €225 |
| €2.000 | €65 | 5 | €291 | €1.454 | €1.500 | 97% | €250 |

**Wijzigingen:**
- Bij €1.200: `MAX_OPEN_TRADES` → 4
- Bij €1.500: `BASE_AMOUNT_EUR` → 55
- Bij €1.800: `MAX_OPEN_TRADES` → 5, `BASE_AMOUNT_EUR` → 60
- Bij €2.000: `BASE_AMOUNT_EUR` → 65

### Fase 4: Schalen (€2.000 – €3.000)

**Focus:** 5-7 trades, grote posities. DCA-ladder is krachtig genoeg voor stevige correcties.

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% | Grid/grid |
|-----------|------|--------|-----------|--------------|--------------|-------|-----------|
| €2.000 | €65 | 5 | €291 | €1.454 | €1.500 | 97% | €250 |
| €2.200 | €65 | 6 | €291 | €1.745 | €1.650 | ⚠️106% | €275 |
| €2.300 | €65 | 6 | €291 | €1.745 | €1.725 | ~100% | €288 |
| €2.500 | €70 | 6 | €313 | €1.880 | €1.875 | ~100% | €313 |
| €2.800 | €70 | 7 | €313 | €2.193 | €2.100 | ⚠️104% | €350 |
| €3.000 | €75 | 7 | €336 | €2.349 | €2.250 | ⚠️104% | €375 |

**Opmerking:** Bij deze bedragen raakt util% soms net boven 100%. Dit is acceptabel omdat:
1. Niet alle trades tegelijk op DCA9 zitten
2. Gemiddeld DCA-gebruik is 2.3 levels (Monte Carlo)
3. Effectieve exposure is ~50-60% van theoretisch maximum

**Wijzigingen:**
- Bij €2.300: `MAX_OPEN_TRADES` → 6
- Bij €2.500: `BASE_AMOUNT_EUR` → 70
- Bij €2.800: `MAX_OPEN_TRADES` → 7
- Bij €3.000: `BASE_AMOUNT_EUR` → 75

### Fase 5: Professioneel (€3.000 – €5.000)

**Focus:** 7-9 trades, maximale diversificatie. Klein DCA als % van portfolio.

| Portfolio | BASE | Trades | Per trade | Max Exposure | Trail Budget | Util% | Grid/grid |
|-----------|------|--------|-----------|--------------|--------------|-------|-----------|
| €3.000 | €75 | 7 | €336 | €2.349 | €2.250 | ~100% | €375 |
| €3.500 | €80 | 7 | €358 | €2.505 | €2.625 | 95% | €438 |
| €4.000 | €85 | 8 | €380 | €3.042 | €3.000 | ~100% | €500 |
| €4.500 | €85 | 9 | €380 | €3.423 | €3.375 | ~100% | €563 |
| €5.000 | €90 | 9 | €403 | €3.625 | €3.750 | 97% | €625 |

**Doel bij €5.000:**
- 9 trailing trades × €403 = €3.625 in trailing DCA
- 2 grids × €625 = €1.250 in grid
- Totaal: €4.875 werkend kapitaal (98% van portfolio)
- Kleinste DCA (level 9): €12.06 — ruim boven Bitvavo minimum

**Wijzigingen:**
- Bij €3.500: `BASE_AMOUNT_EUR` → 80
- Bij €4.000: `BASE_AMOUNT_EUR` → 85, `MAX_OPEN_TRADES` → 8
- Bij €4.500: `MAX_OPEN_TRADES` → 9
- Bij €5.000: `BASE_AMOUNT_EUR` → 90

---

## Risico per fase

| Fase | Max verlies 1 trade | Max verlies ALLE trades | Als % portfolio |
|------|--------------------|-----------------------|-----------------|
| 1 (€461) | €170 | €340 | 74% |
| 2 (€800) | €201 | €604 | 75% |
| 3 (€1.500) | €246 | €984 | 66% |
| 4 (€2.500) | €313 | €1.880 | 75% |
| 5 (€5.000) | €403 | €3.625 | 73% |

> **Worst case = alle open trades naar DCA9 en nooit herstellen.** Dit is een extreme crash-scenario (>18% op alle coins tegelijk). Historisch komt dit ~2× per jaar voor in crypto.

---

## Wanneer opschalen?

**Schaal op wanneer:**
1. Portfolio bereikt volgende stap (door stortingen + reinvest)
2. Bot is minstens 2 weken stabiel
3. Win rate > 60% over laatste 30 trades (cascading DCA target)

**Schaal NIET op wanneer:**
- Portfolio is gegroeid door unrealized gains
- Markt is extreem volatiel (>8% BTC swing in 24u)
- Er zijn onopgeloste errors in de logs

---

## Config wijzigingen per stap

Bij opschaling wijzig je in `bot_config_overrides.json`:

```json
{
  "BASE_AMOUNT_EUR": <zie tabel>,
  "MAX_OPEN_TRADES": <zie tabel>
}
```

**Dat is alles.** De DCA-ladder schaalt automatisch:
- `DCA_AMOUNT_EUR` = BASE × 0.8 (automatisch uit `DCA_AMOUNT_RATIO`)
- Alle 9 levels schalen proportioneel
- Grid schaalt automatisch (25% van portfolio)

Parameters die **NOOIT** wijzigen:
- `DCA_MAX_BUYS` = 9
- `DCA_SIZE_MULTIPLIER` = 0.8
- `DCA_DROP_PCT` = 0.02
- `DCA_STEP_MULTIPLIER` = 1.0
- `EXIT_MODE` = "trailing_only"
- `TRAILING_ACTIVATION_PCT` = 0.015
- `DEFAULT_TRAILING` = 0.025

---

## Monte Carlo validatie (10.000 simulaties, 30 dagen)

Resultaten met huidige config (BASE=€38, 2 trades):

| Metriek | Waarde |
|---------|--------|
| Win rate | 99.6% |
| Gem. profit/trade | €+2.20 |
| Mediaan profit/trade | €+1.99 |
| Gem. ROI/trade | +3.18% |
| Gem. DCA levels gebruikt | 2.3 van 9 |
| Worst case single trade | -€95.70 |
| Trailing exits | 99.6% (0.4% nog open na 30d) |

**DCA-level verdeling:**
- 40% trades: geen DCA nodig (snelle bounce)
- 15% trades: 1 DCA level
- 11% trades: 2 DCA levels
- 8% trades: 3 levels
- Slechts 7% triggers alle 9 levels

> Run `python scripts/dca_cascade_simulator.py` voor actuele simulatie.

---

## Timeline

**Aannames:** Start €461, +€100/maand storting, cascading DCA rendement.

| Milestone | 0% rendement | 2%/mnd | 3%/mnd |
|-----------|-------------|--------|--------|
| **€600** | Jun 2026 | Jun 2026 | Mei 2026 |
| **€800** | Aug 2026 | Jul 2026 | Jul 2026 |
| **€1.000** | Okt 2026 | Sep 2026 | Aug 2026 |
| **€1.500** | Mrt 2027 | Dec 2026 | Nov 2026 |
| **€2.000** | Aug 2027 | Apr 2027 | Mrt 2027 |
| **€3.000** | Jun 2028 | Okt 2027 | Aug 2027 |
| **€5.000** | Feb 2030 | Sep 2028 | Apr 2028 |

---

## Kernprincipes

1. **Alleen BASE en MAX_TRADES wijzigen** — DCA-structuur blijft altijd gelijk
2. **Scale factor = 0.8** — afnemende DCA beschermt tegen overinvestering in dips
3. **9 levels, 2% gap** — optimaal voor alt-coins (18% drawdown dekking)
4. **Exposure ≤ ~100% trail budget** — in praktijk ~50-60% door gemiddeld 2.3 DCA levels
5. **Grid altijd aan** — 2 grids op BTC+ETH, 25% van budget
6. **Reserve = 0%** — maximale inzet
7. **Trailing only** — geen stop-loss, laat DCA het werk doen
