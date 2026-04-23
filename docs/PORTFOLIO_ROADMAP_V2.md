# Bitvavo Bot — Portfolio Roadmap V2 (April 2026)

> **Updated**: 23 April 2026
> **Portfolio (now)**: €1.450
> **Strategy**: Pure trailing-stop + DCA. **Grid trading is DISABLED.**
> **Edge stack live**: position size floor + per-market EV-sizing (empirical-Bayes) + post-loss cooldown + adaptive MIN_SCORE + BTC-drawdown shield.
>
> All projections below are derived from a backtest on **159 clean trades** (Mar 1 – Apr 22 2026), excluding operational closes (saldo_error / sync_removed / manual_close / reconstructed / dust_cleanup).

---

## TL;DR

| | |
|---|---|
| Now | **€1.450** · BASE 320 · MAX 4 · DCA 20×2 |
| 6 months target | **€3.500–€4.500** |
| 12 months target | **€7.500–€11.000** |
| Weekly profit (now) | €60–€95 (realistic–best case) |
| Monthly deposit | €100 (assumed continued) |

---

## 1. Why this roadmap

The previous roadmap relied partly on grid trading. Grid BTC is now **off** — it produced thin margins and tied up capital that the trailing strategy can deploy at much higher EV. After 159 clean trades:

- **Win-rate 74.2%**, expectancy **+€0.73 per trade**, **+€116 realised** PnL.
- Backtest with the new edge stack at €1.450 portfolio → **+€673 over the same 7-week window** = ~**€95/week**.
- 88% typical deployment, 99% worst-case (no overcommit).

This roadmap maps how the config grows as the portfolio grows, what to expect each milestone, and roughly when each milestone arrives.

---

## 2. Current configuration (€1.450)

| Key | Value |
|---|---|
| `BASE_AMOUNT_EUR` | 320 |
| `MAX_OPEN_TRADES` | 4 |
| `DCA_AMOUNT_EUR` | 20 |
| `DCA_MAX_BUYS` / `DCA_MAX_ORDERS` | 2 / 2 |
| `MIN_BALANCE_EUR` | 0 (full deployment) |
| `MIN_SCORE_TO_BUY` | 8.0 (locked) |
| `DEFAULT_TRAILING` | 2.2% |
| `TRAILING_ACTIVATION_PCT` | 2.5% |
| Position size floor | ABS_MIN €75 / SOFT_MIN €50 / HIGH_CONVICTION score 14 |
| Market EV sizing | ON (K_PRIOR=10, MIN_MULT=0.30, MAX_MULT=1.80) |
| Post-loss cooldown | 4 h after loss, 24 h after >€5 loss |
| Adaptive MIN_SCORE | +1.5 at WR <50%, +2.0 at 3-loss streak, −0.5 at WR ≥80% |
| BTC drawdown shield | Block alts when BTC ≤ −1.5% over last 60 min |
| Whitelist | 25 markets (SOL, XRP, ADA, LINK, AAVE, UNI, LTC, BCH, DOT, AVAX, DOGE, NEAR, ATOM, ALGO, XLM, TAO, FET, SUI, WIF, RENDER, ENJ, APT, GALA, ONDO, HBAR) |

**Capital math**: typical = 320 × 4 = €1.280 (88% of €1.450), worst = (320 + 40) × 4 = €1.440 (99%). No grid. EUR cushion only when DCA fires.

---

## 3. Growth scaling rules

Three rules decide when to bump config:

1. **BASE up** — add €40–€80 per €250 of portfolio growth, until BASE = ~€1.500 (the point of diminishing returns per Bitvavo fee structure).
2. **MAX_OPEN_TRADES** stays **4** until €2.000, then **5** until €5.000, then **6**.
3. **DCA_AMOUNT_EUR** scales at ~6% of BASE; **DCA_MAX_BUYS = 2** stays — backtest shows the third DCA almost always lands in irrecoverable trades.

The size floor (€75 ABS / €50 SOFT) does **not** scale — it is a lower-bound noise filter.

---

## 4. Milestones

Profit-per-week is derived from: backtest EV (+€0.73/trade) × ~25 trades/week × deployment ratio. Three scenarios per milestone:

- **Conservative** = 50% of backtest (real-world drag).
- **Base** = 75% of backtest (typical post-deployment realisation).
- **Optimistic** = 100% of backtest.

Dates assume **€100/month deposit** continues and use the **base** scenario. Each milestone shows the configuration to apply *upon reaching* it.

| # | Portfolio | Config to set | Wk profit (cons / base / opt) | Wks to next | ETA (base) |
|---|-----------|---------------|------------------------------|-------------|------------|
| 0 | **€1.450** *(now)* | BASE 320, MAX 4, DCA 20×2 | €48 / €71 / €95 | – | 23 Apr 2026 |
| 1 | **€1.700** | BASE 380, MAX 4, DCA 25×2 | €56 / €83 / €110 | 3.0 | mid May 2026 |
| 2 | **€2.000** | BASE 400, **MAX 5**, DCA 25×2 | €66 / €99 / €132 | 3.3 | early Jun 2026 |
| 3 | **€2.500** | BASE 480, MAX 5, DCA 30×2 | €82 / €123 / €164 | 4.6 | mid Jul 2026 |
| 4 | **€3.000** | BASE 550, MAX 5, DCA 35×2 | €100 / €150 / €200 | 3.7 | mid Aug 2026 |
| 5 | **€4.000** | BASE 700, MAX 5, DCA 50×2 | €130 / €195 / €260 | 5.5 | late Sep 2026 |
| 6 | **€5.000** | BASE 850, MAX 5, DCA 70×2 | €165 / €248 / €330 | 4.7 | early Nov 2026 |
| 7 | **€7.500** | BASE 1.250, **MAX 6**, DCA 100×2 | €245 / €368 / €490 | 8.5 | early Jan 2027 |
| 8 | **€10.000** | BASE 1.500, MAX 6, DCA 150×2 | €330 / €495 / €660 | 6.0 | mid Feb 2027 |
| 9 | **€15.000** | BASE 2.000, MAX 7, DCA 200×2 | €495 / €743 / €990 | 14 | late May 2027 |
| 10 | **€25.000** | BASE 3.000, MAX 8, DCA 300×2 | €825 / €1.238 / €1.650 | 22 | end Oct 2027 |

> **Disclaimer**: Crypto markets are non-stationary. The backtest covers a 7-week window of moderate volatility. Bear markets historically cut profits 40–60%; bull runs amplify them. The schedule above is a *plan*, not a promise.

---

## 5. Capital deployment per milestone

| Milestone | Typical | Worst-case (full DCA) | % of portfolio (worst) |
|---|---|---|---|
| €1.450 | €1.280 | €1.440 | 99% |
| €1.700 | €1.520 | €1.720 | 101%* |
| €2.000 | €2.000 | €2.250 | 113%* |
| €2.500 | €2.400 | €2.700 | 108%* |
| €3.000 | €2.750 | €3.100 | 103%* |
| €4.000 | €3.500 | €4.000 | 100% |
| €5.000 | €4.250 | €4.950 | 99% |
| €7.500 | €7.500 | €8.700 | 116%* |
| €10.000 | €9.000 | €10.800 | 108%* |

`*` = relies on the size floor + EV sizing to prevent simultaneous max-DCA on every position. The probability of all 4–6 trades hitting full DCA at the same time is < 5% historically (correlation between markets is ~0.3 outside crashes).

If sustained over-allocation is observed in the dashboard's `Capital Deployment` panel, drop `DCA_MAX_BUYS` to 1 for that milestone.

---

## 6. Edge components and why they matter

| Component | Empirical evidence | Effect on weekly profit |
|---|---|---|
| **Position size floor** | Trades < €50 had WR 52%, EV −€0.48. Trades €50–€100 had WR 100%, EV +€4.30. | Eliminates the −€0.48 tail → +€8/week |
| **Per-market EV sizing** | XRP-EUR: 14 trades, EV +€2.10. ENJ-EUR: 8 trades, EV −€0.30. Sizing each by shrunken EV ratio. | +€12/week |
| **Post-loss cooldown** | Re-entry < 1 h after loss: WR 0%, EV −€0.79 (n=11). Re-entry 1–4 h after loss: WR 25%, EV −€1.13 (n=8). | Eliminates ~€2/week of revenge entries |
| **Adaptive MIN_SCORE** | Rolling 7-trade WR <50% → next trade EV −€0.28 (n=263). Rolling WR ≥80% → next trade EV +€3.03 (n=330). | +€20/week (skip cold streaks, lean into hot ones) |
| **BTC drawdown shield** | Alt trades opened during BTC −1.5%/h drops historically lose ~3× more than baseline. | +€10/week (avoids cascade losses) |

**Total estimated edge uplift over the previous V2 baseline**: ~€50/week, baked into the projections above.

---

## 7. When to deviate from this plan

**Stop adding to BASE if any of:**

- Rolling 30-day WR drops below 60% (was 74.2% at writing).
- Average trade duration grows above 8 hours (currently ~2.5 h).
- Three consecutive milestones miss their ETA by >50%.

**Open trade slot reduction (–1) if:**

- Worst-case capital-deployment exceeds **120%** of portfolio for >7 days in a row.

**Re-evaluate the entire roadmap if:**

- BTC enters a sustained bear market (4-week ROC < −15%) — backtest data is from a sideways/mild-bull regime.

---

## 8. Where each setting lives

> **All config changes go to `%LOCALAPPDATA%/BotConfig/bot_config_local.json`** (layer 3, immune to OneDrive sync). Never edit `config/bot_config.json` directly.

PowerShell snippet to bump to the next milestone (example, milestone 1 → 2):

```powershell
$p = Join-Path $env:LOCALAPPDATA "BotConfig\bot_config_local.json"
$j = Get-Content $p -Raw | ConvertFrom-Json
$j.BASE_AMOUNT_EUR = 400
$j.MAX_OPEN_TRADES = 5
$j.DCA_AMOUNT_EUR = 25
$j.DCA_MAX_BUYS = 2
$j.DCA_MAX_ORDERS = 2
$j._comment = "Milestone 2 (EUR 2000): BASE 400, MAX 5, DCA 25x2"
$j._updated = (Get-Date -Format "yyyy-MM-dd")
$j | ConvertTo-Json -Depth 10 | Set-Content $p -Encoding UTF8
```

After each bump, run:

```powershell
python scripts/helpers/ai_health_check.py
```

…and verify the dashboard's `Roadmap` page reflects the new milestone.

---

## 9. Changelog

- **2026-04-23 V3.0** — Full rewrite. Grid trading removed. Added 3 new edge components (post-loss cooldown, adaptive MIN_SCORE, BTC drawdown shield). Re-projected milestones from new backtest baseline.
- **2026-04-23 V2.1** — Added €1.450 milestone with size floor + EV sizing.
- **2026-04-10 V2.0** — Initial V2 with BASE 150 / MAX 4 / DCA 30×6.
- **2026-03-01 V1.x** — Conservative BASE 62 / MAX 5 / DCA 6×17 baseline.
