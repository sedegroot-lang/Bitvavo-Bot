"""Standalone shadow rotation evaluator — runs periodically.

Reads current open trades + recent market scoring data, evaluates whether
the bot *would* benefit from rotating capital, and logs to
data/shadow_rotation.jsonl. Never trades.

Run via: python scripts/run_shadow_rotation.py            (one-shot)
Or schedule via cron / Task Scheduler every 5-15 min.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bot import shadow_rotation
from modules.config import load_config


def _load_trade_log() -> dict:
    p = PROJECT_ROOT / "data" / "trade_log.json"
    if not p.exists():
        return {"open": {}}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"open": {}}


def _load_ai_insights() -> list:
    """Use AI supervisor's market insights as candidate source."""
    p = PROJECT_ROOT / "data" / "ai_suggestions.json"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        insights = doc.get("insights") or []
        return [
            {
                "market": i.get("market", "?"),
                "score": float(i.get("score", 0) or 0),
                "expected_pct": float(i.get("expected_pct", 0) or 0),
            }
            for i in insights if isinstance(i, dict) and i.get("market")
        ]
    except Exception:
        return []


def _load_current_prices(markets: list) -> dict:
    """Fetch current prices for given markets via Bitvavo."""
    if not markets:
        return {}
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from python_bitvavo_api.bitvavo import Bitvavo
        bv = Bitvavo({
            "APIKEY": os.getenv("BITVAVO_API_KEY", ""),
            "APISECRET": os.getenv("BITVAVO_API_SECRET", ""),
        })
        out = {}
        ticker = bv.tickerPrice({})
        for t in ticker if isinstance(ticker, list) else []:
            m = t.get("market")
            if m in markets:
                try:
                    out[m] = float(t.get("price", 0))
                except (TypeError, ValueError):
                    pass
        return out
    except Exception as e:
        print(f"[shadow] price fetch failed: {e}", file=sys.stderr)
        return {}


def _load_price_history_6h(markets: list) -> dict:
    """Best-effort: load last few candles per market for stillness check."""
    if not markets:
        return {}
    out = {}
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from python_bitvavo_api.bitvavo import Bitvavo
        bv = Bitvavo({
            "APIKEY": os.getenv("BITVAVO_API_KEY", ""),
            "APISECRET": os.getenv("BITVAVO_API_SECRET", ""),
        })
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - 6 * 3600 * 1000
        for m in markets:
            try:
                candles = bv.candles(m, "1h", {"start": start_ms, "end": end_ms, "limit": 8})
                # Bitvavo: [ts, open, high, low, close, volume]
                if isinstance(candles, list) and candles:
                    out[m] = [float(c[4]) for c in candles if len(c) >= 5]
            except Exception:
                continue
    except Exception:
        pass
    return out


def main() -> int:
    cfg = load_config()
    max_open = int(cfg.get("MAX_OPEN_TRADES", 4) or 4)
    log = _load_trade_log()
    open_trades = log.get("open") or {}
    if not isinstance(open_trades, dict):
        open_trades = {}

    candidates = _load_ai_insights()

    if not open_trades or not candidates:
        print(f"[shadow] open={len(open_trades)} candidates={len(candidates)} — nothing to evaluate")
        return 0

    open_markets = list(open_trades.keys())
    prices = _load_current_prices(open_markets)
    history = _load_price_history_6h(open_markets) if len(open_trades) >= max_open else {}

    suggestions = shadow_rotation.evaluate(
        open_trades, candidates,
        max_open_trades=max_open,
        current_prices=prices,
        price_history_6h=history,
        config=cfg,
    )
    print(f"[shadow] open={len(open_trades)}/{max_open} candidates={len(candidates)} suggestions={len(suggestions)}")
    if suggestions:
        for s in suggestions:
            print(f"  WOULD ROTATE: close {s['close_market']} (+{s['close_pnl_pct']}%, {s['close_age_hours']}h) "
                  f"-> open {s['candidate_market']} (score={s['candidate_score']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
