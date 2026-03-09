# Volledige Bot Analyse – Bitvavo Trading Bot

**Datum:** 22 februari 2026  
**Reviewer:** Senior Quant Trading Engineer Analysis  
**Bot versie:** ~5100 regels, Python, 24/7 op Windows

---

## SAMENVATTING

De bot is **technisch ambitieus en architecturaal indrukwekkend** maar **fundamenteel verliesgevend** door een combinatie van structurele problemen: verkeerde risk/reward verhouding, te complexe ML-stack op te korte timeframes, ongecontroleerde positie-escalatie via DCA, en vertekende performance-tracking. De ~€750 aan partial TP-winst maskeert een onderliggend systeem dat negatieve verwachtingswaarde heeft per trade.

---

## 1. STRATEGIE-EVALUATIE

**Beoordeling: SLECHT**

### Trailing Stop + DCA op Bitvavo altcoins

**Probleem:** Trailing stop is een trend-following exit, maar DCA is een mean-reversion entry. Deze combinatie is **intern tegenstrijdig**:
- De trailing stop veronderstelt dat de prijs blijft stijgen → trend volgen
- DCA bijkopen veronderstelt dat de prijs zal terugkeren → mean reversion
- Bij een echte trend-omslag koop je steeds meer van een dalend asset

**Uit de code (bot_config.json):**
```
DEFAULT_TRAILING: 0.09        (9% – niet 8% zoals eerder vermeld)
DCA_AMOUNT_EUR: 11            (niet €8 – hoger dan gedacht)
DCA_SIZE_MULTIPLIER: 1.5
DCA_STEP_MULTIPLIER: 1.4
```

**Maximale positie-escalatie per trade:**
- Entry: €5
- DCA 1 (na 6% drop): €11 × 1.0 = €11
- DCA 2 (na ~8.4% drop): €11 × 1.5 = €16.50
- DCA 3 (na ~11.8% drop): €11 × 2.25 = €24.75
- **Totaal: €57.25** – dat is **11.5× de initiële positie**

Met een hard SL van 9% op de gemiddelde entry is het maximale verlies per trade: **€57.25 × 9% = €5.15**. Maar als de SL pas triggert na 3 DCA-levels is de prijs al ~12% onder de initiële entry → het werkelijke verlies is groter.

### 5 simultane strategieën

De combinatie trailing + grid + HODL + watchlist + pairs (uitgeschakeld) is **contraproductief**:
- Grid (40% budget) en trailing (55% budget) strijden om hetzelfde kapitaal
- HODL scheduler (€10/week) op BTC/ETH doorkruist de grid op dezelfde markten
- Er zijn maar €5 reserve (5%) → daarom triggert saldo_flood_guard

**Concrete actie:**
1. Kies **één primaire strategie** en wijd 80% budget daaraan
2. Stop DCA bijkopen op verliesgevende posities – DCA alleen bij bewezen winnaars (piramide-up)
3. Verhoog reserve van 5% naar minimaal 20%

---

## 2. ENTRY-SIGNALEN

**Beoordeling: MATIG**

### Huidige signaalcombinatie

4 signaal-providers actief:
| Provider | Trigger | Score |
|---|---|---|
| Range Detector | Prijs <25% van range + RSI<48 | 0-4 punten |
| Volatility Breakout | Prijs > VWAP + 1.8×ATR + volume spike | 0-10 punten |
| Mean Reversion | Z-score ≤ -1.5 + RSI ≤ 50 | variabel |
| TA Filters | SMA cross + EMA + candlestick patterns | 0-3 punten |

**Probleem 1:** Range Detector en Mean Reversion zijn **beide mean-reversion signalen**. In combinatie met een Volatility Breakout (momentum) signaal zijn de entries tegenstrijdig. Je koopt zowel op dips als op breakouts.

**Probleem 2:** `MIN_SCORE_TO_BUY: 10` is hoog – dit vereist dat meerdere tegenstrijdige signalen tegelijk vuren. Dit zou in theorie selectief moeten zijn, maar:
- SIGNALS_GLOBAL_WEIGHT = 3.0 → scores worden 3× vermenigvuldigd
- In praktijk scoren sommige signalen >10 alleen al → effectief filter is laag

**Probleem 3:** RSI 35-58 op 1m candles is **zinloos**. Op 1-minuut timeframe fluctueert RSI-14 constant tussen 30-70. Dit filter blokkeert weinig en laat veel ruis door.

**Concrete actie:**
1. Kies: **óf mean-reversion óf momentum** – niet beide
2. Gebruik RSI op hogere timeframe (15m of 1u) als filter
3. Voeg **multi-timeframe confirmatie** toe: signaal op 1m, bevestiging op 15m/1h
4. Verhoog MIN_SCORE_TO_BUY effectief door SIGNALS_GLOBAL_WEIGHT te verlagen naar 1.0

---

## 3. EXIT-STRATEGIE

**Beoordeling: SLECHT**

### Trailing stop 9%

Voor altcoins met gemiddeld 3-8% dagelijkse volatiliteit is 9% trailing:
- **Te ver** voor scalping/intraday → je geeft bijna al je winst terug
- **Te dicht** voor swing trading → je wordt eruit gestopt door noise

**Concrete analyse:**
- Trailing activatie op 3.2% stijging
- Trailing afstand 9%
- Dus pas na 3.2% stijging begint de trail, en dan moet de prijs nog 9% dalen van de piek
- **Netto minimale winst als trailing uitstopt: 3.2% - 9% = -5.8%** ← VERLIES

Dit is **wiskundig onmogelijk winstgevend**. De trailing stop activatie (3.2%) is lager dan de trailing afstand (9%). Zodra de trailing activeert en vervolgens stopt, maak je verlies tenzij de prijs eerst significant verder is gestegen.

### Partial TP levels

Actuele config:
```
TAKE_PROFIT_TARGETS: [0.03, 0.06, 0.10]
TAKE_PROFIT_PERCENTAGES: [0.30, 0.35, 0.35]
```

- **L1:** 3% winst → 30% verkopen = effectief 0.9% winst op totale positie
- **L2:** 6% winst → 35% verkopen = effectief 2.1% winst op restant
- **L3:** 10% winst → 35% rest verkopen

Na fees (0.25% taker × 2 = 0.5%) + slippage (0.1%):
- L1 netto: 3% - 0.6% = **2.4% op 30% = 0.72% netto op positie**
- Dit is break-even territory voor een €5 positie

De 230× L1 hits × gemiddeld €1.53 = €353 klinkt goed, maar dit is **bruto**. Na fees: ~€353 - (230 × €0.03) = ~€346. Nog steeds positief, maar het vertekent de werkelijke edge.

**Concrete actie:**
1. **CRITICAL FIX:** Trailing activatie MOET hoger zijn dan trailing afstand. Verander naar:
   - `TRAILING_ACTIVATION_PCT: 0.05` (5%)
   - `DEFAULT_TRAILING: 0.04` (4%)
   - Zo is minimale winst bij trail-stop: 5% - 4% = **1% gegarandeerd**
2. Verhoog L1 target naar 5% (na fees: 4.4% netto)
3. Overweeg **time-based exit**: na X uur zonder significante beweging, sluit positie

---

## 4. DCA-STRATEGIE

**Beoordeling: SLECHT**

### Huidige setup

De code in `trading_dca.py` toont twee paden:
1. **Fixed DCA**: ladder met step_multiplier 1.4 op drop_pct 0.06
2. **Dynamic DCA** (actief, `DCA_DYNAMIC: true`): past bedrag aan op 2% van EUR balance + volatiliteit-adjustments

**Probleem 1: Dynamic DCA escaleert ongecontroleerd**
```python
dynamic_amount_eur = max(round(eur_balance * 0.02, 2), 5) * float(size_bias)
```
Bij €500 balance = €10 per DCA. Met size_multiplier 1.5³ = €10 + €15 + €22.50 = **€47.50 extra**.

**Probleem 2: Win rate guard is te zwak**
De code checkt win_rate en max_drawdown, maar:
- Bij win_rate > 60% → max_buys + 1 (tot 5!) → nog agressiever DCA'en
- Bij drawdown > BASE_AMOUNT → slechts 0.85× sizing, max_buys - 1
- Dit is niet genoeg bij structureel verliesgevende trades

**Probleem 3: RSI DCA threshold van 52**
```
RSI_DCA_THRESHOLD: 52.0
```
DCA is alleen geblokkeerd als RSI > 52. Bijna altijd doorgelaten op 1m candles.

**Feitelijke data:** Van de 8 open trades heeft **GEEN ENKELE** een DCA (dca_buys = 0 overal). Dit suggereert dat DCA in praktijk niet triggert door de strikte drop_pct van 6%, maar als het wél triggert, escaleert het snel.

**Concrete actie:**
1. **Flip DCA logica**: DCA niet bij verliezers maar bij winnaars (piramide-up)
2. Max DCA totaal per trade: 2× initiële positie (niet 11.5×)
3. Absolute cap: `DCA_MAX_TOTAL_EUR: 15` per trade
4. DCA alleen toestaan als positie al in winst staat (3%+)

---

## 5. AI/ML BEOORDELING

**Beoordeling: SLECHT (overfitting risico: HOOG)**

### Ensemble: XGB + LSTM + RL op 1m candles

**XGBoost:**
- 11 features (RSI, MACD, BB, ATR, returns, volume, spread, liquidity)
- Getraind op 1m candles, lookahead 20 (= 20 minuten vooruit)
- Target threshold 0.75% prijsverandering

**Probleem:** 20 minuten vooruit voorspellen met indicator-features op 1m is **pure noise-fitting**. Crypto op 1m timeframe is ~random walk met fat tails. De autocorrelatie is effectief nul op die horizon.

**LSTM:**
- Input: (60, 5) sequences – 60 × 1m candles met 5 features
- Confidence threshold 0.65
- **Probleem:** LSTM's hebben minstens duizenden samples nodig per regime. Met 20 altcoins × wisselende regimes is dit onvoldoende.

**RL (Q-Learning):**
- Epsilon 0.05 (5% exploratie) → bijna volledig exploitation
- Q-table in JSON
- **Probleem:** Q-learning met discrete staten op continue price data is gedoemd. De state space is te groot, de tabel zal nooit convergeren met zo weinig exploratie.

**AI Supervisor auto-apply:**
- `AI_AUTO_APPLY: true`
- `AI_FEEDBACK_LOOP_ENABLED: true`
- Parameters die automatisch worden aangepast: trailing, RSI, DCA, base amount, TP targets

**KRITISCH RISICO:** De AI past parameters aan op basis van recente performance → die performance wordt beïnvloed door die parameters → **positieve feedback loop**. Als de bot toevallig wint met agressieve settings, maakt de AI het nog agressiever. Bij verlies het omgekeerde. Dit is **curve fitting op live geld**.

**Concrete actie:**
1. **Schakel AI_AUTO_APPLY uit** (`AI_AUTO_APPLY: false`)
2. Gebruik AI alleen als **advisory** – laat het suggesties doen die je handmatig beoordeelt
3. Verwijder LSTM en RL volledig – houd alleen XGBoost als signaal-filter
4. Train XGBoost op **4h of daily** timeframe, niet 1m
5. Voeg walk-forward validation toe: train op maand N, valideer op maand N+1

---

## 6. RISK MANAGEMENT

**Beoordeling: MATIG (architectuur goed, settings slecht)**

### Positieve punten
- `RiskManager` klasse met segment-gebaseerde drawdown tracking ✓
- Portfolio correlatie check (>70% BTC correlatie blokkeert) ✓  
- Circuit breaker mechanisme ✓
- Kelly factor sizing (0.3) ✓

### Problemen

**1. Conflicterende stop-loss waarden:**
```
HARD_SL_ALT_PCT: 0.09       (9%)
HARD_SL_BTCETH_PCT: 0.10    (10%)
STOP_LOSS_HARD_PCT: 0.12    (12%)
STOP_LOSS_PERCENT: 0.12     (12%)
```
Vier verschillende SL-instellingen. Welke wordt daadwerkelijk gebruikt? Dit is een **configuratie-conflct** dat leidt tot onvoorspelbaar gedrag.

**2. MAX_OPEN_TRADES: 5, maar er zijn 8 open trades**
De data toont 8 open posities met €166.95 totaal geïnvesteerd. De limiet van 5 wordt niet gehandhaafd (waarschijnlijk door manual_restore_from_sync_removed).

**3. Theoretische max drawdown:**
- 5 trades × €57.25 max DCA × 12% SL = **€34.35** max verlies in één scan
- Bij 8 open trades: **€54.96** potentieel verlies
- `RISK_MAX_DAILY_LOSS: €15` wordt hierdoor routinematig overschreden

**4. Saldo reserve: 5%**
Bij €200 beschikbaar: €10 reserve. Dit is **absurd laag**. Daarom triggert saldo_flood_guard (5×, gem -€1.78).

**Concrete actie:**
1. **Één SL-waarde**: kies 8% voor alts, 10% voor BTC/ETH. Verwijder alle duplicaten
2. Verhoog reserve naar **25%** minimum
3. Forceer MAX_OPEN_TRADES hard – geen uitzonderingen
4. Voeg **position-level max loss** toe: sluit trade als verlies > €5 ongeacht SL%

---

## 7. GRID TRADING

**Beoordeling: MATIG**

### Architectuur
De grid module (1432 regels) is technisch solide:
- Volatiliteit-gebaseerde marktselectie (0.3%-1.5% hourly stddev) ✓
- Fee-aware spacing (>0.50% om 2×0.15% maker fees te dekken) ✓
- Auto-rebalance bij ±2% drift ✓
- Ping-pong order management ✓

### Problemen

**1. Budget conflict met trailing bot:**
- Grid: 40% budget, trailing: 55%, reserve: 5%
- Bij €200 budget: Grid €80, Trailing €110, Reserve €10
- Grid investeert €100 per grid × 2 = **€200** → meer dan 40% allocatie

**2. Grid op BTC/ETH + trailing op dezelfde:**
- De bot kan tegelijk een grid-sell en een trailing-buy uitvoeren op hetzelfde asset
- Conflict detection via `get_grid_markets()` lijkt aanwezig maar niet afdwingbaar

**3. Grid werkt slecht in trends:**
- In een bull run: alle sell orders vullen, geen buy orders → je bent je positie kwijt
- In een bear market: alle buy orders vullen, geen sell orders → je zit vast in verlies
- Alleen effectief in **zijwaartse markten** (<5% range)

**Concrete actie:**
1. Grid alleen activeren als volatiliteit 0.3-0.8% (strak zijwaarts)
2. Grid budget verlagen naar €50 per grid (€100 totaal)
3. Grid **niet** combineren met trailing op dezelfde markten – exclusieve allocatie
4. Overweeg grid te pauzeren en al het kapitaal naar trailing te alloceren

---

## 8. KOSTEN & FEES

**Beoordeling: MATIG**

### Fee-analyse

Bitvavo fees:
- **Taker:** 0.25% (market orders)
- **Maker:** 0.15% (limit orders)
- Config: `ORDER_TYPE: "auto"` met `LIMIT_ORDER_PRICE_OFFSET_PCT: 0.1`

Round-trip kosten:
- Best case (maker+maker): 0.30%
- Worst case (taker+taker): 0.50%
- Typical (taker buy + maker sell): 0.40%

**Bij €5 positie:**
- Round-trip fee: €0.020 - €0.025
- Dit is **0.4-0.5% break-even** voordat je winst maakt
- Bij L1 TP van 3%: netto 2.5-2.6% → acceptabel
- Maar bij verlies: fee + verlies = **groter dan berekend**

**Fee-impact op partial TP:**
230 L1 events × €0.0125 taker fee per verkoop = **€2.88 aan fees**. Op €353 bruto is dit verwaarloosbaar (0.8%).

**Maar op DCA events:**
Elke DCA bijkoop = extra 0.25% fee op het bijgekochte bedrag. Bij 3× DCA: €11 + €16.50 + €24.75 = €52.25 × 0.25% = **€0.13** extra aan fees. Klein, maar het eet marge op bij kleine winsten.

**Concrete actie:**
1. Gebruik **limit orders** voor zowel buy als sell om maker fee van 0.15% te betalen
2. Verhoog minimale positiegrootte naar €10 om fee-impact te halflveren
3. Bij partial TP L1: bereken netto winst na fees en skip als netto < €0.20

---

## 9. MARKT-SELECTIE

**Beoordeling: MATIG**

### Huidige whitelist (20 coins)

**Goed:** Mix van large-cap (SOL, XRP, ADA, LTC, BCH) en mid-cap (SUI, APT, RENDER, FET, INJ)

**Probleem 1: Te veel markten voor €200 budget**
20 markten × €5 instap = €100 nodig voor 1 trade per markt. Met MAX_OPEN_TRADES: 5 scan je maar 25% van de lijst. De rest is noise.

**Probleem 2: Hoge onderlinge correlatie**
Bijna alle altcoins zijn 0.7-0.9 gecorreleerd met BTC op dagbasis. Bij een BTC-dump dalen ze allemaal tegelijk → je diversificatie is een illusie.

**Probleem 3: Performance-data per markt**
```
Winnaars:  ADA (+€0.72), UNI (+€0.42), RENDER (+€0.36), FET (+€0.30)
Verliezers: AVAX (-€5.46), LINK (-€1.79), INJ (-€0.63), DOT (-€0.65)
```
AVAX alleen is verantwoordelijk voor **88% van het totale verlies** (saldo_flood_guard). De quarantine manager had dit moeten detecteren.

**Concrete actie:**
1. Reduceer whitelist naar **8-10 markten** met bewezen performance
2. Verwijder AVAX, INJ, DOT (consistent verliesgevend)
3. Focus op coins met **hogere volume** en **lagere spread**: SOL, XRP, ADA, LINK, LTC
4. Implementeer **dynamische markt-rotatie** op basis van 7-daags momentum

---

## 10. ALTERNATIEVE AANPAKKEN

### Top 3 verbeteringen met hoogste impact

#### 1. **CRITICAL: Fix de trailing stop wiskunde** (Impact: ★★★★★)
Het feit dat TRAILING_ACTIVATION_PCT (3.2%) < DEFAULT_TRAILING (9%) betekent dat **elke trailing stop die activeert en vervolgens stopt een verlies oplevert**. Dit is het grootste probleem.

**Fix:**
```json
{
  "TRAILING_ACTIVATION_PCT": 0.06,
  "DEFAULT_TRAILING": 0.04
}
```
Minimale gegarandeerde winst per trailing exit: 6% - 4% = **2%**

#### 2. **Stop met DCA naar verliezers, piramide naar winnaars** (Impact: ★★★★☆)
In plaats van bijkopen bij dalende prijs:
- DCA alleen als positie **al 3%+ in winst** staat
- Verkoop 100% bij hard SL, nooit bijkopen bij verlies
- Dit keert de risk/reward om: kleine verliezen (5-8% van €5 = €0.25-0.40) en grotere winsten

#### 3. **Schakel AI auto-apply uit, simplificeer ML** (Impact: ★★★★☆)
- XGBoost als enige ML model, op 4h timeframe
- Geen auto-parameter tuning
- Vaste, handmatig geteste parameters

### Alternatieve complete aanpak

**Mean-Reversion Scalper (als vervanging):**
1. Scan alleen top 5 meest liquide altcoins
2. Entry: Z-score ≤ -2.0 op 15m VWAP + RSI(14) < 30 op 1h
3. Exit: terugkeer naar VWAP (z-score = 0) of time-stop na 4 uur
4. Position size: €15 vast, geen DCA
5. Max 3 gelijktijdige trades
6. Hard SL: 3% (verlies max €0.45 per trade)
7. Verwachte target: 1-2% per trade (€0.15-0.30)
8. Win rate target: 55%+
9. Expectancy: ~€0.10 per trade × 5 trades/dag = **€0.50/dag = €15/maand**

Dit is conservatief maar **winstgevend** en schaalbaar.

---

## 11. PSYCHOLOGIE & OPERATIONEEL

**Beoordeling: MATIG**

### Windows 24/7 risico's
- **Stroomuitval** → bot stopt, open posities onbeheerd
- **Windows Updates** → herstart, zelfde probleem
- **OneDrive sync** → JSON file corruption (trade_log.json kan corrupt raken bij gelijktijdige schrijf + sync)
- **Geheugenlek** → Python 24/7 met LSTM/XGB models kan RAM-gebruik laten groeien

### Bitvavo-specifiek
- **Rate limits:** 1000 requests per minuut. Bij 25 markten × 3 API calls (ticker, candles, orderbook) per scan = 75 calls per 25 sec = **180 calls/min**. Ruim binnen limiet.
- **API latency:** Metrics tonen 1213ms gemiddeld. Dit is **hoog** – mogelijk door orderbook fetching met depth.
- **Minimum order:** €5.00 per trade. Huidige BASE_AMOUNT_EUR van €5 is precies de minimum → geen marge voor fees.

### Sync-removed probleem
34 van 57 trades (60%) zijn `sync_removed` met €0 winst. Ondanks `DISABLE_SYNC_REMOVE: true` in de config. Dit wijst op een **bug**:
- De bot verwijdert trades als de Bitvavo balance ze niet meer toont
- Dit gebeurt na partial TPs die de positie onder minimum brengen
- De echte P&L van deze trades is **onbekend** – ze kunnen winst of verlies zijn

**Concrete actie:**
1. **Fix sync_removed bug** – dit is de #1 data-integriteit issue
2. Migreer van OneDrive naar lokale opslag voor data files
3. Overweeg VPS (Hetzner €4/maand) voor 24/7 uptime
4. Voeg **heartbeat monitoring** toe met Telegram alert als bot >5 min stil is
5. Verhoog BASE_AMOUNT_EUR naar €10 om boven Bitvavo minimum te zitten met marge

---

## EINDRESULTAAT

### 1. Cijfer: 3.5 / 10

**Onderbouwing:**
| Aspect | Score | Gewicht |
|---|---|---|
| Code-architectuur | 7/10 | Goed gestructureerd, modules, dataclasses |
| Strategie-logica | 2/10 | Intern tegenstrijdig, negatieve verwachtingswaarde |
| Risk management | 4/10 | Goede structuur, slechte configuratie |
| AI/ML | 2/10 | Overfitting, feedback loop, te complex |
| Performance tracking | 5/10 | Uitgebreid maar versluierd door sync_removed |
| Operationeel | 4/10 | Windows, OneDrive, geen failover |
| Winstgevendheid | 1/10 | -€6.18 netto, profit factor 0.23 |

De architectuur verdient een hoger cijfer. Het is duidelijk dat er serieuze engineering effort in zit. Maar een trading bot wordt beoordeeld op P&L, en die is negatief.

---

### 2. Top 3 Prioriteiten (nu direct aanpassen)

#### PRIORITEIT 1: Fix trailing stop wiskunde (vandaag)
```json
{
  "TRAILING_ACTIVATION_PCT": 0.06,
  "DEFAULT_TRAILING": 0.04
}
```
**Impact:** Verandert elke trailing exit van gegarandeerd verlies naar gegarandeerd 2% winst minimum.

#### PRIORITEIT 2: Stop DCA bij verliezers (vandaag)  
```json
{
  "DCA_ENABLED": false
}
```
Tot je DCA-logica omkeert naar piramide-up. Elke DCA bij verlies vergroot je exposure in een verliezende positie.

#### PRIORITEIT 3: Schakel AI auto-apply uit (vandaag)
```json
{
  "AI_AUTO_APPLY": false,
  "AI_FEEDBACK_LOOP_ENABLED": false
}
```
Voorkom dat het systeem zichzelf optimaliseert op random resultaten.

---

### 3. Roadmap 3 Maanden

#### Maand 1: Stabilisatie & Data-integriteit
**Week 1-2:**
- [ ] Fix trailing stop parameters (activation > trailing distance)
- [ ] Schakel DCA uit
- [ ] Schakel AI auto-apply uit
- [ ] Fix sync_removed bug (60% van trades heeft onbekende P&L)
- [ ] Verhoog reserve naar 25%
- [ ] Reduceer whitelist naar 8 markten

**Week 3-4:**
- [ ] Implementeer accurate P&L tracking inclusief fees
- [ ] Backtest huidige strategie op 3 maanden historische data
- [ ] Documenteer baseline: verwachte trades/dag, win rate, avg profit/loss

**Doel maand 1:** Bot die break-even draait met accurate data.

#### Maand 2: Strategie-optimalisatie
**Week 5-6:**
- [ ] Implementeer mean-reversion scalper als alternatief
- [ ] Backtest op 1000+ trades simulatie
- [ ] A/B test: trailing stop vs mean-reversion op paper trading

**Week 7-8:**
- [ ] Optimaliseer XGBoost op 4h timeframe
- [ ] Walk-forward validation implementeren
- [ ] Grid trading evalueren: aan/uit vergelijken over 2 weken

**Doel maand 2:** Strategie met positieve verwachtingswaarde (profit factor > 1.2).

#### Maand 3: Schaling & Operationeel
**Week 9-10:**
- [ ] Migreer naar VPS
- [ ] Implementeer DCA-naar-winnaars (piramide-up) met caps
- [ ] Verhoog positiegrootte geleidelijk (€10 → €15 → €20)

**Week 11-12:**
- [ ] Evalueer 3-maands performance
- [ ] Besluit: door-optimaliseren of stoppen
- [ ] Als positief: geleidelijk opschalen met Kelly sizing

**Doel maand 3:** Consistente winst van €20-50/maand op €300-500 kapitaal.

---

### 4. Eerlijk Advies

**Is deze aanpak realistisch voor consistente winst?**

**Ja, MAAR** alleen met fundamentele aanpassingen. De huidige bot verliest geld door **fixbare fouten**, niet door een fundamenteel onmogelijke aanpak. Specifiek:

**Wat wél werkt:**
- De partial TP strategie genereert ~€750 aan winst. Dit bewijst dat er een edge is in de entry-signalen
- De code-architectuur is professioneel en uitbreidbaar
- De risk management structuur is goed – alleen de parameters zijn fout

**Wat niet werkt en nooit zal werken:**
- ML op 1m crypto candles → er is geen voorspelbare edge op die timeframe
- DCA naar verliezers → dit is martingale met extra stappen
- AI die zijn eigen parameters aanpast → dit is zelf-deceiving optimization

**Fundamentele beperkingen:**
1. **Klein kapitaal (€200-300)** beperkt diversificatie en maakt fees proportioneel groot
2. **Bitvavo fees (0.25% taker)** vereisen minimaal 0.5% bruto edge per trade – dit is haalbaar maar krap
3. **Altcoin correlatie** maakt diversificatie grotendeels illusoir
4. **Regelgeving** – Nederlandse belasting op crypto-winst (vermogensrendementsheffing) eet een deel van de winst

**Realistisch doel:** Met €500 kapitaal, gefixte strategie, en gemiddeld 2-3 trades per dag met 55% win rate en 1.5:1 R/R → **€30-60 per maand**. Niet genoeg om van te leven, wel genoeg om de bot te valideren voor opschaling.

**Mijn advies:** Fix de drie prioriteiten vandaag. Draai 30 dagen met de gefixte parameters. Evalueer dan opnieuw. Als de profit factor boven 1.0 komt, heb je een basis om op te bouwen. Als niet, overweeg een fundamenteel andere strategie (pure mean-reversion scalper).

---

*Dit rapport is gebaseerd op de volledige broncode, configuratie, en trade-log data van 22 februari 2026.*
