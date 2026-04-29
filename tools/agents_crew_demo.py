"""CrewAI multi-agent trade-review demo (3 agents: Analyst, Risk Manager, Reporter).

Demonstrates how a small CrewAI crew can coordinate around a shared task:
1. Analyst computes win-rate / avg-profit / regime stats from closed trades.
2. Risk Manager reviews exposure vs. EUR reserve and flags concentration risk.
3. Reporter writes the final Dutch executive summary.

Uses local Ollama llama3.2:3b (cost: 0 EUR). Run:

    .\\.venv\\Scripts\\python.exe tools\\agents_crew_demo.py

NOTE: This is a SIDECAR demo — it does not touch trading state. Read-only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force CrewAI to use Ollama, skip telemetry
os.environ.setdefault("OPENAI_API_KEY", "ollama-local-dummy")
os.environ.setdefault("OPENAI_API_BASE", "http://127.0.0.1:11434/v1")
os.environ.setdefault("OPENAI_MODEL_NAME", "ollama/llama3.2:3b")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.llm import LLM  # noqa: E402


def _load_state() -> Dict[str, Any]:
    """Read read-only snapshot of bot state for the agents to reason about."""
    state: Dict[str, Any] = {"closed": [], "open": {}, "heartbeat": {}}
    log_path = ROOT / "data" / "trade_log.json"
    if log_path.exists():
        try:
            d = json.loads(log_path.read_text(encoding="utf-8"))
            state["closed"] = d.get("closed", [])[-30:]  # last 30 only
            state["open"] = d.get("open", {})
        except Exception:
            pass
    hb_path = ROOT / "data" / "heartbeat.json"
    if hb_path.exists():
        try:
            state["heartbeat"] = json.loads(hb_path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return state


def _stats_block(closed: List[Dict[str, Any]]) -> str:
    """Pre-compute basic numbers so the LLM doesn't have to do arithmetic."""
    if not closed:
        return "No closed trades available."
    profits = [float(t.get("profit", 0) or 0) for t in closed]
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    total_pnl = sum(profits)
    avg = total_pnl / len(profits) if profits else 0
    by_market: Dict[str, float] = {}
    for t in closed:
        m = str(t.get("market", "?"))
        by_market[m] = by_market.get(m, 0) + float(t.get("profit", 0) or 0)
    top_winners = sorted(by_market.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_losers = sorted(by_market.items(), key=lambda kv: kv[1])[:3]
    return (
        f"closed_trades={len(closed)}, wins={wins}, losses={losses}, "
        f"total_pnl_eur={total_pnl:.2f}, avg_pnl_eur={avg:.3f}\n"
        f"top_winners={top_winners}\ntop_losers={top_losers}"
    )


def _exposure_block(state: Dict[str, Any]) -> str:
    hb = state.get("heartbeat", {}) or {}
    open_n = hb.get("open_trades", len(state.get("open", {})))
    eur = hb.get("eur_balance", 0)
    expo = hb.get("open_exposure_eur", 0)
    tops = (hb.get("portfolio_snapshot") or {}).get("top_markets", {})
    return (
        f"open_trades={open_n}, eur_cash={eur}, exposure_eur={expo}\n"
        f"top_positions={tops}"
    )


def main() -> None:
    state = _load_state()
    stats = _stats_block(state["closed"])
    exposure = _exposure_block(state)

    print("=" * 60)
    print("CrewAI multi-agent trade review demo")
    print("=" * 60)
    print("Pre-computed stats:\n" + stats)
    print("Exposure snapshot:\n" + exposure)
    print("=" * 60)

    llm = LLM(
        model="ollama/llama3.2:3b",
        base_url="http://127.0.0.1:11434",
    )

    analyst = Agent(
        role="Crypto Trade Analyst",
        goal="Evaluate the closed-trade performance and identify patterns.",
        backstory=(
            "You are a quantitative analyst. You answer in concise Dutch bullet "
            "points. You never invent numbers — you only use the numbers given to you."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    risk = Agent(
        role="Risk Manager",
        goal="Assess portfolio concentration, EUR reserve and exposure ratio.",
        backstory=(
            "You are a conservative risk officer. You answer in Dutch and flag "
            "anything that breaches a 15% EUR-reserve rule or shows >50% "
            "concentration in a single market. Be brief."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    reporter = Agent(
        role="Executive Reporter",
        goal="Write a 5-line executive summary in Dutch combining analyst + risk findings.",
        backstory=(
            "You write crystal-clear Dutch summaries for a busy trader. "
            "Maximum 5 short bullets, no fluff."
        ),
        llm=llm,
        allow_delegation=False,
        verbose=False,
    )

    t1 = Task(
        description=(
            "Analyseer onderstaande trade-stats en geef 3 bullets met patronen "
            "(winrate, beste/slechtste markten, gemiddelde PnL).\n\n"
            f"STATS:\n{stats}"
        ),
        expected_output="3 bullets in het Nederlands met cijfers.",
        agent=analyst,
    )

    t2 = Task(
        description=(
            "Beoordeel de exposure-snapshot. Bereken cash-ratio = eur_cash / "
            "(eur_cash + exposure_eur). Flag als ratio < 15% of als 1 markt > 50% "
            "van exposure.\n\n"
            f"EXPOSURE:\n{exposure}"
        ),
        expected_output="2-3 bullets in het Nederlands met concrete cijfers + flags.",
        agent=risk,
    )

    t3 = Task(
        description=(
            "Schrijf een executive summary van max 5 bullets gebaseerd op de "
            "outputs van Analyst en Risk Manager. Eerste bullet = headline status. "
            "Laatste bullet = aanbeveling (HOLD / SCALE_DOWN / RESTORE_RESERVE)."
        ),
        expected_output="5 bullets in het Nederlands.",
        agent=reporter,
        context=[t1, t2],
    )

    crew = Crew(
        agents=[analyst, risk, reporter],
        tasks=[t1, t2, t3],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff()
    print("\n" + "=" * 60)
    print("FINAL EXECUTIVE SUMMARY")
    print("=" * 60)
    print(str(result))


if __name__ == "__main__":
    main()
