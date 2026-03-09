# Bitvavo Bot — Architectuur

## Overzicht

Een geautomatiseerde cryptocurrency trading bot voor het Bitvavo exchange platform.
Budget: ~€250 EUR. Strategie: trailing stop + DCA + signal scoring.

## Data Flow

```
Bitvavo API → get_candles() → indicators (RSI, MACD, EMA, ATR, BB)
                                    ↓
                            signal scoring (modules/signals/)
                                    ↓
                            open_trade_async() [als score ≥ MIN_SCORE_TO_BUY]
                                    ↓
                            trailing stop monitoring (calculate_stop_levels)
                                    ↓
                            place_sell() [bij trailing hit of stop-loss]
```

## Kernbestanden

| Bestand | Regels | Functie |
|---------|--------|---------|
| `trailing_bot.py` | ~6.800 | Hoofdbot: scan, buy, trail, sell, dashboard |
| `ai/ai_supervisor.py` | ~2.900 | AI parameter suggesties + markt scanner |
| `modules/config.py` | ~150 | Config laden + runtime state scheiding |
| `modules/signals/` | ~300 | Protocol-based signal framework (9/10 kwaliteit) |
| `modules/trading_dca.py` | ~650 | DCA (Dollar Cost Averaging) logica |
| `modules/trading_risk.py` | ~365 | Risk management (exposure, stop-loss) |
| `core/indicators.py` | ~200 | Technische indicatoren (RSI, EMA, MACD, ATR) |
| `core/trade_investment.py` | ~190 | Invested EUR berekening (Single Source of Truth) |
| `core/reservation_manager.py` | ~370 | EUR reservering voor meerdere trades |

## Config Systeem

- **Config**: `config/bot_config.json` — alle parameters (statisch)
- **Runtime state**: `data/bot_state.json` — heartbeat, circuit breaker, scan stats
- **Trade log**: `data/trade_log.json` — open + closed trades

Zie [docs/CONFIG_REFERENCE.md](CONFIG_REFERENCE.md) voor alle keys.

## Entry Logica

1. **Circuit breaker check** — pause bij slechte recente performance
2. **HODL market block** — HODL-scheduler markets overslaan
3. **Score check** — minimaal `MIN_SCORE_TO_BUY` (standaard 9.0)
4. **Liquiditeit check** — orderbook depth + spread
5. **Exposure check** — MAX_OPEN_TRADES + MAX_TOTAL_EXPOSURE_EUR
6. **Order plaatsing** — market of limit order via Bitvavo API

## Exit Logica

1. **Trailing stop** — dynamisch op basis van ATR, trend, volume, tijd
2. **Hard stop-loss** — absolute grens (12% alts, 10% BTC/ETH)
3. **Max-age exit** — force close na X dagen
4. **Partial take-profit** — gedeeltelijk verkopen bij TP-levels

## AI Supervisor

- Draait als apart proces (`ai/ai_supervisor.py`)
- Analyseert trades en suggereert parameter aanpassingen
- **Read-only** wanneer `AI_PARAM_LOCK=true` (standaard)
- Schrijft suggesties naar `ai/ai_suggestions.json`

## Dashboard

- Flask-based web dashboard op port 5000
- Real-time trade status, P&L, market scores
- Config editor met save functionaliteit
