# Volledige Bot Analyse – Prompt voor Claude Opus

Kopieer alles hieronder en plak het in een nieuw Claude Opus gesprek.

---

## PROMPT (begin hier met kopiëren)

Je bent een senior quantitative trading engineer en crypto-bot architect met diepgaande kennis van systematische trading, Python-bots, market microstructure en risk management. Je taak is om mijn Bitvavo-trading bot volledig te beoordelen en concrete verbeteringen voor te stellen gericht op maximale winstgevendheid.

---

## BOT OVERZICHT

**Platform:** Bitvavo (Nederlandse crypto-exchange, EUR-paren)  
**Bot-type:** Python trading bot (~5100 regels), draait op Windows, continue 24/7  
**Start-script:** `start_automated.bat`

### Actieve strategieën (simultaan):
1. **Trailing Stop Bot** – primaire strategie: koopt op signalen, verkoopt via trailing stop
2. **Grid Trading** – actief op BTC-EUR en ETH-EUR (max 2 grids, €100 per grid)
3. **HODL Scheduler** – koopt wekelijks €5 BTC + €5 ETH automatisch
4. **Watchlist Manager** – test nieuwe markten met micro-trades (€5)
5. **Pairs Arbitrage** – aanwezig in code maar uitgeschakeld

### AI/ML stack:
- **XGBoost** model (getraind op 1m candles, lookahead 20)
- **LSTM** neural network (price prediction, confidence threshold 0.65)
- **Reinforcement Learning** agent (Q-learning, epsilon 0.05)
- **Ensemble** combining XGB (weight 1.0), LSTM (0.9), RL (0.7)
- **AI Supervisor** – past parameters automatisch aan op basis van performance
- **Sentiment analysis** – geïntegreerd
- **Market regime detection** – geïntegreerd

---

## HUIDIGE PERFORMANCE (echte data)

### Gesloten trades (57 totaal):
| Exit-reden | Aantal | Gem. winst |
|---|---|---|
| sync_removed | 34 | €0.00 |
| auto_free_slot | 8 | €0.00 |
| trailing_tp | 6 | +€0.23 |
| saldo_flood_guard | 5 | **-€1.78** |
| partial_tp_1 | 4 | +€0.34 |

**Netto resultaat gesloten trades: -€6.18 EUR**

### Expectancy stats (laatste 15 trades):
- **Win rate:** 33.3%
- **Gemiddelde winst:** €0.289
- **Gemiddeld verlies:** €0.621
- **Profit factor:** 0.23 (slecht – elk EUR risico levert slechts €0.23 op)
- **Verwachte waarde per trade:** -€0.317

### Partial Take-Profit (NIET volledig gesloten trades):
- **423 partial TP events** totaal
- **L1** (3% winst, 30% positie): 230x → **€353 gerealiseerde winst**
- **L2** (3.5% winst, 35% positie): 131x → **€265 gerealiseerde winst**
- **L3** (10% winst, 30% positie): 62x → **€132 gerealiseerde winst**
- **Totaal partial TP winst: ~€750**

### Huidige stand:
- 8 open trades
- Whitelist: 20 altcoins (SOL, XRP, ADA, AVAX, LINK, NEAR, SUI, APT, DOT, ATOM, AAVE, UNI, LTC, BCH, RENDER, FET, DOGE, OP, ARB, INJ)

---

## CONFIGURATIE (key parameters)

```
BASE_AMOUNT_EUR: 5           # instapgrootte
MAX_OPEN_TRADES: 5           # max gelijktijdige trades
DCA_ENABLED: true
DCA_MAX_BUYS: 3              # max DCA bijkopen
DCA_AMOUNT_EUR: 8            # DCA bijkoop bedrag
DCA_DROP_PCT: 6%             # bijkopen na 6% daling
DCA_SIZE_MULTIPLIER: 1.5     # elke DCA is 1.5x groter
DEFAULT_TRAILING: 8%         # trailing stop afstand
TRAILING_ACTIVATION_PCT: 3.2%# trailing activeert na 3.2% stijging
HARD_SL_ALT_PCT: 9%          # harde stop-loss alts
HARD_SL_BTCETH_PCT: 10%      # harde stop-loss BTC/ETH
RSI_MIN_BUY: 35              # minimum RSI om te kopen
RSI_MAX_BUY: 58              # maximum RSI om te kopen
MIN_SCORE_TO_BUY: 10         # minimum AI score voor entry
SLEEP_SECONDS: 25            # scan interval
MAX_MARKETS_PER_SCAN: 25     # markten per scan
MIN_VOLUME_24H_EUR: 500000   # minimum dagvolume

PARTIAL_TP targets:
  L1: 3% winst → 30% positie verkopen
  L2: 3.5% winst → 35% positie verkopen
  L3: 10% winst → 30% positie verkopen

GRID_TRADING:
  enabled: true
  max_grids: 2
  investment_per_grid: €100
  preferred_markets: BTC-EUR, ETH-EUR
  num_grids: 10
  stop_loss: 12%
  take_profit: 20%

BUDGET_RESERVATION:
  mode: dynamic
  grid_pct: 40%     (van beschikbaar budget)
  trailing_pct: 55% (van beschikbaar budget)
  reserve_pct: 5%

RISK:
  MAX_DAILY_LOSS: €15
  MAX_WEEKLY_LOSS: €30
  MAX_DRAWDOWN_PCT: 25%
  CIRCUIT_BREAKER: stopt bij <25% win rate of <0.5 profit factor
```

---

## MODULES & ARCHITECTUUR

De bot heeft de volgende modules:
- `modules/trading.py` – kernlogica buy/sell
- `modules/trading_dca.py` – DCA bijkopen
- `modules/trading_risk.py` – risk management
- `modules/grid_trading.py` – grid strategie
- `modules/signals/` – trading signalen (range, momentum, mean-reversion, TA)
- `modules/ml.py` + `modules/ml_lstm.py` – ML integratie
- `modules/reinforcement_learning.py` – RL agent
- `modules/ai_engine.py` – AI supervisor
- `modules/performance_analytics.py` – performance tracking
- `modules/watchlist_manager.py` – nieuwe markten testen
- `modules/quarantine_manager.py` – slecht-presterende markten blokkeren
- `modules/pairs_arbitrage.py` – pairs trading (uitgeschakeld)
- `modules/event_hooks.py` – externe triggers
- `modules/bitvavo_client.py` – exchange API
- `core/reservation_manager.py` – budget management

---

## GESIGNALEERDE PROBLEMEN (wat ik al zie)

1. **sync_removed (34x, €0)** – De grootste exitreden is sync. Dit betekent dat de bot trades verwijdert uit zijn tracking als ze niet meer in de Bitvavo-positielijst staan, maar eigenlijk €0 winst registreert. Dit versluiert de echte performance.

2. **saldo_flood_guard (5x, gem -€1.78)** – De bot verkoopt met verlies wanneer het EUR-saldo te laag wordt. Dit is een symptoom van over-allocatie: te weinig reserve EUR.

3. **Profit factor 0.23** – Dramatisch laag. Elke euro die verloren wordt, verdient slechts 23 cent terug. De verliezen zijn gemiddeld 2x zo groot als de winsten.

4. **Win rate 33%** – Te laag voor een systeem met gelijke win/loss grootte. Voor winstgevendheid bij 33% win rate is een R:R van minimaal 2:1 nodig, maar nu is het omgekeerd (avg loss > avg win).

5. **Trailing stop 8% + DCA tot 3x** – Bij een 9% hard SL en 3 DCA-levels met 6% drop per stap kan de maximale positie per trade oplopen tot €5 + €8 + €12 + €18 = **€43** voor een trade die begon als €5. Dit is 8.6x leverage zonder dat de user dit doorheeft.

6. **20 altcoins whitelist** – Veel altcoins met hoge correlatie en hoge volatiliteit. Moeilijk voor de AI om consistente patronen te leren.

7. **LSTM + RL + XGB ensemble** – Drie modellen op 1-minuut candles. Overfitting risico is hoog. Is de out-of-sample performance gevalideerd?

8. **Partial TP L1 target: 3%** – Dit is lager dan de trading spread + fees (0.25% taker × 2 = 0.5%) + slippage. Veel L1 exits zijn waarschijnlijk bijna break-even na kosten.

---

## VRAGEN VOOR JOUW ANALYSE

Analyseer de bot op de volgende punten en geef voor elk een **beoordeling (goed/matig/slecht)** plus **concrete actie**:

### 1. STRATEGIE-EVALUATIE
- Is trailing stop + DCA de beste strategie voor Bitvavo altcoins?
- Welke alternatieve of aanvullende strategieën zouden beter presteren?
- Is de combinatie van 5 simultane strategieën (trailing, grid, hodl, watchlist, pairs) synergistisch of contraproductief?
- Wat is de optimale portfolio-allocatie tussen deze strategieën?

### 2. ENTRY-SIGNALEN
- Is de huidige signaalcombinatie (range, momentum, mean-reversion, TA, AI) effectief?
- Zijn er betere entry-indicatoren voor 1m crypto timeframes?
- Hoe kan MIN_SCORE_TO_BUY worden geoptimaliseerd?
- Is RSI 35-58 als filter zinvol voor 24/7 crypto op 1m candles?

### 3. EXIT-STRATEGIE
- Is trailing stop van 8% optimaal voor altcoins?
- Zijn de partial TP levels (3%, 3.5%, 10%) correct ingesteld?
- Wat is de ideale combinatie van trailing + hard SL + partial TP?
- Zijn de huidige exits te vroeg (leaving money on the table) of te laat?

### 4. DCA-STRATEGIE
- Is aggressief DCA (tot 3x bijkopen) een goede aanpak voor altcoins?
- Wat zijn de risico's van de huidige DCA-setup (van €5 naar potentieel €43)?
- Wanneer is DCA gewenst en wanneer niet?
- Alternatieven voor DCA: piramide-instap, scaled entries?

### 5. AI/ML BEOORDELING
- Is het zinvol om XGB + LSTM + RL te combineren op 1m candles?
- Overfitting risico: trainingsdata is marktdata uit het verleden, altcoins zijn niet-stationair
- Wat zijn betere ML-toepassingen in een trading context?
- Is de AI supervisor die parameters aanpast een risico (feedback loop)?

### 6. RISK MANAGEMENT
- Is de huidige risk setup (9% SL, max 5 trades, €5 basis) goed?
- Hoe groot is de theoretische max drawdown met de huidige DCA-setup?
- Is het circuit-breaker mechanisme (stopt bij <25% win rate) goed ingesteld?
- Ontbreekt er iets fundamenteels in het risk management?

### 7. GRID TRADING
- Is grid trading op BTC-EUR/ETH-EUR zinvol naast een trend-following trailing stop bot?
- Optimale grid-configuratie voor Bitvavo (aantal levels, spread)?
- Wanneer werkt grid trading goed en wanneer slecht?

### 8. KOSTEN & FEES
- Bitvavo taker fee: 0.25%. Bij BASE_AMOUNT_EUR=€5 is de fee €0.0125 per kant = €0.025 round-trip = 0.5% break-even minimaal vereist.
- Partial TP L1 op 3%: na 0.5% fees + 0.1% slippage blijft 2.4% over. Is dit genoeg?
- Hoe minimaliseer je de impact van fees op kleine posities?

### 9. MARKT-SELECTIE
- Is de whitelist van 20 altcoins optimaal?
- Welke coins hebben structureel betere eigenschappen voor deze strategie?
- Moeten er meer of minder markten zijn?
- Is er een betere manier om markten te selecteren dan een vaste whitelist?

### 10. ALTERNATIEVE AANPAKKEN
- Stel een compleet andere aanpak voor als je denkt dat die beter werkt.
- Voorbeelden: mean-reversion only, trend-following only, momentum scalping, funding rate arbitrage, etc.
- Wat zouden de top 3 verbeteringen zijn met de hoogste impact op winstgevendheid?

### 11. PSYCHOLOGIE & OPERATIONEEL
- De bot draait 24/7 op een Windows PC. Wat zijn de risico's?
- Zijn er operationele verbeteringen (VPS, failover, monitoring)?
- Hoe kan de bot beter omgaan met Bitvavo-specifieke eigenaardigheden (limieten, API-snelheid)?

---

## GEVRAAGD EINDRESULTAAT

Geef aan het einde:

1. **Cijfer 1-10** voor de huidige bot (eerlijk onderbouwd)
2. **Top 3 prioriteiten** die ik nu direct moet aanpassen (meeste impact)
3. **Roadmap voor 3 maanden**: Wat doe ik in maand 1, 2 en 3 om winstgevendheid te maximaliseren?
4. **Eerlijk advies**: Is deze aanpak realistisch voor consistente winst, of zijn er fundamentele beperkingen?

Wees direct en gebruik concrete getallen waar mogelijk. Ik heb liever eerlijk slecht nieuws dan lege aanmoediging.
