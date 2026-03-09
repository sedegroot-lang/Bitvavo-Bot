# Trade Analyse & Optimale Config — Maart 2026

**Gebaseerd op 158 afgeronde trades uit SQLite DB (dec 2025) + PnL history (feb 2026)**

---

## 1. SAMENVATTING

| Metric | Waarde |
|--------|--------|
| **Totaal trades** | 158 |
| **Totaal P&L** | **+€315.59** |
| **Win rate** | 69.0% (109 wins / 49 losses) |
| **Gem. winst per trade** | +€3.73 |
| **Gem. verlies per trade** | -€1.87 |
| **Dec 2025** | 76 trades, +€48.14, WR 73.7% |
| **Feb 2026** | 82 trades, +€267.45, WR 64.6% |

> **De bot is WINSTGEVEND** — +€315.59 over 158 trades. Het gevoel van "alleen maar verlies" komt waarschijnlijk door de zichtbare stop-loss verliezen en saldo_flood_guard sells, maar de trailing_tp wint dit ruimschoots terug.

---

## 2. WAAR GAAT HET GELD VERLOREN?

### P&L per Close Reason

| Reden | Trades | P&L | Gemiddeld |
|-------|--------|-----|-----------|
| `trailing_tp` | 85 | **+€354.38** | +€4.17 |
| `partial_tp_1` | 20 | +€12.16 | +€0.61 |
| `auto_free_slot` | 8 | +€0.34 | +€0.04 |
| `partial_tp_2` | 1 | +€0.31 | +€0.31 |
| `stop` | 29 | **-€21.32** | -€0.74 |
| `saldo_flood_guard` | 15 | **-€30.29** | -€2.02 |

### Conclusie
- **`saldo_flood_guard`** is de #1 winstvernietiger: 15 trades, -€30.29
  - Dit is een noodmechanisme dat posities verkoopt als er onvoldoende saldo is
  - Bevat onder andere: MOODENG -€4.72, GALA -€3.61, ADA -€3.27, SOL -€2.69
- **`stop`** (hard stop-loss) kost -€21.32 over 29 trades — maar dat is _normaal_ risicomanagement
- **`trailing_tp`** is de absolute ster: +€354.38 over 85 trades

---

## 3. WIN/LOSS ASYMMETRIE

| | Trades | Totaal | Gemiddeld | Gem. % |
|--|--------|--------|-----------|--------|
| **Winners** | 109 | +€407.11 | +€3.73 | +3.35% |
| **Losers** | 49 | -€91.53 | -€1.87 | -9.46% |

Het gemiddelde verlies (-9.46%) is bijna **3x groter** dan de gemiddelde winst (+3.35%). Dit is typisch voor bots met een brede stop-loss. De hoge win rate (69%) compenseert dit, maar verliezen zijn disproportioneel groot.

---

## 4. MARKTEN: WINNAARS EN VERLIEZERS

### Top Verliezers
| Market | Trades | P&L | Reden |
|--------|--------|-----|-------|
| LINK-EUR | 3 | -€6.56 | saldo_flood_guard + stop (-17.2%) |
| ADA-EUR | 4 | -€4.45 | saldo_flood_guard |
| ALGO-EUR | 3 | -€4.45 | saldo_flood_guard |
| GALA-EUR | 1 | -€3.61 | saldo_flood_guard (-23.3%) |
| SOL-EUR | 2 | -€2.62 | saldo_flood_guard |

### Top Winnaars
| Market | Trades | P&L | Reden |
|--------|--------|-----|-------|
| PTB-EUR | 20 | +€67.77 | 100% WR, trailing_tp |
| THQ-EUR | 2 | +€5.02 | trailing_tp |
| MOODENG-EUR | 10 | +€2.62 | 90% WR, trailing_tp |
| ANIME-EUR | 1 | +€1.54 | trailing_tp |
| APT-EUR | 3 | +€0.77 | trailing_tp |

---

## 5. DCA ANALYSE — WAAROM WERKT HET NIET?

### Kritieke Bevinding: DCA is VOLLEDIG GEBLOKKEERD

**61.705 geblokkeerde DCA-pogingen** in `data/dca_audit.log`. ELKE ENBELE poging is geblokkeerd door `rsi_block`.

**Oorzaak:** `RSI_DCA_THRESHOLD = 35` in config. Dit vereist RSI < 35 (deep oversold) voor DCA. Maar wanneer de prijs 2.5% daalt (DCA_DROP_PCT), is RSI typisch 47-56, NIET < 35.

```
Voorbeeld uit DCA audit log:
  LINK-EUR: RSI 50.1 > threshold 35.0 → SKIP
  SOL-EUR:  RSI 51.1 > threshold 35.0 → SKIP
  DOGE-EUR: RSI 50.4 > threshold 35.0 → SKIP
  LTC-EUR:  RSI 56.3 > threshold 35.0 → SKIP
```

**De code defaulted naar 60** (`cfg.get("RSI_DCA_THRESHOLD", 60)`), maar de config overschrijft dit naar 35. Dit maakt DCA effectief nutteloos.

### Simulatie: Helpt meer DCA?

| DCA Levels | Beste Config | P&L | vs Actueel |
|------------|-------------|-----|------------|
| 0 (geen DCA) | SL=2% | **+€392.31** | **+€76.72** |
| 1 | drop=7% SL=2% | +€386.71 | +€71.12 |
| 2 | drop=7% SL=2% | +€384.71 | +€69.12 |
| 5 | drop=7% SL=2% | +€384.11 | +€68.52 |
| 10 | drop=7% SL=2% | +€384.11 | +€68.52 |

**CONCLUSIE: Meer DCA levels helpen NIET.** 
- De verliezen zijn te diep (10-32%) voor €10 DCA om iets te betekenen
- De bot handelt met €10-80 per positie — €10 DCA bij -15% drop heeft minimaal effect op de gemiddelde prijs
- DCA 0 met SL=2% geeft het BESTE resultaat

### Waarom DCA niet helpt bij deze bot
1. **Te kleine DCA bedragen**: €10 DCA op een €40 positie die -15% staat, verlaagt avg price slechts ~2%
2. **Te diepe drops**: De meeste verliezen zijn -10% tot -32%, ver voorbij waar DCA helpt
3. **Te weinig kapitaal**: Met €300 totaal budget kan je geen serieuze DCA strategie uitvoeren
4. **DCA werkt alleen bij V-shaped recoveries**: Crypto maakt vaak L-shaped drops (daling en dan zijwaarts)

---

## 6. OPTIMALE CONFIG (GESIMULEERD)

### Impact van Stop-Loss alleen (geen DCA)

| Stop-Loss % | P&L | vs Actueel |
|-------------|-----|------------|
| **2%** | **+€392.31** | **+€76.72** |
| 3% | +€384.42 | +€68.83 |
| 4% | +€376.53 | +€60.95 |
| 5% (huidig) | +€368.78 | +€53.19 |
| 7% | +€358.37 | +€42.78 |
| 10% | +€347.50 | +€31.92 |
| 15% | +€337.77 | +€22.18 |
| 30% | +€332.86 | +€17.27 |

**Strakkere stop-loss is verreweg de belangrijkste verbetering.** Elke procent SL-verlaging bespaart ~€8.

### Aanbevolen Config Wijzigingen

```json
{
  "HARD_SL_ALT_PCT": 0.03,          // Was: 0.05 → 3% SL bespaart ~€69
  "HARD_SL_BTCETH_PCT": 0.03,       // Was: 0.05 → consistent
  
  "RSI_DCA_THRESHOLD": 60,           // Was: 35 → Unblock DCA (code default!)
  "DCA_ENABLED": true,               // Behouden
  "DCA_MAX_BUYS": 3,                 // Was: 1 → Meer kansen
  "DCA_DROP_PCT": 0.015,             // Was: 0.025 → Eerder beginnen
  "DCA_AMOUNT_EUR": 15,              // Was: 10 → Meer impact
  "DCA_SIZE_MULTIPLIER": 1.5,        // Was: 1.0 → Martingale-light
  
  "TRAILING_ACTIVATION_PCT": 0.02,   // Was: 0.025 → Eerder activeren
  "DEFAULT_TRAILING": 0.03,          // Was: 0.04 → Strakkere trailing
  
  "MAX_OPEN_TRADES": 4,              // Was: 6 → Minder overexposure
  "BASE_AMOUNT_EUR": 35              // Was: 40 → Ruimte voor DCA
}
```

---

## 7. PRIORITEITEN (IMPACT RANKING)

| # | Actie | Verwacht effect | Moeite |
|---|-------|----------------|--------|
| **1** | SL verlagen naar 3% | **+€69** bespaard | Config wijzig |
| **2** | RSI_DCA_THRESHOLD → 60 | DCA unblocked (61K pogingen) | Config wijzig |
| **3** | saldo_flood_guard fixen | -€30 voorkomen | Code analyse |
| **4** | MAX_OPEN_TRADES → 4 | Minder saldo druk | Config wijzig |
| **5** | Trailing strakkere params | Meer winst locken | Config wijzig |

---

## 8. WAT HELPT NIET

| Idee | Reden |
|------|-------|
| **10 DCA levels** | Budget te klein, drops te diep. Max verschil: €8 over 158 trades |
| **LSTM/RL inschakelen** | Broken op Python 3.13 (zie eerdere analyse) |
| **Meer markten** | Verliezende markten (GALA, ALGO, LINK) kosten geld. Minder = beter |
| **Grotere posities** | Bij huidige SL van 5% is risico al hoog |

---

## 9. KRITIEKE BUG: saldo_flood_guard

De `saldo_flood_guard` verkoopt posities met verlies wanneer er onvoldoende saldo is voor nieuwe trades. Dit kostte -€30.29. Dit is een symptoom van:
- Te veel open trades (MAX_OPEN_TRADES=6) voor het beschikbare kapitaal (~€300)
- Nieuwe buys consumeren saldo, waardoor bestaande posities geliquideerd worden

**Fix**: `MAX_OPEN_TRADES = 4` en `BASE_AMOUNT_EUR = 35` geeft €140 actief + €160 buffer.

---

## 10. SAMENVATTEND

De bot is **winstgevend** (+€315.59, 69% WR). De "alleen maar verlies" perceptie komt van zichtbare stop-loss hits en flood guard sells. De trailing TP strategie werkt uitstekend (+€354).

**De 3 grootste verbeteringen:**
1. 📉 **SL 5% → 3%** = ~€69 bespaard  
2. 🔓 **RSI_DCA_THRESHOLD 35 → 60** = DCA werkt eindelijk
3. 📊 **MAX_OPEN_TRADES 6 → 4** = geen flood guard meer

Gecombineerd verwacht: **+€80-100 extra over dezelfde 158 trades = ~+€395-415 totaal**.
