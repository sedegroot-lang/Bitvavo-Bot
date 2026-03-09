# Competitive Analysis Prompt – Claude Opus

Kopieer alles vanaf "## PROMPT" en plak het in een nieuw Claude Opus gesprek.

---

## PROMPT (begin hier met kopiëren)

Je bent een senior quantitative trading engineer en crypto-bot specialist. Je taak is om een **diepgaande competitive analyse** uit te voeren: vergelijk mijn zelfgebouwde Bitvavo trading bot met de beste commerciële crypto-bots/platforms op de markt.

**Doe externe research** (zoek het web op) naar de volgende platforms en meer:
- 3Commas (3commas.io)
- Cryptohopper
- Pionex
- Bitsgap
- Coinrule
- Shrimpy
- Zignaly / Zignaly2
- HaasOnline
- TradeSanta
- Wunderbit

Voor elk platform, research:
1. Welke strategieën bieden zij aan?
2. Welke AI/ML functies hebben zij?
3. Wat zijn hun sterke punten?
4. Wat zijn hun zwakke punten / beperkingen?
5. Kosten (subscription fees)?
6. Ondersteunde exchanges?
7. Community / user reviews (bijv. G2, Trustpilot, Reddit)?

---

## MIJN BOT — VOLLEDIGE SPECIFICATIES

### Platform & Setup
- **Exchange:** Bitvavo (Nederlandse EUR-exchange)
- **Taal:** Python (~6.700 regels)
- **OS:** Windows, 24/7 continuous
- **Budget:** ~€250-€300 actief kapitaal
- **Kosten:** Zelfbeheerd, geen maandelijkse abonnement

### Actieve Strategieën (simultaan)
| Strategie | Beschrijving |
|-----------|-------------|
| Trailing Stop Bot | Primaire strategie: koopt op multi-signal score, verkoopt via adaptieve trailing stop |
| DCA (Dollar Cost Averaging) | Max 5 bijkopen per positie, 1.5× size multiplier, 1.2× step multiplier |
| Grid Trading | Actief op BTC-EUR en ETH-EUR (€100/grid, max 2 grids) |
| HODL Scheduler | Wekelijks automatisch €5 BTC + €5 ETH kopen |
| Watchlist Manager | Test nieuwe markten met micro-trades (€5) |
| Partial Take-Profit | 3 niveaus: L1=30% bij +3%, L2=35% bij +3.5%, L3=30% bij +10% |

### Signal Scoring Systeem (0-15+ punten, drempel = 9.0)
| Signal | Gewicht |
|--------|---------|
| Range breakout (consolidatie → uitbraak) | 3.0 |
| Volume breakout (volume spike + ATR expansie) | 3.0 |
| Mean reversion (Z-score < -1.5 + RSI < 50) | 3.0 |
| Technical analysis (EMA crossover + trend alignment) | 3.0 |
| XGBoost ML confidence | Bonus |

### Entry Filters
- RSI range: 20-58
- Min volume: 5.0
- Max spread: 2%
- Momentum filter: -12
- Per-markt win rate filter (automatisch slechte markten uitsluiten)

### Adaptieve Trailing Stop (10 lagen)
1. Hard stop: 12% onder buy (alts), 10% (BTC/ETH)
2. Trailing activatie: +2.2% winst
3. 8 stepped niveaus: 1.2% trail → 0.3% trail (strakker naarmate winst stijgt)
4. ATR-based trailing distance
5. Trend-adjusted: bullish = losser, bearish = strakker
6. Profit velocity: Snelle stijgers krijgen meer ruimte
7. Time decay: Strakker na 24/48/72 uur
8. Volume-weighted: Hoog volume = strakker
9. Multi-timeframe consensus: 5m / 15m / 1h
10. Floor rule: Trailing ≥ hard stop ≥ buy price

### AI/ML Stack
| Component | Detail |
|-----------|--------|
| XGBoost model | Getraind op 1m candles, lookahead 20, feature engineering |
| LSTM neural network | Price prediction, confidence threshold 0.65 |
| Reinforcement Learning | Q-learning agent, epsilon 0.05 |
| Ensemble | XGB (1.0) + LSTM (0.9) + RL (0.7) gewogen |
| AI Supervisor | Past config-parameters automatisch aan op basis van live performance |
| Sentiment analysis | Geïntegreerd in signaalscoring |
| Market regime detection | Bull/bear/sideways regime detectie |
| Auto-retrain | Automatische hertraining bij performance degradatie |

### Risk Management
- Max open trades: configureerbaar (standaard 5-8)
- Segment limits: alts max €100, majors max €120, stable max €30
- Hard stop loss op alle posities
- Reservatie-systeem: voorkomt dubbele aankopen per markt
- Saldo guard: voorkomt overexposure

### Whitelist (20 altcoins)
SOL, XRP, ADA, AVAX, LINK, NEAR, SUI, APT, DOT, ATOM, AAVE, UNI, LTC, BCH, RENDER, FET, DOGE, OP, ARB, INJ

### Technische Infrastructuur
- Streamlit dashboard (real-time monitoring)
- Health check endpoints
- Thread-safe LRU cache met TTL
- Telegram notificaties
- Automatische backup systeem
- Docker support
- 35 unit tests

### Historische Performance (echte data, 93 dagen)
| Metric | Waarde |
|--------|--------|
| Totaal trades | 780 |
| Strategie P&L (zonder bugs) | +€795.89 (72.8% win rate, 494 trades) |
| Bug-gerelateerde P&L | -€1.710.66 (273 trades: force-sells door bugs) |
| Netto resultaat | ~-€900 (bugs gecorrigeerd, strategie nu winstgevend) |
| Partial TP winst | ~€750 gerealiseerd |

**Belangrijk:** De strategie zelf is WINSTGEVEND (+72.8% win rate). Historische verliezen kwamen door bugs (force-sell bij saldo-fouten) die inmiddels opgelost zijn.

---

## JOUW OPDRACHT

### Stap 1: Research (externen bronnen raadplegen)
Zoek actuele informatie op over alle genoemde platforms. Gebruik recente bronnen (2024-2026). Kijk naar:
- Officiële websitepagina's
- Gebruikersreviews op Trustpilot, G2, Reddit (r/algotrading, r/CryptoHopper, etc.)
- Vergelijkingsartikelen (bijv. Investopedia, CoinBureau, etc.)

### Stap 2: Vergelijkingstabel maken

Maak een grote vergelijkingstabel met de volgende kolommen:
- Platform naam
- Prijs (per maand)
- Ondersteunde exchanges
- DCA strategie
- Grid trading
- Trailing stop
- AI/ML functies
- Backtesting
- Paper trading
- Community/support kwaliteit
- Bitvavo-support (ja/nee)
- Algemene beoordeling (1-10)

### Stap 3: Diepgaande vergelijking met mijn bot

Voor elk platform, beantwoord:
1. **Wat kan dit platform wat mijn bot NIET kan?** (eerlijk, specifiek)
2. **Wat kan mijn bot wat dit platform NIET kan?** (eerlijk, specifiek)
3. **Welk platform zou mijn bot op basis van functies het dichtst benaderen?**

### Stap 4: Sterke en zwakke punten van mijn bot

Op basis van de vergelijking:
- **Wat zijn de unieke sterktes van mijn bot** t.o.v. commerciële alternatieven?
- **Waar schiet mijn bot tekort** t.o.v. commerciële alternatieven?
- **Welke functies van commerciële platforms zou ik moeten implementeren** om competitief te zijn?

### Stap 5: Eindoordeel

Geef een eerlijk eindoordeel:
- Is mijn bot vergelijkbaar met (of beter dan) betaalde alternatieven?
- Op welk niveau zit mijn bot: amateur hobby-bot / serieuze bot / professioneel niveau?
- Wat is de meest waardevolle volgende stap om de bot te verbeteren?

---

## OUTPUTFORMAAT

Gebruik duidelijke headers, tabellen en bullet points. Wees eerlijk en kritisch — ik wil de waarheid, niet alleen complimenten. Als mijn bot ergens slecht scoort, zeg dat dan direct.

Antwoordtaal: **Nederlands**

---

*(einde prompt)*
