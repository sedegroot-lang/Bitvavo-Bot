# Configuratie Referentie

Alle instellingen van `config/bot_config.json` op een rij.
De meeste hiervan zijn ook te wijzigen via het dashboard (⚙️ Instellingen), maar sommige geavanceerde opties staan alleen in dit bestand.

> **Bewerken:** open `config/bot_config.json` in een teksteditor, of pas waarden aan via het dashboard.
> De bot herlaadt de config automatisch (standaard elke 60 seconden).

---

## Technische Indicatoren

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SMA_SHORT` | 7 | Korte Simple Moving Average periode (in candles). Gebruikt voor trendrichting. |
| `SMA_LONG` | 25 | Lange SMA periode. Kruising met SMA_SHORT geeft koopsignaal. |
| `MACD_FAST` | 8 | Snelle EMA voor MACD berekening. |
| `MACD_SLOW` | 26 | Trage EMA voor MACD berekening. |
| `MACD_SIGNAL` | 9 | Signaallijn periode voor MACD. |
| `BREAKOUT_LOOKBACK` | 20 | Aantal candles om terug te kijken voor breakout detectie. |
| `ATR_WINDOW_1M` | 14 | ATR (Average True Range) venster op 1min candles. |
| `ATR_MULTIPLIER` | 2.2 | Vermenigvuldiger voor ATR. Hogere waarde = ruimere stops. |
| `BOLLINGER_WINDOW` | 20 | Venster voor Bollinger Bands berekening. |
| `STOCHASTIC_WINDOW` | 14 | Venster voor Stochastic oscillator. |
| `ATR_PERIOD` | 14 | Standaard ATR periode (generiek). |

**Advies:** laat deze staan tenzij je de technische analyse goed begrijpt. De standaardwaarden werken voor de meeste markten.

---

## Signaal Modules

De bot combineert meerdere signaalmodules om een koopscore te berekenen.

### Globaal

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SIGNALS_GLOBAL_WEIGHT` | 1.0 | Globale vermenigvuldiger voor alle signaalsystemen. 1.0 = normaal. |
| `SIGNALS_DEBUG_LOGGING` | true | Extra logging voor signaalberekeningen aan/uit. |

### Range Signaal

Detecteert zijwaartse markten en koopt bij de onderkant van de range.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SIGNALS_RANGE_ENABLED` | true | Range-detectie module aan/uit. |
| `SIGNALS_RANGE_LOOKBACK` | 50 | Aantal candles om terug te kijken voor range bepaling. |
| `SIGNALS_RANGE_THRESHOLD` | 0.3 | Drempelwaarde voor range breedte (lager = strengere detectie). |
| `SIGNALS_RANGE_RSI_PERIOD` | 14 | RSI periode binnen range module. |
| `SIGNALS_RANGE_RSI_MAX` | 50 | Maximale RSI om als koopsignaal te tellen in range. |

### Volume Breakout Signaal

Koopt bij prijsuitbraak met hoog volume.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SIGNALS_VOL_BREAKOUT_ENABLED` | true | Volume breakout module aan/uit. |
| `SIGNALS_VOL_ATR_WINDOW` | 14 | ATR venster voor volatiliteitsmeting. |
| `SIGNALS_VOL_ATR_MULT` | 1.8 | ATR vermenigvuldiger voor breakout drempel. |
| `SIGNALS_VOL_VOLUME_WINDOW` | 60 | Aantal candles voor gemiddeld volume. |
| `SIGNALS_VOL_VOLUME_SPIKE` | 2.0 | Volume moet X keer het gemiddelde zijn voor een spike. |

### Mean Reversion Signaal

Koopt als de prijs ver onder het gemiddelde is gedaald (oversold bounce).

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SIGNALS_MEAN_REV_ENABLED` | true | Mean reversion module aan/uit. |
| `SIGNALS_MEAN_REV_WINDOW` | 45 | Lookback venster voor gemiddelde berekening. |
| `SIGNALS_MEAN_REV_Z` | -1.5 | Z-score drempel (negatiever = diepere dip vereist). |
| `SIGNALS_MEAN_REV_RSI_MAX` | 50 | Max RSI voor koopsignaal. |
| `SIGNALS_MEAN_REV_RSI_PERIOD` | 14 | RSI periode. |
| `SIGNALS_MEAN_REV_MA` | 20 | Moving average periode voor mean berekening. |

### Technische Analyse Signaal

Gecombineerd signaal op basis van MA crossover, EMA trend en RSI.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SIGNALS_TA_ENABLED` | true | TA signaalmodule aan/uit. |
| `SIGNALS_TA_SHORT_MA` | 7.5 | Korte MA voor crossover signaal. |
| `SIGNALS_TA_LONG_MA` | 21 | Lange MA voor crossover signaal. |
| `SIGNALS_TA_EMA` | 34 | EMA periode voor trendfilter. |
| `SIGNALS_TA_RSI_PERIOD` | 14 | RSI periode binnen TA module. |

---

## Entry (instappen)

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `MIN_SCORE_TO_BUY` | 7.0 | Minimale AI-score om te kopen (schaal 0-10). Hoger = strenger, minder trades. **Advies: 5-7 voor actief traden, 8+ voor conservatief.** |
| `RSI_MIN_BUY` | 35 | Minimale RSI om te mogen kopen. Voorkomt kopen in vrije val. |
| `RSI_MAX_BUY` | 65 | Maximale RSI om te mogen kopen. Voorkomt kopen op de top. |
| `MIN_AVG_VOLUME_1M` | 5.0 | Minimaal gemiddeld volume op 1min candles (absoluut). Filtert illiquide munten. |
| `MAX_SPREAD_PCT` | 0.02 | Maximale bid-ask spread (2%). Boven deze waarde wordt niet gekocht. |
| `TRAILING_ENTRY_ENABLED` | true | Trailing entry aan/uit. Wacht op een kleine dip na koopsignaal voor betere instap. |
| `TRAILING_ENTRY_PULLBACK_PCT` | 0.012 | Grootte van de dip (1.2%) waarna de entry wordt geplaatst. |
| `TRAILING_ENTRY_TIMEOUT_S` | 180 | Als de dip er niet komt binnen 3 minuten, wordt alsnog gekocht. |
| `MOMENTUM_FILTER_ENABLED` | true | Voorkomt kopen als het 24h-momentum te negatief is. |
| `MOMENTUM_FILTER_THRESHOLD` | -8 | Drempel (in %). Onder -8% dagsverandering wordt niet gekocht. |

---

## Positiebeheer

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `BASE_AMOUNT_EUR` | 38.0 | Standaard bedrag per trade in euro. **Pas dit aan op je budget.** |
| `MAX_OPEN_TRADES` | 2 | Maximaal aantal gelijktijdige posities. **Advies: start met 2-3, verhoog als je budget groeit.** |
| `MAX_TOTAL_EXPOSURE_EUR` | 9999 | Maximale totale blootstelling in euro. Veiligheidsplafond. |
| `MIN_BALANCE_EUR` | 0 | Minimaal EUR saldo dat altijd vrij moet blijven. |
| `MIN_ORDER_EUR` | 5.0 | Minimale ordergrootte (Bitvavo vereist €5 minimum). |
| `MIN_ENTRY_EUR` | 5.0 | Minimum bedrag voor een entry trade. |
| `MAX_ENTRY_EUR` | 9999.0 | Maximum bedrag per entry. |
| `MAX_POSITION_SIZE` | 9999 | Maximale positiegrootte in euro. |
| `POSITION_KELLY_FACTOR` | 0.3 | Kelly criterium factor voor positiegrootte (0.3 = 30% van Kelly optimum). |
| `MAX_MARKETS_PER_SCAN` | 25 | Hoeveel markten per scan-cyclus bekeken worden. |
| `SLEEP_SECONDS` | 25 | Wachttijd tussen scan-cycli in seconden. |
| `OPEN_TRADE_COOLDOWN_SECONDS` | 120 | Minimale wachttijd tussen nieuwe trades (voorkomt overtrading). |
| `MAX_TRADES_PER_SCAN_CYCLE` | 1 | Max trades per scan ronde. Voorkomt dat de bot in één keer alles koopt. |

---

## Trailing Stop (verkopen)

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `DEFAULT_TRAILING` | 0.025 | Standaard trailing stop percentage (2.5%). Als de prijs 2.5% daalt vanaf de top, wordt verkocht. **Advies: 2-4% voor altcoins.** |
| `TRAILING_ACTIVATION_PCT` | 0.015 | De prijs moet eerst 1.5% stijgen voordat de trailing stop actief wordt. |
| `EXIT_MODE` | "trailing_only" | Hoe verkocht wordt. Opties: `trailing_only`, `smart`, `hybrid`. |

### Stepped Trailing (geavanceerd)

De trailing stop wordt strakker naarmate de winst groeit. Elk level is `[minimale_winst, trailing_percentage]`.

| `STEPPED_TRAILING_LEVELS` | standaard | Beschrijving |
|---|---|---|
| `[0.015, 0.012]` | Level 1 | Bij 1.5% winst: trailing van 1.2% |
| `[0.03, 0.01]` | Level 2 | Bij 3% winst: trailing van 1.0% |
| `[0.05, 0.008]` | Level 3 | Bij 5% winst: trailing van 0.8% |
| `[0.08, 0.006]` | Level 4 | Bij 8% winst: trailing van 0.6% |
| `[0.12, 0.005]` | Level 5 | Bij 12% winst: trailing van 0.5% |
| `[0.18, 0.004]` | Level 6 | Bij 18% winst: trailing van 0.4% |
| `[0.25, 0.003]` | Level 7 | Bij 25% winst: trailing van 0.3% |

**Advies:** dit is een van de sterkste features. Hoe meer winst, hoe strakker de stop. Zo bescherm je grote winsten.

---

## Stop Loss

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `STOP_LOSS_ENABLED` | false | Harde stop loss aan/uit. **Staat standaard uit: trailing stop beschermt al.** |
| `ENABLE_STOP_LOSS` | false | Alternatieve toggle (dezelfde functie). |
| `STOP_LOSS_HARD_PCT` | 0.25 | Harde stop op 25% verlies. |
| `HARD_SL_ALT_PCT` | 0.25 | Stop loss percentage voor altcoins. |
| `HARD_SL_BTCETH_PCT` | 0.25 | Stop loss percentage voor BTC en ETH (grotere munten). |
| `STOP_LOSS_TIME_DAYS` | 14 | Na X dagen zonder herstel: verkopen. |
| `STOP_LOSS_TIME_PCT` | 0.25 | Verliesdrempel voor tijdgebonden stop loss. |
| `STOP_LOSS_PERCENT` | 0.25 | Generieke stop loss waarde. |
| `DCA_SL_BUFFER_PCT` | 0.04 | Extra buffer (4%) onder laatste DCA niveau voor stop loss. |

---

## DCA (Dollar Cost Averaging / Bijkopen)

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `DCA_ENABLED` | true | DCA bijkopen aan/uit. **Sterk aanbevolen aan te laten.** |
| `DCA_MAX_BUYS` | 9 | Maximaal aantal bijkooporders per positie. |
| `DCA_MAX_BUYS_PER_ITERATION` | 3 | Max DCA orders per scan cyclus (voorkomt spammen). |
| `DCA_DROP_PCT` | 0.02 | Prijsdaling (2%) vereist tussen DCA niveaus. |
| `DCA_AMOUNT_EUR` | 30.4 | Bedrag per DCA bijkoop in euro. |
| `DCA_AMOUNT_RATIO` | 0.8 | Ratio van DCA bedrag t.o.v. base amount. |
| `DCA_SIZE_MULTIPLIER` | 0.8 | Vermenigvuldiger voor DCA ordergrootte. Onder 1.0 = afnemende DCA grootte. **Advies: 0.8-1.2.** |
| `DCA_STEP_MULTIPLIER` | 1.0 | Vermenigvuldiger voor afstand tussen DCA levels. Boven 1.0 = toenemende afstand. |
| `DCA_DYNAMIC` | false | Dynamische DCA op basis van volatiliteit. |
| `DCA_HYBRID` | false | Hybride DCA mode (combineert vaste en dynamische levels). |
| `RSI_DCA_THRESHOLD` | 100 | RSI drempel voor DCA (100 = geen RSI filter, altijd bijkopen). |
| `SMART_DCA_ENABLED` | false | Slimme DCA die rekening houdt met marktomstandigheden. |

### DCA Pyramid (geavanceerd)

Piramide-bijkopen: extra kopen als de positie al in de winst staat.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `DCA_PYRAMID_UP` | false | Piramide bijkopen aan/uit. **Risicovol, alleen voor ervaren gebruikers.** |
| `DCA_PYRAMID_MIN_PROFIT_PCT` | 0.04 | Minimale winst (4%) voordat piramide actief wordt. |
| `DCA_PYRAMID_SCALE_DOWN` | 0.5 | Elke piramide order is 50% van de vorige. |
| `DCA_PYRAMID_MAX_ADDS` | 0 | Max aantal piramide toevoegingen (0 = uit). |

---

## Partial Take Profit

Verkoop een deel van je positie bij bepaalde winstdoelen. De rest rijdt verder met de trailing stop.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `TAKE_PROFIT_ENABLED` | true | Partial take-profit aan/uit. |
| `TAKE_PROFIT_TARGET_1` | 0.03 | Eerste target: 3% winst → verkoop 30%. |
| `TAKE_PROFIT_TARGET_2` | 0.06 | Tweede target: 6% winst → verkoop 35%. |
| `TAKE_PROFIT_TARGET_3` | 0.10 | Derde target: 10% winst → verkoop 35%. |
| `TAKE_PROFIT_TARGET_4` | 0.12 | Vierde target: 12% winst → verkoop 20%. |
| `TAKE_PROFIT_TARGET_5` | 0.20 | Vijfde target: 20% winst → verkoop 25%. |
| `PARTIAL_TP_SELL_PCT_1` | 0.30 | % van positie verkopen bij target 1. |
| `PARTIAL_TP_SELL_PCT_2` | 0.35 | % van positie verkopen bij target 2. |
| `PARTIAL_TP_SELL_PCT_3` | 0.35 | % van positie verkopen bij target 3. |
| `PARTIAL_TP_SELL_PCT_4` | 0.20 | % van positie verkopen bij target 4. |
| `PARTIAL_TP_SELL_PCT_5` | 0.25 | % van positie verkopen bij target 5. |
| `ADAPTIVE_TP_ENABLED` | true | Past targets automatisch aan op basis van volatiliteit. |
| `ADAPTIVE_EXIT_ENABLED` | true | Slimme exit strategie op basis van marktomstandigheden. |
| `TAKE_PROFIT_TARGET` | 0.015 | Globaal take profit doel (gebruikt als fallback). |
| `MIN_PROFIT_PCT` | 1.0 | Minimale winst in % voordat verkocht mag worden. |

**Advies:** partial take profit is een krachtige feature. Je pakt gegarandeerd winst mee, terwijl een deel van je positie verder kan stijgen.

---

## Herinvesteren van winst

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `REINVEST_ENABLED` | true | Herinvesteer winst automatisch door trade-grootte te verhogen. |
| `REINVEST_PORTION` | 0.5 | 50% van de winst wordt hergeïnvesteerd. |
| `REINVEST_MAX_INCREASE_PCT` | 0.2 | Maximale verhoging van 20% per keer. |
| `REINVEST_MIN_TRADES` | 3 | Minimaal 3 trades nodig voordat herinvesteren start. |
| `REINVEST_MIN_PROFIT` | 3.0 | Minimaal €3 winst voor herinvestering. |
| `REINVEST_CAP` | 25.0 | Maximale herinvestering per trade in euro. |
| `RECYCLE_PROFIT_CAP` | 50 | Winst recycling plafond. |

---

## Balans & Budget

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `AUTO_USE_FULL_BALANCE` | false | Gebruik automatisch je volledige balans. **Advies: uit laten.** |
| `FULL_BALANCE_PORTION` | 0.95 | Als bovenstaande aan: gebruik 95% van de balans. |
| `FULL_BALANCE_MAX_EUR` | 2000.0 | Maximum bij full balance mode. |
| `FEE_TAKER` | 0.0025 | Bitvavo taker fee (0.25%). |
| `FEE_MAKER` | 0.0015 | Bitvavo maker fee (0.15%). |
| `SLIPPAGE_PCT` | 0.001 | Verwachte slippage (0.1%). |
| `MIN_BALANCE_RESERVE` | 0 | Minimaal saldo reserve in euro. |

### Budget Verdeling

Hoe het budget verdeeld wordt tussen Trailing Bot en Grid Bot.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `BUDGET_RESERVATION.enabled` | true | Budget verdeling aan/uit. |
| `BUDGET_RESERVATION.mode` | "dynamic" | Verdelingsmodus: `dynamic` of `fixed`. |
| `BUDGET_RESERVATION.trailing_pct` | 75 | % van budget voor Trailing Bot. |
| `BUDGET_RESERVATION.grid_pct` | 25 | % van budget voor Grid Bot. |
| `BUDGET_RESERVATION.reserve_pct` | 0 | % van budget als reserve (niet belegd). |
| `BUDGET_RESERVATION.grid_bot_max_eur` | 9999 | Max euro voor Grid Bot. |
| `BUDGET_RESERVATION.trailing_bot_max_eur` | 9999 | Max euro voor Trailing Bot. |
| `BUDGET_RESERVATION.reinvest_grid_profits` | true | Herinvesteer Grid Bot winst. |
| `BUDGET_RESERVATION.reinvest_trailing_profits` | true | Herinvesteer Trailing Bot winst. |

---

## Marktselectie

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `WHITELIST_MARKETS` | [SOL, XRP, ADA, ...] | Welke markten de bot mag verhandelen. Leeg = alle markten. |
| `EXCLUDED_MARKETS` | [USDC, USDT, DAI, ...] | Markten die altijd worden overgeslagen (stablecoins etc.). |
| `QUARANTINE_MARKETS` | [] | Markten tijdelijk in quarantaine na slechte prestaties. |
| `WATCHLIST_MARKETS` | [] | Markten onder observatie met kleine (micro) trades. |

### Quarantaine Instellingen

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `QUARANTINE_SETTINGS.enabled` | true | Quarantaine systeem aan/uit. |
| `QUARANTINE_SETTINGS.review_after_days` | 5 | Na X dagen herbeoordeeld. |
| `QUARANTINE_SETTINGS.max_promotions_per_cycle` | 1 | Max markten terug naar whitelist per cyclus. |

### Watchlist Instellingen

De watchlist laat de bot markten eerst testen met kleine trades voordat ze gepromoveerd worden naar de whitelist.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `WATCHLIST_SETTINGS.enabled` | true | Watchlist aan/uit. |
| `WATCHLIST_SETTINGS.mode` | "micro" | Modus: `micro` (echte mini-trades) of `paper` (simulatie). |
| `WATCHLIST_SETTINGS.micro_trade_amount_eur` | 5.0 | Bedrag per micro trade. |
| `WATCHLIST_SETTINGS.max_parallel` | 2 | Max gelijktijdige watchlist trades. |
| `WATCHLIST_SETTINGS.promotion_min_trades` | 5 | Minimaal 5 trades voor promotie. |
| `WATCHLIST_SETTINGS.promotion_min_win_rate_pct` | 50.0 | Minimaal 50% winrate voor promotie. |
| `WATCHLIST_SETTINGS.demote_after_days` | 10 | Na 10 dagen gedegradeerd als het niet presteert. |

### Markt Performance Filter

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `MARKET_PERFORMANCE_FILTER_ENABLED` | true | Filter markten op historische prestatie. |
| `MARKET_PERFORMANCE_MIN_TRADES` | 5 | Minimaal 5 trades nodig voor beoordeling. |
| `MARKET_PERFORMANCE_MIN_EXPECTANCY_EUR` | -0.5 | Minimale verwachte winst per trade in EUR. |
| `MARKET_PERFORMANCE_MAX_CONSEC_LOSSES` | 3 | Max opeenvolgende verliezen. |
| `MIN_VOLUME_24H_EUR` | 500000 | Minimum 24u handelsvolume in EUR. |
| `MIN_PRICE_CHANGE_PCT` | 0.015 | Minimale prijsbeweging om te handelen. |

---

## Orders

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `ORDER_TYPE` | "auto" | Ordertype: `auto`, `market`, of `limit`. Auto kiest het beste type. |
| `LIMIT_ORDER_TIMEOUT_SECONDS` | 3600 | Hoe lang een limit order actief blijft (1 uur). |
| `LIMIT_ORDER_PRICE_OFFSET_PCT` | 0.1 | Offset voor limit order prijs (0.1% beter dan marktprijs). |
| `LIMIT_ORDER_CANCEL_BEHAVIOR` | "cancel_only" | Wat er gebeurt als een limit order niet gevuld wordt. |

---

## AI & Machine Learning

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `AI_ENABLED` | true | AI koopscore systeem aan/uit. |
| `AI_SUPERVISOR_ENABLED` | true | AI supervisor die parameters automatisch optimaliseert. |
| `AI_AUTO_APPLY` | false | Pas AI suggesties automatisch toe. **Advies: uit laten tot je vertrouwen hebt.** |
| `AI_PARAM_LOCK` | false | Vergrendel parameters tegen AI wijzigingen. |
| `AI_APPLY_COOLDOWN_MIN` | 45 | Minimale wachttijd (minuten) tussen AI aanpassingen. |
| `AI_AUTO_APPLY_CRITICAL` | true | Pas kritieke AI suggesties altijd toe (bijv. noodstop). |
| `AI_SENTIMENT_ENABLED` | true | AI sentimentanalyse aan/uit. |
| `AI_CORRELATION_ENABLED` | true | Correlatie-analyse tussen markten. |
| `AI_FEEDBACK_LOOP_ENABLED` | false | Feedback loop voor continue verbetering. |
| `AI_REGIME_RECOMMENDATIONS` | true | AI advies op basis van marktregime (trending/ranging/volatile). |
| `AI_PORTFOLIO_ANALYSIS` | true | Portfolio-niveau analyse door AI. |
| `AI_MARKET_SCOPE` | "guarded-auto" | Hoe ver de AI mag zoeken: `whitelist-only`, `guarded-auto`, `full-auto`. |

### AI Guardrails

Veiligheidsgrenzen voor de AI. De AI mag geen markten toevoegen die hier niet aan voldoen.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `AI_GUARDRAILS.min_volume_24h_eur` | 50000 | Minimum volume. |
| `AI_GUARDRAILS.max_spread_pct` | 0.008 | Maximum spread. |
| `AI_GUARDRAILS.max_position_pct_portfolio` | 1.0 | Max % van portfolio per positie. |
| `AI_GUARDRAILS.max_risk_score` | 55 | Max risicoscore. |

### AI Hertraining

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `AI_AUTO_RETRAIN_ENABLED` | true | Automatisch het ML model hertrainen. |
| `AI_RETRAIN_INTERVAL_DAYS` | 7 | Hertraining elke 7 dagen. |
| `AI_RETRAIN_UTC_HOUR` | "02:00" | Tijdstip van hertraining (UTC). |

### AI Allow Params

`AI_ALLOW_PARAMS` bevat een lijst van parameters die de AI mag aanpassen. Alles wat hier niet in staat, kan de AI niet wijzigen. Standaard mogen de belangrijkste trading parameters aangepast worden (trailing, DCA, entry settings).

---

## Circuit Breaker

Noodrem: stopt de bot als de prestatie te slecht is.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `CIRCUIT_BREAKER_MIN_WIN_RATE` | 0.25 | Onder 25% winrate: pauze. |
| `CIRCUIT_BREAKER_MIN_PROFIT_FACTOR` | 0 | Minimum profit factor (0 = uit). |
| `CIRCUIT_BREAKER_COOLDOWN_MINUTES` | 120 | Pauze van 2 uur na activering. |
| `CIRCUIT_BREAKER_GRACE_TRADES` | 5 | Eerste 5 trades worden niet beoordeeld. |

---

## Risicobeheer

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `RISK_MAX_DAILY_LOSS` | 15.0 | Maximum verlies per dag in EUR. |
| `RISK_MAX_WEEKLY_LOSS` | 30.0 | Maximum verlies per week in EUR. |
| `RISK_MAX_DRAWDOWN_PCT` | 15.0 | Maximum drawdown in %. |
| `RISK_MAX_PORTFOLIO_RISK` | 0.015 | Maximum portfoliorisico (1.5%). |
| `RISK_KELLY_ENABLED` | true | Kelly criterium voor positieberekening. |
| `RISK_EMERGENCY_STOP_ENABLED` | true | Noodstop bij overschrijding van risicolimieten. |

### Segment Limieten

Max blootstelling per marktsegment in EUR.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `RISK_SEGMENT_BASE_LIMITS.majors` | 120 | BTC, ETH en grote munten. |
| `RISK_SEGMENT_BASE_LIMITS.alts` | 100 | Middelgrote altcoins. |
| `RISK_SEGMENT_BASE_LIMITS.stable` | 30 | Stablecoin-gerelateerde paren. |
| `RISK_SEGMENT_BASE_LIMITS.default` | 50 | Overige markten. |

---

## Geavanceerde Engines

Deze modules draaien op de achtergrond voor extra analyse.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `REGIME_ENGINE_ENABLED` | true | Marktregime detectie (trending/ranging/volatile). |
| `CORRELATION_SHIELD_ENABLED` | true | Bescherming tegen te veel gecorreleerde posities. |
| `ORDERBOOK_IMBALANCE_ENABLED` | true | Orderbook analyse voor betere entry timing. |
| `KELLY_VOLPARITY_ENABLED` | true | Kelly + volatiliteitspariteit berekening. |
| `AVELLANEDA_STOIKOV_GRID` | true | Wiskundig grid model voor optimale plaatsing. |
| `MTF_CONFLUENCE_ENABLED` | true | Multi-timeframe confluency check. |
| `VWAP_SCORING_ENABLED` | true | VWAP (Volume Weighted Average Price) scoring. |
| `MOMENTUM_CASCADE_ENABLED` | true | Momentum cascade filter. |
| `SMART_EXECUTION_ENABLED` | true | Slimme orderuitvoering (betere vullingskoers). |
| `FUNDING_RATE_ORACLE_ENABLED` | true | Funding rate monitoring voor marktsentiment. |

**Advies:** laat deze allemaal aan staan. Ze kosten weinig en verbeteren de handelsbeslissingen.

---

## Grid Bot

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `GRID_TRADING.enabled` | true | Grid trading aan/uit. |
| `GRID_TRADING.max_grids` | 2 | Maximaal 2 gelijktijdige grids. |
| `GRID_TRADING.investment_per_grid` | 50 | EUR per grid. |
| `GRID_TRADING.num_grids` | 10 | Aantal gridlijnen. Meer = kleinere winst per trade, maar vaker. |
| `GRID_TRADING.grid_mode` | "arithmetic" | `arithmetic` of `geometric`. Geometric past beter bij crypto. |
| `GRID_TRADING.stop_loss_pct` | 0.12 | Grid stop loss op 12%. |
| `GRID_TRADING.take_profit_pct` | 0.10 | Grid take profit op 10%. |
| `GRID_TRADING.trailing_tp_enabled` | true | Trailing take profit voor de grid. |
| `GRID_TRADING.volatility_adaptive` | true | Past grid automatisch aan op volatiliteit. |
| `GRID_TRADING.inventory_skew` | true | Verschuift het grid op basis van huidige positie. |
| `GRID_TRADING.preferred_markets` | ["BTC-EUR", "ETH-EUR"] | Markten bij voorkeur voor grid trading. |

---

## HODL Planner

Vaste DCA schema's, onafhankelijk van de trading bot. Voor langetermijn opbouw.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `HODL_SCHEDULER.enabled` | true | HODL planner aan/uit. |
| `HODL_SCHEDULER.dry_run` | false | Simulatiemodus (geen echte orders). |
| `HODL_SCHEDULER.poll_interval_seconds` | 300 | Check interval (5 minuten). |
| `HODL_SCHEDULER.schedules` | [...] | Array van schema's (zie onder). |

### Schema voorbeeld

```json
{
    "market": "BTC-EUR",
    "amount_eur": 5.0,
    "interval_minutes": 10080,
    "dry_run": false,
    "note": "Wekelijkse BTC-DCA"
}
```

`interval_minutes`: 10080 = 7 dagen, 1440 = 1 dag, 720 = 12 uur.

---

## Telegram Notificaties

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `TELEGRAM_ENABLED` | true | Telegram meldingen aan/uit. |
| `TELEGRAM_BOT_TOKEN` | "" | Token van je Telegram bot (via @BotFather). |
| `TELEGRAM_CHAT_ID` | "" | Je persoonlijke chat ID. |
| `NOTIFY_TRADES` | true | Melding bij elke koop/verkoop. |
| `NOTIFY_ERRORS` | true | Melding bij fouten. |
| `NOTIFY_DAILY_REPORT` | true | Dagelijks overzicht. |
| `NOTIFY_RISK_ALERTS` | true | Melding bij risicowaarschuwingen. |
| `ALERT_STALE_SECONDS` | 300 | Meldingen ouder dan 5 min worden niet verstuurd. |
| `ALERT_DEDUPE_SECONDS` | 900 | Zelfde melding niet opnieuw sturen binnen 15 min. |

---

## Logging & Monitoring

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `LOG_LEVEL` | "DEBUG" | Logniveau: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_MAX_BYTES` | 262144 | Max grootte logbestand (256KB), daarna roteert het. |
| `LOG_BACKUP_COUNT` | 2 | Aantal oude logbestanden bewaren. |
| `PERF_MONITOR_ENABLED` | true | Performance monitoring aan/uit. |
| `PERF_SAMPLE_SECONDS` | 30 | Sample interval. |

---

## Overig

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `BOT_NAME` | "Bitvavo DCA Bot" | Naam van je bot (verschijnt in logs en meldingen). |
| `CONFIG_HOT_RELOAD_SECONDS` | 60 | Config wordt elke 60 seconden herladen. Geen herstart nodig. |
| `TEST_MODE` | false | Testmodus (geen echte orders). |
| `OPERATOR_ID` | "1" | Unieke ID van de operator. |
| `DASHBOARD_AUTOREFRESH_SECONDS` | 120 | Dashboard verversingsinterval. |
| `DISABLE_SYNC_REMOVE` | true | Voorkom automatisch verwijderen van trades bij sync. |
| `DUST_SWEEP_ENABLED` | true | Ruim kleine restbedragen op (< €0.50). |
| `DUST_THRESHOLD_EUR` | 0.5 | Drempel voor "stof" (dust) in euro. |

### Saldo Guard

Beschermt tegen situaties waarbij het saldo te laag is.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `SALDO_GUARD.enabled` | true | Saldo bewaking aan/uit. |
| `SALDO_GUARD.threshold` | 5 | Minimaal €5 saldo vereist. |
| `SALDO_GUARD.cooldown_seconds` | 600 | 10 minuten cooldown na saldo-alarm. |
| `SALDO_GUARD.cancel_pending_buys` | true | Annuleer openstaande kooporders bij laag saldo. |

### Floodguard

Beschermt tegen te snel achter elkaar verliezen.

| Parameter | Standaard | Beschrijving |
|---|---|---|
| `FLOODGUARD.enabled` | false | Floodguard aan/uit. |
| `FLOODGUARD.max_loss_pct` | 100.0 | Max verlies in % (100 = effectief uit). |
| `FLOODGUARD.max_loss_eur` | 9999.0 | Max verlies in EUR. |
| `FLOODGUARD.max_api_failures` | 10 | Na 10 API fouten: pauzeren. |

---

## Parameters die beginnen met underscore (_)

Parameters die beginnen met `_` zijn **interne runtime waarden**. Deze worden automatisch bijgewerkt door de bot en moeten niet handmatig gewijzigd worden.

| Parameter | Beschrijving |
|---|---|
| `_SALDO_COOLDOWN_UNTIL` | Tijdstip tot wanneer saldo cooldown actief is. |
| `_cb_trades_since_reset` | Aantal trades sinds laatste circuit breaker reset. |
| `_REGIME_ADJ` | Huidige regime-aanpassingen door de AI. |
| `_REGIME_RESULT` | Laatst gedetecteerde marktregime en confidence. |
| `_updated` | Laatste wijzigingsdatum van de config. |

---

## Snel aan de slag

**Beginner?** Pas alleen deze 4 instellingen aan:

1. `BASE_AMOUNT_EUR` → je budget per trade (start klein, bijv. €10-20)
2. `MAX_OPEN_TRADES` → hoeveel posities tegelijk (start met 2-3)
3. `DCA_AMOUNT_EUR` → bedrag per bijkoop (zelfde als base of iets lager)
4. `WHITELIST_MARKETS` → welke munten de bot mag verhandelen

Al het andere werkt goed met de standaardwaarden.
