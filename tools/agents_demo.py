"""LangGraph + Ollama trade-review agent demo.

Loads recent closed trades, computes basic stats, and asks a local llama3.2:3b
model (via Ollama) to write a Dutch trade-review summary using a 3-node
LangGraph state machine: load -> analyse -> summarise.

Cost: 0 EUR (local model). No external API calls except Bitvavo data already
present on disk. Run:

    .\\.venv\\Scripts\\python.exe tools\\agents_demo.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, TypedDict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_ollama import ChatOllama  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402


class AgentState(TypedDict, total=False):
    closed: List[Dict[str, Any]]
    stats: Dict[str, Any]
    summary: str


def _load_trades(state: AgentState) -> AgentState:
    closed: List[Dict[str, Any]] = []
    tl_path = ROOT / "data" / "trade_log.json"
    arc_path = ROOT / "data" / "trade_archive.json"
    cutoff = time.time() - 7 * 86400
    for p in (tl_path, arc_path):
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            items = data.get("closed", []) if isinstance(data, dict) else (
                data.get("trades", []) if isinstance(data, dict) else data
            )
            if isinstance(data, dict) and "trades" in data:
                items = data["trades"]
            for t in items or []:
                if not isinstance(t, dict):
                    continue
                ts = float(t.get("timestamp") or t.get("opened_ts") or 0)
                if ts >= cutoff:
                    closed.append(t)
        except Exception:
            continue
    return {"closed": closed}


def _compute_stats(state: AgentState) -> AgentState:
    trades = state.get("closed", [])
    n = len(trades)
    wins = [t for t in trades if float(t.get("profit", 0) or 0) > 0]
    losses = [t for t in trades if float(t.get("profit", 0) or 0) <= 0]
    total_pnl = sum(float(t.get("profit", 0) or 0) for t in trades)
    by_reason: Dict[str, int] = {}
    for t in trades:
        r = str(t.get("reason", "unknown"))
        by_reason[r] = by_reason.get(r, 0) + 1
    biggest_win = max(trades, key=lambda x: float(x.get("profit", 0) or 0), default=None)
    biggest_loss = min(trades, key=lambda x: float(x.get("profit", 0) or 0), default=None)
    return {
        "stats": {
            "count": n,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
            "total_pnl_eur": round(total_pnl, 2),
            "by_reason": by_reason,
            "biggest_win": {
                "market": biggest_win.get("market") if biggest_win else None,
                "profit": round(float(biggest_win.get("profit", 0) or 0), 2) if biggest_win else 0,
            },
            "biggest_loss": {
                "market": biggest_loss.get("market") if biggest_loss else None,
                "profit": round(float(biggest_loss.get("profit", 0) or 0), 2) if biggest_loss else 0,
            },
        }
    }


def _summarise(state: AgentState) -> AgentState:
    stats = state.get("stats", {})
    llm = ChatOllama(model="llama3.2:3b", temperature=0.2, num_predict=350)
    prompt = (
        "Je bent een crypto-trading analist. Schrijf een KORTE Nederlandse review "
        "(max 8 regels) van de afgelopen 7 dagen op basis van deze stats. "
        "Geef 1 sterk punt en 1 verbeterpunt. Wees concreet, geen disclaimers.\n\n"
        f"Stats JSON:\n{json.dumps(stats, indent=2, ensure_ascii=False)}\n"
    )
    resp = llm.invoke(prompt)
    text = getattr(resp, "content", str(resp))
    return {"summary": str(text).strip()}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("load", _load_trades)
    g.add_node("analyse", _compute_stats)
    g.add_node("summarise", _summarise)
    g.add_edge(START, "load")
    g.add_edge("load", "analyse")
    g.add_edge("analyse", "summarise")
    g.add_edge("summarise", END)
    return g.compile()


def main() -> int:
    t0 = time.time()
    graph = build_graph()
    final = graph.invoke({})
    elapsed = round(time.time() - t0, 1)
    stats = final.get("stats", {})
    summary = final.get("summary", "")
    out = {
        "elapsed_s": elapsed,
        "stats": stats,
        "ai_summary": summary,
        "model": "llama3.2:3b (local Ollama)",
        "ts": int(time.time()),
    }
    out_path = ROOT / "data" / "agents_demo_output.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("=" * 60)
    print(f"LangGraph + Ollama demo finished in {elapsed}s")
    print("=" * 60)
    print(f"Trades (7d): {stats.get('count')}  win_rate: {stats.get('win_rate')}%  "
          f"PnL: {stats.get('total_pnl_eur')} EUR")
    print(f"By reason:   {stats.get('by_reason')}")
    print(f"Best:        {stats.get('biggest_win')}")
    print(f"Worst:       {stats.get('biggest_loss')}")
    print("-" * 60)
    print("AI summary:")
    print(summary)
    print("-" * 60)
    print(f"Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
