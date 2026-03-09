# Claude Opus 4.6 - Systematic Bot Review Plan

**Doel**: Systematische, grondige analyse van je trading bot door Claude Opus 4.6  
**Methode**: 8 gefocuste sessies, elk gericht op specifieke critical paths  
**Verwachte tijdsinvestering**: 6-10 uur verspreid over 3-5 dagen  
**Verwachte verbetering**: 20-40% betere code quality, edge case handling, en risk management

---

## ⚠️ Voorbereiding

### 1. Start elke sessie FRESH
- **Nieuwe chat** in Copilot met Opus 4.6 selected
- Geen carryover van vorige sessie (context contamination)

### 2. Backup maken
```powershell
# Voordat je begint
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -Path "config/bot_config.json" -Destination "backups/bot_config_pre_opus_review_$timestamp.json"
Copy-Item -Path "trailing_bot.py" -Destination "backups/trailing_bot_pre_opus_review_$timestamp.py"
```

### 3. Test environment ready
- Bot GESTOPT tijdens reviews
- `.venv` geactiveerd
- `pytest` werkt

---

## 📋 Sessie Overzicht

| # | Focus | Critical Level | Tijd | Files |
|---|-------|----------------|------|-------|
| 1 | Trade Execution Logic | 🔴 CRITICAL | 60-90 min | bot/trailing.py, bot/api.py |
| 2 | Risk & Position Management | 🔴 CRITICAL | 60-90 min | trailing_bot.py, bot/helpers.py |
| 3 | Signal Generation & Entry | 🟠 HIGH | 45-60 min | bot/signals.py, bot/performance.py |
| 4 | AI Supervisor Architecture | 🟠 HIGH | 60-90 min | ai/ai_supervisor.py, ai/suggest_rules.py |
| 5 | Error Handling & Recovery | 🟡 MEDIUM | 45-60 min | bot/api.py, trailing_bot.py |
| 6 | Data Persistence & State | 🟡 MEDIUM | 45-60 min | data/*.json patterns |
| 7 | ML Pipeline & Training | 🟢 LOW | 30-45 min | ai/ml_optimizer.py, ai/xgb_* |
| 8 | Performance & Optimization | 🟢 LOW | 30-45 min | Alle modules |

---

## 🎯 Sessie 1: Trade Execution Logic

**Waarom eerst**: Dit is waar geld verloren gaat bij bugs  
**Focus**: Order placement, fills, partial fills, cancellations, edge cases

### Prompt voor Opus 4.6:

```
Je bent een senior trading systems engineer die crypto trading bots audit.

TAAK: Analyseer de trade execution logic van deze Bitvavo trading bot.
Focus ALLEEN op bugs, race conditions, edge cases, en risk issues.

CRITICAL VRAGEN:
1. Wat gebeurt er bij partial fills?
2. Hoe wordt order state bijgehouden bij netwerk failures?
3. Kunnen er duplicate orders ontstaan?
4. Wat gebeurt er bij rate limiting?
5. Is er een race condition tussen sell checks en nieuwe buys?
6. Hoe wordt slippage afgehandeld?
7. Wat als een order "stuck" raakt?

DELIVERABLE:
- Lijst van top 5 meest kritieke bugs/risks die je vindt
- Voor elk: exacte file + line number + waarom critical + suggested fix
- Code voorbeelden van de fix

BESTANDEN:
[Plak hier bot/trailing.py volledig]
[Plak hier bot/api.py volledig]
[Plak hier relevante delen van trailing_bot.py - order placement logic]

WEES KRITISCH. Geen complimenten. Alleen problemen en oplossingen.
```

### Wat te doen met output:

1. **Save output** als `reviews/session1_execution_logic.md`
2. **Prioriteer** de top 3 issues
3. **Implement fixes** één voor één
4. **Test** na elke fix met `pytest tests/`
5. **Verify** met bot in paper trading mode

### Red Flags om naar te kijken:

- ❌ Geen mutex/locks bij concurrent order operations
- ❌ Geen timeout handling bij API calls
- ❌ State updates zonder verification
- ❌ Geen idempotency bij order placement
- ❌ Missing error cases in try/except

---

## 🎯 Sessie 2: Risk & Position Management

**Waarom**: Beschermt je kapitaal tegen overexposure  
**Focus**: MAX_CONCURRENT_TRADES, exposure limits, stop-loss, position sizing

### Prompt voor Opus 4.6:

```
Je bent een trading risk management specialist.

TAAK: Audit de risk management systemen van deze trading bot.
Dit bot heeft al geleid tot verliezen door exposure issues.

CRITICAL VRAGEN:
1. Kan MAX_TOTAL_EXPOSURE_EUR worden overschreden? Hoe?
2. Wat gebeurt er als meerdere sells tegelijk executeren en nieuwe buys triggeren?
3. Hoe wordt unrealized P&L berekend? Kan dit verkeerd gaan?
4. Zijn er race conditions bij exposure checking?
5. Wat als een coin crasht -50% voordat stop-loss triggert?
6. Hoe wordt totale exposure berekend bij pending orders?
7. Kan de bot "stuck" raken met max trades open?

DELIVERABLE:
- Top 5 risk management vulnerabilities
- Scenario's die tot capital loss leiden
- Exact code fixes met voorbeelden
- Verbeterde exposure calculation logic

BESTANDEN:
[Plak hier trailing_bot.py - check_exposure, can_open_new_trade sections]
[Plak hier bot/helpers.py]
[Plak hier config/bot_config.json]

FOCUS: Edge cases die tot financial loss leiden.
```

### Wat te doen:

1. **Verify** alle voorgestelde scenario's handmatig:
   ```python
   # Test script maken:
   # _test_exposure_scenarios.py
   ```
2. **Implement** exposure calculation fixes
3. **Add tests** voor edge cases
4. **Backtest** met historical data

### Red Flags:

- ❌ Float precision errors in money calculations
- ❌ Race condition tussen exposure check en order placement
- ❌ Stop-loss niet guaranteed execution
- ❌ Geen circuit breaker bij rapid losses

---

## 🎯 Sessie 3: Signal Generation & Entry Timing

**Waarom**: Betere entries = betere P&L  
**Focus**: Technical indicators, entry logic, market regime detection

### Prompt voor Opus 4.6:

```
Je bent een quantitative trading analyst.

TAAK: Review de signal generation en entry timing logic.
Deze bot gebruikt RSI, Bollinger Bands, en volume voor entry signals.

VRAGEN:
1. Zijn er look-ahead bias issues in indicator calculations?
2. Hoe worden false signals gefilterd?
3. Is de signal logic consistent met market regimes?
4. Wat gebeurt er bij stale/missing data?
5. Worden indicators correct berekend? (formulas check)
6. Is er overfitting op historical data?
7. Hoe wordt signal strength gecombineerd met risk management?

DELIVERABLE:
- Bugs in technical indicator calculations
- Logic errors in signal generation
- Verbeterde filtering voor false positives
- Suggested additional indicators/filters

BESTANDEN:
[Plak hier bot/signals.py volledig]
[Plak hier bot/performance.py - signal scoring delen]
[Plak hier relevante config entries voor signals]
```

### Wat te doen:

1. **Verify** indicator formulas tegen standaard TA libraries
2. **Backtest** verbeterde signals op historical data
3. **A/B test** oude vs nieuwe logic in paper mode

---

## 🎯 Sessie 4: AI Supervisor Architecture

**Waarom**: AI past parameters aan - bugs hier zijn gevaarlijk  
**Focus**: Parameter validation, bounds checking, rollback logic

### Prompt voor Opus 4.6:

```
Je bent een ML systems engineer die production ML systems audit.

TAAK: Review de AI supervisor die trading parameters automatisch aanpast.
Dit is HIGH RISK code - fouten kunnen kapitaal vernietigen.

CRITICAL VRAGEN:
1. Hoe wordt voorkomen dat AI extreme/unsafe parameters zet?
2. Is er proper validation van AI suggestions?
3. Kan de AI stuck raken in een bad feedback loop?
4. Wat gebeurt er bij conflicting suggestions?
5. Hoe wordt rollback gedaan bij slechte performance?
6. Is er human-in-the-loop voor grote changes?
7. Kunnen AI changes race conditions veroorzaken in running trades?

DELIVERABLE:
- Safety issues in AI parameter updates
- Validation gaps in suggestion processing
- Improved bounds checking
- Better rollback mechanisms
- Suggested "AI circuit breaker" logic

BESTANDEN:
[Plak hier ai/ai_supervisor.py volledig]
[Plak hier ai/suggest_rules.py volledig]
[Plak hier AI_ALLOW_PARAMS section van bot_config.json]
```

### Wat te doen:

1. **Implement** stricter validation bounds
2. **Add** AI circuit breaker (auto-disable bij rapid losses)
3. **Test** AI suggestions tegen extreme scenarios
4. **Add logging** voor alle AI decisions

### Red Flags:

- ❌ Geen upper/lower bounds op critical params
- ❌ AI kan zichzelf uitzetten/blocken
- ❌ Geen rate limiting op parameter changes
- ❌ Missing rollback bij performance degradation

---

## 🎯 Sessie 5: Error Handling & Recovery

**Waarom**: Production bots moeten crashes overleven  
**Focus**: Exception handling, graceful degradation, state recovery

### Prompt voor Opus 4.6:

```
Je bent een reliability engineer voor production systems.

TAAK: Audit error handling en recovery mechanisms.
Bot moet 24/7 draaien zonder human intervention.

VRAGEN:
1. Wat gebeurt er bij onverwachte exceptions?
2. Hoe wordt state recovered na crash?
3. Zijn er bare except: blocks zonder logging?
4. Wat gebeurt er bij API downtime?
5. Hoe wordt data corruption detected/fixed?
6. Is er proper cleanup van resources (files, connections)?
7. Kunnen errors leiden tot inconsistent state?

DELIVERABLE:
- Lijst van unhandled error scenarios
- Missing try/except blocks
- Improved error recovery logic
- State validation on startup
- Better logging voor debugging

BESTANDEN:
[Plak hier bot/api.py - error handling delen]
[Plak hier trailing_bot.py - main loop + startup]
[Plak hier relevante delen van andere modules]
```

### Wat te doen:

1. **Test** crash scenarios:
   ```powershell
   # Kill bot tijdens verschillende states
   # Verify recovery
   ```
2. **Add** state validation on startup
3. **Improve** logging voor post-mortem analysis

---

## 🎯 Sessie 6: Data Persistence & State Management

**Waarom**: Data corruption = verlies van trade history  
**Focus**: JSON file handling, concurrent writes, data integrity

### Prompt voor Opus 4.6:

```
Je bent een data engineer die distributed systems audit.

TAAK: Review data persistence en state management.
Bot gebruikt JSON files voor state - single point of failure.

VRAGEN:
1. Wat gebeurt er bij concurrent writes naar zelfde file?
2. Hoe wordt data corruption detected?
3. Is er atomic write garantie?
4. Wat gebeurt er bij disk full?
5. Hoe wordt backward compatibility gehandeld?
6. Is er data backup/recovery?
7. Kunnen er data races ontstaan?

DELIVERABLE:
- Data corruption scenarios
- Concurrent write issues
- Atomic write implementation
- Backup/recovery strategy
- Migration path voor data format changes

BESTANDEN:
[Plak hier utils.py - alle JSON read/write functions]
[Plak hier voorbeelden van data/*.json structure]
```

### Wat te doen:

1. **Implement** atomic writes (temp file + rename)
2. **Add** JSON validation on read
3. **Setup** automated backups
4. **Test** concurrent access scenarios

---

## 🎯 Sessie 7: ML Pipeline & Training

**Waarom**: Bad ML = bad decisions = verlies  
**Focus**: Feature engineering, training loop, model validation

### Prompt voor Opus 4.6:

```
Je bent een ML engineer die production ML pipelines audit.

TAAK: Review ML training en feature engineering pipeline.

VRAGEN:
1. Is er data leakage in feature engineering?
2. Hoe wordt train/test split gedaan?
3. Is het model overfit op recent data?
4. Hoe wordt model performance monitored in production?
5. Zijn er features met NaN/inf values?
6. Hoe wordt model versioning gedaan?
7. Is er A/B testing voor nieuwe models?

DELIVERABLE:
- Data leakage issues
- Overfitting risks
- Improved validation strategy
- Production monitoring for model drift
- Better feature engineering

BESTANDEN:
[Plak hier ai/ml_optimizer.py]
[Plak hier ai/xgb_auto_train.py of xgb_train_enhanced.py]
```

---

## 🎯 Sessie 8: Performance & Optimization

**Waarom**: Slow = missed opportunities  
**Focus**: Bottlenecks, unnecessary API calls, computation efficiency

### Prompt voor Opus 4.6:

```
Je bent een performance engineer.

TAAK: Find performance bottlenecks en optimization opportunities.

VRAGEN:
1. Waar zijn de slowest code paths?
2. Zijn er unnecessary API calls?
3. Kunnen dingen gecached worden?
4. Is er redundant computation?
5. Zijn er memory leaks?
6. Kan iets parallellized worden?

DELIVERABLE:
- Top 5 performance bottlenecks
- Quick wins (easy optimizations)
- Long-term refactoring suggestions

BESTANDEN:
[Plak hier volledige codebase overview + profiling data indien beschikbaar]
```

---

## 📊 Na Alle Sessies

### 1. Consolideer Findings

Maak `OPUS_REVIEW_SUMMARY.md`:

```markdown
# Opus 4.6 Review - Consolidated Findings

## Critical Issues (Fix ASAP)
1. [Issue] - [File] - [Impact]
   - Fix: [Code]
   - Status: [ ] To Do / [ ] Done

## High Priority
...

## Medium Priority
...

## Quick Wins (Low Effort, High Impact)
...

## Long-term Refactoring
...
```

### 2. Implementatie Strategie

```
Week 1: Critical issues (Session 1, 2)
Week 2: High priority (Session 3, 4)
Week 3: Medium priority (Session 5, 6)
Week 4: Optimizations (Session 7, 8)
```

### 3. Verification

Na elke fix:
```powershell
# Run tests
.venv\Scripts\python.exe -m pytest tests/ -v

# Check syntax
.venv\Scripts\python.exe -m py_compile trailing_bot.py

# Paper trading test (24h minimum)
# Monitor logs for errors
```

### 4. Voor/Na Metrics

Track deze metrics voor/na review:

| Metric | Voor | Na | Δ |
|--------|------|-------|---|
| Win Rate | ? | ? | ? |
| Avg P&L per trade | ? | ? | ? |
| Max Drawdown | ? | ? | ? |
| Crashes per week | ? | ? | ? |
| False signals/day | ? | ? | ? |
| API errors/day | ? | ? | ? |

---

## 💡 Pro Tips

### 1. Wees Specifiek in Prompts
❌ "Check deze code"  
✅ "Find race conditions in order placement that could cause duplicate orders"

### 2. Geef Context
Vertel Opus:
- "This bot has lost money due to overexposure issues"
- "We've had crashes during high volatility"
- "AI supervisor once set RSI to 0"

### 3. Vraag om Code, niet Concepts
❌ "We should add better error handling"  
✅ "Show me exactly the try/except blocks to add with proper logging"

### 4. Challenge Opus
Als Opus iets niet vindt:
- "Are you sure there's no race condition here? What if two threads call this simultaneously?"
- "What happens in this exact scenario: [describe edge case]"

### 5. Test Everything
Vertrouw NOOIT blindly op AI suggestions. Test, verify, validate.

---

## 🚨 Warning Signs During Review

Stop en heroverweeg als Opus:
- ❌ Geeft generieke adviezen zonder specifieke code
- ❌ Zegt "everything looks good" (bullshit detector)
- ❌ Suggest major architectural changes zonder duidelijke wins
- ❌ Kan geen concrete bugs vinden (er zijn ALTIJD bugs)

Goede tekens:
- ✅ Vindt specifieke edge cases met line numbers
- ✅ Geeft concrete reproducible scenarios
- ✅ Suggests testable fixes
- ✅ Explains waarom iets critical is

---

## 📝 Template voor Tracking

Maak `REVIEW_PROGRESS.md`:

```markdown
# Review Progress Tracker

## Session 1: Trade Execution ✅ / ⏳ / ⬜
- Started: 2026-02-20 14:30
- Findings: 7 issues
- Top Critical: [Beschrijving]
- Status: 3/7 fixed, 4 pending

## Session 2: Risk Management ⬜
- Planned: 2026-02-21
...
```

---

## Vragen?

Als je tijdens de reviews vastloopt:
1. ✅ Save je Opus output
2. ✅ Kom terug naar mij (Sonnet 4.5) voor implementatie hulp
3. ✅ Test incrementeel, commit vaak

**Succes! Dit gaat je bot significant beter maken.** 🚀

---

**Laatst updated**: 2026-02-20  
**Voor**: Bitvavo Trading Bot v2.x  
**Door**: GitHub Copilot (Claude Sonnet 4.5)
