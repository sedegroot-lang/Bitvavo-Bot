# Alle Strategie-Ideeën — Bitvavo Bot

> Samengesteld 15 april 2026 | Gebaseerd op 1.130 trades, 194 dagen data, 429 Bitvavo markten

---

## Huidige Situatie

| Metric | Waarde |
|--------|--------|
| Portfolio | ~€1.228 totaal |
| Vrij EUR | €401 |
| Grid (BTC) | €184 |
| Open trades | 5 stuks, €655 geïnvesteerd |
| Gescande markten | ~15 van 429 (3.5%) |
| Winrate | 57.1% |
| Avg winst per trade | €2.91 |
| Avg verlies per trade | -€5.61 |
| Netto resultaat | **-€26/week** (-€733 over 194 dagen) |
| DCA gebruik | 3.6% (96.4% trades krijgt 0 DCA) |

---

## Idee 1: Velocity Filter (Bewezen in Backtest)

**Wat**: Blokkeer entry in markten met negatieve rolling 30-dagen P&L. Simpelste verbetering.

**Hoe**:
- Track per-markt P&L over rolling 30 dagen
- Markten met negatief P&L → `MIN_SCORE_TO_BUY + 2` (zachte blokkade)
- BTC en ETH altijd blokkeren voor trailing (grid-fills vervuilen data)

**Backtest resultaat** (794 trades, OOS 60 dagen):
| Strategie | EUR/8 weken | EUR/week |
|-----------|-------------|----------|
| Huidig | -€317 | -€37 |
| Velocity Filter | +€81 | **+€9** |

**Verwachte winst**: +€35-45/week beter dan huidig → netto **+€5 tot +€25/week**

**Implementatietijd**: ~2 uur  
**Risico**: Laag  
**Novelty**: ⭐ (bekende techniek, markt-momentum filter)

---

## Idee 2: ACVO — Adaptive Capital Velocity Optimizer

**Wat**: Velocity filter + dynamische position sizing op basis van momentum.

**Hoe**:
- Rolling 30d P&L per markt (= velocity filter)
- Position size = basis × momentum_multiplier
- Markten met sterk positief momentum → grotere positie
- Markten met negatief momentum → geblokkeerd of minimale positie

**Backtest resultaat** (OOS 60 dagen):
| Strategie | EUR/8 weken | EUR/week |
|-----------|-------------|----------|
| ACVO | +€68 | **+€8** |

**Verwachte winst**: +€5 tot +€30/week  
**Implementatietijd**: ~4 uur  
**Risico**: Laag-Medium  
**Novelty**: ⭐⭐ (momentum sizing is bekend, combinatie met velocity is minder standaard)

**Eerlijkheid**: ACVO is geen revolutionair concept. Het is marktfiltering + momentum sizing met een fancy naam. De grote winst in de backtest kwam grotendeels van het uitsluiten van BTC/ETH (waarschijnlijk grid-fills die als trailing trades in het archief stonden).

---

## Idee 3: Timing Filter (Harde Data)

**Wat**: Vermijd entries op verliestijden. Gebaseerd op analyse van 1.130 echte trades.

**Data uit eigen trades**:
| Periode | Avg profit | Winrate | Trades |
|---------|-----------|---------|--------|
| 00:00-06:00 | **+3.1%** | **80%** | 225 |
| 07:00-12:00 | -0.5% | 49% | 349 |
| **13:00-17:00** | **-7.1%** | **40%** | 308 |
| 18:00-23:00 | -0.6% | 62% | 248 |

**Hoe**:
- Blokkeer entries tussen 13:00-17:00 (of verhoog MIN_SCORE met +3)
- Optioneel: bonus voor nacht-entries (00:00-06:00)

**Verwachte winst**: Als ~27% van trades (308 van 1130) in de verliesperiode vallen met avg -7.1%, en je die vermijdt:
- Vermeden verlies: ~€15-25/week
- Netto: **+€15 tot +€25/week**

**Implementatietijd**: 30 minuten  
**Risico**: Zeer laag (je stopt niet, je wacht alleen)  
**Novelty**: ⭐ (tijd-gebaseerde filtering is oud, maar de specifieke data is uniek voor jouw bot)

---

## Idee 4: Dynamic Market Scanner (DMS)

**Wat**: Scan 100+ markten per cyclus in plaats van ~15. Kies dynamisch de beste markten.

**Feiten**:
- Bitvavo heeft **429 EUR-markten**, 396 met >€1K volume, 124 met >€100K volume
- Bot scant nu ~15 markten = **3.5% van het aanbod**
- Top 40 opportunity-markten zitten GEEN van alle in de bot

**Hoe**:
- Elke 4 uur: haal ticker24h op voor alle markten (1 API call)
- Bereken opportunity score = volatiliteit × √(volume)
- Selecteer top-50 als watchlist
- Roteer watchlist: nieuwe hoge-opportunity markten komen erin, lage gaan eruit
- Signal providers draaien alleen op de actieve watchlist

**Simulatie** (geprojecteerd):
| Markten gescand | EUR/week | EUR/194 dagen |
|-----------------|----------|---------------|
| 15 (huidig) | -€26 | -€733 |
| 30 | +€7 | +€204 |
| 50 | **+€30** | +€825 |
| 100 | +€52 | +€1.443 |

**Verwachte winst**: +€30-55/week (afhankelijk van hoeveel markten, conservatief +€20-35)

**Implementatietijd**: ~1 dag  
**Risico**: Medium (meer markten = meer onbekende coins = meer risico op pump-and-dumps)  
**Novelty**: ⭐⭐ (universe expansion is standaard bij quant funds, maar ongewoon voor retail crypto bots)

**Eerlijkheid**: De projections zijn geschat op basis van "meer keuze = betere selectie". Dit is logisch maar niet bewezen. De winrate-boost van 57%→71% (bij 50 mkts) is een aanname.

---

## Idee 5: Information Cascade Detector (ICD)

**Wat**: Detecteer wanneer een informatiegolf door de crypto-markt rolt en spring in de markten die de golf versterken.

**Hoe**:
- Bereken **Transfer Entropy** (TE) tussen alle marktparen:

$$TE_{X \to Y} = \sum p(y_{t+1}, y_t, x_t) \log \frac{p(y_{t+1} | y_t, x_t)}{p(y_{t+1} | y_t)}$$

- Bouw een directed graph: pijl van A→B als TE boven drempel
- Monitor **graph density** (percolatietheorie): dichtheid > 0.3 = cascade actief
- Identificeer **leaders** (veroorzaken beweging) en **amplifiers** (versterken golf)
- Enter amplifier-markten bij cascade onset

**Real-time resultaat** (15 april 2026, top 50 markten):
- Leaders: LINK, TRUMP, PENGU, HBAR, MON, GALA, RED, TRIA, WLFI, USDC
- Amplifiers: ENJ, AAVE, HYPE, PEPE, ARB, DOGE, NEAR, WIF, FARTCOIN, RENDER
- Huidige graph density: normaal (geen actieve cascade op dit moment)

**Verwachte winst**: Moeilijk te schatten zonder historische cascade-data. Conservatief: **+€10-20/week** als overlay op bestaande signalen.

**Implementatietijd**: ~2 dagen  
**Risico**: Medium-Hoog (cascade detection kan false positives geven)  
**Novelty**: ⭐⭐⭐⭐⭐ (Transfer Entropy + graph percolation voor real-time crypto cascade detection is nergens geïmplementeerd in retail trading)

---

## Idee 6: Reflexive Signal Decay (RSD)

**Wat**: Meet hoe snel je signalen hun waarde verliezen na het moment dat ze vuren.

**Hoe**:
- Voor elk signaaltype: groepeer alle keren dat het vuurde
- Meet werkelijk rendement op t=0, t+1min, t+2min, t+5min, t+15min na signaal
- Fit exponentiële decay: $\alpha(t) = \alpha_0 \cdot e^{-\lambda t}$
- $\lambda$ = decay rate per signaal (hoe sneller het afneemt, hoe urgenter de entry)
- Entry op optimaal moment: wanneer signal-to-noise $\frac{\alpha(t)}{\sigma(t)}$ piekt

**Verwachte winst**: **+€5-15/week** (minder stale entries = minder verliezers)

**Implementatietijd**: ~1 dag  
**Risico**: Laag (verandert niet wát je koopt, maar wanneer)  
**Novelty**: ⭐⭐⭐⭐ (alpha decay is bekend bij institutional equities, maar nooit toegepast op retail crypto signal providers met de reflexieve component)

---

## Idee 7: Adversarial Market Topology (AMT)

**Wat**: Gebruik Topological Data Analysis (TDA) om stop-loss hunting te vermijden.

**Hoe**:
- Bouw Vietoris-Rips complex van recente (prijs, volume, tijd) data
- Bereken persistence diagram: robuuste structuren in de data
- Detecteer "stop-loss gravity wells": prijsniveaus waar stops clusteren
- Zet trailing stops **buiten** deze gravity wells
- Detecteer "topological breakouts": als een 1-cycle sterft = structureel niveau gebroken

**Verwachte winst**: Als 10% van trades gestopt worden op stop-hunting levels, en stops €5.61 avg verlies geven: vermeden verlies ~€5-10/week → **+€5-10/week**

**Implementatietijd**: ~3 dagen  
**Risico**: Hoog (complexe wiskunde, kan mislukken)  
**Novelty**: ⭐⭐⭐⭐⭐ (TDA in retail crypto trading bestaat letterlijk niet)

---

## Idee 8: Kapitaalefficiëntie — Meer Slots, Minder per Trade

**Wat**: Vergroot MAX_OPEN_TRADES, verlaag BASE_AMOUNT_EUR, pool DCA reserve.

**Huidig**:
- 5 slots × €150 base = €750 nodig
- DCA reserve: 6 × €30 × 5 trades = €900 (maar 96.4% wordt nooit gebruikt!)
- Totaal gereserveerd: ~€1.650 voor €1.228 portfolio → **overcommitted**

**Voorstel**:
- 7-8 slots × €80-100 base = €560-800
- Gedeelde DCA pool: €100 totaal (niet per trade)
- Budget per trade daalt, maar meer parallel trades = meer kansen

**Verwachte winst**: Meer trades per dag bij zelfde winrate → **+€10-20/week** (onzeker)

**Implementatietijd**: 1 uur (config change + pooled DCA logic)  
**Risico**: Medium (meer trades = meer exposure)  
**Novelty**: ⭐ (portfolio optimization is standaard)

---

## Overzichtstabel

| # | Idee | EUR/week extra | Implementatie | Risico | Novelty | Bewezen? |
|---|------|---------------|---------------|--------|---------|----------|
| 3 | **Timing Filter** | +€15-25 | 30 min | Zeer laag | ⭐ | JA (harde data) |
| 1 | **Velocity Filter** | +€5-25 | 2 uur | Laag | ⭐ | JA (backtest) |
| 4 | **Dynamic Market Scanner** | +€20-35 | 1 dag | Medium | ⭐⭐ | Deels (simulatie) |
| 6 | **Signal Decay (RSD)** | +€5-15 | 1 dag | Laag | ⭐⭐⭐⭐ | Nee |
| 2 | **ACVO** | +€5-30 | 4 uur | Laag-Med | ⭐⭐ | JA (backtest) |
| 8 | **Kapitaalefficiëntie** | +€10-20 | 1 uur | Medium | ⭐ | Nee |
| 5 | **Cascade Detector (ICD)** | +€10-20 | 2 dagen | Med-Hoog | ⭐⭐⭐⭐⭐ | Nee |
| 7 | **Topology (AMT)** | +€5-10 | 3 dagen | Hoog | ⭐⭐⭐⭐⭐ | Nee |

---

## Aanbevolen Implementatievolgorde

### Fase 1: Quick Wins (dag 1) — verwacht +€25-45/week
1. **Timing Filter** — blokkeer entries 13:00-17:00
2. **Velocity Filter** — blokkeer markten met negatief 30d P&L

### Fase 2: Market Expansion (dag 2-3) — verwacht +€15-30/week extra
3. **Dynamic Market Scanner** — scan 50+ markten
4. **Kapitaalefficiëntie** — 7 slots × €100

### Fase 3: Advanced (week 2) — verwacht +€10-25/week extra
5. **Signal Decay (RSD)** — optimale entry timing
6. **Cascade Detector (ICD)** — cascade-aware entry

### Fase 4: Experimenteel (week 3+) — onzeker
7. **Topology (AMT)** — anti-stop-hunting

---

## Totaal Verwachte Winst

| Scenario | EUR/week | EUR/maand |
|----------|----------|-----------|
| Huidig | -€26 | -€104 |
| Na Fase 1 (timing + velocity) | +€5 tot +€20 | +€20 tot +€80 |
| Na Fase 2 (+DMS + kapitaal) | +€25 tot +€50 | +€100 tot +€200 |
| Na Fase 3 (+RSD + ICD) | +€35 tot +€75 | +€140 tot +€300 |
| Theoretisch maximum | +€50 tot +€100 | +€200 tot +€400 |

### Eerlijkheidsnoot
- Fase 1 schattingen zijn gebaseerd op **echte backtest data** en **1.130 trade analyse**
- Fase 2+ zijn **projecties met aannames** — de werkelijke winst kan hoger of lager zijn
- Ideeën zijn **niet onafhankelijk** — de winst van meerdere ideeën samen is NIET de som van individuele schattingen
- Realistische verwachting na alle fases: **+€30-60/week** (niet +€100)
- De projecties voor meer markten (DMS) bevatten de meeste onzekerheid
- De timing filter data is het meest betrouwbaar (direct gemeten uit eigen trades)

---

## Wat is Echt Nieuw?

| Idee | Is het nieuw? | Eerlijk oordeel |
|------|---------------|-----------------|
| Timing Filter | Nee | Tijd-gebaseerde filters bestaan al 50 jaar |
| Velocity Filter | Nee | Momentum/sector rotation is standaard |
| ACVO | Nee | Momentum sizing met een naam |
| DMS | Nee | Universe expansion is standaard quant |
| Kapitaalefficiëntie | Nee | Portfolio optimization is textbook |
| **RSD** | **Gedeeltelijk** | Alpha decay is bekend (Almgren 2003), maar de reflexieve toepassing op retail crypto signals is nieuw |
| **ICD** | **Ja** | Transfer entropy + graph percolation voor real-time cascade detection in retail crypto = niet gepubliceerd |
| **AMT** | **Ja** | TDA persistent homology voor anti-stop-hunting in crypto = niet gepubliceerd |

Conclusie: 6 van 8 ideeën zijn bestaande technieken slim gecombineerd. **ICD en AMT zijn genuinely novel** maar ook het meest riskant en onbewezen.
