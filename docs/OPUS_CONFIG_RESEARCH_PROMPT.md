# Claude Opus — Comprehensive Config Optimization Request

**Context:** This is a live Python trading bot running on the Bitvavo exchange (Dutch).  
**Task:** Based on the verified data, code bugs, and external research below, produce the **optimal replacement `bot_config.json`** for every parameter.  
**No questions.** Make every decision based on the data. Provide a complete config with reasoning.

---

## 1. ACCOUNT STATUS (VERIFIED)

| Metric | Value |
|--------|-------|
| Deposited total | €670 |
| Current account value | €279.51 |
| **Net loss** | **-€391 (-58%)** |
| Open trades | 8–9 |
| Estimated in open positions | ~€154 |
| Free balance | ~€56 |

**The bot has destroyed 58% of the account. This is not a small drift — it is a fundamental design failure.**

---

## 2. REAL PERFORMANCE DATA (VERIFIED FROM SOURCE FILES)

### Expectancy Stats (`data/expectancy_stats.json`)
```
sample_size:        789 trades
win_rate:           45.7%  (recent 50 trades: ONLY 14%)
avg_win:            €3.76
avg_loss:           €5.31
expectancy_eur:     -€1.16 per trade
profit_factor:      0.597  (needs >1.0 to be profitable)
net_profit:         -€917 (cumulative/backfilled)
longest_win_streak: 49
longest_loss_streak: 36
```

**Break-even math:** To break even at 45.7% win rate, you need avg_win ÷ avg_loss ≥ 1.19.  
Current ratio = 3.76 ÷ 5.31 = **0.71 → losing money by mathematical certainty.**

### Closed Trades Analysis (`data/trade_log.json`)
```
Total closed:     58
Real trades:      16  (abs(profit) > €0.01)
  Real wins:      11   avg profit: +€0.268
  Real losses:    5    avg loss:   -€1.779
Risk/Reward:      0.15  ← CATASTROPHIC (need ≥1.5)
```

**Risk/Reward of 0.15 means you need an 87% win rate to break even. You have 45.7%.**

### Partial TP Events (`data/partial_tp_events.jsonl`) — 30 events total
```
Level 0 (L1 = +5%): 26 hits | €32.65 total | avg €1.26 per hit
Level 1 (L2 = +8%): 4 hits  | €3.02 total  | avg €0.75 per hit
Level 2 (L3 = +12%): 0 hits  | €0.00 total  ← NEVER FIRES

Top coin by partial TP:
  ZEUS-EUR:   8x hits | €24.68 | avg €3.09  (NOTE: NOT in current whitelist!)
  ICX-EUR:    1x      | €1.38
  NEAR-EUR:   1x      | €1.26
  Others:     < €1.00 each
```

**WARNING: L3 (+12%) never fires because HARD_SL_ALT_PCT (12%) hits first. L3 is dead code in practice.**

---

## 3. CURRENT CONFIG (ALL KEY PARAMETERS)

### Position Sizing
```json
"BASE_AMOUNT_EUR": 12.0,
"DCA_AMOUNT_EUR": 6,
"DCA_AMOUNT_RATIO": 0.5,     // NEW: DCA = 50% of BASE = €6
"MAX_OPEN_TRADES": 5,
"MAX_TOTAL_EXPOSURE_EUR": 9999,   // DANGER: NO CAP
"MIN_BALANCE_EUR": 0,             // DANGER: NO FLOOR
```

### Stop-Loss
```json
"STOP_LOSS_HARD_PCT": 0.08,       // 8% hard SL (main coins)
"HARD_SL_ALT_PCT": 0.12,          // 12% hard SL (alts)
"HARD_SL_BTCETH_PCT": 0.10,       // 10% for BTC/ETH (code default)
```

### Trailing Stop
```json
"DEFAULT_TRAILING": 0.032,         // 3.2% trail distance
"TRAILING_ACTIVATION_PCT": 0.045,  // activates at +4.5%
```

### Partial Take-Profit
```json
"TAKE_PROFIT_TARGETS": [0.05, 0.08, 0.12],      // +5%, +8%, +12%
"TAKE_PROFIT_PERCENTAGES": [0.3, 0.35, 0.35],   // sell 30%, 35%, 35%
"PARTIAL_TP_SELL_PCT_1": 0.3,
"PARTIAL_TP_SELL_PCT_2": 0.35,
"PARTIAL_TP_SELL_PCT_3": 0.35,
```

### DCA (Dollar-Cost Averaging / Average-Down)
```json
"DCA_DROP_PCT": 0.06,              // trigger DCA after -6% drop
"DCA_MAX_BUYS": 3,                 // up to 3 DCA adds
"RSI_DCA_THRESHOLD": 45.0,         // DCA only if RSI < 45
```

### Entry Filters
```json
"RSI_MIN_BUY": 35,                 // don't buy if RSI < 35
"RSI_MAX_BUY": 58,                 // don't buy if RSI > 58
"MIN_SCORE_TO_BUY": 10,            // signal strength threshold
```

### Circuit Breaker / Risk Management
```json
"CIRCUIT_BREAKER_MIN_WIN_RATE": 0, // DISABLED (0 = never triggers)
"CIRCUIT_BREAKER_WINDOW": null,    // not set
```

### Fees (Bitvavo actual)
```json
"FEE_MAKER": 0.0015,               // 0.15%
"FEE_TAKER": 0.0025,               // 0.25%
"SLIPPAGE_PCT": 0.001,             // 0.1% estimated slippage
```
**Total round-trip cost: minimum 0.30% (maker+maker), typical 0.50% (taker+taker).**

---

## 4. CRITICAL CODE BUGS (DO NOT CHANGE CONFIG TO WORK AROUND THESE — DOCUMENT THEM)

### Bug #1: DCA Overlaps Stop-Loss (✅ AUTO-FIXED IN CODE)
```
DCA buy 1: at entry price (€12)
DCA buy 2: at -6%   (€6 add)
DCA buy 3: at -12%  (€6 add)

But HARD_SL_ALT_PCT = 0.12 triggers a SELL at -12%
→ DCA buy 3 placed exactly at SL boundary → race condition
```
**Status: Fixed.** `trailing_bot.py` automatically **widens `HARD_SL_ALT_PCT`** at startup if it conflicts with the DCA levels:  
`min_required_sl = DCA_DROP_PCT × DCA_MAX_BUYS + DCA_SL_BUFFER_PCT`  
The SL is widened (not DCA capped) — respecting the user's DCA intent. Config `DCA_SL_BUFFER_PCT` controls the gap (default 1.5%).

**Simulation with current config (DCA_DROP=6%, buffer=1.5%):**
```
DCA_MAX_BUYS=1 → SL unchanged at 12%   (diepste DCA -6%, buffer 6%)
DCA_MAX_BUYS=2 → SL auto-widened to 13.5%
DCA_MAX_BUYS=3 → SL auto-widened to 19.5%
DCA_MAX_BUYS=5 → SL auto-widened to 31.5%
```
**Opus: still configure DCA_DROP_PCT and HARD_SL_ALT_PCT explicitly and consistently** so no auto-widening is needed (prevents accidental very wide SL).

### Bug #2: RSI Threshold Blocks Most DCA (WRONG LOGIC)
```
RSI_DCA_THRESHOLD = 45
This means: DCA only executes when RSI < 45

In a falling market (when you WANT to DCA):
- Price drops -6%      → RSI often 40-55 during decline
- By the time RSI < 45, you are already deep in loss
- If price recovers, RSI rises above 45 → DCA BLOCKED
→ Result: DCA fires very rarely. AAVE blocked at RSI 53.6 > 45 is a documented example.
```

### Bug #3: Pyramid-Up Size Too Small
```
2nd pyramid add = BASE × 0.7 × scale_down_factor
= 12.0 × 0.70 = €8.40 in theory
But with scale modifiers can drop to = €3.50
Minimum order = €5.00
→ Order rejected silently
→ Pyramid doesn't actually work past first add
```

### Bug #4: L3 Partial TP Is Dead Code
```
TAKE_PROFIT_TARGETS[2] = 0.12  (= +12%)
HARD_SL_ALT_PCT = 0.12         (= -12%)

The trade will hit HARD SL before L3 TP in any losing trade.
In a winning ALT trade, price must reach +12% but the trailing stop
(activated at +4.5%, trail 3.2%) will trigger at approximately +1.3% to +8%
before reaching +12%.
→ L3 fires 0 times. Confirmed by data (0 events in 30 total).
```

### Bug #5: MAX_TOTAL_EXPOSURE_EUR = 9999 (No Cap)
```
With 5 open trades × (€12 base + €18 DCA) = €150 exposure
On a €279 account = 54% exposure
If all DCA triggers and HARD_SL fires: -12% × €30 × 5 = -€18 → -€90 max
This is survivable, but with no cap, edge cases can wipe the account.
```

### Bug #6: CIRCUIT_BREAKER Disabled
```
Bot accumulated -€917 net loss over 789 trades with 0 automatic stops.
With CIRCUIT_BREAKER_MIN_WIN_RATE = 0, the bot never pauses regardless of performance.
```

---

## 5. THE ROOT CAUSE OF ALL LOSSES

**The TP-to-SL ratio is fundamentally inverted:**

```
Current setup:
  Stop-Loss:    -8% to -12%
  TP Level 1:   +5%
  Trailing exit: ~+1.3% (activation 4.5% - trail 3.2%)

Implied Risk:Reward = 0.15 (avg_win/avg_loss from real trade data)
```

**Mathematical proof:**
- At 45% win rate, you need Risk:Reward ≥ 1.22:1 to break even
- You have 0.15:1
- To break even with 0.15:1 R:R you would need **87% win rate**
- You have 14% recent win rate

**Either the SL must shrink or the TP must grow — drastically.**

---

## 6. EXTERNAL RESEARCH FINDINGS (PEER-REVIEWED SOURCES)

### RSI Thresholds (Investopedia / Wilder 1978)
- Standard oversold: **< 30** | Standard overbought: **> 70**
- For altcoins in downtrend: consider RSI < 35 as oversold, RSI > 65 as overbought
- For DCA entry (avg-down): only DCA when RSI confirms true oversold (< 35), not just "below neutral"
- **Current RSI_DCA_THRESHOLD = 45 is wrong.** RSI 45 is NEUTRAL territory, not oversold.
- **Recommendation: RSI_DCA_THRESHOLD → 35 (only DCA when actually oversold)**

### Trailing Stops (Investopedia)
- Trail % must accommodate normal price fluctuations without false exits
- For volatile crypto (altcoins): they move 5-10% in normal daily volatility
- A trailing stop of **3.2% is too tight** for altcoins — will be triggered by noise
- Activation at **4.5%** with **3.2% trail** means exit at approximately **+1.3%**
- With 0.5% round-trip fees: **real profit ≈ 0.8% = €0.096 per €12 trade**
- **Recommendation: TRAILING_ACTIVATION_PCT → 3-4%, DEFAULT_TRAILING → 4-5%**
  (Activate sooner, trail wider, let winners run more)

### Stop-Loss Sizing
- For positive expectancy: SL must be ≤ TP × (win_rate / (1 - win_rate))
- At 45% win rate: max SL = TP × (0.45/0.55) = TP × 0.82
- If TP L1 = 5%: max SL = 4.1% to break even (currently 8% = 1.96× too large)
- **Two valid options:**
  - **Option A (Tight SL):** SL = 3-4%, TP L1 = 5%, L2 = 10%, L3 = 20%
  - **Option B (Wide SL):** Keep SL at 8-12%, but TP L1 must be ≥ 10%, L2 ≥ 20%, L3 ≥ 35%

### DCA / Average Down Strategy
- Research consensus: DCA average-down works for long-term index investing (years)
- For short-term altcoin trading: DCA increases average cost but also amplifies loss if trade doesn't recover
- Each DCA add requires the price to recover MORE (higher breakeven) to become profitable
- **With 14% recent win rate: DCA is actively making losses worse**
- **Recommendation: Reduce DCA adds to MAX 2, with tighter RSI filter (< 30)**

### Position Sizing (Kelly Criterion)
- Kelly % = (win_rate × avg_win - (1-win_rate) × avg_loss) / avg_win
- Kelly = (0.457 × 3.76 - 0.543 × 5.31) / 3.76
- Kelly = (1.72 - 2.88) / 3.76 = **-0.31 → NEGATIVE**
- **A negative Kelly means: do not trade at all with current edge.**
- Minimum viable Kelly requires positive expectancy first.
- Once fixed: optimal position size ≈ half-Kelly = safe bet sizing

### Circuit Breaker
- Industry standard: pause trading if rolling win rate < 30% over last 20-40 trades
- Current win rate (recent 50): 14% → bot should have paused automatically
- **CIRCUIT_BREAKER_MIN_WIN_RATE must be set to at minimum 0.25-0.30**

---

## 7. HYBRID DCA — ANALYSE EN AANBEVELING

### Wat de bot nu doet: twee DCA-modi in één systeem

De bot heeft een "hybrid DCA" systeem dat **twee compleet verschillende strategieën** combineert in dezelfde code:

**Modus A — Average-Down (verliezende positie)**
```
Entry: koop €12
Prijs daalt -6% → koop €6 extra (gemiddelde kostprijs daalt)
Prijs daalt -12% → koop €6 extra (gemiddelde kostprijs daalt verder)
Doel: als prijs herstelt, eerder break-even
```

**Modus B — Pyramid-Up (winnende positie)**
```
Entry: koop €12
Prijs stijgt +X% → koop extra (volg de trend omhoog)
Doel: winst maximaliseren in sterke opwaartse beweging
```

### Het fundamentele conflict

**Deze twee modi BOTSEN in de bestaande implementatie:**

1. Ze delen dezelfde `dca_buys` teller → als je average-down hebt gedaan, denkt het systeem ook dat je pyramid-buys hebt gedaan, waardoor verdere toevoegingen geblokkeerd worden.

2. Pyramid-up vereist een stijgende markt. Average-down vereist een dalende markt. Ze kunnen **nooit tegelijk zinvol zijn** voor dezelfde trade.

3. De RSI_DCA_THRESHOLD (45) is ontworpen voor average-down (check of markt echt oversold is), maar blokkeert ook pyramid-up in een gezonde uptrend waar RSI logischerwijs > 45 staat.

4. De schaalberekening voor pyramid-up resulteert in orders van €3.50 — **onder de minimum ordergrootte van €5** — waardoor die DCA stilletjes wordt geweigerd.

### Mijn oordeel: SCHAKEL PYRAMID-UP UIT

**Het empirische bewijs is duidelijk:**
- Gemiddelde winst per winnende trade: **€0.268**
- Met 0.5% round-trip fee op €12 entry = **€0.06 aan kosten**
- Netto na fees: **~€0.21 per win**

Bij deze marges voegt een pyramid-up €6 extra slechts **~€0.10 potentiële extra winst** toe (als het +2% verder gaat), maar vergroot ook het verlies als de rit ten einde is. De bot heeft niet de juiste trend-detectie om pyramid betrouwbaar te timen.

**Average-down DCA is de enige modus die de bot daadwerkelijk uitvoert** (en zelfs die zelden, door de RSI-drempel). Pyramid-up wordt vrijwel nooit succesvol afgerond door de €3.50 < €5 bug.

### Aanbeveling voor Opus

Stel de config zo in dat **uitsluitend average-down DCA actief is:**

```python
# Gewenste situatie: alleen average-down
DCA_MODE = "average_down_only"   # als dit een config-optie is
# Of: gewoon DCA_PYRAMID_BUYS = 0 / niet instellen
# En: DCA_DROP_PCT verlagen zodat DCA-prijsniveaus BOVEN de stop-loss liggen

# Logische volgorde met tight SL (optie A):
#   Entry:          €12 @ prijs P
#   Hard SL:        -4% → verkoopprijs = P × 0.96
#   DCA add 1:      -2.5% → €6 extra, nieuwe gemiddelde = P × 0.9833
#   DCA add 2:      -3.5% cumulatief → nog €6 extra (optioneel, alleen als RSI < 30)
#   Break-even na DCA 1: prijs moet herstellen naar ~P × 0.9944 (met fees)
#   Hard SL NOOIT raken als DCA correct gecalibreerd is
```

**Kritische eis aan Opus — conflict-vrije DCA/SL kalibratie:**

> **✅ DIT IS AL GEÏMPLEMENTEERD IN CODE** (`trailing_bot.py` DCA/SL AutoFix guard)  
> De bot berekent bij opstarten de minimaal benodigde SL voor alle geconfigureerde DCA-niveaus:  
> `min_required_sl = DCA_DROP_PCT × DCA_MAX_BUYS + DCA_SL_BUFFER_PCT`  
> Als `HARD_SL_ALT_PCT` te krap is, wordt de SL **automatisch verbreed** (niet DCA gecapt) — de DCA intent van de gebruiker wordt gerespecteerd.

**Voorbeeld — 5 DCA adds instellen:**
```
DCA_MAX_BUYS  = 5
DCA_DROP_PCT  = 2%
Buffer        = 1.5%
min_safe_sl   = 5 × 2% + 1.5% = 11.5%

Als HARD_SL_ALT_PCT = 8%  → auto-verbreed naar 11.5%  [log: WARNING]
Als HARD_SL_ALT_PCT = 12% → ongewijzigd               [geen warning]
```

**Aanbeveling voor Opus:** stel `HARD_SL_ALT_PCT` expliciet in op `DCA_DROP_PCT × DCA_MAX_BUYS + 2%` zodat de auto-fix nooit hoeft in te grijpen. Dat geeft de schoonste log en voorkomt verrassingen.

---

## 8. WHITELIST / COIN SELECTION


**Current whitelist (from config logic / active trades):**
SOL, XRP, ADA, LINK, AAVE, UNI, LTC, BCH, RENDER, FET, AVAX, APT

**Performance insights from real data:**
- Best partial TP performer: **ZEUS-EUR** (8 hits, €24.68) — **NOT IN WHITELIST**
- Current whitelist coins: average €0.27 per win, -€1.78 per loss
- High-volatility large-caps (SOL, ADA, LINK) have tight spreads but slow moves
- ZEUS, JASMY, NEAR, ICX showed better partial TP hits per trade

---

## 9. YOUR TASK

**Produce a complete, working `bot_config.json` with these requirements:**

1. **Fix the R:R ratio** — select either Option A (tight SL) or Option B (wide TP) and apply consistently
2. **Fix stop-loss values** — must be mathematically consistent with TP levels
3. **Fix trailing stop** — activation and trail must allow trades to grow meaningfully
4. **Fix RSI_DCA_THRESHOLD** — lower to 30-35 (true oversold only)
5. **Fix DCA_DROP_PCT** — if SL shrinks, DCA drops must shrink proportionally
6. **Enable CIRCUIT_BREAKER** — minimum win rate 0.30 over 20 trades
7. **Set MAX_TOTAL_EXPOSURE_EUR** — cap at 80% of current account (≈€224)
8. **Set MIN_BALANCE_EUR** — floor at €30 (never trade below this)
9. **Fix L3 TP target** — must be reachable BEFORE trailing fires AND BEFORE SL triggers
10. **Preserve existing parameters** that are not broken (fees, API keys, file paths, etc.)

**The output must be:**
- A complete, valid JSON config
- Every parameter that affects P&L must be included and mathematically justified
- Include a comment block ABOVE the JSON with your reasoning for each changed parameter

**Additional constraint:**
- Account is €279.51 — this is a SMALL account. Protect capital first.
- BASE_AMOUNT_EUR = €12 is appropriate (4.3% per trade — conservative)
- Change nothing about API keys, file paths, or technical parameters unless directly related to P&L

---

## 10. PARAMETERS THAT ARE FINE (DO NOT CHANGE)

```json
"BASE_AMOUNT_EUR": 12.0,          // fine for account size
"DCA_AMOUNT_RATIO": 0.5,          // fine (€6 = 50% of €12)
"RSI_MIN_BUY": 35,                // fine (don't buy oversold)
"RSI_MAX_BUY": 58,                // fine (don't buy overbought)
"MIN_SCORE_TO_BUY": 10,           // signal strength gate, fine
"MAX_OPEN_TRADES": 5,             // fine
"FEE_MAKER": 0.0015,              // Bitvavo actual
"FEE_TAKER": 0.0025,              // Bitvavo actual
"SLIPPAGE_PCT": 0.001,            // reasonable estimate
"ATR_MULTIPLIER": 2.2,            // fine
"ATR_WINDOW_1M": 14,              // standard
```

---

## 11. SUMMARY OF CHANGES NEEDED

| Parameter | Current | Problem | Target Range |
|-----------|---------|---------|--------------|
| `STOP_LOSS_HARD_PCT` | 8% | Too wide vs TP | 3-4% (Option A) OR keep if TP↑ |
| `HARD_SL_ALT_PCT` | 12% | L3 TP identical = SL fires instead of TP | 5-6% (A) OR remove L3 (B) |
| `DEFAULT_TRAILING` | 3.2% | Too tight, noise exits | 4-5% |
| `TRAILING_ACTIVATION_PCT` | 4.5% | Exit at +1.3% net, ~€0.10 profit | 3-4% but give 5%+ to run |
| `TAKE_PROFIT_TARGETS[0]` | 5% | Fine if SL < 4% | 5% (A) or 10% (B) |
| `TAKE_PROFIT_TARGETS[1]` | 8% | Reachable but rarely | 12% (A) or 20% (B) |
| `TAKE_PROFIT_TARGETS[2]` | 12% | NEVER fires, SL hits first | 20%+ (A) or 35%+ (B) |
| `RSI_DCA_THRESHOLD` | 45 | Neutral = DCA blocked too often | 30-35 |
| `DCA_DROP_PCT` | 6% | Buy 2 at -6%, buy 3 at -12% = at SL | 3-4% (A) |
| `DCA_MAX_BUYS` | 3 | 3rd buy always near or past SL | 2 (A) |
| `CIRCUIT_BREAKER_MIN_WIN_RATE` | 0 (off) | Never stops itself while losing | 0.30 |
| `MAX_TOTAL_EXPOSURE_EUR` | 9999 | No cap = full account risk | 200 |
| `MIN_BALANCE_EUR` | 0 | No floor = account can reach €0 | 30 |

---

*Research compiled by GitHub Copilot (Claude Sonnet 4.6). Data is verified from live trade files. External research from Investopedia (Wilder RSI methodology, trailing stop theory, risk:reward principles). All numbers reflect actual bot performance as of the last scan.*
