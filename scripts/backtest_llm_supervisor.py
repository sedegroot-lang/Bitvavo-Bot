"""
Backtest LLM/rule supervisor on historical closed trades.

Voor elke gesloten trade met volledige features:
1. Reconstrueer SupervisorContext uit de opgeslagen entry-features
2. Vraag verdict aan supervisor
3. Als veto → trade was nooit geopend; profit_avoided = -trade.profit
4. Als no veto → trade was uitgevoerd; profit_kept = trade.profit

Vergelijk:
  baseline_pnl  (alle trades)
  supervised_pnl (vetoed trades verwijderd)
  delta = supervised_pnl - baseline_pnl

Run:
    .\\.venv\\Scripts\\python.exe scripts\\backtest_llm_supervisor.py
    .\\.venv\\Scripts\\python.exe scripts\\backtest_llm_supervisor.py --backend ollama
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules.ai.llm_supervisor import SupervisorContext, evaluate_entry  # noqa: E402


def load_all_closed() -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    log_path = ROOT / "data" / "trade_log.json"
    arch_path = ROOT / "data" / "trade_archive.json"
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as f:
            d = json.load(f)
            trades.extend(d.get("closed", []) or [])
    if arch_path.exists():
        with arch_path.open("r", encoding="utf-8") as f:
            a = json.load(f)
            arr = a.get("trades", []) if isinstance(a, dict) else (a or [])
            trades.extend(arr)
    return trades


def has_features(t: Dict[str, Any]) -> bool:
    """Trade is bruikbaar voor backtest als ALLE feature-velden aanwezig zijn."""
    needed = ("rsi_at_entry", "macd_at_entry", "volatility_at_entry", "volume_24h_eur", "score")
    return all(t.get(k) is not None for k in needed)


def build_ctx(t: Dict[str, Any]) -> SupervisorContext:
    return SupervisorContext(
        market=str(t.get("market", "?")),
        rsi=float(t.get("rsi_at_entry") or 50.0),
        macd=float(t.get("macd_at_entry") or 0.0),
        regime=str(t.get("opened_regime") or "unknown"),
        volatility=float(t.get("volatility_at_entry") or 0.0),
        volume_24h_eur=float(t.get("volume_24h_eur") or 0.0),
        score=float(t.get("score") or 0.0),
    )


def fmt_eur(x: float) -> str:
    return f"€{x:+,.2f}"


def run(backend: str = "rule", verbose: bool = False) -> None:
    all_trades = load_all_closed()
    print(f"Loaded {len(all_trades)} closed trades from log + archive.")

    usable = [t for t in all_trades if has_features(t)]
    print(f"Trades with full feature set: {len(usable)}")
    if not usable:
        print("No usable trades — exit.")
        return

    baseline_pnl = sum(float(t.get("profit") or 0.0) for t in usable)
    baseline_winners = sum(1 for t in usable if (t.get("profit") or 0) > 0)
    baseline_losers = len(usable) - baseline_winners

    vetoed = []
    kept = []
    for t in usable:
        ctx = build_ctx(t)
        v = evaluate_entry(ctx, backend=backend)
        if v.veto:
            vetoed.append((t, v))
        else:
            kept.append((t, v))

    veto_pnl_avoided = sum(-(float(t.get("profit") or 0)) for t, _ in vetoed)
    kept_pnl = sum(float(t.get("profit") or 0) for t, _ in kept)
    delta = kept_pnl - baseline_pnl

    n_veto_correct = sum(1 for t, _ in vetoed if (t.get("profit") or 0) <= 0)  # vetoed losers = good
    n_veto_wrong = len(vetoed) - n_veto_correct  # vetoed winners = bad

    print()
    print("═══ BACKTEST RESULTS ═══")
    print(f"Backend          : {backend}")
    print(f"Trades evaluated : {len(usable)}")
    print(f"Vetoed           : {len(vetoed)}  (correct={n_veto_correct} losers, wrong={n_veto_wrong} winners)")
    print(f"Kept             : {len(kept)}")
    print()
    print(f"Baseline PnL     : {fmt_eur(baseline_pnl)}  (W:{baseline_winners} L:{baseline_losers})")
    print(f"Supervised PnL   : {fmt_eur(kept_pnl)}")
    print(f"Avoided losses   : {fmt_eur(veto_pnl_avoided)}")
    print(f"Delta vs baseline: {fmt_eur(delta)}  ({(delta/abs(baseline_pnl)*100) if baseline_pnl else 0:+.1f}%)")
    print()

    # Win-rate impact
    kept_winners = sum(1 for t, _ in kept if (t.get("profit") or 0) > 0)
    kept_losers = len(kept) - kept_winners
    base_wr = baseline_winners / len(usable) * 100 if usable else 0
    new_wr = kept_winners / len(kept) * 100 if kept else 0
    print(f"Win-rate baseline: {base_wr:.1f}%")
    print(f"Win-rate after   : {new_wr:.1f}%")
    print(f"Win-rate delta   : {new_wr - base_wr:+.1f} pp")
    print()

    # Veto precision/recall on losers
    total_losers = baseline_losers
    if total_losers:
        recall = n_veto_correct / total_losers * 100
        precision = (n_veto_correct / len(vetoed) * 100) if vetoed else 0.0
        print(f"Loser-recall     : {recall:.1f}%  (van alle losers werd dit % gevangen)")
        print(f"Veto-precision   : {precision:.1f}%  (van alle veto's was dit % terecht)")

    if verbose:
        print("\n--- vetoed trades sample ---")
        for t, v in vetoed[:10]:
            print(f"  {t.get('market')} profit={float(t.get('profit') or 0):+.2f} reason={v.reasoning}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--backend", default="rule", choices=["rule", "ollama"])
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    run(backend=args.backend, verbose=args.verbose)
