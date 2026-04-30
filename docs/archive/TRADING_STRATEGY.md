# Bitvavo Bot — Trading Strategie

## Strategie Overzicht

De bot combineert **momentum signals** met **trailing stops** en **DCA** om in
volatiele crypto-markten te handelen met een budget van ~€250.

## Signal Scoring

De bot scoort markten op een schaal van 0-15+ punten:

| Signal | Gewicht | Beschrijving |
|--------|---------|-------------|
| Range breakout | 3.0 | Prijs breekt uit range na consolidatie |
| Volume breakout | 3.0 | Volume spike + ATR expansie |
| Mean reversion | 3.0 | Z-score < -1.5 + RSI < 50 |
| Technical analysis | 3.0 | EMA crossover + trend alignment |
| AI XGBoost | bonus | ML model confidence als extra score |

**Drempel**: `MIN_SCORE_TO_BUY = 9.0` — minimaal 3 signalen moeten overeenkomen.

## Entry Filters

| Filter | Config Key | Waarde |
|--------|-----------|--------|
| RSI range | `RSI_MIN_BUY` / `RSI_MAX_BUY` | 20 - 58 |
| Min volume | `MIN_AVG_VOLUME_1M` | 5.0 |
| Max spread | `MAX_SPREAD_PCT` | 2% |
| Momentum filter | `MOMENTUM_FILTER_THRESHOLD` | -12 |
| Performance filter | `MARKET_PERFORMANCE_FILTER_ENABLED` | Per-markt win rate |

## Trailing Stop Systeem

De trailing stop is **adaptief** met 10 lagen:

1. **Hard stop**: 12% onder buy (alts), 10% (BTC/ETH)
2. **Activatie**: Trailing start bij +2.2% winst
3. **Stepped levels**: 8 niveaus van 1.2% trail → 0.3% trail
4. **ATR-based**: Trailing afstand = ATR × multiplier
5. **Trend-adjusted**: Bullish = losser, bearish = strakker
6. **Profit velocity**: Snelle stijgers krijgen meer ruimte
7. **Time decay**: Strakker na 24/48/72 uur
8. **Volume-weighted**: Hoog volume = strakker
9. **Multi-timeframe**: 5m/15m/1h consensus
10. **Floor rule**: Trailing ≥ hard stop ≥ buy price

## DCA (Dollar Cost Averaging)

| Parameter | Waarde | Beschrijving |
|-----------|--------|-------------|
| `DCA_ENABLED` | true | DCA actief |
| `DCA_DROP_PCT` | 6% | Bijcall na 6% daling |
| `DCA_MAX_BUYS` | 5 | Max 5 bijkopen |
| `DCA_AMOUNT_EUR` | €5 | Bedrag per bijkoop |
| `DCA_SIZE_MULTIPLIER` | 1.5× | Elke bijkoop 1.5× groter |
| `DCA_STEP_MULTIPLIER` | 1.2× | Elke stap 1.2× dieper |

## Partial Take-Profit

Winst wordt in 3 stappen genomen:

| Level | Target | Sell % |
|-------|--------|--------|
| TP1 | +2.5% | 30% |
| TP2 | +5.5% | 35% |
| TP3 | +10% | 35% |

## Circuit Breaker

Pauzeert nieuwe trades bij slechte performance:
- **Trigger**: Win rate < 25% over laatste 20 trades
- **Cooldown**: 60 minuten
- **Grace period**: 5 trades na cooldown voordat re-evaluatie

## Risk Management

| Parameter | Waarde |
|-----------|--------|
| Max open trades | 4 |
| Max total exposure | €9999 |
| Base trade amount | €12 |
| Position Kelly factor | 0.3 |
