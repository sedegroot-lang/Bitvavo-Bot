# Profit Optimization Roadmap

**Generated**: 2026-02-20  
**Status**: Phase 1-2 IMPLEMENTED + TESTED  
**Bot**: Bitvavo Trading Bot v2.x  

---

## Huidige Situatie (780 trades, 93 dagen)

| Metric | Waarde |
|--------|--------|
| **Totaal trades** | 780 |
| **Strategy P&L** | **+€795.89** (72.8% WR, 494 trades) |
| **Bug P&L** | **-€1,710.66** (273 trades: saldo_flood_guard, saldo_error, sync_removed) |
| **Netto** | **-€914.77** |
| **Account** | €280.72 (€6.65 beschikbaar, 8 open posities) |

### Conclusie: De strategie is WINSTGEVEND. Bugs vernietigen de winst.

---

## Phase 1: CRITICAL BUG FIXES [✅ GEÏMPLEMENTEERD]

### 1.1 SALDO_GUARD Config [✅ DONE]
**Impact**: Voorkomt premature trade-sluiting bij tijdelijke balance-problemen  
**File**: `config/bot_config.json`  
**Fix**: `max_retries_before_close` verhoogd van 3 naar 10

### 1.2 Expectancy Tracking Fix [✅ DONE]
**Impact**: Expectancy stats berekenen nu over ALLE 780+ trades, niet alleen laatste 15  
**File**: `bot/performance.py` → `publish_expectancy_metrics()` + `_load_archive_trades()`  
**Was**: Alleen `_closed_trades_ref` (huidige sessie)  
**Nu**: Archive (780) + sessie trades, de-duplicated

### 1.3 Saldo_error → _finalize_close_trade [✅ DONE]
**Impact**: Saldo_error sluitingen bewaren nu ML metadata (score, RSI, regime)  
**File**: `trailing_bot.py` L2818  
**Was**: Handmatige archive_trade + closed_trades.append (metadata verloren)  
**Nu**: `_finalize_close_trade()` die automatisch metadata kopieert

### 1.4 Stale Cooldown Verwijderd [✅ DONE]
**File**: `config/bot_config.json`  
**Fix**: `_SALDO_COOLDOWN_UNTIL` verwijderd

### 1.5 FLOODGUARD Confirmed Disabled [✅ DONE]
**Impact**: Legacy force-sell blijft uitgeschakeld  

---

## Phase 2: RISK & CONFIG FIXES [✅ GEÏMPLEMENTEERD]

### 2.1 Risk Segment Limits [✅ DONE]
**Impact**: Voorkomt overexposure naar één segment  
**Was**: alts=9999, majors=9999, stable=9999, default=9999  
**Nu**: alts=100, majors=120, stable=30, default=50

### 2.2 HODL Scheduler Enabled [✅ DONE]
**Impact**: Passieve wekelijkse BTC + ETH accumulation (€5/week elk)  
**File**: `config/bot_config.json` → `HODL_SCHEDULER.enabled = true`

### 2.3 ML Metadata Storage [✅ DONE]
**Impact**: Nieuwe trades slaan nu MACD, SMA_short, SMA_long op bij entry  
**File**: `trailing_bot.py` L4645-4660 + `_finalize_close_trade()` kopieert extra velden  

### 2.4 ML Training Data Generator [✅ DONE]
**Impact**: 507 valide training rows uit archive (excl. bug-trades)  
**File**: `scripts/ml/generate_training_from_archive.py`  
**Output**: `trade_features.csv` (507 rows) + `ai/training_data/archive_training_data.csv`

---

## Phase 3: PARAMETER OPTIMIZATION [🔲 HANDMATIG]

> **Voer uit na 1 week bot-draaitijd met Phase 1-2 fixes actief**

### 3.1 Run Backtester + Optimizer
```powershell
# Genereer optimale SL/TP/trailing parameters
.venv\Scripts\python.exe -c "
from modules.optimizer import quick_optimize
results = quick_optimize(profile='balanced', objective='profit_factor')
print(results)
"
```

### 3.2 Overweeg Parameter Aanpassingen
Huidige parameters vs aanbeveling:

| Parameter | Huidig | Aanbevolen | Reden |
|-----------|--------|------------|-------|
| `HARD_SL_ALT_PCT` | 9% | 6-7% | Gemiddeld verlies is €6.23 — strakkere SL limiteert verlies |
| `TRAILING_ACTIVATION_PCT` | 3.2% | 4-5% | Iets hoger om fees+slippage te coveren |
| `PARTIAL_TP_SELL_PCT_1` | 30% | 40-50% | Meer winst pakken bij eerste TP |
| `BASE_AMOUNT_EUR` | €6 | €8-10 | Hogere positie = minder fee-impact |

**NIET AUTOMATISCH TOEPASSEN** — eerst backtesten met optimizer.

### 3.3 Hertraining ML Model
```powershell
# Na 200+ feature-rich trades (verwacht: 4-6 weken):
.venv\Scripts\python.exe scripts/ml/generate_training_from_archive.py
.venv\Scripts\python.exe ai/xgb_auto_train.py
```

---

## Phase 4: GRID TRADING ACTIVATIE [🔲 TOEKOMSTIG]

**Wanneer**: Na Phase 3 stabiel is (2-4 weken)  
**Verwacht rendement**: 2-8%/maand extra in zijwaartse markten

### Benodigde stappen:
1. [ ] `GRID_TRADING` config sectie toevoegen aan `bot_config.json`
2. [ ] Real Bitvavo limit-order execution in `modules/grid_trading.py`
3. [ ] Fee-accounting (0.15% maker / 0.25% taker) in grid P&L
4. [ ] AI Grid Advisor integratie voor automatische range-selectie
5. [ ] Run in dry-run mode 1 week, dan live

### Grid Trading geschat werk: ~40-60 uur

---

## Verificatie Checklist

### Phase 1-2 (gedaan):
- [x] `py_compile` alle gewijzigde bestanden: OK
- [x] `pytest tests/`: 325 passed, 1 pre-existing failure (onrelated DCA test)
- [x] Config backup: `backups/bot_config_pre_roadmap_20260220_144221.json`
- [x] trailing_bot backup: `backups/trailing_bot_pre_roadmap_20260220_144221.py`
- [x] Performance.py backup: `backups/performance_pre_roadmap_20260220_144221.py`
- [x] ML training data: 507 rows gegenereerd

### Na bot herstart:
- [ ] Monitor `data/expectancy_stats.json` — sample_size moet ~780+ zijn
- [ ] Geen `saldo_flood_guard` closes meer (legacy guard disabled)
- [ ] HODL scheduler koopt wekelijks BTC+ETH
- [ ] Nieuwe trades bevatten `rsi_at_entry`, `macd_at_entry`, `sma_*_at_entry`

---

## Gewijzigde Bestanden

| Bestand | Wijziging |
|---------|-----------|
| `config/bot_config.json` | SALDO_GUARD, HODL enabled, risk segment limits |
| `bot/performance.py` | `_load_archive_trades()` + expectancy includes archive |
| `trailing_bot.py` | saldo_error → _finalize_close_trade, extra ML metadata |
| `scripts/ml/generate_training_from_archive.py` | Nieuw — training data generator |
| `trade_features.csv` | Vernieuwd — 507 rows uit archief |
| `ai/training_data/archive_training_data.csv` | Nieuw — enhanced features |

---

## Verwachte Impact

| Scenario | Zonder fixes | Met Phase 1-2 | Met Phase 3-4 |
|----------|-------------|---------------|---------------|
| Bug losses/maand | ~€350-900 | ~€0-50 | ~€0-50 |
| Strategy profit/maand | ~€160-550 | ~€160-550 | ~€200-700 |
| **Netto/maand** | **-€200 tot -€700** | **+€100 tot +€500** | **+€150 tot +€650** |

---

## Cleanup

```powershell
# Verwijder tijdelijke bestanden
Remove-Item _apply_config_fixes.py -ErrorAction SilentlyContinue
```
