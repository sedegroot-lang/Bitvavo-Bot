# Fix Log â€” Bitvavo Trading Bot

> **IMPORTANT**: Every Copilot session MUST read this file before making any fix.
> Check if the issue has been addressed here before. After fixing a bug, log it below.

---

## #086 — Crash-safe patch for `python_bitvavo_api` negative-sleep bug (2026-05-06)

### Context
Dashboard backend (and any process using the Bitvavo lib) crashed silently around 22:47 with `ValueError: sleep length must be non-negative` originating from `python_bitvavo_api.bitvavo.rateLimitThread.waitForReset(waitTime)`. When the rate-limit reset window has already passed, `waitTime` becomes negative; `time.sleep(waitTime)` then raises and kills the rateLimitThread. The thread death cascades: WebSocket / REST callers hang, dashboard heartbeat freezes, watchdog also dies, port 5002 stops responding. User reported "Data in het dashboard is stale en klopt niet."

### Solution
- New `modules/bitvavo_patch.py` — module-level monkey-patch that wraps `rateLimitThread.waitForReset` to clamp the sleep duration with `max(0.0, float(waitTime or 0))`. Idempotent (`_PATCHED` flag). Auto-applies on import.
- Imported once at the top of `trailing_bot.py` (right after `load_dotenv()`, before any module that may instantiate the Bitvavo client).
- Imported once in `tools/dashboard_v2/backend/main.py` (after `STATIC = ...`) so the dashboard process is also protected.
- Direct edit of `.venv/Lib/site-packages/python_bitvavo_api/bitvavo.py` for belt-and-braces (will not survive `pip install`, hence the runtime patch is the source of truth).

### Verification
- Verified `_PATCHED=True` and the new `waitForReset` source after import.
- Dashboard backend restarted cleanly; `/api/health` returns `heartbeat_age_s=28.15`, `bot_online=true`, `ai_online=true`.

### Files
- `modules/bitvavo_patch.py` (NEW)
- `trailing_bot.py` (1 import line)
- `tools/dashboard_v2/backend/main.py` (try/except import block)

---

## #085 — Score histogram logging (MIN_SCORE realism observability) (2026-05-06)

### Context
User asked: "Is MIN_SCORE 18 wel realistisch — zal er ooit een trade 18 scoren?" There was no live observability of the score distribution per scan, so we could not see whether the bot was starving because of bad markets or because the threshold is mis-calibrated.

### Solution
In the entry scan loop in `trailing_bot.py` (just before the `if score < min_score_threshold` filter), accumulate `(market, score)` into `all_scores`. After the scan summary log, compute and emit:
- Buckets: `<5`, `5-7`, `7-9`, `9-12`, `12-15`, `15-18`, `>=18`.
- Aggregate stats: count evaluated, max, mean, median.
- Top-5 markets by score.
- Append a JSONL record to `data/score_histogram.jsonl` per scan: `{ts, threshold, evaluated, max, median, mean, buckets, top5, regime}`.
- Stash latest snapshot to `CONFIG['LAST_SCORE_HISTOGRAM']` so the dashboard can surface it.

### Findings (from archive analysis at fix time)
- 51 trades had a score logged. Max=32.7, mean=15.3, median=13.2, p90=21.5.
- Bucket distribution: `<7=0`, `7-9=1`, `9-12=17`, `12-15=10`, `15-18=8`, `>=18=15` (~29% of historical trades reach ≥18).
- Live scan at fix time: 0 markets passing for >25 min — bot starving.

### Files
- `trailing_bot.py` (~60 LOC: `all_scores` accumulator + histogram block)
- `data/score_histogram.jsonl` (new append-only log)

---

## #084 — Persistent cost-basis cache for swaps / airdrops / recoveries (2026-05-05)

### Context
After FIX #083 recovered NOT-EUR with `buy_price=€0.000431, invested=€617.97`, the value kept resetting to `buy_price=current_price, invested=0` on every bot startup. Because NOT-EUR was acquired via an **ENJ→NOT swap**, `bv.trades('NOT-EUR')` returns no fills — so `derive_cost_basis()` returns None, the archive recovery returns None, and `sync_engine` falls back to "use current price as buy_price" with `invested_eur=0`. Result: dashboard shows "Geïnvesteerd: —", trailing/DCA decisions get wrong basis, P&L view broken. The user had to manually re-fix the file every restart.

### Solution
New `core/cost_basis_cache.py` — persistent JSON cache (`data/cost_basis_cache.json`), RLock-protected, atomic tmp+replace writes, no TTL. API: `get(market)`, `set(market, buy_price, invested_eur, amount, source)`, `remove(market)`, `restore_into(market, trade)`.

`restore_into()` is the integration point: it writes cached cost-basis fields into a trade dict ONLY when those fields are unset/zero. Critically:
- Never overwrites a valid existing buy_price/invested_eur.
- Never lowers `highest_price` (preserves trailing high-water mark).
- Returns False when cache empty → safe to call unconditionally.

### Integration points (3 sync paths)
1. `bot/sync_engine.py` existing-local merge: when `initial_invested_eur <= 0`, check cache first **before** calling `derive_cost_basis`.
2. `bot/sync_engine.py` new_local re-adopt: same — cache lookup before derive.
3. `modules/sync_validator.py auto_add_missing_positions`: cache lookup as the first cost-basis source, before derive_cost_basis / FIFO / archive fallbacks.

### Cache seeded for current positions (one-off)
- NOT-EUR: buy_price=€0.00043070, invested=€617.97, source=`enj_swap_2026-05-05`
- ENJ-EUR: buy_price=€0.045344, invested=€660.14, source=`manual_recovery`
- RENDER-EUR: buy_price=€1.573830, invested=€309.72, source=`manual_recovery`

### Changes
- `core/cost_basis_cache.py` (NEW, ~130 LOC).
- `bot/sync_engine.py`: 2 cache-lookup blocks added (existing-local + new_local).
- `modules/sync_validator.py`: cache lookup as 1st cost-basis source in `auto_add_missing_positions`.
- `tests/test_cost_basis_cache.py` (NEW): 9 tests across `TestCacheCRUD` (4) + `TestRestoreInto` (5). All passing.
- `data/cost_basis_cache.json` (NEW data file, seeded with 3 entries).

### Verification
- 15/15 tests pass (9 new + 4 phantom-safety + 2 dca-preserves).
- After bot restart, NOT-EUR's cost basis survives sync.

### Lesson
For any "derived state" that can't be reconstructed from external truth (Bitvavo API), provide an authoritative override layer. `bv.trades()` is incomplete — swaps, airdrops, internal transfers, dust consolidations all leave coins with no order history. The cache is that override layer. Same pattern as `core/entry_metadata.py` (FIX #074): persistent JSON, RLock, restore-only-when-unset, never lower trailing high.

---

## #083 — Phantom-fix nuked real positions on transient API hiccup (2026-05-05)

### Context
At bot restart 15:48, the startup `SyncValidator.auto_fix_phantom_positions()` deleted **ENJ-EUR** AND **RENDER-EUR** from `data/trade_log.json` even though the user still held both on Bitvavo (14,558 ENJ + 196 RENDER). RENDER had perfectly clean sync — no mismatch, no desync — yet still got wiped. Combined with NOT-EUR being created via SWAP from ENJ (which also looked like an amount mismatch on ENJ), the user was left with **3 untracked positions worth €1545** (ENJ €619, NOT €612, RENDER €313): bot had no view of them, no trailing stop, no exit logic.

### Root Cause
`auto_fix_phantom_positions` calls `get_bitvavo_balances()` once and trusts the result. If that call returns an empty dict (transient API hiccup, rate-limit, network blip, partial response), then EVERY bot position appears phantom because `if symbol not in bitvavo_balances` is True for everything. The function then deletes them all.

There were zero safety gates: no empty-result check, no second-fetch verification, no max-deletion threshold.

### Solution (3 defensive gates in `modules/sync_validator.py`)
1. **Gate 1 — empty fetch**: if first `get_bitvavo_balances()` returns `{}` → log error, return 0 (delete nothing).
2. **Gate 2 — second-fetch verification**: do a second independent fetch; if it's empty → abort. If both succeed but disagree on which symbols exist, **union** the symbol sets so a transient miss in one fetch can't mark a real position as phantom.
3. **Gate 3 — majority threshold**: if the candidate-deletion list would remove ≥ 50% of non-skipped bot positions, that's a sync bug not reality → abort and require manual review.

### Recovery (separate one-off script)
`tmp/recover_positions.py --apply` re-imports the 3 untracked positions into `trade_log.json` with derived cost basis:
- ENJ-EUR: €0.045344 from 7 historic buy fills (€660 cost)
- NOT-EUR: €0.000461 derived from ENJ→NOT swap (14593.89 ENJ × €0.045344 = €661.75 cost)
- RENDER-EUR: €1.573830 from 1 historic buy fill (€310 cost)

### Changes
- `modules/sync_validator.py` (auto_fix_phantom_positions): 3 safety gates added (~35 LOC).
- `tests/test_sync_validator_phantom_safety.py` (NEW): 4 regression tests covering empty-fetch abort, majority-threshold abort, single-genuine-phantom happy path, and partial-fetch union behaviour. All passing.
- `tmp/recover_positions.py` (one-off): re-imports the 3 lost positions.

### Verification
- 6/6 tests pass (4 new + 2 existing sync_validator tests).
- `data/trade_log.json` now has ENJ-EUR, NOT-EUR, RENDER-EUR with correct cost basis.
- Backup of pre-recovery trade_log saved to `data/trade_log.json.recovery_backup_<ts>`.

### Lesson
Never delete persistent state based on a single API call. Any irreversible operation triggered by external state must:
(a) verify the input is non-empty/non-degraded,
(b) cross-check via a second independent fetch,
(c) refuse to act if the proposed change is unreasonably large.
This is the same defensive pattern as FIX_LOG #001's "always derive from full order history" rule applied to deletion logic.

---

## #082 — Cold-Tier Auto-Discovery: bridge unknown markets → warm watchlist (2026-05-05)

### Context
User requested: "implementeer (a) de tiered-scanning verkennen". Existing tiered system has hot tier (`WHITELIST_MARKETS`, ~18 markets, scanned every 25s) and warm tier (`WATCHLIST_MARKETS`, micro-mode entries via `modules/watchlist_manager.py` with mature promote/demote logic). Gap: ~370 EUR markets on Bitvavo never get looked at because the warm tier only fills when AI explicitly queues markets — there is no proactive scanner of the cold tier.

### Solution
New `scripts/cold_tier_scanner.py` (cron-friendly, ~210 lines): one cheap public Bitvavo `ticker24h({})` call returns all ~428 EUR markets with last/volume/24h-change. A simple per-candidate heuristic ranks them:

`score = log10(volume_eur) + |Δ24h|/5 − max(0,|Δ24h|−25)/5 − max(0,|Δ24h|−50)/5 − (5 if vol<floor)`

Excludes everything already on whitelist/watchlist/kill-zone/blacklist (read from all 3 config layers). Default dry-run prints ranked top-10 + writes `tmp/cold_tier_proposals.json`. With `--apply` appends top-N (default 2) to `WATCHLIST_MARKETS` in **LOCAL config only** (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`) — the existing `watchlist_manager` then handles micro-mode entries and promote/demote via its analytics-driven review.

### Changes
- `scripts/cold_tier_scanner.py` (NEW): scanner with `--apply`, `--n`, `--min-volume` flags. Reads excluded markets from all 3 config layers. Writes only to local config (avoids OneDrive revert bug in `watchlist_manager._write_config`).
- `tests/test_cold_tier_scanner.py` (NEW): 11 tests across `TestScoring`, `TestRanking`, `TestApplyTopN`. All passing.

### Verification
- 11/11 tests PASSED.
- Live dry-run: 428 EUR markets fetched, 31 excluded, 14 candidates passed €750k volume floor. Top-2: TON-EUR (+36.9%, €5.1M vol, score 11.71) and NOT-EUR (+27.9%, €1.7M vol, score 11.23).

### Lesson
Don't duplicate existing infra. `watchlist_manager.py` was already mature with promote/demote/review — the actual gap was ONE step earlier (cold→warm discovery). Building a second promotion engine would have been over-engineering. Also: scanner writes only to local override, never to `config/bot_config.json`, to avoid the latent OneDrive-revert bug in `watchlist_manager._write_config` (separate fix for another day).

### Related
- #081 Deep-Dip Hunter (companion edge for unusual market conditions).
- `modules/watchlist_manager.py::queue_market_for_watchlist` — would be the canonical entrypoint, but has the OneDrive-write bug; cold scanner deliberately writes local-only.
- Suggested cron: hourly, with `--apply --n 1` after 1 week of dry-run review.

---

## #081 — Deep-Dip Hunter: catch -25%+ dumps that have stabilised (2026-05-05)

### Context
User observation: "ik kijk soms naar bitvavo, en dan kijk ik naar trades die heel erg ver zijn gezakt, wel 30%, soms koop ik die en is die erg winstgevend, zo is dat ook gegaan bij ZEUS. de bot doet hier niets mee."
The standard signal pipeline INTENTIONALLY avoids these (looks like falling knife — MACD negative, regime BEARISH/HIGH_VOLATILITY → low score → blocked). Mostly correct, but selective dip-buys on quality markets that have stopped falling can yield 8-20% bounces in 24-72h.

### Solution (deliberately conservative)
New module `core/deep_dip_hunter.py` runs as a **score booster**, not a buy-trigger. All standard quality gates still apply (regime, correlation shield, kill-zone). The hunter only adds +5.0 score when ALL the following pass:
- Drawdown peak→now in last 48h ≥ 25% (configurable)
- Drawdown ≤ 60% (cap: avoid true rugs)
- Last 4h: no new low (price has bottomed)
- Last bar GREEN (close ≥ open OR close ≥ prev close)
- Bounce from absolute low ≥ 1% (confirmation, not knife)
- 24h volume ≥ €500k (no shitcoins)
- Market NOT in kill_zone blacklist (those crashed for fundamental reasons)

The +5.0 boost helps a depressed signal score (typically 13-15 in dump conditions) clear MIN_SCORE_TO_BUY=18 without globally lowering the bar.

### Changes
- `core/deep_dip_hunter.py` (NEW): `detect_deep_dip(market, candles_1h, volume_24h_eur, config, blacklist)` → `(active, boost, reason, details)`. Pure function, ~190 lines.
- `trailing_bot.py` (line ~2598): wired call between whitelist boost and `min_score_threshold` check. Fetches 50× 1h candles + 24h volume, passes `KILL_ZONE_MARKETS` as blacklist. Logs `[DEEP_DIP] {m}: ACTIVE +5.0 (...) score→XX`.
- `tests/test_deep_dip_hunter.py` (NEW): 14 tests across `TestDeepDipBasics`, `TestQualityGates`, `TestStabilisation`, `TestConfigOverrides`, `TestRobustness`. All passing.
- Local config: added 7 keys (`DEEP_DIP_HUNTER_ENABLED`, `DEEP_DIP_LOOKBACK_HOURS=48`, `DEEP_DIP_MIN_DROP_PCT=25`, `DEEP_DIP_MAX_DROP_PCT=60`, `DEEP_DIP_STABILISE_HOURS=4`, `DEEP_DIP_MIN_VOLUME_EUR=500000`, `DEEP_DIP_SCORE_BOOST=5.0`).

### Verification
- 14/14 deep_dip tests PASSED
- Position sizing & trailing stops are UNCHANGED (Phase 1: detection + boost only). If 30-day live data confirms edge, Phase 2 will add half-size BUY + wider trailing stop for dip entries.

### Lesson
Survivorship bias warning: user remembers ZEUS-style winners, not the 5 dips that became -50% rugs. Mitigated via (a) max-drop cap (-60%), (b) green-bar + bounce confirmation (price has actually stopped falling), (c) volume gate (no shitcoins), (d) blacklist veto (markets that crashed for real reasons stay blocked). The hunter does NOT lower MIN_SCORE_TO_BUY; it only helps qualifying dips reach the existing floor.

### Related
- Tiered scanning: `WHITELIST_MARKETS` (hot tier, ~18 markets, scanned every 25s) + `WATCHLIST_MARKETS` (warm tier, micro-mode entries) already exist. Auto-promotion from cold→warm based on Wilson stats is a separate future task — current `scripts/auto_blacklist_learner.py` only blocks/whitelists, doesn't promote unknowns to scan list.
- Whitelist boost was bumped from +2.0 → +4.0 (proportional fix: MIN_SCORE_TO_BUY is 18, not 7.0 as instructions claimed; +4.0 on 18 = same relative weight as original +2.0 on 7.0).

---

## #080 — Heartbeat writer never started + dashboard "€0 totaal" + price-flash dead (2026-05-05)

### Context
User reported three dashboard issues simultaneously:
1. "Totaal kapitaal €0,00 €-1.920,01 (-100%) sinds storting — Waarom staat er 0?" while bot clearly held €1557 in ENJ + RENDER positions.
2. Live price did not flash green/red on changes.
3. "Bot offline" pill shown even though `trailing_bot.py` PID 22280 was actively scanning markets and writing logs.

### Diagnosis
- `data/heartbeat.json` mtime was **13:54:30**, but the bot had been running since **14:07:55** — meaning the bot's heartbeat-writer thread was NEVER ticking after restart.
- Root cause: `trailing_bot.py::initialize_managers()` creates `monitoring_manager = MonitoringManager(...)` as a **local variable** but never assigns it to `bot.shared.state.monitoring_manager`. The shim `bot/scheduler.py::start_heartbeat_writer()` does `mgr = getattr(state, "monitoring_manager", None) or globals().get("monitoring_manager")` → both return None → silent return → no thread starts.
- This also broke `start_heartbeat_monitor` and `start_reservation_watchdog`.
- `data/account_overview.json` had `total_account_value_eur: 0.0` while `open_trade_value_eur: 1647.92`. The overview file was 12 minutes stale because `bot/portfolio.py::write_account_overview` had `except Exception: return None` — silently swallowing whatever started failing intermittently. No log line, no traceback, impossible to diagnose.
- Frontend `app.js` price-flash diff iterated `for (const tr of opens)` where `opens = this.t.open || []`. But `this.t.open` is a **dict keyed by market**, not an array. `for..of` over a plain object yields nothing → no price changes ever detected → no flash animation.

### Changes
- `trailing_bot.py` (~line 3845): after `monitoring_manager = MonitoringManager(...)`, register all three managers on `bot.shared.state` so the scheduler shims can find them. Added explicit info log "Background threads gestart: ...".
- `bot/portfolio.py::write_account_overview`: replaced silent `except Exception: return None` with proper `S.log("[ERROR] write_account_overview failed: ...", level="error")` so future failures are visible.
- `tools/dashboard_v2/backend/main.py::_portfolio()`: defensive fallback — when `total_account_value_eur <= 0` but `eur_available + open_trade_value_eur > 0`, sum them as the displayed total. Avoids "€0 totaal" when overview snapshot is briefly stale.
- `tools/dashboard_v2/frontend/app.js` (~line 180): fixed `for..of` over dict bug. Now uses `Object.values(this.t.open || {})` (with array fallback for backwards compat). Live price flashes green/red on every change again.
- Cache: `index.html` `?v=8 → ?v=9`, `sw.js` `VERSION 6 → 7`.

### Verification
- Restart bot to pick up `state.monitoring_manager` change. Verify `data/heartbeat.json` mtime refreshes every ~30s.
- Verify dashboard topbar pill shows "online" within 3 minutes (180s threshold).
- Verify dashboard "Totaal kapitaal" shows non-zero when EUR or asset value > 0.
- Verify open-position row green/red flashes on live price tick.

### Lesson
Three independent silent-swallow bugs cascaded into "the dashboard is dead". Lesson: **never `except Exception: pass/return None`** without a log. The cost of one extra log line is negligible compared to spending 30 minutes diagnosing a stale snapshot file. Also: when refactoring a monolith into a `state` singleton, every locally-bound manager MUST be registered on `state` or every shim that consults `state.<manager>` becomes a no-op.

---



### Context
After Kill-Zone Filter (#078) shipped, user asked: "backtest al je ideeen, en we zijn nu alleen aan het blacklisten — niet aan het whitelisten. Misschien moet er soms een markt op de whitelist die veel potentie heeft."
Backtested 6 ideas + 4 trailing-stop alternatives over 60d (22 markets, 1h candles) and 7-month archive (870 trades).

### Backtest Findings
- **Whitelist (Wilson lower bound, n>=15)**: WIF-EUR (87.4%), ACT-EUR (82.1%), MOODENG-EUR (78.9%), PTB-EUR (74.3%) → high-conviction markets
- **Extended blacklist** (avg PnL <€-0.50 OR Wilson <40%): INJ-EUR, SOL-EUR, AVAX-EUR, XRP-EUR, ZEUS-EUR added
- **Auto-blacklist learner sim**: blocking 5 worst markets recovers ~+€65 over 7 months (~+€9/mo)
- **Trailing-stop alternatives REJECTED**: backtested CURRENT (€95.67), WIDER (€59.22), ATR_ADAPT (€58.81), HYBRID (€43.45) — current stepped trailing is optimal. The "132% upside missed" theory was misleading; alternatives gave back more in dips than they captured in winners.

### Changes
- `core/kill_zone_filter.py`:
  - `DEFAULT_BLACKLIST` extended: USDC, DOT, ADA → + INJ, SOL, AVAX, XRP, ZEUS
  - New `DEFAULT_WHITELIST = (WIF, ACT, MOODENG, PTB)`
  - New Rule 0 in `is_kill_zone()`: whitelist precedence — bypasses ALL filters (incl. blacklist)
  - New `whitelist_score_boost(market, config) -> float` returns +2.0 (configurable) for whitelisted markets, 0.0 otherwise
  - New config keys: `KILL_ZONE_WHITELIST`, `WHITELIST_SCORE_BOOST`, `WHITELIST_BOOST_ENABLED`
- `trailing_bot.py` (line ~2585, between `[CORR_SHIELD]` and `min_score_threshold` check): wired `whitelist_score_boost` — adds bonus to score BEFORE the MIN_SCORE_TO_BUY=7.0 floor (so high-potential markets clear threshold easier without lowering it globally).
- `tests/test_kill_zone_filter.py`: 18 → 29 tests. New `TestWhitelist` (3) + `TestScoreBoost` (7) + updated `test_default_blacklist_constant`.
- `scripts/auto_blacklist_learner.py` (NEW): periodic (cron-friendly) script. Reads `data/trade_archive.json`, computes per-market 60d rolling Wilson-bound stats. Suggests blacklist additions (Wilson <40% OR avg_pnl <-€0.50, n>=10), whitelist additions (Wilson >=70%, n>=15, profitable), and blacklist removals (recovered: Wilson >=55%). Default: dry-run. `--apply` writes to local config; `--notify` sends Telegram. USDC-EUR is in `PROTECTED_BLACKLIST` (never auto-removed). First run found LINK-EUR as new whitelist candidate (97% wr, n=35).
- Local config (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`): added new keys.

### Verification
- `pytest tests/test_kill_zone_filter.py -v` → 29/29 PASSED
- Full suite: 849 passed, 3 skipped
- Lint clean
- MIN_SCORE_TO_BUY stays LOCKED at 7.0 (whitelist boost is additive, not a threshold lowering)

### Lesson
Blacklist alone leaves money on the table — high-potential markets deserve a small score boost (+2.0) so they reach the 7.0 floor more easily without globally lowering the bar. The auto-learner closes the feedback loop: bot trades → archive → learner suggests new blacklist/whitelist → human approves via `--apply`. Backtest BEFORE deploying ideas: trailing-stop tweaks looked great in theory ("132% upside!") but lost money in practice.

---

## #078 — Kill-Zone Filter (anti-XGBoost veto layer) added (2026-05-05)

### Context
After 3 iterations of revolutionary-strategy backtests (predator/H1/H2/H3, then train-test split exposing H2 as overfit), pivoted to a META improvement: **post-mortem analysis on the bot's own 658 historical trades** (`trade_features.csv`).

### Findings (cross-validated, decision tree depth=3, 5-fold CV)
- Baseline win-rate: 61.4%
- CV accuracy: 64.6% ± 6.9% — real predictive signal
- RSI < 45 + low volume (<5000): 53 trades, **20.8% win-rate**
- Markets USDC-EUR (0/24), DOT-EUR (18% / 50), ADA-EUR (33% / 15) — historical loss leaders
- price/SMA > 1.8 (price extended): 65 trades, **26.2% win-rate**

### Impact (from production data, no overfit)
- Blocking the 5 strongest kill-zones: 86 trades blocked (13.1% of volume)
- Survivors win-rate: **67.7%** (vs 61.4% baseline) → **+6.3pp uplift**
- Estimated savings: ~€183 per 7 months ≈ **€26/month structural**

### Implementation
- New module `core/kill_zone_filter.py` — pure functions `is_kill_zone()` + `compute_features_from_candles()`. No I/O, no state.
- Wired into `bot/orders_impl.py::place_buy` between exposure check and budget reservation. Skipped for DCA buys and existing open trades. Fetches 60×1m candles via cached `safe_call(bv.candles)` → cheap (cached).
- Config keys (in local override only): `KILL_ZONE_ENABLED=true`, `KILL_ZONE_MARKETS=["USDC-EUR","DOT-EUR","ADA-EUR"]`, `KILL_ZONE_RSI_MAX=45.0`, `KILL_ZONE_VOL_MIN=5000`, `KILL_ZONE_PRICE_EXT=1.8`.

### Failure modes guarded
- Filter raises → caught, logged at debug, entry proceeds (fail-open).
- Candle fetch fails → empty features dict → only blacklist rule active.
- Pure-function design enables 18 unit tests to fully cover behaviour without mocking the bot.

### Verification
- `pytest tests/test_kill_zone_filter.py -v` → **18 passed**.
- Backtest output saved at `tmp/kill_zones.log`.

### Files changed
- `core/kill_zone_filter.py` (new)
- `bot/orders_impl.py` (insert kill-zone block after step 1c)
- `tests/test_kill_zone_filter.py` (new, 18 tests)
- `tmp/find_kill_zones.py` (research script — kept as documentation)
- `%LOCALAPPDATA%/BotConfig/bot_config_local.json` (5 new config keys)

---

## #077 — 3 production runtime errors found in logs (2026-05-05)

### Symptoms (recurring every loop)
1. `Reinvest logic faalde: '>' not supported between instances of 'str' and 'int'`
2. `AIEngine: portfolio status error: 'str' object has no attribute 'get'`
3. `Kon ..\data\ai_advanced_analysis.json niet schrijven: [Errno 2] No such file or directory: '..\data\ai_advanced_analysis.json.tmp'`

### Root causes
1. **Reinvest** (`bot/trade_lifecycle.py`): `t.get("timestamp", 0) > last_ts` — when trade timestamp loaded from JSON is an ISO string, the `>` comparison vs the int `LAST_REINVEST_TS` raises TypeError. Crashed on every reinvest tick → no reinvest ever ran.
2. **AI portfolio status** (`modules/ai_engine.py` `get_portfolio_status`): iterated `balance` from Bitvavo without validating the response shape. On rate-limit/circuit-breaker fallback, the wrapper can return a dict (error envelope) or a list with non-dict items, exploding on `.get()`.
3. **AI supervisor** (`ai/ai_supervisor.py`): hard-coded `os.path.join('..', 'data', ...)` for trade_log read and ai_advanced_analysis write — only worked when CWD == `ai/`. The whole module already defines `_PROJECT_ROOT`; these two call-sites were missed.

### Fixes
1. Added `_ts_to_float()` local that coerces numeric strings + ISO datetimes to float; both sides of the comparison now go through it. Profit also coerced via `float(... or 0)`.
2. Added `isinstance(balance, list)` guard up-front + `isinstance(asset, dict)` per-iteration skip; defensive `or 0.0` on numeric extraction.
3. Replaced both `os.path.join('..', 'data', ...)` with `os.path.join(_PROJECT_ROOT, 'data', ...)`.

### Verification
- 820 passed, 3 skipped (`pytest tests/ -q`).
- Lint clean on changed files.

### Files changed
- `bot/trade_lifecycle.py` (reinvest block)
- `modules/ai_engine.py` (`get_portfolio_status`)
- `ai/ai_supervisor.py` (lines 1445, 1467)

---

## #076 — Bot-opened trades lost score/regime/RSI/MACD metadata after sync re-adopt (2026-05-05)

### Symptom
Open trades that were demonstrably opened by the bot (e.g. `ENJ-EUR`, `RENDER-EUR`) showed `score=0.0`, `opened_regime='unknown'`, `volatility_at_entry=0.0`, `rsi_at_entry=None` after some hours/days. User: *"Ik heb deze trades niet geopend dit heeft de bot gedaan, ik denk dat de gegevens verloren raken door de sync"*. AI logs and downstream analytics treated these as "manual buy" entries with no entry intelligence.

### Root cause
Multiple legitimate paths can drop a trade from `state.open_trades` while the position still exists on Bitvavo:
- `auto_free_slot` (low-PnL eviction, then sync re-adopts moments later)
- atomic `trade_log.json` save failure mid-cycle
- crash/restart between order-fill and `save_trades_atomic`

When this happens, `bot/sync_engine.py` rebuilds the trade from balance + order history (`new_local` path) with **default sentinels**: `score=0.0`, `opened_regime='unknown'`, `volatility_at_entry=0.0`, no `rsi_at_entry`. The original entry context is gone forever — sync has no source for it.

### Fix
1. New `core/entry_metadata.py` — persistent JSON cache (`data/entry_metadata.json`) keyed by market with 30-day TTL, RLock-protected, atomic tmp+replace writes. Stores ~15 entry-time fields (score, regime, all `*_at_entry` indicators, volume_24h_eur, opened_ts, _entry_source).
2. `trailing_bot.py` — after every successful initial buy, call `entry_metadata.record(market, trade)` to snapshot the rich entry context.
3. `bot/sync_engine.py` — both sync paths (existing-local merge + `new_local` re-adopt) now call `entry_metadata.restore_into(market, trade)`. Restore only overwrites sentinel defaults (score==0.0, regime in {'unknown','sync_attach'}, vol==0.0) — never clobbers real values. Sets `_metadata_restored_from_cache=True` flag for traceability.
4. `bot/close_trade.py` — calls `entry_metadata.clear(market)` after successful close to keep cache lean.
5. Sync re-adopts now label `opened_regime='sync_attach'` (instead of `'unknown'`) and `_entry_source='sync_attach'` so true sync-orphans (no cache) are distinguishable from real bot entries.

### Verification
- 820 tests pass + 3 skipped (`pytest tests/ -q`).
- No errors on changed files.
- Manual test: closing a trade via `close_trade` removes its cache entry; opening a new trade writes a cache entry within the same loop tick.

### Files changed
- `core/entry_metadata.py` (NEW)
- `trailing_bot.py` (~line 3596 — record after `_ti_set_initial`)
- `bot/sync_engine.py` (both ~line 300 + ~line 388 paths)
- `bot/close_trade.py` (~line 129)

---

## #075 — `sync_validator` add-missing wiped reconciled DCA + trailing state on every cycle (2026-05-04)

### Symptom
Dashboard for `ENJ-EUR` showed **"DCA 0/3"** even though the trade had been reconciled to 4 DCA events with `invested_eur=€1201.80`. Logs proved FIX #074's reconcile path ran successfully every ~10 minutes:

```
[08:32:31] RECONCILE [ENJ-EUR] DCA #1..#4 recovered, initial_invested_eur €1201.80 → €285.23
[08:41:32] RECONCILE [ENJ-EUR] DCA #1..#4 recovered, initial_invested_eur €1201.80 → €285.23
[08:50:20] RECONCILE [ENJ-EUR] DCA #1..#4 recovered, initial_invested_eur €1201.80 → €285.23
```
…but each time the next sync pass wiped the recovered state again.

### Root cause
`modules/sync_validator.py::auto_add_missing_positions` decided ENJ-EUR was "missing from `bot_positions`" at 07:55 (likely due to a transient read while `trade_log.json` was mid-write or a brief desync race). It then UNCONDITIONALLY **overwrote** the existing entry with a fresh dict:

```python
trade_log['open'][add['market']] = {
    'dca_buys': 0,
    'dca_events': []  # never present, so empty
    'trailing_activated': False,
    'highest_since_activation': None,
    'initial_invested_eur': add.get('initial_invested_eur', invested),  # = total cost!
    ...
}
```

This wiped `dca_events`, `dca_buys`, `trailing_activated`, `highest_since_activation`, and corrupted `initial_invested_eur` (set to total cost basis = €1201.80 instead of the true initial €285.23). Every cycle: reconcile recovers → next sync wipes → repeat.

### Fix
`modules/sync_validator.py` extracted apply-loop into `_apply_additions(...)` and added a guard:

```python
existing = trade_log['open'].get(mkt)
if isinstance(existing, dict):
    has_dca_events = bool(existing.get('dca_events'))
    has_dca_buys = int(existing.get('dca_buys', 0) or 0) > 0
    has_initial = float(existing.get('initial_invested_eur', 0) or 0) > 0
    if has_dca_events or has_dca_buys or has_initial:
        # MERGE: only refresh amount + synced_at; keep DCA/trailing intact
        existing['amount'] = add['amount']
        existing['synced_at'] = timestamp
        continue
```

Existing entries with any reconciled state are now MERGED (amount + synced_at refreshed), never overwritten. New entries (truly missing) still get the full default dict.

### Tests
`tests/test_sync_validator_preserves_dca.py`:
- `test_existing_entry_with_dca_history_is_preserved` — ENJ entry with 4 events, `dca_buys=4`, `trailing_activated=True`, `initial_invested_eur=€285.23` survives an `_apply_additions` call that would normally inject `initial_invested_eur=€1201.80`.
- `test_missing_entry_is_added_normally` — truly missing market still gets full default entry.

### Manual repair
Re-ran `tmp/reconcile_enj.py` → ENJ now has `dca_buys=5, dca_events=5, amount=27827.40, invested_eur=€1281.80` (one more DCA happened post-FIX #074).

### Lesson
**NEVER overwrite an existing trade entry from a sync/recovery path.** If the entry exists, MERGE only the volatile sync fields (amount, synced_at). Reconciled state (DCA history, trailing activation, immutable initial_invested_eur) must be treated as ground truth — wiping it forces every dependent invariant to drift. Sync paths should fail-soft (log + skip) rather than fail-destructive (overwrite).

---

## #074 — DCA pending limit-order: invisible-order branch dropped fills → 4 cascading DCAs on ENJ (2026-05-04)

### Symptom
ENJ-EUR fired **4 DCA orders** in ~30 minutes (max=3): €80 + €288 + €288 + €259 ≈ €915 extra spent on top of the €285 initial. Telegram delivered duplicate "DCA 1/3" notifications. After-state in `data/trade_log.json`:
- `amount=26026.94 ENJ` (correct via sync engine)
- `invested_eur=€365.35` (FOUT — actual ~€1201)
- `dca_buys=0` (FOUT — should be 4)
- `dca_events=[]` (empty — fills never recorded)

### Root cause (regression from FIX #073)
`modules/trading_dca.py:_check_pending_dca_order` had a fallback branch for when `bitvavo.getOrder()` returned `None` AND `bitvavo.ordersOpen()` did not contain the order:

```python
if not order:
    self._record_dca_audit(... 'pending_order_invisible_cleared' ...)
    self._clear_pending_dca(trade)
    return 'cleared'
```

Bitvavo MAKER limit orders that have **filled** sometimes briefly disappear from both `getOrder()` and `ordersOpen()` (filled, removed from active book, history not yet served). The "be conservative, clear it" path silently dropped the fill: `dca_buys`/`dca_events` were never updated. The sync engine independently corrected `amount` from the exchange balance but `derive_cost_basis` does not touch `dca_buys`/`dca_events`, so the next DCA loop saw `dca_buys=0` and fired **another** DCA at level 1 (or whatever level the recomputed target hit). Repeat until price recovered above target.

The €80 → €288 amount jump was a **separate config issue**: local config had both `DCA_AMOUNT_EUR=80` and `DCA_AMOUNT_RATIO=0.9` set; `trailing_bot.py:3724-3728` formula prefers ratio: `BASE_AMOUNT_EUR (320) × 0.9 = €288`. The first €80 came from a per-trade `dca_amount_eur` field saved earlier under different config.

### Fix
`modules/trading_dca.py:_check_pending_dca_order` invisible branch now invokes `core.dca_reconcile.reconcile_trade()` against Bitvavo's order history instead of clearing silently:

```python
if not order:
    from core.dca_reconcile import reconcile_trade
    before_count = len(trade.get('dca_events') or [])
    rec = reconcile_trade(ctx.bitvavo, market, trade,
                          dca_max=int(settings.max_buys or 3), dry_run=False)
    after_count = len(trade.get('dca_events') or [])
    if (after_count - before_count) > 0:
        # missing fill recovered → record + clear pending
        self._record_dca_audit(... 'pending_invisible_reconciled' ...)
        self._clear_pending_dca(trade); ctx.save_trades()
        return 'filled'
    # genuinely never filled
    self._record_dca_audit(... 'pending_order_invisible_no_fill_in_history' ...)
    self._clear_pending_dca(trade); ctx.save_trades()
    return 'cleared'
```

If reconcile itself raises, the pending stash is **kept** (returns `'error'`) so the next loop retries `getOrder()` rather than firing a duplicate DCA.

### Manual repair
`tmp/reconcile_enj.py` ran `reconcile_trade('ENJ-EUR', dca_max=3)` → recovered all 4 missing events from order history, set `invested_eur=€1201.80`, `dca_buys=4`, fixed `initial_invested_eur` to actual initial buy. Backup at `data/trade_log.json.bak.fix074.<ts>`.

### Tests
`tests/test_dca_limit_order_tracking.py::TestInvisiblePendingTriggersReconcile`:
- `test_invisible_with_fill_in_history_records_event` — reconcile recovers fill → `dca_buys=1`, event added, pending cleared, no duplicate `place_buy`.
- `test_invisible_with_no_history_clears_without_double_dca` — no history → cleared cleanly without bumping counts.
- `test_invisible_reconcile_failure_keeps_pending_no_double_dca` — reconcile raises → pending preserved, **NO** duplicate DCA placed.

### Lesson
**Invisible ≠ never-filled.** When a tracked exchange order disappears, the truth lives in the order/trade history endpoint. Always reconcile from history before clearing local tracking, otherwise mutations done by other code paths (sync engine updating `amount` from balance) create silent desync that the next loop interprets as "no DCA done yet" and double-fires.

---

## #073 — DCA limit-order: split GEPLAATST/GEVULD + pending tracking + cascading guard + auto-timeout (2026-05-03)

### Symptom
After FIX #072, the Telegram message still arrived **immediately** when a MAKER limit DCA was placed (status='new', filledAmountQuote=0). User: *"zit er ook een timer op de limit order dca? wat als die niet bereikt wordt, wordt die dan opnieuw geplaatst?"*. Two latent risks:
1. Telegram fired "DCA Buy" before the order actually filled — misleading.
2. Next bot loop (~25s later) saw the price still below the trigger and would attempt **another** DCA at the same level → cascading limit orders stacking on the book.
3. `LIMIT_ORDER_TIMEOUT_SECONDS=None` and `bot/order_cleanup.py:cancel_open_buys_by_age()` skips any market that exists in `open_trades` → DCA limit orders would NEVER be auto-cancelled if they didn't fill.

### Root cause
`modules/trading_dca.py` had no concept of an in-flight pending order. After `place_buy()` succeeded it always:
- recorded a DCA event (FIX #072 mitigated the €0 corruption but the event was still recorded as "filled"),
- sent the Telegram alert,
- mutated `dca_buys` / `invested_eur`.

Next loop iteration would see `dca_buys` already incremented (good — no cascade for THAT level) BUT if the limit order then cancelled / expired externally, the bot had no way to detect or react. Conversely, if FIX #072 had been stricter and refused to record the event, the loop would have re-fired the same DCA every 25s.

### Fix
`modules/trading_dca.py` (both `_execute_fixed_dca` and `_execute_dynamic_dca` paths):

1. **Pending-order stash**: when `place_buy()` returns a non-filled limit response (`status='new'`, `filledAmountQuote=0`), the trade dict gets `pending_dca_order_id`, `pending_dca_order_ts`, `pending_dca_order_eur`, `pending_dca_order_price`, `pending_dca_order_market`. `dca_buys` / `invested_eur` are **NOT** mutated.
2. **Pre-place guard** (`_check_pending_dca_order`): at the top of every DCA loop, if a pending order exists, poll via `bitvavo.getOrder(market, oid)`:
   - `status='new'` / `partiallyFilled` and not timed out → return (no new placement).
   - `status='filled'` → record the actual fill (`add_dca` + `record_dca`), send "✅ GEVULD" Telegram, clear pending fields, continue.
   - `status='cancelled'` / `'rejected'` / `'expired'` → if there's a partial fill, record it; clear pending fields.
   - Order invisible (getOrder returns None and not in ordersOpen) → clear pending; sync engine will reconcile via `derive_cost_basis`.
   - Age > `DCA_LIMIT_ORDER_TIMEOUT_SECONDS` (default 600s) → call `cancelOrder` with `operatorId` fallback chain (kw → dict → positional), record any partial, clear pending fields.
3. **Telegram split**: limit-not-filled → `📥 DCA limit GEPLAATST {n}/{max} | Wacht op fill...`. Filled (immediate or via polling) → `✅ DCA Buy {n}/{max} GEVULD`.
4. **No change to `bot/order_cleanup.py`**: intentional — its `if market in open_trades: continue` guard protects DCA orders. With FIX #073's internal 600s timeout, DCA orders are self-managed and don't need the global cleanup.

### Verification
- 9 new tests in `tests/test_dca_limit_order_tracking.py` — all pass: unfilled stash, fill recording on poll, no-cascade-while-pending, timeout-cancel, market-order immediate fill, externally-cancelled clear, partial-fill-on-cancel.
- Updated 2 legacy mocks in `tests/test_trading_behaviors.py` (place_buy now requires explicit `status='filled'` + filled fields to be treated as filled).
- **Full suite**: 815 passed, 3 skipped in 122.54s — no regressions.

### Lesson
- **Separate "order placed" from "order filled" events.** A success response with `orderId` only proves acceptance, not execution. For MAKER limit orders this distinction is essential.
- Stash the pending orderId on the trade itself — the next loop iteration becomes the natural reconciler. No background thread or extra state file required.
- Always provide an internal timeout for any limit order the bot places. Don't depend on the global `LIMIT_ORDER_TIMEOUT_SECONDS` cleanup loop because intentional skip rules may exclude your market.

---

## #072 — DCA Telegram showed "Bedrag €0.00" + phantom dca_buys on MAKER limit orders (2026-05-03)

### Symptom
User: *"📉 DCA Buy 1/2 | ENJ-EUR ... Bedrag: €0.00"*. Bot fired ENJ DCA at 08:15:27, broadcast a €0.00 amount on Telegram, then subsequent inspection showed `dca_buys=0` and `dca_events=[]` in `data/trade_log.json`. The pending limit order was sitting on Bitvavo at €0.044379 unfilled.

### Root cause
1. `bot/orders_impl.py is_order_success()` returns True for `status='new'` (limit order accepted, not yet filled). MAKER orders rest on the book — they are valid, just not filled yet.
2. `modules/trading_dca.py` then read `buy_result['filledAmountQuote']` and **blindly overwrote** the fallback `actual_dca_eur=eur_amount` with `0.0` (the unfilled amount).
3. Downstream:
   - `core.trade_investment.add_dca(trade, 0.0)` returned silently with a warning → `invested_eur` did not grow.
   - `core.dca_state.record_dca(amount_eur=0, tokens_bought=0)` recorded a zero-value event → `dca_buys=1` in memory.
   - Telegram showed `Bedrag: €0.00`.
4. Sync engine then ran (rederives DCA state from exchange order *fills*), saw no fill yet → reset `dca_buys=0` and wiped `dca_events`. Bot was poised to fire **another** DCA next loop → cascading limit orders.

### Fix
`modules/trading_dca.py` (both legacy and dynamic ladder paths, lines ~579 and ~777): only overwrite `actual_dca_eur`/`actual_dca_tokens` from the response when the parsed value is **> 0**. Otherwise keep the fallback (the EUR commit). This:
- Telegram shows the committed amount (€80) instead of €0.00.
- `invested_eur` is incremented optimistically by the commit.
- Sync engine reconciles the actual filled amount once the limit fills (existing behaviour).
- If the limit cancels/expires, the bot's order_cleanup logic will detect and the trade reconciliation rules will adjust.

Also: cancelled the orphan limit order on Bitvavo (`bv.cancelOrder(market, orderId, operatorId='1')`) and cleared the stale per-trade `dca_amount_eur=20 / dca_drop_pct=0.025 / dca_max=2` baked into the 3 open trades from before FIX #071, so they now use the new globals (€80 / 3% / 3 max).

### Verification
- `get_errors` on `modules/trading_dca.py` → no errors.
- `bv.ordersOpen({'market':'ENJ-EUR'})` → 0 open after cancel.
- `data/trade_log.json` open trades all show `dca_amount_eur=None / dca_drop_pct=None / dca_max=None` → globals win.
- Bot restarted, dashboard restarted, `/api/health` → ok=true / bot_online=true.

### Lesson
- **Never trust an exchange API response field equal to 0 as authoritative**. A returned `filledAmount=0` on a `status='new'` limit order means "accepted, awaiting fill" — not "no fill ever". Use `> 0` guards before overwriting commit values.
- A naive "is_order_success" returning True for `status='new'` is fine for limit orders, but downstream code must distinguish *committed* from *filled*.
- Per-trade DCA settings (`dca_amount_eur` etc.) baked into trades override globals. After a config change, sweep `data/trade_log.json` to clear stale per-trade overrides — otherwise the new global never takes effect for existing positions.

---

## #071 — DCA never triggers on synced positions: DCA_MIN_SCORE blocks score=0 trades (2026-05-03)

### Symptom
User: *"waarom wort er geen dca uuitgevoerd op ENJ?"*. ENJ-EUR was -7.5% under entry but `dca_buys=0`. Same for SUI/RENDER. `bot.log` showed: `DCA voor SUI-EUR overgeslagen: trade-score 0.00 < DCA_MIN_SCORE 12.00`.

### Root cause
1. `modules/trading_dca.py` lines 157-175 enforce a hard gate: `if trade.score < DCA_MIN_SCORE: skip`.
2. Trades imported via `bot/sync.py` (positions held when bot was offline) get `score=0.0` because the entry score is unknown — there is no rescore-on-sync path.
3. With `DCA_MIN_SCORE=12` (Road-to-10 #061 default) **all synced trades are permanently DCA-blocked**.
4. Secondary: `DCA_AMOUNT_EUR=20` on a `BASE=320` trade = 6.25% — even if it triggered, cost-basis improvement would be -0.43% over the full 2-step ladder. Useless.

### Fix
Local config update (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`, hot-reloaded next loop):
- `DCA_MIN_SCORE`: 12 → **0** (gate disabled; synced trades can DCA)
- `DCA_AMOUNT_EUR`: 20 → **80** (25% of BASE; meaningful averaging)
- `DCA_MAX_BUYS`: 2 → **3** (drop coverage to -9%)
- `DCA_DROP_PCT`: 0.025 → **0.03** (avoid triggering on noise)

Math (normalised entry=1.0): full 3-step ladder with €80 DCAs at -3%/-6%/-9% → cost basis -2.69%, total per trade €560, max 4 trades = €2240 exposure (well within budget).

### Verification
- `load_config()` readback confirms all 4 keys live in CONFIG.
- ENJ next DCA trigger now at `0.047774 × 0.97 = 0.046341` (current 0.044205 → already below first trigger, will fire on next loop).
- Backup of pre-change local config saved as `bot_config_local.json.bak.<ts>`.

### Lesson
- A hard score gate on DCA assumes every open trade was opened by *this* bot in *this* session. False for synced positions — they have no score history.
- **Architectural alternative** (not done now, candidate for future): rescore open trades each scan cycle and write back `trade['score']`, so DCA gates work uniformly. For now `DCA_MIN_SCORE=0` is the pragmatic fix.
- Always sanity-check `DCA_AMOUNT_EUR / BASE_AMOUNT_EUR` ratio. Below ~15% the DCA is cosmetic.

---

## #070 — Duplicate trailing_bot processes: weak singleton guard (2026-05-02)

### Symptom
User: *"als je 1 doet, en we starten weer opnieuw op, dan heb je hetzelfde probleem"*. Two `trailing_bot.py` python.exe processes alive (PIDs 15748 and 21360), both children of monitor.py (10376). monitor.log showed only **one** `Starting trailing_bot.py` line. PID-file rewritten 13s after first launch by the second instance.

### Root cause
1. `trailing_bot.py` called `ensure_single_instance_or_exit('trailing_bot.py', allow_claim=True)`. With `allow_claim=True` a second instance does `taskkill` on the existing PID and continues. When the old process is busy with heavy imports it ignores the signal — both keep running.
2. `_acquire_windows_mutex_or_exit()` silently returned when `CreateMutexW` returned NULL (e.g. WinDLL load issue), falling back to the weaker PID-file path. No log.
3. `monitor.py` only used `_get_windows_pids_by_cmd_match('trailing_bot.py')` to detect duplicates. WMI/tasklist races during process start can return zero rows for a few hundred ms → monitor spawns a second instance.
4. No audit trail of who acquired/refused the singleton, so the spawn source could not be traced.

### Fix
1. `scripts/helpers/single_instance.py`:
   - Added `_audit(script_name, event, **fields)` → `logs/singleton_audit.log` with PID, PPID, parent cmdline, event (`mutex_acquired`, `mutex_already_exists`, `mutex_null_handle`, `mutex_exception`, `claim_attempt`, `claim_failed_target_alive`, `refused_existing_alive`).
   - `CreateMutexW` NULL handle now `sys.exit(1)` instead of silent fallthrough.
   - After `allow_claim=True` taskkill, verify the target PID actually died; if still alive → `sys.exit(1)` instead of running a duplicate.
2. `trailing_bot.py` line ~3987: `allow_claim=True` → `allow_claim=False`. Second instance exits cleanly.
3. `scripts/helpers/monitor.py` (around line 597): pre-Popen check now also reads `logs/trailing_bot.py.pid` and verifies via `psutil.pid_exists` before spawning. Closes the WMI-race window.

### Verification
- `pytest tests/ -k "single_instance or singleton or monitor"` → 7 passed, 2 skipped.
- `get_errors` on all three changed files → no errors.
- Bot stayed running during fix (no restart performed at user request).
- Effect after next restart: only one trailing_bot can exist; `logs/singleton_audit.log` will show the source if it ever happens again.

### Lesson
- Never trust WMI/tasklist as the **only** duplicate-process detector on Windows — it has a multi-100ms race window during `Popen`.
- `allow_claim=True` on a singleton is a footgun unless the kill is verified. Prefer "second instance exits cleanly".
- Always audit-log singleton decisions to `logs/singleton_audit.log` so the source of duplicates is traceable next time.

---
## #068 â€” Scan throughput: only 8/30 markets evaluated per cycle, scan_age 28 min (2026-05-01)

### Symptom
User: *"waarom worden er iedere keer maar zo weinig markten gescand en staat er laatste scan 28m geleden"*. Heartbeat showed `evaluated=2/30`, `scan_age=28min`, threshold=64.985. Bot log showed per-market scan time ~25â€“36 s; `SCAN_WATCHDOG_SECONDS=300` aborted after market 8/30. Cycle time ballooned from expected ~25 s â†’ 5+ min.

### Root cause
1. **`BITVAVO_CACHE_TTLS = {}` (empty)** in resolved config â†’ `safe_call()` cache disabled â†’ every `get_candles()`, `book()`, `tickerPrice()`, `ticker24h()` re-fetched from Bitvavo REST. Per market the scan loop calls `get_candles()` 4â€“6Ã— (signal_strength 1m+5m, momentum filter, VWAP, MTF confluence, BTC cascade, block-reason logging) plus orderbook + ticker24h. With occasional SSL flake â†’ 25â€“36 s per market.
2. **`BLOCK_ENTRY_REGIMES` regime block was checked AFTER signal_strength** (line 2560), so when regime=BEARISH the bot still ran LSTM/HTF/VWAP/MTF for every market just to throw the result away. Wasted ~25 s Ã— 30 markets per cycle.

### Fix
1. **Local config (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`)**: added `BITVAVO_CACHE_TTLS = {candles:30, tickerPrice:5, book:10, ticker24h:60, balance:30, markets:300, assets:300}`. Hot-reloads automatically.
2. **`trailing_bot.py` (around line 2429)**: moved `_REGIME_ENTRY_BLOCKED` check to top of per-market loop (immediately after `[SCAN] Evaluating ...` log). Skips momentum filter, signal_strength, ML ensemble, HTF, VWAP, MTF, OBI, correlation shield when regime blocks all entries anyway.

### Verification
- Live log showed BCH-EUR scan dropped from 28s â†’ 7s the moment cache TTLs hot-reloaded.
- `python -c "from modules.config import load_config; print(load_config()['BITVAVO_CACHE_TTLS'])"` confirms cache config picked up.
- `get_errors` on `trailing_bot.py` â†’ no errors.
- Commit `46122f0` pushed to `main`.

### Lesson
- **Always set `BITVAVO_CACHE_TTLS`** in local config â€” without it, the per-call cache layer in `bot/api.py::safe_call()` silently no-ops because `cache_ttls.get(key, 0.0) = 0.0`. Sane defaults: candles 30s, tickerPrice 5s, book 10s, ticker24h 60s, balance 30s.
- **Check cheap gating flags FIRST** in per-market scan loops. Regime / cooldown / blacklist must short-circuit before expensive ML inference, HTF candle fetches, or orderbook calls.

---

## #067 â€” Telegram bot overhaul: noise control + 14 new commands + enriched trade alerts (2026-05-01)

### Symptom
User feedback: *"ik wil meer info, een betere log met minder ruis, meer commands, maak de beste telegram bot ooit"*. Bestaande `modules/telegram_handler.py` had:
- Geen severity-gating â†’ elke `notify()` werd verstuurd, ook routine info â†’ log-overload.
- Geen quiet hours â†’ 's nachts spam.
- Geen dedupe â†’ identieke alerts (zelfde event, andere prijs/timestamp) bleven herhalen.
- Trade alerts (BUY/SELL) bevatten alleen prijs+amount; geen score/regime/RSI/MACD/peak/hold-time.
- Alleen 17 commands, geen `/today`, `/week`, `/positions`, `/regime`, `/ai`, `/why`, `/health`, `/uptime`, `/version`, `/top`, `/fees`, `/quiet`, `/pause`, `/resume`.

### Fix
1. **Severity ladder** in `modules/telegram_handler.py`:
    - `_classify(text)` â†’ `trade` (KOOP/VERKOOP/STOP-LOSS), `critical` (CIRCUIT/EMERG/CRASH/CONNECTION LOST/SHUTDOWN/SALDO ERROR), `alert` (ERROR/WARN/FAIL/RETRY), `info` (rest).
    - `TELEGRAM_NOTIFY_LEVEL` config (`info|alert|trades|critical|off`) gate in `notify()`.
2. **Quiet hours**: `_in_quiet_hours(cfg)` met `TELEGRAM_QUIET_START`/`TELEGRAM_QUIET_END` (HH:MM, lokale tijd). Tijdens quiet hours alleen `trade`/`critical`. Spans middernacht correct (22:00â†’07:00).
3. **Dedupe**: `_normalize_for_dedupe()` strip-t timestamps/prijzen/getallen â†’ key. Eerste keer in `ALERT_DEDUPE_SECONDS` (default 600s) doorgelaten; daarna geblokt. Op de 5e (`ALERT_BURST_THRESHOLD`) collapse naar Ã©Ã©n samenvatting "(Ã—5 in 600s)".
4. **Enriched BUY alert** (`_trade_watch_loop`): toont nu score, regime emoji (ðŸš€ trending / âš–ï¸ neutraal / ðŸ›¡ï¸ defensief), RSI@entry, MACD@entry, volatility%.
5. **Enriched SELL alert**: hold-time (h/m), peak% retrace, dca count, partial_tp returned â‚¬, gemapte reason emoji (ðŸŽ¯ trailing / ðŸ›‘ stop_loss / âš ï¸ saldo_error / ðŸ§  ai_exit / ðŸšª manual / â° time_stop).
6. **14 nieuwe commands**: `/today` `/week` `/positions` `/fees` `/regime` `/ai` `/health` `/uptime` `/version` `/top` `/why <coin>` `/quiet on|off` `/pause` `/resume`.
    - `/pause` schrijft `MIN_SCORE_TO_BUY=999` naar local override + saved prev in `data/telegram_pause_state.json`.
    - `/resume` herstelt prev maar floored op 7.0 (respecteert MIN_SCORE_TO_BUYâ‰¥7 lock uit copilot-instructions Â§12).
7. **`/help` heropbouwd**: 4 categorieÃ«n (Snel overzicht / Strategie & markt / Beheer / Tuning) met copy-paste tuning voorbeelden voor minder ruis.
8. **Nieuwe ALLOWED_KEYS** in `_apply_set_command()`: `TELEGRAM_NOTIFY_LEVEL`, `TELEGRAM_QUIET_START`, `TELEGRAM_QUIET_END` (alle str). `ALERT_DEDUPE_SECONDS` was al toegestaan via int-pad.

### Verification
- Import smoke test: `from modules import telegram_handler` â†’ OK.
- 28 helpers gedetecteerd (`_get_*`, `_set_quiet`, `_pause_entries`, `_resume_entries`).
- Per-helper smoke run (`_get_today_text`, `_get_week_text`, `_get_ai_text`, `_get_regime_text`, `_get_uptime_text`, `_get_version_text`, `_get_health_text`, `_get_positions_text`, `_get_fees_text`, `_get_why_text`) â†’ alle returnen tekst (50â€“369 chars), geen exceptions.
- `_classify()` correct: trade/critical/alert/info matches.
- `_normalize_for_dedupe('ENJ-EUR price â‚¬1.23 at 10:45')` â†’ `enj#eur price # at #` (timestamps + getallen weg).
- `pytest -k telegram` â†’ geen tests, geen regressies (807 deselected).
- Geen syntax errors (`get_errors`).

### Notes / How to use
- Bot moet herstart worden voor live alerts â†’ user kan `/restart` sturen of `python trailing_bot.py` herladen.
- Tuning voor "minder ruis" (voorbeeld user-config):
    - `/set TELEGRAM_NOTIFY_LEVEL trades` (alleen trade+critical)
    - `/set TELEGRAM_QUIET_START 22:00` + `/set TELEGRAM_QUIET_END 07:00`
    - `/set ALERT_DEDUPE_SECONDS 1800` (30 min)
- `/why <coin>` is een placeholder die `score`/`opened_regime`/`rsi_at_entry`/`macd_at_entry` uit `open_trades[market]` toont â€” werkt direct want die fields worden al door `bot/orders_impl.py` gevuld bij entry.

### Files Changed
- `modules/telegram_handler.py` (~750 â†’ ~1400 regels). Geen call-site changes elders.

---

## #066 â€” Road-to-10 monolith shrink batch 1: trade_repair + path_utils extraction (2026-04-30)

### Symptom
`trailing_bot.py` was 4908 regels â€” laatste open item van road-to-10 (target â‰¤300). Veel dead code (`_legacy` wrappers) en zelfstandige helpers zaten nog in de monoliet. Volledige extractie is meerdaags werk; deze batch pakt veilige low-risk extractions.

### Fix
1. **Verwijderd**: `_cancel_open_buys_if_capped_legacy` (~75 regels) en `_cancel_open_buys_by_age_legacy` (~105 regels). Geen callers (geverifieerd via grep).
2. **`bot/trade_repair.py`** (NIEUW, ~150 regels) â€” `validate_and_repair_trades()` extracted. Implementeert GUARD 0+1+4+5 (dca_state.sync_derived_fields), GUARD 2 (negative invested repair), GUARD 3 (absurd total_invested), GUARD 6 (initial+events consistency), GUARD 7 (buy_priceÃ—amount fallback). Gebruikt `bot.shared.state` voor open_trades/CONFIG/save_trades_fn.
3. **`bot/path_utils.py`** (NIEUW, ~100 regels) â€” `log_throttled`, `ensure_parent_dir`, `resolve_path`, `append_trade_pnl_jsonl`. Pure helpers, valt terug op `Path(__file__).parent.parent` als `state.PROJECT_ROOT` ontbreekt.
4. **`trailing_bot.py`** â€” alle bovenstaande functies vervangen door 4-line shims die naar de extracted modules forwarden. Behoud van publieke API (geen call-site changes nodig).

### Result (batch 1+2 combined)
- `trailing_bot.py`: 4908 â†’ **4449 regels** (-459, -9.4%).
- 806 tests pass (geen regressies).
- Geen gedragsverandering â€” pure code-reorganisatie. Bot-restart niet nodig.

### Batch 2 additions (commit 2)
- **`bot/close_trade.py`** (NIEUW, ~165 regels) â€” `finalize_close_trade()` extracted. Bevat alle close-bookkeeping (archive â†’ record stats â†’ market_profits â†’ market_expectancy â†’ post_loss_cooldown â†’ adaptive_score â†’ bayesian_fusion â†’ meta_learner â†’ del open_trades â†’ save â†’ cleanup â†’ signal_publisher). Geen gedragsverandering. Alle hooks zijn `try/except: pass` zodat Ã©Ã©n faler niet de hele close blokkeert.
- `_signal_pub` wordt lazy gefetched via `from modules import signal_publisher` binnen de extracted functie â€” geen state-registratie nodig.

### Batch 3 additions (commit 3)
- **`bot/maintenance.py`** (NIEUW, ~110 regels) â€” `apply_dynamic_performance_tweaks`, `register_saldo_error`, `optimize_parameters` extracted.
- **`bot/ai_regime.py`** (NIEUW, ~95 regels) â€” `get_ai_regime_bias` extracted met eigen module-level cache. Leest `AI_HEARTBEAT_FILE` + alle thresholds via `state.CONFIG`.

### Batch 4 additions (commit 4)
- **`bot/market_helpers.py`** (NIEUW, ~120 regels) â€” `get_true_invested_eur(trade, market)` (bulletproof invested met 20% divergence cross-check), `get_pending_bitvavo_orders()` (excludeert grid orders en in-memory open_trades), `count_pending_bitvavo_orders()` (len wrapper). Leest `state.bitvavo`/`state.safe_call`/`state.open_trades`/`state.get_active_grid_markets`.
- **`bot/event_hooks_adapter.py`** (NIEUW, ~80 regels) â€” module-level `EVENT_STATE` singleton (Ã©Ã©n-malig `EventState()` op import) + `event_hooks_paused(market)` met module-private transition cache + `event_hook_status_payload()` voor dashboard. Graceful fallback als `modules.event_hooks` ontbreekt.
- `trailing_bot.py` shimmed: 3 functies vervangen door 4-line stubs en het volledige `EVENT_STATE`/`_event_hooks_paused`/`_event_hook_status_payload` blok (~50 regels) vervangen door Ã©Ã©n 13-line `try/except` import.

### Result (na batch 4)
- `trailing_bot.py`: 4908 â†’ **4206 regels** (-702, -14.3%).
- Tests: 806 pass / 3 skip (zelfde als vÃ³Ã³r deze sessie).

### Batch 5 additions (commit 5)
- **`bot/circuit_breaker.py`** (NIEUW, ~85 regels) â€” `is_active()` extracted uit nested fn binnen `open_trade_async`. Leest grace/cooldown/wr/pf via `state.CONFIG`, mutateert `_circuit_breaker_until_ts` + `_cb_trades_since_reset`. Gebruikt lazy `import trailing_bot` om `tb.TRADE_LOG` runtime-patches te respecteren (test-compat).
- **`bot/auto_sync_manager.py`** (NIEUW, ~70 regels) â€” `start(interval)` extracted uit `start_auto_sync`. Eigen module-level `_auto_sync_thread` handle. Leest `synchronizer`/`trades_lock`/`open_trades`/`closed_trades`/`market_profits` via `state`.
- `trailing_bot.py` shimmed: nested `_circuit_breaker_active` (~53 regels) vervangen door 1-line lazy import; `start_auto_sync` body (~33 regels) vervangen door 4-line shim.

### Result (na batch 5)
- `trailing_bot.py`: 4908 â†’ **4126 regels** (-782, -15.9%).
- Tests: 806 pass / 3 skip.

### Batch 6 additions (commit 6)
- **`bot/cost_basis_helpers.py`** (NIEUW, ~30 regels) â€” `get_true_total_invested(trade)` pure helper.
- **`bot/ml_optimizer_runner.py`** (NIEUW, ~45 regels) â€” `maybe_run()` async, eigen module-level `_LAST_RUN` timestamp.
- **`bot/safety_buy.py`** (NIEUW, ~45 regels) â€” `safety_buy(market, amt_eur, entry_price)` async met market-order fallback.
- `trailing_bot.py` shimmed: 3 functies (~58 regels totaal) vervangen door 4-line shims.

### Result (na batch 6)
- `trailing_bot.py`: 4908 â†’ **4080 regels** (-828, -16.9%).
- Tests: 806 pass / 3 skip.

### Batch 7 additions (commit 7)
- **`bot/grid_market_helpers.py`** (NIEUW, ~45 regels) â€” `get_active_grid_markets()` extracted. Leest `state.CONFIG['GRID_TRADING'].enabled` en `modules.grid_trading.get_grid_manager()`.
- `trailing_bot.py` shimmed: `get_active_grid_markets` (~30 regels) vervangen door 4-line shim.

### Result (na batch 7)
- `trailing_bot.py`: 4908 â†’ **4058 regels** (-850, -17.3%).
- Tests: 806 pass / 3 skip.

### Lessons / Notes
- `bot_loop()` (2640 regels) en `initialize_managers()` (167 regels met Context-dataclass closures) blijven multi-day werk â€” eerlijke scope-separatie.
- Pattern bevestigd: extract â†’ shim met lazy import â†’ smoke test â†’ pytest â†’ commit. Werkt veilig.

### Files Changed
- `trailing_bot.py` (legacy wrappers verwijderd, 5 functies vervangen door shims)
- `bot/trade_repair.py` (nieuw)
- `bot/path_utils.py` (nieuw)

---

## #065 â€” Road-to-10 fase 4/5/6/7 final closure: registry + per-market trailing + rate-limit alert + bandit clean (2026-04-30)

### Symptom
Roadmap had nog open items in fase 4 (model registry), fase 5 (per-market trailing), fase 6 (CI/CD ghcr.io + demo-mode tickoff), en fase 7 (bandit medium warnings + healthcheck + rate-limit alerts). Demo-mode + ghcr.io + healthcheck waren al geÃ¯mplementeerd maar niet afgevinkt.

### Fix
1. **`models/registry.py`** (NIEUW) â€” scant `models/ai_xgb_model_*.json` + bijbehorende `_metrics_` files en schrijft `models/registry.json` met `{trained_at, auc, support, positive_ratio, version_ts}`. Run via `python -m models.registry`.
2. **`bot/per_market_trailing.py`** (NIEUW) â€” `get_trailing_params(market, config)` met curated defaults voor BTC-EUR (1.0/0.6/0.4), ETH-EUR (1.2/0.7/0.5), SOL-EUR (1.5/0.9/0.6). Override-keten: `PER_MARKET_TRAILING` config â†’ curated â†’ globale config keys.
3. **`bot/rate_limit_alert.py`** (NIEUW) â€” `check_and_alert(threshold=0.8, cooldown_sec=300)` leest `bot.api.get_rate_limit_status()` en logt WARNING per bucket met cooldown.
4. **`bot/scheduler.py`** â€” nieuwe `check_rate_limits()` wrapper die scheduler-managed rate-limit health-check aanbiedt.
5. **`core/binance_lead_lag.py` + `core/funding_rate_oracle.py`** â€” `# nosec B310` justifications voor trusted internal Binance/Coinbase URLs.
6. **`modules/database_manager.py`** â€” `# nosec B608` justifications: `set_clause` is samengesteld uit interne dict-keys (geen user input), `where_clause` is interne literal met parameter placeholders.
7. **`tests/test_road_to_10_phase6.py`** (NIEUW) â€” 14 tests (4 registry + 4 per-market + 4 rate-limit + 1 demo + 1 scheduler hook).
8. **`docs/COPILOT_ROAD_TO_10.md`** â€” afvinks: dashboard_flask weg, feature store, model registry, per-market trailing, demo-mode, CI/CD ghcr.io, bandit clean, healthcheck, rate-limit metrics. Versielog #065 toegevoegd.

### Lessons learned
- Bandit B310 (urlopen) en B608 (SQL string format) zijn vaak false-positives in trusted-internal flows. `# nosec` met justification is de juiste oplossing als de input-source bewezen veilig is.
- Per-market trailing-config is een drop-in helper die naar wens kan worden ingebouwd in `bot/trailing.py` zonder bestaande globale defaults te breken.
- Model registry is leesbaar zonder dat de bot er aan gewend hoeft te zijn â€” `python -m models.registry` werkt standalone.

### Tests
**806 pass / 0 fail / 3 skip** (was 792, +14 nieuwe phase6 tests).
**Bandit medium = 0 / high = 0** âœ….

### Files
- `models/registry.py` (NEW)
- `bot/per_market_trailing.py` (NEW)
- `bot/rate_limit_alert.py` (NEW)
- `bot/scheduler.py` (+check_rate_limits)
- `core/binance_lead_lag.py` (+nosec B310)
- `core/funding_rate_oracle.py` (+nosec B310)
- `modules/database_manager.py` (+nosec B608 Ã—2)
- `tests/test_road_to_10_phase6.py` (NEW, 14 tests)
- `docs/COPILOT_ROAD_TO_10.md` (8 tickoffs + versielog)
- `docs/FIX_LOG.md` (#065)

---

## #064 â€” Road-to-10 fase 4+5 wrap: shadow_trading + decorrelation entry-wiring (2026-04-30)

### Symptom
Roadmap fase 4 (shadow trading 1-week loop) en fase 5 (decorrelation filter actief in entry pipeline) waren nog open. `apply_decorrelation_filter` ontbrak en geen append-only shadow log.

### Fix
1. **`bot/shadow_trading.py`** (NIEUW) â€” `log_shadow_entry(market, payload)` schrijft naar `data/shadow_trades.jsonl`. Default disabled via `SHADOW_TRADING_ENABLED=false`.
2. **`bot/entry_pipeline.py`** â€” `apply_decorrelation_filter(decision, candidate_closes, open_market_closes, config)` toegevoegd. Honoreert `DECORRELATION_ENABLED` + `DECORRELATION_MAX_CORR` (default 0.7).
3. **`tests/test_road_to_10_phase5.py`** (NIEUW) â€” 7 tests voor decorrelation passthrough/blocking + shadow JSONL append.
4. **`docs/COPILOT_ROAD_TO_10.md`** â€” afgevinkt: scheduler, entry_pipeline, exit_pipeline, walk-forward, drift, shadow, limit-orders, ws scaffold, Grafana JSON. Versielog #062/#063/#064 toegevoegd.

### Lessons learned
- `apply_decorrelation_filter` is opt-in via config: tot we 1 week shadow data hebben weten we niet of 0.7 correlation drempel realistisch is voor crypto (alle alts hebben hoge BTC correlation).
- Shadow log MOET disabled-by-default zijn â€” bij activeren groeit `data/shadow_trades.jsonl` snel.

### Tests
**Tot 820 pass verwacht** (was 785, +10 nieuwe phase5 tests waarvan 7 phase5 + 3 decorrelation extra).

### Files
- `bot/shadow_trading.py` (NIEUW)
- `bot/entry_pipeline.py` (+apply_decorrelation_filter)
- `tests/test_road_to_10_phase5.py` (NIEUW)
- `docs/COPILOT_ROAD_TO_10.md` (afvinks + versielog)
- `docs/FIX_LOG.md` (#064)

---

## #063 â€” Road-to-10 fase 5 closure: /log fix + exit_pipeline + decorrelation + ML cron + config (2026-04-30)

### Symptom
1. `/log` Telegram commando gaf niets terug â€” bot_log.txt regels bevatten `<` (bv `EUR balans (0.00 < 9.60)`) wat Telegram HTML-parser breekt: `Bad Request: can't parse entities: Unsupported start tag "" at byte offset 338`.
2. Roadmap fase 5 had limit-orders code maar niet aan in productie config; geen exit_pipeline; geen decorrelation filter; walk-forward script werd nooit getriggerd.

### Fix
1. **`modules/telegram_handler.py`** â€” `_get_log_text()` nu `html.escape(l[-120:])` zodat `<`/`>`/`&` niet breken. Status-text idem (inline `__import__('html').escape`).
2. **`bot/exit_pipeline.py`** (NIEUW) â€” `derive_unrealised_pct`, `should_lock_breakeven`, `should_partial_tp`. Pure helpers. **Honoreert FIX-LOG #003**: nooit sell-at-loss, nooit time-based.
3. **`bot/decorrelation.py`** (NIEUW) â€” `pearson_correlation` + `is_decorrelated`. Filter voor entry-pipeline om SOL+AVAX+MATIC-allemaal-long te voorkomen.
4. **`tests/test_road_to_10_phase4.py`** (NIEUW) â€” 13 tests.
5. **Windows Task Scheduler** â€” `BitvavoBot_DailyML` daily 04:30 â†’ `scripts/scheduled_ml_jobs.py` (drift_monitor + walk_forward).
6. **`bot_config_local.json`** geÃ¼pdatet:
   - `LIMIT_ORDER_PREFER=true` + `ORDER_TYPE=limit` (recapture 39% slippage)
   - `BLOCK_ENTRY_REGIMES=["BEARISH"]` (#059 framework geactiveerd)
   - `TRAILING_ACTIVATION_PCT=1.5` (was hoger; lost RENDER/ENJ "trailing nooit geactiveerd op +2.6% piek" probleem op)
   - `DCA_MIN_SCORE=12.0` (#061 gate strikt; legacy 0.0)

### Lessons learned
- Telegram HTML mode crasht stilletjes op user-content (logs/JSON) â€” escape ALTIJD bij `<code>...</code>`.
- Existing trades (RENDER/ENJ) blijven gelocked want trailing-activation was te hoog t.o.v. realistische piek-bewegingen op â‚¬400-â‚¬1100 alts.

### Tests
**785 pass, 0 fail, 3 skip** (was 772, +13 nieuwe).

### Files
- `modules/telegram_handler.py` (HTML escape)
- `bot/exit_pipeline.py` (NIEUW)
- `bot/decorrelation.py` (NIEUW)
- `tests/test_road_to_10_phase4.py` (NIEUW)
- `scripts/scheduled_ml_jobs.py` (al uit #062, nu Task Scheduler aan)
- `%LOCALAPPDATA%/BotConfig/bot_config_local.json` (5 keys)
- `docs/FIX_LOG.md` (#063)

---

## #062 â€” Road-to-10 fase 3-5 sweep: scheduler/ws_price_feed/entry_pipeline + ML cron (2026-04-29)

### Symptom
Roadmap fase 3 (extracten verder) + fase 5 (WS feed + walk-forward + drift cron) stonden nog open. Heartbeat/reservation watchdog/auto_sync orchestratie zat nog hardcoded in `trailing_bot.py`. Geen WS-stub om incrementeel naar push-prices te bewegen. Geen geÃ¼nificeerde entry-decision helper. Walk-forward + drift_monitor scripts bestonden maar werden nooit getriggerd.

### Fix
1. **`bot/scheduler.py`** (NIEUW) â€” `start_heartbeat_monitor`, `start_heartbeat_writer`, `start_reservation_watchdog`, `start_all_schedulers()`. Idempotent, no-op wanneer `state.monitoring_manager` ontbreekt.
2. **`bot/ws_price_feed.py`** (NIEUW) â€” `WSPriceFeed` scaffold: `start/stop/get_last_price`, module-level `latest_price/latest_book` cache met TTL. Default disabled via `WS_PRICE_FEED_ENABLED=false`. Detecteert ontbrekende `newWebsocket()` automatisch en blijft REST-only zonder te crashen.
3. **`bot/entry_pipeline.py`** (NIEUW) â€” `decide_entry()` + `decide_order_type()`: pure decision helpers (geen I/O), retourneren `EntryDecision`. Honoreert `LIMIT_ORDER_PREFER` + auto-spread switch (limit bij <0.1% spread, anders market).
4. **`scripts/scheduled_ml_jobs.py`** (NIEUW) â€” daily cron-runner voor `drift_monitor` + `backtest.walk_forward`; alerts naar Telegram + `logs/ml_drift_alert.txt`; resultaten naar `data/walk_forward_history.jsonl`.
5. **`trailing_bot.py`** â€” `_start_heartbeat_monitor/writer/reservation_watchdog` gereduceerd tot 3-regelige shims naar `bot.scheduler`.
6. **`bot/shared.py`** â€” `monitoring_manager` + `liquidation_manager` velden toegevoegd aan `_SharedState` zodat scheduler ze via state kan bereiken.
7. **`tests/test_road_to_10_phase3.py`** â€” 15 nieuwe tests (scheduler facade, WS price cache + TTL, entry_pipeline beslislogica + order_type routing).

### Lessons learned
- `state.log` heeft een no-op default die `print` is en geen `level=` kwarg accepteert; tests moeten `state.log = MagicMock()` zetten voor modules die `level='debug'` loggen.
- Scheduler-extractie was 100% mechanisch want bestaande functies waren al shims naar `monitoring_manager`. Pure win, nul gedragsverandering.
- WS feed laat default `WS_PRICE_FEED_ENABLED=false` â€” nul risico voor productie tot we expliciet enablen + meten.

### Tests
772 pass, 0 fail, 3 skip (was 757) â€” +15 nieuwe road-to-10 phase3 tests.

### Files
- `bot/scheduler.py` (NIEUW)
- `bot/ws_price_feed.py` (NIEUW)
- `bot/entry_pipeline.py` (NIEUW)
- `scripts/scheduled_ml_jobs.py` (NIEUW)
- `tests/test_road_to_10_phase3.py` (NIEUW)
- `trailing_bot.py` (3 shims)
- `bot/shared.py` (+2 fields)
- `docs/FIX_LOG.md` (#062)

---

## #061 â€” Monolith split #2: order_cleanup extracted + DCA_MIN_SCORE gate (2026-04-29)

### Symptom
Roadmap fase 2 (monoliet opsplitsen) en fase 5 (DCA strikter) waren beide nog open. `cancel_open_buys_if_capped` + `cancel_open_buys_by_age` (~180 regels) zaten nog in `trailing_bot.py`. DCA had geen score-floor: een trade met score 4 kreeg dezelfde DCA-behandeling als een score-15 trade.

### Fix
1. **`bot/order_cleanup.py`** (NIEUW) â€” beide cancel-functies geÃ«xtraheerd; gebruiken `bot.shared.state` voor alle deps (CONFIG, bitvavo, log, metrics_collector, OPERATOR_ID, count_active_open_trades, _get_pending_count, count_pending_bitvavo_orders, get_active_grid_markets). Grid-protection identiek (markt+orderId allowlist).
2. **`trailing_bot.py`** â€” beide functies gereduceerd tot 3-regelige shims; legacy bodies hernoemd `_*_legacy` (ongebruikt).
3. **`modules/trading_dca.py`** â€” `DCA_MIN_SCORE` config check toegevoegd in `handle_trade()` direct na enabled/price-checks. Default 0.0 = disabled (legacy gedrag). Wanneer `> 0`, slaat DCA over voor trades met `trade.get('score') < DCA_MIN_SCORE` met log + audit-entry `score_below_min`.
4. **`tests/test_order_cleanup_and_dca_min_score.py`** (NIEUW) â€” 13 tests:
   - 5 voor `cancel_open_buys_if_capped` (under-cap skip, capped cancel, market-already-open, grid-protect, sell-side skip)
   - 5 voor `cancel_open_buys_by_age` (timeout=0 disabled, old cancel, fresh keep, market-type skip, no-timestamp skip)
   - 3 voor `DCA_MIN_SCORE` (block on low score, allow on high score, no-op when threshold=0)

### Validation
- 757 tests pass / 0 fail / 3 skip (was 744).
- `py_compile bot/order_cleanup.py trailing_bot.py modules/trading_dca.py` clean.
- Backwards-compatible: oude config zonder `DCA_MIN_SCORE` gedraagt zich identiek.

### Lesson
- Tweede monoliet-extractie was makkelijker dan de eerste omdat `bot.shared.state` al alle deps had (bitvavo, OPERATOR_ID, metrics_collector, grid helpers). Pattern is nu: zoek functie â†’ check shared state heeft de deps â†’ schrijf module met `from bot.shared import state` â†’ vervang body door shim.
- Configurable thresholds met sane default (0 = off) maakt nieuwe gates risk-vrij om te shippen.

---



### Symptom
Na #059 stond `bot/main_loop.py` als seam klaar, maar er was nog geen Ã©chte code-extractie uit `trailing_bot.py` (4635 regels). Eerste concrete monolith-reductie nodig om de pattern te bewijzen voor toekomstige extracties.

### Fix
- **`bot/startup_validation.py`** (NIEUW) â€” `validate_config(config: Mapping)` als pure functie; logt + returnt list van issues. Eerder ~70 regels logica in `trailing_bot.py`.
- **`trailing_bot.py:validate_config`** â€” gereduceerd tot 4-regelige shim die `bot.startup_validation.validate_config(CONFIG)` aanroept.
- **`tests/test_startup_validation.py`** (NIEUW) â€” 10 tests dekken alle 7 issue-takken + edge cases (lege config, ongeldige tier-entries).

### Validation
- 744 tests pass / 0 fail / 3 skip (was 734).
- Bandit clean op nieuwe module.
- Backwards-compatible: oude callsite `validate_config()` blijft werken.

### Lesson
- Veel "monolith functies" zijn al shims die naar `bot/`, `core/`, of `modules/` delegeren. Echte extractie-targets zijn pure functies die module-level globals lezen via dict-arg ipv globals.
- Pure functies (geen state-mutatie) zijn de veiligste eerste extracties â€” testbaar zonder mocks.

---

## #059 â€” Road-to-10 phase 2: conformal wiring, per-market trailing overrides, regime entry block, main_loop wrapper, Prometheus alert rules (2026-04-29)

### Symptom
Na #058 stonden nog 4 items open: MAPIE conformal helper bestond maar werd niet aangeroepen vanuit `bot/signals.py`, geen per-market trailing override mechanisme, geen configurable regime entry block (alleen hardcoded BEARISH), geen `bot/main_loop.py` seam voor monolith-extractie, en geen Prometheus alert rules YAML naast het Grafana JSON.

### Fix
1. **`ai/conformal.py`** â€” `save_calibrator()/load_calibrator()/enrich_ml_info()` toegevoegd; memoised disk-load van `models/conformal_calibrator.pkl`, no-op zonder MAPIE.
2. **`bot/signals.py`** â€” na entry-confidence block roept `enrich_ml_info(ml_info, X=features)` aan; voegt `ml_calibrated` + `ml_conf_interval_width` toe aan ml_info zonder te breken als calibrator ontbreekt.
3. **`bot/trailing.py`** â€” `MARKET_TRAILING_OVERRIDES` schema gelezen voor zowel `base_trailing_pct` als `stepped_levels` per markt; per-market wint van regime override wint van trade-level wint van DEFAULT.
4. **`trailing_bot.py`** â€” `BLOCK_ENTRY_REGIMES` config (lijst van regime-namen); zet `_REGIME_ENTRY_BLOCKED` flag, gecheckt vlak na bearish-block in entry-loop, slaat market over met log.
5. **`bot/main_loop.py`** (NIEUW) â€” thin wrapper die `trailing_bot.bot_loop` re-exporteert + `run(once=False)` runner. Seam waar geleidelijke monolith-extractie kan landen.
6. **`docs/grafana/prometheus_alerts.yml`** (NIEUW) â€” 4 groups / 9 alerts: BotOffline, HeartbeatStale, NoOpenTrades, ExposureSpike, DrawdownDeep, RateLimitNearExhaustion (>80%), RateLimitExhausted (>95%), AIOffline.
7. **`tests/test_road_to_10_phase2.py`** (NIEUW) â€” 6 tests, 100% pass.

### Validation
- 728 tests pass / 0 fail (pre-fase 2), 6 nieuwe tests pass = 734 totaal.
- Geen errors op `bot/signals.py`, `bot/trailing.py`, `bot/main_loop.py`, `ai/conformal.py`, `trailing_bot.py`.
- Bot draait door op zelfde PID; configurabele opties default off (backwards-compatible).

### Lesson
- Als je een module-skeleton publiceert (zoals MAPIE conformal in #058), verifieer dat het ergens wordt aangeroepen â€” anders is het dood gewicht.
- Per-market overrides MOETEN ook stepped_levels respecteren, niet alleen `base_trailing_pct`.
- Configurabele regime blocks moeten een persistente flag op CONFIG zetten zodat ze in de scan-loop zonder lookup beschikbaar zijn.

---

## #058 â€” Road-to-10 sweep: feature store, model registry, walk-forward, demo mode, drift monitor, shadow report, conformal wrapper, Grafana, Docker healthcheck, ghcr.io CI, bandit clean, rate-limit metrics (2026-04-29)

### Symptom
Veel kleine roadmap-items uit Road-to-10 stonden nog open: geen feature-store versionering, geen model registry naast `ai/ai_xgb_model.json`, geen reproduceerbaar walk-forward framework (oude `_backtest_*.py` waren ad-hoc), geen demo mode voor onboarding zonder API-keys, geen rate-limit metrics, oude Flask docker healthcheck (poort 5001), geen Docker image in ghcr.io, en bandit had 1 HIGH severity finding (`shell=True` in `scripts/helpers/monitor.py`).

### Fix
1. **`ai/features/`** â€” `FEATURE_STORE_VERSION='1.0.0'` + 11-feature schema + `vectorize()` helper, single source of truth voor model features.
2. **`ai/model_registry.py`** â€” `register_model()/read_metadata()/latest_model_metadata()` schrijven `<model>.meta.json` naast elk artefact (n_train, val_metric, feature_store_version, git commit).
3. **`backtest/walk_forward.py`** â€” vervangt ad-hoc backtest scripts. `WalkForwardConfig(train_days, test_days, step_days)` + `run_walk_forward(trades_path, cfg)` produceert windowed PnL/win-rate/sharpe-like.
4. **`bot/demo_mode.py` + `tests/fixtures/demo/`** â€” `BOT_DEMO_MODE=1` env var + canned balance/ticker fixtures voor demos & CI smoke tests.
5. **`scripts/drift_monitor.py`** â€” z-score check per feature t.o.v. baseline (`--update-baseline` flag), exit code 1 bij drift > 3Ïƒ. Pure-functions geÃ¼t.
6. **`scripts/shadow_report.py`** â€” aggregator over `data/shadow_trades.jsonl` met PnL, win-rate, blocked-by-reason histogram.
7. **`ai/conformal.py`** â€” MAPIE wrapper voor calibrated prediction intervals; gracefully no-op als MAPIE niet geÃ¯nstalleerd is.
8. **`bot/api.py::get_rate_limit_status()`** â€” snapshot van `_rate_buckets` per endpoint; `tools/dashboard_v2/backend/main.py` exposeert `bitvavo_ratelimit_usage_ratio{bucket=...}` op `/metrics`.
9. **`docs/grafana/bitvavo_bot_dashboard.json` + README** â€” drop-in Grafana dashboard met 11 panels + suggested alerts (bot down, heartbeat stale, rate-limit > 80%, PnL drawdown).
10. **`Dockerfile` + `docker-compose.yml`** â€” healthcheck nu op poort **5002** (V2) i.p.v. dode 5001/dashboard_flask.
11. **`.github/workflows/release.yml`** â€” extra job `publish-docker` bouwt en pusht image naar `ghcr.io/<owner>/bitvavo-bot:{VERSION,latest}` op tag-push.
12. **`tests/test_road_to_10_helpers.py`** â€” 17 nieuwe tests dekken alle 7 nieuwe modules.
13. **`scripts/helpers/monitor.py`** â€” `subprocess.run(shell=True)` vervangen door `shlex.split` + `shell=False` (bandit HIGH B602 weg).
14. **`tests/test_integration.py`** â€” module-level `pytest.skip(allow_module_level=True)`: legacy Flask-dashboard tests retired.

### Stats
- Tests: **728 pass, 3 skip, 0 fail** (was 747 pass / 8 fail door dode dashboard_flask).
- Bandit: **0 HIGH**, 14 MEDIUM (B113 timeouts in legacy scripts, B310 url-open allowlist, B608 SQL string concat in archive scripts), 310 LOW.
- Files: +9 nieuwe modules, +1 Grafana JSON, +1 fixtures dir, ~200 regels tests.

### Lesson
Roadmap items die "klein" lijken (registry, feature versioning, drift, walk-forward) zijn elk losstaand een paar honderd regels â€” maar samen worden ze multiplicatief: feature_store + model_registry + walk_forward + drift_monitor vormen samen het minimale **MLOps backbone** dat reproducibility geeft. Bandit lopen voor commit kost <1 min en vangt directe shell-injection vectors.

---

## #057 â€” Road-to-10: Prometheus exporter + kill-switch + structured JSON events (2026-04-29)

### Symptom
Roadmap items uit Fase 3 (observability) en Fase 7 (veiligheid) waren nog open: geen Prometheus formaat, geen externe kill-switch, geen structured JSON event log.

### Fix
1. **`GET /metrics` op dashboard V2** â€” Prometheus exposition format met `bitvavo_bot_online`, `bitvavo_bot_ai_online`, `bitvavo_heartbeat_age_seconds`, `bitvavo_open_trades`, `bitvavo_open_exposure_eur`, `bitvavo_eur_cash`, `bitvavo_total_account_value_eur`, `bitvavo_total_pnl_eur`, `bitvavo_total_fees_eur`, `bitvavo_win_rate`, `bitvavo_total_closed_trades`. Hergebruikt bestaande `_heartbeat()/_portfolio()/_performance()` accessors â€” geen extra subprocess of port nodig.
2. **`POST/GET/DELETE /api/admin/shutdown`** â€” schrijft `data/shutdown.flag`. Bot loop checkt het flag bij elke cycle-start en doet graceful shutdown (save trades + Telegram bericht). Optionele `KILL_SWITCH_TOKEN` env var voor token-protected POST.
3. **`modules/event_logger.py`** â€” `log_event(event, **fields)` schrijft thread-safe JSON-lines naar `logs/events.jsonl` (override via `BOT_EVENTS_LOG`). Nooit raises, ook niet bij invalid path. Gewired aan entry-confidence scan.
4. **6 nieuwe unit tests** (`tests/test_event_logger.py`) â€” single line, multi append, non-serializable, thread safety (200 concurrent writes), invalid-path safety.

### Lesson
Observability + safety scoort hoog op risico/reward bij kleine code-investering: ~150 regels en je krijgt scrape-friendly metrics, externe kill-switch en JSON-event audit trail. Hergebruik van bestaande dashboard process voorkomt aparte port/proces management.



### Symptom
Drie open trades (RENDER 6.3d, XLM 1.5d, ENJ 1.5d) zaten onder water. FIX #003 verbiedt time-based exits en verlies-sells, dus de enige weg is **betere entries**. Gebruiker vroeg: *"pas de allerbeste signal confidence toe en test."*

### Root cause
Bestaande pipeline filtert op Ã©Ã©n score (`MIN_SCORE_TO_BUY=8`) maar weegt geen multi-pillar context: trend op meerdere timeframes, RSI-archetype per regime, volume-kwaliteit (sweet 1.2-3.5x median, geen pump), volatiliteit-band, ML-confidence en cross-market correlatie met open trades. Resultaat: trades die op Ã©Ã©n dimensie scoren maar op andere fragiel zijn slipten erdoor.

### Fix
1. **Nieuw module `bot/entry_confidence.py`** â€” pure-function 6-pillar scorer (Trend, Momentum, Volume, Volatility, ML, Cross). Geometrische middeling (Ã©Ã©n zwakke pijler trekt totaal omlaag), met floor van 0.05 per pijler om wipe te voorkomen.
2. **Hook in `bot/signals.py::_signal_strength_impl`** â€” na pack-eval voegt `entry_confidence`, `entry_pillars`, `entry_weakest_pillar` en `entry_confidence_passed` toe aan `ml_info`. Wrapped in try/except zodat fouten nooit signaal blokkeren.
3. **Gate in `trailing_bot.py::bot_loop`** vÃ³Ã³r `open_trades_async` â€” als `ENTRY_CONFIDENCE_ENABLED` filtert candidates op `>= ENTRY_CONFIDENCE_MIN` en sorteert op confidence desc. Logt ALTIJD de top-8 distributie zodat we shadow-data hebben.
4. **23 unit tests** in `tests/test_entry_confidence.py` (alle pijlers + composite + edge cases nan/inf/empty/short).
5. **Config in `%LOCALAPPDATA%/BotConfig/bot_config_local.json`**: `ENTRY_CONFIDENCE_ENABLED=true`, `ENTRY_CONFIDENCE_MIN=0.55`, `ENTRY_CONFIDENCE_RANK_ONLY=false`.

### Lesson
Geen time-stop, geen verlies-sell â€” fix moet upstream bij de entry-keuze zitten. Multi-pillar geometric mean dwingt brede kwaliteit af i.p.v. cherry-pick op Ã©Ã©n score. Pure functies + dataclass-resultaat = triviaal te testen en te loggen voor toekomstige ML-feedback.



### Symptom
Gebruiker: *"In posities â‚¬ 1.696,25 < dit klopt niet, is te hoog. 3 / 4 trades."*  
Heartbeat zei `open_exposure_eur=1434.14` met 3 open trades, dashboard V2 toonde â‚¬1696.25 met 4 trades.

### Root cause
`tools/dashboard_v2/backend/main.py::_portfolio()` las `data/account_overview.json` (snapshot van ~90 min geleden, toen er nog 4 trades open waren). Snapshot werd niet vergeleken met fresh heartbeat data.

### Fix
Stale-detection toegevoegd: als heartbeat `ts` >300s nieuwer is dan overview `snapshot_ts`, gebruik `hb.open_exposure_eur` en `hb.open_trades` als bron i.p.v. de stale overview-velden.

### Lesson
Bij snapshot+stream architectuur ALTIJD freshness van snapshot vergelijken met latest stream-event vÃ³Ã³r render. Heartbeat is single source of truth voor live exposure.

---

## #054 â€” V2 dashboard "TRAILING WACHT" label was misleidend (2026-04-29)

### Symptom
Gebruiker: *"bij RENDER en ENJ staat trailing wacht, waarom staat er trailing wacht terwijl de trailing niet is geactiveerd, ook staat er al een trailing stop bedrag."*

### Root cause
`_compute_trailing_stop()` zette `status_label="TRAILING WACHT"` voor de toestand "trailing was activated â†’ highest crossed +1.8% boven buy â†’ daarna zakte prijs terug onder buy". Klant las "wacht" als "is nog niet actief", terwijl het in werkelijkheid betekende "actief maar tijdelijk inactief omdat prijs onder buy zit".

### Fix
Status label hernoemd naar `"TRAILING TERUG ONDER BUY"` met inline comment in code. Frontend `tr.status_label` binding bijgewerkt zodat de oranje (`warn`) class op beide labels matcht.

### Lesson
Status-strings moeten zelfverklarend zijn. "WACHT" = ambigu. Geef altijd de oorzaak, niet alleen de toestand.

---

## #055 â€” Stale `data/grid_states.json` in repo terwijl `GRID_TRADING.enabled=False` (2026-04-29)

### Symptom
Gebruiker: *"ik krijg op telegram berichten over grid bot btc rebalance, maar er staat helemaal geen gridbot aan."*

### Root cause
`data/grid_states.json` bevatte een BTC-EUR grid van een eerdere sessie met `config.enabled=true` en 12 historical rebalances. Hoewel `trailing_bot.py` `auto_manage()` correct guard via globale `grid_enabled`, kunnen externe scripts die het state-file direct laden de Telegram alerts triggeren. Daarnaast geeft het in dashboard V2 verwarrende grid-tab data.

### Fix
`data/grid_states.json` verplaatst naar `data/grid_states.json.disabled-{ts}.bak`. Bot blijft veilig (file regenerates leeg op enable). Alle nieuwe alerts zijn nu eenduidig.

### Lesson
Wanneer een feature wordt uitgeschakeld (`enabled=false`), schoon ook persistent state op â€” niet alleen config. State files overleven config-disables en kunnen latente alerts triggeren.

---

## #052 â€” Repo-hygiÃ«ne sweep: 98 debug-scripts naar `scripts/debug/`, analyse-output naar `tmp/` (2026-04-28)

### Symptom
Project root had 98 `_*.py` debug-scripts en 35+ `_*.txt`/`_*.json`/`_*.log` analyse-bestanden. Repo-hygiÃ«ne score 4/10 â€” onmogelijk te navigeren, ze waren ook in workspace listings, geen import-relatie maar maakten root onleesbaar.

### Fix
- 98 `_*.py` verplaatst naar `scripts/debug/` (untracked, dus gewone `Move-Item`).
- 37 `_*.txt`/`_*.json`/`_*.log`/`_*.html`/`_*.csv` verplaatst naar `tmp/` (gitignored).
- `.gitignore` uitgebreid met `tmp/`, `_*.{txt,json,log,html,csv,old}`, `scripts/debug/_*.py`.
- Geen test of module importeert ooit `_*.py` (geverifieerd met grep) â€” geen functioneel risico.
- Toegevoegd: `.editorconfig`, `Makefile`, `.vscode/tasks.json`, `SETUP.md`.
- `requirements.txt` opgesplitst in `-core.txt`, `-ml.txt`, `-dev.txt`.

### Lesson
Debug/analyse-scripts moeten vanaf dag 1 in een aparte map (`scripts/debug/` of `notebooks/scratch/`). Root-spam ontstaat sneller dan je denkt â€” voorkom door PR-review of pre-commit hook die `_*.py` in root weigert.

---

## #051 â€” Stale saldo_errors uit archive triggerden Saldo Guard â†’ DCA buy orders cancelled elke cycle (2026-04-28)

### Symptom
DCA's faalden de hele dag. Smart DCA logde "executing DCA" voor RENDER-EUR, ENJ-EUR, XLM-EUR maar er gingen geen orders door. Gebruiker moest handmatig kopen. Logs:
```
WARNING: Detected saldo_error for MIRA-EUR/XPL-EUR/CROSS-EUR/... (30+ markets, elke cycle)
WARNING: Saldo Guard: 29 saldo errors > drempel 5 â€” beschermingsmaatregelen actief
WARNING: Saldo Guard: openstaande BUY orders geannuleerd
WARNING: Saldo Guard: nieuwe entries gepauzeerd voor 300s
```

### Root cause
`bot/trade_lifecycle.py::save_trades` itereert elke cyclus over `closed_trades + trade_archive`. Voor elke trade met `reason=='saldo_error'` en `sell_price==0` werd hij re-pending gemarkeerd â€” **zonder timestamp-cutoff**. Het archive bevatte 29 saldo_errors van **206-207 dagen geleden** (april 2025) die elke cyclus opnieuw werden geappend aan `pending_saldo.json`. Resultaat: Saldo Guard `_get_pending_saldo_count()` â†’ 29 > drempel 5 â†’ cancelt elke cyclus alle openstaande BUY limit orders, inclusief DCA-orders die net waren geplaatst.

### Fix
- `bot/trade_lifecycle.py`: alleen saldo_errors van **<48h oud** als pending behandelen. Configurable via `SALDO_GUARD.pending_max_age_hours` (default 48).
- `data/pending_saldo.json` geleegd.
- Bot herstart om CONFIG `_SALDO_COOLDOWN_UNTIL` te clearen en nieuwe code te laden.

### Lesson
Re-detectie zonder timestamp-cutoff = bug-klasse. Elk filter dat closed/archive scant moet een leeftijdsgrens hebben â€” anders worden oude states eindeloos geherregistreerd. Tests dekten alleen de "fresh" path, niet "archive met oude entries". Test toevoegen die archive met saldo_errors >48h oud opneemt en verifieert dat ze NIET re-pended worden.

---

## #050 â€” Telegram-spam "heartbeat stale or missing" terwijl bot gewoon draait (2026-04-26)

### Symptom
Gebruiker krijgt herhaaldelijk Telegram-meldingen:
> `ALERT: heartbeat stale or missing (last_ts=...). Bot may be down.`

Terwijl `data/heartbeat.json` vers is (age ~30-60s), bot draait, trades gaan door. Echte false-positives.

### Root cause
`modules/trading_monitoring.py::start_heartbeat_monitor`:
1. EÃ©n transient OS-error tijdens `os.replace()` (Windows/OneDrive race) â†’ `OSError` werd niet opgevangen â†’ `ts=None` â†’ alert pad.
2. Geen retry, geen "consecutive confirmation" â€” eerste hiccup alert direct.
3. Lege/half-geschreven JSON gaf `JSONDecodeError` (wel gevangen) maar `ts` bleef None â†’ ook alert pad bij volgende loop.

### Fix
1. `_alerts_enabled()`: nieuwe config flag `HEARTBEAT_STALE_ALERT_ENABLED` (default `True`), per loop hot-reloadbaar.
2. **Retry-loop** binnen monitor: 3x read met 100/200/300ms backoff voor transient OSError/JSONDecodeError.
3. **Consecutive confirmation**: alert pas na 3 opeenvolgende stale checks (~3 minuten bij interval=60s) â€” niet bij 1 hiccup.
4. Read als `utf-8-sig` (verdraagt BOM), accept `ts` of `timestamp` veld.
5. In `bot_config_local.json`: `HEARTBEAT_STALE_ALERT_ENABLED = false` om de Telegram-melding helemaal uit te zetten.

### Lesson
Atomic `os.replace()` op Windows + OneDrive geeft soms transient OS-errors zelfs als de write succesvol is. Lezers moeten ALTIJD retry + last-known-good fallback hebben, NIET Ã©Ã©n read = waarheid. Dit was hetzelfde patroon als FIX #048 maar dan in de monitor i.p.v. dashboard.

---

## #049 â€” Trade-card toonde verkeerde "GeÃ¯nvesteerd" + inconsistente P/L na partial sell (2026-04-25)

### Symptom
LTC trade-card op dashboard toont:
- GeÃ¯nvesteerd: â‚¬320,03 (de originele aankoop)
- Huidige waarde: â‚¬145,44
- P/L: â‚¬-174,59 / +1,67%

â†’ getallen kloppen niet bij elkaar (â‚¬-174 met +1,67%?). Gebruiker dacht dat de bot de partial sell had gemist.

### Root cause
Bot detecteerde de partial sell wel correct: `invested_eur` stond op â‚¬143,06 (current cost basis), `initial_invested_eur` op â‚¬320,03 (immutable origineel). Maar:
- **Backend** (`tools/dashboard_v2/backend/main.py:322`): `invested = initial_invested_eur or invested_eur` â†’ gebruikte de â‚¬320 voor `unrealised_pnl_eur`-berekening, terwijl `unrealised_pnl_pct` los uit `cur/buy_price` kwam â†’ tegenstrijdige getallen.
- **Frontend** (`index.html:192`): toonde `initial_invested_eur` als "GeÃ¯nvesteerd" zonder uitleg over de partial sell.

### Fix
1. Backend: `invested = invested_eur or initial_invested_eur` (huidige cost basis wint). Nieuwe velden: `invested_eur_current`, `partially_sold`, `total_pnl_eur` (incl. al-teruggehaalde EUR).
2. Frontend: toont `invested_eur_current`, badge "deels verkocht" + sub-regel met origineel + teruggekomen EUR.

### Lesson
Cost basis voor live P/L = `invested_eur` (mutable, current). `initial_invested_eur` is alleen voor context/historie. Twee getallen op dezelfde card moeten ALTIJD dezelfde basis gebruiken anders krijg je inconsistente outputs (â‚¬-174 vs +1.67%).

---

## #048 â€” Dashboard V2 toonde lege pagina (heartbeat null) door stale uvicorn-proces (2026-04-25)

### Symptom
Dashboard pagina laadt wel, maar alle KPI/portfolio velden zijn leeg / `--`. `GET /api/health` geeft `bot_online:false, heartbeat_age_s:null` terwijl `data/heartbeat.json` wel vers is (bot draait gewoon).

### Root cause
1. **Race condition**: bot schrijft heartbeat via atomic `os.replace()`. Op Windows kan tussen unlink en rename de file kortstondig "in use" zijn â†’ `_read_json` vangt exception â†’ returnt `{}` â†’ `bot_online:false`.
2. **Geen fallback**: 1 mislukte read â†’ `{}` werd gewoon doorgegeven aan UI. Gecombineerd met TTL-cache van 2s voelt het alsof het "vast zit", maar elke read ging fout.
3. **Geen watchdog**: niets controleerde of dashboard nog gezond was vs. werkelijke heartbeat-versheid.

### Fix
1. `_read_json` in `tools/dashboard_v2/backend/main.py`: 3x retry met 50/100/150 ms backoff + **last-known-good fallback** per pad. Bij transiÃ«nte fouten serveert hij vorige succesvolle waarde i.p.v. `{}`.
2. Nieuw script `scripts/dashboard_v2_watchdog.py`: pingt elke 30s `GET /api/health`, en als 3 checks (â‰ˆ90s) achter elkaar onhealthy zijn TERWIJL `heartbeat.json` wel vers is â†’ kill+restart uvicorn op `0.0.0.0:5002`. Cooldown 5 min tegen restart-loops.
3. Watchdog toegevoegd aan `scripts/startup/start_bot.py` als ManagedProcess met auto_restart=True.

### Lesson
Op Windows is atomic JSON-replace nooit 100% race-vrij door file locks. Lezers MOETEN retryen + last-known-good fallback hebben, anders krijgen UI's lege schermen bij transiÃ«nte fouten. **Nooit `except: return {}`** zonder fallback bij hoog-frequente bestanden.

---

## #047 â€” SCAN_WATCHDOG_SECONDS te laag â†’ maar 1-2 markten gescand per cycle (2026-04-25)

### Symptom
Dashboard signal-status toont continu `1/20 markets gescand`, geen entries hoewel 2 slots vrij + EUR cash = â‚¬373.93. Log:
```
[SCAN WATCHDOG] Aborting scan after 2 markets / 20 (elapsed 60.5s)
[SCAN SUMMARY] 20 markets, 2 evaluated ... 0.03 markets/s
```

### Root cause
`SCAN_WATCHDOG_SECONDS` default = **60s** (`trailing_bot.py:1088`), maar elke market kost 25-30s door LSTM + ensemble inference (XGB+LSTM+RL). Na 2 markten breekt watchdog af â†’ 18 markten worden nooit geÃ«valueerd â†’ bot mist alle entries behalve random eerste 2.

### Fix
Bumped `SCAN_WATCHDOG_SECONDS = 300` (5 min) in `%LOCALAPPDATA%\BotConfig\bot_config_local.json`. Hot-reloaded zonder restart. Bij volgende cycle worden alle 20 markten geÃ«valueerd (~9 min worst case, ruim binnen 5-min budget op gemiddelde snelheid).

### Lesson
Scan-tijd schaalt lineair met aantal markten Ã— inference-tijd per markt. LSTM + ensemble â‰ˆ 25s per markt â†’ minimum watchdog = `markets Ã— 30s` met buffer. Bij future model-uitbreidingen: meet nieuwe per-markt tijd en pas watchdog aan.

---

## #046 â€” Telegram /set met dot-key faalde stil + Portfolio toonde slechts 5 closed trades (i.p.v. 800+) + Roadmap stortingsscenario's miste compounding-uitleg en hogere stappen + Stortingsplan-component overbodig (2026-04-23)

### Symptom / Aanleiding
Gebruiker meldde:
1. "Als ik parameters aanpas in telegram, dan doet die dat niet naar local config" â†’ `/set BUDGET_RESERVATION.trailing_pct 80` had geen effect.
2. "Bij portfolio zie ik nog maar 5 trades staan, terwijl ik 100 heb aangevinkt. het lijkt wel of al die trades weg zijn" â†’ trade_log had 7 closed; archive had 861 maar werd niet gemerged.
3. Vraag of de Mijlpaal-ETA tabel winst-herinvestering meeneemt + verzoek om dynamische stappen 500/1000.
4. Verzoek om Stortingsplan-tabel te verwijderen.

### Root cause
1. `_apply_set_command()` in `modules/telegram_handler.py` deed `key.upper()` op de **hele** key incl. dot. `BUDGET_RESERVATION.trailing_pct` werd `BUDGET_RESERVATION.TRAILING_PCT` (child geupperd) â†’ niet in `ALLOWED_KEYS` â†’ user kreeg "Onbekende parameter". Bot config gebruikt **lowercase** children dus de uppercase write zou bovendien een nieuwe key naast de bestaande hebben gezet.
2. Het portfolio-template wordt geserveerd door **`tools/dashboard_flask/blueprints/main/routes.py`** (Flask blueprint), NIET door `app.py::portfolio`. De blueprint las alleen `trades.get('closed', [])` (â‰ˆ5 trades) en raakte de archive nooit. Bovendien gebruikt `data/trade_archive.json` de top-level key `'trades'` (NIET `'closed'`) â€” 861 trades waren onzichtbaar.
3. Bestaande tekst zei alleen "compounding" zonder duidelijk te maken dat dat trading-winst herbelegt; deposits stonden vast op 0/100/200/300; geen stappen voor â‚¬500/â‚¬1000.
4. `deposit_plan` was hardcoded V2-fasering die niet meer matchte met huidige roadmap.

### Fix
- **MOD** `modules/telegram_handler.py::_apply_set_command`: dot-keys worden nu opgesplitst â€” parent UPPERCASE, child case-preserve. Lookup in `ALLOWED_KEYS` is case-insensitive zodat `/set budget_reservation.trailing_pct 80` of `/set BUDGET_RESERVATION.TRAILING_PCT 80` beide werken. Reply toont nu expliciet het opgeslagen pad: `%LOCALAPPDATA%/BotConfig/bot_config_local.json`.
- **MOD** `modules/telegram_handler.py::_save_local_override`: dot-keys worden geschreven met UPPERCASE parent + originele-case child (matched bot config schema). Single-level keys nog steeds `key.upper()`.
- **MOD** `tools/dashboard_flask/blueprints/main/routes.py::portfolio`: merget nu `data/trade_archive.json` (zowel `trades` als `closed` keys) in `closed_trades_raw`, dedupliceert op `(market, timestamp, sell_price)`, en logt `[PORTFOLIO] Closed trades after archive merge: N` voor diagnose. Resultaat: 837 trades beschikbaar i.p.v. 5 â†’ met `?trades_count=100` toont nu 97 (3 partial-TP filtered).
- **MOD** `tools/dashboard_flask/app.py::portfolio` (monolith fallback): zelfde merge toegevoegd voor consistentie.
- **MOD** `tools/dashboard_flask/app.py::roadmap`: `SCENARIO_DEPOSITS = [0, 100, 200, 300, 500, 1000]` en `SCENARIO_TARGETS = [2000, 5000, 10000, 25000, 50000]` â€” tabel is nu 6Ã—5 i.p.v. 4Ã—3. `deposit_scenarios[].etas` lijst-vorm voor template-loop. Stortingsplan-blok verwijderd. Comment toegevoegd dat groei% Ã— kapitaal = winst-herinvestering.
- **MOD** `tools/dashboard_flask/templates/roadmap.html`: drie-kolom layout vervangen door 2-kolom (Stortingsplan-paneel weg). Deposit-toggle uitgebreid met â‚¬500/â‚¬1000. Scenario-tabel rendert nu via `{% for t in scenario_targets %}` + `{% for eta in s.etas %}`. Onderschrift expliciet: "âœ… Trading-winst wordt automatisch herbelegd in de simulatie".

### Verification
- `/set BUDGET_RESERVATION.trailing_pct 80` â†’ schreef `BUDGET_RESERVATION.trailing_pct = 80.0` naar local override; readback bevestigd; daarna teruggezet naar 100.
- `/set GRID_TRADING.enabled true` â†’ schreef correct in geneste dict.
- `/portfolio?trades_count=100` â†’ log: `Closed trades after archive merge: 837`, `Closed trades count: 97`. Response 241kB (was ~177kB).
- `/roadmap?deposit=500` â†’ 200, deposit-toggle bevat â‚¬500 en â‚¬1000, scenario-tabel toont kolommen â‚¬25.000 en â‚¬50.000, onderschrift bevat "automatisch herbelegd".
- Stortingsplan-paneel niet meer in HTML (alleen orphan CSS in `.deposit-table` die ongebruikt is).
- 16 python-procs draaien na 2Ã— herstart.

### Lesson (CRITICAL)
- **Dashboard heeft TWEE portfolio-routes** (monolith `app.py::portfolio` Ã©n `blueprints/main/routes.py::portfolio`) â€” bij wijzigingen aan portfolio-data ALTIJD beide controleren. De blueprint wint omdat hij eerst geregistreerd wordt in Flask app-init.
- **`data/trade_archive.json` gebruikt key `'trades'`, niet `'closed'`** â€” alle dashboard-aggregaties die archive merging doen moeten beide keys lezen (`get('trades', []) + get('closed', [])`).
- **Telegram dot-keys: parent UPPERCASE, child case-preserve.** `key.upper()` op de hele key breekt de lookup omdat bot config schema lowercase children gebruikt (`enabled`, `trailing_pct`, etc.).

---

## #045 â€” Dashboard Parameters tab schreef wijzigingen naar OneDrive base config + RSI Max DCA validatie blokkeerde 100 + Roadmap miste deposit-scenario's en multi-level passief inkomen (2026-04-23)

### Symptom / Aanleiding
Gebruiker meldde dat:
1. "Als ik wat aanpas of het ook echt veranderd" â†’ **wijzigingen werden NIET persistent**: `/api/strategy/save` schreef naar `config/bot_config.json` (OneDrive!) â†’ werd elke sync gereverteerd.
2. RSI Max DCA veld toonde HTML5 popup "minimaal 70" terwijl waarde 100 â†’ input had `min="30" max="70"`, browser zei "Value must be â‰¤ 70" â†’ user las dat als minimum.
3. Roadmap-tab toonde alleen "Opbrengst bij â‚¬6.000", geen scenarios voor andere kapitaalniveaus, geen ETA per stortingsbedrag.
4. Algemene "rommelige" layout van Parameters-tab â€” vrijwel geen CSS voor `.param-field`/`.params-grid`/`.input-row`/`.ai-switch`.
5. Vraag: "doet auto_retrain zelf de retrain? blijft timer staan na restart?"

### Root cause
1. `tools/dashboard_flask/app.py::save_strategy_parameters()` deed `write_json_compat(str(config_path), config)` waar `config_path = PROJECT_ROOT/config/bot_config.json` â€” strijdig met de project-regel "ALL config changes MUST go to `%LOCALAPPDATA%/BotConfig/bot_config_local.json`".
2. Templates `parameters.html` had hardcoded `min/max` op RSI-velden (`30-40`, `60-90`, `30-70`) terwijl RSI gewoon 0-100 is.
3. Roadmap had Ã©Ã©n hardcoded `earnings_at_5k` dict en Ã©Ã©n globale ETA met vaste deposit_per_week.
4. CSS-classes (`.params-grid`, `.param-field`, `.ctrl-btn`, `.ai-switch`, `.params-save-bar`) waren nergens gedefinieerd in `dashboard.css` â†’ browser fallback layout.
5. Auto_retrain DOES self-run (`auto_retrain.py --loop` via `start_automated.ps1`) en IS restart-safe (`trained_at` opgeslagen in `ai/ai_model_metrics.json`, `compute_due_time` rekent vanaf laatste training). Geen bug, alleen onduidelijkheid.

### Fix
- **MOD** `tools/dashboard_flask/app.py::save_strategy_parameters`: schrijft nu **alleen** geraakte keys naar `LOCAL_OVERRIDE_PATH` (`%LOCALAPPDATA%/BotConfig/bot_config_local.json`), gemerged met bestaande lokale overrides. Atomic write (`.tmp` + `os.replace`). Response geeft `saved_to` + `saved_keys` terug.
- **MOD** `templates/parameters.html`: RSI-velden naar `min="0" max="100"` met tooltips. Sticky save bar met live-status ("Onopgeslagen wijzigingen" / "Opgeslagen naar local override"). Param-fields markeren met `.dirty` class bij wijziging.
- **MOD** `templates/roadmap.html` + `app.py::roadmap`:
  - `?deposit=0|100|200|300` selector â†’ herberekent ETA's met compounding model `simv = simv*(1+groei) + deposit/week` per week tot doel.
  - Nieuwe **Passief Inkomen tabel** voor 9 kapitaalniveaus (â‚¬1.5k â†’ â‚¬50k) met /dag, /maand, /jaar op basis van werkelijke recente daily yield% uit performance-stats.
  - Nieuwe **Stortingsscenario tabel**: ETA naar â‚¬2k/â‚¬5k/â‚¬10k voor 4 deposit-niveaus naast elkaar.
  - Nieuwe **Auto-Retrain Status panel**: leest `ai/ai_model_metrics.json` â†’ toont last/next + uitleg dat timer restart-safe is.
  - Nieuwe **Geavanceerde Roadmap-ideeÃ«n** sectie: 12 advanced ideas (multi-strategy A/B, sentiment overlay, per-coin Kelly, time-of-day filter, auto-withdraw, hedge perpetuals, staking, multi-exchange arbitrage, capital plan optimizer, push-notif, backtest button).
- **MOD** `static/css/dashboard.css`: 200 regels nieuwe styling voor params-form (clean grid, hover, dirty marker, AI toggle switch, sticky save bar, slide-in toast).

### Files
- MOD: `tools/dashboard_flask/app.py` (save endpoint + roadmap route met scenarios/passive income/future ideas/autoretrain)
- MOD: `tools/dashboard_flask/templates/parameters.html` (RSI bounds + sticky save bar + dirty markers + saved-to feedback)
- MOD: `tools/dashboard_flask/templates/roadmap.html` (4 nieuwe panels + CSS)
- MOD: `tools/dashboard_flask/static/css/dashboard.css` (~200 regels params-form V2 styling)

### Validatie
- `Invoke-WebRequest /roadmap?deposit=200` â†’ 200 OK, alle 4 nieuwe sections aanwezig (Passief Inkomen, Stortingsscenario, Auto-Retrain, Geavanceerde Roadmap-ideeÃ«n).
- `Invoke-WebRequest /parameters` â†’ 200 OK, sticky save bar + local override hint + RSI 0-100 aanwezig.
- POST `/api/strategy/save` met `{"max_open_trades":4}` â†’ response `saved_to: %LOCALAPPDATA%/BotConfig/bot_config_local.json`, `saved_keys: [MAX_OPEN_TRADES]`. Verified met PowerShell read-back: `MAX_OPEN_TRADES = 4` in local override file.
- Bot restart: 16 procs running.

### Lesson Learned
**Dashboard write-paths moeten ALTIJD naar LOCAL_OVERRIDE_PATH gaan.** Elke `/api/.../save` route die `config/bot_config.json` direct schrijft is een bug waiting to happen â€” OneDrive reverteert. Check ook andere endpoints (whitelist/blacklist/reset/etc.) â€” die staan nog steeds op `bot_config.json` en moeten apart geaudit worden bij volgende sessie.

---

## #044 â€” Regular XGB nooit (her)getraind: trade_features.csv ontbrak + bb_position/stochastic_k werden niet gelogd (2026-04-23)

### Symptom / Aanleiding
Het regular 7-feature XGB model (`ai/ai_xgb_model.json`) dat de bot **live** laadt in `modules.ml._get_xgb_model` werd nooit (her)getraind:
1. `tools/auto_retrain.py` verwacht `trade_features.csv` in project-root â†’ bestand bestond niet â†’ `_training_data_ready()` skipte training elke cyclus.
2. NaÃ¯ef bouwen vanuit archief gaf 837 rijen, maar 785 hadden default `rsi=50` / `sma=0` (entry-snapshot werd vroeger niet gelogd) â†’ bruikbaar = 52, label-balans 47/5 â†’ onbruikbaar voor training.
3. `bb_position` en `stochastic_k` werden bij entry **nergens** opgeslagen, ondanks dat `bot/signals.py` ze in `ml_info` plaatst.

### Root Cause
1. Geen pipeline-stap die `trade_features.csv` genereert uit het archief.
2. `trailing_bot.py` entry-meta block sloeg wel `rsi/macd/sma_short/sma_long/bb_upper/bb_lower/...` op maar niet `bb_position` en `stochastic_k`.
3. Voor historische trades was er geen backfill-mechanisme om de snapshot uit Bitvavo candles te reconstrueren.

### Fix
- **NEW** `scripts/build_trade_features.py`: bouwt `trade_features.csv` (rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k, label) uit `trade_log.json` + `trade_archive.json`. Filtert default-only rows en mergt optionele backfill-cache.
- **NEW** `scripts/backfill_trade_features.py`: voor trades zonder echte snapshot fetcht 1m candles (3h venster) rond `opened_ts` via Bitvavo API en herberekent alle 7 features. Resultaat naar `data/trade_features_backfill.json` (resumable cache). Eerste run: **588/757 succes** â†’ 652 bruikbare rijen voor training.
- **MOD** `trailing_bot.py`: entry-meta block slaat nu ook `bb_position_at_entry` en `stochastic_k_at_entry` op uit `ml_info`. Vanaf nu zijn alle 7 features per nieuwe trade direct uit `trade_archive.json` afleidbaar.
- **MOD** `tools/auto_retrain.py`: roept eerst `backfill_trade_features.py` (incrementeel via cache), dan `build_trade_features.py`, dan pas `_training_data_ready()` + `xgb_walk_forward.py`. Volledig automatische pipeline.

### Files
- NEW: `scripts/build_trade_features.py`
- NEW: `scripts/backfill_trade_features.py`
- MOD: `trailing_bot.py` (entry-meta save: `bb_position_at_entry`, `stochastic_k_at_entry`)
- MOD: `tools/auto_retrain.py` (BACKFILL_SCRIPT/BUILD_FEATURES_SCRIPT chained vÃ³Ã³r train)
- NEW data: `data/trade_features_backfill.json` (757 entries cache), `trade_features.csv` (652 rows)

### Validation
- `python ai/xgb_walk_forward.py --window 400 --step 100` â†’ "Samples: 652, Features: 7, Folds: 2, Avg Accuracy: 55.00%, Avg Precision: 62.98%, Buy rate: 61.04%". Feature importance evenwichtig verdeeld (rsi 0.15, sma_short 0.19, volume 0.19, bb_position 0.10, stochastic_k 0.09).
- Model verified: `xgb.XGBClassifier().load_model('ai/ai_xgb_model.json').n_features_in_ == 7` âœ“

### Notes
- Bitvavo's historische candle endpoint geeft beperkte data terug voor pairs > paar maanden oud (~25-35 candles ipv 60) â†’ 169 oudere trades konden niet backfilled worden ("insufficient_candles"). Acceptabel: 588 echte + 64 originele snapshots = 652 trainset.
- `data/trade_features_backfill.json` is incrementeel: volgende runs van de backfill skippen reeds-cached entries, dus `auto_retrain` mag deze veilig elke cyclus draaien.

---

## #043 â€” Slechts 7 closed trades zichtbaar voor enhanced trainer + grid-exclusion blokkeert BTC/ETH terwijl GRID_TRADING uit staat (2026-04-23)

### Symptom / Aanleiding
1. `xgb_train_enhanced.py` rapporteerde "Loaded 7 closed trades" terwijl er **861** trades in `data/trade_archive.json` staan â†’ MIN_SAMPLES (100) nooit gehaald â†’ enhanced trainer kon nooit draaien.
2. Bot-log toonde herhaald `[GRID] Excluding grid markets from trailing management: ['BTC-EUR']` en `Excluding grid trading markets from trailing bot: ['BTC-EUR']` â€” terwijl `GRID_TRADING.enabled=False` in config en `[Grid] DISABLED in config` Ã³Ã³k al gelogd werd. BTC-EUR (en bij implicatie ETH-EUR uit andere whitelist-checks) bleven uitgesloten van trailing terwijl ze in de whitelist staan.

### Root Cause
1. `ai/xgb_train_enhanced.py.load_closed_trades()` las allÃ©Ã©n `data/trade_log.json`. De lifecycle manager archiveert oudere trades naar `data/trade_archive.json` (861 entries), waardoor `trade_log.json` slechts ~7 recente closed trades bevat. Het archief werd genegeerd.
2. `trailing_bot.get_active_grid_markets()` riep onvoorwaardelijk `get_grid_manager().get_all_grids_summary()` aan. Die returnt actieve grids op basis van **on-disk `data/grid_states.json`** â€” een stale BTC-EUR grid uit een eerdere sessie bleef staan. Geen check op `CONFIG['GRID_TRADING']['enabled']` â†’ wanneer grid module is uitgezet via config, blijft de stale state alsnog markets uitsluiten.

### Fix
- `ai/xgb_train_enhanced.py`:
  - `load_closed_trades()` leest nu zowel `data/trade_log.json` als `data/trade_archive.json` en deduplicate op `(market, opened_ts/timestamp, sell_order_id)`. Resultaat: **837 unique closed trades** (was 7) â†’ MIN_SAMPLES ruim gehaald, positive ratio 57.95%.
  - `extract_features_from_trades()` accepteert nu zowel nieuwe (`*_at_entry`) als legacy (`*_at_buy`) field names voor RSI/MACD/volatility.
  - Feature-cols uitgebreid met `macd_at_buy` en `volatility_at_buy`.
- `trailing_bot.get_active_grid_markets()`: early return `set()` als `CONFIG['GRID_TRADING'].get('enabled', False)` False is. Stale `grid_states.json` kan zo nooit meer markets uitsluiten van trailing.

### Files
- MOD: `ai/xgb_train_enhanced.py` (load_closed_trades, extract_features_from_trades, prepare_training_data)
- MOD: `trailing_bot.py` (`get_active_grid_markets`)

### Validation
- Standalone: `load_closed_trades()` â†’ "Loaded 7 closed trades from trade_log.json / Loaded 861 archived trades / Total unique 837 / Extracted 837 feature records / Positive ratio 57.95%".
- Bot herstart na fix: nieuwe scan toont **"Nieuwe scan gestart: 20 markten (totaal 20)"** (was 19) â€” BTC-EUR is nu opgenomen. Geen `Excluding grid` log lines meer na restart.
- 16 procs running, heartbeat fresh.

### Notes
- Andere modules met `xxx_archive.json` skip-patroon (sync, performance) controleren of ze Ã³Ã³k archief negeren â€” toekomstige refactor.
- Stale `data/grid_states.json` blijft op disk staan; harmless nu de guard er is, maar ooit handmatig opruimen als grid trading definitief af.

---

## #042 â€” auto_retrain overwrote 7-feature XGB met 5-feature enhanced + LSTM script ontbrak + TF niet geÃ¯nstalleerd (2026-04-23)

### Symptom / Aanleiding
Bot logde herhaaldelijk:
```
[Ensemble] ... XGB=0, LSTM=None(0.33), RL=None(0.00) â†’ HOLD (conf=1.00)
LSTM predictor laden mislukt: TensorFlow is vereist voor LSTM predictor
```
en eerder, bij retrain runs: `Feature shape mismatch, expected: 7, got: 5`. Resultaat: ensemble degradeerde naar XGB-only (of zelfs alleen score-based) en `auto_retrain.py --loop` riep een script aan dat niet bestond (`scripts/train_lstm_model.py`).

### Root Cause
1. `tools/auto_retrain.py` had `TRAIN_SCRIPT = ai/xgb_train_enhanced.py` â€” die schrijft een 5-feature model naar `ai/ai_xgb_model.json`, terwijl `modules/ml.py` een 7-feature model verwacht (rsi, macd, sma_short, sma_long, volume, bb_position, stochastic_k). Elke retrain-run brak de bot.
2. Geen guard tegen ontbrekende `trade_features.csv` â†’ trainer crashte; bestaand model werd overschreven of corrupt.
3. `scripts/train_lstm_model.py` werd door auto_retrain aangeroepen maar bestond niet â†’ subprocess-failure per cyclus.
4. TensorFlow was niet geÃ¯nstalleerd in de venv (`Python 3.13.7`); LSTM-predictor in `modules/ml_lstm.py` raised â†’ ensemble viel terug op XGB-only.

### Fix
- `tools/auto_retrain.py`:
  - `TRAIN_SCRIPT` â†’ `ai/xgb_walk_forward.py` (regular 7-feature trainer; enhanced is post-trade analyse only).
  - Nieuwe helper `_training_data_ready() -> Tuple[bool, str]` checkt of `trade_features.csv` bestaat Ã©n â‰¥`MIN_TRAIN_SAMPLES` (100) rijen heeft. Bij `False` â†’ log warning en SKIP de XGB-stap (bestaande model blijft staan).
  - LSTM-blok krijgt `lstm_script.exists()` guard vooraf.
  - `build_train_command` geeft `--window`/`--step` door uit `AI_RETRAIN_ARGS`.
- `scripts/train_lstm_model.py` (NIEUW): walk-forward LSTM trainer die live Bitvavo candles ophaalt (10 markets Ã— 1440Ã—1m), sequences bouwt (lookback=60, horizon=5, up_threshold=0.003), model bouwt via `LSTMPricePredictor.build_model()` â†’ `train()` â†’ `save_model()`. Aborts safely zonder overschrijven als TF mist of <200 sequences.
- `%LOCALAPPDATA%/BotConfig/bot_config_local.json`: `USE_LSTM=true` (helper script `_enable_lstm.py` met `encoding='utf-8-sig'` BOM-safe).
- `pip install tensorflow` â†’ TF 2.21.0 (Python 3.13 wheels werken; CPU-only op Windows, geen GPU).

### Files
- MOD: `tools/auto_retrain.py`
- NEW: `scripts/train_lstm_model.py`
- NEW (helper, niet committed): `_enable_lstm.py`, `_smoke_ml.py`
- CONFIG: `%LOCALAPPDATA%/BotConfig/bot_config_local.json` (`USE_LSTM=true`)

### Validation
- `import tensorflow as tf; tf.__version__` â†’ `2.21.0`.
- `LSTMPricePredictor.load_model()` op `models/lstm_price_model.h5` â†’ `True`; `predict(np.random.rand(60,5))` â†’ `('NEUTRAL', 0.78)`.
- Bot herstart: 16 procs running, heartbeat fresh, 3 trades managed, log toont `LSTM model gebouwd: 60 lookback, 5 features` en `LSTM model geladen van models\lstm_price_model.h5`. Geen `Feature shape mismatch` meer, geen `TensorFlow is vereist` warnings sinds restart.
- Auto_retrain triggerde live `train_lstm_model.py` â†’ 10771 train / 2693 val sequences over 10 markten Ã— 10 epochs (training in progress).

### Notes
- **Twee XGB-modellen serveren verschillende doelen**: `ai_xgb_model.json` (7-feat regular) wordt door bot geladen voor live signalen. `ai_xgb_model_enhanced.json` (5-feat) is uitsluitend post-trade analyse â€” die mag nooit naar de regular path geschreven worden.
- **`trade_features.csv` bestaat nog niet**: er zijn slechts 7 closed trades; auto_retrain skipt XGB veilig totdat data ready is.
- **Python 3.13 + TF 2.21**: officieel ondersteund vanaf TF 2.17+. Wheels installeerden zonder problemen via `pip install tensorflow`.
- **OneDrive-immune config**: `USE_LSTM` gezet in `%LOCALAPPDATA%/BotConfig/bot_config_local.json` zodat OneDrive het niet kan reverten.

---

## #041 â€” trailing_bot.py crash-loop: KeyError op SMA_SHORT bij module-load (2026-04-23)

### Symptom / Aanleiding
Bot maakte geen nieuwe trades meer. `monitor.py` startte `trailing_bot.py` continu opnieuw op (~elke 7-15s) â€” zichtbaar in `scripts/helpers/logs/monitor.log` en stderr toonde:
```
File "trailing_bot.py", line 720, in <module>
    SMA_SHORT = CONFIG["SMA_SHORT"]
KeyError: 'SMA_SHORT'
```
De keys `SMA_SHORT`, `SMA_LONG`, `MACD_FAST`, `MACD_SLOW`, `MACD_SIGNAL`, `BREAKOUT_LOOKBACK`, `MIN_SCORE_TO_BUY` ontbraken in zowel `config/bot_config.json` als `bot_config_local.json`. Module-level dict-subscript leverde direct een `KeyError` op import â†’ crash voor `bot_loop()` ooit draaide.

`heartbeat.json` werd hierdoor sinds 09:33 niet meer ververst, terwijl support-services (dashboard, AI supervisor, monitor zelf) wÃ©l bleven loggen â€” waardoor het leek alsof de bot draaide.

### Root Cause
1. `trailing_bot.py` regels 720-726 gebruikten `CONFIG["KEY"]` (raise op missing) i.p.v. `.get()` met default.
2. `modules/config.py.load_config()` past schema-defaults uit `config_schema.py` NIET toe op de geladen dict â€” schema is alleen voor validatie.
3. Combinatie = elke missende key crasht de bot bij module-import.

### Fix
Vervangen door `_as_int(CONFIG.get(...), <schema_default>)` met defaults uit `modules/config_schema.py`:
- `SMA_SHORT=20`, `SMA_LONG=50`, `MACD_FAST=12`, `MACD_SLOW=26`, `MACD_SIGNAL=9`, `BREAKOUT_LOOKBACK=50`, `MIN_SCORE_TO_BUY=7.0` (laatste blijft float).

### Files
- MOD: `trailing_bot.py` (regels 720-726)

### Notes
- Dit is een terugkerend patroon: **module-level `CONFIG[...]` is fragiel**. Zoek alle resterende dict-subscripts in trailing_bot.py op import-niveau en migreer naar `.get()` met defaults â€” toekomstige config-drift mag de bot niet meer crashen.
- Overweeg `load_config()` schema-defaults te laten inject â€” maar dat is een bredere refactor.
- De kwaadaardige neveneffecten van deze crash-loop: `scripts/helpers/logs/trailing_stdout.log` is gegroeid tot **868 MB** en `bot_log.txt.rotation.log` tot **5.3 GB**. Schoonmaak nodig.

---

## #040 â€” Nieuwe edge stack: post-loss cooldown + adaptive MIN_SCORE + BTC drawdown shield + dashboard refresh (2026-04-24)

### Symptom / Aanleiding
Volgende-generatie verbeteringen na #039 full-deployment. Doelen:
1. Voorkom direct re-entry op een net verloren markt (revenge trading).
2. Verhoog MIN_SCORE-drempel automatisch tijdens slechte periodes (lage rolling WR / loss-streak).
3. Skip new entries (excl. BTC-EUR) als BTC zelf instort op 5m timeframe (crash hedge).
4. Dashboard verouderd visueel â€” vol grid-trading milestones die niet meer relevant zijn.

### Fix Applied
**Drie nieuwe entry-gates** (bot/), elk geÃ¯soleerd + thread-safe + unit-tested:
- `bot/post_loss_cooldown.py` â€” `PostLossCooldown` singleton. Blokkeert market voor `POST_LOSS_COOLDOWN_SEC` (default 4h) na verlies; `POST_LOSS_BIG_COOLDOWN_SEC` (24h) na verlies > `POST_LOSS_BIG_LOSS_EUR` (â‚¬5). Persistent: `data/post_loss_cooldown.json`.
- `bot/adaptive_score.py` â€” `AdaptiveScoreThreshold(lookback=7)` met deque rolling-WR. Loss-streak override (â‰¥3 verliezen â†’ +2.0 op MIN_SCORE) heeft voorrang. WR-ladder: <40% +1.5, <55% +0.5, >75% âˆ’0.5.
- `bot/btc_drawdown_shield.py` â€” Stateless. Skip nieuwe entries als BTC 5m return over `BTC_DRAWDOWN_LOOKBACK_5M` (12 candles = ~1u) onder `BTC_DRAWDOWN_THRESHOLD_PCT` (default âˆ’1.5%). BTC-EUR market exempt.

**Wiring** in `trailing_bot.py`:
- Adaptive bump op `min_score_threshold` direct na config-load (~line 3041).
- Post-loss + BTC shield gates direct na `_event_hooks_paused` continue (~line 3160).
- Close-hooks naar beide singletons (`record_close`) in `_finalize_close_trade` na bestaande `market_expectancy.record_trade`.

**Tests**: 24 nieuwe unit tests in `tests/test_post_loss_cooldown.py`, `test_adaptive_score.py`, `test_btc_drawdown_shield.py` â€” alle slagen.

**Roadmap V2 herschreven**: `docs/PORTFOLIO_ROADMAP_V2.md` volledig zonder grid trading. 10 milestones â‚¬1.450â†’â‚¬25.000 met conservatief/base/optimistisch winstprojecties en ETAs t/m okt 2027.

**Dashboard milestones array** in `tools/dashboard_flask/app.py` (line 3774) gesynchroniseerd met nieuwe roadmap (geen grid entries meer, denominator 6000 â†’ 10000).

**Dashboard visual refresh** (non-destructief):
- Nieuwe `static/css/v3_modern.css` â€” dark glassmorphism design system, deep purple-blue accent, geladen LAATST in base.html zodat het alle legacy CSS overruled.
- **Command Palette (Ctrl+K / Cmd+K)** toegevoegd in base.html â€” quick-jump naar alle 10 hoofdpagina's met zoekfunctie, keyboard nav (â†‘â†“â†µEsc).

### Lesson
Voorkomen van re-entry-on-loss is empirisch veel effectiever dan alleen een hogere MIN_SCORE â€” markets vertonen 1-4u "post-loss EV-dip" patronen waar zelfs goede signalen onderpresteren. BTC drives ~80% van alt-correlatie op 5m: een BTC âˆ’1.5% in 1u is een betrouwbaarder kill-switch dan losse alt-checks. Adaptive MIN_SCORE met loss-streak override = dynamische rem op cascading losses zonder handmatige interventie.

Dashboard-tip: Ã©Ã©n LAATST-geladen CSS file (cascading override) is veiliger dan refactoren van 15 legacy files. Command Palette is ~50 regels JS en transformeert UX op alle 10 pagina's tegelijk.

---



### Symptom
Vorige iteratie #038 (BASE=200, MAX=4) liet typical 4Ã—200 = â‚¬800 = 55% van portfolio idle. Gebruiker terecht op gewezen: "200Ã—4 = 800, 600 idle".

### Fix
Echte volledige deployment via wijdere grid-search (BASE 200-350, MAX 3-5, DCA 20-50 Ã— 1-3):
- `BASE_AMOUNT_EUR`: 200 â†’ **320**
- `DCA_AMOUNT_EUR`: 40 â†’ **20** (klein want 97% trades trigger nooit DCA)
- `DCA_MAX_BUYS`/`ORDERS`: 2 â†’ **2** (ongewijzigd)
- `MAX_OPEN_TRADES`: 4 (ongewijzigd, behoudt diversificatie boven 3-slots winners)

Numeriek:
- Typical (geen DCA): 4 Ã— 320 = **â‚¬1.280 = 88%** van â‚¬1.450
- Worst (alle DCAs gevuld): 4 Ã— 360 = **â‚¬1.440 = 99%**
- Cash buffer: ~â‚¬170 voor fees+slippage
- Sim PnL: **+â‚¬673** op 123 trades = **+477% vs realized** = ~+â‚¬95/week

### Lesson
Bij "all capital deployed" moet de typical-case (no-DCA) zelf al ~85-90% zijn. Anders zit het meeste idle want 97% van trades doet geen DCA. DCA klein houden + BASE groot maken = correct. 3-slots config (BASE=350, MAX=3) gaf marginaal hogere PnL maar concentratierisico op single market crash is te hoog.

---

## #038 â€” â‚¬1.450 sizing upgrade naar NO-RESERVE profiel (2026-04-23)

### Symptom
InitiÃ«le V2.1 config (#037) was te conservatief voor de daadwerkelijke risk-appetite van de gebruiker â€” BASE=120 op â‚¬1.450 portfolio liet â‚¬610 (42%) ongebruikt.

### Fix
Lokale config opgeschaald naar de "no-reserve" variant van de â‚¬1.450 backtest:
- `BASE_AMOUNT_EUR`: 120 â†’ **200**
- `DCA_AMOUNT_EUR`: 30 â†’ **40**
- `DCA_MAX_BUYS`/`DCA_MAX_ORDERS`: 3 â†’ **2**
- `MIN_BALANCE_EUR`: 0 (expliciet â€” geen harde reserve)
- `MAX_OPEN_TRADES`: 4 (ongewijzigd, behoudt diversificatie)

Worst-case exposure: 4 Ã— (200 + 40Ã—2) = **â‚¬1.120 = 77%** van â‚¬1.450.
Sim PnL backtest: **+â‚¬431,63** op 123 clean trades (vs +â‚¬273 voor BASE=120 = **+58%**, vs +â‚¬117 realized = **+270%**).

### Lesson
Bij "geen reserve" houd je nog steeds 4 slots om concentratierisico te beperken. De Ã©chte rem op grotere posities is **slippage en spread-impact** boven ~â‚¬200/trade op kleinere alts (FET, ENJ, GALA), niet de capital-efficiency. Backtest schaalt PnL lineair maar live verlies door slippage kan 5-10% afsnijden van de geprojecteerde +270%.

---

## #036 â€” /set Telegram commando schrijft naar verkeerde config-laag (2026-04-21)

### Symptom
`/set BASE_AMOUNT_EUR 1000` (of andere keys) via Telegram had geen effect: de bot startte trades met het oude bedrag. Ookzag `/config` afwijkende waarden t.o.v. wat de bot echt gebruikte.

### Root Cause
`_load_config()` in `telegram_handler.py` las alleen layer 1 (`config/bot_config.json`, OneDrive). `_save_config()` schreef ook alleen naar layer 1. Maar de bot's runtime config is de 3-laags merged result waarbij **layer 3 (`LOCAL_OVERRIDE_PATH`) altijd wint**. Als layer 3 `BASE_AMOUNT_EUR = 127` had, overschreef die layer 3 elke write naar layer 1 bij de volgende `load_config()`.

### Fix Applied
| File | Change |
|------|--------|
| `modules/telegram_handler.py` | `_load_config()` roept nu `modules.config.load_config()` aan (volledige 3-laags merge) zodat alle Telegram-commando's de echte bot-waarden tonen |
| `modules/telegram_handler.py` | `_save_config()` verwijderd; vervangen door `_save_local_override(key, value)` die alleen de gewijzigde key naar `LOCAL_OVERRIDE_PATH` (layer 3) schrijft â€” wint over alles, nooit teruggedraaid door OneDrive |
| `modules/telegram_handler.py` | `_apply_set_command()` gebruikt nu `_save_local_override()` i.p.v. read-modify-write op layer 1 |
| `modules/telegram_handler.py` | `_save_chat_id()` gebruikt nu ook `_save_local_override()` |
| `modules/telegram_handler.py` | `BUDGET_RESERVATION.*` keys toegevoegd aan `ALLOWED_KEYS` (trailing_pct, grid_pct, reserve_pct, min_reserve_eur, mode) |
| `modules/telegram_handler.py` | Success message bijgewerkt: "Actief na volgende bot-loop (~25s)" i.p.v. "Herstart bot" |

### Lesson
`/set` moet altijd schrijven naar `LOCAL_OVERRIDE_PATH` (layer 3). Lees-modify-write op layer 1 werkt nooit betrouwbaar omdat layer 3 alles overschrijft. Gebruik altijd `_save_local_override()` voor config-aanpassingen via Telegram.

---

## #035 â€” Nieuw: /update Telegram commando (git pull + herstart) (2026-04-21)

### Symptom
Geen manier om code-updates op de crypto laptop te deployen zonder fysieke toegang (geen `git pull` mogelijk op afstand).

### Fix Applied
| File | Change |
|------|--------|
| `modules/telegram_handler.py` | Nieuwe functie `_git_pull_and_restart()`: voert `git pull` uit in `BASE_DIR`, stuurt uitvoer als Telegram-bericht, en roept `_restart_bot()` aan bij succes |
| `modules/telegram_handler.py` | `/update` commando toegevoegd aan command handler en `/help` tekst |
| `modules/telegram_handler.py` | Module docstring bijgewerkt met `/update` |

### Lesson
Bij een `git pull` fout (exit code â‰  0) wordt de bot NIET herstart â€” de foutmelding wordt via Telegram gestuurd zodat de gebruiker het kan oplossen.
---

## #037 â€” Position size floor + per-market EV-sizing for â‚¬1.450 portfolio (2026-04-23)

### Symptom
Bot at â‚¬1.450 portfolio was running with V2-start config (BASE=1000, MAX=6, DCA=61x5) â€” **6Ã— over-leveraged** for the actual portfolio. Many trades fired at <â‚¬25 invested (negative EV bucket: âˆ’â‚¬0,12/trade), while the proven sweet-spot (â‚¬75-â‚¬150) sat at +â‚¬3,34/trade. No data feedback loop to under-weight historically losing markets.

### Root cause
1. Single global BASE_AMOUNT_EUR was applied uniformly regardless of per-market expectancy.
2. No floor on tiny positions: dust-sized buys diluted the portfolio with negative-EV trades.
3. Config had not been right-sized after portfolio shrunk from â‚¬4k â†’ â‚¬1.450.

### Fix (3 new components)
1. **`bot/sizing_floor.py`** â€” `enforce_size_floor(market, proposed_eur, score, eur_balance, is_dca, cfg, log)`:
   - <SOFT_MIN (â‚¬50): abort
   - SOFT_MIN..ABS_MIN (â‚¬50-â‚¬75): bump up if balance allows OR allow if score â‰¥ 14 (high-conviction bypass) OR abort
   - â‰¥ ABS_MIN: pass-through
   - DCA buys exempt
2. **`core/market_expectancy.py`** â€” `MarketExpectancy` with empirical-Bayes shrinkage:
   - `shrunk_ev = (n Ã— ev_market + K_PRIOR Ã— ev_global) / (n + K_PRIOR)` with K_PRIOR=10, ALPHA=0.7
   - `size_multiplier(market) â†’ 0.0` if shrunk_ev â‰¤ âˆ’0.50 (blacklist), else clamped 0.30..1.80
   - Persists to `data/market_expectancy.json`, atomic writes every 5 trades
3. **Score-stamping** in `trailing_bot.py:open_trade_async` so the size-floor's high-conviction bypass actually has the entry score available.
4. Wired both into `bot/orders_impl.py:place_buy()` (after EUR balance safeguard, gated by `MARKET_EV_SIZING_ENABLED` and `POSITION_SIZE_FLOOR_ENABLED`).
5. Wired `market_ev.record_trade()` into `trailing_bot._finalize_close_trade` so the model self-improves on every closed trade (operational error reasons excluded).
6. **Bootstrap** script `scripts/helpers/bootstrap_market_ev.py` seeds 159 trades from the clean archive (March-April 2026, no saldo_error/sync_removed/manual/reconstructed/dust).
7. Local config right-sized for â‚¬1.450:
   ```
   BASE_AMOUNT_EUR: 1000 â†’ 120
   MAX_OPEN_TRADES: 6 â†’ 4
   DCA_AMOUNT_EUR: 61 â†’ 30
   DCA_MAX_BUYS: 5 â†’ 3
   DEFAULT_TRAILING: 0.024 â†’ 0.022
   TRAILING_ACTIVATION_PCT: 0.020 â†’ 0.025
   POSITION_SIZE_FLOOR_ENABLED: true (new)
   POSITION_SIZE_ABS_MIN_EUR: 75 (new)
   POSITION_SIZE_SOFT_MIN_EUR: 50 (new)
   POSITION_SIZE_HIGH_CONVICTION_SCORE: 14 (new)
   MARKET_EV_SIZING_ENABLED: true (new)
   ```
   Worst-case exposure: 4 Ã— (120 + 30Ã—3) = â‚¬840 = 58% of â‚¬1.450 âœ…

### Validation
- 17/17 new unit tests pass (`tests/test_sizing_floor.py`, `tests/test_market_expectancy.py`).
- Bootstrap seeded 159 trades, global EV +â‚¬0,73/trade, all whitelisted markets profitable, no blacklists triggered.
- Backtest on 123 clean trades since 2026-03-01: simulated PnL **+â‚¬273,24** vs realized +â‚¬116,59 = **+134% projected improvement**.

### Files touched
- NEW: `bot/sizing_floor.py`, `core/market_expectancy.py`, `scripts/helpers/bootstrap_market_ev.py`
- NEW: `tests/test_sizing_floor.py`, `tests/test_market_expectancy.py`
- MOD: `bot/orders_impl.py` (place_buy gates), `trailing_bot.py` (open_trade_async score stamp + _finalize_close_trade record), `bot/shared.py` (last_signal_score field)
- MOD: `docs/PORTFOLIO_ROADMAP_V2.md` (â‚¬1.450 milestone), `tools/dashboard_flask/app.py` (milestone array)
- LOCAL config: `%LOCALAPPDATA%/BotConfig/bot_config_local.json`

### Lesson
When portfolio shrinks significantly, BASE_AMOUNT must shrink with it â€” running â‚¬1000 BASE on a â‚¬1450 portfolio leaves no room for diversification or DCA. Always size BASE so that `MAX_TRADES Ã— (BASE + DCA_MAX Ã— DCA_AMOUNT) â‰¤ 60% Ã— portfolio` to preserve the 15% EUR reserve plus a safety buffer.

---

## #034 â€” Shadow tracker crash on string timestamps in closed_trades (2026-04-15)

### Symptom
Shadow mode hook in bot_loop silently failed â€” no entries written to `data/shadow_log.jsonl` despite scan completing successfully. Debug logging revealed: `could not convert string to float: '2026-04-10 20:12:20'`

### Root Cause
`closed_trades` list contains entries where `timestamp` field is an ISO date string (e.g. `'2026-04-10 20:12:20'`) rather than a unix float. The velocity filter's `float(t.get("timestamp"))` crashed on these entries. The `except Exception: pass` silently swallowed the error.

### Fix Applied
| File | Change |
|------|--------|
| `core/shadow_tracker.py` | Added `_parse_ts(val)` helper that handles float, int, and ISO date string timestamps |
| `core/shadow_tracker.py` | Velocity filter now uses `_parse_ts()` instead of bare `float()` |
| `trailing_bot.py` | Changed shadow hook `except Exception: pass` to `except Exception as e: log(...)` for debug visibility |

### Lesson
Never use bare `float()` on trade timestamps â€” the archive and closed_trades list contain mixed format timestamps (unix floats AND ISO strings). Always use a defensive parser.

---

## #033 â€” Grid counter-orders all at same price + no sell levels (2026-04-13)

### Symptom
Grid BTC-EUR had 6 open orders, ALL buys, NO sells. Three counter-buy orders were all
placed at the exact same price (60105), and three original buy levels at different prices.
Grid was using full â‚¬184 budget but was effectively a one-sided buy wall with no ability
to profit from price movements. Total open order value spread:
- 3 original buys: â‚¬56/each at 58891, 59498, 60105
- 3 counter-buys: â‚¬5/each all at 60105 (duplicate price!)

### Root Cause (3 bugs)

1. **`_find_next_lower_price` scanned placed/pending levels, not the grid ladder**:
   When sells at 61778 and 61927 filled, the counter-buy price was found by scanning
   `state.levels` for the nearest placed/pending level below. The only placed buy levels
   were at 58891, 59498, 60105 â€” so ALL three counter-buys got price 60105 (the highest
   placed buy). The function had no concept of the grid's actual price spacing.

2. **No sell-side price ladder stored**: The grid started with no BTC, so only buy levels
   were created (`buy_only` mode). The sell-side grid prices were never stored. When a buy
   filled and needed to place a counter-sell, `_find_next_higher_price` searched for
   placed/pending levels above â€” finding none (all sells were filled or cancelled).

3. **Budget imbalance**: With no BTC balance, `_calculate_grid_levels` allocated 100% of
   budget to buy side. The sell orders got only whatever tiny BTC dust existed (~â‚¬5 each).
   After those tiny sells filled, the counter-buys were equally tiny (~â‚¬5 each), creating
   a massive imbalance where most of the budget sat in buy orders that would never fill.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | NEW: `price_ladder: List[float]` field on `GridState` â€” stores full grid price ladder |
| `modules/grid_trading.py` | NEW: `_compute_full_ladder()` â€” derives complete grid prices from config (both buy AND sell side) |
| `modules/grid_trading.py` | NEW: `_get_price_ladder()` â€” returns stored ladder with config fallback |
| `modules/grid_trading.py` | FIXED: `_find_next_higher_price()` uses price_ladder instead of scanning level statuses |
| `modules/grid_trading.py` | FIXED: `_find_next_lower_price()` uses price_ladder instead of scanning level statuses |
| `modules/grid_trading.py` | Both find functions have fallback: calculate one grid step beyond ladder bounds |
| `modules/grid_trading.py` | `create_grid()` stores full ladder via `_compute_full_ladder()` |
| `modules/grid_trading.py` | `_rebalance_grid()` updates ladder on rebalance |
| `modules/grid_trading.py` | `_save_states()` / `_load_states()` persist/restore `price_ladder` |
| `bot_config_local.json` | `GRID_TRADING.num_grids`: 5â†’10 for better trade frequency with â‚¬184 budget |
| `data/grid_states.json` | Reset: old broken grid deleted, new grid created with proper ladder |

### Grid Config Applied
- Market: BTC-EUR, Range: Â±4% (8% total), 10 price levels, â‚¬184 budget
- 5 buy levels placed at different prices (â‚¬36.88/level)
- Full 10-price ladder stored (5 buy + 5 sell prices) for counter-order placement
- When a buy fills, counter-sell placed at correct next-higher ladder price (not arbitrary)

### Key Rules
1. **`price_ladder` must always contain ALL grid prices** (both buy and sell side), even when
   only buy orders are placed. This ensures counter-orders go to the correct price.
2. **Never scan `state.levels` status for counter-order pricing** â€” use the price ladder.
3. **Counter-sell price = next ladder price above the filled buy price** (not the nearest
   placed/pending level).

---

## #032 â€” Grid sells below cost: lost cost basis + phantom fills (2026-04-13)

### Symptom
ALL grid sells since the initial buy at â‚¬61,594 were below cost:
- Sell @ 61,196 â†’ loss -â‚¬0.43
- Sell @ 60,648 â†’ loss -â‚¬0.21
- Sell @ 61,254 â†’ loss -â‚¬0.10
- Sell @ 60,956 â†’ loss -â‚¬0.10

Grid reported `total_profit: +â‚¬1.57` when real P&L was **-â‚¬0.90** (â‚¬2.47 discrepancy).
Also: 72 phantom fills from simulation script contaminated `grid_fills_log.json`.

### Root Cause

1. **`last_buy_fill_price` was 0.0**: The buy at 61,594 occurred BEFORE FIX #031b added
   persistence of `last_buy_fill_price` to `_save_states()`. After bot restart, the field
   loaded as 0.0 (default) because it was never saved to disk. All subsequent rebalances
   had NO cost protection (`if state.last_buy_fill_price > 0` â†’ always false).

2. **No fallback for unknown cost basis**: When `last_buy_fill_price` was 0 and inventory
   existed, the grid had no mechanism to recover the cost. It placed sell orders below
   the actual buy price, guaranteeing losses on every sell.

3. **Phantom fills from simulation**: The `_grid_deep_sim.py` script (FIX #031b) wrote to
   the real `data/grid_fills_log.json` because `_log_fill` wasn't mocked in all test paths.
   72 phantom fills at impossible prices (81,450 and 91,125) contaminated the log.

4. **Profit calculation fallback showed fake profits**: `_estimate_buy_cost` fell through to
   `sell_price * 0.99` estimate when no cost basis was known, showing positive profit on
   what were actually losses.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | NEW: `_derive_cost_from_exchange()` queries Bitvavo trades API for last buy price |
| `modules/grid_trading.py` | `_load_states()`: derives cost from exchange when `last_buy_fill_price==0` + inventory |
| `modules/grid_trading.py` | `_rebalance_grid()`: derives cost before protection check; uses current price as last resort |
| `modules/grid_trading.py` | `start_grid()`: derives cost + blocks sell orders below cost basis |
| `modules/grid_trading.py` | `_estimate_buy_cost()`: exchange fallback instead of fake 0.99 estimate |
| `data/grid_states.json` | Corrected `last_buy_fill_price` to 61594, `total_profit` to -0.90 |
| `data/grid_fills_log.json` | Removed 72 phantom fills, corrected profit values on remaining 4 sells |

### Key Rules
1. **`last_buy_fill_price` must NEVER be 0 when inventory exists.** If it is, derive from Bitvavo.
2. **Simulations must use isolated file paths** (`GRID_FILLS_LOG`, `GRID_STATE_FILE`).
3. **ALL sell placements must check cost basis** â€” in `_rebalance_grid`, `start_grid`, AND counter-orders.

---

## #031 â€” Grid rebalance creates sells below buy cost basis (2026-04-12)

### Symptom
Grid bot bought BTC at â‚¬61,594 (07:30), then vol-adaptive rebalance triggered in the same cycle,
placing a sell at â‚¬61,196 â€” below the buy price. Sell filled at 07:49 for a loss of â‚¬0.43 but
the grid reported +â‚¬1.24 profit (â‚¬1.67 discrepancy).

### Root Cause (3 bugs)

1. **Vol-adaptive rebalance in same cycle as fill**: `auto_manage()` Step 3 processes fills, then
   Step 3b checks vol-adaptive and can trigger a `_rebalance_grid()` in the same call. The new
   grid levels are centered on current price, ignoring the cost basis of just-bought inventory.
   
2. **`_estimate_buy_cost()` uses grid level prices**: After rebalance, the function estimates
   cost from `_find_next_lower_price()` which returns new grid levels, not the actual buy price.
   For the sell at â‚¬61,196, it estimated cost at â‚¬59,360 (the new lower buy level), yielding
   fake +â‚¬1.24 profit when real cost was â‚¬61,594 = loss.

3. **No cost basis protection in `_rebalance_grid()`**: Rebalance blindly sets sell levels from
   grid math without checking if they're below the actual buy cost of held inventory.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` | Added `last_buy_fill_price` to `GridState` â€” tracks actual buy fill price for cost basis. |
| `modules/grid_trading.py` | Buy fill handler now sets `state.last_buy_fill_price = fill_price`. |
| `modules/grid_trading.py` | `auto_manage()` Step 3 tracks `fills_this_cycle`; Step 3b skips rebalance if fills occurred. |
| `modules/grid_trading.py` | `_rebalance_grid()` raises sell levels above cost basis (+ 2Ã— maker fee) when inventory held. |
| `modules/grid_trading.py` | `_estimate_buy_cost()` uses `last_buy_fill_price` when available instead of grid level estimate. |
| `data/grid_states.json` | Corrected `total_profit` from +â‚¬1.24 to -â‚¬0.43, added `last_buy_fill_price`. |

### Key Rule
**NEVER rebalance in the same cycle as a fill.** After a buy fill, the grid must protect
sell levels above the actual buy cost basis. Grid profit must use actual fill prices,
not grid level estimates.

---

## #031b â€” Grid deep analysis: 5 structural bugs (2026-04-12)

### Symptom
Ultra-deep simulation (`_grid_deep_sim.py`, 10 test scenarios) uncovered 5 bugs in
`modules/grid_trading.py` â€” confirmed by automated test failures.

### Bugs Found & Fixed

| # | Bug | Severity | Root Cause | Fix |
|---|-----|----------|-----------|-----|
| 1 | `_save_states()` doesn't persist `last_buy_fill_price` | CRITICAL | Field added to `GridState` and `_load_states()` but missing from `_save_states()` explicit dict | Added `'last_buy_fill_price': state.last_buy_fill_price` to save dict |
| 2 | `update_grid()` rebalance fires after fill in same call | CRITICAL | `update_grid()` has its own auto-rebalance check at end (separate from `auto_manage()`). After processing fills, it checked if price was out of range and rebalanced â€” same class of bug as #031 | Added `fills_occurred` flag; rebalance block guarded with `if config.auto_rebalance and not fills_occurred:` |
| 3 | `_find_next_higher/lower_price` returns stale level prices | MODERATE | After rebalances, old filled/cancelled levels remained in `state.levels`. Price search returned their prices (e.g. 57000 from cancelled level) instead of None | Filter to `l.status in ('placed', 'pending')` only |
| 4 | `base_balance` can go negative on sell fill | MODERATE | `state.base_balance -= actual_amount` without floor when sell amount exceeds balance (rounding/partial fills) | Changed to `state.base_balance = max(0.0, state.base_balance - actual_amount)` |
| 5 | `_estimate_buy_cost` uses wrong cost basis for paired trades | MODERATE | With multiple buy/sell pairs, `last_buy_fill_price` is the LAST buy price, not the specific paired buy. Sell at level paired with buy@59200 used cost from last buy@60500 â€” â‚¬1.30 error | Now looks up `sell_level.pair_level_id` â†’ finds paired buy level's `filled_price`. Falls back to `last_buy_fill_price` only if no pair found |

### Files Changed

| File | Change |
|------|--------|
| `modules/grid_trading.py` | `_save_states()`: added `last_buy_fill_price` to serialization dict |
| `modules/grid_trading.py` | `update_grid()`: added `fills_occurred` flag, defers rebalance when fills processed |
| `modules/grid_trading.py` | `_find_next_higher/lower_price()`: filter by `status in ('placed', 'pending')` |
| `modules/grid_trading.py` | Sell fill handler: `base_balance = max(0.0, base_balance - actual_amount)` |
| `modules/grid_trading.py` | `_estimate_buy_cost()`: paired buy level lookup via `pair_level_id` before fallback |
| `tests/test_grid_trading.py` | Added `load_freshest` patch for test isolation from LocalAppData |

### Key Rule
**`update_grid()` has its OWN rebalance check** â€” separate from `auto_manage()`.
Both paths must defer rebalance when fills occurred. Always check `pair_level_id`
for accurate per-trade cost basis.

---

## #001 â€” invested_eur desync after external buys (2026-03-25)

### Symptom
Dashboard showed wrong P&L for all open trades. Bitvavo showed:
- AVAX: +0.38% profit, bot dashboard showed +26.49%
- ALGO: -4.69% loss, bot showed +2.91%
- NEAR: -7.35% loss, bot showed -0.14%

The `invested_eur` field was too low (stuck at pre-external-buy values), making profits appear inflated.

### Root Cause (3 overlapping bugs)

1. **`derive_cost_basis` used `opened_ts` filter**: When the sync engine called
   `derive_cost_basis(bitvavo, market, amount, opened_ts=opened_ts)`, the `opened_ts`
   was set to the bot's restart/sync time (NOT the actual first buy). This caused
   the API to only return trades AFTER that timestamp, missing earlier buys that
   are part of the current position. Even though there was a fallback to fetch all
   trades, the result could still be wrong due to pagination issues.

2. **Three overlapping sync checks fought each other**: The sync engine had:
   - STALE check (50% threshold â€” almost never triggered)
   - Invested drift check (5% threshold â€” triggered but used wrong opened_ts)
   - CONSISTENCY GUARD (forced invested_eur = buy_price Ã— amount)
   These checks conflicted: if derive partially succeeded (updated buy_price but
   not invested_eur), the CONSISTENCY GUARD would propagate the wrong buy_price
   to invested_eur. If derive failed, the fallback set invested_eur = old_buy_price
   Ã— new_amount (wrong because old_buy_price didn't include the new buys).

3. **Dashboard `max()` hack masked the problem**: The dashboard used
   `invested = max(invested_eur, buy_price Ã— amount)` which showed the HIGHER value.
   When buy_price was wrong (too high), this overstated the cost basis, but in a
   different direction than the actual error. This made the displayed P&L look
   plausible even though the underlying data was wrong.

### Fix Applied

| File | Change |
|------|--------|
| `modules/cost_basis.py` | `derive_cost_basis()` now ALWAYS fetches full trade history (ignores `opened_ts`). The parameter is kept for API compat but never used as filter. |
| `bot/sync_engine.py` | Replaced 3 overlapping checks with ONE unified approach: re-derive on amount change, missing invested, periodic (4h), or >2% divergence. Uses `derive_cost_basis` as single source of truth. No `opened_ts` filter. |
| `trailing_bot.py` | GUARD 7 no longer blindly forces `invested_eur = buy_price*amount`. Only fills in when invested_eur is 0. Logs warning for >10% divergence. |
| `tools/dashboard_flask/app.py` | Removed `max()` hack. Uses `invested_eur` directly as it's now kept correct by sync engine. |
| `data/trade_log.json` | Fixed current data with correct values derived from Bitvavo transaction history. |

### Correct Values (from Bitvavo "Mijn assets" P&L on 2026-03-25)
- AVAX-EUR: cost_basis=â‚¬207.38, avg_price=â‚¬8.303
- ALGO-EUR: cost_basis=â‚¬250.62, avg_price=â‚¬0.07960
- NEAR-EUR: cost_basis=â‚¬259.81, avg_price=â‚¬1.1946

### Prevention
- `derive_cost_basis` always uses full order history (no date filter)
- Sync engine re-derives on ANY amount change (>0.1%)
- Periodic 4-hour re-derive as safety net
- Test: `tests/test_cost_basis_sync.py` validates the complete flow
- GUARD 7 in `validate_and_repair_trades` logs >10% divergence for manual review

### How to verify data is correct
Compare bot's invested_eur with Bitvavo's "Ongerealiseerde P&L":
```
bitvavo_cost_basis = saldo_eur + abs(unrealized_pnl_eur)  # when P&L is negative
bitvavo_cost_basis = saldo_eur - unrealized_pnl_eur       # when P&L is positive
```
Bot's invested_eur should be within ~1% of bitvavo_cost_basis (difference is fees).

---

## #002 â€” trading_sync.py filter silently drops positions on API glitch (2026-03-25)

### Symptom
After bot restart, AVAX-EUR disappeared from open_trades. The sync_debug.json showed
only 2 mapped markets (NEAR, ALGO) even though trade_log.json had 3 open trades.
Investigation revealed AVAX was actually sold at 19:23 by the old bot via trailing_tp
(sell_price=â‚¬8.37, profit=+â‚¬0.66), so the removal was correct in this case.
However, the code path that removed it is dangerous for transient API failures.

### Root Cause
`modules/trading_sync.py` has a `filtered_state` line that retains ONLY markets present
in the current Bitvavo balance API response:
```python
filtered_state = {m: e for m, e in open_state.items() if m in open_markets and open_markets[m] > 0}
```
This filter **bypasses** the `DISABLE_SYNC_REMOVE=True` config guard. If the Bitvavo
balance API has a transient failure (returns incomplete data), ALL positions missing
from the response are silently deleted from trade_log.json â€” even though they still
exist on the exchange.

Additionally, `modules/trading_sync.py` could only reconstruct missing positions from
`pending_saldo.json`, not from Bitvavo order history. If a position existed on Bitvavo
but wasn't in pending_saldo, it was silently ignored.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | `filtered_state` now respects `DISABLE_SYNC_REMOVE`. When True, positions missing from API are KEPT (not silently dropped). Logs a warning instead. |
| `modules/trading_sync.py` | Added auto-discover via `derive_cost_basis()`: if a Bitvavo balance has no matching open trade AND isn't in pending_saldo, the sync now derives cost basis from order history and creates the trade entry automatically. |

### Prevention
- With `DISABLE_SYNC_REMOVE=True` (default), positions are never silently dropped
- Auto-discover catches orphan positions via derive_cost_basis
- `bot/sync_engine.py` already had proper auto-discover; now `modules/trading_sync.py` does too

---

## #003 â€” Disable all time-based exits and loss sells (2026-03-25)

### Symptom
User does not want any trade to be closed based on time, and no trade may EVER be sold at a loss.

### What was disabled

| Mechanism | File | What it did | Action |
|-----------|------|-------------|--------|
| Hard stop-loss | `bot/trailing.py` `check_stop_loss()` | Sold at >15% loss | Function now always returns `(False, "disabled")` |
| Time stop-loss | `bot/trailing.py` `check_stop_loss()` | Sold after N days + loss | Same: always returns False |
| 48h exit | `bot/trailing.py` `check_advanced_exit_strategies()` | Sold at >3% profit after 48h | Code removed |
| 24h tighten | `bot/trailing.py` `check_advanced_exit_strategies()` | Set `time_tighten` flag after 24h | Code removed |
| time_tighten consumption | `bot/trailing.py` `calculate_stop_levels()` | Tightened trailing stop by 50% | Code removed |
| Hard SL sell path | `trailing_bot.py` ~L2852 | Executed sell on stop-loss trigger | Wrapped in `if False:` â€” unreachable |

### Still active (profit-gated, safe)
- Trailing TP: already has `real_profit <= 0` guard (blocks loss sells)
- Partial TP: only triggers at configured profit thresholds
- Volatility spike exit: requires >5% profit
- Auto-free slots: requires >0.5% profit
- Max age / max drawdown: both have loss-blocking guards

### Prevention
- `check_stop_loss()` is a no-op; even if config enables it, nothing happens
- Hard SL sell path is dead code (`if False:`)
- Tests updated to assert stop-loss never triggers

---

## #004 â€” dca_buys inflated to buy_order_count on synced positions (2026-03-26)

### Symptom
XRP-EUR showed `dca_buys=17` despite having zero DCA events executed. Same for NEAR and ALGO.

### Root Cause
`modules/sync_validator.py` `auto_add_missing_positions()` set `dca_buys = max(1, result.buy_order_count)` where `buy_order_count` is ALL historical buy orders for the market (including old closed positions). For XRP with 17+ historical buy orders, this set `dca_buys=17` on a brand-new position.

Additionally, `dca_max` was inflated to `max(config_dca_max, dca_buys)` â€” so with `dca_buys=17` and config `DCA_MAX_BUYS=17`, `dca_max=17`. This made all repair guards in `trailing_bot.py` (GUARD 1 and GUARD 5) ineffective because `dca_buys == dca_max`.

GUARD 5 used `min(max(dca_buys_now, actual_event_count), dca_max_now)` which NEVER reduced `dca_buys` below its current value â€” even when `dca_events` was empty.

### Fix Applied

| File | Change |
|------|--------|
| `modules/sync_validator.py` L296 | `dca_buys = 0` for newly synced positions (not `max(1, buy_order_count)`) |
| `modules/sync_validator.py` L315 | Same fix in FIFO fallback path |
| `modules/sync_validator.py` L413 | `dca_max` uses config value, not `max(config, dca_buys)` |
| `trailing_bot.py` GUARD 5 ~L893 | `correct_buys = min(actual_event_count, dca_max_global)` â€” now based on `dca_events` count, not `max(dca_buys, events)` |
| trade_log.json | Reset all open trades: `dca_buys=0`, `dca_max` from config |

### Key rule
`dca_buys` must ALWAYS equal `len(dca_events)`. A newly synced position has `dca_buys=0` because the bot hasn't executed any DCAs. `buy_order_count` from cost_basis includes historical orders from old positions and must NEVER be used as a DCA counter.

---

## #005 â€” DCA cascading: multiple buys at same price in one cycle (2026-03-26)

### Symptom
Bot executed 3 DCAs on NEAR-EUR and 2 on ALGO-EUR within 2 minutes, ALL at the same
market price (1.0563 / 0.0731). Burned through â‚¬175 of â‚¬178 balance. Each successive
DCA had decreasing EUR amounts (36â†’33â†’29) due to 0.9x multiplier but the price never
dropped further between buys.

### Root Cause
In `_execute_fixed_dca` and `_execute_dynamic_dca`, the DCA target price was calculated
from `buy_price` (weighted average entry price):
```python
target_price = float(trade.get("buy_price", current_price)) * (1 - step_pct)
```
After each DCA buy, `buy_price` is recalculated as a weighted average which DROPS (since
we're averaging down). The while loop immediately checks the next DCA level using this
new lower `buy_price`. Since the market price hasn't changed, and the new target is still
above market price, the next DCA triggers too. This cascades until `max_buys_per_iteration`
(which was 3) is exhausted.

Example with NEAR: buy_price=1.23, current=1.056, drop=2.5%:
- DCA1: target=1.23*0.975=1.20 â†’ 1.056 < 1.20 â†’ trigger. buy_price drops to ~1.15
- DCA2: target=1.15*0.975=1.12 â†’ 1.056 < 1.12 â†’ trigger. buy_price drops to ~1.10
- DCA3: target=1.10*0.975=1.07 â†’ 1.056 < 1.07 â†’ trigger. max_per_iter=3, stops.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_dca.py` `_execute_fixed_dca` | Target calculated from `last_dca_price` instead of `buy_price`. After each DCA, `last_dca_price` = current execution price, so next DCA needs genuine further drop. |
| `modules/trading_dca.py` `_execute_fixed_dca` | `dca_next_price` after buy also uses `last_dca_price` as reference |
| `modules/trading_dca.py` `_execute_dynamic_dca` | Same two fixes in the dynamic DCA path |
| `bot_config_local.json` | `DCA_MAX_BUYS_PER_ITERATION`: 3 â†’ 1 (extra safety â€” max 1 DCA per 25s bot cycle) |
| `tests/test_dca_buys_corruption.py` | Updated `test_multiple_dcas_in_one_call` to expect 1 DCA (not 3), fixed mock `**kwargs` |

### Key rule
DCA target must be based on `last_dca_price` (where the bot LAST bought), not `buy_price`
(weighted average). Each DCA should require `drop_pct` additional decline from the previous
DCA execution price. `DCA_MAX_BUYS_PER_ITERATION` should be 1 for safety.

---

## #006 â€” dca_buys=17 re-inflation + XRP invested_eur wrong (2026-03-27)

### Symptom
XRP-EUR dashboard showed 17 DCAs (only 0 real), +56.32% profit when the trade was
actually near breakeven or loss. All three open trades (XRP, NEAR, ALGO) had `dca_buys=17`.
XRP also showed `invested_eur=â‚¬41.86` while `buy_price*amount=â‚¬66.95` (37% too low).

### Root Cause (5 overlapping bugs)

1. **GUARD 5 NameError (`dca_max_now` undefined)**: `trailing_bot.py` GUARD 5 referenced
   `dca_max_now` which doesn't exist (should be `dca_max_global`). This crashed the guard
   silently, so it NEVER corrected inflated `dca_buys` values.

2. **sync_engine re-inflates dca_buys from buy_order_count**: `bot/sync_engine.py`'s 4-hour
   periodic re-derive set `dca_buys = buy_order_count - 1` from ALL historical orders
   (including old closed positions). With 17+ historical buys, this set dca_buys=16 or 17
   every 4 hours, undoing any correction from FIX #004.

3. **trade_store validation refused to reduce dca_buys**: `modules/trade_store.py`
   `_validate_and_fix_trade_data()` only increased dca_buys upward to match dca_events.
   When `dca_buys > dca_events`, it warned but KEPT the inflated value "to prevent
   duplicate DCA". For synced positions with 0 real DCAs, this preserved dca_buys=17.

4. **FIFO dust threshold too tight (1e-8)**: `modules/cost_basis.py` reset the position
   only when `pos_amount <= 1e-8`. Crypto dust from old positions (e.g., 0.01 XRP worth
   â‚¬0.01) exceeded this threshold, causing old position costs at cheap prices to bleed
   into the current position's cost basis. This made `invested_eur` too low.

5. **XRP invested_eur set from contaminated derive**: The FIFO included old cheap XRP buys
   from previous positions. Because old position sells left dust > 1e-8, the position
   never fully reset. New buys were averaged with old cheap costs, producing
   `invested_eur=â‚¬41.86` instead of the correct ~â‚¬66.95.

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` GUARD 5 | Fixed `dca_max_now` â†’ `dca_max_global` (NameError that silently crashed the guard) |
| `bot/sync_engine.py` | Removed dca_buys inflation from `buy_order_count`. Comment explains: dca_buys must ONLY change when bot executes a DCA buy |
| `modules/trade_store.py` | Validation: reduce dca_buys to 0 only when `dca_events` is empty. When events exist but fewer than dca_buys (events lost during sync/restart), keep dca_buys to prevent duplicate DCAs |
| `modules/cost_basis.py` | FIFO dust threshold: `pos_amount <= 1e-8` â†’ `pos_amount < 1e-6 or pos_cost < â‚¬1.00`. Catches crypto dust without affecting legitimate partial sells |
| `data/trade_log.json` | XRP: dca_buys 17â†’0, invested_eur â‚¬41.86â†’â‚¬66.95. NEAR/ALGO: dca_buys kept at 17 (legitimate, events partially lost) |

### Key Rules
- `dca_buys=0` when `dca_events` is empty (synced position, no bot-tracked DCAs)
- `dca_buys >= len(dca_events)` when events exist (events can be lost during sync/restart, keep dca_buys to prevent duplicate DCA)
- NEVER derive `dca_buys` from `buy_order_count` (includes old closed positions)
- `invested_eur` must be consistent with `buy_price * amount` (within fee margin)
- FIFO position reset must catch crypto dust (value < â‚¬1), not just amount < 1e-8

### Prevention
- GUARD 5 now works (NameError fixed) â€” resets dca_buys to 0 only when dca_events is empty
- When dca_events exist but fewer than dca_buys (events lost), dca_buys is preserved
- sync_engine no longer touches dca_buys during re-derives
- FIFO uses value-based dust detection (â‚¬1 threshold) to prevent old history contamination

---

## #007 â€” Event-sourced DCA state: dca_buys desync structurally impossible (2026-03-27)

### Symptom
dca_buys kept desyncing from actual DCA events due to 6+ different code paths
independently mutating the counter: `_execute_fixed_dca`, `_execute_dynamic_dca`,
`_execute_pyramid_up`, `sync_engine`, `trade_store` validation, and `trailing_bot`
GUARD 5. Each had slightly different logic, and bugs in one weren't caught by others.

### Root Cause
`dca_buys` was a standalone mutable counter updated independently in 6+ places.
`dca_events` was a separate list that should have been the source of truth but wasn't
â€” many code paths updated `dca_buys` without touching `dca_events` (e.g., pyramid_up),
or used `dca_buys` as the authoritative value when events were the ground truth.

### Fix Applied â€” Event-sourced architecture (`core/dca_state.py`)

| File | Change |
|------|--------|
| `core/dca_state.py` | **NEW MODULE**: Event-sourced DCA state. `dca_events` is the SINGLE source of truth. `dca_buys = len(dca_events)` ALWAYS. Provides `record_dca()` (only way to add DCA), `sync_derived_fields()` (recompute from events), `validate_events()`, `detect_untracked_buys()`. |
| `modules/trading_dca.py` `_execute_fixed_dca` | Replaced 20 lines of inline state mutations with `dca_state.record_dca()` call |
| `modules/trading_dca.py` `_execute_dynamic_dca` | Same: replaced inline mutations with `record_dca()` |
| `modules/trading_dca.py` `_execute_pyramid_up` | Now uses `add_dca()` + `record_dca()` (was directly assigning invested_eur and NOT creating events) |
| `trailing_bot.py` GUARD 0+1+4+5 | Replaced 4 separate DCA guards with single `sync_derived_fields()` call |
| `bot/sync_engine.py` | Added `sync_derived_fields()` call after every cost basis re-derive |
| `modules/trade_store.py` | Replaced manual Rule 4 (dca_buys consistency) with `sync_derived_fields()` call + fallback |
| `tests/test_dca_state.py` | **35 tests** covering: bot DCA, manual detection, restart recovery, cascading prevention, inflated dca_buys |

### Key Design Rules
- `record_dca()` is the **ONLY** way to add a DCA â€” it atomically: creates event, appends to events list, recomputes dca_buys, updates last_dca_price, calculates dca_next_price
- `sync_derived_fields()` is the **ONLY** validation â€” recomputes all derived DCA fields from events
- `dca_buys` stored in trade dict for backward compat, but always recomputed from events
- `_execute_pyramid_up` now records events (was silently skipping event creation)

### Prevention
- dca_buys desync is **structurally impossible**: only `record_dca()` can increment it, and it always equals `len(dca_events)`
- All 4 integration points (trading_dca, trailing_bot, sync_engine, trade_store) use the same module
- 35 unit tests cover all 5 scenarios from the user's DCA redesign specification

---

## #007b â€” dca_buys re-inflation via trading_sync.py cache + sync_engine dca_max (2026-06-24)

### Symptom
After #007 was deployed, XRP dca_buys immediately jumped back to 17. NEAR/ALGO also 17.

### Root Cause (2 missed code paths in #007)

1. **`modules/trading_sync.py` L609**: When a trade disappears and reappears (common during sync),
   `removed_cache` stores the old dca_buys. On restore, `max(current, cached)` was used â€” this
   only increases, so the inflated value 17 was restored from cache every time.

2. **`bot/sync_engine.py` L281**: `dca_max = max(inferred_max, dca_buys)` used dca_buys to inflate
   dca_max. When dca_buys was already 17 (from cache), dca_max also became 17.

3. **Snapshot save** in trading_sync.py saved the inflated dca_buys to cache, perpetuating the cycle.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` L609 | Replaced `max()` restore with `setdefault()` â€” cache value only used if no existing value |
| `modules/trading_sync.py` post-restore | Added `sync_derived_fields()` call after cache restore â€” events override any cached dca_buys |
| `modules/trading_sync.py` snapshot save | Snapshot now uses `len(dca_events)` as source of truth instead of raw `dca_buys` |
| `bot/sync_engine.py` L281 | Removed `max(..., dca_buys)` â€” dca_max now comes from `inferred_max` or config `DCA_MAX_BUYS`, never inflated by dca_buys |
| `data/trade_log.json` | Corrected: XRP dca_buys=0, NEAR=3, ALGO=2 (matching event counts) |

### Prevention
- `sync_derived_fields()` now called after EVERY trade state restoration (trading_sync cache restore)
- Cache snapshot stores event-derived count, not raw field
- dca_max no longer uses dca_buys as input (prevents circular inflation)

---

## #008 â€” Codebase-wide bug analysis: 10 fixes across 7 files (2026-03-27)

### Symptom
Deep analysis revealed 14 bugs (4 critical, 5 high, 3 medium, 2 low). Key risks: chunked sell counting API failures as filled, MAX_DRAWDOWN_SL selling at a loss, missing uuid import crashing DCA headroom, partial DCA state corruption on exception.

### Root Cause
Multiple independent issues accumulated across bot evolution:
1. `orders_impl.py` chunked sell treated `None` API response as full fill â†’ ghost tokens
2. `trailing_bot.py` MAX_DRAWDOWN_SL path had no profit guard â†’ could sell at a loss
3. `trading_dca.py` missing `import uuid` â†’ `_reserve_headroom()` crashed silently
4. `sync_engine.py` inferred `dca_max` from `buy_order_count` â†’ inflated (repeat of #004)
5. `config.py` RUNTIME_STATE_KEYS missing 4 keys â†’ leaked to config file on save
6. `trading_dca.py` record_dca/add_dca not wrapped in rollback â†’ partial state on exception
7. `trading_dca.py` pyramid-up used `buy_price * amount` as invested_eur fallback â†’ violated FIX #001
8. `trade_store.py` fallback dca_buys check missing `> dca_max` cap

### Fix Applied
1. **orders_impl.py** (L498-505): Chunked sell now treats non-dict API response as 0 fill
2. **trailing_bot.py** (L2357-2370): Added loss guard â€” blocks sell if `gross < invested`
3. **trading_dca.py** (L8): Added `import uuid`
4. **sync_engine.py** (L272-285): Replaced `buy_order_count` inference with `CONFIG['DCA_MAX_BUYS']`
5. **config.py**: Added `SYNC_ENABLED`, `SYNC_INTERVAL_SECONDS`, `MIN_SCORE_TO_BUY`, `OPERATOR_ID` to RUNTIME_STATE_KEYS
6. **trading_dca.py** (fixed + dynamic DCA): Wrapped `_ti_add_dca()` + `_ds_record()` in snapshot/rollback â€” rolls back `invested_eur`, `dca_buys`, `dca_events`, `buy_price`, `amount` on exception
7. **trading_dca.py** (pyramid-up): Changed to skip pyramid entirely if `invested_eur <= 0` instead of using `buy_price * amount` fallback
8. **trade_store.py**: Added `dca_buys > dca_max` cap in fallback validation path
9. **tests/test_dashboard_render.py**: Fixed `pnl_eur` from -5.0 to 5.0 (trailing badge requires profit)
10. **tests/test_grid_trading.py**: Fixed tolerance from 0.001 to 0.02 (accounts for price normalization)

### Prevention
- DCA state mutations now always have rollback on failure
- Cost basis rules (FIX #001) no longer violated by pyramid-up
- All 99 targeted tests pass after fixes

---

## #009 â€” FIFO cost basis: average-cost sell method inflated invested_eur (2026-04-06)

### Symptom
LINK-EUR `invested_eur` was â‚¬72.90 in the bot, but Bitvavo showed cost basis of â‚¬70.87 (2.86% off).
Other markets showed smaller but similar discrepancies (XRP 0.44%, NEAR 0.06%).

### Root Cause
`_compute_cost_basis_from_fills()` in `modules/cost_basis.py` used **average-cost** accounting
for sells, but the code comment called it "FIFO". With average cost, each sell deducts
`avg_cost Ã— sold_amount` from `pos_cost`. This means old expensive lots and new cheap lots
are blended together â€” residual cost from historical buy/sell cycles bleeds into the current
position's cost basis.

For LINK-EUR specifically:
- The trade history showed 12.028 LINK after processing all fills (93 fills)
- The actual Bitvavo balance was 9.426 LINK
- The 2.602 LINK phantom excess came from the very first buys (never sold in the API)
- With average-cost scaling (`avg_cost Ã— target_amount`), the expensive phantom lots
  inflated the cost: â‚¬7.73/unit Ã— 9.426 = â‚¬72.90
- True cost of the 2 actual buys: 5.468 @ 7.5967 + 3.958 @ 7.4102 = â‚¬71.06

### Fix Applied

| File | Change |
|------|--------|
| `modules/cost_basis.py` | Replaced average-cost sell deduction with **true FIFO lot tracking** using a `deque` of `[amount, cost_per_unit, timestamp, order_id]` lots. Sells now consume the oldest lots first. |
| `modules/cost_basis.py` | Added `_fifo_remove(lots, qty)` helper for FIFO lot consumption. |
| `modules/cost_basis.py` | When `pos_amount > target_amount + tolerance` (phantom holdings from missing API sells), FIFO-remove the excess oldest lots before computing `invested_eur`. |
| `modules/cost_basis.py` | `earliest_timestamp` and `buy_order_ids` now derived from **remaining** lots (not first buy ever). This correctly reflects when the current position started. |
| `tests/test_cost_basis_sync.py` | Added `TestFifoExcessRemoval` class with 3 tests: phantom holdings, no-excess, and FIFO sell ordering. |

### Result after fix
| | Before (avg cost) | After (FIFO) | Bitvavo |
|---|---|---|---|
| LINK invested_eur | â‚¬72.90 | â‚¬71.06 | â‚¬70.87 |
| Diff vs Bitvavo | 2.86% | 0.27% | â€” |

### Prevention
- True FIFO lot tracking ensures sells always consume oldest lots
- Phantom excess lots are FIFO-removed to match actual balance
- `earliest_timestamp` reflects the actual current position, not historical first buy
- 70 tests pass including 3 new FIFO-specific tests

---

## #010 â€” Dashboard portfolio value excluded BTC/ETH and used stale data (2026-04-06)

### Symptom
Dashboard showed "Account Waarde" as â‚¬795.39 while Bitvavo's real portfolio value was â‚¬820.90 â€” a â‚¬25.51 gap.

### Root Cause
Two overlapping issues:
1. **HODL assets (BTC, ETH) excluded from trade cards**: The dashboard card builder skips `HODL_SYMBOLS = ['BTC', 'ETH']`, so `total_current` (sum of card values) misses these assets (~â‚¬10.34 combined).
2. **Stale `account_overview.json` used as override**: `calculate_portfolio_totals()` read `data/account_overview.json` which is only updated when the bot is running. When the bot is stopped, prices become stale (2.5 days old in this case â†’ ~â‚¬19 price drift).
3. The dashboard never independently computed the real portfolio total from ALL Bitvavo balances Ã— live prices.

### Fix Applied

| File | Change |
|------|--------|
| `tools/dashboard_flask/app.py` | `calculate_portfolio_totals()` now computes real total from ALL Bitvavo balances Ã— live prices via `get_cached_balances()` + `get_live_price()`. Removed stale `account_overview.json` dependency. |
| `tools/dashboard_flask/services/portfolio_service.py` | `calculate_totals()` now computes real total from ALL balances Ã— live prices via `price_service.get_all_balances()` + `price_service.get_price()`. Removed `account_overview.json` dependency. |
| `tools/dashboard_flask/services/price_service.py` | Added `get_all_balances()` method with API call + file fallback to `data/sync_raw_balances.json`. |

### Prevention
- Dashboard now independently calculates portfolio total â€” never depends on bot-generated files for the headline number.
- All Bitvavo balances (BTC, ETH, and any other asset) are included in the total, matching what Bitvavo itself shows.
- Graceful fallback: if API fails, reads cached `sync_raw_balances.json`; if that fails too, falls back to `total_current + eur_balance`.

---

## #011 â€” Grid trading zombie states + budget_cfg reads wrong config (2026-04-07)

### Symptom
Grid trading enabled in config but no orders appeared on Bitvavo. No grid-related log entries.

### Root Cause
1. **Zombie grid states**: Old BTC-EUR and ETH-EUR grids in `data/grid_states.json` had `status: "running"` but `config.enabled: false` and all orders `cancelled`. These counted as "active" grids (`active_count = 2 >= max_grids`), blocking new grid creation.
2. **budget_cfg hardcoded path**: `_auto_create_grids()` read `BUDGET_RESERVATION` directly from `config/bot_config.json` instead of the merged `self.bot_config`. Local overrides (grid_pct, trailing_pct) were invisible to the grid module.

### Fix Applied
1. Cleared `data/grid_states.json` (backup in `data/grid_states_backup_old.json`) to allow fresh grid creation.
2. Changed `_auto_create_grids()` in `modules/grid_trading.py` to read `self.bot_config.get('BUDGET_RESERVATION', {})` instead of raw file read.
3. Added `max_grids: 1` to GRID_TRADING config (only BTC-EUR per roadmap â‚¬1000 phase).

### Prevention
- Grid module now uses merged config (respects local overrides).
- Explicit `max_grids` in config prevents default-value surprises.

---

## #012 â€” Grid cancelOrder fails without operatorId â†’ orphaned orders (2026-04-07)

### Symptom
User saw 11 open orders on Bitvavo instead of expected 9. Two orphaned BTC-EUR buy orders (â‚¬31.70 each at 55619 and 57998) remained on the exchange after a vol-adaptive rebalance from 5â†’18 grids.

### Root Cause
`GridManager._cancel_order()` called `self.bitvavo.cancelOrder(market, order_id)` without passing the `operatorId` parameter. The Bitvavo API returns HTTP 400 `"operatorId parameter is required"` when this is missing. During the vol-adaptive rebalance, the initial 2 grid orders could not be cancelled, and the code silently continued placing 9 new orders â€” leaving 11 total.

The `trailing_bot.py` monolith already passed `operatorId` correctly (`bitvavo.cancelOrder(market, orderId, operatorId=str(OPERATOR_ID))`), but the extracted grid module was missing it.

### Fix Applied

| File | Change |
|------|--------|
| `modules/grid_trading.py` `_cancel_order()` | Added `operator_id = self.bot_config.get('OPERATOR_ID')` and passed it as third arg to `cancelOrder()`. Also added error logging for API error responses. |
| Bitvavo exchange | Manually cancelled the 2 orphaned orders (ids `...676e96` and `...6770a3`) via API with operatorId. |

### Prevention
- `_cancel_order()` now always passes `operatorId` from config, matching `trailing_bot.py` convention.
- Error responses from cancel are now logged explicitly instead of silently returning False.

---

## #013 â€” Grid proportional budget: sell levels below minimum â†’ budget wasted (2026-04-07)

### Symptom
With 0.00041638 BTC (~â‚¬24.57) from earlier grid fills, the proportional budget split divided
sell budget equally across all sell levels (e.g. 9 levels Ã— â‚¬2.73 each). Bitvavo requires minimum
â‚¬5 per order, so ALL sell levels were skipped by the `amount_eur < 5.0` filter, wasting the entire
sell budget and deploying only ~â‚¬134 instead of ~â‚¬158.

### Root Cause
Proportional allocation divided `sell_budget_actual` by `levels_per_side` (total sell levels),
not by the number of sell levels that can actually meet the minimum order. When per-level amount
falls below â‚¬5, every sell level gets filtered out.

### Fix Applied
- `core/avellaneda_stoikov.py`: Calculate `affordable_sells = min(int(sell_budget_actual / 5.0), levels_per_side)`.
  Concentrate sell budget into `affordable_sells` levels closest to mid-price. Track `sells_placed` counter in
  the generation loop to stop generating sell levels beyond what's affordable.
- `modules/grid_trading.py` (static fallback): Same logic â€” `affordable_sells` count, `sells_placed` counter,
  skip sell levels once the affordable count is reached.

### Prevention
- Both A-S and static grid paths now calculate the maximum number of sell levels that meet the â‚¬5 minimum
  before allocating budget, preventing budget waste from below-minimum sell orders.

---

## #014 â€” invested_eur not updated after amount change in trading_sync + BTC grid ghost trade (2026-04-08)

### Symptom
1. **UNI-EUR**: Dashboard showed invested=â‚¬49.04 but actual cost basis was â‚¬91.22. A second buy
   (DCA) was executed on Bitvavo, the amount was updated but invested_eur was NOT recalculated.
2. **BTC-EUR**: Dashboard showed a ghost trade with invested=â‚¬0.03. This was BTC dust from the
   grid trading module being picked up as a regular trade by the sync engine.

### Root Cause

1. **`modules/trading_sync.py`** (startup sync): When live amount differs from trade_log amount,
   `entry["amount"] = live_amount` was updated but `invested_eur` was NOT recalculated via
   `derive_cost_basis()`. The amount-only update meant that by the time `bot/sync_engine.py`
   ran its 4-check reconciliation, Check 1 (amount changed) no longer triggered because the
   amount already matched. Check 4 (divergence >2%) should have caught it eventually but
   the bug persisted from the startup sync gap.

2. **`bot/sync_engine.py`**: The balance iteration loop excluded HODL markets but NOT grid-managed
   markets. BTC balance (from active grid orders) was detected as a new position and created
   as a dust trade entry.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | When amount changes >0.1%, now calls `derive_cost_basis()` to recalculate `buy_price`, `invested_eur`, `total_invested_eur` from Bitvavo order history |
| `bot/sync_engine.py` | Added grid market exclusion: reads `data/grid_states.json` for running/paused/initialized grids, skips those markets in the balance sync loop |
| `data/trade_log.json` | UNI-EUR: `invested_eur` corrected 49.04 â†’ 91.22 via `derive_cost_basis()` |
| `tests/test_sync_trailing_dca.py` | Fixed pre-existing test failure: added missing `fills_used` field to `_FakeCostBasis` dataclass |

### Prevention
- `trading_sync.py` now derives cost basis on ANY significant amount change, not just updating amount
- Grid-managed markets are excluded from sync_engine balance detection (same pattern as HODL exclusion)
- **Rule**: When updating `amount`, ALWAYS recalculate `invested_eur` via `derive_cost_basis()` â€” NEVER update amount alone

---

## #015 â€” highest_price lost on trade archival, blocking trailing analysis (2026-04-08)

### Symptom
All 354 archived trailing_tp trades have `highest_price=0` or missing. Without peak price data, it's impossible to backtest trailing stop configurations (activation %, trailing %, stepped levels) because we don't know how high each trade went before exit.

### Root Cause
`_finalize_close_trade()` in `trailing_bot.py` computed `max_profit_pct` from the open trade's `highest_price`, but never carried the raw `highest_price` value into the archived `closed_entry`. The metadata carry-forward loop only included `score`, `rsi_at_entry`, `volume_24h_eur`, `volatility_at_entry`, `opened_regime`, `macd_at_entry`, `sma_short_at_entry`, `sma_long_at_entry`, `dca_buys`, `tp_levels_done` â€” no trailing-related fields.

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` `_finalize_close_trade()` | Added `highest_price`, `trailing_activation_pct`, `base_trailing_pct` to the metadata carry-forward loop. These fields are now preserved in archived trades. |

### Prevention
- New trades closed after this fix will have `highest_price` in their archive record
- After 4-8 weeks of data accumulation, trailing settings can be properly backtested using real peak data
- **Rule**: When adding new per-trade tracking fields, always ensure they are included in `_finalize_close_trade()`'s metadata carry-forward list

---

## #016 â€” GUARD 6 NameError + trailing actief template + DCA reconcile SSOT (2026-04-09)

### Symptom
Three interrelated bugs:
1. **GUARD 6 NameError**: `name 'dca_events' is not defined` crash every ~60min in `validate_and_repair_trades()` for ALL open trades â€” invested_eur consistency check was silently failing.
2. **"Trailing actief" in loss**: Dashboard showed "TRAILING ACTIEF" badge for trades at -3% loss (e.g. UNI-EUR at -3.02%). Misleading â€” trailing should only show when trade is in profit.
3. **Missing DCA events**: UNI-EUR had 3 DCAs on Bitvavo but bot only tracked 2 â€” DCA #1 (2026-04-08 16:59, â‚¬41.94 @ â‚¬2.7037) was lost during a bot restart.

### Root Cause
1. **GUARD 6**: Line 888 of `trailing_bot.py` used bare variable name `dca_events` instead of `trade.get('dca_events', [])`. Python scope: the name was never defined in the function scope.
2. **Template bypass**: `portfolio.html` checked `card.trailing_activated` at 5 separate locations (lines 250, 304, 512, 1091, 1148) â€” this is a permanent boolean flag that stays True once set. The Python status computation at `app.py:907` correctly checked `live_price >= buy_price`, but the Jinja2 template bypassed it entirely.
3. **DCA loss**: Bot was restarted between DCA #1 and DCA #2 buys. DCA #1 was executed, but its event was never persisted because the bot wasn't running when it happened (executed by a previous instance that was killed).

### Fix Applied

| File | Change |
|------|--------|
| `trailing_bot.py` line 882-885 | **GUARD 6 NameError**: Replaced bare `dca_events` with `_guard6_events = trade.get('dca_events', []) or []` |
| `portfolio.html` 5 locations | **Trailing actief in loss**: Added `card.pnl >= 0` check to all 5 trailing_activated conditionals. Added "â¸ï¸ Trailing wacht (verlies)" state for trades that have trailing activated but are in loss. |
| `core/dca_reconcile.py` (NEW) | **Bitvavo SSOT reconcile engine**: Fetches all filled buy trades from Bitvavo, groups by orderId, compares with bot's dca_events, recovers missing events (source="reconcile"), corrects amount/invested_eur/buy_price, enriches existing events with order_id. |
| `trailing_bot.py` bot_loop + startup | Integrated reconcile: runs at startup and every 5 minutes in bot loop. Auto-saves if any repairs made. |
| `tests/test_dca_reconcile.py` (NEW) | 19 tests covering: fill grouping, no-fills, matched events, missing DCA recovery, partial recovery, fuzzy timestamp matching, financial corrections, dry-run mode, error handling, order_id enrichment, batch processing, market exclusion. |

### Prevention
- **SSOT**: Bitvavo order history is now the single source of truth. Every 5 minutes, the reconcile engine checks all open trades and recovers any missing DCA events automatically. Lost events during restarts are now self-healing.
- **Template safety**: All trailing_activated checks now require positive P&L. Added visual "wacht" state for clarity.
- **Variable scoping**: GUARD 6 now uses explicit `_guard6_` prefix to avoid variable name collisions in the large validate function.

---

## #017 â€” Grid vol-adaptive inflates num_grids 5â†’20, dead config keys (2026-04-09)

### Symptom
BTC-EUR grid had 11 open orders on Bitvavo instead of ~5 (user configured `num_grids: 5`). `investment_per_grid` and `max_total_investment` in config were hardcoded at 150 despite BUDGET_RESERVATION dynamic mode handling it.

### Root Cause
1. **Volatility-adaptive runaway**: `get_volatility_adjusted_num_grids()` in `core/avellaneda_stoikov.py` has `max_grids=20` default. With BTC's low hourly volatility (Ïƒâ‰ˆ0.0013), `vol_ratio = 0.26`, `adjusted = 5/0.26 â‰ˆ 19` â†’ capped at 20. The calling code in `auto_manage()` passed `config.num_grids` (the already-mutated state value) instead of the original user config.
2. **Dead config keys**: `investment_per_grid` and `max_total_investment` in GRID_TRADING are overridden when `BUDGET_RESERVATION.enabled=true, mode="dynamic"` â€” the actual investment is `total_account_value Ã— grid_pct / max_grids`. Hardcoded 150 was misleading.

### Fix Applied
1. `modules/grid_trading.py` Step 3b: Read `user_num_grids` from GRID_TRADING config (original value, not mutated state). Pass `max_grids=min(20, user_num_grids * 2)` to cap volatility scaling (5â†’max 10, not 5â†’20).
2. Removed `investment_per_grid` and `max_total_investment` from `bot_config_local.json` â€” BUDGET_RESERVATION dynamic mode provides the actual values.

### Prevention
- Volatility-adaptive now capped at 2Ã— user-configured num_grids. Uses original config as base, not the mutated grid state.
- Dead config keys removed to avoid confusion about what actually controls investment sizing.

---

## #018 â€” Dashboard shows all trades as "Externe Positie" after OneDrive revert (2026-04-09)

### Symptom
All 5 open trades (UNI, XRP, LINK, LTC, NEAR) periodically show as "EXTERN POSITIE" on the dashboard with +â‚¬0.00 P&L. Happens frequently and resolves after a few minutes when the bot saves again.

### Root Cause
Two-layer failure when OneDrive reverts `trade_log.json` to an older/empty version:

1. **`load_freshest()` preferred stale local mirror**: The local mirror in `%LOCALAPPDATA%` had a newer `_save_ts` but only contained BTC-EUR (from a partial save during a previous restart). Since it was "newer", `load_freshest` picked it over the OneDrive copy that had all 5 real trades. Result: `open_trades` only contained BTC-EUR (which is skipped as HODL), so all 5 trailing trades fell through to "external balance" detection.

2. **Dashboard `load_trades()` returned empty data**: When `data.get('open')` was falsy (empty dict), `_last_good_trades` was correctly NOT updated, but the empty data was still cached and returned. The fallback to `_last_good_trades` only triggered on exceptions, not on "valid but empty" responses.

### Fix Applied
| File | Change |
|------|--------|
| `core/local_state.py` | `load_freshest()` now checks data quality: if local is newer but has 0 open trades while OneDrive has real trades (and delta < 600s), uses OneDrive instead. Prevents stale mirror from winning. |
| `tools/dashboard_flask/app.py` | `load_trades()` fallback is now active: when trade_log returns 0 open trades but `_last_good_trades` has data, returns the last-known-good snapshot immediately instead of caching the empty data. |
| `tests/test_local_state.py` | 6 new tests for `load_freshest` data quality scenarios. |

### Prevention
- Dashboard never shows external positions when it previously had real trade data (last-known-good fallback).
- `load_freshest` uses data quality heuristic in addition to timestamps â€” empty local mirror can't override OneDrive with real trades.

---

## #019 â€” Dashboard deposit total wrong + stale grid orders (2026-04-09)

### Symptom
Dashboard "totaal gestort" showed â‚¬230 instead of â‚¬1620.01. Two conflicting deposit files existed:
- `config/deposits.json` (correct, API-synced, 18 deposits, â‚¬1620.01)
- `data/deposits.json` (wrong, 2 manual entries, â‚¬230)

Additionally, 2 stale BTC-EUR buy orders at â‚¬57,141 and â‚¬59,586 (from pre-FIX #017) were still live on Bitvavo but not tracked in `grid_states.json`.

### Root Cause
1. `data_service.py` loaded deposits from `data/deposits.json` (old manual file) instead of `config/deposits.json` (API-synced).
2. `app.py` performance stats (line 2681) also read from `data/deposits.json`.
3. `get_total_deposited()` in data_service used `deposits.get('entries', [])` for dict format â€” should be `deposits.get('deposits', [])`.
4. Old grid orders were orphaned when FIX #017 switched to new grid_states.json â€” the old orders were never cancelled.

### Fix Applied

| File | Change |
|------|--------|
| `tools/dashboard_flask/services/data_service.py` `load_deposits()` | Changed path from `data/deposits.json` to `config/deposits.json`. Changed default from `[]` to `{'total_deposited_eur': 0, 'deposits': []}`. Updated return type hint to `Dict`. |
| `tools/dashboard_flask/services/data_service.py` `get_total_deposited()` | Fixed dict branch to use `data.get('deposits', [])` instead of `data.get('entries', [])`. |
| `tools/dashboard_flask/app.py` line 2681 | Changed `PROJECT_ROOT / 'data' / 'deposits.json'` to `PROJECT_ROOT / 'config' / 'deposits.json'`. |
| `data/deposits.json` | Deleted (old manual file). |
| Bitvavo exchange | Cancelled 2 stale BTC-EUR buy orders at â‚¬57,141 and â‚¬59,586 via API. |
| `config/deposits.json` | Fresh sync from Bitvavo API: 18 deposits, â‚¬1620.01 (including new â‚¬150 deposit). |

### Prevention
- Single source of truth for deposits: `config/deposits.json` (API-synced). No manual `data/deposits.json`.
- Both `data_service.py` and `app.py` now read from the same path.

---

## #020 â€” Orphaned partial-TP positions adopted with wrong invested_eur (2026-04-09)

### Symptom
SOL-EUR appeared in open trades with `invested_eur = â‚¬12.02` instead of the real cost basis (~â‚¬77 Ã— 0.17 = ~â‚¬13.20). This is a recurring pattern: after a `partial_tp` sell, the remaining position loses its trade_log entry (restart, OneDrive revert, etc.), and when the sync engine re-adopts it, `derive_cost_basis` finds 0 orders (old fills purged from Bitvavo API), so it falls back to `amount Ã— current_ticker_price` â€” producing a tiny `invested_eur` unrelated to the real cost.

### Root Cause
Three code paths all had the same flaw â€” **no fallback to the trade archive** when `derive_cost_basis` fails:

1. `modules/sync_validator.py` `auto_add_missing_positions()`: Falls back to `amount Ã— current_price` when derive fails.
2. `bot/sync_engine.py` new-trade adoption: No invested_eur set at all when derive fails (later "corrected" by `get_true_invested_eur` to `buy_price Ã— amount` where `buy_price` = current ticker).
3. The trade archive **already contains** the partial_tp record with the correct `buy_price`, but nobody checked it.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trade_archive.py` | Added `recover_cost_from_archive(market, amount)` â€” looks up the most recent partial_tp entry (or last closed trade) in the archive and recovers `buy_price`, `invested_eur`, etc. |
| `modules/sync_validator.py` `auto_add_missing_positions()` | Added archive recovery fallback between FIFO/buy-trade fallbacks and the final current-price fallback. If derive_cost_basis AND FIFO both fail, checks the archive before falling back to ticker price. |
| `bot/sync_engine.py` new-trade branch | Added archive recovery when `derive_cost_basis` returns None or throws â€” before the trade is added with no `invested_eur`. |
| `tests/test_archive_recovery.py` | 6 new tests: partial_tp recovery, last-trade fallback, unknown market â†’ None, key completeness, empty archive, zero buy_price. |

### Prevention
- Orphaned partial-TP positions now get their original buy_price from the archive instead of the current ticker price.
- The fix is purely additive (new fallback layer) â€” existing derive_cost_basis logic is unchanged and still takes priority when it works.
- Archive data is persistent (never deleted) and backed up to `%LOCALAPPDATA%`, so it survives OneDrive reverts.

---

## #021 â€” Grid orders never placed: corrupt state + missing min base amount check (2026-04-09)

### Symptom
Grid trading enabled in config but no new orders placed on Bitvavo. BTC-EUR grid detected as "zombie" and paused. ETH-EUR grid had fake `test-order-123` order IDs causing 97.92% phantom stop-loss.

### Root Cause
1. **Corrupt grid_states.json**: BTC-EUR had `auto_created: false`, 8 levels with amounts ~0.00007 BTC (below Bitvavo min 0.0001 BTC), â‚¬50 investment. ETH-EUR had `order_id: "test-order-123"` â€” test data that leaked into production state. Origin: likely dashboard/manual creation with wrong params or state file corruption.
2. **Wrong Bitvavo API field name in `get_min_order_size()`**: `bot/api.py` looked for `minOrderSize`/`minOrderAmount` but Bitvavo API returns `minOrderInBaseAsset`. Result: `get_min_order_size()` always returned `0.0`, so min-size validation in `_place_limit_order()` was **never effective**. Orders with tiny amounts passed all checks and were rejected by Bitvavo API directly.
3. **No min BASE amount validation in level creation**: `_calculate_grid_levels()` only checked EUR value â‰¥ â‚¬5.50 per level, not Bitvavo's minimum base order size.
4. **A-S dynamic spacing path bypassed min base check**: The Avellaneda-Stoikov path created levels and returned early before the static path's min base validation. Levels with amounts below minimum were created unchecked.
5. **`load_freshest` restored old corrupt state from LocalAppData**: After clearing `data/grid_states.json`, `mirror_to_local`'s copy at `%LOCALAPPDATA%/BotConfig/state/grid_states.json` still had the corrupt state with higher `_save_ts`, so it was loaded as "freshest". Both files needed to be deleted.
6. **No recovery for never-started grids**: `is_broken` cleanup only matched `status in ('stopped', 'error')` â€” grids stuck in `initialized` or `placing_orders` were never cleaned up.
7. **`_cancel_order` passed operatorId positionally**: Caused cancel failures for corrupt ETH-EUR grid.
8. **Test fixture pollution**: Grid tests' `_save_states()` called `mirror_to_local()` writing to real `%LOCALAPPDATA%` path, contaminating production state with test data.

### Fix Applied

| File | Change |
|------|--------|
| `data/grid_states.json` + `%LOCALAPPDATA%` copy | Both deleted (backup in `grid_states_backup_corrupt_20260409.json`). Auto_manage creates fresh grids with correct dynamic budget params. |
| `bot/api.py` `get_min_order_size()` | Added `minOrderInBaseAsset` as primary field lookup (Bitvavo's actual field name). Kept legacy field names as fallback. |
| `bot/api.py` `get_amount_precision()`, `get_amount_step()` | Also fixed to check `minOrderInBaseAsset` before legacy `minOrderAmount`. |
| `utils.py` `get_min_order_size()` | Same: added `minOrderInBaseAsset` as primary lookup. |
| `modules/grid_trading.py` `_normalize_amount()` | Fixed fallback field from `minOrderAmount` to `minOrderInBaseAsset`. |
| `modules/grid_trading.py` `_calculate_grid_levels()` | Added min BASE amount check in BOTH A-S dynamic and static paths. Reduces `num_grids` until possible, returns empty if impossible. |
| `modules/grid_trading.py` `_auto_create_grids()` | Added per-candidate min base amount check. |
| `modules/grid_trading.py` `auto_manage()` Step 4 | Extended `is_broken` to also match `initialized`/`placing_orders` + 5-min grace. |
| `modules/grid_trading.py` `_cancel_order()` | Changed operatorId to keyword argument. |
| `tests/test_grid_trading.py` | Patched `mirror_to_local` in fixture to prevent test writes to production `%LOCALAPPDATA%`. |

### Prevention
- **Field name fix is the critical fix**: `get_min_order_size()` now correctly reads `minOrderInBaseAsset` from Bitvavo API, so all min-size checks actually work.
- Min base amount validation in both A-S and static paths prevents creating levels below minimum.
- Broken grid cleanup now catches all non-running states with 0 trades after 5-min grace.
- Test fixture mocks `mirror_to_local` to prevent test data contaminating production LocalAppData state.
- Both `data/` and `%LOCALAPPDATA%` copies must be cleared when resetting state (load_freshest picks the newer).
- This is the 3rd grid state corruption fix (see #011, #012). The test pollution was likely the origin of the corrupt state.

---

## #022 â€” Sell orders leave dust: place_sell uses min(trade, balance) instead of full balance (2026-04-09)

### Symptom
NEAR-EUR trailing TP sold 46.84 tokens but left 3.88 tokens (~â‚¬4.50) behind. Sync engine re-adopted this as a new trade, then auto_free_slot sold it, but the cycle repeated. Dashboard showed ghost NEAR positions.

### Root Cause
`place_sell()` in `bot/orders_impl.py` line 451 used `sell_amount = min(amount_base, available)`. When the Bitvavo balance (`available`) is larger than the trade-tracked amount (`amount_base`) â€” due to rounding, DCA differences, or partial fill accounting â€” only the trade amount is sold, leaving tokens behind.

### Fix Applied
| File | Change |
|------|--------|
| `bot/orders_impl.py` | Added `sell_all: bool = False` parameter to `place_sell()`. When `sell_all=True`, uses `max(amount_base, available)` to sell the full Bitvavo balance |
| `trailing_bot.py` | Pass-through `sell_all` in wrapper. All full-exit paths (trailing TP, max age, drawdown stop) now pass `sell_all=True` |
| `modules/trading_liquidation.py` | Auto-free-slot calls `place_sell(market, amount, sell_all=True)` |

Partial TP sells correctly keep `sell_all=False` (only sell a portion).

### Prevention
- Full exits always use `sell_all=True` â€” no dust left behind
- Partial sells remain conservative with `min()` to avoid over-selling

---

## #023 â€” SOL/NEAR invested_eur not reflecting sells and manual buys (2026-04-09)

### Symptom
SOL-EUR showed invested_eur=â‚¬24.06 but Bitvavo order history: 3 buys (â‚¬36.08) minus 2 sells (â‚¬14.10) = net â‚¬21.90. The 2 sells were not deducted from invested_eur. NEAR-EUR showed invested_eur=â‚¬4.50 after user manually bought â‚¬5.50 more â€” amount synced (8.60 tokens) but cost stayed at â‚¬4.50.

### Root Cause
The sync engine's immutability guard (`invested_sync.py`) only updates invested_eur when it's 0 or missing. Once set, it's never overwritten by normal sync cycles. This is correct for normal operation (prevents partial TP corruption) but means manual buys and untracked sells are never reconciled into invested_eur.

### Fix Applied
| File | Change |
|------|--------|
| `data/trade_log.json` | SOL-EUR: invested_eur 24.06â†’21.90, total_invested_eur 24.06â†’21.90 (FIFO-derived) |
| `data/trade_log.json` | NEAR-EUR: invested_eur 4.50â†’10.00, total_invested_eur 4.50â†’10.00, amount 4.72â†’8.60 (FIFO-derived) |

Values derived via `modules.cost_basis.derive_cost_basis()` using full FIFO lot tracking from Bitvavo order history.

### Prevention
- When users report cost basis discrepancies, run `derive_cost_basis()` to get the true FIFO value and compare with stored invested_eur
- The sync engine correctly protects invested_eur from overwrites; manual corrections need explicit FIFO verification

---

## #024 â€” Dust adoptâ†’fake-sellâ†’re-adopt infinite loop after chunked sells (2026-04-10)

### Symptom
After trailing TP sold LINK-EUR in chunks (â‚¬99.74 + â‚¬37.50), ~0.28 LINK (~â‚¬2.10) remained as dust. This dust was below Bitvavo's â‚¬5 minimum order size, making it unsellable. The sync engine adopted it as a new trade â†’ auto_free_slot tried to sell â†’ got "below_minimum_order_size" error but treated error dict as truthy (success) â†’ removed trade without selling â†’ sync re-adopted â†’ loop repeated 26 times creating 26 fake "auto_free_slot" closed trades.

### Root Cause
Three bugs combined:
1. **auto_free_slot truthy check**: `if ctx.place_sell(...)` â€” error dicts like `{"error": "below_minimum_order_size"}` are truthy in Python, so failed sells were treated as successes
2. **trading_sync.py no EUR threshold**: Unlike sync_engine.py (â‚¬5 threshold), trading_sync adopted ANY non-zero balance as a new trade
3. **Chunked sell leaves dust**: After chunks, remaining 0.28 LINK (â‚¬2.10) was below â‚¬5 min order and couldn't be sold or cleaned up

### Fix Applied
| File | Change |
|------|--------|
| `modules/trading_liquidation.py` | auto_free_slot: `sell_resp` checked for `error`/`errorCode` keys instead of truthy test |
| `modules/trading_sync.py` | Added â‚¬5 EUR dust threshold (SYNC_DUST_VALUE_EUR) before adopting new positions |
| `bot/orders_impl.py` | Chunked sell: attempts to sell remaining after all chunks; logs "unsellable dust" if below min order |
| `bot/orders_impl.py` | DUST_THRESHOLD_EUR default raised from â‚¬1 to â‚¬5 (matching Bitvavo's min order) |
| `trailing_bot.py` | Added `_cleanup_market_dust(m)` after trailing_tp, max_age, and drawdown exits |
| `data/trade_log.json` | Removed 26 fake LINK-EUR auto_free_slot closed trade entries |

### Prevention
- Sell response is now properly validated (not just truthy check)
- Sync won't adopt positions below â‚¬5 (Bitvavo's min order size)
- Post-exit dust sweep attempts cleanup immediately
- Chunked sells attempt to sell remaining dust; log clearly when below minimum

---

## #028 â€” Dashboard portfolio page crash: mixed timestamp types in sort (2026-04-10)

### Symptom
Dashboard `/portfolio` page threw `TypeError: '<' not supported between instances of 'float' and 'str'` when sorting closed trades.

### Root Cause
Some trades in the archive have `timestamp` as a string (e.g. from manual edits or older format), while most have it as a float. Python's `sorted()` can't compare `float < str`.

### Fix
Wrapped `x.get('timestamp', 0)` in `float(... or 0)` in all 3 sort locations:
- `tools/dashboard_flask/blueprints/main/routes.py` line 234
- `tools/dashboard_flask/app.py` line 1982
- `tools/dashboard_flask/app.py` line 3634

### Prevention
Always coerce archive field values to the expected type before comparison. Trade archive can contain mixed types from different code paths.

---

## #029 â€” Dashboard portfolio crash: datetime string timestamps can't be float-converted (2026-04-10)

### Symptom
Dashboard `/portfolio` page threw `ValueError: could not convert string to float: '2026-04-10 20:12:20'` when sorting closed trades.

### Root Cause
Fix #028 wrapped timestamps in `float()`, but some archive entries have `timestamp` as a datetime string (`'%Y-%m-%d %H:%M:%S'` format) which `float()` can't parse. Need a multi-format parser.

### Fix
Added `_ts_to_float(v)` helper in both `routes.py` and `app.py` that tries:
1. `float(v)` â€” handles numeric and numeric-string timestamps
2. `datetime.strptime(v, '%Y-%m-%d %H:%M:%S').timestamp()` â€” handles datetime strings
3. `datetime.fromisoformat(v).timestamp()` â€” handles ISO format strings
4. Falls back to `0.0` on any error

Applied in all 3 sort locations (same as #028).

### Files Changed
| File | Change |
|------|--------|
| `tools/dashboard_flask/blueprints/main/routes.py` | Added `_ts_to_float` helper + `datetime` import, used in sort |
| `tools/dashboard_flask/app.py` | Added `_ts_to_float` helper, used in 7 locations (sort, comparison, alerts, performance, reports) |
| `tools/dashboard_flask/services/portfolio_service.py` | Added `_ts_to_float` helper, used in PnL calculation |

### Prevention
Use `_ts_to_float()` for all timestamp sorting/comparison in the dashboard. Never assume timestamps are numeric â€” the trade archive contains mixed formats (unix epoch floats, datetime strings like `'2026-04-10 20:12:20'`, ISO format, None).

---

## #027 â€” Incomplete sells leaving dust: get_amount_step used minOrder instead of quantityDecimals (2026-04-10)

### Symptom
After every sell, residual balances ("dust") remained on Bitvavo. Examples:
- TAO-EUR: `normalize_amount(0.00913)` â†’ **0.0** (sell NOTHING, entire balance becomes dust)
- UNI-EUR: `normalize_amount(62.95)` â†’ **62.70** (0.25 UNI / ~â‚¬3.50 lost as dust)
- XRP-EUR: `normalize_amount(46.69)` â†’ **43.12** (3.56 XRP / ~â‚¬8.70 lost as dust)
- XLM-EUR: `normalize_amount(224.31)` â†’ **197.27** (27.04 XLM / ~â‚¬4.80 lost as dust)

This was the ROOT CAUSE behind all dust-related issues (#022â€“#026). Previous fixes only cleaned up
dust after the fact; this fix prevents dust from being created.

### Root Cause
`get_amount_step()` in `bot/api.py` returned `minOrderInBaseAsset` (Bitvavo's minimum order SIZE)
and used it as the amount STEP for normalization. `normalize_amount()` computed:
`floor(amount / step) * step` â€” treating the minimum order size as a divisor.

Example: TAO-EUR has `minOrderInBaseAsset = 0.02144965` (min order = 0.0214 TAO).
`floor(0.00913 / 0.02144965) = 0` â†’ normalized to **0.0** â†’ sell NOTHING.

UNI-EUR has `minOrderInBaseAsset = 1.84417788`:
`floor(62.95 / 1.84417788) = 34` â†’ `34 Ã— 1.844 = 62.70` â†’ **0.25 UNI lost as dust**.

The correct step is `10^(-quantityDecimals)` â€” e.g., for TAO (8 decimals) the step is 0.00000001,
not 0.02144965. Every single market was affected to varying degrees.

### Fix Applied

| File | Change |
|------|--------|
| `bot/api.py` | `get_amount_step()`: Returns `10^(-quantityDecimals)` instead of `minOrderInBaseAsset`. Now uses the actual decimal precision as the step size. |
| `bot/api.py` | `get_amount_precision()`: Checks `quantityDecimals` field first before falling back to counting decimals in `minOrderInBaseAsset`. |
| `bot/orders_impl.py` | `place_sell()` sell_all path: Uses direct `Decimal.quantize()` to `quantityDecimals` precision with `ROUND_DOWN` instead of `normalize_amount()`. Ensures full balance is sold with only decimal truncation. |
| `bot/orders_impl.py` | Post-sell sweep: After `sell_all` market sell, checks remaining balance and attempts to sell any remainder â‰¥ min order size. |
| `tests/test_bot_api.py` | 4 new tests in `TestAmountStepPrecision`: verifies step uses quantityDecimals for 8-dec and 6-dec markets, full-balance normalization, precision lookup. |

### Validation
End-to-end test with real Bitvavo API market data for 7 positions:
ALL markets normalize to exact balance with **ZERO DUST** (TAO, ALGO, UNI, XRP, XLM, LINK, LTC).

### Prevention
- `get_amount_step()` now uses `quantityDecimals` (the correct Bitvavo field for precision).
- `sell_all=True` bypasses `normalize_amount()` entirely, using direct Decimal truncation.
- Post-sell sweep catches any remaining balance after the primary sell.
- 4 dedicated regression tests verify step size calculation and full-balance normalization.

**CRITICAL RULE**: `minOrderInBaseAsset` is the MINIMUM ORDER SIZE, NOT an amount step/increment.
The amount step is always `10^(-quantityDecimals)`. Never confuse these two API fields.

---

## Template for new entries

```
## #NNN â€” Short description (YYYY-MM-DD)

### Symptom
What the user saw.

### Root Cause
Why it happened.

### Fix Applied
What was changed and where.

### Prevention
How we prevent recurrence.
```

---

## #026 â€” Dust trades never closed: wrong threshold + no auto-removal (2026-04-10)

### Symptom
TAO-EUR (â‚¬2.10) and ALGO-EUR (â‚¬0.05) remained as open trades indefinitely after partial sells.
They could not be sold (below Bitvavo â‚¬5 minimum) but still counted as open trades, blocking
new entries. Bot log showed `HARD STOP: already at max trades (5+0+0/5)` even though only 4
real trades existed. The `[DUST_SKIP]` log showed `drempel â‚¬0` â€” threshold was ~0 instead of 5.

### Root Cause
Two issues:
1. **Config `DUST_TRADE_THRESHOLD_EUR=0.5`** in `config/bot_config.json`. With 0.5, TAO (â‚¬2.10)
   was above threshold and NOT filtered as dust. Only ALGO (â‚¬0.05) was skipped. The `:.0f` format
   rounded 0.5 to "â‚¬0" in logs, making it look like zero.
2. **No auto-cleanup of dust trades**. Even when dust was correctly identified (ALGO), it was only
   skipped in the trailing management loop â€” the trade record remained in `open_trades` forever.
   `_cleanup_market_dust` skips markets that ARE in open_trades (`if market in S.open_trades: return`),
   so it couldn't help either.

### Fix Applied

| File | Change |
|------|--------|
| `%LOCALAPPDATA%/BotConfig/bot_config_local.json` | Set `DUST_TRADE_THRESHOLD_EUR=5.0` and `DUST_THRESHOLD_EUR=5.0` in local config (overrides base config's 0.5) |
| `bot/shared.py` | Changed default `DUST_TRADE_THRESHOLD_EUR` from 1.0 to 5.0 |
| `trailing_bot.py` | Added auto-cleanup: before per-trade loop, scan all open trades, close any with value < threshold via `_finalize_close_trade()` with `reason='dust_cleanup'` |
| `tests/test_dust_cleanup.py` | New test file: 7 tests for count_active_open_trades filtering, count_dust_trades, shared state default |

### Prevention
- Dust positions are now automatically closed (archived) each main loop cycle â€” they don't accumulate.
- Config threshold is 5.0 (matching Bitvavo minimum), set in local config that OneDrive can't revert.
- Shared state default is 5.0 so even without config, dust filtering uses the Bitvavo minimum.

---

## #025 â€” Dust positions counted as open trades, blocking new entries (2026-04-10)

### Symptom
Dust positions (< â‚¬5 EUR value) left after partial sells were treated as real open trades. This caused:
- Phantom "capacity full" when only a few real trades existed
- Main loop managing trailing/DCA on unsellable dust (wasteful)
- Correlation shield including dust in calculations
- Liquidation capacity checks blocked by dust

### Root Cause
Multiple places used `len(open_trades)` to count trades without filtering out dust positions below the â‚¬5 Bitvavo minimum order threshold.

### Fix Applied
1. **`trailing_bot.py` main loop** (L2260): Skip dust trades â€” compute EUR value, skip if < `DUST_TRADE_THRESHOLD_EUR`
2. **`trailing_bot.py` correlation shield** (L3042): Use `count_active_open_trades()` instead of `len(open_trades)`, skip dust in market iteration
3. **`modules/trading_liquidation.py`** (L166): Count only non-dust trades for capacity check
4. **`modules/trading_sync.py`** (L271): Count only non-dust trades for adoption room calculation

### Prevention
All capacity/counting checks now use value-based filtering against `DUST_TRADE_THRESHOLD_EUR` (default â‚¬5). Entry checks already used `count_active_open_trades()` which was correct â€” now all other paths are consistent.

---

## #030 â€” Grid market BTC-EUR adopted as trailing trade by trading_sync.py (2026-04-12)

### Symptom
BTC-EUR (a grid-managed market) appeared in `open_trades` in `data/trade_log.json` and was shown on the dashboard as a regular trailing trade. The trailing bot could potentially apply trailing stops, DCA, or dust cleanup on grid-managed assets, causing conflicts with the grid module.

### Root Cause
Two missing grid filters:
1. **`modules/trading_sync.py`**: Both `sync_open_trades()` and `reconcile_balances()` had zero grid market filtering. When these methods fetched Bitvavo balances, BTC (held by the grid module) was treated as a regular position and added to `open_trades`.
2. **`trailing_bot.py` main loop**: The per-trade management loop (trailing stops, DCA, dust cleanup) only skipped HODL markets but not grid markets. If a grid market was in `open_trades` (via the sync bug above), the trailing bot would actively manage it.

Note: `bot/sync_engine.py` already had grid filtering (FIX #014), but `modules/trading_sync.py` (the older parallel sync system) did not.

### Fix Applied

| File | Change |
|------|--------|
| `modules/trading_sync.py` | Added `_get_grid_markets()` helper. Both `sync_open_trades()` and `reconcile_balances()` now skip grid-managed markets when building the balance map. |
| `trailing_bot.py` | Added `grid_markets_set` alongside `hodl_markets_set`. The per-trade loop and dust cleanup loop now skip grid markets. |
| `data/trade_log.json` | Removed BTC-EUR from `open` trades (it was incorrectly added by the unfixed sync). |

### Prevention
- Grid markets are now excluded at ALL sync entry points: `bot/sync_engine.py`, `modules/trading_sync.py`, and `modules/sync_validator.py`.
- The trailing bot's management loop explicitly skips grid markets even if they somehow end up in `open_trades`.

