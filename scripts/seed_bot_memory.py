"""Seed bot_memory with the bot's institutional knowledge.

Run once to populate data/bot_memory.json with everything we already know
about how this specific bot performs, what works and what doesn't.

Re-runnable: dedup logic prevents duplicates.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.ai.bot_memory import get_memory  # noqa: E402

mem = get_memory()
USER = "bot"

facts = [
    # ── Hard config rules ──
    ("MIN_SCORE_TO_BUY blijft 7.0 — gebruiker wil dit nooit verlagen tenzij expliciet gevraagd", "config"),
    ("MAX_OPEN_TRADES minimum is 3, nooit lager (enforced in ai_supervisor + suggest_rules)", "config"),
    ("Config wijzigingen ALLEEN in %LOCALAPPDATA%/BotConfig/bot_config_local.json — OneDrive revert anders", "config"),
    ("invested_eur moet ALTIJD via derive_cost_basis uit Bitvavo order history (incl fees)", "config"),
    ("derive_cost_basis moet volledige trade history ophalen (geen opened_ts filter)", "config"),

    # ── Bot performance observations ──
    ("60d backtest: BOT-TAKER verliest -€62 (-26.5%/jr) op €1500 — current bot proxy verliest geld", "performance"),
    ("60d backtest: BOT-MAKER (limit orders 65% fill) verliest -€47 — maker fees helpen weinig", "performance"),
    ("60d backtest: B&H BTC/ETH 70/30 wint +€306 (+124%/jr) met -11.7% MaxDD — bull run periode", "performance"),
    ("60d backtest: DCA-BTC/ETH 70/30 wint +€35 (+14.4%/jr) met -1.5% MaxDD — laag risico, lage return", "performance"),
    ("60d backtest: ACC (Bandit + Self-Doubt) wint +€26 met -1.45% MaxDD (laagste DD) — bandit schakelt active arm uit naar 0%", "performance"),
    ("ACC self-doubt firede 4x in 60d, terecht — bot Sharpe was structureel negatief", "performance"),

    # ── Structural insights ──
    ("Conformal prediction supervisor levert geen edge op (alle backtests negatief, q_hat=0.6266)", "ml"),
    ("XGBoost signal filter (proba>=0.75) gaf +€0.17 over 20 trades = ruis, niet deployable", "ml"),
    ("Break-even win-rate met 0.25% taker fee + TP+1.5%/SL-2% = 64.3% — bot haalt 53-55%", "performance"),
    ("Trailing stops kappen winners af tijdens bull trends — root cause waarom B&H wint van bot", "strategy"),
    ("Bot heeft géén regime-bewustzijn over zichzelf — blijft kopen tijdens losing streak", "strategy"),

    # ── Architectural lessons ──
    ("trailing_bot.py is monolith ~4300 regels, nieuwe code in bot/ core/ modules/ packages", "architecture"),
    ("Bitvavo API calls via safe_call() met retries, circuit-breaker en 10s thread-timeout", "architecture"),
    ("Trade state mutations vereisen state.trades_lock RLock", "architecture"),
    ("Metrics emission moet non-blocking — wrap in try/except: pass, never raise", "architecture"),

    # ── Workflow rules ──
    ("Voor elke bug fix: lees docs/FIX_LOG.md eerst, log fix daarna", "workflow"),
    ("Na code change: run tests, dan commit + push naar GitHub", "workflow"),
    ("Health check: python scripts/helpers/ai_health_check.py", "workflow"),

    # ── Recent strategic decisions ──
    ("Adaptive Capital Council (ACC) = bandit allocator over 4 arms (Active/DCA/Grid/Cash)", "strategy"),
    ("ACC voorkomt verliezen door active arm uit te schakelen bij Sharpe<0 — werkt aantoonbaar in 60d backtest", "strategy"),
    ("Dashboard 'Realistische Verwachting' toont nu p25/median/p75 weekly PnL ipv extrapolatie", "dashboard"),
    ("Rule-supervisor draait in shadow mode (niet live), +€6.31 backtest gain", "strategy"),
]

print(f"Seeding {len(facts)} facts into {mem.path}")
added = 0
deduped = 0
for text, cat in facts:
    before = len(mem.get_all(USER))
    mem.add(text, user_id=USER, metadata={"category": cat})
    after = len(mem.get_all(USER))
    if after > before:
        added += 1
    else:
        deduped += 1

print(f"Added: {added}  Deduped: {deduped}")
print()
print("Stats:")
import json
print(json.dumps(mem.stats(), indent=2))
print()
print("Sample search 'trailing winners':")
for r in mem.search("trailing winners bull", user_id=USER, limit=3):
    print(f"  [{r['score']:.3f}] [{r['metadata'].get('category')}] {r['text']}")
print()
print("Sample search 'config MIN_SCORE':")
for r in mem.search("config MIN_SCORE", user_id=USER, limit=3):
    print(f"  [{r['score']:.3f}] [{r['metadata'].get('category')}] {r['text']}")
