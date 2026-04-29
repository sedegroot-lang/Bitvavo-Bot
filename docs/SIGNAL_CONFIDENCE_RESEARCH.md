# 🎯 Signal Confidence Research — "Wij zijn het signaal"

> **Auteur:** Copilot · **Datum:** 2026-04-29 · **Status:** Research / Discussion (geen code change yet)
> **Doel:** Van "11 markten halen MIN_SCORE" naar "1 markt verdient écht onze entry vandaag"

---

## 0. Probleemstelling (verbatim van gebruiker)

> *"Ik zit behoorlijk lang vast in trades met de huidige strategie, kijk maar naar de leeftijd
> van de trades. Er zijn 11 markten die voldoen aan de min score, maar stel je voor dat die nou
> al die 11 markten had geopend, is dat niet veels te veel? Hoe krijgen we meer confidence in
> een trade voordat we een trade starten?"*

### Symptomen vandaag (2026-04-29)
| Markt | Leeftijd | Score@entry | Regime | Status |
|---|---|---|---|---|
| RENDER-EUR | **6.3 dagen** | 0.0 (legacy) | unknown | TRAILING terug onder buy |
| XLM-EUR | 1.5 d | 17.5 | neutral | actief |
| ENJ-EUR | 1.5 d | 15.7 | neutral | TRAILING terug onder buy |

→ De **gemiddelde leeftijd van open trades is 3.1 dagen** terwijl de bot is gebouwd voor 4-24h
turnover. Geld zit te lang vast in **één-richting-tegen** posities.

### De 11-kandidaten paradox
Als de bot vandaag 11 markten boven `MIN_SCORE_TO_BUY=8` ziet, en `MAX_OPEN_TRADES=4`, dan
opent hij willekeurig de eerste 4. Dat is **survivorship bias by accident** — geen actieve keuze.

---

## 1. Waarom de huidige score onvoldoende is

De huidige score combineert (uit `bot/signals.py` + `modules/signals/*`):

1. **Trend filters** — SMA crossover, MACD richting
2. **Momentum** — RSI in zone, prijs > VWAP
3. **Volatility** — ATR-band, Bollinger expansion
4. **Volume** — 1m volume ≥ X EUR
5. **Optionele plugins** — range, mean-reversion, vol-breakout

**Tekortkomingen:**

| Probleem | Voorbeeld vandaag |
|---|---|
| Score is **lineaire som** van zwakke signalen | Een markt kan 8.0 halen met 4 zwakke confirmaties; een ándere markt 8.0 halen met 1 sterke + 3 nul. Same score, totaal verschillende kwaliteit. |
| Geen **regime-conditioneel gewicht** | Mean-reversion telt evenveel mee in TRENDING_UP als in RANGING. |
| Geen **forward-looking feature** (ML-output is informational, niet gating) | XGB-model output zit in score maar niet als veto. |
| Geen **cross-market ranking** | We vragen "haalt deze markt de drempel?" niet "is dit de béste van de N kandidaten?". |
| Geen **tijdsfilter** ("waarom nu?") | We kunnen een trade openen 4u te vroeg ten opzichte van een breakout. |
| **Cooldown-only de-correlation** | Als BTC, ETH, SOL allemaal hetzelfde regime delen, opent de bot drie trades met 95% gecorreleerde uitkomst. |

---

## 2. Confidence framework — zes pillars

Stel **`entry_confidence ∈ [0, 1]`** samen uit zes onafhankelijke pillars. Een trade opent
alleen als `entry_confidence ≥ 0.65` ÉN het de **rank-1** kandidaat is van deze cyclus.

### Pillar A — Trend agreement (multi-timeframe)
- **3 timeframes parallel**: 1m, 15m, 1h
- Score = aantal TFs waarop EMA(20) > EMA(50) en MACD>0 / 3
- **Eis ≥ 2/3** anders pillar = 0
- Voorkomt: trade openen op een 1m-fakeout terwijl 1h-trend down is

### Pillar B — Momentum quality (oversold-bounce vs continuation)
- **In RANGING**: prefer RSI 30-40 met bullish divergentie (bounce setup)
- **In TRENDING_UP**: prefer RSI 50-65 met higher-lows op 5m (continuation)
- Score = match van de huidige setup met het regime-archetype
- Voorkomt: chasen van een already-pumped markt (RSI 70+) of trying to catch falling knife (RSI <25)

### Pillar C — Volume confirmation (institutionele voetafdruk)
- **Z-score van 5m volume vs 30-bar mediaan** — moet ≥ +1.0σ zijn
- **OBV slope laatste 30 bars** — moet positief zijn voor long
- **Geen large-trade-asymmetrie**: top-3 trades laatste 5m mogen niet >40% van volume zijn (anti-spoof)
- Voorkomt: micro-cap met ge-faked volume (zoals oude UNI-incident)

### Pillar D — Volatility opportunity (juiste R:R)
- **ATR/price ≥ 0.4%** op 5m (anders is target-net niet te halen)
- **ATR/price ≤ 2.5%** op 5m (anders is whipsaw-risk te hoog)
- Score = 1 - |0.012 - vol| / 0.013 (gebeld op 1.2% vol als sweet spot)
- Voorkomt: dood-stille markten (target onbereikbaar) en wilde markten (stop te snel geraakt)

### Pillar E — ML model agreement (XGB + LSTM + RL ensemble)
- **XGB win-prob ≥ 0.55** vereist
- **MAPIE conformal interval breedte ≤ 0.20** (model is confident, niet "0.5 ± 0.4")
- **LSTM 30m-forecast** moet positief zijn (slope > 0)
- Score = (xgb_p - 0.5) × 2 × (1 - mapie_width)
- Voorkomt: trades waar het model "weet dat het niet weet"

### Pillar F — Cross-market context (correlatie + alpha)
- **β tot BTC** moet < 0.7 OF BTC zelf moet ook bullish zijn
- **Relative strength** vs BTC laatste 24h moet positief zijn
- **Geen overlap met open trades** (max 1 trade per sector / per cluster)
- Score = 1 - max_correlation_with_open_trades
- Voorkomt: 4 trades die feitelijk 1 trade zijn (alle altcoins long)

---

## 3. Aggregatie & ranking

```python
# Pseudocode
def entry_confidence(market, ctx) -> float:
    a = trend_agreement_pillar(market)        # 0..1
    b = momentum_quality_pillar(market, ctx)  # 0..1
    c = volume_confirmation_pillar(market)    # 0..1
    d = volatility_opportunity_pillar(market) # 0..1
    e = ml_agreement_pillar(market)           # 0..1
    f = cross_market_pillar(market, ctx)      # 0..1
    
    # ALL pillars matter — geometric mean (one weak pillar tanks the score)
    return (a * b * c * d * e * f) ** (1/6)

def select_entries(candidates, max_open=4):
    # Step 1: hard filters (each pillar ≥ 0.4)
    candidates = [c for c in candidates if all(p >= 0.4 for p in c.pillars)]
    
    # Step 2: rank by entry_confidence
    candidates.sort(key=lambda c: c.entry_confidence, reverse=True)
    
    # Step 3: take only top N where confidence ≥ 0.65 AND each is decorrelated from existing
    selected = []
    for c in candidates:
        if c.entry_confidence < 0.65: break
        if any(corr(c, s) > 0.7 for s in selected + open_trades): continue
        selected.append(c)
        if len(selected) >= max_open: break
    return selected
```

### Resultaat: van 11 → 0-2 entries per cyclus
- Geometric mean = ELK pillar moet redelijk zijn (1 zwak pillar = totaal zwak)
- Dynamic threshold (0.65) = bot opent vaker NIETS i.p.v. mediocre trades
- Decorrelation = portfolio echt gediversifieerd

---

## 4. Time-stop / "Why am I still in this?"

Naast confidence-bij-entry moeten we ook **continuous re-evaluation** doen:

```python
# Elke loop voor elke open trade
def should_stay_in(trade) -> bool:
    age_h = (now - trade.opened_ts) / 3600
    
    # Hard time-stop: na 48h zonder progress = exit
    if age_h > 48 and trade.unrealised_pct < 1.0:
        return False
    
    # Soft time-stop: na 24h met negative confidence revaluation
    if age_h > 24:
        new_conf = entry_confidence(trade.market, ctx)
        if new_conf < 0.40:  # what made it interesting is gone
            return False
    
    # No-momentum-no-mercy: 6h zonder ATR-multiple bewegingen
    if age_h > 6 and abs(trade.high - trade.buy) < 0.5 * trade.atr_at_entry:
        return False
    
    return True
```

→ Lost RENDER 6.3-dagen probleem direct op.

---

## 5. Ranking-only mode (start hier — laagste risico)

**Voorgestelde implementatie volgorde:**

1. **Sprint 1 (1u):** Voeg `pillars: dict` toe aan elke trade-evaluatie als **passive logging**
   — niet gebruikt voor beslissingen, alleen om data te verzamelen
2. **Sprint 2 (2u):** Implementeer pillars C, D, F (volume, volatility, cross-market) — meest mechanisch
3. **Sprint 3 (2u):** Implementeer pillars A, B (multi-TF trend, regime-aware momentum)
4. **Sprint 4 (1u):** Pillar E (ML agreement met MAPIE breedte als confidence proxy)
5. **Sprint 5 (1u):** Activeer **ranking-only mode**: bot blijft de huidige scoring gebruiken,
   MAAR opent alleen de **rank-1** kandidaat per cyclus i.p.v. eerste 4-die-passeren
6. **Sprint 6 (1u):** Schakel hard threshold `entry_confidence ≥ 0.65` in als gating
7. **Sprint 7 (1u):** Time-stop op open trades (zie sectie 4)

→ **Total: ~9 uur werk** voor een fundamenteel betere entry pipeline

---

## 6. Externe inspiratie

| Bron | Wat we kunnen jatten |
|---|---|
| **Freqtrade `Strategy` interface** | Abstract base class met `populate_buy_trend(df)` / `populate_sell_trend(df)`. Maakt 6-pillar implementatie modulair. |
| **Hummingbot connectors** | Multi-exchange order book aggregation voor pillar C (volume) — Bitvavo alleen is te dun. |
| **Qlib feature store** | Versioned features met snapshot voor backtesting van pillar E. |
| **Jesse strategy patterns** | "Wait for confirmation" patroon — bevestiging in volgende candle nodig vóór entry. |

---

## 7. Backtesting strategie voor deze hypotheses

**Eerst meten, dan code.** Voor iedere pillar:

1. Bouw historische dataset van laatste 90d closed trades
2. Bereken pillar-score retrospectief voor elke trade
3. Plot: pillar-score (X) vs realized PnL (Y) → wil monotonic positief verband zien
4. Pillar die geen verband toont → schrappen of herontwerpen

**Use existing trade_features.csv** (zie `scripts/build_trade_features.py`) als basis. Voeg
pillar kolommen toe en run XGB feature-importance.

---

## 8. Direct uitvoerbare experimenten (zonder code-change)

Met de huidige config kunnen we deze tests al draaien:

### Experiment A — `MIN_SCORE_TO_BUY` van 8.0 → 14.0
- **Hypothese:** trades met score 8-14 zijn marginaal en verzieken portefeuille
- **Bewijs nodig:** vergelijk win-rate van score-bucket [8,11) vs [14,∞)
- **Verwachting:** win-rate stijgt 5-10%, # trades daalt 60-70%

### Experiment B — `MAX_OPEN_TRADES` van 4 → 2
- **Hypothese:** geconcentreerde portefeuille = scherpere allocatie
- **Bewijs nodig:** Sharpe ratio over 30d met max=2 vs max=4
- **Risico:** als bot vaak NIETS open heeft = idle EUR = opportunity cost

### Experiment C — Hard time-stop bij 24u
- **Hypothese:** trades die in 24u geen +2% halen, halen het sowieso niet
- **Bewijs nodig:** histogram van time-to-+2% voor winnende trades
- **Verwachting:** mediaan winning trade hits +2% binnen 6u

→ **Aanbeveling:** doe Experiment A eerst (laagste risico, hoogste informatie-rendement).

---

## 9. Definition of Done (deze research → werkende feature)

- [ ] Pillars A-F geïmplementeerd in `bot/entry_confidence.py`
- [ ] `entry_confidence` als kolom in `trade_features.csv`
- [ ] Backtest toont `entry_confidence` ≥ 0.65 = win-rate ≥ 65% (vs huidige ~50%)
- [ ] Live: bot opent maximaal 1-2 trades/dag (vs huidig 4-8)
- [ ] Gemiddelde trade-leeftijd zakt van 3.1d → < 1.0d
- [ ] Hard time-stop in werking → geen open trades > 48u meer

---

## 10. Eerste actie aanbeveling

**Niet beginnen met code.** Eerst:

1. Run **Experiment A** met live A/B (`MIN_SCORE_TO_BUY=14` voor 1 week)
2. Verzamel data: hoeveel trades, welke win-rate
3. Pas dan implementatie van pillar-framework starten

→ Dit voorkomt premature optimization en geeft een bewezen baseline.

---

*Volgende stap: bespreek met Sed — welke 1-2 experimenten draaien we deze week?*
